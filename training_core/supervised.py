"""Supervised challenger-selection helpers extracted from the legacy training file.

Phase 5 moves the supervised-classifier candidate selection logic behind an
explicit seam while keeping ``model_training`` as the stable import surface.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedShuffleSplit

from bioauth_model.scoring import classifier_training_summary
from evaluation_core.metrics import (
    LABEL_CONVENTION,
    LABEL_GENUINE,
    LABEL_INTRUDER,
    _binary_metrics,
    _false_accept_false_reject_rates as _bioauth_false_accept_false_reject_rates,
)

try:
    from lightgbm import LGBMClassifier

    USING_LIGHTGBM = True
except Exception:  # pragma: no cover - optional runtime extra
    LGBMClassifier = None
    USING_LIGHTGBM = False


CHALLENGER_SELECTION_VERSION = "phase9-challenger-v2"
SUPERVISED_SELECTION_HOLDOUT_FRACTION = 0.2
CHALLENGER_MIN_AUC_IMPROVEMENT = 0.02
CHALLENGER_MIN_F1_IMPROVEMENT = 0.01
CHALLENGER_MAX_FAR_DEGRADATION = 0.0
CHALLENGER_MAX_FRR_DEGRADATION = 0.0


def _ordered_unique_strings(values: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _select_supervised_validation_indices(
    y_clf: np.ndarray,
    sample_sources: List[str],
    *,
    holdout_fraction: float = SUPERVISED_SELECTION_HOLDOUT_FRACTION,
) -> tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    y_arr = np.asarray(y_clf, dtype=int)
    sources = [str(item or "unknown") for item in sample_sources]
    pos_sessions = _ordered_unique_strings([sources[idx] for idx, label in enumerate(y_arr.tolist()) if int(label) == 0])
    neg_sessions = _ordered_unique_strings([sources[idx] for idx, label in enumerate(y_arr.tolist()) if int(label) == 1])

    if len(pos_sessions) >= 2 and len(neg_sessions) >= 2:
        pos_holdout = max(1, int(round(len(pos_sessions) * holdout_fraction)))
        neg_holdout = max(1, int(round(len(neg_sessions) * holdout_fraction)))
        pos_holdout = min(pos_holdout, len(pos_sessions) - 1)
        neg_holdout = min(neg_holdout, len(neg_sessions) - 1)
        validation_sessions = set(pos_sessions[-pos_holdout:] + neg_sessions[-neg_holdout:])
        val_idx = np.asarray([idx for idx, session in enumerate(sources) if session in validation_sessions], dtype=int)
        train_idx = np.asarray([idx for idx, session in enumerate(sources) if session not in validation_sessions], dtype=int)
        if train_idx.size and val_idx.size and len(set(y_arr[train_idx].tolist())) >= 2 and len(set(y_arr[val_idx].tolist())) >= 2:
            split = {
                "method": "session_holdout",
                "holdout_fraction": float(holdout_fraction),
                "train_window_samples": int(train_idx.size),
                "validation_window_samples": int(val_idx.size),
                "train_session_count": int(len(set(sources[idx] for idx in train_idx.tolist()))),
                "validation_session_count": int(len(set(sources[idx] for idx in val_idx.tolist()))),
                "validation_sessions": sorted(validation_sessions),
            }
            return train_idx, val_idx, split

    splitter = StratifiedShuffleSplit(n_splits=1, test_size=holdout_fraction, random_state=42)
    train_idx, val_idx = next(splitter.split(np.zeros((len(y_arr), 1), dtype=float), y_arr))
    split = {
        "method": "stratified_shuffle_split",
        "holdout_fraction": float(holdout_fraction),
        "train_window_samples": int(len(train_idx)),
        "validation_window_samples": int(len(val_idx)),
        "train_session_count": int(len(set(sources[idx] for idx in train_idx.tolist()))),
        "validation_session_count": int(len(set(sources[idx] for idx in val_idx.tolist()))),
        "validation_sessions": sorted({sources[idx] for idx in val_idx.tolist()}),
    }
    return np.asarray(train_idx, dtype=int), np.asarray(val_idx, dtype=int), split


def _make_supervised_classifier(
    family: str,
    *,
    cpu_parallel_jobs: Callable[[], int],
    using_lightgbm: bool = USING_LIGHTGBM,
    lgbm_classifier: Any = LGBMClassifier,
    random_forest_classifier: Any = RandomForestClassifier,
):
    normalized = str(family or "").strip().lower()
    parallel_jobs = int(cpu_parallel_jobs())
    if normalized == "lightgbm" and using_lightgbm and lgbm_classifier is not None:
        params = {
            "n_estimators": 220,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "subsample": 0.9,
            "colsample_bytree": 0.9,
            "reg_lambda": 0.1,
            "random_state": 42,
            "n_jobs": parallel_jobs,
        }
        return lgbm_classifier(**params), params
    params = {
        "n_estimators": 320,
        "max_depth": None,
        "min_samples_leaf": 2,
        "class_weight": "balanced_subsample",
        "random_state": 42,
        "n_jobs": parallel_jobs,
    }
    return random_forest_classifier(**params), params


def _classifier_probability_values(candidate: Any, X_val: np.ndarray) -> np.ndarray:
    if hasattr(candidate, "predict_proba"):
        probs = np.asarray(candidate.predict_proba(X_val), dtype=float)
        if probs.ndim == 2 and probs.shape[1] >= 2:
            return probs[:, 1]
        if probs.ndim == 2 and probs.shape[1] == 1:
            return probs[:, 0]
    if hasattr(candidate, "decision_function"):
        raw = np.asarray(candidate.decision_function(X_val), dtype=float)
        return 1.0 / (1.0 + np.exp(-raw))
    preds = np.asarray(candidate.predict(X_val), dtype=float)
    return preds.astype(float)


def _false_accept_false_reject_rates(*, tn: int, fp: int, fn: int, tp: int) -> tuple[float, float]:
    """Training path wrapper for the shared BioAuth FAR/FRR convention.

    Labels are fixed across evaluation and supervised selection:
    LABEL_GENUINE=0, LABEL_INTRUDER=1, and higher classifier scores are
    more suspicious. Therefore FN means an intruder was accepted and belongs
    to FAR, while FP means a genuine sample was rejected and belongs to FRR.
    """

    return _bioauth_false_accept_false_reject_rates(tn=tn, fp=fp, fn=fn, tp=tp)


def _evaluate_supervised_candidate(candidate: Any, X_val: np.ndarray, y_val: np.ndarray) -> Dict[str, Any]:
    probs = _classifier_probability_values(candidate, X_val)
    preds = (probs >= 0.5).astype(int)
    metrics = _binary_metrics(y_val, preds, probs)
    auc = metrics.get("auc")
    f1 = float(metrics.get("f1") or 0.0)
    precision = float(metrics.get("precision") or 0.0)
    selection_score = float(auc if auc is not None else (0.7 * f1 + 0.3 * precision))
    metrics.update(
        {
            "label_convention": dict(LABEL_CONVENTION),
            "decision_threshold": 0.5,
            "selection_score": selection_score,
            "validation_window_samples": int(len(y_val)),
        }
    )
    return metrics


def _challenger_respects_error_rate_guards(
    baseline: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    max_far_degradation: float = CHALLENGER_MAX_FAR_DEGRADATION,
    max_frr_degradation: float = CHALLENGER_MAX_FRR_DEGRADATION,
) -> bool:
    baseline_far = float(baseline.get("far") or 0.0)
    challenger_far = float(challenger.get("far") or 0.0)
    baseline_frr = float(baseline.get("frr") or 0.0)
    challenger_frr = float(challenger.get("frr") or 0.0)
    return bool(
        challenger_far <= baseline_far + max_far_degradation
        and challenger_frr <= baseline_frr + max_frr_degradation
    )


def _select_primary_supervised_family(
    candidate_scores: Mapping[str, Mapping[str, Any]],
    *,
    challenger_respects_error_rate_guards_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], bool] | None = None,
    min_auc_improvement: float = CHALLENGER_MIN_AUC_IMPROVEMENT,
    min_f1_improvement: float = CHALLENGER_MIN_F1_IMPROVEMENT,
) -> str:
    baseline = dict(candidate_scores.get("random_forest") or {})
    challenger = dict(candidate_scores.get("lightgbm") or {})
    if not challenger:
        return "random_forest"
    guard_fn = challenger_respects_error_rate_guards_fn or (lambda base, cand: _challenger_respects_error_rate_guards(base, cand))
    if not guard_fn(baseline, challenger):
        return "random_forest"
    baseline_auc = baseline.get("auc")
    challenger_auc = challenger.get("auc")
    if baseline_auc is not None and challenger_auc is not None:
        if float(challenger_auc) >= float(baseline_auc) + min_auc_improvement:
            return "lightgbm"
        return "random_forest"
    baseline_f1 = float(baseline.get("f1") or 0.0)
    challenger_f1 = float(challenger.get("f1") or 0.0)
    if challenger_f1 >= baseline_f1 + min_f1_improvement:
        return "lightgbm"
    return "random_forest"


class _NullHeartbeat:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def train_supervised_classifier_candidates(
    X_pos: np.ndarray,
    X_neg: np.ndarray,
    *,
    pos_sample_sources: List[str],
    neg_sample_sources: List[str],
    minimum_negative_samples: int,
    progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]] = None,
    emit_progress_fn: Callable[[Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]], float, str, Optional[Mapping[str, Any]]], None] | None = None,
    heartbeat_factory: Callable[[Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]], float, str, Optional[Mapping[str, Any]]], Any] | None = None,
    classifier_training_summary_fn: Callable[[int, int], Dict[str, Any]] = classifier_training_summary,
    select_validation_indices_fn: Callable[[np.ndarray, List[str]], tuple[np.ndarray, np.ndarray, Dict[str, Any]]] | None = None,
    make_supervised_classifier_fn: Callable[[str], tuple[Any, Dict[str, Any]]] | None = None,
    evaluate_candidate_fn: Callable[[Any, np.ndarray, np.ndarray], Dict[str, Any]] | None = None,
    select_primary_family_fn: Callable[[Mapping[str, Mapping[str, Any]]], str] | None = None,
    using_lightgbm: bool = USING_LIGHTGBM,
    lgbm_classifier: Any = LGBMClassifier,
    selection_version: str = CHALLENGER_SELECTION_VERSION,
    min_auc_improvement: float = CHALLENGER_MIN_AUC_IMPROVEMENT,
    min_f1_improvement: float = CHALLENGER_MIN_F1_IMPROVEMENT,
    max_far_degradation: float = CHALLENGER_MAX_FAR_DEGRADATION,
    max_frr_degradation: float = CHALLENGER_MAX_FRR_DEGRADATION,
) -> tuple[Any | None, Dict[str, Any]]:
    def _emit(fraction: float, detail_key: str, params: Optional[Mapping[str, Any]] = None) -> None:
        if emit_progress_fn is not None:
            emit_progress_fn(progress_callback, float(fraction), str(detail_key), params)

    def _heartbeat(fraction: float, detail_key: str, params: Optional[Mapping[str, Any]] = None):
        if heartbeat_factory is None:
            return _NullHeartbeat()
        return heartbeat_factory(progress_callback, float(fraction), str(detail_key), params)

    select_validation_indices_fn = select_validation_indices_fn or (
        lambda y_clf, sample_sources: _select_supervised_validation_indices(
            y_clf,
            sample_sources,
            holdout_fraction=SUPERVISED_SELECTION_HOLDOUT_FRACTION,
        )
    )
    make_supervised_classifier_fn = make_supervised_classifier_fn or (
        lambda family: _make_supervised_classifier(
            family,
            cpu_parallel_jobs=lambda: max(1, int(os.cpu_count() or 1) - 1),
            using_lightgbm=using_lightgbm,
            lgbm_classifier=lgbm_classifier,
            random_forest_classifier=RandomForestClassifier,
        )
    )
    evaluate_candidate_fn = evaluate_candidate_fn or _evaluate_supervised_candidate
    select_primary_family_fn = select_primary_family_fn or (
        lambda scores: _select_primary_supervised_family(
            scores,
            min_auc_improvement=min_auc_improvement,
            min_f1_improvement=min_f1_improvement,
            challenger_respects_error_rate_guards_fn=lambda baseline, challenger: _challenger_respects_error_rate_guards(
                baseline,
                challenger,
                max_far_degradation=max_far_degradation,
                max_frr_degradation=max_frr_degradation,
            ),
        )
    )

    classifier_info = classifier_training_summary_fn(len(X_neg), minimum_negative_samples)
    if not classifier_info["classifier_enabled"]:
        _emit(0.74, "training_detail_training_challenger_classifier_skipped")
        _emit(0.82, "training_detail_final_classifier_fit_skipped")
        classifier_info.update(
            {
                "classifier_family": None,
                "supervised_classifier": {
                    "selection_version": selection_version,
                    "enabled": False,
                    "selected_family": None,
                    "baseline_family": "random_forest",
                    "challenger_family": "lightgbm" if using_lightgbm else None,
                    "selection_reason": "Trusted negative windows were insufficient for supervised classifier training.",
                    "head_to_head": {},
                },
            }
        )
        return None, classifier_info

    X_clf = np.vstack([X_pos, X_neg])
    y_clf = np.concatenate([np.full(len(X_pos), LABEL_GENUINE, dtype=int), np.full(len(X_neg), LABEL_INTRUDER, dtype=int)])
    sample_sources = [str(item or "unknown") for item in list(pos_sample_sources) + list(neg_sample_sources)]
    train_idx, val_idx, validation_split = select_validation_indices_fn(y_clf, sample_sources)

    families = ["random_forest"]
    if using_lightgbm and lgbm_classifier is not None:
        families.append("lightgbm")

    candidate_scores: Dict[str, Dict[str, Any]] = {}
    hyperparameters: Dict[str, Dict[str, Any]] = {}
    family_progress = {
        "random_forest": (0.66, "training_detail_training_baseline_classifier"),
        "lightgbm": (0.74, "training_detail_training_challenger_classifier"),
    }
    for family in families:
        fraction, detail_key = family_progress.get(family, (0.66, "training_detail_training_baseline_classifier"))
        candidate, params = make_supervised_classifier_fn(family)
        _emit(fraction, detail_key, {"classifier_family": family})
        with _heartbeat(fraction, detail_key, {"classifier_family": family}):
            candidate.fit(X_clf[train_idx], y_clf[train_idx])
        metrics = evaluate_candidate_fn(candidate, X_clf[val_idx], y_clf[val_idx])
        metrics["family"] = family
        metrics["available"] = True
        hyperparameters[family] = dict(params)
        candidate_scores[family] = metrics

    if "lightgbm" not in families:
        _emit(0.74, "training_detail_training_challenger_classifier_skipped")

    selected_family = select_primary_family_fn(candidate_scores)
    selected_model, selected_params = make_supervised_classifier_fn(selected_family)
    _emit(0.82, "training_detail_final_classifier_fit", {"classifier_family": selected_family})
    with _heartbeat(0.82, "training_detail_final_classifier_fit", {"classifier_family": selected_family}):
        selected_model.fit(X_clf, y_clf)

    selection_reason = "Selected baseline random_forest because it matched or outperformed the challenger on the validation split, or because the challenger failed the FAR/FRR guardrails."
    if selected_family == "lightgbm":
        selection_reason = "Selected challenger lightgbm because it cleared the meaningful-improvement threshold and did not degrade FAR/FRR on the validation split."

    classifier_info.update(
        {
            "classifier_family": selected_family,
            "supervised_classifier": {
                "selection_version": selection_version,
                "enabled": True,
                "selected_family": selected_family,
                "baseline_family": "random_forest",
                "challenger_family": "lightgbm" if using_lightgbm else None,
                "selection_reason": selection_reason,
                "selection_metric": "auc_with_far_frr_guard_then_f1_fallback",
                "selection_constraints": {
                    "min_auc_improvement": float(min_auc_improvement),
                    "min_f1_improvement": float(min_f1_improvement),
                    "max_far_degradation": float(max_far_degradation),
                    "max_frr_degradation": float(max_frr_degradation),
                },
                "validation_split": validation_split,
                "head_to_head": candidate_scores,
                "hyperparameters": hyperparameters,
                "selected_hyperparameters": dict(selected_params),
            },
        }
    )
    return selected_model, classifier_info


__all__ = [
    "CHALLENGER_MAX_FAR_DEGRADATION",
    "CHALLENGER_MAX_FRR_DEGRADATION",
    "CHALLENGER_MIN_AUC_IMPROVEMENT",
    "CHALLENGER_MIN_F1_IMPROVEMENT",
    "CHALLENGER_SELECTION_VERSION",
    "SUPERVISED_SELECTION_HOLDOUT_FRACTION",
    "_classifier_probability_values",
    "_challenger_respects_error_rate_guards",
    "_evaluate_supervised_candidate",
    "_false_accept_false_reject_rates",
    "_make_supervised_classifier",
    "_ordered_unique_strings",
    "_select_primary_supervised_family",
    "_select_supervised_validation_indices",
    "train_supervised_classifier_candidates",
]
