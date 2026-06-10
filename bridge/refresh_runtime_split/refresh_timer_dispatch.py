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

def fail_pending_logger_start(self, *, reason: str = "logger_unavailable", detail: str = "") -> None:
    facade = _facade()
    reason = str(reason or "logger_unavailable").strip() or "logger_unavailable"
    key = getattr(self, "_pending_logger_process_key", None) or (self._logger_process_key() if self._current_user else None)
    pending_user = str(getattr(self, "_pending_logger_user_id", "") or ((self._current_user or {}).get("user_id", "") if self._current_user else ""))
    pending_kind = str(getattr(self, "_pending_logger_session_kind", "") or "protected").strip().lower() or "protected"
    pending_session_id = str(getattr(self, "_pending_logger_session_id", "") or "")
    pending_run_id = str(getattr(self, "_pending_logger_run_id", "") or "")
    if self._current_user:
        facade.request_stop(self._logger_key())
        facade.request_stop("monitor")
    monitor_proc = self._running_processes.get("monitor")
    if monitor_proc is not None and monitor_proc.poll() is None:
        try:
            monitor_proc.terminate()
        except (AttributeError, OSError):
            pass
    self._running_processes.pop("monitor", None)
    if key:
        proc = self._running_processes.get(key)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except (AttributeError, OSError):
                pass
        self._running_processes.pop(key, None)
    state = self._active_state_for_current_user()
    failed_state = dict(state) if isinstance(state, dict) and state else {}
    if self._current_user and pending_kind == "protected":
        failed_state.update(
            {
                "active": False,
                "session_kind": "protected",
                "mode": failed_state.get("mode") or "standalone",
                "decision": "",
                "user_id": pending_user or self._current_user["user_id"],
                "session_id": failed_state.get("session_id") or pending_session_id,
                "run_id": failed_state.get("run_id") or pending_run_id,
                "logger_ready": False,
                "logger_failed": True,
                "monitor_ready": False,
                "monitor_failed": False,
                "technical_failure": True,
                "awaiting_evidence": False,
                "pending_monitor_start": False,
                "protected_failure_reason": reason,
                "monitor_error": detail or reason,
                "runtime_diagnostic_code": reason,
                "runtime_diagnostic_reason": detail or reason,
                "runtime_diagnostics": {
                    "phase": "logger_startup_failure",
                    "reason": reason,
                    "detail": detail or reason,
                },
                "runtime_recent_risks": [],
                "runtime_recent_decisions": [],
                "runtime_window_count": 0,
                "runtime_quality_ok_windows": 0,
                "runtime_last_window_diag": {},
                "status": "logger_unavailable",
            }
        )
        facade.write_session_state(failed_state)
    self._last_process_start_error = detail or self._t("process_not_ready", process="logger.py")
    self._set_status(self._last_process_start_error, "danger")
    self._clear_pending_logger_start()
    if hasattr(self, "_clear_pending_monitor_start"):
        self._clear_pending_monitor_start()
    self._monitor_launch_attempted = False
    self._logger_start_failed = True
    self._update_refresh_timer(force=True)

def maybe_finish_pending_logger_start(self) -> None:
    facade = _facade()
    if not bool(getattr(self, "_pending_logger_start", False)):
        return
    pending_user = facade.slugify_username(getattr(self, "_pending_logger_user_id", "") or "")
    current_user = facade.slugify_username((self._current_user or {}).get("user_id", "") or "")
    if not self._current_user or pending_user != current_user:
        self._clear_pending_logger_start()
        return
    key = getattr(self, "_pending_logger_process_key", None) or self._logger_process_key()
    proc = self._running_processes.get(key)
    if proc is None:
        self._fail_pending_logger_start(reason="logger_start_lost")
        return
    exit_code = proc.poll()
    if exit_code is not None:
        self._running_processes.pop(key, None)
        detail = facade.translate_string(
            getattr(self, "_language", "en"),
            "process_exited_immediately",
            process="logger.py",
            code=exit_code,
        )
        self._fail_pending_logger_start(reason="logger_exited_before_ready", detail=detail)
        return

    state = self._active_state_for_current_user()
    try:
        from bridge import session_runtime_helpers as _session_helpers
        state = _session_helpers.merge_worker_heartbeats_into_state(self, state, persist=True)
    except Exception:
        pass
    session_kind = str(state.get("session_kind") or "").strip().lower()
    logger_ready = bool(state.get("logger_ready"))
    if logger_ready and bool(state.get("active")) and session_kind == str(getattr(self, "_pending_logger_session_kind", "") or ""):
        self._clear_pending_logger_start()
        self._update_refresh_timer(force=True)
        return

    if bool(state.get("logger_failed")) or str(state.get("status") or "").strip().lower() in {"failed", "logger_runtime_error", "logger_unavailable", "logger_start_lost"}:
        self._fail_pending_logger_start(reason="logger_reported_failure")
        return

    if facade.time.monotonic() >= float(getattr(self, "_logger_start_deadline", 0.0) or 0.0):
        self._fail_pending_logger_start()
