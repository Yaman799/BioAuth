"""Post-unlock auto-resume controller for commercial protected sessions."""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, Optional

from . import protection_session_controller, worker_processes

LOGGER = logging.getLogger(__name__)


def _legacy():
    from bridge import session_runtime_helpers
    return session_runtime_helpers


def maybe_resume_after_unlock(bridge: Any, state: Optional[Dict[str, Any]] = None) -> bool:
    """Resume once after Windows unlock, after old workers are stopped."""
    facade = _legacy()._facade()
    data = state if isinstance(state, dict) else getattr(bridge, "_runtime_state", {})
    data = _fresh_resume_state(facade, data)
    if not getattr(bridge, "_current_user", None) or not isinstance(data, dict):
        return False
    try:
        import os
        from bioauth_runtime.desktop_instance import owns_desktop_instance
        if os.environ.get("BIOAUTH_DESKTOP_INSTANCE_ID") and not owns_desktop_instance(getattr(facade, "BASE_DIR", "")):
            return False
    except Exception:
        LOGGER.debug("Auto-resume desktop ownership check failed safely", exc_info=True)
        return False
    if _resume_claim_active(data):
        return False
    if not bool(data.get("auto_resume_pending") or data.get("resume_after_unlock")):
        return False
    if bool(data.get("active")):
        return False
    if str(data.get("session_kind") or "").lower() != "protected":
        return False
    if not _has_lock_handoff_marker(data):
        return False
    if _auto_resume_attempt_count(data) >= 1:
        _write_resume_blocked_state(
            bridge,
            data,
            code="auto_resume_loop_guard",
            reason="Auto-resume stopped to prevent repeated lock loop after high-risk handoff.",
        )
        return False
    if _is_technical_terminal_state(data):
        return False
    if facade.is_current_session_locked():
        return False
    now = facade.time.time()
    if now - float(getattr(bridge, "_last_auto_resume_attempt_at", 0.0) or 0.0) < 1.5:
        return False
    if bool(getattr(bridge, "_auto_resume_inflight", False)):
        return False

    if _old_workers_alive(bridge):
        return False

    # Hotfix 7W: do the expensive preflight + process spawn outside the Qt
    # refresh path. Repeated lock/unlock cycles were making the MainThread do
    # stop_pair, Start Protection, process spawn, and dashboard refresh in one
    # cycle, causing visible freezes after multiple locks.
    bridge._last_auto_resume_attempt_at = now
    bridge._auto_resume_inflight = True
    _mark_auto_resume_attempt(bridge, data, now=now)
    threading.Thread(
        target=_run_auto_resume_worker,
        args=(bridge,),
        name="bioauth-auto-resume",
        daemon=True,
    ).start()
    return True




def _run_auto_resume_worker(bridge: Any) -> None:
    """Run post-unlock resume without blocking dashboard refresh."""
    source_state = getattr(bridge, "_auto_resume_source_state", {})
    source_state = source_state if isinstance(source_state, dict) else {}
    try:
        worker_processes.stop_pair(bridge, reason="auto_resume_preflight", wait_timeout=1.25)
        if _old_workers_alive(bridge):
            return
        started = protection_session_controller.start_protection(bridge, auto_resume=True, trigger_refresh=False)
        if not started:
            _write_resume_blocked_state(
                bridge,
                source_state,
                code="auto_resume_start_failed",
                reason="Auto-resume was claimed but Start Protection did not complete.",
            )
    except Exception:
        LOGGER.debug("Auto-resume worker failed safely", exc_info=True)
        _write_resume_blocked_state(
            bridge,
            source_state,
            code="auto_resume_worker_failed",
            reason="Auto-resume worker failed after claiming the lock handoff.",
        )
    finally:
        bridge._auto_resume_inflight = False


def _fresh_resume_state(facade: Any, data: Any) -> Dict[str, Any]:
    """Prefer the latest persisted resume state over stale dashboard snapshots."""
    current = data if isinstance(data, dict) else {}
    try:
        latest = facade.read_session_state(default={})
    except Exception:
        latest = {}
    if not isinstance(latest, dict) or not latest:
        return dict(current)
    latest_handoff = _handoff_id(latest)
    current_handoff = _handoff_id(current)
    same_handoff = bool(latest_handoff and current_handoff and latest_handoff == current_handoff)
    same_session = bool(latest.get("session_id") and latest.get("session_id") == current.get("session_id"))
    latest_resume_related = bool(
        latest.get("auto_resume_pending")
        or latest.get("resume_after_unlock")
        or latest.get("auto_resume_in_progress")
        or latest.get("resume_in_progress")
        or latest.get("auto_resume_claim_id")
        or latest.get("lock_loop_guard_auto_resume_attempt_count")
        or latest.get("auto_resume_attempt_count")
    )
    if latest_resume_related and (same_handoff or same_session or not current):
        return dict(latest)
    merged = dict(current)
    if same_handoff or same_session:
        for key in (
            "auto_resume_attempt_count",
            "lock_loop_guard_auto_resume_attempt_count",
            "auto_resume_in_progress",
            "resume_in_progress",
            "auto_resume_claim_id",
            "auto_resume_claimed_at",
        ):
            if key in latest:
                merged[key] = latest.get(key)
    return merged


