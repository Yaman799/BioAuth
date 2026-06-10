"""Extracted implementation section for `bridge/refresh_runtime_helpers.py`."""
from __future__ import annotations
from importlib import import_module
import logging
import re
import time
from typing import Any, Dict, Optional
from bridge import session_runtime_helpers as _process_helpers
from bridge.shared import read_session_state
from bridge.qt_thread_dispatch import dispatch_to_qt_thread, is_qt_main_thread
from bioauth_runtime import runtime_boundary

def fail_pending_monitor_start(self, *, reason: str = "protected_monitor_failed", detail: str = "", diagnostics: Optional[Dict[str, Any]] = None) -> None:
    facade = _facade()
    reason = str(reason or "protected_monitor_failed").strip() or "protected_monitor_failed"
    diagnostics = dict(diagnostics or _process_helpers.worker_diagnostics_snapshot(self, "monitor") or {})
    if not detail:
        detail, diagnostics = _process_helpers.worker_failure_detail(self, "monitor", fallback=reason)
    detail = str(detail or reason).strip() or reason
    reason, detail, diagnostics = _monitor_start_exit_reason_from_state(
        self,
        fallback_reason=reason,
        fallback_detail=detail,
        diagnostics=diagnostics,
    )
    self._clear_pending_monitor_start()
    self._monitor_start_failed = True
    state = self._active_state_for_current_user()
    failed_state = dict(state) if isinstance(state, dict) else {}
    if self._current_user:
        failed_state.setdefault("active", True)
        failed_state.setdefault("session_kind", "protected")
        failed_state.setdefault("mode", "standalone")
        failed_state.setdefault("decision", "pending")
        failed_state.setdefault("user_id", self._current_user.get("user_id"))
    failed_state.update(
        {
            "monitor_ready": False,
            "monitor_failed": True,
            "technical_failure": True,
            "awaiting_evidence": False,
            "monitor_error": detail,
            "protected_failure_reason": detail,
            "monitor_exit_code": diagnostics.get("exit_code"),
            "monitor_startup_error_kind": reason,
            "monitor_start_exit_reason": diagnostics.get("monitor_start_exit_reason") or reason,
            "monitor_exit_reason": diagnostics.get("monitor_exit_reason") or "",
            "monitor_exit_detail": dict(diagnostics.get("monitor_exit_detail") or {}),
            "monitor_exit_recorded_at": diagnostics.get("monitor_exit_recorded_at"),
            "monitor_start_state_status": diagnostics.get("monitor_start_state_status"),
            "monitor_start_state_active": diagnostics.get("monitor_start_state_active"),
            "monitor_start_state_session_id": diagnostics.get("monitor_start_state_session_id"),
            "runtime_diagnostic_code": reason,
            "runtime_diagnostic_reason": detail,
            "runtime_diagnostics": {
                "phase": "monitor_startup_failure",
                "reason": reason,
                "exit_code": diagnostics.get("exit_code"),
                "monitor_start_exit_reason": diagnostics.get("monitor_start_exit_reason") or reason,
                "monitor_exit_reason": diagnostics.get("monitor_exit_reason") or "",
                "monitor_exit_detail": dict(diagnostics.get("monitor_exit_detail") or {}),
                "monitor_start_state_status": diagnostics.get("monitor_start_state_status"),
                "monitor_start_state_active": diagnostics.get("monitor_start_state_active"),
                "monitor_start_state_session_id": diagnostics.get("monitor_start_state_session_id"),
                "stderr_tail": list(diagnostics.get("stderr_tail") or [])[-3:],
                "stdout_tail": list(diagnostics.get("stdout_tail") or [])[-3:],
            },
            "runtime_recent_risks": [],
            "runtime_recent_decisions": [],
            "runtime_window_count": 0,
            "runtime_quality_ok_windows": 0,
            "runtime_last_window_diag": {},
            "status": reason if str(reason).startswith("monitor_start_") or str(reason) == "monitor_process_lost" else "monitor_unavailable",
        }
    )
    facade.write_session_state(failed_state)
    logger_proc = self._running_processes.get(self._logger_process_key()) if self._current_user else None
    monitor_proc = self._running_processes.get("monitor")
    if self._current_user:
        facade.request_stop(self._logger_key())
    facade.request_stop("monitor")
    for proc in (monitor_proc, logger_proc):
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except (AttributeError, OSError):
                pass
    self._set_status(self._t("protected_monitor_failed"), "danger")
    self._update_refresh_timer(force=True)

