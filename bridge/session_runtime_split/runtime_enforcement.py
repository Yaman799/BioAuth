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

def maybe_start_passive_auto_enrollment(self) -> bool:
    """Start passive enrollment capture only when backend policy says it is safe."""

    if not self._current_user:
        return False
    if bool(getattr(self, "_training_in_progress", False)):
        self._last_passive_auto_enrollment_block_reason = "training_active"
        return False
    try:
        allowed, reason = self._auto_enrollment_collection_decision()
    except Exception:
        allowed, reason = False, "decision_error"
    self._last_passive_auto_enrollment_block_reason = str(reason or "")
    if not allowed:
        setattr(self, "_pending_remediation_plan", None)
        setattr(self, "_pending_remediation_plan_id", "")
        return False
    try:
        from metadata_core.auto_enrollment import AUTO_ENROLLMENT_MIN_SPACING_SECONDS

        last_finalized_at = float(getattr(self, "_last_passive_auto_enrollment_finalized_at", 0.0) or 0.0)
        if last_finalized_at > 0.0 and (_facade().time.time() - last_finalized_at) < AUTO_ENROLLMENT_MIN_SPACING_SECONDS:
            self._last_passive_auto_enrollment_block_reason = "collection_spacing_active"
            return False
    except Exception:
        pass
    active_state = self._active_state_for_current_user()
    if self._session_flow(active_state) != "idle":
        return False
    self._pending_passive_auto_enrollment = True
    started = bool(start_enrollment(self, passive_auto_enrollment=True))
    if not started:
        self._pending_passive_auto_enrollment = False
        setattr(self, "_pending_remediation_plan", None)
        setattr(self, "_pending_remediation_plan_id", "")
        return False
    self._last_passive_auto_enrollment_start_at = _facade().time.time()
    self._last_passive_auto_enrollment_block_reason = "collecting"
    signal = getattr(self, "autoEnrollmentChanged", None)
    if signal is not None and hasattr(signal, "emit"):
        signal.emit()
    return True

def stop_passive_auto_enrollment_if_active(self, *, reason: str = "opt_out") -> bool:
    """Stop only a passive auto-enrollment session; leave manual sessions untouched."""

    state = self._active_state_for_current_user()
    if not _is_passive_auto_enrollment_state(state):
        return False
    if not bool(state.get("active")):
        return False
    if _passive_stop_or_finalize_already_requested(state) or bool(getattr(self, "_passive_auto_enrollment_finalizing", False)):
        self._last_passive_auto_enrollment_block_reason = "finalizing_passive_session"
        _debug_skip_duplicate_passive_finalization(self, reason="stop_already_requested", state=state)
        return False
    try:
        state = dict(state)
        state["auto_enrollment_stop_reason"] = str(reason or "opt_out")
        state["auto_enrollment_stop_requested"] = True
        state["auto_enrollment_stop_requested_at"] = _facade().time.time()
        _facade().write_session_state(state)
    except Exception:
        pass
    self.stopCurrentSession(silent=True)
    signal = getattr(self, "autoEnrollmentChanged", None)
    if signal is not None and hasattr(signal, "emit"):
        signal.emit()
    return True

