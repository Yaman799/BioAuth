"""Worker heartbeat access for the commercial runtime supervisor."""
from __future__ import annotations

from typing import Any, Dict, Optional


def _legacy():
    from bridge import session_runtime_helpers
    return session_runtime_helpers


def read_matching(bridge: Any, kind: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Read a heartbeat only when it matches the current protected session."""
    return dict(_legacy()._read_matching_worker_heartbeat(bridge, kind, state or {}) or {})


def clear_current_session() -> None:
    """Clear worker heartbeat files before a new protected session starts."""
    facade = _legacy()._facade()
    try:
        facade.clear_worker_heartbeat("logger")
        facade.clear_worker_heartbeat("monitor")
    except Exception:
        pass


def merge_into_state(bridge: Any, state: Optional[Dict[str, Any]] = None, *, persist: bool = False) -> Dict[str, Any]:
    """Overlay matching worker heartbeat facts onto bridge runtime state."""
    return dict(_legacy().merge_worker_heartbeats_into_state(bridge, state or {}, persist=persist) or {})


_STARTING_VALUES = {"", "starting", "protected_starting", "logger_starting", "monitor_starting"}


def normalize_protected_startup_ready_state(state: Optional[Dict[str, Any]]) -> tuple[Dict[str, Any], bool]:
    """Clear stale startup fields once logger and monitor are ready."""
    data = dict(state or {}) if isinstance(state, dict) else {}
    if str(data.get("session_kind") or "").strip().lower() != "protected":
        return data, False
    if not bool(data.get("active", False)):
        return data, False
    if not (bool(data.get("logger_ready")) and bool(data.get("monitor_ready"))):
        return data, False

    changed = False

    def set_if(key: str, value: Any) -> None:
        nonlocal changed
        if data.get(key) != value:
            data[key] = value
            changed = True

    set_if("pending_monitor_start", False)
    set_if("worker_heartbeat_waiting_for", "")
    set_if("logger_ready", True)
    set_if("monitor_ready", True)
    if bool(data.get("awaiting_evidence", True)):
        set_if("awaiting_evidence", True)

    flow = str(data.get("flow") or "").strip().lower()
    if flow in _STARTING_VALUES:
        set_if("flow", "protected_active")

    status = str(data.get("status") or "").strip().lower()
    if status in _STARTING_VALUES:
        set_if("status", "collecting_evidence")

    runtime_status = str(data.get("runtime_status") or "").strip().lower()
    if runtime_status in _STARTING_VALUES:
        set_if("runtime_status", "collecting")

    if not str(data.get("runtime_decision") or "").strip():
        set_if("runtime_decision", "pending")

    diag_code = str(data.get("runtime_diag_code") or data.get("runtime_diagnostic_code") or "").strip().lower()
    diag_reason = str(data.get("runtime_diag_reason") or data.get("runtime_diagnostic_reason") or "").strip().lower()
    if diag_code in {"", "protected_starting", "logger_starting", "monitor_starting"} or "waiting for logger readiness" in diag_reason:
        set_if("runtime_diag_code", "collecting_evidence")
        set_if("runtime_diag_reason", "awaiting evidence")
    return data, changed
