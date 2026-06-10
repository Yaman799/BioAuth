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

def start_shadow_evidence_monitor(self, *, trigger_refresh: bool = True, auto_bootstrap: bool = False) -> bool:  # [FLOW: RESEARCH — never auto-starts in user mode]
    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    if _demo_classic_protected_enabled():
        self._last_shadow_evidence_monitor_block_reason = ""
        self._last_shadow_evidence_monitor_skipped_reason = "demo_classic_protected_uses_direct_monitor"
        clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
        if callable(clear_shadow):
            clear_shadow()
        if callable(debug):
            debug(
                "runtime",
                "shadow_evidence_monitor_skipped",
                payload={"shadow_monitor_skipped_reason": "demo_classic_protected_uses_direct_monitor", "demo_classic_protected": True},
                level="info",
            )
        return False
    reason = _shadow_evidence_block_reason(self, auto_bootstrap=auto_bootstrap)
    if reason:
        if reason == "independent_shadow_evidence_monitor_disabled":
            self._last_shadow_evidence_monitor_block_reason = ""
            self._last_shadow_evidence_monitor_skipped_reason = reason
            clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
            if callable(clear_shadow):
                try:
                    clear_shadow()
                except Exception:
                    LOGGER.debug("Failed clearing disabled independent shadow monitor pending context", exc_info=True)
            else:
                setattr(self, "_pending_shadow_evidence_monitor_start", False)
            if callable(debug):
                debug(
                    "runtime",
                    "shadow_evidence_monitor_skipped",
                    payload={
                        "reason": reason,
                        "candidate_status": _shadow_evidence_candidate_status(self),
                        "developer_enable_env": _INDEPENDENT_SHADOW_EVIDENCE_MONITOR_ENV,
                    },
                    level="info",
                )
            return False
        self._last_shadow_evidence_monitor_block_reason = reason
        if callable(debug):
            debug("runtime", "shadow_evidence_monitor_blocked", payload={"reason": reason, "candidate_status": _shadow_evidence_candidate_status(self)}, level="debug")
        return False

    active_state = self._active_state_for_current_user()
    active_kind = str((active_state or {}).get("session_kind") or "").strip().lower()
    existing_shadow_state = bool((active_state or {}).get("active")) and active_kind == SHADOW_EVIDENCE_SESSION_KIND
    logger_running = _shadow_evidence_logger_running(self)
    monitor_running = _shadow_evidence_monitor_running(self)
    if existing_shadow_state or logger_running or monitor_running:
        if monitor_running:
            _mark_shadow_evidence_monitor_collecting(self, active_state)
            clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
            if callable(clear_shadow):
                clear_shadow()
            self._set_status("Collecting evidence · waiting for lock-quality windows", "info")
            if callable(debug):
                debug("runtime", "shadow_evidence_monitor_started", payload={"session_kind": SHADOW_EVIDENCE_SESSION_KIND, "already_running": True}, level="info")
            return True
        if logger_running:
            _restore_shadow_evidence_pending_context(self, active_state)
            self._last_shadow_evidence_monitor_block_reason = ""
            self._set_status("Collecting evidence · waiting for shadow monitor readiness", "info")
            if callable(debug):
                debug("runtime", "shadow_evidence_logger_started", payload={"session_kind": SHADOW_EVIDENCE_SESSION_KIND, "already_running": True}, level="info")
            finish_pending = getattr(self, "_maybe_finish_pending_monitor_start", None)
            if callable(finish_pending):
                finish_pending()
            if trigger_refresh:
                refresh_timer = getattr(self, "_update_refresh_timer", None)
                if callable(refresh_timer):
                    refresh_timer(force=True)
                _request_refresh(self, "session:shadow_evidence_logger_ready", True)
            return True

    if callable(debug):
        debug("runtime", "shadow_evidence_monitor_start_requested", payload={"candidate_status": _shadow_evidence_candidate_status(self)}, level="info")
    if not self._stop_stale_monitor():
        self._last_shadow_evidence_monitor_block_reason = "stop_stale_monitor_pending"
        return False
    _clear_shadow_stop_controls(self)
    self._clear_history_archive_watch()
    facade.clear_session_state()
    facade.invalidate_session_discovery_cache()
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    self._last_alert_signature = None
    self._pending_logger_session_id = facade.uuid.uuid4().hex
    self._pending_logger_run_id = facade.uuid.uuid4().hex
    self._active_live_session_dir = self._new_live_session_dir()
    env = self._session_process_env() or {}
    env.update({
        "BIOAUTH_RUNTIME_MODE": SHADOW_EVIDENCE_SESSION_KIND,
        "BIOAUTH_SHADOW_EVIDENCE_ONLY": "1",
        "BIOAUTH_EVIDENCE_SOURCE": SHADOW_EVIDENCE_SOURCE,
    })
    self._pending_shadow_evidence_monitor_start = True
    self._shadow_evidence_monitor_user_id = self._current_user["user_id"]
    self._shadow_evidence_monitor_start_deadline = facade.time.time() + facade.MONITOR_START_GRACE_SEC
    self._shadow_evidence_monitor_launch_attempted = False
    self._shadow_evidence_monitor_failed = False
    self._last_shadow_evidence_monitor_attempt_at = facade.time.time()
    started = self._start_process(
        _shadow_logger_process_key(self),
        [facade.LOGGER_SCRIPT, self._current_user["user_id"], SHADOW_EVIDENCE_SESSION_KIND],
        extra_env=env,
    )
    if not started:
        self._active_live_session_dir = None
        clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
        if callable(clear_shadow):
            clear_shadow()
        self._shadow_evidence_monitor_failed = True
        return False
    self._set_status("BioAuth is collecting shadow runtime evidence safely without enabling Protected Sessions.", "info")
    if callable(debug):
        debug("runtime", "shadow_evidence_logger_started", payload={"session_kind": SHADOW_EVIDENCE_SESSION_KIND}, level="info")
    if trigger_refresh:
        refresh_timer = getattr(self, "_update_refresh_timer", None)
        if callable(refresh_timer):
            refresh_timer(force=True)
        _request_refresh(self, "session:start_shadow_evidence", True)
    return True

