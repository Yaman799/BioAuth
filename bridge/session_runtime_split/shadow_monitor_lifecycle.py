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

def stop_current_session(self, silent: bool = False) -> None:  # [FLOW: USER]
    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("action", "stopCurrentSession requested", payload={"silent": bool(silent), "flow": self._session_flow()})
    try:
        stop_live_candidate_observer(self, reason="session_stop_requested", timeout=0.75)
    except Exception:
        LOGGER.debug("Live candidate observer stop during stopCurrentSession failed safely", exc_info=True)
    self._clear_pending_logger_start()
    self._clear_pending_monitor_start()
    clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
    if callable(clear_shadow):
        clear_shadow()
    state = self._active_state_for_current_user()
    flow = self._session_flow(state)
    if recover_stale_passive_auto_enrollment_finalization(self, state, source="manual_stop"):
        return
    if not state:
        self._clear_history_archive_watch()
        facade.clear_stop("monitor")
        if self._current_user:
            facade.clear_stop(self._logger_key())
        _clear_shadow_stop_controls(self)
        facade.invalidate_session_discovery_cache()
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        if not silent:
            self._set_status(self._t("stop_requested"), "info")
        refresh_timer = getattr(self, "_update_refresh_timer", None)
        if callable(refresh_timer):
            refresh_timer(force=True)
        _request_refresh(self, "session:stop_no_state", True)
        return
    if flow == "idle" and not bool(state.get("active")):
        self._clear_history_archive_watch()
        facade.clear_stop("monitor")
        if self._current_user:
            facade.clear_stop(self._logger_key())
        _clear_shadow_stop_controls(self)
        facade.invalidate_session_discovery_cache()
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        if not silent:
            self._set_status(self._t("stop_requested"), "info")
        refresh_timer = getattr(self, "_update_refresh_timer", None)
        if callable(refresh_timer):
            refresh_timer(force=True)
        _request_refresh(self, "session:stop_idle_state", True)
        return
    if self._runtime_state_is_orphaned(state):
        if _state_is_shadow_evidence(state):
            _request_shadow_stop_controls(self)
        elif self._current_user:
            facade.request_stop(self._logger_key())
        self._stop_stale_monitor(wait_timeout=1.0)
        self._force_clear_orphaned_runtime_state(state, reason="stop_requested_for_orphaned_runtime")
        if not silent:
            self._set_status(self._t("stop_requested"), "info")
        refresh_timer = getattr(self, "_update_refresh_timer", None)
        if callable(refresh_timer):
            refresh_timer(force=True)
        _request_refresh(self, "session:stop_orphaned_runtime", True)
        return
    if flow == "protected_technical_failure" and _terminal_failure_without_worker(self, state):
        _request_stop_for_current_session(self)
        _clear_runtime_after_terminal_stop(self, state, reason="stop_requested_for_terminal_failure_without_worker")
        if not silent:
            self._set_status(self._t("stop_requested"), "info")
        refresh_timer = getattr(self, "_update_refresh_timer", None)
        if callable(refresh_timer):
            refresh_timer(force=True)
        _request_refresh(self, "session:stop_terminal_failure", True)
        return
    if flow == "protected_forced_stop" and not state.get("active"):
        if self._current_user:
            facade.request_stop(self._logger_key())
        self._stop_stale_monitor(wait_timeout=1.0)
        facade.clear_session_state()
        facade.invalidate_session_discovery_cache()
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        self._last_alert_signature = None
        self._active_live_session_dir = None
        if not silent:
            self._set_status(self._t("stop_requested"), "info")
        refresh_timer = getattr(self, "_update_refresh_timer", None)
        if callable(refresh_timer):
            refresh_timer(force=True)
        _request_refresh(self, "session:stop_forced_state", True)
        return
    if _state_is_shadow_evidence(state) or bool(getattr(self, "_pending_shadow_evidence_monitor_start", False)):
        _request_shadow_stop_controls(self)
    else:
        if self._current_user:
            facade.request_stop(self._logger_key())
        facade.request_stop("monitor")
    self._begin_history_archive_watch()
    if not silent:
        self._set_status(self._t("stop_requested"), "info")
    facade.invalidate_session_discovery_cache()
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    self._update_refresh_timer(force=True)
    _request_refresh(self, "session:stop_current", True)

def stop_production_monitor(self, silent: bool = False) -> None:  # [FLOW: USER]
    """Compatibility wrapper for supervisor-owned Stop Protection."""
    from bioauth_runtime.supervisor import stop_controller

    stop_controller.stop_protection(self, reason="user_requested", silent=silent)

def maybe_resume_protection_after_unlock(self, state: Optional[Dict[str, Any]] = None) -> bool:
    """Compatibility wrapper for supervisor-owned post-unlock resume."""
    from bioauth_runtime.supervisor import resume_controller

    return resume_controller.maybe_resume_after_unlock(self, state=state)