def maybe_finish_pending_monitor_start(self) -> None:
    facade = _facade()
    pending_shadow = bool(getattr(self, "_pending_shadow_evidence_monitor_start", False))
    if not self._pending_monitor_start and not pending_shadow:
        return
    if pending_shadow:
        pending_user = facade.slugify_username(getattr(self, "_shadow_evidence_monitor_user_id", "") or "")
    else:
        pending_user = facade.slugify_username(getattr(self, "_pending_monitor_user_id", "") or "")
    current_user = facade.slugify_username((self._current_user or {}).get("user_id", "") or "")
    if not self._current_user or pending_user != current_user:
        if pending_shadow:
            clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
            if callable(clear_shadow):
                clear_shadow()
        else:
            self._clear_pending_monitor_start()
        return

    state = self._active_state_for_current_user()
    try:
        from bridge import session_runtime_helpers as _session_helpers
        state = _session_helpers.merge_worker_heartbeats_into_state(self, state, persist=True)
    except Exception:
        pass
    session_kind = str(state.get("session_kind") or "").strip().lower()
    expected_kind = "shadow_evidence" if pending_shadow else "protected"
    monitor_ready = bool(state.get("monitor_ready"))
    if monitor_ready and session_kind == expected_kind:
        if pending_shadow:
            clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
            if callable(clear_shadow):
                clear_shadow()
        else:
            self._clear_pending_monitor_start()
        return

    logger_key = _shadow_logger_process_key(self) if pending_shadow else self._logger_process_key()
    monitor_key = _shadow_monitor_process_key(self) if pending_shadow else "monitor"
    logger_proc = self._running_processes.get(logger_key)
    logger_alive = logger_proc is not None and logger_proc.poll() is None
    fail = self._fail_pending_shadow_evidence_monitor_start if pending_shadow else self._fail_pending_monitor_start
    if not logger_alive:
        fail(reason="logger_lost_before_monitor_ready")
        return

    monitor_proc = self._running_processes.get(monitor_key)
    monitor_alive = monitor_proc is not None and monitor_proc.poll() is None
    deadline = float(getattr(self, "_shadow_evidence_monitor_start_deadline", 0.0) if pending_shadow else getattr(self, "_monitor_start_deadline", 0.0) or 0.0)
    deadline_hit = facade.time.time() >= deadline

    if monitor_proc is not None and not monitor_alive:
        diagnostics = _process_helpers.record_completed_process(self, monitor_key, monitor_proc, reason="exited_before_ready")
        self._running_processes.pop(monitor_key, None)
        detail, diagnostics = _process_helpers.worker_failure_detail(self, monitor_key, fallback="monitor_exited_before_ready")
        fail(reason="monitor_exited_before_ready", detail=detail, diagnostics=diagnostics)
        return

    if monitor_alive:
        if deadline_hit:
            try:
                from bridge import session_runtime_helpers as _session_helpers
                monitor_hb = _session_helpers._read_matching_worker_heartbeat(self, "monitor", state)
                hb_age = _session_helpers._heartbeat_age_sec(monitor_hb) if monitor_hb else 999999.0
                if monitor_hb and hb_age <= max(30.0, facade.MONITOR_START_GRACE_SEC * 3.0):
                    if pending_shadow:
                        self._shadow_evidence_monitor_start_deadline = facade.time.time() + facade.MONITOR_START_GRACE_SEC
                    else:
                        self._monitor_start_deadline = facade.time.time() + facade.MONITOR_START_GRACE_SEC
                    debug = getattr(self, "_debug_trace", None)
                    if callable(debug):
                        debug("runtime", "monitor_start_wait_extended_by_worker_heartbeat", payload={"heartbeat_age_sec": hb_age, "status": monitor_hb.get("status"), "monitor_ready": monitor_hb.get("monitor_ready")}, level="debug")
                    return
            except Exception:
                pass
            fail(reason="monitor_start_timeout")
        return

    launch_attempted = bool(getattr(self, "_shadow_evidence_monitor_launch_attempted", False) if pending_shadow else getattr(self, "_monitor_launch_attempted", False))
    if launch_attempted:
        detail, diagnostics = _process_helpers.worker_failure_detail(self, monitor_key, fallback="monitor_process_lost")
        fail(reason="monitor_process_lost", detail=detail, diagnostics=diagnostics)
        return

    logger_ready = bool(state.get("logger_ready"))
    if bool(state.get("logger_failed")) or str(state.get("status") or "").strip().lower() in {"failed", "logger_runtime_error", "logger_unavailable", "logger_start_lost"}:
        fail(reason="logger_reported_failure")
        return
    if not logger_ready:
        if deadline_hit:
            fail(reason="logger_ready_timeout")
        return

    ready_to_spawn = logger_ready and bool(state.get("active")) and session_kind == expected_kind
    if ready_to_spawn:
        env = self._session_process_env() or {}
        if pending_shadow:
            env.update({"BIOAUTH_RUNTIME_MODE": "shadow_evidence", "BIOAUTH_SHADOW_EVIDENCE_ONLY": "1", "BIOAUTH_EVIDENCE_SOURCE": "shadow_evidence_monitor"})
        started = self._start_process(monitor_key, [facade.MONITOR_SCRIPT, self._current_user["user_id"]], extra_env=env)
        if not started:
            fail(reason="monitor_start_timeout")
            return
        debug = getattr(self, "_debug_trace", None)
        if pending_shadow:
            self._shadow_evidence_monitor_launch_attempted = True
            self._shadow_evidence_monitor_start_deadline = facade.time.time() + facade.MONITOR_START_GRACE_SEC
            if callable(debug):
                debug("runtime", "shadow_evidence_monitor_started", payload={"session_kind": "shadow_evidence"}, level="info")
        else:
            self._monitor_launch_attempted = True
            self._monitor_start_deadline = facade.time.time() + facade.MONITOR_START_GRACE_SEC

