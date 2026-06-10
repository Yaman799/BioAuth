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

def start_protected_session(self, *, auto_resume: bool = False, trigger_refresh: bool = True) -> bool:  # [FLOW: USER]
    """Compatibility wrapper for the commercial runtime supervisor.

    Legacy source-order markers kept for static compatibility tests:
    if not facade.clear_session_state():
    facade.clear_worker_heartbeat("logger")
    facade.clear_worker_heartbeat("monitor")
    self._pending_logger_session_id = facade.uuid.uuid4().hex
    bridge_initial_protected_state_written
    "worker_heartbeat_waiting_for": "logger"
    started = self._start_process(
        self._logger_process_key(),
    """
    from bioauth_runtime.supervisor import protection_session_controller

    return protection_session_controller.start_protection(
        self, auto_resume=auto_resume, trigger_refresh=trigger_refresh
    )

def stop_enrollment_logger(self, silent: bool = False) -> bool:
    """Request stop for only the normal enrollment logger.

    This QML-facing helper deliberately does not target the production
    ``monitor`` stop control and does not request hidden shadow-evidence stop
    controls. Logger finalization is allowed to archive the live session.
    """
    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        try:
            debug("action", "stopEnrollmentLogger requested", payload={"silent": bool(silent)}, level="info")
        except TypeError:
            debug("action", "stopEnrollmentLogger requested", payload={"silent": bool(silent)})
    if not getattr(self, "_current_user", None):
        return False

    try:
        stop_live_candidate_observer(self, reason="enrollment_logger_stop_requested", timeout=0.75)
    except Exception:
        LOGGER.debug("Live candidate observer stop during stopEnrollmentLogger failed safely", exc_info=True)

    try:
        state = self._active_state_for_current_user()
    except Exception:
        state = {}
    state = state if isinstance(state, dict) else {}

    # Hidden shadow evidence and protected-session monitor/logger state have
    # separate lifecycle contracts. This button is enrollment-logger only.
    if not _normal_enrollment_logger_stop_available(self, state):
        return False

    try:
        facade.request_stop(self._logger_key())
    except Exception:
        LOGGER.exception("Failed requesting normal enrollment logger stop")
        return False

    begin_watch = getattr(self, "_begin_history_archive_watch", None)
    if callable(begin_watch):
        try:
            begin_watch()
        except Exception:
            LOGGER.debug("Failed starting history archive watch for enrollment logger stop", exc_info=True)
    if not silent:
        self._set_status(self._t("stop_requested"), "info")
    try:
        facade.invalidate_session_discovery_cache()
    except Exception:
        LOGGER.debug("Failed invalidating session discovery cache after enrollment logger stop", exc_info=True)
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        try:
            invalidate()
        except Exception:
            LOGGER.debug("Failed invalidating dashboard cache after enrollment logger stop", exc_info=True)
    refresh_timer = getattr(self, "_update_refresh_timer", None)
    if callable(refresh_timer):
        refresh_timer(force=True)
    controls_signal = getattr(self, "controlsChanged", None)
    if controls_signal is not None and hasattr(controls_signal, "emit"):
        try:
            controls_signal.emit()
        except Exception:
            LOGGER.debug("Failed emitting controlsChanged after enrollment logger stop", exc_info=True)
    _request_refresh(self, "session:stop_enrollment_logger", True)
    return True
