"""Extracted implementation section for `bridge/session_runtime_helpers.py`."""
from __future__ import annotations
import json
import logging
import os
import re
import signal
import threading
import time
from collections import deque
from importlib import import_module
from typing import Any, Dict, List, Optional
from release_runtime import startup_protected_session_decision, write_release_runtime_event

def _request_refresh(self, reason: str, force: bool = False) -> None:
    request = getattr(self, "requestRefresh", None)
    if callable(request):
        request(reason, force)
        return
    legacy = getattr(self, "refreshNow", None)
    if callable(legacy):
        legacy()

def _facade():
    return import_module("bridge.session_mixin")

def _user_runtime():
    return import_module("bioauth.session.user_runtime")

def _heartbeat_age_sec(payload: Dict[str, Any]) -> float:
    try:
        ts = float(payload.get("heartbeat_at") or payload.get("logger_heartbeat_at") or payload.get("monitor_heartbeat_at") or 0.0)
        if ts <= 0:
            return 999999.0
        return max(0.0, time.time() - ts)
    except Exception:
        return 999999.0

def _worker_heartbeat_matches(state: Dict[str, Any], heartbeat: Dict[str, Any], *, kind: str, pending_session_id: str = "", pending_user: str = "") -> bool:
    if not isinstance(heartbeat, dict) or not heartbeat:
        return False
    session_id = str(state.get("session_id") or pending_session_id or "").strip()
    hb_session_id = str(heartbeat.get("session_id") or "").strip()
    if session_id and hb_session_id and hb_session_id != session_id:
        return False
    expected_user = str(state.get("user_id") or state.get("expected_user") or pending_user or "").strip()
    hb_user = str(heartbeat.get("user_id") or heartbeat.get("expected_user") or "").strip()
    if expected_user and hb_user:
        try:
            facade = _facade()
            if facade.slugify_username(expected_user) != facade.slugify_username(hb_user):
                return False
        except Exception:
            if expected_user != hb_user:
                return False
    hb_kind = str(heartbeat.get("worker_kind") or kind or "").strip().lower()
    return not hb_kind or hb_kind == str(kind or "").strip().lower()

def _is_terminal_protected_state(state: Optional[Dict[str, Any]]) -> bool:
    """Return True for protected states that worker heartbeats must not revive."""
    data = state if isinstance(state, dict) else {}
    if not data:
        return False
    session_kind = str(data.get("session_kind") or data.get("runtime_mode") or data.get("mode") or "").strip().lower()
    if session_kind and session_kind != "protected":
        return False
    if _is_resume_pending_lock_handoff(data):
        return True
    if bool(data.get("active")):
        return False
    session_state = str(data.get("session_state") or "").strip().lower()
    status = str(data.get("status") or data.get("runtime_status") or "").strip().lower()
    decision = str(data.get("decision") or "").strip().lower()
    flow = str(data.get("flow") or "").strip().lower()
    return (
        session_state in _TERMINAL_SESSION_STATES
        or status in _TERMINAL_RUNTIME_STATUSES
        or decision in {"stopped", "idle"}
        or (flow == "idle" and bool(data.get("stop_reason") or data.get("stopped_at")))
    )


def _is_resume_pending_lock_handoff(data: Dict[str, Any]) -> bool:
    """Return True for lock-controller handoff states awaiting unlock/resume."""
    status_values = {
        str(data.get("status") or "").strip().lower(),
        str(data.get("runtime_status") or "").strip().lower(),
    }
    explicit = bool(data.get("lock_controller_handoff") or data.get("lock_handoff_id"))
    resume_pending = bool(data.get("auto_resume_pending") or data.get("resume_after_unlock"))
    forced_lock = bool(data.get("forced_stop") or data.get("app_locked") or data.get("screen_locked"))
    expected_exit = bool(data.get("forced_stop_expected_monitor_exit") or data.get("monitor_exit_expected"))
    return (
        not bool(data.get("active"))
        and ("resume_pending" in status_values or resume_pending)
        and (explicit or expected_exit or (resume_pending and forced_lock))
    )

def _heartbeat_is_fresh(heartbeat: Optional[Dict[str, Any]], *, max_age_sec: float) -> bool:
    if not isinstance(heartbeat, dict) or not heartbeat:
        return False
    try:
        age = _heartbeat_age_sec(heartbeat)
    except Exception:
        return False
    return age >= 0.0 and age <= float(max_age_sec)

def _has_current_tracked_process_alive(self) -> bool:
    for proc in dict(getattr(self, "_running_processes", {}) or {}).values():
        try:
            if proc is not None and proc.poll() is None:
                return True
        except Exception:
            continue
    return False

