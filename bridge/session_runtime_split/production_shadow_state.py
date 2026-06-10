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

def shutdown_runtime_workers(self, *, reason: str = "app_shutdown", wait_timeout: float = 0.75) -> Dict[str, Any]:  # [FLOW: USER/LIFECYCLE]
    """Stop all BioAuth runtime workers during application shutdown.

    Closing the UI must not leave monitor.py/logger.py running, and the next UI
    launch must not see a protected session as still active just because a worker
    heartbeat survived the previous window.
    """
    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    try:
        state = facade.read_session_state(default={})
    except Exception:
        state = {}
    state = state if isinstance(state, dict) else {}
    session_kind = str(state.get("session_kind") or state.get("runtime_mode") or state.get("mode") or "").strip().lower()
    try:
        flow = _normal_user_session_flow(self, state)
    except Exception:
        flow = "unknown"
    if callable(debug):
        _debug_runtime_event(
            self,
            "application_shutdown_runtime_cleanup_requested",
            payload={"reason": str(reason or "app_shutdown"), "flow": flow, "session_kind": session_kind},
            level="info",
        )

    try:
        stop_live_candidate_observer(self, reason="application_shutdown", timeout=min(0.75, max(0.1, float(wait_timeout or 0.75))))
    except Exception:
        LOGGER.debug("Live candidate observer stop during application shutdown failed safely", exc_info=True)

    logger_stop_name = _logger_stop_name_from_state(self, state)
    stop_names = ["monitor", logger_stop_name]
    for name in stop_names:
        try:
            facade.request_stop(name)
        except Exception:
            LOGGER.debug("Failed requesting %s stop during application shutdown", name, exc_info=True)
    try:
        _request_shadow_stop_controls(self)
    except Exception:
        LOGGER.debug("Failed requesting shadow stop during application shutdown", exc_info=True)

    protected_result: Dict[str, Any] = {}
    if session_kind == "protected" or str(flow).startswith("protected"):
        try:
            protected_result = finalize_protected_session_stop(
                self,
                reason=str(reason or "app_shutdown"),
                silent=True,
                wait_timeout=max(0.1, float(wait_timeout or 0.75)),
            )
        except Exception:
            LOGGER.exception("Failed finalizing protected session during application shutdown")
            protected_result = {"ok": False, "reason": "protected_shutdown_finalizer_failed"}

    terminated: Dict[str, Dict[str, Any]] = {}
    for key in list((getattr(self, "_running_processes", {}) or {}).keys()):
        try:
            # Stop files were already requested above; terminate tracked workers so
            # the UI process never exits while its own child workers remain alive.
            terminated[str(key)] = _terminate_process_key(
                self,
                str(key),
                graceful_timeout=max(0.1, min(0.75, float(wait_timeout or 0.75))),
                force_timeout=0.5,
                terminate_first=True,
            )
        except Exception:
            LOGGER.debug("Failed terminating tracked worker %s during application shutdown", key, exc_info=True)

    monitor_external_result = _terminate_pid_best_effort(
        _state_pid_for(state, "monitor_pid"),
        label="monitor",
        wait_timeout=max(0.25, min(1.0, float(wait_timeout or 0.75))),
    )
    logger_external_result = _terminate_pid_best_effort(
        _state_pid_for(state, "logger_pid", "pid"),
        label="logger",
        wait_timeout=max(0.25, min(1.0, float(wait_timeout or 0.75))),
    )

    # For non-protected active states such as enrollment, write an idle terminal
    # state after stop was requested. Protected sessions are handled by the
    # dedicated finalizer above.
    if state.get("active") and not (session_kind == "protected" or str(flow).startswith("protected")):
        now = facade.time.time()
        terminal = dict(state)
        terminal.update({
            "active": False,
            "session_state": "stopped",
            "flow": "idle",
            "status": "stopped",
            "runtime_status": "idle",
            "decision": "stopped",
            "stop_reason": str(reason or "app_shutdown"),
            "stopped_at": now,
            "stopped_at_text": facade.time.strftime("%Y-%m-%d %H:%M:%S", facade.time.localtime(now)),
            "logger_ready": False,
            "monitor_ready": False,
            "auto_resume_pending": False,
            "resume_after_unlock": False,
            "return_verification": False,
            "forced_stop": False,
            "app_locked": False,
            "screen_locked": False,
            "monitor_holding": False,
            "restriction_active": False,
            "feedback_prompt": {},
        })
        try:
            facade.write_session_state(terminal)
            self._runtime_state = dict(terminal)
        except Exception:
            LOGGER.debug("Failed writing terminal shutdown state", exc_info=True)
    elif not state.get("active"):
        try:
            facade.clear_session_state()
        except Exception:
            LOGGER.debug("Failed clearing inactive session state during shutdown", exc_info=True)

    self._clear_pending_monitor_start()
    self._clear_pending_logger_start()
    clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
    if callable(clear_shadow):
        try:
            clear_shadow()
        except Exception:
            LOGGER.debug("Failed clearing shadow pending state during shutdown", exc_info=True)
    try:
        self._clear_history_archive_watch()
    except Exception:
        LOGGER.debug("Failed clearing history archive watch during shutdown", exc_info=True)
    self._active_live_session_dir = None
    self._last_alert_signature = None
    try:
        facade.invalidate_session_discovery_cache()
    except Exception:
        LOGGER.debug("Failed invalidating session discovery cache during shutdown", exc_info=True)
    try:
        self._cleanup_processes()
    except Exception:
        LOGGER.debug("Final worker cleanup during shutdown failed", exc_info=True)

    result = {
        "ok": True,
        "reason": str(reason or "app_shutdown"),
        "flow": flow,
        "session_kind": session_kind,
        "protected": protected_result,
        "terminated": terminated,
        "monitor_external_pid": monitor_external_result,
        "logger_external_pid": logger_external_result,
    }
    if callable(debug):
        _debug_runtime_event(self, "application_shutdown_runtime_cleanup_finished", payload=result, level="info")
    return result