def _safe_refresh_reason(reason: Any) -> str:
    text = str(reason or "manual").strip().lower().replace(" ", "_")
    safe = "".join(ch for ch in text if ch.isalnum() or ch in {"_", "-", ".", ":"})
    return (safe or "manual")[:96]

def _ensure_refresh_request_state(self) -> None:
    if not hasattr(self, "_refresh_inflight"):
        self._refresh_inflight = False
    if not hasattr(self, "_refresh_requested"):
        self._refresh_requested = False
    if not hasattr(self, "_refresh_requested_force"):
        self._refresh_requested_force = False
    if not hasattr(self, "_refresh_requested_reason"):
        self._refresh_requested_reason = ""
    if not hasattr(self, "_refresh_debounce_pending"):
        self._refresh_debounce_pending = False
    if not hasattr(self, "_refresh_debounce_force"):
        self._refresh_debounce_force = False
    if not hasattr(self, "_refresh_debounce_reason"):
        self._refresh_debounce_reason = ""
    if not hasattr(self, "_refresh_active_reason"):
        self._refresh_active_reason = ""
    if not hasattr(self, "_refresh_active_coalesced"):
        self._refresh_active_coalesced = False
    if not hasattr(self, "_refresh_followup_scheduled"):
        self._refresh_followup_scheduled = False

def _is_critical_refresh(reason: str, force: bool) -> bool:
    if force:
        return True
    lowered = _safe_refresh_reason(reason)
    return any(token in lowered for token in _CRITICAL_REFRESH_REASON_TOKENS)

def _merge_refresh_reason(previous: str, next_reason: str) -> str:
    previous = _safe_refresh_reason(previous) if previous else ""
    next_reason = _safe_refresh_reason(next_reason)
    if not previous:
        return next_reason
    if next_reason in previous.split("+"):
        return previous
    merged = f"{previous}+{next_reason}"
    return merged[:96]
