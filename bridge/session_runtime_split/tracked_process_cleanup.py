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

def finalize_protected_session_stop(self, *, reason: str = "user_requested", silent: bool = False, wait_timeout: float = 1.25) -> Dict[str, Any]:
    """Backend-owned finalizer for user-facing protected session shutdown.

    Stop Monitor must close both workers: the production monitor and the normal
    protected-session logger.  Leaving the logger alive keeps heartbeat and live
    telemetry in protected_active even after monitor.py exits.  This helper is
    intentionally idempotent and never touches production approval metadata.
    """
    facade = _facade()
    state = self._active_state_for_current_user()
    state = state if isinstance(state, dict) else {}
    logger_key = _normal_logger_process_key(self)
    monitor_key = "monitor"
    try:
        flow_for_log = _normal_user_session_flow(self, state)
    except Exception:
        flow_for_log = str((state or {}).get("flow") or getattr(self, "_session_flow", lambda: "unknown")() or "unknown")
    _debug_runtime_event(self, "protected_session_stop_requested", payload={"reason": str(reason or "user_requested"), "flow": flow_for_log, "monitor_key": monitor_key, "logger_key": logger_key}, level="info")

    self._clear_pending_monitor_start()
    self._clear_pending_logger_start()
    try:
        facade.request_stop(monitor_key)
        _debug_runtime_event(self, "protected_session_monitor_stop_requested", payload={"process_key": monitor_key}, level="info")
    except Exception:
        LOGGER.exception("Failed requesting protected monitor stop")
    if getattr(self, "_current_user", None):
        try:
            facade.request_stop(self._logger_key())
            _debug_runtime_event(self, "protected_session_logger_stop_requested", payload={"process_key": logger_key}, level="info")
        except Exception:
            LOGGER.exception("Failed requesting protected logger stop")

    monitor_result = _terminate_process_key(self, monitor_key, graceful_timeout=min(0.75, max(0.1, float(wait_timeout))), force_timeout=0.5)
    logger_result = _terminate_process_key(self, logger_key, graceful_timeout=max(0.1, float(wait_timeout)), force_timeout=0.75, terminate_first=False)

    monitor_external_result = {"label": "monitor", "pid": 0, "found": False, "still_alive": False}
    logger_external_result = {"label": "logger", "pid": 0, "found": False, "still_alive": False}
    if not bool(monitor_result.get("found")):
        monitor_external_result = _terminate_pid_best_effort(
            _state_pid_for(state, "monitor_pid"),
            label="monitor",
            wait_timeout=max(0.25, min(1.0, float(wait_timeout or 0.75))),
        )
    if not bool(logger_result.get("found")):
        logger_external_result = _terminate_pid_best_effort(
            _state_pid_for(state, "logger_pid", "pid"),
            label="logger",
            wait_timeout=max(0.25, min(1.0, float(wait_timeout or 0.75))),
        )

    latest_state = facade.read_session_state(default={})
    latest_state = latest_state if isinstance(latest_state, dict) else state
    terminal_state = _terminal_protected_session_state(self, latest_state, reason=reason)
    marker_path = _write_terminal_live_session_marker(terminal_state)
    try:
        # Commercial-Core-22O: stop finalization is the hard boundary for the
        # single-writer runtime.  Clear worker heartbeats before and after the
        # terminal write so stale logger/monitor files cannot revive the stopped
        # session back into protected_starting during the next refresh.
        facade.clear_worker_heartbeat("logger")
        facade.clear_worker_heartbeat("monitor")
    except Exception:
        LOGGER.debug("Failed clearing worker heartbeats before protected terminal write", exc_info=True)
    try:
        facade.write_session_state(terminal_state)
    except Exception:
        LOGGER.exception("Failed writing protected terminal session state")
    try:
        facade.clear_worker_heartbeat("logger")
        facade.clear_worker_heartbeat("monitor")
    except Exception:
        LOGGER.debug("Failed clearing worker heartbeats after protected terminal write", exc_info=True)

    self._clear_pending_monitor_start()
    self._clear_pending_logger_start()
    self._clear_history_archive_watch()
    self._last_alert_signature = None
    self._active_live_session_dir = None
    self._runtime_state = dict(terminal_state)
    try:
        # Keep stop files in place when this UI instance has no process handle and
        # no recorded PID was found/killed.  That lets orphan workers from a
        # previously closed UI observe the stop request instead of immediately
        # clearing the signal they need to exit.  A fresh Start Protection call
        # clears these controls immediately before spawning new workers.
        if bool(monitor_result.get("found")) or bool(monitor_external_result.get("found")) and not bool(monitor_external_result.get("still_alive")):
            facade.clear_stop(monitor_key)
        logger_stop_name = _logger_stop_name_from_state(self, latest_state)
        if bool(logger_result.get("found")) or bool(logger_external_result.get("found")) and not bool(logger_external_result.get("still_alive")):
            facade.clear_stop(logger_stop_name)
    except Exception:
        LOGGER.debug("Failed clearing protected stop controls after finalization", exc_info=True)
    try:
        facade.invalidate_session_discovery_cache()
    except Exception:
        LOGGER.debug("Failed invalidating session discovery cache after protected finalization", exc_info=True)
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    _emit_runtime_and_control_changes(self)
    _debug_runtime_event(self, "protected_session_telemetry_reset", payload={"runtime_status": "idle", "flow": "idle", "reason": str(reason or "user_requested")}, level="info")
    _debug_runtime_event(
        self,
        "protected_session_finalized",
        payload={
            "reason": str(reason or "user_requested"),
            "monitor": monitor_result,
            "logger": logger_result,
            "monitor_external_pid": monitor_external_result,
            "logger_external_pid": logger_external_result,
            "terminal_marker": marker_path,
        },
        level="info",
    )
    if not silent:
        try:
            self._set_status("Protected session stopped. Ready to start monitoring again.", "info")
        except Exception:
            LOGGER.debug("Failed setting protected stop status", exc_info=True)
    refresh_timer = getattr(self, "_update_refresh_timer", None)
    if callable(refresh_timer):
        refresh_timer(force=True)
    _request_refresh(self, "session:protected_stop_finalized", True)
    return {
        "ok": True,
        "monitor": monitor_result,
        "logger": logger_result,
        "monitor_external_pid": monitor_external_result,
        "logger_external_pid": logger_external_result,
        "terminal_marker": marker_path,
        "state": terminal_state,
    }

