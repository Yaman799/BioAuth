from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

import numpy as np

RISK_SENSITIVITY_PRESETS = {
    "conservative": {
        "name": "Conservative",
        "single_intruder_risk": 78,
        "single_intruder_prob": 0.90,
        "single_suspicious_risk": 68,
        "single_suspicious_prob": 0.42,
        "multi_intruder_risk": 76,
        "multi_intruder_prob": 0.76,
        "multi_intruder_severe_prob": 0.60,
        "multi_intruder_severe_count": 2,
        "multi_suspicious_risk": 66,
        "multi_suspicious_prob": 0.42,
        "multi_suspicious_windows": 2,
        "anomaly_only_single_intruder_risk": 100,
        "anomaly_only_single_suspicious_risk": 68,
        "anomaly_only_multi_intruder_risk": 98,
        "anomaly_only_multi_intruder_severe_count": 3,
        "anomaly_only_multi_suspicious_risk": 68,
        "anomaly_only_multi_suspicious_windows": 2,
        "suspicious_window_risk": 68.0,
        "severe_window_risk": 88.0,
        "anomaly_weight": 0.62,
        "classifier_weight": 0.38,
        "classifier_positive_cutoff": 0.58,
        "sequence_weight": 0.20,
        "runtime_high_risk_override": 94.0,
        "runtime_high_risk_min_elapsed_seconds": 18.0,
        "runtime_suspicious_fast_lock_risk": 94.0,
        "runtime_suspicious_fast_lock_avg_risk": 90.0,
        "runtime_suspicious_fast_lock_elapsed_seconds": 18.0,
        "runtime_suspicious_fast_lock_alert_hits": 2,
        "runtime_intruder_confirmations": 3,
        "runtime_intruder_avg3_threshold": 70.0,
        "runtime_intruder_avg4_ml_threshold": 64.0,
        "runtime_intruder_avg4_severe_threshold": 72.0,
        "runtime_alert_hits_threshold": 3,
        "runtime_alert_avg4_threshold": 72.0,
        "runtime_alert_ml_avg4_threshold": 76.0,
        "runtime_avg_risk_intruder_threshold": 78.0,
        "runtime_severe_hit_threshold": 86.0,
        "runtime_severe_hit_count": 2,
        "runtime_min_samples_for_action": 3,
        "runtime_min_lock_elapsed_seconds": 36.0,
        "runtime_secondary_lock_elapsed_seconds": 24.0,
        "runtime_warning_reset_avg_risk": 38.0,
        "runtime_warning_escalation_alert_hits": 3,
        "runtime_warning_lock_alert_hits": 2,
        "runtime_warning_lock_peak_risk": 82.0,
        "runtime_warning_lock_alert_avg_risk": 76.0,
        "runtime_warning_lock_elapsed_seconds": 10.0,
        "runtime_warning_fast_interval_seconds": 1.25,
        "runtime_startup_fast_interval_seconds": 1.25,
        "runtime_confirmation_window_seconds": 10.0,
        "runtime_pending_memory_keep": 1,
        "runtime_post_transition_lock_dwell_seconds": 8.0,
        "runtime_post_recovery_lock_dwell_seconds": 8.0,
        "runtime_legit_reset_streak": 4,
        "runtime_legit_reset_avg_risk": 28.0,
        "runtime_recovery_override_risk": 98.0,
    },
    "balanced": {
        "name": "Balanced",
        "single_intruder_risk": 72,
        "single_intruder_prob": 0.85,
        "single_suspicious_risk": 58,
        "single_suspicious_prob": 0.35,
        "multi_intruder_risk": 70,
        "multi_intruder_prob": 0.72,
        "multi_intruder_severe_prob": 0.55,
        "multi_intruder_severe_count": 2,
        "multi_suspicious_risk": 60,
        "multi_suspicious_prob": 0.35,
        "multi_suspicious_windows": 2,
        "anomaly_only_single_intruder_risk": 99,
        "anomaly_only_single_suspicious_risk": 60,
        "anomaly_only_multi_intruder_risk": 96,
        "anomaly_only_multi_intruder_severe_count": 3,
        "anomaly_only_multi_suspicious_risk": 60,
        "anomaly_only_multi_suspicious_windows": 2,
        "suspicious_window_risk": 60.0,
        "severe_window_risk": 82.0,
        "anomaly_weight": 0.55,
        "classifier_weight": 0.45,
        "classifier_positive_cutoff": 0.55,
        "sequence_weight": 0.20,
        "runtime_high_risk_override": 90.0,
        "runtime_high_risk_min_elapsed_seconds": 15.0,
        "runtime_suspicious_fast_lock_risk": 90.0,
        "runtime_suspicious_fast_lock_avg_risk": 85.0,
        "runtime_suspicious_fast_lock_elapsed_seconds": 12.0,
        "runtime_suspicious_fast_lock_alert_hits": 2,
        "runtime_intruder_confirmations": 2,
        "runtime_intruder_avg3_threshold": 66.0,
        "runtime_intruder_avg4_ml_threshold": 60.0,
        "runtime_intruder_avg4_severe_threshold": 68.0,
        "runtime_alert_hits_threshold": 3,
        "runtime_alert_avg4_threshold": 68.0,
        "runtime_alert_ml_avg4_threshold": 72.0,
        "runtime_avg_risk_intruder_threshold": 74.0,
        "runtime_severe_hit_threshold": 80.0,
        "runtime_severe_hit_count": 2,
        "runtime_min_samples_for_action": 3,
        "runtime_min_lock_elapsed_seconds": 30.0,
        "runtime_secondary_lock_elapsed_seconds": 20.0,
        "runtime_warning_reset_avg_risk": 35.0,
        "runtime_warning_escalation_alert_hits": 2,
        "runtime_warning_lock_alert_hits": 2,
        "runtime_warning_lock_peak_risk": 76.0,
        "runtime_warning_lock_alert_avg_risk": 72.0,
        "runtime_warning_lock_elapsed_seconds": 8.0,
        "runtime_warning_fast_interval_seconds": 1.0,
        "runtime_startup_fast_interval_seconds": 1.0,
        "runtime_confirmation_window_seconds": 10.0,
        "runtime_pending_memory_keep": 1,
        "runtime_post_transition_lock_dwell_seconds": 8.0,
        "runtime_post_recovery_lock_dwell_seconds": 8.0,
        "runtime_legit_reset_streak": 3,
        "runtime_legit_reset_avg_risk": 28.0,
        "runtime_recovery_override_risk": 98.0,
    },
    "strict": {
        "name": "Strict",
        "single_intruder_risk": 68,
        "single_intruder_prob": 0.78,
        "single_suspicious_risk": 52,
        "single_suspicious_prob": 0.28,
        "multi_intruder_risk": 66,
        "multi_intruder_prob": 0.66,
        "multi_intruder_severe_prob": 0.48,
        "multi_intruder_severe_count": 2,
        "multi_suspicious_risk": 54,
        "multi_suspicious_prob": 0.28,
        "multi_suspicious_windows": 2,
        "anomaly_only_single_intruder_risk": 96,
        "anomaly_only_single_suspicious_risk": 55,
        "anomaly_only_multi_intruder_risk": 92,
        "anomaly_only_multi_intruder_severe_count": 2,
        "anomaly_only_multi_suspicious_risk": 55,
        "anomaly_only_multi_suspicious_windows": 2,
        "suspicious_window_risk": 55.0,
        "severe_window_risk": 78.0,
        "anomaly_weight": 0.50,
        "classifier_weight": 0.50,
        "classifier_positive_cutoff": 0.50,
        "sequence_weight": 0.20,
        "runtime_high_risk_override": 86.0,
        "runtime_high_risk_min_elapsed_seconds": 12.0,
        "runtime_suspicious_fast_lock_risk": 86.0,
        "runtime_suspicious_fast_lock_avg_risk": 80.0,
        "runtime_suspicious_fast_lock_elapsed_seconds": 10.0,
        "runtime_suspicious_fast_lock_alert_hits": 2,
        "runtime_intruder_confirmations": 2,
        "runtime_intruder_avg3_threshold": 62.0,
        "runtime_intruder_avg4_ml_threshold": 56.0,
        "runtime_intruder_avg4_severe_threshold": 64.0,
        "runtime_alert_hits_threshold": 2,
        "runtime_alert_avg4_threshold": 64.0,
        "runtime_alert_ml_avg4_threshold": 68.0,
        "runtime_avg_risk_intruder_threshold": 70.0,
        "runtime_severe_hit_threshold": 76.0,
        "runtime_severe_hit_count": 2,
        "runtime_min_samples_for_action": 3,
        "runtime_min_lock_elapsed_seconds": 24.0,
        "runtime_secondary_lock_elapsed_seconds": 16.0,
        "runtime_warning_reset_avg_risk": 32.0,
        "runtime_warning_escalation_alert_hits": 2,
        "runtime_warning_lock_alert_hits": 2,
        "runtime_warning_lock_peak_risk": 72.0,
        "runtime_warning_lock_alert_avg_risk": 68.0,
        "runtime_warning_lock_elapsed_seconds": 6.0,
        "runtime_warning_fast_interval_seconds": 0.9,
        "runtime_startup_fast_interval_seconds": 0.9,
        "runtime_confirmation_window_seconds": 10.0,
        "runtime_pending_memory_keep": 1,
        "runtime_post_transition_lock_dwell_seconds": 6.0,
        "runtime_post_recovery_lock_dwell_seconds": 6.0,
        "runtime_legit_reset_streak": 3,
        "runtime_legit_reset_avg_risk": 30.0,
        "runtime_recovery_override_risk": 96.0,
    },
}
DEFAULT_RISK_SENSITIVITY = "balanced"


