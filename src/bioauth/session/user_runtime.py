"""User-facing session runtime query helpers.

This module is the first Phase 12 extraction from
``bridge.session_runtime_helpers``.  It owns small USER-flow query helpers while
delegating shared/runtime internals back to the bridge compatibility module.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Optional


def _srh():
    return import_module("bridge.session_runtime_helpers")


def _active_state_for_current_user(bridge: Any) -> Dict[str, Any]:
    try:
        state = bridge._active_state_for_current_user()
    except Exception:
        state = {}
    return state if isinstance(state, dict) else {}


def normal_enrollment_logger_flow(bridge: Any, state: Optional[Dict[str, Any]] = None) -> str:
    srh = _srh()
    flow = srh._normal_user_session_flow(bridge, state)
    if flow == "enrollment_active":
        return "enrollment_active"
    if srh._normal_logger_process_running(bridge):
        return "enrollment_active"
    return "idle"


def normal_enrollment_logger_stop_available(bridge: Any, state: Optional[Dict[str, Any]] = None) -> bool:
    srh = _srh()
    if not getattr(bridge, "_current_user", None):
        return False
    state = state if isinstance(state, dict) else None
    if state is None:
        state = _active_state_for_current_user(bridge)
    state = state if isinstance(state, dict) else {}
    if srh._state_is_shadow_evidence(state):
        return False
    if bool(getattr(bridge, "_pending_shadow_evidence_monitor_start", False)):
        return False
    if srh._shadow_logger_start_pending(bridge):
        return False
    if bool(getattr(bridge, "_pending_logger_start", False)):
        return srh._pending_logger_kind(bridge) == "enrollment"
    session_kind = str(state.get("session_kind") or state.get("runtime_mode") or state.get("mode") or "").strip().lower()
    if bool(state.get("active")):
        return session_kind == "enrollment"
    return srh._normal_logger_process_running(bridge)


def production_monitor_flow(bridge: Any, state: Optional[Dict[str, Any]] = None) -> str:
    srh = _srh()
    if not srh._production_monitor_process_running(bridge):
        return "idle"
    flow = srh._normal_user_session_flow(bridge, state)
    return flow if flow.startswith("protected") else "protected_active"


def protected_session_stop_available(bridge: Any, state: Optional[Dict[str, Any]] = None) -> bool:
    """Return True when Stop Monitor can safely finalize a protected session."""
    srh = _srh()
    if not getattr(bridge, "_current_user", None):
        return False
    if srh._production_monitor_process_running(bridge):
        return True
    if srh._normal_logger_start_pending(bridge) and srh._pending_logger_kind(bridge) == "protected":
        return True
    try:
        resolved_state = state if isinstance(state, dict) else bridge._active_state_for_current_user()
    except Exception:
        resolved_state = {}
    resolved_state = resolved_state if isinstance(resolved_state, dict) else {}
    if srh._state_is_shadow_evidence(resolved_state):
        return False
    session_kind = str(
        resolved_state.get("session_kind")
        or resolved_state.get("runtime_mode")
        or resolved_state.get("mode")
        or ""
    ).strip().lower()
    if session_kind != "protected":
        return False
    if srh._normal_logger_process_running(bridge):
        return True
    if bool(resolved_state.get("active")):
        return True
    flow = str(resolved_state.get("flow") or "").strip().lower()
    return flow.startswith("protected") and str(resolved_state.get("session_state") or "").strip().lower() not in {"stopped", "idle", "ended", "complete", "completed"}


def worker_diagnostics_snapshot(bridge: Any, key: str) -> Dict[str, Any]:
    """Return a snapshot of stdout/stderr tail for a worker process."""
    srh = _srh()
    diag = srh._worker_diag_map(bridge).get(str(key))
    if not isinstance(diag, dict):
        return {}
    snapshot = dict(diag)
    snapshot["stdout_tail"] = list(diag.get("stdout_tail") or [])[-srh._WORKER_TAIL_LIMIT:]
    snapshot["stderr_tail"] = list(diag.get("stderr_tail") or [])[-srh._WORKER_TAIL_LIMIT:]
    return snapshot


def worker_failure_detail(bridge: Any, key: str, *, fallback: str) -> tuple[str, Dict[str, Any]]:
    srh = _srh()
    diag = worker_diagnostics_snapshot(bridge, key)
    exit_code = diag.get("exit_code")
    reason = str(fallback or "worker_failed")
    if exit_code is not None:
        reason = f"{reason} (exit code {exit_code})"
    stderr_tail = [line for line in list(diag.get("stderr_tail") or []) if line]
    stdout_tail = [line for line in list(diag.get("stdout_tail") or []) if line]
    if stderr_tail:
        reason = f"{reason}: {stderr_tail[-1]}"
    elif stdout_tail:
        reason = f"{reason}: {stdout_tail[-1]}"
    return srh._safe_worker_line(reason), diag
