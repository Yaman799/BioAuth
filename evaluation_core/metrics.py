from __future__ import annotations

import os
from importlib import import_module
from typing import Any, Callable, Dict, Mapping, Sequence

import numpy as np

LABEL_GENUINE = 0
LABEL_INTRUDER = 1
LABEL_CONVENTION_VERSION = "bioauth-labels-v1"
SCORE_DIRECTION = "higher_score_more_suspicious"
DEFAULT_DECISION_THRESHOLD = 0.5
DEFAULT_BOOTSTRAP_ITERATIONS = 200
DEFAULT_BOOTSTRAP_MIN_SAMPLES = 10


LABEL_CONVENTION: Dict[str, Any] = {
    "version": LABEL_CONVENTION_VERSION,
    "genuine": LABEL_GENUINE,
    "intruder": LABEL_INTRUDER,
    "score_direction": SCORE_DIRECTION,
    "prediction_rule": "predict intruder when suspicious risk score >= threshold",
    "confusion_matrix": {
        "tn": "genuine accepted",
        "fp": "genuine rejected (false reject)",
        "fn": "intruder accepted (false accept)",
        "tp": "intruder rejected",
    },
    "far": "false accept rate = intruder accepted / all intruder samples = FN / (FN + TP)",
    "frr": "false reject rate = genuine rejected / all genuine samples = FP / (FP + TN)",
}


def _facade():
    return import_module("model_evaluation")


def _session_truth_label(session_path: str, negative_lookup: set[str]) -> int:
    normalized = os.path.normcase(os.path.abspath(session_path))
    return LABEL_INTRUDER if normalized in negative_lookup else LABEL_GENUINE


def _predicted_intruder(details: Mapping[str, Any]) -> int:
    final_value = str(details.get("final") or "").strip().lower()
    if final_value in {"suspicious", "intruder", "rejected", "unauthorized"}:
        return LABEL_INTRUDER
    return LABEL_GENUINE


def _as_label_array(values: Sequence[int]) -> np.ndarray:
    labels = np.asarray(list(values), dtype=int)
    if labels.size and not set(int(item) for item in np.unique(labels)).issubset({LABEL_GENUINE, LABEL_INTRUDER}):
        raise ValueError("BioAuth evaluation labels must use LABEL_GENUINE=0 and LABEL_INTRUDER=1.")
    return labels


def _as_score_array(values: Sequence[float]) -> np.ndarray:
    scores = np.asarray(list(values), dtype=float)
    if scores.size:
        scores = np.where(np.isfinite(scores), scores, 0.0)
    return scores


def predict_labels_at_threshold(risk_scores: Sequence[float], threshold: float = DEFAULT_DECISION_THRESHOLD) -> np.ndarray:
    """Return BioAuth labels using the project score direction.

    The project convention is explicit and safety-critical: larger risk scores
    are more suspicious, LABEL_INTRUDER is 1, and a sample is predicted as
    intruder/rejected when risk >= threshold.
    """

    scores = _as_score_array(risk_scores)
    return (scores >= float(threshold)).astype(int)


def confusion_counts(y_true: Sequence[int], y_pred: Sequence[int]) -> Dict[str, int]:
    y_true_arr = _as_label_array(y_true)
    y_pred_arr = _as_label_array(y_pred)
    if y_true_arr.size == 0:
        return {"tn": 0, "fp": 0, "fn": 0, "tp": 0}
    if y_true_arr.size != y_pred_arr.size:
        raise ValueError("y_true and y_pred must have the same length.")
    tn = int(np.sum((y_true_arr == LABEL_GENUINE) & (y_pred_arr == LABEL_GENUINE)))
    fp = int(np.sum((y_true_arr == LABEL_GENUINE) & (y_pred_arr == LABEL_INTRUDER)))
    fn = int(np.sum((y_true_arr == LABEL_INTRUDER) & (y_pred_arr == LABEL_GENUINE)))
    tp = int(np.sum((y_true_arr == LABEL_INTRUDER) & (y_pred_arr == LABEL_INTRUDER)))
    return {"tn": tn, "fp": fp, "fn": fn, "tp": tp}