@dataclass(frozen=True)
class DecisionOutcome:
    final: str
    risk: int
    raw: float
    ml_pred: int
    intruder_prob: float
    suspicious_windows: int
    severe_windows: int
    classifier_used: bool
    sensitivity: str
    decision_reason: str = ""
    decision_details: Dict[str, Any] | None = None


def normalize_sensitivity_preset(value: str | None) -> str:
    key = str(value or "").strip().lower()
    return key if key in RISK_SENSITIVITY_PRESETS else DEFAULT_RISK_SENSITIVITY


def resolve_sensitivity_config(
    sensitivity: str | None,
    overrides: Mapping[str, Any] | None = None,
) -> Dict[str, float]:
    preset_name = normalize_sensitivity_preset(sensitivity)
    config = dict(RISK_SENSITIVITY_PRESETS[preset_name])
    if isinstance(overrides, Mapping):
        for key, value in overrides.items():
            if key not in config:
                continue
            try:
                config[key] = float(value) if isinstance(config[key], (int, float)) else value
            except Exception:
                continue
    config["preset"] = preset_name
    return config


def resolve_runtime_escalation_config(
    sensitivity: str | None,
    overrides: Mapping[str, Any] | None = None,
) -> Dict[str, float]:
    return resolve_sensitivity_config(sensitivity, overrides)


