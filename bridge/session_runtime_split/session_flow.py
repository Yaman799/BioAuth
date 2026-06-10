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

def _restore_shadow_evidence_pending_context(self, state: Optional[Dict[str, Any]] = None) -> None:
    if not getattr(self, "_current_user", None):
        return
    facade = _facade()
    state = state if isinstance(state, dict) else self._active_state_for_current_user()
    if not getattr(self, "_active_live_session_dir", None):
        live_dir = str((state or {}).get("live_session_dir") or "").strip()
        if live_dir:
            self._active_live_session_dir = live_dir
    if not str(getattr(self, "_pending_logger_session_id", "") or "").strip():
        session_id = str((state or {}).get("session_id") or "").strip()
        if session_id:
            self._pending_logger_session_id = session_id
    if not str(getattr(self, "_pending_logger_run_id", "") or "").strip():
        run_id = str((state or {}).get("run_id") or "").strip()
        if run_id:
            self._pending_logger_run_id = run_id
    self._pending_shadow_evidence_monitor_start = True
    self._shadow_evidence_monitor_user_id = self._current_user["user_id"]
    if float(getattr(self, "_shadow_evidence_monitor_start_deadline", 0.0) or 0.0) <= 0.0:
        self._shadow_evidence_monitor_start_deadline = facade.time.time() + facade.MONITOR_START_GRACE_SEC
    self._shadow_evidence_monitor_failed = False
    updated = dict(state or {})
    updated.setdefault("active", True)
    updated.setdefault("user_id", self._current_user.get("user_id"))
    updated.update({
        "session_kind": SHADOW_EVIDENCE_SESSION_KIND,
        "mode": SHADOW_EVIDENCE_SESSION_KIND,
        "runtime_mode": SHADOW_EVIDENCE_SESSION_KIND,
        "evidence_source": SHADOW_EVIDENCE_SOURCE,
        "status": "starting",
        "technical_failure": False,
        "monitor_failed": False,
        "monitor_error": "",
        "shadow_evidence_blocked_reason": "",
    })
    try:
        facade.write_session_state(updated)
    except Exception:
        LOGGER.debug("Failed restoring shadow evidence pending state", exc_info=True)
    self._runtime_state = updated

def _mark_shadow_evidence_monitor_collecting(self, state: Optional[Dict[str, Any]] = None) -> None:
    state = dict(state) if isinstance(state, dict) else dict(self._active_state_for_current_user() or {})
    if getattr(self, "_current_user", None):
        state.setdefault("active", True)
        state.setdefault("user_id", self._current_user.get("user_id"))
    state.update({
        "session_kind": SHADOW_EVIDENCE_SESSION_KIND,
        "mode": SHADOW_EVIDENCE_SESSION_KIND,
        "runtime_mode": SHADOW_EVIDENCE_SESSION_KIND,
        "evidence_source": SHADOW_EVIDENCE_SOURCE,
        "status": "shadow_evidence",
        "technical_failure": False,
        "monitor_failed": False,
        "shadow_evidence_blocked_reason": "",
    })
    try:
        _facade().write_session_state(state)
    except Exception:
        LOGGER.debug("Failed writing shadow evidence collecting state", exc_info=True)
    self._runtime_state = state
    self._shadow_evidence_monitor_failed = False
    self._last_shadow_evidence_monitor_block_reason = ""

def _shadow_evidence_block_reason(self, *, auto_bootstrap: bool = False) -> str:
    facade = _facade()
    if not self._current_user:
        return "not_authenticated"
    if bool(getattr(self, "_shadow_automation_paused", False)):
        return "developer_shadow_paused"
    if not self._has_current_user_welcome_consent():
        return "consent_required"
    if bool(getattr(self, "_training_in_progress", False)):
        return "training_active"
    training_progress = getattr(self, "_training_progress", {}) if isinstance(getattr(self, "_training_progress", None), dict) else {}
    training_stage = str(training_progress.get("stage_key") or training_progress.get("stage") or "").strip().lower()
    if "evaluat" in training_stage:
        return "evaluation_active"
    if bool(getattr(self, "_passive_auto_enrollment_finalizing", False)) or bool(getattr(self, "_history_sync_pending", False)):
        return "passive_auto_enrollment_finalizing"
    if _is_passive_auto_enrollment_state(getattr(self, "_runtime_state", {})) or bool(getattr(self, "_pending_passive_auto_enrollment", False)):
        return "passive_auto_enrollment_active"
    if _normal_logger_start_pending(self):
        return "logger_pending_conflict"
    if bool(getattr(self, "_pending_monitor_start", False)):
        return "protected_monitor_pending"
    if not _independent_shadow_evidence_monitor_enabled(self):
        return "independent_shadow_evidence_monitor_disabled"
    candidate_status = _shadow_evidence_candidate_status(self)
    if candidate_status != "approved_for_shadow":
        return "candidate_not_approved_for_shadow"
    profile = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
    approval = _profile_production_approval_state(self)
    if bool(profile.get("production_ready")) or bool(approval.get("productionReady")) or bool(approval.get("protectedSessionsAvailable")):
        return "production_ready_use_protected_sessions"
    runtime_reason = str(approval.get("runtimeValidationReason") or "").strip().lower()
    shadow_start_allowed_reasons = {
        "ok",
        "",
        "runtime_pointer_missing",
        "runtime_pointer_invalid",
        "model_not_approved_for_production",
        "bundle_role_not_production",
        "runtime_pointer_missing_bundle_base",
        "shadow_validation_not_started",
        "shadow_validation_running",
        "shadow_validation_needs_evidence",
        "production_evidence_missing",
        "production_evidence_partial",
        "production_evidence_required",
    }
    if runtime_reason and runtime_reason not in shadow_start_allowed_reasons:
        return f"runtime_schema_or_bundle_blocked:{runtime_reason}"
    active_state = self._active_state_for_current_user()
    active_kind = str(active_state.get("session_kind") or "").strip().lower()
    if active_state.get("active") and active_kind == "protected":
        return "protected_session_active"
    if active_state.get("active") and active_kind == "enrollment":
        return "enrollment_active"
    if _protected_or_unrelated_monitor_running(self):
        return "monitor_process_conflict"
    if active_state.get("active") and active_kind == SHADOW_EVIDENCE_SESSION_KIND:
        # A shadow evidence logger state is the normal middle of the bootstrap.
        # Do not collapse logger and monitor duplicates into the generic
        # already_running failure that is used for interactive session starts.
        return ""
    flow = self._session_flow(active_state)
    if flow not in {"idle", "shadow_evidence_starting", "shadow_evidence_collecting", "shadow_evidence_active", "shadow_evidence_failed"}:
        return f"runtime_busy:{flow}"
    if bool(getattr(self, "_shadow_evidence_monitor_launch_attempted", False)) and not bool(getattr(self, "_pending_shadow_evidence_monitor_start", False)):
        last_at = float(getattr(self, "_last_shadow_evidence_monitor_attempt_at", 0.0) or 0.0)
        if auto_bootstrap and last_at and (facade.time.time() - last_at) < SHADOW_EVIDENCE_BOOTSTRAP_COOLDOWN_SECONDS:
            return "shadow_evidence_start_rate_limited"
    return ""
