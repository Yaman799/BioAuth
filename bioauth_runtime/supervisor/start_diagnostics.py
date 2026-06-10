"""Start Protection diagnostics and safe failure-state publishing."""
from __future__ import annotations

import logging
import traceback
from typing import Any, Callable, Dict

LOGGER = logging.getLogger(__name__)
SAFE_START_FAILED_MESSAGE = "Protection could not start. Check diagnostics for the exact reason."


def log_checkpoint(bridge: Any, checkpoint: str, **payload: Any) -> None:
    """Publish one safe Start Protection checkpoint to debug trace and logs."""
    safe_payload = {str(k): _safe_log_value(v) for k, v in payload.items()}
    safe_payload["checkpoint"] = checkpoint
    debug = getattr(bridge, "_debug_trace", None)
    if callable(debug):
        try:
            debug("supervisor", checkpoint, payload=safe_payload)
        except Exception:
            LOGGER.debug("debug trace failed for start checkpoint", exc_info=True)
    LOGGER.info("[supervisor] %s %s", checkpoint, safe_payload)


def log_exception(bridge: Any, exc: Exception) -> None:
    """Log an exception with a safe traceback for diagnostics."""
    log_checkpoint(
        bridge,
        "start_failed_exception",
        error_type=type(exc).__name__,
        error_message=safe_reason(exc),
        traceback=traceback.format_exc(limit=20),
    )
    LOGGER.exception("Start Protection failed with exception")


def set_status(bridge: Any, message: str, tone: str) -> None:
    """Set a user-visible bridge status without allowing UI errors to crash start."""
    setter = getattr(bridge, "_set_status", None)
    if callable(setter):
        try:
            setter(str(message), str(tone))
        except Exception:
            LOGGER.debug("Failed setting UI status", exc_info=True)


def write_start_blocked_state(
    bridge: Any,
    legacy_provider: Callable[[], Any],
    code: str,
    reason: str,
) -> None:
    """Write a non-destructive diagnostic state for duplicate/already-active starts."""
    state = _safe_base_state(bridge, legacy_provider)
    state.update(
        {
            "runtime_diag_code": code,
            "runtime_diag_reason": safe_short(reason),
            "runtime_status": state.get("runtime_status") or "start_blocked",
            "runtime_decision": state.get("runtime_decision") or "blocked",
        }
    )
    _write_state(bridge, legacy_provider, state, "start blocked")


def write_start_failed_state(
    bridge: Any,
    legacy_provider: Callable[[], Any],
    code: str,
    reason: str,
    *,
    checkpoint: str,
) -> None:
    """Write a safe failed-to-start state for pre-session failures."""
    state = _safe_base_state(bridge, legacy_provider)
    state.update(
        {
            "schema_version": 2,
            "active": False,
            "session_kind": "protected",
            "status": "failed_to_start",
            "flow": "protected_start_failed",
            "runtime_status": "start_failed",
            "runtime_decision": "failed",
            "runtime_diag_code": code,
            "runtime_diag_reason": safe_short(reason),
            "runtime_diag_checkpoint": checkpoint,
            "pending_monitor_start": False,
            "logger_ready": False,
            "monitor_ready": False,
            "awaiting_evidence": False,
        }
    )
    _write_state(bridge, legacy_provider, state, "start failure")


def write_logger_spawn_failed_state(
    bridge: Any,
    legacy_provider: Callable[[], Any],
    worker_processes: Any,
    code: str,
) -> None:
    """Write failed-to-start state after logger spawn fails and clean partial workers."""
    state = _safe_base_state(bridge, legacy_provider)
    state.update(getattr(bridge, "_runtime_state", {}) or {})
    state.update(
        {
            "active": False,
            "status": "failed_to_start",
            "flow": "protected_start_failed",
            "runtime_status": "start_failed",
            "runtime_decision": "failed",
            "runtime_diag_code": code,
            "runtime_diag_reason": "Logger process could not be started.",
            "pending_monitor_start": False,
            "logger_ready": False,
            "monitor_ready": False,
            "logger_failed": True,
            "awaiting_evidence": False,
        }
    )
    try:
        worker_processes.stop_pair(bridge, reason="logger_spawn_failed", wait_timeout=0.25)
    except Exception:
        LOGGER.debug("Failed cleaning partial workers after logger spawn failure", exc_info=True)
    _write_state(bridge, legacy_provider, state, "logger spawn failure")
    log_checkpoint(bridge, "logger_spawn_failed", runtime_diag_code=code)


def safe_user_id(user: Any) -> str:
    """Return a non-sensitive user identifier already used by runtime state."""
    if isinstance(user, dict):
        return str(user.get("user_id") or user.get("username") or "")
    return ""


def safe_reason(value: Any) -> str:
    """Return a short, single-line diagnostic reason."""
    return safe_short(str(value or type(value).__name__))


def safe_short(value: str, limit: int = 180) -> str:
    """Clamp diagnostic text so UI/session state stays safe and compact."""
    text = " ".join(str(value or "").split())
    return text[:limit]


def _safe_base_state(bridge: Any, legacy_provider: Callable[[], Any]) -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    try:
        current = legacy_provider()._facade().read_session_state(default={})
        if isinstance(current, dict):
            state.update(current)
    except Exception:
        pass
    runtime_state = getattr(bridge, "_runtime_state", None)
    if isinstance(runtime_state, dict):
        for key, value in runtime_state.items():
            state.setdefault(key, value)
    user_id = safe_user_id(getattr(bridge, "_current_user", None))
    if user_id:
        state.setdefault("user", user_id)
        state.setdefault("user_id", user_id)
    if getattr(bridge, "_pending_logger_session_id", ""):
        state.setdefault("session_id", bridge._pending_logger_session_id)
    if getattr(bridge, "_pending_logger_run_id", ""):
        state.setdefault("run_id", bridge._pending_logger_run_id)
    if getattr(bridge, "_active_live_session_dir", ""):
        state.setdefault("live_session_dir", bridge._active_live_session_dir)
    return state


def _write_state(bridge: Any, legacy_provider: Callable[[], Any], state: Dict[str, Any], label: str) -> None:
    try:
        legacy_provider()._facade().write_session_state(state)
    except Exception:
        LOGGER.exception("Failed writing %s session state", label)
    bridge._runtime_state = dict(state)


def _safe_log_value(value: Any) -> Any:
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_log_value(item) for item in value[:8]]
    if isinstance(value, dict):
        return {str(k): _safe_log_value(v) for k, v in list(value.items())[:12]}
    return safe_short(str(value), limit=300)