def _resume_claim_active(data: Dict[str, Any]) -> bool:
    """Return true while an async auto-resume claim is still active."""
    if bool(data.get("auto_resume_in_progress") or data.get("resume_in_progress")):
        return True
    claim_id = str(data.get("auto_resume_claim_id") or "").strip()
    if not claim_id:
        return False
    try:
        claimed_at = float(data.get("auto_resume_claimed_at") or 0.0)
    except (TypeError, ValueError):
        claimed_at = 0.0
    try:
        now = float(_legacy()._facade().time.time())
    except Exception:
        import time as _time
        now = _time.time()
    return claimed_at > 0.0 and now - claimed_at < 120.0


def _handoff_id(data: Dict[str, Any]) -> str:
    return str(
        data.get("lock_handoff_id")
        or data.get("lock_controller_handoff_id")
        or f"{data.get('session_id') or ''}:{data.get('final_action') or ''}:{data.get('lock_reason') or ''}"
    ).strip()


def _auto_resume_attempt_count(data: Dict[str, Any]) -> int:
    try:
        return max(
            int(data.get("auto_resume_attempt_count") or 0),
            int(data.get("lock_loop_guard_auto_resume_attempt_count") or 0),
        )
    except (TypeError, ValueError):
        return 0


def _mark_auto_resume_attempt(bridge: Any, data: Dict[str, Any], *, now: float) -> None:
    """Persist one-shot resume metadata before the background resume starts."""
    facade = _legacy()._facade()
    attempt_count = _auto_resume_attempt_count(data) + 1
    handoff_id = _handoff_id(data)
    updated = dict(data)
    claim_id = uuid.uuid4().hex
    updated.update({
        "auto_resume_attempt_count": attempt_count,
        "lock_loop_guard_auto_resume_attempt_count": attempt_count,
        "lock_loop_guard_handoff_id": handoff_id,
        "last_lock_handoff_id": handoff_id,
        "last_lock_handoff_session_id": str(data.get("session_id") or ""),
        "last_lock_handoff_ts": data.get("lock_controller_last_attempt_at") or data.get("expected_worker_exit_recorded_at") or now,
        "auto_resume_last_attempt_at": now,
        "auto_resume_claimed_at": now,
        "auto_resume_claim_id": claim_id,
        "auto_resume_in_progress": True,
        "resume_in_progress": True,
        "auto_resume_pending": False,
        "resume_after_unlock": False,
        "flow": "resume_in_progress",
        "status": "resume_in_progress",
        "runtime_status": "resume_in_progress",
        "runtime_decision": "pending",
        "runtime_diag_code": "auto_resume_claimed",
        "runtime_diag_reason": "Auto-resume claimed atomically; duplicate dashboard refreshes will not start another resume.",
    })
    try:
        facade.write_session_state(updated)
        bridge._runtime_state = dict(updated)
        bridge._auto_resume_source_state = dict(updated)
    except Exception:
        LOGGER.debug("Failed marking auto-resume attempt", exc_info=True)
        bridge._auto_resume_source_state = dict(data)


def _write_resume_blocked_state(bridge: Any, data: Dict[str, Any], *, code: str, reason: str) -> None:
    facade = _legacy()._facade()
    blocked = dict(data)
    blocked.update({
        "active": False,
        "flow": "resume_blocked",
        "status": "resume_blocked",
        "runtime_status": "resume_blocked",
        "runtime_decision": "pending",
        "decision": "pending",
        "auto_resume_pending": False,
        "resume_after_unlock": False,
        "auto_resume_in_progress": False,
        "resume_in_progress": False,
        "return_verification": False,
        "runtime_diag_code": code,
        "runtime_diag_reason": reason,
        "runtime_diagnostic_code": code,
        "runtime_diagnostic_reason": reason,
        "lock_loop_guard_blocked": True,
    })
    try:
        facade.write_session_state(blocked)
        bridge._runtime_state = dict(blocked)
    except Exception:
        LOGGER.debug("Failed writing resume blocked state", exc_info=True)


def _has_lock_handoff_marker(data: Dict[str, Any]) -> bool:
    """Only lock_controller-created terminal states may auto-resume."""
    final_action = str(data.get("final_action") or "").strip().lower()
    status = str(data.get("status") or data.get("runtime_status") or "").strip().lower()
    explicit = bool(data.get("lock_controller_handoff") or data.get("lock_handoff_id"))
    legacy_lock = (
        status == "resume_pending"
        and bool(data.get("forced_stop"))
        and bool(data.get("protected_action_requested") or data.get("app_locked") or data.get("lockRequested"))
        and final_action in {"windows_locked", "windows_lock_requested"}
    )
    return bool(explicit or legacy_lock)


def _is_technical_terminal_state(data: Dict[str, Any]) -> bool:
    blocked = {
        "logger_exited_after_ready",
        "monitor_exited_after_ready",
        "worker_pair_dead",
        "technical_failure",
        "interrupted",
    }
    values = {
        str(data.get("status") or "").strip().lower(),
        str(data.get("runtime_status") or "").strip().lower(),
        str(data.get("runtime_diag_code") or data.get("runtime_diagnostic_code") or "").strip().lower(),
    }
    return bool(values & blocked or data.get("technical_failure") or data.get("logger_failed") or data.get("monitor_failed"))

def _old_workers_alive(bridge: Any) -> bool:
    logger_key = bridge._logger_process_key() if getattr(bridge, "_current_user", None) else ""
    return worker_processes.process_alive(bridge, "monitor") or (bool(logger_key) and worker_processes.process_alive(bridge, logger_key))
