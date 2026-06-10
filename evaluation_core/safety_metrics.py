from __future__ import annotations

from statistics import mean
from typing import Any, Dict, Mapping, Sequence

SAFETY_METRICS_SCHEMA_VERSION = "closed-beta-safety-metrics-v1"

_WARNING_FINALS = {"warning", "warn", "suspicious", "intruder", "rejected", "unauthorized"}
_LOCK_FINALS = {"lock", "locked", "device_locked", "intruder_lock", "system_locked"}
_LOW_QUALITY_REASONS = {"insufficient_evidence", "low_event_count", "high_idle_ratio"}
_STARTUP_POST_IDLE_REASONS = {"startup_window", "post_idle_window"}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _as_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_rate(numerator: int | float, denominator: int | float) -> float:
    try:
        denominator = float(denominator)
        if denominator <= 0:
            return 0.0
        return float(numerator) / denominator
    except Exception:
        return 0.0


def _reason_codes(record: Mapping[str, Any]) -> set[str]:
    raw = record.get("reason_codes") or record.get("reasons") or record.get("decision_reasons") or record.get("quality_reasons") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, Sequence):
        raw = []
    return {str(item).strip().lower() for item in raw if str(item).strip()}


def _truth_is_intruder(record: Mapping[str, Any]) -> bool:
    for key in ("true_label", "truth_label", "label"):
        if key in record:
            try:
                return int(record.get(key)) == 1
            except Exception:
                pass
    kind = str(record.get("actor") or record.get("truth") or record.get("session_type") or "").strip().lower()
    return kind in {"intruder", "attacker", "negative", "unauthorized"}


def _predicted_intruder(record: Mapping[str, Any]) -> bool:
    for key in ("predicted_label", "prediction_label"):
        if key in record:
            try:
                return int(record.get(key)) == 1
            except Exception:
                pass
    final = str(record.get("final") or record.get("decision") or record.get("status") or "").strip().lower()
    return final in {"suspicious", "intruder", "rejected", "unauthorized", "warning", "locked", "lock"}


def _warning_triggered(record: Mapping[str, Any]) -> bool:
    if any(key in record for key in ("warning", "warning_shown", "warning_triggered")):
        return _as_bool(record.get("warning") or record.get("warning_shown") or record.get("warning_triggered"))
    final = str(record.get("final") or record.get("decision") or "").strip().lower()
    return final in _WARNING_FINALS


def _lock_triggered(record: Mapping[str, Any]) -> bool:
    if any(key in record for key in ("lock", "locked", "lock_triggered")):
        return _as_bool(record.get("lock") or record.get("locked") or record.get("lock_triggered"))
    final = str(record.get("final") or record.get("decision") or "").strip().lower()
    return final in _LOCK_FINALS


def _low_quality(record: Mapping[str, Any]) -> bool:
    reasons = _reason_codes(record)
    if reasons.intersection(_LOW_QUALITY_REASONS):
        return True
    if "quality_ok" in record and not _as_bool(record.get("quality_ok")):
        return True
    score = _as_float(record.get("quality_score"), default=None)
    return score is not None and score < 0.50


def _confirmation_seconds(record: Mapping[str, Any]) -> float | None:
    for key in ("time_to_confirm_intruder_seconds", "confirm_elapsed_seconds", "confirmation_seconds"):
        value = _as_float(record.get(key), default=None)
        if value is not None and value >= 0:
            return value
    return None


def _coverage_status(beta_coverage: Mapping[str, Any] | None) -> Dict[str, Any]:
    coverage = dict(beta_coverage or {})
    users = int(_as_float(coverage.get("user_count"), 0.0) or 0)
    windows_devices = int(_as_float(coverage.get("windows_device_count"), 0.0) or 0)
    dpi_profiles = int(_as_float(coverage.get("dpi_profile_count"), 0.0) or 0)
    keyboard_layouts = int(_as_float(coverage.get("keyboard_layout_count"), 0.0) or 0)
    language_contexts = int(_as_float(coverage.get("language_context_count"), 0.0) or 0)
    observation_hours = float(_as_float(coverage.get("total_observation_hours"), 0.0) or 0.0)
    missing: list[str] = []
    if users < 20:
        missing.append("minimum_20_beta_users")
    if users > 50:
        missing.append("closed_beta_user_count_over_50_review_required")
    if windows_devices < 1:
        missing.append("windows_device_coverage")
    if dpi_profiles < 2:
        missing.append("dpi_variation")
    if keyboard_layouts < 2:
        missing.append("keyboard_layout_variation")
    if language_contexts < 2:
        missing.append("language_or_context_variation")
    if observation_hours < 10.0:
        missing.append("minimum_observation_hours")
    return {
        "user_count": users,
        "windows_device_count": windows_devices,
        "dpi_profile_count": dpi_profiles,
        "keyboard_layout_count": keyboard_layouts,
        "language_context_count": language_contexts,
        "total_observation_hours": observation_hours,
        "closed_beta_ready": not missing,
        "missing": missing,
    }


