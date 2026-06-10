"""Extracted implementation section for `bridge/refresh_runtime_helpers.py`."""
from __future__ import annotations
from importlib import import_module
import logging
import re
import time
from typing import Any, Dict, Optional
from bridge import session_runtime_helpers as _process_helpers
from bridge.shared import read_session_state
from bridge.qt_thread_dispatch import dispatch_to_qt_thread, is_qt_main_thread
from bioauth_runtime import runtime_boundary

def check_worker_pair_liveness(self) -> Dict[str, Any]:
    """Return supervisor worker-pair health for display only.

    Refresh no longer starts, stops, or recovers logger/monitor workers.
    Enforcement of the recommended action belongs to the supervisor.
    """
    now = time.time()
    last_check = float(getattr(self, "_worker_pair_last_check_at", 0.0) or 0.0)
    if now - last_check < _WORKER_PAIR_CHECK_INTERVAL_SEC:
        cached = getattr(self, "_worker_pair_status_cache", {})
        return dict(cached) if isinstance(cached, dict) else {}
    self._worker_pair_last_check_at = now
    state = getattr(self, "_runtime_state", {})
    if not isinstance(state, dict):
        return {}
    try:
        from bioauth_runtime.supervisor.worker_health import classify_worker_pair

        result = classify_worker_pair(self, state).as_dict()
        self._worker_pair_status_cache = dict(result)
        debug = getattr(self, "_debug_trace", None)
        if callable(debug) and str(result.get("recommended_action") or "ok") != "ok":
            debug("worker_pair", "worker pair health observed", payload=result, level="warn")
        return dict(result)
    except Exception:
        _LOGGER.debug("check_worker_pair_liveness failed safely", exc_info=True)
        return {}

def _facade():
    return import_module("bridge.refresh_mixin")

def _shadow_logger_process_key(self) -> str:
    helper = getattr(self, "_shadow_logger_process_key", None)
    if callable(helper):
        return str(helper() or "")
    user = _facade().slugify_username((getattr(self, "_current_user", {}) or {}).get("user_id", "") or "") or "user"
    return f"shadow_logger_user_{user}"

def _shadow_monitor_process_key(self) -> str:
    helper = getattr(self, "_shadow_monitor_process_key", None)
    if callable(helper):
        return str(helper() or "")
    user = _facade().slugify_username((getattr(self, "_current_user", {}) or {}).get("user_id", "") or "") or "user"
    return f"shadow_monitor_user_{user}"

def _shadow_logger_stop_control_name(self) -> str:
    helper = getattr(self, "_shadow_logger_stop_control_name", None)
    if callable(helper):
        return str(helper() or "")
    return _shadow_logger_process_key(self)

def _shadow_monitor_stop_control_name(self) -> str:
    helper = getattr(self, "_shadow_monitor_stop_control_name", None)
    if callable(helper):
        return str(helper() or "")
    return _shadow_monitor_process_key(self)

def _safe_dashboard_error_text(error: Any) -> str:
    text = str(error or "").strip().replace("\r", " ").replace("\n", " ")
    if not text:
        return ""
    # Keep UI-visible errors honest but avoid leaking local paths or long internals.
    text = re.sub(r"([A-Za-z]:\\|/)[^\s]+", "[path]", text)
    text = " ".join(text.split())
    return text[:180]

def _ensure_dashboard_state_fields(self) -> None:
    defaults = {
        "_dashboard_snapshot_loading": False,
        "_dashboard_snapshot_stale": False,
        "_dashboard_snapshot_updating": False,
        "_dashboard_last_refresh_duration_ms": 0,
        "_dashboard_last_snapshot_duration_ms": 0,
        "_dashboard_last_refresh_error": "",
        "_dashboard_last_refresh_reason": "",
        "_dashboard_last_refresh_completed_at": 0.0,
    }
    for name, value in defaults.items():
        if not hasattr(self, name):
            setattr(self, name, value)

