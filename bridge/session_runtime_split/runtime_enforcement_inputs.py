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

def session_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
    facade = _facade()
    state = state if isinstance(state, dict) else self._runtime_state
    decision = str(state.get("decision") or "").strip().lower()
    session_kind = str(state.get("session_kind") or "").strip().lower()
    pending_logger_kind = str(getattr(self, "_pending_logger_session_kind", "") or "").strip().lower()
    final_decision = str(state.get("final_decision") or state.get("archive_label") or "").strip().lower()
    shadow_evidence = session_kind == SHADOW_EVIDENCE_SESSION_KIND
    forced_stop = bool(
        state.get("forced_stop")
        or state.get("app_locked")
        or state.get("monitor_holding")
        or state.get("restriction_active")
        or (not shadow_evidence and decision == "intruder")
        or (not shadow_evidence and final_decision == "intruder")
    )
    status = str(state.get("status") or "").strip().lower()
    retry_handoff_state = str(state.get("retry_handoff_state") or getattr(self, "_retry_handoff_state", "") or "").strip().lower()
    resume_pending = bool(state.get("auto_resume_pending") or state.get("resume_after_unlock"))

    if _is_terminal_protected_state(state):
        return "idle"

    # Commercial-Core-22B: stale hidden shadow evidence state must not be
    # surfaced as an active user flow.  If no exact shadow logger/monitor process
    # is alive, clear the old state before the first heartbeat/debug snapshot can
    # report `flow=shadow_evidence_collecting`.  Live shadow developer mode is
    # still respected because _is_shadow_runtime_process_running() checks exact
    # hidden shadow process identities.
    shadow_pending = bool(getattr(self, "_pending_shadow_evidence_monitor_start", False)) or (bool(getattr(self, "_pending_logger_start", False)) and pending_logger_kind == SHADOW_EVIDENCE_SESSION_KIND)
    shadow_retry_state = retry_handoff_state.startswith("shadow_evidence_")
    if (shadow_evidence or shadow_pending or shadow_retry_state) and not _is_shadow_runtime_process_running(self):
        try:
            _clear_stale_shadow_state_if_safe(self, state)
        except Exception:
            LOGGER.debug("Failed clearing stale shadow state while resolving session flow", exc_info=True)
        if isinstance(getattr(self, "_runtime_state", None), dict):
            self._runtime_state = {}
        return "idle"

    if retry_handoff_state == "shadow_evidence_settling_for_retry":
        return "shadow_evidence_settling_for_retry"
    if retry_handoff_state == "shadow_evidence_stopped_for_retry":
        return "retry_training_ready"
    if shadow_pending:
        return "shadow_evidence_starting"
    if self._pending_monitor_start:
        return "protected_starting"
    if resume_pending and not state.get("active"):
        return "protected_resume_pending"
    if forced_stop:
        return "protected_forced_stop"
    if not state.get("active"):
        return "idle"
    if session_kind == "enrollment":
        return "enrollment_active"
    monitor_ready = bool(state.get("monitor_ready"))
    if shadow_evidence:
        if facade.runtime_status_is_technical_failure(status) or bool(state.get("technical_failure")) or bool(getattr(self, "_shadow_evidence_monitor_failed", False)):
            return "shadow_evidence_failed"
        if not monitor_ready:
            return "shadow_evidence_starting"
        if status in {"starting", "model_unavailable", "insufficient_windows", "insufficient_events", "awaiting_evidence", "shadow_evidence"} or bool(state.get("awaiting_evidence")):
            return "shadow_evidence_collecting"
        return "shadow_evidence_active"
    if facade.runtime_status_is_technical_failure(status) or bool(state.get("technical_failure")):
        return "protected_technical_failure"
    if session_kind == "protected" and status == "insufficient_windows":
        return "protected_collecting"
    if session_kind == "protected" and (bool(getattr(self, "_monitor_start_failed", False)) or not monitor_ready):
        return "protected_starting"
    if decision == "suspicious":
        return "protected_warning"
    return "protected_active"

