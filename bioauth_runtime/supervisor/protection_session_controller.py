"""Start Protection orchestration for the commercial runtime supervisor."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict

from . import heartbeat_store, start_diagnostics, worker_processes
from bridge.qt_thread_dispatch import dispatch_to_qt_thread

LOGGER = logging.getLogger(__name__)
SAFE_START_FAILED_MESSAGE = start_diagnostics.SAFE_START_FAILED_MESSAGE


def _legacy():
    from bridge import session_runtime_helpers
    return session_runtime_helpers


def start_protection(bridge: Any, *, auto_resume: bool = False, trigger_refresh: bool = True) -> bool:
    """Create one protected session and start logger first."""
    start_diagnostics.log_checkpoint(bridge, "supervisor_start_entered", auto_resume=bool(auto_resume))
    try:
        return _start_protection_inner(bridge, auto_resume=auto_resume, trigger_refresh=trigger_refresh)
    except Exception as exc:  # pragma: no cover - exercised through targeted tests.
        start_diagnostics.log_exception(bridge, exc)
        start_diagnostics.write_start_failed_state(
            bridge,
            _legacy,
            "start_protection_exception",
            start_diagnostics.safe_reason(exc),
            checkpoint="start_failed_exception",
        )
        start_diagnostics.set_status(bridge, SAFE_START_FAILED_MESSAGE, "danger")
        _request_refresh(bridge, trigger_refresh, "supervisor:start_failed_exception")
        return False


def _start_protection_inner(bridge: Any, *, auto_resume: bool, trigger_refresh: bool) -> bool:
    legacy = _legacy()
    facade = legacy._facade()
    refresh_timer = getattr(bridge, "_update_refresh_timer", None) if trigger_refresh else None
    debug = getattr(bridge, "_debug_trace", None)
    try:
        import os
        from bioauth_runtime.desktop_instance import owns_desktop_instance
        if os.environ.get("BIOAUTH_DESKTOP_INSTANCE_ID") and not owns_desktop_instance(getattr(facade, "BASE_DIR", "")):
            return _block_start(
                bridge,
                "start_blocked_not_active_desktop_instance",
                "Another BioAuth desktop instance owns this control directory.",
                trigger_refresh=trigger_refresh,
                preserve_current=True,
            )
    except Exception:
        LOGGER.debug("Desktop instance ownership check failed safely", exc_info=True)
    if callable(debug):
        debug("supervisor", "start protection requested", payload={"auto_resume": bool(auto_resume)})

    user = getattr(bridge, "_current_user", None)
    start_diagnostics.log_checkpoint(bridge, "current_user_resolved", has_user=bool(user), user_id=start_diagnostics.safe_user_id(user))
    if not user:
        return _block_start(
            bridge,
            "start_blocked_no_authenticated_user",
            "No authenticated user is available for Start Protection.",
            trigger_refresh=trigger_refresh,
        )

    active_state = bridge._active_state_for_current_user()
    flow = legacy._normal_user_session_flow(bridge, active_state)
    start_diagnostics.log_checkpoint(bridge, "active_session_guard_checked", flow=flow, active=bool(active_state.get("active")))

    in_progress = _start_already_in_progress(bridge, active_state)
    start_diagnostics.log_checkpoint(bridge, "start_in_progress_guard_checked", in_progress=bool(in_progress))
    if in_progress:
        return _block_start(
            bridge,
            "start_blocked_start_already_in_progress",
            "Start Protection is already in progress.",
            trigger_refresh=trigger_refresh,
            status_key="already_running",
            preserve_current=True,
        )

    if flow != "idle" and not (auto_resume and flow == "protected_resume_pending"):
        return _block_start(
            bridge,
            "start_blocked_already_active",
            "Protected runtime is already active or not idle.",
            trigger_refresh=trigger_refresh,
            status_key="already_running",
            preserve_current=True,
        )

    start_diagnostics.log_checkpoint(bridge, "onboarding_or_consent_validation_result", started=True)
    if not _validate_user_ready(bridge):
        return _block_start(
            bridge,
            "start_blocked_onboarding_required",
            "Onboarding or policy consent is required before Start Protection.",
            trigger_refresh=trigger_refresh,
            keep_existing_status=True,
        )
    start_diagnostics.log_checkpoint(bridge, "onboarding_or_consent_validation_result", ok=True)

    start_diagnostics.log_checkpoint(bridge, "production_profile_validation_started")
    profile = _production_profile(bridge)
    profile_ready = bool(profile.get("production_ready"))
    start_diagnostics.log_checkpoint(bridge, "production_profile_validation_result", production_ready=profile_ready)
    if not profile_ready:
        return _block_start(
            bridge,
            "start_blocked_profile_not_ready",
            "Production runtime profile is not ready.",
            trigger_refresh=trigger_refresh,
            status_key="profile_not_runtime_ready",
        )

    if not _prepare_new_session(bridge, auto_resume=auto_resume):
        if callable(refresh_timer):
            refresh_timer(force=True)
        return _block_start(
            bridge,
            "start_blocked_runtime_state_busy",
            getattr(bridge, "_last_process_start_error", "Runtime state is busy."),
            trigger_refresh=trigger_refresh,
            keep_existing_status=True,
        )

    try:
        started = _start_logger(bridge)
    except Exception as exc:
        bridge._active_live_session_dir = None
        bridge._last_process_start_error = SAFE_START_FAILED_MESSAGE
        start_diagnostics.write_logger_spawn_failed_state(bridge, _legacy, worker_processes, "logger_spawn_failed")
        start_diagnostics.log_checkpoint(bridge, "logger_spawn_failed", error_type=type(exc).__name__, error_message=start_diagnostics.safe_reason(exc))
        start_diagnostics.set_status(bridge, SAFE_START_FAILED_MESSAGE, "danger")
        _request_refresh(bridge, trigger_refresh, "supervisor:logger_spawn_failed")
        return False
    if not started:
        bridge._active_live_session_dir = None
        start_diagnostics.write_logger_spawn_failed_state(bridge, _legacy, worker_processes, "logger_spawn_failed")
        if not getattr(bridge, "_last_process_start_error", ""):
            start_diagnostics.set_status(bridge, SAFE_START_FAILED_MESSAGE, "danger")
        _request_refresh(bridge, trigger_refresh, "supervisor:logger_spawn_failed")
        return False

    _mark_monitor_pending(bridge)
    start_diagnostics.log_checkpoint(bridge, "pending_logger_readiness_written", pending_logger=True, pending_monitor=True)
    _ensure_start_watcher(bridge)
    _ensure_health_watcher(bridge)
    start_diagnostics.set_status(bridge, bridge._t("protected_resumed_verify" if auto_resume else "protected_starting_capture"), "info")
    start_diagnostics.log_checkpoint(bridge, "supervisor_start_completed", session_id=getattr(bridge, "_pending_logger_session_id", ""))
    _request_refresh(bridge, trigger_refresh, "supervisor:start_protected")
    return True


def advance_pending_start(bridge: Any) -> Dict[str, Any]:
    """Progress logger/monitor readiness from supervisor-owned polling."""
    result = {"logger": False, "monitor": False}
    if bool(getattr(bridge, "_pending_logger_start", False)):
        result["logger"] = _finish_pending_logger_start(bridge)
    if bool(getattr(bridge, "_pending_monitor_start", False)):
        result["monitor"] = _finish_pending_monitor_start(bridge)
    return result



def _ensure_start_watcher(bridge: Any) -> None:
    """Run pending logger/monitor readiness outside dashboard refresh."""
    if bool(getattr(bridge, "_supervisor_start_watcher_active", False)):
        return
    bridge._supervisor_start_watcher_active = True

    def _watch() -> None:
        try:
            deadline = time.time() + 45.0
            while time.time() < deadline:
                if not (bool(getattr(bridge, "_pending_logger_start", False)) or bool(getattr(bridge, "_pending_monitor_start", False))):
                    return
                advance_pending_start(bridge)
                time.sleep(0.25)
        finally:
            bridge._supervisor_start_watcher_active = False

    threading.Thread(target=_watch, name="bioauth-supervisor-start", daemon=True).start()


def _ensure_health_watcher(bridge: Any) -> None:
    """Keep worker failure handling in supervisor-owned background polling."""
    if bool(getattr(bridge, "_supervisor_health_watcher_active", False)):
        return
    bridge._supervisor_health_watcher_active = True

    def _watch() -> None:
        try:
            while _protected_runtime_active(bridge):
                try:
                    bridge._cleanup_processes()
                except Exception:
                    LOGGER.debug("supervisor health cleanup failed safely", exc_info=True)
                time.sleep(1.0)
        finally:
            bridge._supervisor_health_watcher_active = False

    threading.Thread(target=_watch, name="bioauth-supervisor-health", daemon=True).start()


def _protected_runtime_active(bridge: Any) -> bool:
    try:
        state = _legacy()._facade().read_session_state(default={})
    except Exception:
        state = {}
    return isinstance(state, dict) and str(state.get("session_kind") or "").lower() == "protected" and bool(state.get("active"))


def _validate_user_ready(bridge: Any) -> bool:
    if not getattr(bridge, "_current_user", None):
        return False
    if not bridge._has_current_user_welcome_consent():
        bridge._onboarding_visible = True
        bridge.onboardingChanged.emit()
        start_diagnostics.set_status(bridge, bridge._t("policy_required"), "warn")
        return False
    return True


def _production_profile(bridge: Any) -> Dict[str, Any]:
    legacy = _legacy()
    facade = legacy._facade()
    user_id = bridge._current_user["user_id"]
    profile = bridge._profile if isinstance(getattr(bridge, "_profile", None), dict) and bridge._profile else facade.user_profile_status(user_id)
    if bool(profile.get("production_ready")):
        return dict(profile)
    try:
        from metadata_core.production_bootstrap import last_good_production_overlay

        overlay = last_good_production_overlay(str(user_id))
    except Exception:
        overlay = {}
    if overlay and bool(overlay.get("production_ready") or overlay.get("productionReady")):
        merged = dict(profile)
        merged.update(overlay)
        bridge._profile = merged
        return merged
    return dict(profile)


def _prepare_new_session(bridge: Any, *, auto_resume: bool) -> bool:
    legacy = _legacy()
    facade = legacy._facade()
    if not legacy.stop_stale_monitor(bridge):
        start_diagnostics.set_status(bridge, bridge._t("stop_requested"), "info")
        return False
    facade.clear_stop(bridge._logger_key())
    facade.clear_stop("monitor")
    # Hotfix 7G: remove stale legacy/unscoped worker controls before new protected start.
    for stale_name in ("logger_legit", "logger_intruder"):
        try:
            facade.clear_stop(stale_name)
        except Exception:
            LOGGER.debug("Failed clearing stale legacy stop control %s", stale_name, exc_info=True)
    bridge._clear_history_archive_watch()
    prepare = getattr(facade, "prepare_session_state_for_new_runtime", None)
    if callable(prepare):
        try:
            prepared = prepare("protected_start", stale_after_sec=4.0)
        except TypeError:
            prepared = prepare("protected_start")
        except Exception as exc:
            prepared = {"ok": False, "detail": str(exc)}
        if prepared and not bool(prepared.get("ok", True)):
            bridge._last_process_start_error = "Protection could not start because the runtime state is busy. Please try again."
            start_diagnostics.set_status(bridge, bridge._last_process_start_error, "danger")
            return False
    if not facade.clear_session_state():
        bridge._last_process_start_error = "Protection could not start because runtime state could not be reset."
        start_diagnostics.set_status(bridge, bridge._last_process_start_error, "danger")
        return False
    heartbeat_store.clear_current_session()
    if auto_resume:
        _clear_stale_runtime_summary()
    start_diagnostics.log_checkpoint(bridge, "stale_heartbeats_cleared")
    facade.invalidate_session_discovery_cache()
    invalidate = getattr(bridge, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    bridge._last_alert_signature = None
    bridge._pending_logger_session_id = facade.uuid.uuid4().hex
    start_diagnostics.log_checkpoint(bridge, "session_id_created", session_id=bridge._pending_logger_session_id)
    bridge._pending_logger_run_id = facade.uuid.uuid4().hex
    start_diagnostics.log_checkpoint(bridge, "run_id_created", run_id=bridge._pending_logger_run_id)
    bridge._active_live_session_dir = bridge._new_live_session_dir()
    start_diagnostics.log_checkpoint(bridge, "live_session_dir_created", live_session_dir=bridge._active_live_session_dir)
    _write_initial_state(bridge, auto_resume=auto_resume)
    return True


def _write_initial_state(bridge: Any, *, auto_resume: bool) -> None:
    legacy = _legacy()
    facade = legacy._facade()
    now = facade.time.time()
    state = {
        "schema_version": 2,
        "session_id": bridge._pending_logger_session_id,
        "run_id": bridge._pending_logger_run_id,
        "mode": "standalone",
        "decision": "pending",
        "active": True,
        "source": "supervisor",
        "user": bridge._current_user["user_id"],
        "user_id": bridge._current_user["user_id"],
        "session_kind": "protected",
        "started_at": now,
        "started_at_text": facade.time.strftime("%Y-%m-%d %H:%M:%S", facade.time.localtime(now)),
        "status": "verifying_return" if auto_resume else "starting",
        "flow": "verifying_return" if auto_resume else "protected_starting",
        "runtime_status": "starting",
        "runtime_decision": "pending",
        "logger_ready": False,
        "monitor_ready": False,
        "monitor_failed": False,
        "logger_failed": False,
        "technical_failure": False,
        "awaiting_evidence": True,
        "pending_monitor_start": True,
        "live_session_dir": bridge._active_live_session_dir,
        "worker_heartbeat_single_writer": True,
        "worker_heartbeat_waiting_for": "logger",
        "runtime_diag_code": "protected_starting",
        "runtime_diag_reason": "Waiting for logger readiness.",
    }
    try:
        from bioauth_runtime.desktop_instance import current_instance
        instance = current_instance()
        if instance:
            state.update({
                "desktop_instance_pid": instance.get("pid"),
                "desktop_instance_executable": instance.get("executable_path"),
                "desktop_instance_id": instance.get("instance_id"),
            })
    except Exception:
        pass
    if auto_resume:
        source = getattr(bridge, "_auto_resume_source_state", {})
        source = source if isinstance(source, dict) else {}
        try:
            attempt_count = int(source.get("auto_resume_attempt_count") or source.get("lock_loop_guard_auto_resume_attempt_count") or 1)
        except (TypeError, ValueError):
            attempt_count = 1
        state.update({
            "return_verification": True,
            "auto_resume_pending": False,
            "resume_after_unlock": False,
            "auto_resume_attempt_count": max(1, attempt_count),
            "lock_loop_guard_auto_resume_attempt_count": max(1, attempt_count),
            "auto_resume_from_lock_handoff_id": source.get("lock_handoff_id") or source.get("lock_loop_guard_handoff_id") or "",
            "last_lock_handoff_session_id": source.get("session_id") or "",
            "last_lock_handoff_ts": source.get("lock_controller_last_attempt_at") or source.get("expected_worker_exit_recorded_at") or "",
            "auto_resume_started_at": now,
            "auto_resume_in_progress": False,
            "resume_in_progress": False,
            "auto_resume_completed": True,
            "auto_resume_completed_at": now,
            "auto_resume_claim_id": source.get("auto_resume_claim_id") or "",
            "auto_resume_claimed_at": source.get("auto_resume_claimed_at") or "",
            "auto_resume_grace_until": now + 30.0,
            "auto_resume_min_quality_windows": 3,
            "auto_resume_loop_guard_armed": True,
            "post_unlock_fresh_window_required": True,
            "stale_runtime_summary_cleared_for_auto_resume": True,
        })
    start_diagnostics.log_checkpoint(bridge, "initial_session_state_write_started")
    facade.write_session_state(state)
    bridge._runtime_state = dict(state)
    start_diagnostics.log_checkpoint(bridge, "initial_session_state_written", session_id=state.get("session_id"))


def _clear_stale_runtime_summary() -> None:
    """Remove previous-session risk summary before post-unlock verification starts."""
    try:
        from pathlib import Path
        from control import CONTROL_DIR

        for name in ("runtime_summary.json", "runtime_summary.json.tmp"):
            try:
                (Path(CONTROL_DIR) / name).unlink(missing_ok=True)
            except Exception:
                LOGGER.debug("Failed clearing stale %s", name, exc_info=True)
    except Exception:
        LOGGER.debug("Failed clearing stale runtime summary", exc_info=True)


def _start_logger(bridge: Any) -> bool:
    legacy = _legacy()
    facade = legacy._facade()
    bridge._pending_logger_start = True
    bridge._pending_logger_process_key = bridge._logger_process_key()
    bridge._pending_logger_session_kind = "protected"
    bridge._pending_logger_user_id = bridge._current_user["user_id"]
    bridge._logger_start_deadline = facade.time.monotonic() + facade.LOGGER_START_GRACE_SEC
    bridge._logger_start_failed = False
    args = [facade.LOGGER_SCRIPT, bridge._current_user["user_id"], "protected"]
    start_diagnostics.log_checkpoint(bridge, "logger_spawn_requested", key=bridge._logger_process_key(), args=args)
    try:
        started = bool(worker_processes.start_worker(
            bridge,
            bridge._logger_process_key(),
            args,
            extra_env=bridge._session_process_env(),
        ))
    except Exception as exc:
        start_diagnostics.log_checkpoint(bridge, "logger_spawn_failed", error_type=type(exc).__name__, error_message=start_diagnostics.safe_reason(exc))
        bridge._last_process_start_error = SAFE_START_FAILED_MESSAGE
        raise
    pid = _worker_pid(bridge, bridge._logger_process_key())
    start_diagnostics.log_checkpoint(bridge, "logger_spawn_result", ok=started, pid=pid)
    return started


def _mark_monitor_pending(bridge: Any) -> None:
    facade = _legacy()._facade()
    bridge._pending_monitor_start = True
    bridge._pending_monitor_user_id = bridge._current_user["user_id"]
    bridge._monitor_start_deadline = facade.time.time() + facade.MONITOR_START_GRACE_SEC
    bridge._monitor_launch_attempted = False
    bridge._monitor_start_failed = False


def _finish_pending_logger_start(bridge: Any) -> bool:
    # Existing implementation contains only pending-start state transitions.
    from bridge import refresh_runtime_helpers

    refresh_runtime_helpers.maybe_finish_pending_logger_start(bridge)
    return not bool(getattr(bridge, "_pending_logger_start", False))


def _finish_pending_monitor_start(bridge: Any) -> bool:
    from bridge import refresh_runtime_helpers

    refresh_runtime_helpers.maybe_finish_pending_monitor_start(bridge)
    completed = not bool(getattr(bridge, "_pending_monitor_start", False))
    if completed:
        _normalize_startup_state_after_monitor_ready(bridge)
    return completed


def _normalize_startup_state_after_monitor_ready(bridge: Any) -> None:
    legacy = _legacy()
    facade = legacy._facade()
    try:
        state = facade.read_session_state(default={})
        merged = heartbeat_store.merge_into_state(bridge, state, persist=False)
        normalized, changed = heartbeat_store.normalize_protected_startup_ready_state(merged)
        if changed or normalized != state:
            facade.write_session_state(normalized)
            bridge._runtime_state = dict(normalized)
            start_diagnostics.log_checkpoint(
                bridge,
                "protected_startup_state_advanced",
                session_id=normalized.get("session_id"),
                flow=normalized.get("flow"),
                runtime_status=normalized.get("runtime_status"),
            )
    except Exception:
        LOGGER.debug("Failed advancing protected startup state after monitor readiness", exc_info=True)


def _request_refresh(bridge: Any, enabled: bool, reason: str) -> None:
    if not enabled:
        return

    def _do_refresh() -> None:
        timer = getattr(bridge, "_update_refresh_timer", None)
        if callable(timer):
            timer(force=True)
        _legacy()._request_refresh(bridge, reason, True)

    if not dispatch_to_qt_thread(bridge, _do_refresh, target_action=f"supervisor_refresh:{reason}"):
        return


def _start_already_in_progress(bridge: Any, state: Dict[str, Any]) -> bool:
    if bool(getattr(bridge, "_pending_logger_start", False)) or bool(getattr(bridge, "_pending_monitor_start", False)):
        return True
    status = str((state or {}).get("status") or "").lower()
    flow = str((state or {}).get("flow") or "").lower()
    if status in {"starting", "logger_starting", "monitor_starting"}:
        return True
    return flow == "protected_starting"


def _block_start(
    bridge: Any,
    code: str,
    reason: str,
    *,
    trigger_refresh: bool,
    status_key: str = "",
    keep_existing_status: bool = False,
    preserve_current: bool = False,
) -> bool:
    start_diagnostics.log_checkpoint(bridge, code, reason=reason)
    if not keep_existing_status:
        start_diagnostics.set_status(bridge, bridge._t(status_key) if status_key else SAFE_START_FAILED_MESSAGE, "warn")
    if preserve_current:
        start_diagnostics.write_start_blocked_state(bridge, _legacy, code, reason)
    else:
        start_diagnostics.write_start_failed_state(bridge, _legacy, code, reason, checkpoint=code)
    _request_refresh(bridge, trigger_refresh, f"supervisor:{code}")
    return False


def _worker_pid(bridge: Any, key: str) -> Any:
    try:
        proc = (getattr(bridge, "_running_processes", {}) or {}).get(str(key))
        return getattr(proc, "pid", None)
    except Exception:
        return None