def _clear_runtime_after_terminal_stop(self, state: Optional[Dict[str, Any]] = None, *, reason: str = "terminal_stop") -> None:
    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("runtime", "Clearing terminal runtime state", payload={"reason": str(reason or "terminal_stop"), "state": dict(state or {})}, level="warn")
    self._clear_pending_logger_start()
    self._clear_pending_monitor_start()
    clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
    if callable(clear_shadow):
        clear_shadow()
    self._clear_history_archive_watch()
    facade.clear_session_state()
    try:
        facade.clear_worker_heartbeat("logger")
        facade.clear_worker_heartbeat("monitor")
    except Exception:
        LOGGER.debug("Failed clearing worker heartbeats before protected start", exc_info=True)
    facade.invalidate_session_discovery_cache()
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    self._last_alert_signature = None
    self._active_live_session_dir = None

def _terminal_failure_without_worker(self, state: Optional[Dict[str, Any]] = None) -> bool:
    facade = _facade()
    state = state if isinstance(state, dict) else {}
    if not bool(state.get("active")):
        return False
    status = str(state.get("status") or "").strip().lower()
    technical = bool(state.get("technical_failure")) or bool(state.get("logger_failed")) or bool(state.get("monitor_failed")) or facade.runtime_status_is_technical_failure(status)
    if not technical:
        return False
    return not _has_tracked_running_session_process(self)

def force_clear_orphaned_runtime_state(self, state: Optional[Dict[str, Any]] = None, *, reason: str = "") -> None:
    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    quarantine_path = ""
    try:
        quarantine_path = facade.quarantine_session_state(reason or "orphaned")
    except Exception:
        LOGGER.exception("Failed quarantining orphaned runtime state")
    if callable(debug):
        debug("runtime", "Clearing orphaned runtime state", payload={"reason": str(reason or "orphaned"), "quarantine_path": quarantine_path, "state": dict(state or {})}, level="warn")
    self._clear_pending_logger_start()
    self._clear_pending_monitor_start()
    clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
    if callable(clear_shadow):
        clear_shadow()
    self._clear_history_archive_watch()
    facade.clear_session_state()
    facade.clear_stop("monitor")
    if self._current_user:
        facade.clear_stop(self._logger_key())
    _clear_shadow_stop_controls(self)
    facade.invalidate_session_discovery_cache()
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    self._last_alert_signature = None
    self._active_live_session_dir = None

def clear_stale_runtime_state(self) -> None:
    facade = _facade()
    state = facade.read_session_state(default={})
    if self._runtime_state_is_orphaned(state):
        self._force_clear_orphaned_runtime_state(state, reason="stale_runtime_after_reboot")
        return
    if _terminal_failure_without_worker(self, state):
        _request_stop_for_current_session(self)
        _clear_runtime_after_terminal_stop(self, state, reason="stale_terminal_failure_without_worker")
        return
    if not state.get("active"):
        facade.clear_session_state()
        self._clear_history_archive_watch()
        facade.invalidate_session_discovery_cache()
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        self._last_alert_signature = None
        self._active_live_session_dir = None
    self._clear_pending_logger_start()
    self._clear_pending_monitor_start()
    facade.clear_stop("monitor")
    if self._current_user:
        facade.clear_stop(self._logger_key())
    _clear_shadow_stop_controls(self)