def maybe_autostart_protection(self) -> bool:
    if not bool(getattr(self, "_boot_autostart_pending", False)):
        return False
    if _facade().time.time() < float(getattr(self, "_boot_autostart_earliest_at", 0.0) or 0.0):
        return False
    flow = self._session_flow()
    profile = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
    settings = getattr(self, "_app_settings", {}) if isinstance(getattr(self, "_app_settings", None), dict) else {}
    decision = startup_protected_session_decision(
        settings=settings,
        background=bool(getattr(self, "_background", False)),
        authenticated=bool(getattr(self, "_current_user", None)),
        has_current_consent=bool(getattr(self, "_has_current_user_welcome_consent", lambda: False)()),
        profile=profile,
        flow=flow,
    )
    if not bool(decision.get("allowed")):
        # Startup autostart is one-shot and fail-closed. It must not retry in a loop,
        # unlock Protected Sessions, collect owner enrollment data, or change model gates.
        self._boot_autostart_pending = False
        try:
            write_release_runtime_event(
                "startup_protected_session_blocked",
                reason=str(decision.get("reason") or "blocked"),
                background=bool(getattr(self, "_background", False)),
                run_on_startup=bool(settings.get("run_on_startup", False)),
                remember_login_enabled=bool(settings.get("remember_login_enabled", False)),
                startup_protected_sessions_enabled=bool(settings.get("startup_protected_sessions_enabled", False)),
                authenticated=bool(getattr(self, "_current_user", None)),
                profile_production_ready=bool(profile.get("production_ready")),
                model_status=str(decision.get("model_status") or ""),
                flow=str(decision.get("flow") or flow),
            )
        except Exception:
            pass
        return False
    self._boot_autostart_pending = False
    try:
        write_release_runtime_event(
            "startup_protected_session_allowed",
            reason="allowed",
            background=True,
            run_on_startup=True,
            remember_login_enabled=True,
            startup_protected_sessions_enabled=True,
            authenticated=True,
            profile_production_ready=True,
            model_status=str(decision.get("model_status") or ""),
            flow="idle",
        )
    except Exception:
        pass
    return bool(self._start_protected_session(auto_resume=False, trigger_refresh=True))

def _is_passive_auto_enrollment_state(state: Optional[Dict[str, Any]]) -> bool:
    try:
        from metadata_core.auto_enrollment import is_passive_auto_enrollment_state

        return is_passive_auto_enrollment_state(state)
    except Exception:
        if not isinstance(state, dict):
            return False
        return bool(state.get("auto_enrollment")) and str(state.get("collection_source") or "").strip().lower() == "passive_auto_enrollment"

def _session_logger_process_alive(self) -> bool:
    processes = getattr(self, "_running_processes", {})
    if not isinstance(processes, dict):
        return False
    key_fn = getattr(self, "_logger_process_key", None)
    expected_key = ""
    if callable(key_fn):
        try:
            expected_key = str(key_fn() or "")
        except (TypeError, RuntimeError, ValueError):
            expected_key = ""
    if not expected_key:
        return False
    process = processes.get(expected_key)
    poll = getattr(process, "poll", None)
    if process is not None and not callable(poll):
        return True
    if callable(poll):
        try:
            return poll() is None
        except (OSError, RuntimeError, ValueError):
            return True
    return False

def _passive_stop_or_finalize_already_requested(state: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(state, dict):
        return False
    return bool(
        state.get("auto_enrollment_finalizing")
        or state.get("auto_enrollment_stop_requested")
        or state.get("stop_requested")
        or state.get("archive_requested")
        or state.get("archive_pending")
    )

def _passive_finalization_epoch(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
        if numeric > 0.0:
            return numeric
    except (TypeError, ValueError, OverflowError):
        pass
    text = str(value or "").strip()
    if not text:
        return None
    try:
        from datetime import datetime

        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return float(parsed.timestamp())
    except (TypeError, ValueError, OSError):
        return None

def _passive_finalization_started_at(self, state: Optional[Dict[str, Any]], *, now: Optional[float] = None) -> Optional[float]:
    data = state if isinstance(state, dict) else {}
    for key in (
        "auto_enrollment_finalizing_started_at",
        "auto_enrollment_finalizing_since",
        "auto_enrollment_stop_requested_at",
    ):
        value = _passive_finalization_epoch(data.get(key))
        if value is not None:
            return value
    if now is None:
        now = _facade().time.time()
    session_id = str(data.get("session_id") or "")
    signature = f"{session_id}:{data.get('started_at') or ''}:{data.get('user_id') or ''}"
    observed_signature = str(getattr(self, "_passive_finalization_observed_signature", "") or "")
    observed_since = float(getattr(self, "_passive_finalization_observed_since", 0.0) or 0.0)
    if signature and signature == observed_signature and observed_since > 0.0:
        return observed_since
    setattr(self, "_passive_finalization_observed_signature", signature)
    setattr(self, "_passive_finalization_observed_since", float(now))
    return None

def _passive_finalization_elapsed_seconds(self, state: Optional[Dict[str, Any]]) -> Optional[float]:
    try:
        now = _facade().time.time()
        started_at = _passive_finalization_started_at(self, state, now=now)
        if started_at is None:
            return None
        return max(0.0, float(now) - float(started_at))
    except (TypeError, ValueError, OverflowError, RuntimeError):
        return None
