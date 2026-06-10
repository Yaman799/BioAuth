"""Extracted implementation section for `bridge/refresh_dashboard_helpers.py`."""
from __future__ import annotations
import logging
import os
from importlib import import_module
from typing import Any, Dict, List
from bioauth_runtime import runtime_boundary
from bridge.runtime_labels import runtime_policy_display_fields
from bridge import refresh_runtime_helpers as _refresh_state
from bridge.qt_thread_dispatch import dispatch_to_qt_thread

def _facade():
    return import_module("bridge.refresh_mixin")

def _production_approval_status_for_user(*args, **kwargs):
    from metadata_core.production_approval import production_approval_status_for_user

    return production_approval_status_for_user(*args, **kwargs)

def _time_now(facade) -> float:
    clock = getattr(getattr(facade, "time", None), "perf_counter", None) or getattr(getattr(facade, "time", None), "time", None)
    if callable(clock):
        return float(clock())
    return 0.0

def _elapsed_ms(facade, started_at: float) -> int:
    try:
        return max(0, int(round((_time_now(facade) - float(started_at)) * 1000.0)))
    except (TypeError, ValueError, OverflowError):
        return 0

def _coerce_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0

def _dashboard_debug_timing(raw: Dict[str, Any] | None, *, cache_hit: bool, session_count: int | None = None) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    payload: Dict[str, Any] = {}
    for key in _DASHBOARD_TIMING_FIELDS:
        if key == "cache_hit":
            payload[key] = bool(cache_hit)
        elif key == "dashboard_snapshot_mode":
            payload[key] = str(source.get(key) or "")
        elif key in {"session_index_hit", "session_index_rebuild", "model_metadata_cache_hit", "runtime_validation_cache_hit"}:
            payload[key] = bool(source.get(key, False))
        elif key == "session_count":
            payload[key] = _coerce_nonnegative_int(session_count if session_count is not None else source.get(key, 0))
        else:
            payload[key] = _coerce_nonnegative_int(source.get(key, 0))
    return payload

def _set_dashboard_debug_timing(self, raw: Dict[str, Any] | None, *, cache_hit: bool, session_count: int | None = None) -> Dict[str, Any]:
    payload = _dashboard_debug_timing(raw, cache_hit=cache_hit, session_count=session_count)
    self._last_dashboard_snapshot_timing = payload
    return payload

def _add_dashboard_view_timing(self, elapsed_ms: int) -> None:
    timing = getattr(self, "_last_dashboard_snapshot_timing", None)
    if not isinstance(timing, dict):
        return
    payload = dict(timing)
    payload["dashboard_normalization_ms"] = _coerce_nonnegative_int(payload.get("dashboard_normalization_ms", 0)) + _coerce_nonnegative_int(elapsed_ms)
    payload["dashboard_total_ms"] = _coerce_nonnegative_int(payload.get("dashboard_total_ms", 0)) + _coerce_nonnegative_int(elapsed_ms)
    self._last_dashboard_snapshot_timing = _dashboard_debug_timing(payload, cache_hit=bool(payload.get("cache_hit")), session_count=payload.get("session_count"))

def _production_approval_refresh_signature(profile_view: Dict[str, Any]) -> str:
    production = profile_view.get("production_approval_state") if isinstance(profile_view, dict) else {}
    if not isinstance(production, dict):
        production = {}
    parts = [
        str(production.get("status") or ""),
        str(production.get("phase") or ""),
        str(production.get("candidate_status") or production.get("candidateStatus") or ""),
        str(production.get("reason_code") or production.get("reasonCode") or ""),
        str(production.get("protected_sessions_available") or production.get("protectedSessionsAvailable") or ""),
        str(production.get("candidate_artifact_digest") or production.get("candidateArtifactDigest") or ""),
    ]
    return "|".join(parts)[:512]

def _should_observe_production_approval_state(self, profile_view: Dict[str, Any], *, source: str = "dashboard_refresh") -> bool:
    state = getattr(self, "_runtime_state", {})
    state = state if isinstance(state, dict) else {}
    try:
        flow = str(self._session_flow(state) or "")
    except Exception:
        flow = ""
    if runtime_boundary.is_commercial_protected_runtime(state, flow=flow):
        return False
    facade = _facade()
    now = _time_now(facade) or getattr(facade.time, "time", lambda: 0.0)()
    signature = _production_approval_refresh_signature(profile_view)
    last_signature = str(getattr(self, "_last_dashboard_production_observe_signature", "") or "")
    try:
        last_at = float(getattr(self, "_last_dashboard_production_observe_at", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        last_at = 0.0
    active = bool(getattr(self, "_training_in_progress", False) or getattr(self, "_pending_monitor_start", False) or getattr(self, "_pending_logger_start", False))
    interval = 5.0 if active else 15.0
    if str(source or "") != "dashboard_refresh":
        interval = 0.0
    if signature != last_signature or (now - last_at) >= interval:
        self._last_dashboard_production_observe_signature = signature
        self._last_dashboard_production_observe_at = now
        return True
    return False

def format_elapsed(self, started_at: Any) -> str:
    facade = _facade()
    try:
        if started_at in (None, ""):
            return "--"
        total = max(0, int(facade.time.time() - float(started_at)))
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except (TypeError, ValueError, OverflowError):
        return "--"

def _runtime_age_seconds(now: float, value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        age = float(now) - float(value)
        if age < 0:
            return 0.0
        return round(age, 1)
    except (TypeError, ValueError, OverflowError):
        return None

def _runtime_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)

def _runtime_elapsed_seconds(now: float, started_at: Any) -> float | None:
    try:
        if started_at in (None, ""):
            return None
        return max(0.0, float(now) - float(started_at))
    except (TypeError, ValueError, OverflowError):
        return None

def _recent_risk_trend(values: Any) -> List[float]:
    trend: List[float] = []
    if not isinstance(values, (list, tuple)):
        return trend
    for raw_value in values[-7:]:
        try:
            trend.append(round(float(raw_value), 2))
        except (TypeError, ValueError, OverflowError):
            continue
    return trend if len(trend) >= 2 else []

def _drift_channel_status(
    *,
    active: bool,
    technical_failure: bool,
    awaiting_evidence: bool,
    telemetry_fresh: bool,
    capture_fresh: bool,
    event_count: int,
) -> tuple[str, str]:
    if technical_failure:
        return "Monitor unavailable", "danger"
    if not active:
        return "Preview only", "neutral"
    if event_count <= 0:
        return "Waiting for capture", "warn"
    if capture_fresh or telemetry_fresh:
        return "Capture live", "success"
    if awaiting_evidence:
        return "Capture-only", "warn"
    return "Capture-only", "warn"

def _combined_drift_status(
    *,
    active: bool,
    technical_failure: bool,
    awaiting_evidence: bool,
    telemetry_fresh: bool,
    window_count: int,
    quality_ok_windows: int,
) -> tuple[str, str]:
    if technical_failure:
        return "Monitor unavailable", "danger"
    if not active:
        return "Preview only", "neutral"
    if awaiting_evidence or window_count <= 0:
        return "Collecting evidence", "warn"
    if not telemetry_fresh:
        return "Monitor unavailable", "warn"
    if quality_ok_windows <= 0:
        return "Collecting evidence", "warn"
    return "Live", "success"

def _evidence_capture_text(label: str, count: int, active: bool, fresh: bool) -> str:
    if not active:
        return f"No protected session is active. {label} evidence will update during live capture."
    freshness = "fresh" if fresh else "not fresh yet"
    return f"{label} events captured: {count}. Capture telemetry is {freshness}."
