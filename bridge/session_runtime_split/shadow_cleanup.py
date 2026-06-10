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

def _clear_stale_shadow_state_if_safe(self, state: Optional[Dict[str, Any]] = None) -> bool:
    """Clear hidden shadow-only state only when no exact shadow process is alive.

    This is intentionally scoped to shadow_evidence state. It must not clear
    normal enrollment/protected-session state and it must not touch production
    monitor stop controls.
    """
    if _is_shadow_runtime_process_running(self):
        return False
    state = state if isinstance(state, dict) else None
    if state is None:
        try:
            state = self._active_state_for_current_user()
        except Exception:
            state = {}
    changed = False
    if _state_is_shadow_evidence(state) or str((state or {}).get("retry_handoff_state") or "").strip().lower().startswith("shadow_evidence_"):
        try:
            _facade().clear_session_state()
            changed = True
        except Exception:
            LOGGER.debug("Failed clearing stale hidden shadow session state", exc_info=True)
    if bool(getattr(self, "_pending_shadow_evidence_monitor_start", False)):
        clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
        if callable(clear_shadow):
            try:
                clear_shadow()
            except Exception:
                LOGGER.debug("Failed clearing stale hidden shadow pending context", exc_info=True)
        else:
            setattr(self, "_pending_shadow_evidence_monitor_start", False)
        changed = True
    if _shadow_logger_start_pending(self):
        clear_logger = getattr(self, "_clear_pending_logger_start", None)
        if callable(clear_logger):
            try:
                clear_logger()
            except Exception:
                LOGGER.debug("Failed clearing stale hidden shadow logger pending context", exc_info=True)
        else:
            setattr(self, "_pending_logger_start", False)
            setattr(self, "_pending_logger_session_kind", "")
        changed = True
    if changed:
        try:
            _clear_shadow_stop_controls(self)
        except Exception:
            LOGGER.debug("Failed clearing stale hidden shadow stop controls", exc_info=True)
        try:
            _facade().invalidate_session_discovery_cache()
        except Exception:
            LOGGER.debug("Failed invalidating session discovery cache after stale shadow cleanup", exc_info=True)
    return changed

def _normal_user_session_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
    """Resolve only user-facing enrollment/protected-session flow.

    Hidden shadow_evidence state is ignored for normal UI enablement. Stale
    shadow state is cleared when no exact shadow process is alive.
    """
    facade = _facade()
    state = state if isinstance(state, dict) else None
    if state is None:
        try:
            state = self._active_state_for_current_user()
        except Exception:
            state = {}
    state = state if isinstance(state, dict) else {}
    if _is_terminal_protected_state(state):
        return "idle"
    if _state_is_shadow_evidence(state):
        _clear_stale_shadow_state_if_safe(self, state)
        return "idle"
    if _normal_logger_start_pending(self):
        pending_logger_kind = _pending_logger_kind(self)
        if pending_logger_kind == "protected":
            return "protected_starting"
        return "enrollment_starting"
    if bool(getattr(self, "_pending_monitor_start", False)):
        return "protected_starting"
    decision = str(state.get("decision") or "").strip().lower()
    final_decision = str(state.get("final_decision") or state.get("archive_label") or "").strip().lower()
    forced_stop = bool(
        state.get("forced_stop")
        or state.get("app_locked")
        or state.get("monitor_holding")
        or state.get("restriction_active")
        or decision == "intruder"
        or final_decision == "intruder"
    )
    status = str(state.get("status") or "").strip().lower()
    resume_pending = bool(state.get("auto_resume_pending") or state.get("resume_after_unlock"))
    if resume_pending and not state.get("active"):
        return "protected_resume_pending"
    if forced_stop:
        return "protected_forced_stop"
    if not state.get("active"):
        return "idle"
    session_kind = str(state.get("session_kind") or state.get("runtime_mode") or state.get("mode") or "").strip().lower()
    if session_kind == "enrollment":
        return "enrollment_active"
    if session_kind == "protected":
        if facade.runtime_status_is_technical_failure(status) or bool(state.get("technical_failure")):
            return "protected_technical_failure"
        if status == "insufficient_windows":
            return "protected_collecting"
        if bool(getattr(self, "_monitor_start_failed", False)) or not bool(state.get("monitor_ready")):
            return "protected_starting"
        if decision == "suspicious":
            return "protected_warning"
        return "protected_active"
    return "idle"

def _normal_enrollment_logger_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
    return _user_runtime().normal_enrollment_logger_flow(self, state=state)

def _normal_enrollment_logger_stop_available(self, state: Optional[Dict[str, Any]] = None) -> bool:
    return _user_runtime().normal_enrollment_logger_stop_available(self, state=state)

