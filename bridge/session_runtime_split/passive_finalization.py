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

def request_shadow_evidence_stop_for_retry(self, *, reason: str = "remediation_evidence_complete") -> bool:
    """Request a safe shadow_evidence logger/monitor shutdown before retry training.

    This helper is lifecycle-only. It does not train, promote, unlock Protected
    Sessions, delete ledgers, or convert shadow evidence into owner-positive
    training data.
    """

    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    blocker = _shadow_evidence_retry_handoff_block_reason(self)
    if blocker:
        self._retry_handoff_state = "blocked"
        self._retry_handoff_blockers = [blocker]
        self._retry_handoff_last_error = blocker
        if callable(debug):
            debug("runtime", "retry_handoff_blocked", payload={"reason": blocker}, level="warn")
        self._set_status("Retry training is waiting for a safe runtime handoff.", "warn")
        return False
    state = self._active_state_for_current_user()
    active_kind = str((state or {}).get("session_kind") or "").strip().lower()
    shadow_runtime = bool((state or {}).get("active") and active_kind == SHADOW_EVIDENCE_SESSION_KIND)
    shadow_pending = bool(getattr(self, "_pending_shadow_evidence_monitor_start", False))
    logger_running = _shadow_evidence_logger_running(self)
    monitor_running = _shadow_evidence_monitor_running(self)
    if not (shadow_runtime or shadow_pending or logger_running or monitor_running):
        return _mark_shadow_evidence_stopped_for_retry(self, reason="already_stopped_for_retry")
    updated = dict(state or {})
    updated.setdefault("user_id", getattr(self, "_current_user", {}).get("user_id") if getattr(self, "_current_user", None) else "")
    updated.update({
        "active": True,
        "session_kind": SHADOW_EVIDENCE_SESSION_KIND,
        "mode": SHADOW_EVIDENCE_SESSION_KIND,
        "runtime_mode": SHADOW_EVIDENCE_SESSION_KIND,
        "evidence_source": SHADOW_EVIDENCE_SOURCE,
        "status": "shadow_evidence_settling_for_retry",
        "retry_handoff_state": "shadow_evidence_settling_for_retry",
        "retry_handoff_blockers": [],
        "retry_handoff_last_error": "",
        "shadow_evidence_stopped_for_retry": False,
        "shadow_evidence_stop_reason": str(reason or "remediation_evidence_complete"),
        "stop_requested": True,
        "stop_reason": "retry_training_handoff",
        "excluded_from_positive_training": True,
        "training_counts_toward_minimum": False,
        "owner_positive_training_allowed": False,
        "protected_sessions_available": False,
        "production_ready": False,
    })
    try:
        facade.write_session_state(updated)
    except Exception:
        LOGGER.debug("Failed writing shadow evidence retry handoff state", exc_info=True)
    self._runtime_state = updated
    self._retry_handoff_state = "shadow_evidence_settling_for_retry"
    self._retry_handoff_blockers = []
    self._retry_handoff_last_error = ""
    self._shadow_evidence_stopped_for_retry = False
    try:
        _request_shadow_stop_controls(self)
    except Exception as exc:
        self._retry_handoff_state = "blocked"
        self._retry_handoff_blockers = ["stop_request_failed"]
        self._retry_handoff_last_error = str(exc)
        updated["retry_handoff_state"] = "blocked"
        updated["retry_handoff_blockers"] = ["stop_request_failed"]
        updated["retry_handoff_last_error"] = "stop_request_failed"
        try:
            facade.write_session_state(updated)
        except Exception:
            LOGGER.debug("Failed writing shadow evidence retry handoff stop failure", exc_info=True)
        if callable(debug):
            debug("runtime", "retry_handoff_blocked", payload={"reason": "stop_request_failed"}, level="warn")
        return False
    begin_watch = getattr(self, "_begin_history_archive_watch", None)
    if callable(begin_watch):
        begin_watch()
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    self._set_status("Settling shadow evidence before retry training. Training will wait until monitoring stops safely.", "info")
    if callable(debug):
        debug("runtime", "shadow_evidence_stop_for_retry_requested", payload={"reason": str(reason or "remediation_evidence_complete")}, level="info")
    refresh_timer = getattr(self, "_update_refresh_timer", None)
    if callable(refresh_timer):
        refresh_timer(force=True)
    _request_refresh(self, "session:shadow_evidence_stop_for_retry", True)
    return True

def maybe_mark_shadow_evidence_stopped_for_retry(self) -> bool:
    state_text = str(getattr(self, "_retry_handoff_state", "") or "").strip().lower()
    active_state = self._active_state_for_current_user()
    state_text = str((active_state or {}).get("retry_handoff_state") or state_text or "").strip().lower()
    if state_text != "shadow_evidence_settling_for_retry":
        return False
    return _mark_shadow_evidence_stopped_for_retry(self, reason="processes_stopped_for_retry")