def calculate_user_facing_safety_metrics(
    decisions: Sequence[Mapping[str, Any]] | None = None,
    *,
    observation_seconds: float | None = None,
    beta_coverage: Mapping[str, Any] | None = None,
    conservative_target_false_locks: int = 0,
) -> Dict[str, Any]:
    """Calculate privacy-preserving beta safety metrics from decision summaries.

    Input records must be decision/session summaries only. Raw keyboard/mouse events,
    feature vectors, or screenshots are intentionally neither required nor copied.
    """
    records = [dict(item) for item in (decisions or []) if isinstance(item, Mapping)]
    total = len(records)
    legit_total = 0
    intruder_total = 0
    false_rejects = 0
    false_accepts = 0
    warnings = 0
    locks = 0
    false_locks = 0
    low_quality = 0
    startup_post_idle_warnings = 0
    confirm_times: list[float] = []
    derived_seconds = 0.0

    for record in records:
        truth_intruder = _truth_is_intruder(record)
        predicted_intruder = _predicted_intruder(record)
        warning = _warning_triggered(record)
        locked = _lock_triggered(record)
        reasons = _reason_codes(record)
        if truth_intruder:
            intruder_total += 1
            if not predicted_intruder and not locked:
                false_accepts += 1
            confirm_seconds = _confirmation_seconds(record)
            if confirm_seconds is not None:
                confirm_times.append(confirm_seconds)
        else:
            legit_total += 1
            if predicted_intruder or locked:
                false_rejects += 1
            if locked:
                false_locks += 1
        if warning:
            warnings += 1
            if reasons.intersection(_STARTUP_POST_IDLE_REASONS):
                startup_post_idle_warnings += 1
        if locked:
            locks += 1
        if _low_quality(record):
            low_quality += 1
        derived_seconds += float(_as_float(record.get("duration_seconds"), 0.0) or 0.0)

    effective_seconds = float(observation_seconds or 0.0) or derived_seconds
    hours = effective_seconds / 3600.0 if effective_seconds > 0 else 0.0
    coverage = _coverage_status(beta_coverage)
    return {
        "schema_version": SAFETY_METRICS_SCHEMA_VERSION,
        "privacy_preserving": True,
        "raw_biometric_data_included": False,
        "frr_user": _safe_rate(false_rejects, legit_total),
        "far_intruder": _safe_rate(false_accepts, intruder_total),
        "warning_per_hour": _safe_rate(warnings, hours) if hours > 0 else None,
        "lock_per_hour": _safe_rate(locks, hours) if hours > 0 else None,
        "false_lock_count": int(false_locks),
        "time_to_confirm_intruder": float(mean(confirm_times)) if confirm_times else None,
        "low_quality_decision_rate": _safe_rate(low_quality, total),
        "startup_post_idle_warning_rate": _safe_rate(startup_post_idle_warnings, warnings),
        "counts": {
            "decision_count": int(total),
            "legitimate_decision_count": int(legit_total),
            "intruder_decision_count": int(intruder_total),
            "warning_count": int(warnings),
            "lock_count": int(locks),
            "false_reject_count": int(false_rejects),
            "false_accept_count": int(false_accepts),
            "low_quality_decision_count": int(low_quality),
            "startup_post_idle_warning_count": int(startup_post_idle_warnings),
        },
        "observation_hours": float(hours),
        "data_coverage": coverage,
        "conservative_beta_target": {
            "false_lock_count_max": int(conservative_target_false_locks),
            "target": "zero_or_near_zero_false_locks",
        },
    }