def _protected_state_is_stale_without_workers(self, state: Optional[Dict[str, Any]]) -> bool:
    """Detect protected startup/active state left behind after the UI was closed.

    This is intentionally conservative: a fresh matching worker heartbeat means
    an external logger/monitor may still be alive, so we do not clear it.  If no
    process is tracked by this bridge and no worker heartbeat is fresh, a
    protected_starting/protected_active session is stale UI state and must be
    converted to terminal idle instead of being surfaced forever.
    """
    data = state if isinstance(state, dict) else {}
    if not data or _is_terminal_protected_state(data):
        return False
    if bool(getattr(self, "_pending_logger_start", False)) or bool(getattr(self, "_pending_monitor_start", False)):
        return False
    session_kind = str(data.get("session_kind") or data.get("runtime_mode") or data.get("mode") or "").strip().lower()
    flow = str(data.get("flow") or "").strip().lower()
    status = str(data.get("status") or data.get("runtime_status") or "").strip().lower()
    if session_kind != "protected" and not flow.startswith("protected"):
        return False
    if not (bool(data.get("active")) or flow.startswith("protected") or status in {"ok", "starting", "insufficient_evidence", "insufficient_windows"}):
        return False
    if _has_current_tracked_process_alive(self):
        return False
    logger_hb = _read_matching_worker_heartbeat(self, "logger", data)
    monitor_hb = _read_matching_worker_heartbeat(self, "monitor", data)
    if _heartbeat_is_fresh(logger_hb, max_age_sec=_PROTECTED_STALE_FLOW_RECOVERY_HEARTBEAT_GRACE_SEC):
        return False
    if _heartbeat_is_fresh(monitor_hb, max_age_sec=_PROTECTED_STALE_FLOW_RECOVERY_HEARTBEAT_GRACE_SEC):
        return False
    return True

def recover_stale_protected_flow_without_workers(self, state: Optional[Dict[str, Any]] = None, *, reason: str = "stale_protected_flow_without_workers") -> bool:
    """Terminalize stale protected state left by closing the UI during protection."""
    data = state if isinstance(state, dict) else {}
    if not _protected_state_is_stale_without_workers(self, data):
        return False
    facade = _facade()
    terminal = _terminal_protected_session_state(self, data, reason=reason)
    terminal.update({
        "stale_protected_flow_recovered": True,
        "stale_protected_flow_recovery_reason": str(reason or "stale_protected_flow_without_workers"),
        "runtime_diagnostic_code": "",
        "runtime_diagnostic_reason": "",
        "protected_failure_reason": "",
    })
    try:
        facade.clear_worker_heartbeat("logger")
        facade.clear_worker_heartbeat("monitor")
    except Exception:
        LOGGER.debug("Failed clearing worker heartbeats during stale protected-flow recovery", exc_info=True)
    try:
        facade.clear_stop("monitor")
        if getattr(self, "_current_user", None):
            facade.clear_stop(self._logger_key())
    except Exception:
        LOGGER.debug("Failed clearing stop controls during stale protected-flow recovery", exc_info=True)
    try:
        facade.write_session_state(terminal)
    except Exception:
        LOGGER.exception("Failed writing terminal state during stale protected-flow recovery")
        return False
    self._clear_pending_logger_start()
    self._clear_pending_monitor_start()
    self._last_alert_signature = None
    self._active_live_session_dir = None
    self._runtime_state = dict(terminal)
    try:
        facade.invalidate_session_discovery_cache()
    except Exception:
        LOGGER.debug("Failed invalidating discovery cache after stale protected-flow recovery", exc_info=True)
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("runtime", "Recovered stale protected flow without workers", payload={"reason": str(reason or "stale_protected_flow_without_workers"), "state": dict(data)}, level="warn")
    return True

def _read_matching_worker_heartbeat(self, kind: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    facade = _facade()
    state = state if isinstance(state, dict) else {}
    try:
        heartbeat = facade.read_worker_heartbeat(kind, default={})
    except Exception:
        return {}
    pending_session_id = ""
    pending_user = ""
    if kind == "logger":
        pending_session_id = str(getattr(self, "_pending_logger_session_id", "") or "")
        pending_user = str(getattr(self, "_pending_logger_user_id", "") or "")
    elif kind == "monitor":
        pending_session_id = str(getattr(self, "_pending_logger_session_id", "") or state.get("session_id") or "")
        pending_user = str(getattr(self, "_pending_monitor_user_id", "") or "")
    if _worker_heartbeat_matches(state, heartbeat, kind=kind, pending_session_id=pending_session_id, pending_user=pending_user):
        return dict(heartbeat)
    return {}