def stop_shadow_evidence_monitor(self, *, reason: str = "stop_requested") -> bool:  # [FLOW: RESEARCH]
    state = self._active_state_for_current_user()
    if str(state.get("session_kind") or "").strip().lower() != SHADOW_EVIDENCE_SESSION_KIND and not bool(getattr(self, "_pending_shadow_evidence_monitor_start", False)) and not _is_shadow_runtime_process_running(self):
        return False
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("runtime", "shadow_evidence_monitor_stop_requested", payload={"reason": str(reason or "stop_requested")}, level="info")
    _request_shadow_stop_controls(self)
    clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
    if callable(clear_shadow):
        clear_shadow()
    try:
        _facade().invalidate_session_discovery_cache()
    except Exception:
        LOGGER.debug("Failed invalidating session cache after hidden shadow stop request", exc_info=True)
    refresh_timer = getattr(self, "_update_refresh_timer", None)
    if callable(refresh_timer):
        refresh_timer(force=True)
    _request_refresh(self, "session:stop_shadow_evidence", True)
    return True

def start_enrollment(self, *, passive_auto_enrollment: bool = False) -> bool:  # [FLOW: USER]
    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("action", "startEnrollment requested", payload={"user": str((self._current_user or {}).get("user_id", "") or ""), "passive_auto_enrollment": bool(passive_auto_enrollment)})
    if not self._current_user:
        return False
    if bool(getattr(self, "_training_in_progress", False)):
        self._set_status(self._t("enrollment_blocked_training_active"), "warn")
        return False
    if not self._has_current_user_welcome_consent():
        self._onboarding_visible = True
        self.onboardingChanged.emit()
        self._set_status(self._t("policy_required"), "warn")
        return False
    active_state = self._active_state_for_current_user()
    if _normal_logger_start_pending(self):
        self._set_status(self._t("enrollment_started"), "info")
        refresh_timer = getattr(self, "_update_refresh_timer", None)
        if callable(refresh_timer):
            refresh_timer(force=True)
        _request_refresh(self, "session:enrollment_pending", True)
        return False
    if _request_hidden_shadow_cleanup_for_normal_action(self, reason="normal_enrollment_requested", state=active_state):
        self._set_status(self._t("capture_session_finishing"), "info")
        refresh_timer = getattr(self, "_update_refresh_timer", None)
        if callable(refresh_timer):
            refresh_timer(force=True)
        _request_refresh(self, "session:normal_enrollment_waiting_for_capture_cleanup", True)
        return False
    active_state = self._active_state_for_current_user()
    if (
        active_state.get("active")
        and str(active_state.get("session_kind") or "").strip().lower() == "enrollment"
        and bool(active_state.get("logger_ready"))
    ):
        self._set_status(self._t("enrollment_started"), "info")
        _request_refresh(self, "session:enrollment_active", True)
        return False
    if _normal_enrollment_logger_flow(self, active_state) != "idle":
        self._set_status(self._t("already_running"), "warn")
        return False
    if _normal_user_session_flow(self, active_state) != "idle":
        self._set_status(self._t("another_capture_session_active"), "warn")
        return False
    if not self._stop_stale_monitor():
        self._set_status(self._t("stop_requested"), "info")
        refresh_timer = getattr(self, "_update_refresh_timer", None)
        if callable(refresh_timer):
            refresh_timer(force=True)
        _request_refresh(self, "session:enrollment_stop_stale_monitor", True)
        return False
    self._pending_passive_auto_enrollment = bool(passive_auto_enrollment)
    facade.clear_stop(self._logger_key())
    self._clear_history_archive_watch()
    facade.clear_session_state()
    facade.invalidate_session_discovery_cache()
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    self._pending_logger_session_id = facade.uuid.uuid4().hex
    self._pending_logger_run_id = facade.uuid.uuid4().hex
    self._active_live_session_dir = self._new_live_session_dir()
    try:
        now = facade.time.time()
        initial_state = {
            "schema_version": 2,
            "session_id": self._pending_logger_session_id,
            "run_id": self._pending_logger_run_id,
            "mode": "standalone",
            "decision": "pending",
            "active": True,
            "source": "bridge",
            "user_id": self._current_user["user_id"],
            "session_kind": "protected",
            "started_at": now,
            "started_at_text": facade.time.strftime("%Y-%m-%d %H:%M:%S", facade.time.localtime(now)),
            "status": "starting",
            "logger_ready": False,
            "monitor_ready": False,
            "monitor_failed": False,
            "logger_failed": False,
            "technical_failure": False,
            "awaiting_evidence": True,
            "pending_monitor_start": True,
            "live_session_dir": self._active_live_session_dir,
            "worker_heartbeat_single_writer": True,
        }
        facade.write_session_state(initial_state)
        self._runtime_state = dict(initial_state)
    except Exception:
        LOGGER.debug("Failed writing bridge-owned initial protected session state", exc_info=True)
    started = self._start_process(
        self._logger_process_key(),
        [facade.LOGGER_SCRIPT, self._current_user["user_id"], "enrollment"],
        extra_env=self._session_process_env(),
    )
    if not started:
        self._active_live_session_dir = None
        self._pending_passive_auto_enrollment = False
    if started:
        self._set_status("BioAuth is learning your natural behavior in the background." if passive_auto_enrollment else self._t("enrollment_started"), "info")
        try:
            start_live_candidate_observer(self, reason="passive_enrollment_start" if passive_auto_enrollment else "enrollment_start")
        except Exception:
            LOGGER.debug("Live candidate observer start for enrollment failed safely", exc_info=True)
    elif not getattr(self, "_last_process_start_error", ""):
        self._set_status(self._t("already_running"), "warn")
    self._update_refresh_timer(force=True)
    _request_refresh(self, "session:start_passive_auto_enrollment" if passive_auto_enrollment else "session:start_enrollment", True)
    return bool(started)