def _production_monitor_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
    return _user_runtime().production_monitor_flow(self, state=state)

def _protected_session_stop_available(self, state: Optional[Dict[str, Any]] = None) -> bool:
    return _user_runtime().protected_session_stop_available(self, state=state)

def _shadow_session_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
    state = state if isinstance(state, dict) else None
    if state is None:
        try:
            state = self._active_state_for_current_user()
        except Exception:
            state = {}
    if _state_is_shadow_evidence(state) or bool(getattr(self, "_pending_shadow_evidence_monitor_start", False)):
        try:
            return session_flow(self, state)
        except Exception:
            return "shadow_evidence_active" if _is_shadow_runtime_process_running(self) else "idle"
    return "shadow_evidence_active" if _is_shadow_runtime_process_running(self) else "idle"

def _request_hidden_shadow_cleanup_for_normal_action(self, *, reason: str = "normal_capture_requested", state: Optional[Dict[str, Any]] = None) -> bool:
    """Request hidden shadow cleanup and report whether a live shadow process remains.

    The request uses only shadow-specific stop controls and never targets the
    production ``monitor`` key or normal ``logger_user_<user>`` key.
    """
    state = state if isinstance(state, dict) else None
    if state is None:
        try:
            state = self._active_state_for_current_user()
        except Exception:
            state = {}
    has_shadow_context = _state_is_shadow_evidence(state) or bool(getattr(self, "_pending_shadow_evidence_monitor_start", False)) or _shadow_logger_start_pending(self) or _is_shadow_runtime_process_running(self)
    if not has_shadow_context:
        return False
    if _has_stale_shadow_state(self, state):
        _clear_stale_shadow_state_if_safe(self, state)
        return False
    try:
        _request_shadow_stop_controls(self)
    except Exception:
        LOGGER.debug("Hidden shadow cleanup request failed before normal user action", exc_info=True)
    clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
    if callable(clear_shadow):
        try:
            clear_shadow()
        except Exception:
            LOGGER.debug("Failed clearing hidden shadow pending context during normal action", exc_info=True)
    return _is_shadow_runtime_process_running(self)

def _safe_worker_line(value: Any) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if not text:
        return ""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("<redacted>", text)
    if len(text) > _WORKER_LINE_LIMIT:
        text = text[:_WORKER_LINE_LIMIT] + "..."
    return text

def _worker_diag_map(self) -> Dict[str, Dict[str, Any]]:
    diagnostics = getattr(self, "_worker_diagnostics", None)
    if not isinstance(diagnostics, dict):
        diagnostics = {}
        setattr(self, "_worker_diagnostics", diagnostics)
    return diagnostics

def _ensure_worker_diag(self, key: str) -> Dict[str, Any]:
    diagnostics = _worker_diag_map(self)
    diag = diagnostics.get(str(key))
    if not isinstance(diag, dict):
        diag = {"stdout_tail": deque(maxlen=_WORKER_TAIL_LIMIT), "stderr_tail": deque(maxlen=_WORKER_TAIL_LIMIT)}
        diagnostics[str(key)] = diag
    if not isinstance(diag.get("stdout_tail"), deque):
        diag["stdout_tail"] = deque(list(diag.get("stdout_tail") or [])[-_WORKER_TAIL_LIMIT:], maxlen=_WORKER_TAIL_LIMIT)
    if not isinstance(diag.get("stderr_tail"), deque):
        diag["stderr_tail"] = deque(list(diag.get("stderr_tail") or [])[-_WORKER_TAIL_LIMIT:], maxlen=_WORKER_TAIL_LIMIT)
    return diag

def _append_worker_output(self, key: str, stream_name: str, line: Any) -> None:
    safe = _safe_worker_line(line)
    if not safe:
        return
    diag = _ensure_worker_diag(self, key)
    tail_name = "stderr_tail" if stream_name == "stderr" else "stdout_tail"
    diag[tail_name].append(safe)
    diag[f"last_{stream_name}_at"] = time.time()

def _start_worker_output_reader(self, key: str, stream: Any, stream_name: str) -> None:
    if stream is None:
        return

    def _reader() -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                _append_worker_output(self, key, stream_name, line)
        except Exception as exc:
            LOGGER.debug("Worker %s %s capture stopped: %s", key, stream_name, exc)
        finally:
            try:
                stream.close()
            except (OSError, ValueError):
                LOGGER.debug("Worker %s %s stream close failed", key, stream_name, exc_info=True)

    thread = threading.Thread(target=_reader, name=f"bioauth-{key}-{stream_name}-tail", daemon=True)
    thread.start()
