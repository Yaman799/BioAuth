"""Stop Protection and worker-failure handoff for the commercial supervisor."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from . import worker_processes
from .fresh_heartbeat_guard import block_false_pair_stop_when_heartbeats_fresh
from bridge.qt_thread_dispatch import dispatch_to_qt_thread

LOGGER = logging.getLogger(__name__)


def _legacy():
    from bridge import session_runtime_helpers
    return session_runtime_helpers



def _canonical_supervisor_stop_reason(reason: str) -> str:
    value = str(reason or "").strip().lower()
    mapping = {
        "user_requested": "user_stop",
        "stop_requested": "user_stop",
        "protected_stop_requested": "user_stop",
        "session_stop_requested": "user_stop",
        "app_close": "app_shutdown",
        "shutdown": "app_shutdown",
    }
    return mapping.get(value, value or "supervisor_stop")


def _explicit_stop_in_progress(bridge: Any) -> bool:
    """Return True while a user/app stop is intentionally draining workers."""
    reason = _canonical_supervisor_stop_reason(getattr(bridge, "_supervisor_stop_in_progress_reason", ""))
    if bool(getattr(bridge, "_supervisor_stop_in_progress", False)) and reason in {"user_stop", "app_shutdown", "test_stop"}:
        return True
    try:
        state = _legacy()._facade().read_session_state(default={})
    except Exception:
        state = {}
    if not isinstance(state, dict):
        return False
    state_reason = _canonical_supervisor_stop_reason(state.get("stop_reason") or state.get("stop_in_progress_reason") or "")
    if bool(state.get("stop_in_progress")) and state_reason in {"user_stop", "app_shutdown", "test_stop"}:
        return True
    if str(state.get("flow") or "").lower() in {"idle", "protected_stopped"} and state_reason in {"user_stop", "app_shutdown", "test_stop"}:
        return True
    return False

def stop_protection(bridge: Any, *, reason: str = "user_requested", silent: bool = False, wait_timeout: float = 1.25) -> Dict[str, Any]:
    """Stop logger and monitor through one supervisor path."""
    canonical_reason = _canonical_supervisor_stop_reason(reason)
    try:
        legacy = _legacy()
        setattr(bridge, "_supervisor_stop_in_progress", True)
        setattr(bridge, "_supervisor_stop_in_progress_reason", canonical_reason)
        try:
            state = legacy._facade().read_session_state(default={})
            if isinstance(state, dict):
                marked = dict(state)
                marked.update({
                    "stop_in_progress": True,
                    "stop_in_progress_reason": canonical_reason,
                    "stop_reason": canonical_reason,
                    "stop_requested_at": time.time(),
                })
                legacy._facade().write_session_state(marked)
                bridge._runtime_state = dict(marked)
        except Exception:
            LOGGER.debug("Failed marking explicit stop in progress", exc_info=True)
        try:
            legacy.stop_live_candidate_observer(bridge, reason="protected_stop_requested", timeout=0.75)
        except Exception:
            LOGGER.debug("Live candidate observer stop failed safely", exc_info=True)
        result = worker_processes.stop_pair(bridge, reason=reason, wait_timeout=wait_timeout)
        terminal = _terminal_state(bridge, reason=canonical_reason)
        terminal.update({"stop_in_progress": False, "stop_in_progress_reason": ""})
        legacy._facade().write_session_state(terminal)
        bridge._runtime_state = dict(terminal)
        _clear_bridge_runtime_flags(bridge)
        if not silent:
            bridge._set_status(bridge._t("stop_requested"), "info")
        _request_refresh(bridge, "supervisor:stop_protection")
        result.update({"ok": True, "state": terminal})
        return result
    except Exception as exc:
        LOGGER.exception("Supervisor stop_protection failed")
        return {"ok": False, "reason": str(reason or "user_requested"), "error": str(exc)}
    finally:
        try:
            setattr(bridge, "_supervisor_stop_in_progress", False)
            setattr(bridge, "_supervisor_stop_in_progress_reason", "")
        except Exception:
            pass


def shutdown_workers(bridge: Any, *, reason: str = "app_shutdown", wait_timeout: float = 0.75) -> Dict[str, Any]:
    """App-shutdown cleanup using the same worker pair stop path."""
    return stop_protection(bridge, reason=reason, silent=True, wait_timeout=wait_timeout)


def handle_logger_exit_after_ready(bridge: Any, key: str, diagnostics: Optional[Dict[str, Any]] = None) -> None:
    """Route logger death to supervisor stop/failure handling."""
    if _explicit_stop_in_progress(bridge):
        return
    if _expected_exit_after_lock_handoff(bridge, "logger", diagnostics):
        return
    if not _protected_active_state(bridge):
        return
    if block_false_pair_stop_when_heartbeats_fresh(
        bridge,
        failed_worker="logger",
        completed_key=str(key or ""),
        diagnostics=diagnostics,
    ):
        return
    detail = _failure_detail(bridge, key, diagnostics, "logger_exited_after_ready")
    result = worker_processes.stop_pair(bridge, reason="logger_exited_after_ready", wait_timeout=0.85)
    _write_failure_state(bridge, "logger_exited_after_ready", detail, result, logger_failed=True, diagnostics=diagnostics)


def handle_monitor_exit_after_ready(bridge: Any, diagnostics: Optional[Dict[str, Any]] = None) -> None:
    """Route monitor death to supervisor stop/failure handling."""
    if _explicit_stop_in_progress(bridge):
        return
    if _expected_exit_after_lock_handoff(bridge, "monitor", diagnostics):
        return
    if not _protected_active_state(bridge, require_monitor_ready=True):
        return
    if block_false_pair_stop_when_heartbeats_fresh(
        bridge,
        failed_worker="monitor",
        completed_key="monitor",
        diagnostics=diagnostics,
    ):
        return
    detail = _failure_detail(bridge, "monitor", diagnostics, "monitor_exited_after_ready")
    result = worker_processes.stop_pair(bridge, reason="monitor_exited_after_ready", wait_timeout=0.85)
    _write_failure_state(bridge, "monitor_exited_after_ready", detail, result, monitor_failed=True, diagnostics=diagnostics)






def _read_lock_handoff_runtime_artifacts(state: Dict[str, Any]) -> Dict[str, Any]:
    """Read monitor-published lock handoff even before bridge persists it."""
    session_id = str((state or {}).get("session_id") or "").strip()
    candidates = []
    try:
        facade = _legacy()._facade()
        for kind in ("monitor", "logger"):
            try:
                hb = facade.read_worker_heartbeat(kind, default={})
            except Exception:
                hb = {}
            if isinstance(hb, dict):
                candidates.append(hb)
    except Exception:
        pass
    try:
        import json
        from pathlib import Path
        from control import CONTROL_DIR
        summary = json.loads((Path(CONTROL_DIR) / "runtime_summary.json").read_text(encoding="utf-8"))
        if isinstance(summary, dict):
            candidates.append(summary)
    except Exception:
        pass
    for payload in candidates:
        if not isinstance(payload, dict) or not payload:
            continue
        if session_id and str(payload.get("session_id") or "").strip() not in {"", session_id}:
            continue
        if _is_lock_handoff_state(payload):
            return dict(payload)
    return {}

def _expected_exit_after_lock_handoff(bridge: Any, worker_kind: str, diagnostics: Optional[Dict[str, Any]] = None) -> bool:
    """Keep lock/auto-resume handoff from becoming a technical worker failure."""
    facade = _legacy()._facade()
    try:
        state = facade.read_session_state(default={})
    except Exception:
        state = {}
    state = state if isinstance(state, dict) else {}
    diag = diagnostics if isinstance(diagnostics, dict) else {}
    final_hb = diag.get("final_heartbeat") if isinstance(diag.get("final_heartbeat"), dict) else {}
    candidate = dict(state)
    if final_hb:
        for key in (
            "forced_stop",
            "app_locked",
            "screen_locked",
            "auto_resume_pending",
            "resume_after_unlock",
            "forced_stop_expected_monitor_exit",
            "monitor_exit_expected",
            "lock_controller_handoff",
            "lock_handoff_id",
            "status",
            "runtime_status",
            "final_decision",
            "archive_label",
            "stop_reason",
        ):
            if key in final_hb and not candidate.get(key):
                candidate[key] = final_hb.get(key)
    artifact = _read_lock_handoff_runtime_artifacts(candidate)
    if artifact:
        for key, value in artifact.items():
            if key not in candidate or not candidate.get(key):
                candidate[key] = value
    if not _is_lock_handoff_state(candidate):
        return False
    updated = dict(state)
    for key, value in candidate.items():
        if key not in updated or not updated.get(key):
            updated[key] = value
    now = time.time()
    block_auto_resume = bool(candidate.get("lock_loop_guard_block_auto_resume") or candidate.get("lock_loop_guard_blocked"))
    block_code = str(candidate.get("runtime_diag_code") or "auto_resume_loop_guard")
    block_reason = str(
        candidate.get("runtime_diag_reason")
        or "Auto-resume stopped to prevent repeated lock loop after high-risk handoff."
    )
    updated.update({
        "active": False,
        "session_state": "stopped" if block_auto_resume else "resume_pending",
        "flow": "resume_blocked" if block_auto_resume else "protected_forced_stop",
        "status": block_code if block_auto_resume else "resume_pending",
        "runtime_status": "resume_blocked" if block_auto_resume else "resume_pending",
        "runtime_decision": "pending" if block_auto_resume else (updated.get("runtime_decision") or "intruder"),
        "decision": "pending" if block_auto_resume else (updated.get("decision") or "intruder"),
        "final_decision": updated.get("final_decision") or ("pending" if block_auto_resume else "intruder"),
        "archive_label": updated.get("archive_label") or ("interrupted" if block_auto_resume else "intruder"),
        "final_bucket": updated.get("final_bucket") or "rejected",
        "logger_ready": False if str(worker_kind or "") == "logger" else bool(updated.get("logger_ready", False)),
        "monitor_ready": False,
        "logger_failed": False,
        "monitor_failed": False,
        "technical_failure": False,
        "risk_engine_stopped": False,
        "process_pair_failed": False,
        "auto_resume_pending": False if block_auto_resume else True,
        "resume_after_unlock": False if block_auto_resume else True,
        "auto_resume_in_progress": False,
        "resume_in_progress": False,
        "return_verification": False if block_auto_resume else bool(updated.get("return_verification", False)),
        "forced_stop": True,
        "protected_action_requested": False if block_auto_resume else True,
        "forced_stop_expected_monitor_exit": True,
        "monitor_exit_expected": True,
        "expected_worker_exit_after_lock_handoff": True,
        "expected_worker_exit_kind": str(worker_kind or ""),
        "expected_worker_exit_recorded_at": now,
        "expected_worker_exit_code": diag.get("exit_code"),
        "runtime_diag_code": block_code if block_auto_resume else "awaiting_unlock_resume",
        "runtime_diag_reason": block_reason if block_auto_resume else "Expected worker exit after confirmed high-risk lock handoff; waiting for unlock auto-resume.",
        "runtime_diagnostic_code": block_code if block_auto_resume else "awaiting_unlock_resume",
        "runtime_diagnostic_reason": block_reason if block_auto_resume else "Expected worker exit after confirmed high-risk lock handoff; waiting for unlock auto-resume.",
        "lock_loop_guard_blocked": bool(block_auto_resume),
        "status_message": candidate.get("status_message") or updated.get("status_message") or ("High risk repeated after unlock. Protection was stopped to prevent repeated locking. Start protection again manually." if block_auto_resume else updated.get("status_message")),
    })
    try:
        facade.write_session_state(updated)
        bridge._runtime_state = dict(updated)
    except Exception:
        LOGGER.debug("Failed preserving expected lock-handoff worker exit state", exc_info=True)
        return False
    _request_refresh(bridge, f"supervisor:expected_{worker_kind}_exit_after_lock_handoff")
    return True


def _is_lock_handoff_state(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    status_values = {
        str(data.get("status") or "").strip().lower(),
        str(data.get("runtime_status") or "").strip().lower(),
        str(data.get("session_state") or "").strip().lower(),
    }
    explicit = bool(data.get("lock_controller_handoff") or data.get("lock_handoff_id"))
    resume_pending = bool(data.get("auto_resume_pending") or data.get("resume_after_unlock") or "resume_pending" in status_values)
    forced_lock = bool(data.get("forced_stop") or data.get("app_locked") or data.get("screen_locked") or data.get("protected_action_requested"))
    expected_exit = bool(data.get("forced_stop_expected_monitor_exit") or data.get("monitor_exit_expected"))
    terminal_intruder = str(data.get("final_decision") or data.get("archive_label") or data.get("decision") or "").strip().lower() == "intruder"
    stop_reason = str(data.get("stop_reason") or "").strip().lower()
    return bool(
        explicit
        or expected_exit
        or (resume_pending and forced_lock)
        or (terminal_intruder and stop_reason in {"monitor_intruder", "intruder_lock", "confirmed_high_risk"})
    )

def _terminal_state(bridge: Any, *, reason: str) -> Dict[str, Any]:
    facade = _legacy()._facade()
    try:
        state = facade.read_session_state(default={})
    except Exception:
        state = {}
    terminal = dict(state) if isinstance(state, dict) else {}
    now = time.time()
    terminal.update({
        "active": False,
        "session_state": "stopped",
        "flow": "idle",
        "status": "stopped",
        "runtime_status": "idle",
        "decision": "stopped",
        "stop_reason": str(reason or "user_requested"),
        "stopped_at": now,
        "stopped_at_text": facade.time.strftime("%Y-%m-%d %H:%M:%S", facade.time.localtime(now)),
        "logger_ready": False,
        "monitor_ready": False,
        "auto_resume_pending": False,
        "resume_after_unlock": False,
        "return_verification": False,
        "forced_stop": False,
        "feedback_prompt": {},
    })
    return terminal


def _protected_active_state(bridge: Any, *, require_monitor_ready: bool = False) -> bool:
    facade = _legacy()._facade()
    try:
        state = facade.read_session_state(default={})
    except Exception:
        state = {}
    if not isinstance(state, dict):
        return False
    if str(state.get("session_kind") or "").lower() != "protected":
        return False
    if bool(state.get("auto_resume_pending") or state.get("resume_after_unlock")):
        return False
    if require_monitor_ready and not bool(state.get("monitor_ready")):
        return False
    return bool(state.get("active")) and not bool(state.get("technical_failure"))


def _failure_detail(bridge: Any, key: str, diagnostics: Optional[Dict[str, Any]], fallback: str) -> str:
    try:
        detail, _diag = _legacy().worker_failure_detail(bridge, key, fallback=fallback)
        return str(detail or fallback)
    except Exception:
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        return str(diagnostics.get("detail") or fallback)


def _worker_exit_diagnostics(
    bridge: Any,
    key: str,
    diagnostics: Optional[Dict[str, Any]],
    *,
    logger_failed: bool,
    monitor_failed: bool,
) -> Dict[str, Any]:
    """Collect safe diagnostics for an unexpected ready-worker exit."""
    facade = _legacy()._facade()
    data = dict(diagnostics or {})
    try:
        snapshot = _legacy().worker_diagnostics_snapshot(bridge, key)
        if isinstance(snapshot, dict):
            data.update({k: v for k, v in snapshot.items() if k not in data or not data.get(k)})
    except Exception:
        LOGGER.debug("Failed reading worker diagnostics snapshot", exc_info=True)
    worker_kind = "logger" if logger_failed else "monitor" if monitor_failed else ""
    heartbeat = {}
    if worker_kind:
        try:
            heartbeat = facade.read_worker_heartbeat(worker_kind, default={})
        except Exception:
            heartbeat = {}
    stop_name = ""
    if logger_failed:
        try:
            stop_name = bridge._logger_key()
        except Exception:
            stop_name = key
    elif monitor_failed:
        stop_name = "monitor"
    control_status = {}
    stop_requested = False
    if stop_name:
        try:
            from control import stop_control_status
            state = facade.read_session_state(default={})
            state = state if isinstance(state, dict) else {}
            control_status = stop_control_status(
                stop_name,
                worker_key=stop_name,
                session_id=str(state.get("session_id") or ""),
                run_id=str(state.get("run_id") or ""),
                allowed_reasons=(
                    "user_stop",
                    "app_shutdown",
                    "supervisor_stop",
                    "monitor_failed_pair_stop",
                    "logger_failed_pair_stop",
                    "test_stop",
                ),
            )
            stop_requested = bool(control_status.get("should_stop"))
        except Exception:
            control_status = {}
            stop_requested = False
    stdout_tail = list(data.get("stdout_tail") or [])[-8:]
    stderr_tail = list(data.get("stderr_tail") or [])[-8:]
    return {
        "exit_code": data.get("exit_code"),
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "final_heartbeat": dict(heartbeat or {}),
        "final_heartbeat_status": str((heartbeat or {}).get("status") or ""),
        "stop_requested": bool(stop_requested),
        **dict(control_status or {}),
        "app_shutdown_requested": bool(getattr(bridge, "_shutdown_cleanup_started", False)),
        "archived": bool((heartbeat or {}).get("archived")),
        "archive_path": str((heartbeat or {}).get("archive_path") or ""),
        "archive_label": str((heartbeat or {}).get("archive_label") or ""),
        "archive_group": str((heartbeat or {}).get("archive_group") or ""),
        "final_bucket": str((heartbeat or {}).get("final_bucket") or ""),
        "stop_reason": str((heartbeat or {}).get("stop_reason") or data.get("reason") or ""),
    }


def _write_failure_state(bridge: Any, code: str, detail: str, stop_result: Dict[str, Any], *, logger_failed: bool = False, monitor_failed: bool = False, diagnostics: Optional[Dict[str, Any]] = None) -> None:
    facade = _legacy()._facade()
    try:
        state = facade.read_session_state(default={})
    except Exception:
        state = {}
    updated = dict(state) if isinstance(state, dict) else {}
    diag_key = getattr(bridge, "_logger_process_key", lambda: "")() if logger_failed else "monitor"
    diagnostics = _worker_exit_diagnostics(
        bridge,
        str(diag_key or "monitor"),
        diagnostics if isinstance(diagnostics, dict) else ((stop_result or {}).get("logger" if logger_failed else "monitor") if isinstance(stop_result, dict) else {}),
        logger_failed=logger_failed,
        monitor_failed=monitor_failed,
    )
    updated.update({
        "active": False,
        "session_state": "stopped",
        "flow": "protected_stopped",
        "status": code,
        "runtime_status": code,
        "runtime_decision": "failed",
        "decision": "failed",
        "logger_ready": False,
        "monitor_ready": False,
        "logger_failed": bool(logger_failed),
        "monitor_failed": bool(monitor_failed),
        "technical_failure": True,
        "awaiting_evidence": False,
        "riskAvailable": False,
        "decisionRiskAvailable": False,
        "risk_available": False,
        "decision_risk_available": False,
        "risk_engine_stopped": True,
        "process_pair_failed": True,
        "process_pair_state": code,
        "protected_failure_reason": detail,
        "runtime_diag_code": code,
        "runtime_diag_reason": detail,
        "runtime_diagnostic_code": code,
        "runtime_diagnostic_reason": detail,
        "auto_resume_pending": False,
        "resume_after_unlock": False,
        "return_verification": False,
        "forced_stop": False,
        "screen_locked": False,
        "app_locked": False,
        "protected_action_requested": False,
        "postLockConfirmationPending": False,
        "postLockConfirmationPromptAfterUnlock": False,
        "postLockConfirmationStage": "",
        "postLockConfirmationEventId": "",
        "postLockConfirmationEventSessionId": "",
        "lock_reason": "",
        "final_action": "worker_exited_after_ready",
        "supervisor_stop_result": dict(stop_result or {}),
        "worker_exit_diagnostics": diagnostics,
    })
    facade.write_session_state(updated)
    bridge._runtime_state = dict(updated)
    try:
        _legacy()._facade().invalidate_session_discovery_cache()
    except Exception:
        pass
    _request_refresh(bridge, f"supervisor:{code}")

def _clear_bridge_runtime_flags(bridge: Any) -> None:
    for name in ("_clear_pending_logger_start", "_clear_pending_monitor_start"):
        fn = getattr(bridge, name, None)
        if callable(fn):
            fn()
    bridge._active_live_session_dir = None
    bridge._last_alert_signature = None
    try:
        _legacy()._facade().invalidate_session_discovery_cache()
    except Exception:
        pass

def _request_refresh(bridge: Any, reason: str) -> None:
    def _do_refresh() -> None:
        timer = getattr(bridge, "_update_refresh_timer", None)
        if callable(timer):
            timer(force=True)
        try:
            _legacy()._request_refresh(bridge, reason, True)
        except Exception:
            pass

    dispatch_to_qt_thread(bridge, _do_refresh, target_action=f"supervisor_stop_refresh:{reason}")
