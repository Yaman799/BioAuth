"""Fresh-heartbeat guard for ambiguous worker-process exits."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

LOGGER = logging.getLogger(__name__)
FRESH_HEARTBEAT_MAX_AGE_SEC = 15.0


def _legacy():
    from bridge import session_runtime_helpers
    return session_runtime_helpers


def block_false_pair_stop_when_heartbeats_fresh(
    bridge: Any,
    *,
    failed_worker: str,
    completed_key: str,
    diagnostics: Optional[Dict[str, Any]],
) -> bool:
    """Return True when fresh current-session heartbeats should block failure.

    Windows venv launchers can hand off to the base interpreter and leave the
    tracked Popen handle completed while the real worker keeps publishing
    current-session heartbeats.  Fresh matching logger and monitor heartbeats
    are therefore authoritative over process-handle ambiguity.
    """
    facade = _legacy()._facade()
    try:
        state = facade.read_session_state(default={})
    except Exception:
        state = {}
    if not _state_allows_guard(state):
        return False

    logger_hb = _matching_heartbeat(bridge, "logger", state)
    monitor_hb = _matching_heartbeat(bridge, "monitor", state)
    logger_age = _heartbeat_age(logger_hb)
    monitor_age = _heartbeat_age(monitor_hb)
    if not (_is_fresh(logger_hb, logger_age) and _is_fresh(monitor_hb, monitor_age)):
        return False

    _record_blocked_pair_stop(
        bridge,
        state,
        failed_worker=failed_worker,
        completed_key=completed_key,
        diagnostics=diagnostics,
        logger_age=logger_age,
        monitor_age=monitor_age,
    )
    return True


def _state_allows_guard(state: Any) -> bool:
    if not isinstance(state, dict):
        return False
    if str(state.get("session_kind") or "").lower() != "protected":
        return False
    return bool(state.get("active")) and not bool(state.get("technical_failure"))


def _matching_heartbeat(bridge: Any, kind: str, state: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return dict(_legacy()._read_matching_worker_heartbeat(bridge, kind, state) or {})
    except Exception:
        try:
            return dict(_legacy()._facade().read_worker_heartbeat(kind, default={}) or {})
        except Exception:
            return {}


def _is_fresh(payload: Dict[str, Any], age: float) -> bool:
    return bool(payload) and age <= FRESH_HEARTBEAT_MAX_AGE_SEC


def _heartbeat_age(payload: Dict[str, Any]) -> float:
    if not isinstance(payload, dict) or not payload:
        return 999999.0
    try:
        stamp = float(
            payload.get("heartbeat_at")
            or payload.get("logger_heartbeat_at")
            or payload.get("monitor_heartbeat_at")
            or 0.0
        )
        if stamp <= 0.0:
            return 999999.0
        return max(0.0, time.time() - stamp)
    except Exception:
        return 999999.0


def _record_blocked_pair_stop(
    bridge: Any,
    state: Dict[str, Any],
    *,
    failed_worker: str,
    completed_key: str,
    diagnostics: Optional[Dict[str, Any]],
    logger_age: float,
    monitor_age: float,
) -> None:
    diag = _blocked_pair_stop_diag(
        bridge,
        failed_worker=failed_worker,
        completed_key=completed_key,
        diagnostics=diagnostics,
        logger_age=logger_age,
        monitor_age=monitor_age,
    )
    updated = dict(state)
    updated.update(diag)
    updated["active"] = True
    updated["flow"] = updated.get("flow") or "protected_active"
    updated["technical_failure"] = False
    try:
        _legacy()._facade().write_session_state(updated)
    except Exception:
        LOGGER.debug("Failed writing blocked pair-stop diagnostics", exc_info=True)
    bridge._runtime_state = dict(updated)
    bridge._worker_pair_status_cache = {**dict(getattr(bridge, "_worker_pair_status_cache", {}) or {}), **diag}
    debug = getattr(bridge, "_debug_trace", None)
    if callable(debug):
        debug("worker_pair", "Blocked false worker-pair stop because heartbeats are fresh", payload=diag, level="warn")


def _blocked_pair_stop_diag(
    bridge: Any,
    *,
    failed_worker: str,
    completed_key: str,
    diagnostics: Optional[Dict[str, Any]],
    logger_age: float,
    monitor_age: float,
) -> Dict[str, Any]:
    diag = {
        "worker_pair_stop_blocked_by_fresh_heartbeats": True,
        "worker_health_reason": "fresh_current_session_heartbeats_override_completed_process_handle",
        "pair_stop_source": "bioauth_runtime.supervisor.stop_controller",
        "failed_worker_candidate": str(failed_worker or ""),
        "completed_process_key": str(completed_key or ""),
        "logger_heartbeat_age": round(float(logger_age), 3),
        "monitor_heartbeat_age": round(float(monitor_age), 3),
        "logger_pid_status": _pid_status(bridge, getattr(bridge, "_logger_process_key", lambda: "")()),
        "monitor_pid_status": _pid_status(bridge, "monitor"),
    }
    if isinstance(diagnostics, dict):
        diag["completed_process_exit_code"] = diagnostics.get("exit_code")
        diag["completed_process_reason"] = str(diagnostics.get("reason") or "")
    return diag


def _pid_status(bridge: Any, key: str) -> str:
    try:
        proc = (getattr(bridge, "_running_processes", {}) or {}).get(str(key or ""))
        if proc is None:
            return "missing_handle"
        return "alive" if proc.poll() is None else "completed_handle"
    except Exception:
        return "unknown"