def dashboard_state_payload(self) -> Dict[str, Any]:
    _ensure_dashboard_state_fields(self)
    history_loading = bool(
        getattr(self, "_dashboard_full_history_loading", False)
        or getattr(self, "_dashboard_full_history_refresh_inflight", False)
    )
    snapshot_loading = bool(getattr(self, "_dashboard_snapshot_loading", False))
    snapshot_updating = bool(
        getattr(self, "_dashboard_snapshot_updating", False)
        or getattr(self, "_dashboard_snapshot_refresh_inflight", False)
    )
    stale = bool(getattr(self, "_dashboard_snapshot_stale", False))
    error = _safe_dashboard_error_text(getattr(self, "_dashboard_last_refresh_error", ""))
    if error:
        status = "error"
    elif snapshot_loading:
        status = "loading"
    elif history_loading:
        status = "history_loading"
    elif snapshot_updating:
        status = "updating"
    elif stale:
        status = "stale"
    else:
        status = "ready"
    return {
        "status": status,
        "loading": snapshot_loading,
        "updating": bool(snapshot_updating or history_loading),
        "stale": stale,
        "snapshotLoading": snapshot_loading,
        "snapshotUpdating": snapshot_updating,
        "snapshotStale": stale,
        "historyLoading": history_loading,
        "historyRequested": bool(getattr(self, "_dashboard_full_history_requested", False)),
        "historyLoaded": bool(
            getattr(self, "_dashboard_full_history_user", "")
            and isinstance(getattr(self, "_dashboard_full_history_cache", {}), dict)
            and bool(getattr(self, "_dashboard_full_history_cache", {}))
            and not history_loading
        ),
        "historyError": _safe_dashboard_error_text(getattr(self, "_dashboard_full_history_error", "")),
        "refreshInflight": bool(getattr(self, "_refresh_inflight", False)),
        "snapshotInflight": bool(getattr(self, "_dashboard_snapshot_refresh_inflight", False)),
        "lastRefreshDurationMs": int(getattr(self, "_dashboard_last_refresh_duration_ms", 0) or 0),
        "lastSnapshotDurationMs": int(getattr(self, "_dashboard_last_snapshot_duration_ms", 0) or 0),
        "lastRefreshError": error,
        "lastRefreshReason": str(getattr(self, "_dashboard_last_refresh_reason", "") or ""),
        "lastRefreshCompletedAt": float(getattr(self, "_dashboard_last_refresh_completed_at", 0.0) or 0.0),
    }

def is_dashboard_visible(self) -> bool:
    return bool(getattr(self, "_dashboard_visible", True))

def emit_dashboard_state_changed(self) -> None:
    if not is_dashboard_visible(self):
        return
    signal = getattr(self, "dashboardStateChanged", None)
    if signal is not None and hasattr(signal, "emit"):
        signal.emit()

def set_dashboard_visible(self, visible: bool) -> None:
    _ensure_refresh_request_state(self)
    previous = is_dashboard_visible(self)
    next_visible = bool(visible)
    self._dashboard_visible = next_visible
    if previous == next_visible:
        return
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug(
            "refresh",
            "dashboard visibility changed",
            payload={"dashboard_visible": next_visible},
            level="debug",
        )
    if next_visible:
        facade = _facade()
        now = facade.time.time()
        last_at = float(getattr(self, "_last_dashboard_visible_refresh_requested_at", 0.0) or 0.0)
        if not bool(getattr(self, "_dashboard_visible_refresh_pending", False)) and (now - last_at) >= 0.25:
            self._last_dashboard_visible_refresh_requested_at = now
            self._dashboard_visible_refresh_pending = True
            request_refresh(self, reason="ui:dashboard_visible", force=True)
    else:
        self._dashboard_visible_refresh_pending = False

def set_dashboard_state(
    self,
    *,
    loading: Optional[bool] = None,
    updating: Optional[bool] = None,
    stale: Optional[bool] = None,
    last_refresh_duration_ms: Optional[int] = None,
    last_snapshot_duration_ms: Optional[int] = None,
    last_refresh_error: Optional[Any] = None,
    last_refresh_reason: Optional[str] = None,
    completed_at: Optional[float] = None,
    emit: bool = True,
) -> Dict[str, Any]:
    _ensure_dashboard_state_fields(self)
    before = dashboard_state_payload(self)
    if loading is not None:
        self._dashboard_snapshot_loading = bool(loading)
    if updating is not None:
        self._dashboard_snapshot_updating = bool(updating)
    if stale is not None:
        self._dashboard_snapshot_stale = bool(stale)
    if last_refresh_duration_ms is not None:
        self._dashboard_last_refresh_duration_ms = max(0, int(last_refresh_duration_ms or 0))
    if last_snapshot_duration_ms is not None:
        self._dashboard_last_snapshot_duration_ms = max(0, int(last_snapshot_duration_ms or 0))
    if last_refresh_error is not None:
        self._dashboard_last_refresh_error = _safe_dashboard_error_text(last_refresh_error)
    if last_refresh_reason is not None:
        self._dashboard_last_refresh_reason = str(last_refresh_reason or "")[:96]
    if completed_at is not None:
        try:
            self._dashboard_last_refresh_completed_at = max(0.0, float(completed_at))
        except (TypeError, ValueError, OverflowError):
            self._dashboard_last_refresh_completed_at = 0.0
    after = dashboard_state_payload(self)
    if emit and after != before and is_dashboard_visible(self):
        emit_dashboard_state_changed(self)
    return after

def set_status(self, message: str, tone: str = "info") -> bool:
    new_message = str(message or "")
    new_tone = str(tone or "info")
    # Face operations own their status text while they are opening/capturing/
    # verifying with the camera. Dashboard refreshes must not overwrite messages
    # like "Capturing face samples" with generic product/dashboard text.
    if bool(getattr(self, "_face_operation_inflight", False)) and not bool(getattr(self, "_face_status_update_allowed", False)):
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("status", "status update suppressed during face operation", payload={"tone": new_tone})
        return False
    if new_message == getattr(self, "_status_message", "") and new_tone == getattr(self, "_status_tone", "info"):
        return False
    self._status_message = new_message
    self._status_tone = new_tone
    self.statusChanged.emit()
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("status", new_message or "(status cleared)", payload={"tone": new_tone})
    return True
