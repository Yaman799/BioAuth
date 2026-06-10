"""Runtime readiness and calibration maturity policy helpers.

This module is intentionally dependency-light so the monitor can apply safety
policy without importing the ML stack. It does not score features or change the
model's numeric risk output; it only describes when production auto-lock is
allowed.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Sequence

CALIBRATION_MATURITY_POLICY_VERSION = "calibration-maturity-v1"
MIN_MATURITY_TRUSTED_SESSIONS = 8
MIN_MATURITY_GOOD_WINDOWS = 60
MIN_MATURITY_DURATION_SECONDS = 300.0
MIN_MATURITY_CONTEXT_COVERAGE = 1
MIN_MATURITY_MODALITY_COVERAGE = 2

# Phase 5 Hybrid Direct Test contract defaults. These constants are safety
# assertions only; this phase does not enable device influence or lock behavior.
DEVELOPER_DIRECT_TEST_ENABLED_DEFAULT = False
HYBRID_DIRECT_CAN_INFLUENCE_DEVICE_DEFAULT = False
EXPERIMENT_CAN_LOCK_ALONE = False
NO_SINGLE_MODEL_CAN_LOCK = True

_IMMATURE_STATUS = "immature_warning_only"
_MATURE_STATUS = "mature_lock_allowed"
_ONBOARDING_STATUS = "onboarding_warning_only"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _records_from_selection(selection_summary: Mapping[str, Any] | None) -> list[Dict[str, Any]]:
    selection = dict(selection_summary or {})
    records: list[Dict[str, Any]] = []
    for pool_name in ("enrollment", "protected"):
        pool = dict((selection.get("positive_pool") or {}).get(pool_name) or {})
        for item in list(pool.get("included_records") or []):
            if isinstance(item, Mapping):
                record = dict(item)
                record.setdefault("session_kind", pool_name)
                records.append(record)
    if not records:
        for item in list(selection.get("included_sessions") or []):
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role and role != "positive":
                continue
            records.append(dict(item))
    return records


def _record_duration_seconds(record: Mapping[str, Any]) -> float:
    indicators = dict(record.get("quality_indicators") or {})
    return max(
        _safe_float(indicators.get("duration_seconds")),
        _safe_float(record.get("duration_seconds")),
    )


def _sample_context(sample: Mapping[str, Any]) -> str:
    for key in ("context", "behavior_context", "used_context", "route_context"):
        value = str(sample.get(key) or "").strip().lower()
        if value:
            return value
    kb_share = _safe_float(sample.get("session_kb_share"), -1.0)
    ms_share = _safe_float(sample.get("session_ms_share"), -1.0)
    if kb_share < 0.0 and ms_share < 0.0:
        for prefix in ("scale_20s", "scale_10s", "scale_5s"):
            kb_share = max(kb_share, _safe_float(sample.get(f"{prefix}_session_kb_share"), -1.0))
            ms_share = max(ms_share, _safe_float(sample.get(f"{prefix}_session_ms_share"), -1.0))
    if kb_share >= 0.70 and kb_share >= ms_share:
        return "keyboard_heavy"
    if ms_share >= 0.70 and ms_share >= kb_share:
        return "mouse_heavy"
    if kb_share >= 0.0 or ms_share >= 0.0:
        return "mixed"
    return "unknown"


def _modality_from_record(record: Mapping[str, Any]) -> str:
    value = str(record.get("modality_band") or "").strip().lower()
    if value:
        return value
    indicators = dict(record.get("quality_indicators") or {})
    kb_share = _safe_float(indicators.get("keyboard_share"), -1.0)
    if kb_share >= 0.70:
        return "keyboard_heavy"
    if 0.0 <= kb_share <= 0.30:
        return "mouse_heavy"
    if kb_share >= 0.0:
        return "mixed"
    return "unknown"


def _modality_from_sample(sample: Mapping[str, Any]) -> str:
    context = _sample_context(sample)
    if context in {"keyboard_heavy", "mouse_heavy", "mixed"}:
        return context
    return "unknown"


def build_calibration_maturity(
    *,
    selection_summary: Mapping[str, Any] | None = None,
    positive_samples: Sequence[Mapping[str, Any]] | None = None,
    positive_sample_sources: Sequence[str] | None = None,
    user_calibration: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a metadata gate that decides whether runtime auto-lock may be used.

    Positive samples are already chosen by the training selection pipeline. This
    function never adds sessions to training; it only summarizes readiness.
    """

    records = _records_from_selection(selection_summary)
    unique_session_names = {
        str(record.get("session_name") or record.get("session_path") or "").strip()
        for record in records
        if str(record.get("session_name") or record.get("session_path") or "").strip()
    }
    if not unique_session_names and positive_sample_sources:
        unique_session_names = {str(name or "").strip() for name in positive_sample_sources if str(name or "").strip()}

    enrollment_records = [record for record in records if str(record.get("session_kind") or "").strip().lower() == "enrollment"]
    trusted_sessions = len(unique_session_names)
    enrollment_sessions = len({str(record.get("session_name") or record.get("session_path") or "") for record in enrollment_records if str(record.get("session_name") or record.get("session_path") or "")})
    if enrollment_sessions <= 0:
        enrollment_sessions = trusted_sessions

    samples = [dict(sample or {}) for sample in list(positive_samples or [])]
    good_windows = len(samples)
    total_duration = sum(_record_duration_seconds(record) for record in records)
    if total_duration <= 0.0:
        total_duration = max(0.0, float(good_windows) * 5.0)

    sample_contexts = {_sample_context(sample) for sample in samples}
    record_modalities = {_modality_from_record(record) for record in records}
    sample_modalities = {_modality_from_sample(sample) for sample in samples}
    contexts = sorted(ctx for ctx in sample_contexts if ctx and ctx != "unknown")
    modalities = sorted(mod for mod in (record_modalities | sample_modalities) if mod and mod != "unknown")
    production_contexts = [ctx for ctx in contexts if ctx != "short_session"]
    production_modalities = [mod for mod in modalities if mod in {"keyboard_heavy", "mouse_heavy", "mixed"}]

    requirements = {
        "minimum_trusted_sessions": int(MIN_MATURITY_TRUSTED_SESSIONS),
        "minimum_good_windows": int(MIN_MATURITY_GOOD_WINDOWS),
        "minimum_duration_seconds": float(MIN_MATURITY_DURATION_SECONDS),
        "minimum_context_coverage": int(MIN_MATURITY_CONTEXT_COVERAGE),
        "minimum_modality_coverage": int(MIN_MATURITY_MODALITY_COVERAGE),
    }
    counts = {
        "trusted_sessions": int(trusted_sessions),
        "enrollment_sessions": int(enrollment_sessions),
        "good_windows": int(good_windows),
        "duration_seconds": round(float(total_duration), 3),
        "context_coverage": int(len(set(production_contexts))),
        "modality_coverage": int(len(set(production_modalities))),
        "contexts": production_contexts,
        "modalities": production_modalities,
    }

    reason_codes: list[str] = []
    if counts["trusted_sessions"] < requirements["minimum_trusted_sessions"]:
        reason_codes.append("needs_more_trusted_sessions")
    if counts["good_windows"] < requirements["minimum_good_windows"]:
        reason_codes.append("needs_more_good_windows")
    if counts["duration_seconds"] < requirements["minimum_duration_seconds"]:
        reason_codes.append("needs_more_duration")
    if counts["context_coverage"] < requirements["minimum_context_coverage"]:
        reason_codes.append("needs_context_coverage")
    if counts["modality_coverage"] < requirements["minimum_modality_coverage"]:
        reason_codes.append("needs_modality_coverage")

    calibration_payload = dict(user_calibration or {})
    if calibration_payload and not bool(calibration_payload.get("maturity_flag")):
        reason_codes.append("user_calibration_not_mature")

    mature = not reason_codes
    phase = _MATURE_STATUS if mature else (_ONBOARDING_STATUS if trusted_sessions <= 0 else _IMMATURE_STATUS)
    return {
        "version": CALIBRATION_MATURITY_POLICY_VERSION,
        "mature": bool(mature),
        "lock_allowed": bool(mature),
        "progressive_phase": phase,
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "requirements": requirements,
        "counts": counts,
        "message": "Lock allowed after calibration maturity gate passed." if mature else "Warning-only protection until calibration maturity gate passes.",
    }