def _monotonic_points(points: list[float]) -> list[float]:
    out: list[float] = []
    floor = None
    for value in points:
        cur = float(value)
        if floor is None:
            out.append(cur)
            floor = cur
            continue
        if cur <= floor:
            cur = floor + 1e-6
        out.append(cur)
        floor = cur
    return out


def compute_risk(raw: float, meta: Dict[str, Any]) -> float:
    stats = meta.get("score_percentiles") if isinstance(meta, dict) else None
    if isinstance(stats, dict) and stats:
        xs = _monotonic_points(
            [
                float(stats.get("p50", 0.0)),
                float(stats.get("p75", stats.get("p50", 0.0))),
                float(stats.get("p90", stats.get("p75", 0.0))),
                float(stats.get("p95", stats.get("p90", 0.0))),
                float(stats.get("p98", stats.get("p95", 0.0))),
                float(stats.get("tail_high", stats.get("p98", 0.0) + 1.0)),
            ]
        )
        ys = [15.0, 30.0, 55.0, 75.0, 90.0, 100.0]
        return float(np.clip(np.interp(float(raw), xs, ys, left=0.0, right=100.0), 0.0, 100.0))

    p10 = meta.get("p10") if isinstance(meta, dict) else None
    p90 = meta.get("p90") if isinstance(meta, dict) else None
    if p10 is None or p90 is None:
        return 0.0
    if abs(float(p90) - float(p10)) < 1e-9:
        return 50.0
    return float(np.clip(np.interp(float(raw), [float(p10), float(p90)], [0.0, 100.0]), 0.0, 100.0))