def maybe_start_shadow_evidence_monitor(self) -> bool:
    # Commercial default: independent shadow evidence monitor is disabled.
    # Report-only/runtime-fed shadow evidence is introduced by later phases and
    # must not block auto-training or protected monitor startup in the meantime.
    if not _independent_shadow_evidence_monitor_enabled(self):
        self._last_shadow_evidence_monitor_block_reason = ""
        self._last_shadow_evidence_monitor_skipped_reason = "independent_shadow_evidence_monitor_disabled"
        clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
        if callable(clear_shadow):
            try:
                clear_shadow()
            except Exception:
                LOGGER.debug("Failed clearing disabled auto shadow pending context", exc_info=True)
        else:
            setattr(self, "_pending_shadow_evidence_monitor_start", False)
        return False
    return start_shadow_evidence_monitor(self, trigger_refresh=True, auto_bootstrap=True)

def _shadow_evidence_retry_handoff_block_reason(self) -> str:
    if not getattr(self, "_current_user", None):
        return "not_authenticated"
    if bool(getattr(self, "_training_in_progress", False)):
        return "training_active"
    training_progress = getattr(self, "_training_progress", {}) if isinstance(getattr(self, "_training_progress", None), dict) else {}
    training_stage = str(training_progress.get("stage_key") or training_progress.get("stage") or "").strip().lower()
    if "evaluat" in training_stage or bool(getattr(self, "_evaluation_in_progress", False)) or bool(getattr(self, "_candidate_evaluation_active", False)) or bool(getattr(self, "_model_evaluation_active", False)):
        return "evaluation_active"
    if bool(getattr(self, "_passive_auto_enrollment_finalizing", False)) or bool(getattr(self, "_history_sync_pending", False)):
        return "passive_auto_enrollment_finalizing"
    runtime_state = getattr(self, "_runtime_state", {}) if isinstance(getattr(self, "_runtime_state", None), dict) else {}
    runtime_kind = str((runtime_state or {}).get("session_kind") or "").strip().lower()
    runtime_source = str((runtime_state or {}).get("collection_source") or "").strip().lower()
    runtime_passive = bool((runtime_state or {}).get("active") and runtime_kind == "enrollment" and (bool((runtime_state or {}).get("auto_enrollment")) or runtime_source == "passive_auto_enrollment"))
    if _is_passive_auto_enrollment_state(runtime_state) or runtime_passive or bool(getattr(self, "_pending_passive_auto_enrollment", False)):
        return "passive_auto_enrollment_active"
    active_state = self._active_state_for_current_user()
    active_kind = str((active_state or {}).get("session_kind") or "").strip().lower()
    if bool((active_state or {}).get("active")) and active_kind == "protected":
        return "protected_session_active"
    if bool(getattr(self, "_pending_monitor_start", False)):
        return "protected_monitor_pending"
    return ""

def _mark_shadow_evidence_stopped_for_retry(self, *, reason: str = "stopped_for_retry") -> bool:
    facade = _facade()
    if _shadow_evidence_logger_running(self) or _shadow_evidence_monitor_running(self):
        return False
    state = dict(self._active_state_for_current_user() or {})
    if state and str(state.get("session_kind") or "").strip().lower() not in {"", SHADOW_EVIDENCE_SESSION_KIND}:
        return False
    state.update({
        "active": False,
        "status": "shadow_evidence_stopped_for_retry",
        "session_kind": SHADOW_EVIDENCE_SESSION_KIND,
        "mode": SHADOW_EVIDENCE_SESSION_KIND,
        "runtime_mode": SHADOW_EVIDENCE_SESSION_KIND,
        "evidence_source": SHADOW_EVIDENCE_SOURCE,
        "retry_handoff_state": "shadow_evidence_stopped_for_retry",
        "retry_handoff_blockers": [],
        "retry_handoff_last_error": "",
        "shadow_evidence_stopped_for_retry": True,
        "shadow_evidence_stop_reason": str(reason or "stopped_for_retry"),
        "protected_sessions_available": False,
        "production_ready": False,
        "excluded_from_positive_training": True,
        "training_counts_toward_minimum": False,
        "owner_positive_training_allowed": False,
    })
    try:
        facade.write_session_state(state)
    except Exception:
        LOGGER.debug("Failed writing shadow evidence stopped-for-retry state", exc_info=True)
    self._runtime_state = state
    self._retry_handoff_state = "shadow_evidence_stopped_for_retry"
    self._retry_handoff_blockers = []
    self._retry_handoff_last_error = ""
    self._shadow_evidence_stopped_for_retry = True
    self._clear_pending_monitor_start()
    clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
    if callable(clear_shadow):
        clear_shadow()
    _clear_shadow_stop_controls(self)
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    return True