def normalize_calibration_maturity(meta: Mapping[str, Any] | None) -> Dict[str, Any]:
    payload = dict(meta or {})
    maturity = payload.get("calibration_maturity")
    if isinstance(maturity, Mapping):
        normalized = dict(maturity)
        normalized.setdefault("version", CALIBRATION_MATURITY_POLICY_VERSION)
        normalized.setdefault("reason_codes", [])
        normalized.setdefault("requirements", {})
        normalized.setdefault("counts", {})
        normalized["mature"] = bool(normalized.get("mature"))
        normalized["lock_allowed"] = bool(normalized.get("lock_allowed") and normalized.get("mature"))
        normalized.setdefault("progressive_phase", _MATURE_STATUS if normalized["lock_allowed"] else _IMMATURE_STATUS)
        return normalized

    legacy = dict(payload.get("user_calibration") or {}) if isinstance(payload.get("user_calibration"), Mapping) else {}
    if bool(legacy.get("maturity_flag")):
        return {
            "version": "legacy-user-calibration",
            "mature": True,
            "lock_allowed": True,
            "progressive_phase": _MATURE_STATUS,
            "reason_codes": [],
            "requirements": {},
            "counts": {},
            "message": "Legacy user calibration maturity flag allows lock for backward compatibility.",
        }
    return {
        "version": CALIBRATION_MATURITY_POLICY_VERSION,
        "mature": False,
        "lock_allowed": False,
        "progressive_phase": _ONBOARDING_STATUS,
        "reason_codes": ["calibration_maturity_missing"],
        "requirements": {
            "minimum_trusted_sessions": int(MIN_MATURITY_TRUSTED_SESSIONS),
            "minimum_good_windows": int(MIN_MATURITY_GOOD_WINDOWS),
            "minimum_duration_seconds": float(MIN_MATURITY_DURATION_SECONDS),
            "minimum_context_coverage": int(MIN_MATURITY_CONTEXT_COVERAGE),
            "minimum_modality_coverage": int(MIN_MATURITY_MODALITY_COVERAGE),
        },
        "counts": {},
        "message": "Warning-only protection until calibration maturity metadata exists.",
    }