def _precision_recall_f1_from_counts(counts: Mapping[str, int]) -> tuple[float, float, float]:
    tp = int(counts.get("tp", 0))
    fp = int(counts.get("fp", 0))
    fn = int(counts.get("fn", 0))
    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    f1 = float((2.0 * precision * recall) / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def _roc_auc_score_binary(y_true: Sequence[int], risk_scores: Sequence[float]) -> float | None:
    labels = _as_label_array(y_true)
    scores = _as_score_array(risk_scores)
    if labels.size == 0 or labels.size != scores.size:
        return None
    positive_count = int(np.sum(labels == LABEL_INTRUDER))
    negative_count = int(np.sum(labels == LABEL_GENUINE))
    if positive_count == 0 or negative_count == 0:
        return None

    order = np.argsort(scores, kind="mergesort")
    sorted_scores = scores[order]
    ranks = np.empty(scores.size, dtype=float)
    start = 0
    while start < sorted_scores.size:
        end = start + 1
        while end < sorted_scores.size and sorted_scores[end] == sorted_scores[start]:
            end += 1
        average_rank = (start + 1 + end) / 2.0
        ranks[order[start:end]] = average_rank
        start = end
    positive_rank_sum = float(np.sum(ranks[labels == LABEL_INTRUDER]))
    auc = (positive_rank_sum - (positive_count * (positive_count + 1) / 2.0)) / (positive_count * negative_count)
    return float(auc)


def _false_accept_false_reject_rates(*, tn: int, fp: int, fn: int, tp: int) -> tuple[float, float]:
    """Return FAR then FRR under BioAuth's fixed label convention.

    With LABEL_GENUINE=0 and LABEL_INTRUDER=1:
    - TN = genuine accepted
    - FP = genuine rejected, so it contributes to FRR
    - FN = intruder accepted, so it contributes to FAR
    - TP = intruder rejected
    """

    far = float(fn / (fn + tp)) if (fn + tp) > 0 else 0.0
    frr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
    return far, frr


def false_accept_rate_from_counts(counts: Mapping[str, int]) -> float:
    far, _ = _false_accept_false_reject_rates(
        tn=int(counts.get("tn", 0)),
        fp=int(counts.get("fp", 0)),
        fn=int(counts.get("fn", 0)),
        tp=int(counts.get("tp", 0)),
    )
    return far


def false_reject_rate_from_counts(counts: Mapping[str, int]) -> float:
    _, frr = _false_accept_false_reject_rates(
        tn=int(counts.get("tn", 0)),
        fp=int(counts.get("fp", 0)),
        fn=int(counts.get("fn", 0)),
        tp=int(counts.get("tp", 0)),
    )
    return frr


def error_rates_at_threshold(y_true: Sequence[int], risk_scores: Sequence[float], threshold: float) -> Dict[str, Any]:
    y_true_arr = _as_label_array(y_true)
    pred = predict_labels_at_threshold(risk_scores, threshold)
    counts = confusion_counts(y_true_arr, pred)
    far, frr = _false_accept_false_reject_rates(**counts)
    return {
        "threshold": float(threshold),
        "far": float(far),
        "frr": float(frr),
        "confusion_matrix": counts,
    }


def _candidate_thresholds(scores: np.ndarray) -> list[float]:
    if scores.size == 0:
        return [DEFAULT_DECISION_THRESHOLD]
    unique_scores = sorted(float(item) for item in np.unique(scores))
    thresholds = set(unique_scores)
    if len(unique_scores) >= 2:
        for left, right in zip(unique_scores, unique_scores[1:]):
            thresholds.add((left + right) / 2.0)
    thresholds.add(float(min(unique_scores) - 1e-12))
    thresholds.add(float(max(unique_scores) + 1e-12))
    thresholds.add(DEFAULT_DECISION_THRESHOLD)
    return sorted(thresholds)


def compute_eer(y_true: Sequence[int], risk_scores: Sequence[float]) -> Dict[str, Any]:
    """Compute EER using BioAuth label and score direction semantics.

    Returns a metadata dictionary instead of a bare float so callers can persist
    the threshold and FAR/FRR values that produced the EER. If either class is
    missing, the result is explicitly unavailable rather than misleadingly zero.
    """

    y_true_arr = _as_label_array(y_true)
    scores_arr = _as_score_array(risk_scores)
    if y_true_arr.size == 0 or scores_arr.size == 0 or y_true_arr.size != scores_arr.size:
        return {"available": False, "reason": "empty_or_mismatched_inputs", "eer": None, "threshold": None, "far": None, "frr": None}
    labels_present = set(int(item) for item in np.unique(y_true_arr))
    if not labels_present.issuperset({LABEL_GENUINE, LABEL_INTRUDER}):
        return {"available": False, "reason": "both_genuine_and_intruder_required", "eer": None, "threshold": None, "far": None, "frr": None}

    best: Dict[str, Any] | None = None
    for threshold in _candidate_thresholds(scores_arr):
        candidate = error_rates_at_threshold(y_true_arr, scores_arr, threshold)
        candidate["eer"] = float((candidate["far"] + candidate["frr"]) / 2.0)
        candidate["absolute_gap"] = float(abs(candidate["far"] - candidate["frr"]))
        if best is None:
            best = candidate
            continue
        current_key = (candidate["absolute_gap"], candidate["eer"], candidate["threshold"])
        best_key = (best["absolute_gap"], best["eer"], best["threshold"])
        if current_key < best_key:
            best = candidate
    assert best is not None
    return {
        "available": True,
        "reason": "ok",
        "eer": float(best["eer"]),
        "threshold": float(best["threshold"]),
        "far": float(best["far"]),
        "frr": float(best["frr"]),
        "absolute_gap": float(best["absolute_gap"]),
        "confusion_matrix": dict(best["confusion_matrix"]),
    }


def calibrate_thresholds(
    y_true: Sequence[int],
    risk_scores: Sequence[float],
    *,
    target_far: float | None = None,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """Return data-derived global/per-user thresholds for risk scores.

    This helper does not promote or enable a model. It only reports thresholds
    derived from the supplied validation labels and suspiciousness scores.
    """

    y_true_arr = _as_label_array(y_true)
    scores_arr = _as_score_array(risk_scores)
    sample_counts = sample_count_summary(y_true_arr)
    eer = compute_eer(y_true_arr, scores_arr)
    result: Dict[str, Any] = {
        "available": bool(eer.get("available")),
        "label_convention": dict(LABEL_CONVENTION),
        "sample_counts": sample_counts,
        "global_threshold": eer.get("threshold"),
        "per_user_threshold": eer.get("threshold") if user_id else None,
        "per_user_thresholds": {str(user_id): eer.get("threshold")} if user_id else {},
        "method": "min_eer_threshold",
        "eer": eer,
        "target_far": None,
    }
    if not eer.get("available"):
        result["reason"] = eer.get("reason")
        return result

    if target_far is not None:
        max_far = max(0.0, min(1.0, float(target_far)))
        eligible: list[Dict[str, Any]] = []
        for threshold in _candidate_thresholds(scores_arr):
            candidate = error_rates_at_threshold(y_true_arr, scores_arr, threshold)
            if candidate["far"] <= max_far:
                eligible.append(candidate)
        if eligible:
            chosen = sorted(eligible, key=lambda item: (item["frr"], abs(item["far"] - max_far), item["threshold"]))[0]
            result["target_far"] = {
                "available": True,
                "max_far": float(max_far),
                "threshold": float(chosen["threshold"]),
                "far": float(chosen["far"]),
                "frr": float(chosen["frr"]),
                "confusion_matrix": dict(chosen["confusion_matrix"]),
            }
        else:
            result["target_far"] = {"available": False, "max_far": float(max_far), "reason": "no_threshold_met_target_far"}
    return result


def sample_count_summary(y_true: Sequence[int]) -> Dict[str, int]:
    labels = _as_label_array(y_true)
    return {
        "total": int(labels.size),
        "genuine": int(np.sum(labels == LABEL_GENUINE)) if labels.size else 0,
        "intruder": int(np.sum(labels == LABEL_INTRUDER)) if labels.size else 0,
    }


def bootstrap_metric_ci(
    y_true: Sequence[int],
    values: Sequence[float] | Sequence[int],
    metric_fn: Callable[[np.ndarray, np.ndarray], float | None],
    *,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    confidence: float = 0.95,
    min_samples: int = DEFAULT_BOOTSTRAP_MIN_SAMPLES,
    random_seed: int = 42,
) -> Dict[str, Any]:
    y_arr = _as_label_array(y_true)
    value_arr = np.asarray(list(values), dtype=float)
    if y_arr.size != value_arr.size or y_arr.size < int(min_samples):
        return {
            "available": False,
            "reason": "insufficient_or_mismatched_samples",
            "sample_count": int(y_arr.size),
            "min_samples": int(min_samples),
            "low": None,
            "high": None,
        }
    estimates: list[float] = []
    rng = np.random.default_rng(int(random_seed))
    indices = np.arange(y_arr.size)
    for _ in range(max(1, int(iterations))):
        sample_idx = rng.choice(indices, size=y_arr.size, replace=True)
        try:
            value = metric_fn(y_arr[sample_idx], value_arr[sample_idx])
        except Exception:
            value = None
        if value is None:
            continue
        try:
            numeric = float(value)
        except Exception:
            continue
        if np.isfinite(numeric):
            estimates.append(numeric)
    if not estimates:
        return {"available": False, "reason": "metric_unavailable_in_bootstrap", "sample_count": int(y_arr.size), "low": None, "high": None}
    alpha = (1.0 - float(confidence)) / 2.0
    low, high = np.quantile(np.asarray(estimates, dtype=float), [alpha, 1.0 - alpha])
    return {
        "available": True,
        "confidence": float(confidence),
        "iterations": int(iterations),
        "sample_count": int(y_arr.size),
        "low": float(low),
        "high": float(high),
    }


def metric_confidence_intervals(
    y_true: Sequence[int],
    y_pred: Sequence[int],
    risk_scores: Sequence[float],
    *,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    min_samples: int = DEFAULT_BOOTSTRAP_MIN_SAMPLES,
) -> Dict[str, Any]:
    def _auc(labels: np.ndarray, scores: np.ndarray) -> float | None:
        if not set(int(item) for item in np.unique(labels)).issuperset({LABEL_GENUINE, LABEL_INTRUDER}):
            return None
        return _roc_auc_score_binary(labels, scores)

    def _f1(labels: np.ndarray, preds: np.ndarray) -> float:
        counts = confusion_counts(labels, preds.astype(int))
        _precision_value, _recall_value, f1_value = _precision_recall_f1_from_counts(counts)
        return f1_value

    def _precision(labels: np.ndarray, preds: np.ndarray) -> float:
        counts = confusion_counts(labels, preds.astype(int))
        precision_value, _recall_value, _f1_value = _precision_recall_f1_from_counts(counts)
        return precision_value

    def _recall(labels: np.ndarray, preds: np.ndarray) -> float:
        counts = confusion_counts(labels, preds.astype(int))
        _precision_value, recall_value, _f1_value = _precision_recall_f1_from_counts(counts)
        return recall_value

    def _far(labels: np.ndarray, preds: np.ndarray) -> float:
        counts = confusion_counts(labels, preds.astype(int))
        return false_accept_rate_from_counts(counts)

    def _frr(labels: np.ndarray, preds: np.ndarray) -> float:
        counts = confusion_counts(labels, preds.astype(int))
        return false_reject_rate_from_counts(counts)

    return {
        "auc": bootstrap_metric_ci(y_true, risk_scores, _auc, iterations=iterations, min_samples=min_samples),
        "f1": bootstrap_metric_ci(y_true, y_pred, _f1, iterations=iterations, min_samples=min_samples),
        "precision": bootstrap_metric_ci(y_true, y_pred, _precision, iterations=iterations, min_samples=min_samples),
        "recall": bootstrap_metric_ci(y_true, y_pred, _recall, iterations=iterations, min_samples=min_samples),
        "far": bootstrap_metric_ci(y_true, y_pred, _far, iterations=iterations, min_samples=min_samples),
        "frr": bootstrap_metric_ci(y_true, y_pred, _frr, iterations=iterations, min_samples=min_samples),
    }


def _binary_metrics(y_true: Sequence[int], y_pred: Sequence[int], risk_scores: Sequence[float]) -> Dict[str, Any]:
    y_true_arr = _as_label_array(y_true)
    y_pred_arr = _as_label_array(y_pred)
    scores_arr = _as_score_array(risk_scores)

    metrics: Dict[str, Any] = {
        "label_convention": dict(LABEL_CONVENTION),
        "auc": None,
        "f1": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "far": 0.0,
        "frr": 0.0,
        "eer": None,
        "eer_threshold": None,
        "far_at_eer_threshold": None,
        "frr_at_eer_threshold": None,
        "global_threshold": None,
        "per_user_threshold": None,
        "thresholds": {},
        "confidence_intervals": {},
        "sample_counts": sample_count_summary(y_true_arr),
        "confusion_matrix": {"tn": 0, "fp": 0, "fn": 0, "tp": 0},
    }
    if y_true_arr.size == 0:
        metrics["thresholds"] = calibrate_thresholds(y_true_arr, scores_arr)
        metrics["confidence_intervals"] = metric_confidence_intervals(y_true_arr, y_pred_arr, scores_arr)
        return metrics

    labels_present = set(int(item) for item in np.unique(y_true_arr))
    if labels_present.issuperset({LABEL_GENUINE, LABEL_INTRUDER}) and scores_arr.size == y_true_arr.size:
        try:
            metrics["auc"] = _roc_auc_score_binary(y_true_arr, scores_arr)
        except Exception:
            metrics["auc"] = None
    counts = confusion_counts(y_true_arr, y_pred_arr)
    precision_value, recall_value, f1_value = _precision_recall_f1_from_counts(counts)
    metrics["f1"] = f1_value
    metrics["precision"] = precision_value
    metrics["recall"] = recall_value
    metrics["confusion_matrix"] = counts
    metrics["far"], metrics["frr"] = _false_accept_false_reject_rates(**counts)

    if scores_arr.size == y_true_arr.size:
        thresholds = calibrate_thresholds(y_true_arr, scores_arr)
        metrics["thresholds"] = thresholds
        eer = dict(thresholds.get("eer") or {})
        metrics["eer"] = eer.get("eer")
        metrics["eer_threshold"] = eer.get("threshold")
        metrics["far_at_eer_threshold"] = eer.get("far")
        metrics["frr_at_eer_threshold"] = eer.get("frr")
        metrics["global_threshold"] = thresholds.get("global_threshold")
        metrics["per_user_threshold"] = thresholds.get("per_user_threshold")
        metrics["confidence_intervals"] = metric_confidence_intervals(y_true_arr, y_pred_arr, scores_arr)
    return metrics


def evaluate_model_bundle(model: Any, metadata: Mapping[str, Any], classifier: Any, positive_sessions: Sequence[str], negative_sessions: Sequence[str]) -> Dict[str, Any]:
    facade = _facade()
    positives = facade._unique_paths(positive_sessions)
    negatives = facade._unique_paths(negative_sessions)
    all_sessions = positives + negatives
    negative_lookup = {os.path.normcase(os.path.abspath(path)) for path in negatives}
    session_results = []
    y_true = []
    y_pred = []
    risk_scores = []
    hybrid_risk_scores = []
    hybrid_pred = []
    total_windows = 0
    hybrid_available_sessions = 0
    for session_path in all_sessions:
        details = facade.predict_from_session_details(model, session_path, metadata=dict(metadata), classifier=classifier)
        truth_label = _session_truth_label(session_path, negative_lookup)
        predicted_label = _predicted_intruder(details)
        risk_value = facade._safe_score(details.get("risk"))
        raw_value = facade._safe_score(details.get("raw"))
        window_count = int(details.get("window_count") or 0)
        total_windows += max(0, window_count)
        y_true.append(truth_label)
        y_pred.append(predicted_label)
        risk_scores.append(risk_value)
        hybrid_shadow = dict(details.get("hybrid_shadow") or {}) if isinstance(details, Mapping) else {}
        hybrid_used = bool(hybrid_shadow.get("used"))
        if hybrid_used:
            hybrid_available_sessions += 1
        hybrid_label = _predicted_intruder({"final": hybrid_shadow.get("final", details.get("final"))})
        hybrid_risk_value = facade._safe_score(hybrid_shadow.get("risk", details.get("risk")))
        hybrid_pred.append(hybrid_label)
        hybrid_risk_scores.append(hybrid_risk_value)
        session_results.append({
            "session_name": facade._safe_session_name(session_path),
            "session_path": os.path.abspath(session_path),
            "true_label": int(truth_label),
            "predicted_label": int(predicted_label),
            "final": str(details.get("final") or "unknown"),
            "status": str(details.get("status") or "prediction_failed"),
            "raw": raw_value,
            "risk": risk_value,
            "ml": int(details.get("ml") or 0),
            "window_count": window_count,
            "deep_shadow": hybrid_shadow,
        })
    metrics = _binary_metrics(y_true, y_pred, risk_scores)
    metrics["session_count"] = int(len(all_sessions))
    metrics["window_count"] = int(total_windows)
    metrics["legitimate_session_count"] = int(len(positives))
    metrics["intruder_session_count"] = int(len(negatives))
    hybrid_metrics = _binary_metrics(y_true, hybrid_pred, hybrid_risk_scores)
    hybrid_metrics["session_count"] = int(len(all_sessions))
    hybrid_metrics["window_count"] = int(total_windows)
    hybrid_metrics["legitimate_session_count"] = int(len(positives))
    hybrid_metrics["intruder_session_count"] = int(len(negatives))
    hybrid_metrics["deep_available_session_count"] = int(hybrid_available_sessions)
    return {"session_results": session_results, "metrics": metrics, "hybrid_shadow_metrics": hybrid_metrics}


__all__ = [
    "DEFAULT_BOOTSTRAP_ITERATIONS",
    "DEFAULT_BOOTSTRAP_MIN_SAMPLES",
    "DEFAULT_DECISION_THRESHOLD",
    "LABEL_CONVENTION",
    "LABEL_CONVENTION_VERSION",
    "LABEL_GENUINE",
    "LABEL_INTRUDER",
    "SCORE_DIRECTION",
    "_binary_metrics",
    "_false_accept_false_reject_rates",
    "_predicted_intruder",
    "_session_truth_label",
    "bootstrap_metric_ci",
    "calibrate_thresholds",
    "compute_eer",
    "confusion_counts",
    "error_rates_at_threshold",
    "evaluate_model_bundle",
    "false_accept_rate_from_counts",
    "false_reject_rate_from_counts",
    "metric_confidence_intervals",
    "_precision_recall_f1_from_counts",
    "_roc_auc_score_binary",
    "predict_labels_at_threshold",
    "sample_count_summary",
]
