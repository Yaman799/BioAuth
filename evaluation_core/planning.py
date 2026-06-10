from __future__ import annotations

import math
import os
from importlib import import_module
from typing import Any, Dict, List, Mapping, Sequence


def _facade():
    return import_module("model_evaluation")


def plan_session_holdout_split(positive_sessions: Sequence[str], negative_sessions: Sequence[str], *, holdout_fraction: float = 0.2, minimum_train_positive: int = 2, minimum_test_positive: int = 1, minimum_train_negative: int = 1) -> Dict[str, List[str]]:
    facade = _facade()
    positives = sorted(facade._unique_paths(positive_sessions), key=lambda item: os.path.getmtime(item) if os.path.exists(item) else 0.0)
    negatives = sorted(facade._unique_paths(negative_sessions), key=lambda item: os.path.getmtime(item) if os.path.exists(item) else 0.0)
    result: Dict[str, List[str]] = {"train_positive_sessions": list(positives), "test_positive_sessions": [], "train_negative_sessions": list(negatives), "test_negative_sessions": []}
    if len(positives) >= (minimum_train_positive + minimum_test_positive):
        test_count = max(minimum_test_positive, int(math.ceil(len(positives) * max(0.0, holdout_fraction))))
        test_count = min(test_count, len(positives) - minimum_train_positive)
        if test_count > 0:
            result["test_positive_sessions"] = positives[-test_count:]
            result["train_positive_sessions"] = positives[:-test_count]
    if len(negatives) >= (minimum_train_negative + 1):
        test_count = max(1, int(math.ceil(len(negatives) * max(0.0, holdout_fraction))))
        test_count = min(test_count, len(negatives) - minimum_train_negative)
        if test_count > 0:
            result["test_negative_sessions"] = negatives[-test_count:]
            result["train_negative_sessions"] = negatives[:-test_count]
    return result


def plan_session_cross_validation_splits(positive_sessions: Sequence[str], negative_sessions: Sequence[str], *, max_folds: int = 3, minimum_train_positive: int = 2, minimum_train_negative: int = 1) -> List[Dict[str, List[str]]]:
    facade = _facade()
    positives = sorted(facade._unique_paths(positive_sessions), key=lambda item: os.path.getmtime(item) if os.path.exists(item) else 0.0)
    negatives = sorted(facade._unique_paths(negative_sessions), key=lambda item: os.path.getmtime(item) if os.path.exists(item) else 0.0)
    candidate_folds = min(int(max_folds), len(positives))
    if negatives:
        candidate_folds = min(candidate_folds, len(negatives))
    if candidate_folds < 2:
        return []
    splits: List[Dict[str, List[str]]] = []
    for fold_index in range(candidate_folds):
        test_positive = positives[fold_index::candidate_folds]
        test_negative = negatives[fold_index::candidate_folds] if negatives else []
        train_positive = [path for path in positives if path not in test_positive]
        train_negative = [path for path in negatives if path not in test_negative]
        if len(train_positive) < minimum_train_positive:
            continue
        if negatives and len(train_negative) < minimum_train_negative:
            continue
        if not test_positive and not test_negative:
            continue
        splits.append({"fold_index": int(len(splits)), "train_positive_sessions": train_positive, "test_positive_sessions": test_positive, "train_negative_sessions": train_negative, "test_negative_sessions": test_negative})
    return splits


def _aggregate_cross_validation_evaluations(folds: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    facade = _facade()
    combined_session_results = []
    y_true = []
    y_pred = []
    risk_scores = []
    total_windows = 0
    fold_summaries = []
    for fold in folds:
        fold_eval = dict(fold.get("evaluation") or {})
        for item in list(fold_eval.get("session_results") or []):
            entry = dict(item)
            entry["fold_index"] = int(fold.get("fold_index") or 0)
            combined_session_results.append(entry)
            y_true.append(int(entry.get("true_label") or 0))
            y_pred.append(int(entry.get("predicted_label") or 0))
            risk_scores.append(facade._safe_score(entry.get("risk")))
            total_windows += int(entry.get("window_count") or 0)
        fold_summaries.append({
            "fold_index": int(fold.get("fold_index") or 0),
            "split_plan": {
                "train_positive_sessions": [facade._safe_session_name(path) for path in list(fold.get("train_positive_sessions") or [])],
                "test_positive_sessions": [facade._safe_session_name(path) for path in list(fold.get("test_positive_sessions") or [])],
                "train_negative_sessions": [facade._safe_session_name(path) for path in list(fold.get("train_negative_sessions") or [])],
                "test_negative_sessions": [facade._safe_session_name(path) for path in list(fold.get("test_negative_sessions") or [])],
            },
            "metrics": dict((fold_eval.get("metrics") or {})),
        })
    metrics = facade._binary_metrics(y_true, y_pred, risk_scores)
    metrics["session_count"] = len(combined_session_results)
    metrics["window_count"] = int(total_windows)
    metrics["legitimate_session_count"] = int(sum(1 for label in y_true if label == 0))
    metrics["intruder_session_count"] = int(sum(1 for label in y_true if label == 1))
    return {"metrics": metrics, "session_results": combined_session_results, "folds": fold_summaries, "fold_count": len(fold_summaries)}


def _evaluate_current_production_bundle(*, user_id: str, reference_positive_sessions: Sequence[str], reference_negative_sessions: Sequence[str], candidate_base_dir: str) -> Dict[str, Any] | None:
    facade = _facade()
    if not user_id:
        return None
    runtime_paths = facade.resolve_active_runtime_paths(user_id)
    if not runtime_paths:
        return None
    if os.path.normcase(os.path.abspath(runtime_paths.get("base") or "")) == os.path.normcase(os.path.abspath(candidate_base_dir or "")):
        return None
    try:
        model = facade.load_model(runtime_paths["model"])
        metadata = facade.load_metadata(runtime_paths["metadata"]) or {}
        classifier = facade.load_classifier(runtime_paths["classifier"]) if os.path.exists(runtime_paths["classifier"]) else None
    except Exception:
        return None
    evaluation = facade.evaluate_model_bundle(model, metadata, classifier, reference_positive_sessions, reference_negative_sessions)
    evaluation["bundle_base"] = os.path.relpath(runtime_paths["base"], os.path.dirname(runtime_paths["base"]))
    return evaluation