def maturity_progress_summary(maturity: Mapping[str, Any] | None) -> Dict[str, Any]:
    payload = normalize_calibration_maturity({"calibration_maturity": dict(maturity or {})}) if isinstance(maturity, Mapping) else normalize_calibration_maturity({})
    requirements = dict(payload.get("requirements") or {})
    counts = dict(payload.get("counts") or {})
    sessions_required = _safe_int(requirements.get("minimum_trusted_sessions"), MIN_MATURITY_TRUSTED_SESSIONS)
    windows_required = _safe_int(requirements.get("minimum_good_windows"), MIN_MATURITY_GOOD_WINDOWS)
    sessions = _safe_int(counts.get("trusted_sessions"), 0)
    windows = _safe_int(counts.get("good_windows"), 0)
    return {
        "mature": bool(payload.get("mature")),
        "lock_allowed": bool(payload.get("lock_allowed")),
        "progressive_phase": str(payload.get("progressive_phase") or _IMMATURE_STATUS),
        "required_sessions": sessions_required,
        "trusted_sessions": sessions,
        "remaining_sessions": max(0, sessions_required - sessions),
        "required_good_windows": windows_required,
        "good_windows": windows,
        "remaining_good_windows": max(0, windows_required - windows),
        "reason_codes": list(payload.get("reason_codes") or []),
        "message": str(payload.get("message") or ""),
    }


__all__ = [
    "CALIBRATION_MATURITY_POLICY_VERSION",
    "DEVELOPER_DIRECT_TEST_ENABLED_DEFAULT",
    "EXPERIMENT_CAN_LOCK_ALONE",
    "HYBRID_DIRECT_CAN_INFLUENCE_DEVICE_DEFAULT",
    "NO_SINGLE_MODEL_CAN_LOCK",
    "MIN_MATURITY_CONTEXT_COVERAGE",
    "MIN_MATURITY_DURATION_SECONDS",
    "MIN_MATURITY_GOOD_WINDOWS",
    "MIN_MATURITY_MODALITY_COVERAGE",
    "MIN_MATURITY_TRUSTED_SESSIONS",
    "build_calibration_maturity",
    "maturity_progress_summary",
    "normalize_calibration_maturity",
]