def maybe_finalize_passive_auto_enrollment(self) -> bool:
    """Finalize only passive auto-enrollment sessions using safe live counters."""

    if not getattr(self, "_current_user", None):
        return False
    state = self._active_state_for_current_user()
    if not _is_passive_auto_enrollment_state(state):
        return False
    if _passive_stop_or_finalize_already_requested(state) or bool(getattr(self, "_passive_auto_enrollment_finalizing", False)):
        self._last_passive_auto_enrollment_finalize_reason = "already_finalizing"
        self._last_passive_auto_enrollment_block_reason = "finalizing_passive_session"
        _debug_skip_duplicate_passive_finalization(self, reason="already_finalizing", state=state)
        return False
    if bool(getattr(self, "_history_sync_pending", False)) and not _session_logger_process_alive(self):
        self._last_passive_auto_enrollment_finalize_reason = "archive_pending"
        self._last_passive_auto_enrollment_block_reason = "finalizing_passive_session"
        _debug_skip_duplicate_passive_finalization(self, reason="archive_pending", state=state)
        return False
    try:
        from metadata_core.auto_enrollment import passive_collection_should_finalize

        auto_state = {}
        try:
            auto_state = dict(getattr(self, "autoEnrollmentState", {}) or {})
        except Exception:
            auto_state = {}
        readiness_state = {}
        try:
            readiness_state = dict(getattr(self, "modelReadinessState", {}) or {})
        except Exception:
            readiness_state = {}
        should_finalize, reason = passive_collection_should_finalize(
            state,
            auto_enrollment_state=auto_state,
            model_readiness_state=readiness_state,
            profile=getattr(self, "_profile", {}) if isinstance(getattr(self, "_profile", None), dict) else {},
            now=_facade().time.time(),
        )
    except Exception:
        LOGGER.exception("Passive auto-enrollment finalizer decision failed")
        should_finalize, reason = False, "finalizer_error"
    self._last_passive_auto_enrollment_finalize_reason = str(reason or "")
    if not should_finalize:
        return False
    try:
        updated = dict(state)
        now = _facade().time.time()
        updated["auto_enrollment_finalize_reason"] = str(reason or "finalized")
        updated["auto_enrollment_stop_reason"] = str(reason or "finalized")
        updated["auto_enrollment_finalizing"] = True
        updated["auto_enrollment_finalizing_started_at"] = now
        updated["auto_enrollment_finalizing_started_at_text"] = _safe_recovery_timestamp(now)
        updated["auto_enrollment_stop_requested"] = True
        updated["auto_enrollment_stop_requested_at"] = now
        _facade().write_session_state(updated)
        self._runtime_state = updated
    except Exception:
        LOGGER.debug("Failed annotating passive auto-enrollment finalization state", exc_info=True)
    self._passive_auto_enrollment_finalizing = True
    self._last_passive_auto_enrollment_finalized_at = _facade().time.time()
    self._last_passive_auto_enrollment_block_reason = "finalizing_passive_session"
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("auto_enrollment", "Finalizing passive Smart Auto Enrollment session", payload={"reason": str(reason or "")})
    self.stopCurrentSession(silent=True)
    try:
        _facade().invalidate_session_discovery_cache()
    except Exception:
        LOGGER.debug("Failed invalidating session discovery cache after passive finalization", exc_info=True)
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    refresh_timer = getattr(self, "_update_refresh_timer", None)
    if callable(refresh_timer):
        refresh_timer(force=True)
    request = getattr(self, "requestRefresh", None)
    if callable(request):
        request("auto_enrollment:finalized_passive_session", True)
    signal = getattr(self, "autoEnrollmentChanged", None)
    if signal is not None and hasattr(signal, "emit"):
        signal.emit()
    readiness_signal = getattr(self, "modelReadinessChanged", None)
    if readiness_signal is not None and hasattr(readiness_signal, "emit"):
        readiness_signal.emit()
    return True

def _profile_production_approval_state(self) -> Dict[str, Any]:
    profile = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
    state = profile.get("production_approval_state") if isinstance(profile, dict) else {}
    return dict(state) if isinstance(state, dict) else {}

def _shadow_evidence_candidate_status(self) -> str:
    profile = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
    approval = _profile_production_approval_state(self)
    for source, key in (
        (approval, "modelStatus"),
        (approval, "candidate_status"),
        (profile, "candidate_model_status"),
        (profile, "model_status"),
    ):
        text = str((source or {}).get(key) or "").strip().lower()
        if text:
            return text
    return ""

def _process_is_alive(proc: Any) -> bool:
    try:
        return proc is not None and proc.poll() is None
    except Exception:
        return False

def _shadow_evidence_logger_running(self) -> bool:
    if not getattr(self, "_current_user", None):
        return False
    processes = getattr(self, "_running_processes", {})
    if not isinstance(processes, dict):
        return False
    return _process_is_alive(processes.get(_shadow_logger_process_key(self)))

def _shadow_evidence_monitor_running(self) -> bool:
    processes = getattr(self, "_running_processes", {})
    if not isinstance(processes, dict):
        return False
    proc = processes.get(_shadow_monitor_process_key(self))
    if not _process_is_alive(proc):
        return False
    state = self._active_state_for_current_user()
    session_kind = str((state or {}).get("session_kind") or "").strip().lower()
    return session_kind == SHADOW_EVIDENCE_SESSION_KIND or bool(getattr(self, "_pending_shadow_evidence_monitor_start", False))

def _production_monitor_process_running(self) -> bool:
    processes = getattr(self, "_running_processes", {})
    if not isinstance(processes, dict):
        return False
    proc = processes.get("monitor")
    if not _process_is_alive(proc):
        return False
    try:
        state = self._active_state_for_current_user()
    except Exception:
        state = {}
    session_kind = str((state or {}).get("session_kind") or (state or {}).get("runtime_mode") or "").strip().lower()
    return session_kind != SHADOW_EVIDENCE_SESSION_KIND

def _protected_or_unrelated_monitor_running(self) -> bool:
    return _production_monitor_process_running(self)
