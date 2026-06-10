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

def fail_pending_shadow_evidence_monitor_start(self, *, reason: str = "shadow_evidence_monitor_failed", detail: str = "", diagnostics: Optional[Dict[str, Any]] = None) -> None:
    facade = _facade()
    reason = str(reason or "shadow_evidence_monitor_failed").strip() or "shadow_evidence_monitor_failed"
    shadow_monitor_key = _shadow_monitor_process_key(self)
    shadow_logger_key = _shadow_logger_process_key(self)
    diagnostics = dict(diagnostics or _process_helpers.worker_diagnostics_snapshot(self, shadow_monitor_key) or {})
    shadow_enabled = False
    try:
        from bridge import session_runtime_helpers as _session_helpers

        shadow_enabled = bool(_session_helpers._independent_shadow_evidence_monitor_enabled(self))
    except Exception:
        shadow_enabled = False
    if not shadow_enabled:
        clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
        if callable(clear_shadow):
            try:
                clear_shadow()
            except Exception:
                LOGGER.debug("Failed clearing disabled shadow evidence monitor pending state", exc_info=True)
        else:
            setattr(self, "_pending_shadow_evidence_monitor_start", False)
        self._shadow_evidence_monitor_failed = False
        self._last_shadow_evidence_monitor_block_reason = ""
        self._last_shadow_evidence_monitor_skipped_reason = "independent_shadow_evidence_monitor_disabled"
        logger_proc = self._running_processes.get(shadow_logger_key) if self._current_user else None
        monitor_proc = self._running_processes.get(shadow_monitor_key)
        if self._current_user:
            facade.request_stop(_shadow_logger_stop_control_name(self))
        facade.request_stop(_shadow_monitor_stop_control_name(self))
        for proc in (monitor_proc, logger_proc):
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except (AttributeError, OSError):
                    pass
        cleanup = getattr(self, "_clear_stale_shadow_state_if_safe", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                LOGGER.debug("Failed clearing disabled shadow evidence state after startup failure", exc_info=True)
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug(
                "runtime",
                "shadow_evidence_monitor_skipped",
                payload={"reason": "independent_shadow_evidence_monitor_disabled", "failed_reason": reason},
                level="info",
            )
        set_status = getattr(self, "_set_status", None)
        if callable(set_status):
            set_status("Shadow evidence monitor is disabled for commercial runtime. Continuing without shadow capture.", "info")
        self._update_refresh_timer(force=True)
        return
    if not detail:
        detail, diagnostics = _process_helpers.worker_failure_detail(self, shadow_monitor_key, fallback=reason)
    detail = str(detail or reason).strip() or reason
    clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
    if callable(clear_shadow):
        clear_shadow()
    self._shadow_evidence_monitor_failed = True
    self._last_shadow_evidence_monitor_block_reason = reason
    state = self._active_state_for_current_user()
    failed_state = dict(state) if isinstance(state, dict) else {}
    if self._current_user:
        failed_state.setdefault("active", True)
        failed_state.setdefault("session_kind", "shadow_evidence")
        failed_state.setdefault("mode", "shadow_evidence")
        failed_state.setdefault("decision", "pending")
        failed_state.setdefault("user_id", self._current_user.get("user_id"))
    failed_state.update({
        "monitor_ready": False,
        "monitor_failed": True,
        "technical_failure": True,
        "awaiting_evidence": False,
        "monitor_error": detail,
        "protected_failure_reason": "",
        "shadow_evidence_blocked_reason": reason,
        "monitor_exit_code": diagnostics.get("exit_code"),
        "monitor_startup_error_kind": reason,
        "runtime_diagnostic_code": reason,
        "runtime_diagnostic_reason": detail,
        "runtime_diagnostics": {
            "phase": "shadow_evidence_monitor_startup_failure",
            "reason": reason,
            "exit_code": diagnostics.get("exit_code"),
            "stderr_tail": list(diagnostics.get("stderr_tail") or [])[-3:],
            "stdout_tail": list(diagnostics.get("stdout_tail") or [])[-3:],
        },
        "runtime_recent_risks": [],
        "runtime_recent_decisions": [],
        "runtime_window_count": 0,
        "runtime_quality_ok_windows": 0,
        "runtime_last_window_diag": {},
        "runtime_mode": "shadow_evidence",
        "evidence_source": "shadow_evidence_monitor",
        "status": "shadow_evidence_failed",
    })
    facade.write_session_state(failed_state)
    logger_proc = self._running_processes.get(shadow_logger_key) if self._current_user else None
    monitor_proc = self._running_processes.get(shadow_monitor_key)
    if self._current_user:
        facade.request_stop(_shadow_logger_stop_control_name(self))
    facade.request_stop(_shadow_monitor_stop_control_name(self))
    for proc in (monitor_proc, logger_proc):
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except (AttributeError, OSError):
                pass
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("runtime", "shadow_evidence_monitor_blocked", payload={"reason": reason, "detail": detail}, level="warn")
    set_status = getattr(self, "_set_status", None)
    if callable(set_status):
        set_status("Shadow evidence monitor could not start safely. Protected Sessions remain unavailable.", "warn")
    self._update_refresh_timer(force=True)

def _safe_monitor_start_detail(reason: str, *, exit_reason: str = "", exit_detail: Optional[Dict[str, Any]] = None, worker_detail: str = "") -> str:
    parts = [str(reason or "monitor_start_failed").strip() or "monitor_start_failed"]
    if exit_reason:
        parts.append(f"monitor_exit_reason={exit_reason}")
    if isinstance(exit_detail, dict) and exit_detail:
        interesting = []
        for key in (
            "state_status",
            "state_decision",
            "state_stop_reason",
            "state_active",
            "expected_session_id",
            "actual_session_id",
            "error_type",
        ):
            if key in exit_detail:
                interesting.append(f"{key}={exit_detail.get(key)}")
        if interesting:
            parts.append("; ".join(interesting))
    if worker_detail and "removed orphaned session_state lock" not in worker_detail.lower():
        parts.append(str(worker_detail).strip()[:240])
    return " | ".join(part for part in parts if part)

def _monitor_start_exit_reason_from_state(self, *, fallback_reason: str, fallback_detail: str, diagnostics: Dict[str, Any]) -> tuple[str, str, Dict[str, Any]]:
    """Preserve the monitor's own startup-exit reason before overwriting session_state.

    The monitor process can exit cleanly during startup after writing a final
    state such as ``monitor_exit_reason=session_inactive`` or
    ``session_id_mismatch``.  Older bridge handling replaced that with a generic
    ``monitor_process_lost (exit code 0)`` message, which made the UI claim the
    runtime was merely busy/locked and hid the actual state transition.
    """
    reason = str(fallback_reason or "monitor_process_lost").strip() or "monitor_process_lost"
    detail = str(fallback_detail or "").strip()
    enriched = dict(diagnostics or {})
    try:
        state = read_session_state(default={})
    except Exception:
        state = {}
    state = state if isinstance(state, dict) else {}
    exit_reason = str(state.get("monitor_exit_reason") or "").strip().lower()
    exit_detail = state.get("monitor_exit_detail") if isinstance(state.get("monitor_exit_detail"), dict) else {}
    if exit_reason and exit_reason not in {"unknown", "monitor_exited_after_ready"}:
        reason = _MONITOR_START_EXIT_REASON_MAP.get(exit_reason, f"monitor_start_{exit_reason}")
        detail = _safe_monitor_start_detail(reason, exit_reason=exit_reason, exit_detail=exit_detail, worker_detail=detail)
    elif reason in {"monitor_process_lost", "monitor_exited_before_ready"}:
        stderr_tail = "\n".join(str(line) for line in list(enriched.get("stderr_tail") or [])[-5:])
        if "Removed orphaned session_state lock from dead owner" in stderr_tail:
            reason = "monitor_start_stale_lock_recovered"
            detail = _safe_monitor_start_detail(reason, worker_detail=detail)
    enriched.update({
        "monitor_start_exit_reason": reason,
        "monitor_exit_reason": exit_reason,
        "monitor_exit_detail": dict(exit_detail or {}),
        "monitor_exit_recorded_at": state.get("monitor_exit_recorded_at"),
        "monitor_start_state_status": state.get("status"),
        "monitor_start_state_active": state.get("active"),
        "monitor_start_state_session_id": state.get("session_id"),
    })
    return reason, (detail or reason), enriched