def weighted_average(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0
    weights = np.linspace(1.0, 1.0 + 0.3 * max(0, arr.size - 1), num=arr.size)
    weights = weights / weights.sum()
    return float(np.average(arr, weights=weights))



def score_windows(
    *,
    raw_scores: np.ndarray,
    anomaly_risk_values: np.ndarray,
    classifier_probs: np.ndarray | None,
    sensitivity: str | None,
    overrides: Mapping[str, Any] | None = None,
    sequence_probs: np.ndarray | None = None,
) -> Dict[str, Any]:
    config = resolve_sensitivity_config(sensitivity, overrides)
    raw = weighted_average(raw_scores)
    base_risk = int(round(weighted_average(anomaly_risk_values)))
    classifier_used = classifier_probs is not None and np.asarray(classifier_probs).size > 0
    intruder_prob = 0.0
    ml_pred = 0
    effective_risk_values = np.asarray(anomaly_risk_values, dtype=float).copy()
    if classifier_used:
        probs = np.clip(np.asarray(classifier_probs, dtype=float), 0.0, 1.0)
        intruder_prob = weighted_average(probs)
        ml_pred = int(intruder_prob >= float(config["classifier_positive_cutoff"]))
        anomaly_weight = float(config["anomaly_weight"])
        classifier_weight = float(config["classifier_weight"])
        effective_risk_values = np.clip((effective_risk_values * anomaly_weight) + (probs * 100.0 * classifier_weight), 0, 100)
    risk = int(round(weighted_average(effective_risk_values)))
    suspicious_windows = int(np.sum(effective_risk_values >= float(config["suspicious_window_risk"])))
    severe_windows = int(np.sum(effective_risk_values >= float(config["severe_window_risk"])))
    hybrid = {"available": False, "used": False, "sequence_prob": None, "risk": risk, "intruder_prob": intruder_prob, "ml_pred": ml_pred, "suspicious_windows": suspicious_windows, "severe_windows": severe_windows, "classifier_used": classifier_used, "effective_risk_values": effective_risk_values.copy()}
    if sequence_probs is not None and np.asarray(sequence_probs).size > 0:
        sequence_values = np.clip(np.asarray(sequence_probs, dtype=float), 0.0, 1.0)
        sequence_prob = weighted_average(sequence_values)
        seq_weight = float(config.get("sequence_weight", 0.20))
        anomaly_weight = float(config["anomaly_weight"])
        classifier_weight = float(config["classifier_weight"] if classifier_used else 0.0)
        total = max(1e-6, anomaly_weight + classifier_weight + seq_weight)
        fusion_values = (np.asarray(anomaly_risk_values, dtype=float) * anomaly_weight)
        if classifier_used:
            fusion_values = fusion_values + (np.clip(np.asarray(classifier_probs, dtype=float), 0.0, 1.0) * 100.0 * classifier_weight)
        fusion_values = np.clip((fusion_values + (sequence_prob * 100.0 * seq_weight)) / total, 0, 100)
        fusion_prob_parts = []
        fusion_prob_weights = []
        if classifier_used:
            fusion_prob_parts.append(intruder_prob); fusion_prob_weights.append(classifier_weight)
        fusion_prob_parts.append(sequence_prob); fusion_prob_weights.append(seq_weight)
        fusion_prob = float(np.average(np.asarray(fusion_prob_parts, dtype=float), weights=np.asarray(fusion_prob_weights, dtype=float))) if fusion_prob_parts else 0.0
        hybrid = {
            "available": True,
            "used": True,
            "sequence_prob": float(sequence_prob),
            "risk": int(round(weighted_average(fusion_values))),
            "intruder_prob": float(fusion_prob),
            "ml_pred": int(fusion_prob >= float(config["classifier_positive_cutoff"])),
            "suspicious_windows": int(np.sum(fusion_values >= float(config["suspicious_window_risk"]))),
            "severe_windows": int(np.sum(fusion_values >= float(config["severe_window_risk"]))),
            "classifier_used": bool(classifier_used),
            "effective_risk_values": fusion_values,
        }
    return {
        "config": config,
        "raw": raw,
        "base_risk": base_risk,
        "risk": risk,
        "ml_pred": ml_pred,
        "intruder_prob": intruder_prob,
        "suspicious_windows": suspicious_windows,
        "severe_windows": severe_windows,
        "classifier_used": classifier_used,
        "effective_risk_values": effective_risk_values,
        "hybrid": hybrid,
    }


def final_decision_from_metrics(*, metrics: Mapping[str, Any], window_count: int) -> DecisionOutcome:
    risk = int(metrics.get("risk", 0) or 0)
    raw = float(metrics.get("raw", 0.0) or 0.0)
    ml_pred = int(metrics.get("ml_pred", 0) or 0)
    intruder_prob = float(metrics.get("intruder_prob", 0.0) or 0.0)
    suspicious_windows = int(metrics.get("suspicious_windows", 0) or 0)
    severe_windows = int(metrics.get("severe_windows", 0) or 0)
    classifier_used = bool(metrics.get("classifier_used"))
    config = dict(metrics.get("config") or {})
    sensitivity = str(config.get("preset") or DEFAULT_RISK_SENSITIVITY)
    final = "legitimate"
    decision_reason = "below_threshold"

    details: Dict[str, Any] = {
        "risk": risk,
        "intruder_prob": round(float(intruder_prob), 6),
        "suspicious_windows": suspicious_windows,
        "severe_windows": severe_windows,
        "classifier_used": classifier_used,
        "window_count": int(window_count),
        "risk_sensitivity": sensitivity,
    }

    if int(window_count) <= 1:
        details.update({
            "single_intruder_risk": int(config["single_intruder_risk"]) if classifier_used else int(config["anomaly_only_single_intruder_risk"]),
            "single_suspicious_risk": int(config["single_suspicious_risk"]) if classifier_used else int(config["anomaly_only_single_suspicious_risk"]),
            "single_intruder_prob": float(config.get("single_intruder_prob", 0.0)),
            "single_suspicious_prob": float(config.get("single_suspicious_prob", 0.0)),
        })
        if classifier_used:
            if intruder_prob >= float(config["single_intruder_prob"]) and risk >= int(config["single_intruder_risk"]):
                final = "intruder"
                decision_reason = "single_intruder_risk_and_probability"
            elif risk >= int(config["single_suspicious_risk"]):
                final = "suspicious"
                decision_reason = "single_suspicious_risk_threshold"
            elif intruder_prob >= float(config["single_suspicious_prob"]):
                final = "suspicious"
                decision_reason = "single_suspicious_probability_threshold"
            else:
                decision_reason = "single_below_suspicious_threshold"
        else:
            if risk >= int(config["anomaly_only_single_intruder_risk"]):
                final = "intruder"
                decision_reason = "single_anomaly_intruder_risk_threshold"
            elif risk >= int(config["anomaly_only_single_suspicious_risk"]):
                final = "suspicious"
                decision_reason = "single_anomaly_suspicious_risk_threshold"
            else:
                decision_reason = "single_anomaly_below_suspicious_threshold"
    else:
        details.update({
            "multi_intruder_risk": int(config["multi_intruder_risk"]) if classifier_used else int(config["anomaly_only_multi_intruder_risk"]),
            "multi_suspicious_risk": int(config["multi_suspicious_risk"]) if classifier_used else int(config["anomaly_only_multi_suspicious_risk"]),
            "multi_intruder_prob": float(config.get("multi_intruder_prob", 0.0)),
            "multi_intruder_severe_prob": float(config.get("multi_intruder_severe_prob", 0.0)),
            "multi_suspicious_prob": float(config.get("multi_suspicious_prob", 0.0)),
            "multi_suspicious_windows": int(config["multi_suspicious_windows"]) if classifier_used else int(config["anomaly_only_multi_suspicious_windows"]),
        })
        if classifier_used:
            if intruder_prob >= float(config["multi_intruder_prob"]) and risk >= int(config["multi_intruder_risk"]):
                final = "intruder"
                decision_reason = "multi_intruder_risk_and_probability"
            elif (
                intruder_prob >= float(config["multi_intruder_severe_prob"])
                and severe_windows >= int(config["multi_intruder_severe_count"])
                and risk >= int(config["multi_intruder_risk"])
            ):
                final = "intruder"
                decision_reason = "multi_intruder_severe_probability_and_windows"
            elif suspicious_windows >= int(config["multi_suspicious_windows"]):
                final = "suspicious"
                decision_reason = "multi_suspicious_window_count"
            elif risk >= int(config["multi_suspicious_risk"]):
                final = "suspicious"
                decision_reason = "multi_suspicious_risk_threshold"
            elif intruder_prob >= float(config["multi_suspicious_prob"]):
                final = "suspicious"
                decision_reason = "multi_suspicious_probability_threshold"
            else:
                decision_reason = "multi_below_suspicious_threshold"
        else:
            if severe_windows >= int(config["anomaly_only_multi_intruder_severe_count"]) and risk >= int(config["anomaly_only_multi_intruder_risk"]):
                final = "intruder"
                decision_reason = "multi_anomaly_intruder_severe_windows"
            elif suspicious_windows >= int(config["anomaly_only_multi_suspicious_windows"]):
                final = "suspicious"
                decision_reason = "multi_anomaly_suspicious_window_count"
            elif risk >= int(config["anomaly_only_multi_suspicious_risk"]):
                final = "suspicious"
                decision_reason = "multi_anomaly_suspicious_risk_threshold"
            else:
                decision_reason = "multi_anomaly_below_suspicious_threshold"

    details["decision_reason"] = decision_reason
    details["risk_below_suspicious_risk_threshold"] = bool(
        final == "suspicious"
        and risk < int(details.get("single_suspicious_risk") or details.get("multi_suspicious_risk") or 0)
    )

    return DecisionOutcome(
        final=final,
        risk=risk,
        raw=raw,
        ml_pred=ml_pred,
        intruder_prob=intruder_prob,
        suspicious_windows=suspicious_windows,
        severe_windows=severe_windows,
        classifier_used=classifier_used,
        sensitivity=sensitivity,
        decision_reason=decision_reason,
        decision_details=details,
    )


def classifier_training_summary(negative_window_samples: int, minimum_negative_samples: int) -> Dict[str, Any]:
    usable_negatives = int(negative_window_samples or 0)
    minimum = int(minimum_negative_samples or 0)
    enabled = usable_negatives >= minimum
    return {
        "classifier_enabled": enabled,
        "classifier_reason": (
            "supervised classifier trained from trusted negative windows"
            if enabled
            else "anomaly-only fallback because trusted negative windows were insufficient"
        ),
        "negative_window_samples": usable_negatives,
        "minimum_negative_window_samples": minimum,
        "supervised_classifier_strategy": "RandomForest baseline with optional LightGBM challenger when enough trusted negative windows exist; otherwise anomaly-only IsolationForest/IForest plus non-authoritative Phase 7 classical baseline comparisons",
    }
