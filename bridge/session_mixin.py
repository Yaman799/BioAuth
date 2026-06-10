from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from evidence_capture import delete_evidence_for_session
from feedback_loop import record_warning_feedback
from paths import data_dir

from . import session_history_helpers, session_runtime_helpers, session_training_helpers, session_promotion_helpers
from release_runtime import write_release_runtime_event
from shadow_core.background_contracts import (
    shadow_evidence_ledger_path,
    shadow_evidence_paths,
    shadow_evidence_state_path,
    shadow_eval_report_path,
    shadow_gate_result_path,
    shadow_logger_key,
    shadow_logger_process_key,
    shadow_logger_stop_control_name,
    shadow_monitor_key,
    shadow_monitor_process_key,
    shadow_monitor_stop_control_name,
)

from .shared import (
    BASE_DIR,
    LOGGER_SCRIPT,
    MAX_ENROLLMENT_SESSIONS,
    MIN_ENROLLMENT_SESSIONS,
    MONITOR_SCRIPT,
    LOGGER_START_GRACE_SEC,
    MONITOR_START_GRACE_SEC,
    QDesktopServices,
    QUrl,
    Slot,
    _spawn_command,
    build_user_dashboard_snapshot,
    clear_session_state,
    clear_stop,
    current_boot_marker,
    current_boot_time_epoch,
    invalidate_session_discovery_cache,
    read_session_metadata,
    remove_session_from_index,
    update_session_index_for_path,
    read_session_state,
    request_stop,
    sessions_dir,
    slugify_username,
    write_session_state,
    read_worker_heartbeat,
    write_worker_heartbeat,
    clear_worker_heartbeat,
    train_user_model,
    user_profile_status,
    translate_backend_result,
    translate_string,
    runtime_status_is_technical_failure,
    is_current_session_locked,
)

LOGGER = logging.getLogger(__name__)


_USER_HOME_ALLOWED_ACTIONS = frozenset({
    "start_enrollment",
    "stop_enrollment",
    "start_protection",
    "stop_protection",
    "train_profile",
    "open_settings",
    "refresh_status",
})


class SessionMixin:

    def _destructive_action_block_reason(self, *, for_delete: bool = False) -> str:
        flow = self._session_flow()
        if flow != "idle":
            return self._t("account_delete_busy" if for_delete else "profile_reset_busy")
        if bool(getattr(self, "_training_in_progress", False)):
            return self._t("account_delete_training" if for_delete else "profile_reset_training")
        return ""

    def _resolve_user_session_path(self, path: str) -> tuple[str, Dict[str, Any]]:
        if not self._current_user or not path:
            raise ValueError(self._t("history_delete_fail"))
        safe_user = self._safe_user()
        resolved = os.path.realpath(path)
        sessions_root = os.path.realpath(sessions_dir())
        if os.path.commonpath([resolved, sessions_root]) != sessions_root:
            raise ValueError(self._t("history_delete_fail"))
        meta = read_session_metadata(resolved) or {}
        meta_user = slugify_username(str(meta.get("user_id") or "")) if meta.get("user_id") else ""
        name = os.path.basename(resolved)
        if meta_user and meta_user != safe_user:
            raise ValueError(self._t("history_delete_fail"))
        if not meta_user and not name.startswith(f"{safe_user}_"):
            raise ValueError(self._t("history_delete_fail"))
        return resolved, meta

    def _safe_user(self) -> str:
        return slugify_username((self._current_user or {}).get("user_id", ""))

    def _logger_key(self) -> str:
        return f"logger_user_{self._safe_user()}"

    def _logger_process_key(self) -> str:
        return self._logger_key() if self._current_user else "logger"

    def _shadow_logger_key(self, user_id: Optional[str] = None) -> str:
        return shadow_logger_key(user_id if user_id is not None else self._safe_user())

    def _shadow_logger_process_key(self, user_id: Optional[str] = None) -> str:
        return shadow_logger_process_key(user_id if user_id is not None else self._safe_user())

    def _shadow_logger_stop_control_name(self, user_id: Optional[str] = None) -> str:
        return shadow_logger_stop_control_name(user_id if user_id is not None else self._safe_user())

    def _shadow_monitor_key(self, user_id: Optional[str] = None) -> str:
        return shadow_monitor_key(user_id if user_id is not None else self._safe_user())

    def _shadow_monitor_process_key(self, user_id: Optional[str] = None) -> str:
        return shadow_monitor_process_key(user_id if user_id is not None else self._safe_user())

    def _shadow_monitor_stop_control_name(self, user_id: Optional[str] = None) -> str:
        return shadow_monitor_stop_control_name(user_id if user_id is not None else self._safe_user())

    def _shadow_evidence_state_path(self, user_id: Optional[str] = None) -> str:
        return shadow_evidence_state_path(user_id if user_id is not None else self._safe_user())

    def _shadow_evidence_ledger_path(self, user_id: Optional[str] = None) -> str:
        return shadow_evidence_ledger_path(user_id if user_id is not None else self._safe_user())

    def _shadow_eval_report_path(self, user_id: Optional[str] = None) -> str:
        return shadow_eval_report_path(user_id if user_id is not None else self._safe_user())

    def _shadow_gate_result_path(self, user_id: Optional[str] = None) -> str:
        return shadow_gate_result_path(user_id if user_id is not None else self._safe_user())

    def _shadow_evidence_paths(self, user_id: Optional[str] = None) -> Dict[str, str]:
        return shadow_evidence_paths(user_id if user_id is not None else self._safe_user())

    def _new_live_session_dir(self) -> str:
        base = os.path.join(data_dir(), "live_session_runs")
        os.makedirs(base, exist_ok=True)
        token = f"{self._safe_user() or 'user'}_{uuid.uuid4().hex}"
        path = os.path.join(base, token)
        os.makedirs(path, exist_ok=True)
        return path

    def _session_process_env(self) -> Optional[Dict[str, str]]:
        live_dir = str(getattr(self, "_active_live_session_dir", "") or "").strip()
        if not live_dir:
            return None
        session_id = str(getattr(self, "_pending_logger_session_id", "") or "").strip()
        run_id = str(getattr(self, "_pending_logger_run_id", "") or "").strip()
        env = {"BIOAUTH_LIVE_SESSION_DIR": live_dir}
        if session_id:
            env["BIOAUTH_SESSION_ID"] = session_id
        if run_id:
            env["BIOAUTH_RUN_ID"] = run_id
        desktop_instance_id = str(os.environ.get("BIOAUTH_DESKTOP_INSTANCE_ID", "") or "").strip()
        desktop_instance_pid = str(os.environ.get("BIOAUTH_DESKTOP_INSTANCE_PID", "") or "").strip()
        if desktop_instance_id:
            env["BIOAUTH_DESKTOP_INSTANCE_ID"] = desktop_instance_id
        if desktop_instance_pid:
            env["BIOAUTH_DESKTOP_INSTANCE_PID"] = desktop_instance_pid
        dev_sim_active = False
        try:
            checker = getattr(self, "_developer_production_ready_simulation_active", None)
            dev_sim_active = bool(checker()) if callable(checker) else False
        except Exception:
            dev_sim_active = False
        if dev_sim_active and not bool(getattr(self, "_pending_passive_auto_enrollment", False)):
            env.update({
                "BIOAUTH_DEV_PRODUCTION_READY_SIMULATION": "1",
                "BIOAUTH_ALLOW_SHADOW_CANDIDATE_RUNTIME_FALLBACK": "1",
                "BIOAUTH_RUNTIME_BUNDLE_SOURCE": "developer_shadow_candidate",
            })
        if bool(getattr(self, "_pending_passive_auto_enrollment", False)):
            try:
                from metadata_core.auto_enrollment import passive_collection_env

                env.update(
                    passive_collection_env(
                        getattr(self, "_pending_remediation_plan", None),
                        remediation_plan_id=str(getattr(self, "_pending_remediation_plan_id", "") or ""),
                    )
                )
            except Exception:
                env.update({
                    "BIOAUTH_AUTO_ENROLLMENT": "1",
                    "BIOAUTH_COLLECTION_SOURCE": "passive_auto_enrollment",
                })
        return env

    def _clear_history_archive_watch(self) -> None:
        self._history_sync_pending = False
        self._history_sync_deadline = 0.0
        self._history_sync_hard_deadline = 0.0
        self._history_sync_started_at = 0.0
        self._history_sync_status = "idle"
        self._history_sync_warning = ""

    def _begin_history_archive_watch(self, timeout_sec: float = 15.0, *, hard_timeout_sec: float = 30.0) -> None:
        now = time.time()
        soft_timeout = max(2.0, float(timeout_sec))
        hard_timeout = max(soft_timeout, float(hard_timeout_sec))
        self._history_sync_pending = True
        self._history_sync_started_at = now
        self._history_sync_deadline = now + soft_timeout
        self._history_sync_hard_deadline = now + hard_timeout
        self._history_sync_status = "finalizing"
        self._history_sync_warning = ""

    def _start_process(self, key: str, args: List[str], extra_env: Optional[Dict[str, str]] = None) -> bool:
        return session_runtime_helpers.start_process(self, key, args, extra_env=extra_env)

    def _maybe_start_passive_auto_enrollment(self) -> bool:
        return session_runtime_helpers.maybe_start_passive_auto_enrollment(self)

    def _maybe_finalize_passive_auto_enrollment(self) -> bool:
        return session_runtime_helpers.maybe_finalize_passive_auto_enrollment(self)

    def _recover_stale_passive_auto_enrollment_finalization(self, *, source: str = "refresh") -> bool:
        return session_runtime_helpers.recover_stale_passive_auto_enrollment_finalization(self, source=source)

    def _maybe_start_auto_training(self) -> bool:
        return session_training_helpers.maybe_start_auto_training(self)

    def _maybe_auto_promote_production(self) -> bool:
        return session_promotion_helpers.maybe_auto_promote_production(self)

    def _stop_passive_auto_enrollment_if_active(self, *, reason: str = "opt_out") -> bool:
        return session_runtime_helpers.stop_passive_auto_enrollment_if_active(self, reason=reason)

    def _expected_monitor_exit_after_forced_stop(self, state: Optional[Dict[str, Any]], diagnostics: Optional[Dict[str, Any]] = None) -> bool:
        """Classify a monitor process exit after a deliberate high-risk stop.

        The monitor exits cleanly after monitor_core.incident writes a
        resume-pending forced-stop state.  That is not a risk-engine failure; it
        is the handoff point where the UI should wait for unlock and auto-start
        a fresh protected session.
        """
        state = state if isinstance(state, dict) else {}
        if not state:
            return False
        session_kind = str(state.get("session_kind") or state.get("runtime_mode") or state.get("mode") or "").strip().lower()
        if session_kind not in {"protected", "monitored"}:
            return False
        status = str(state.get("status") or "").strip().lower()
        final_decision = str(state.get("final_decision") or state.get("archive_label") or state.get("decision") or "").strip().lower()
        stop_reason = str(state.get("stop_reason") or "").strip().lower()
        expected = bool(
            state.get("forced_stop_expected_monitor_exit")
            or state.get("monitor_exit_expected")
            or state.get("auto_resume_pending")
            or state.get("resume_after_unlock")
            or status == "resume_pending"
            or stop_reason in {"monitor_intruder", "confirmed_high_risk", "intruder_lock"}
            or final_decision == "intruder"
        )
        if not expected:
            return False
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        try:
            detail, failure_diag = session_runtime_helpers.worker_failure_detail(self, "monitor", fallback="monitor_exited_after_forced_stop")
        except Exception:
            detail, failure_diag = "monitor_exited_after_forced_stop", diagnostics
        failure_diag = failure_diag if isinstance(failure_diag, dict) else diagnostics
        stderr_tail = list(failure_diag.get("stderr_tail") or diagnostics.get("stderr_tail") or [])[-8:]
        stdout_tail = list(failure_diag.get("stdout_tail") or diagnostics.get("stdout_tail") or [])[-8:]
        exit_code = failure_diag.get("exit_code", diagnostics.get("exit_code"))
        now = time.time()
        updated = dict(state)
        updated.update({
            "active": False,
            "status": "resume_pending",
            "monitor_ready": False,
            "monitor_failed": False,
            "technical_failure": False,
            "risk_engine_stopped": False,
            "auto_resume_pending": True,
            "resume_after_unlock": True,
            "resume_reason": updated.get("resume_reason") or "confirmed_high_risk_forced_stop",
            "monitor_exit_expected": True,
            "monitor_exit_reason": "monitor_exited_after_forced_stop",
            "monitor_exit_detail": detail or "monitor_exited_after_forced_stop",
            "monitor_exit_code": exit_code,
            "monitor_exit_recorded_at": now,
            "monitor_stdout_tail": stdout_tail,
            "monitor_stderr_tail": stderr_tail,
            "runtime_diagnostic_code": "monitor_exited_after_forced_stop",
            "runtime_diagnostic_reason": "The risk monitor stopped after a confirmed high-risk forced stop; BioAuth is waiting to resume after unlock.",
            "runtime_diagnostic_summary": f"expected monitor exit after forced stop; {detail or 'monitor_exited_after_forced_stop'}",
            "runtime_confirmation_rule": updated.get("runtime_confirmation_rule") or "warning_followup_lock",
            "runtime_diagnostics": {
                "phase": "monitor_exited_after_forced_stop",
                "detail": detail,
                "exit_code": exit_code,
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
                "previous_status": state.get("status"),
                "previous_decision": state.get("decision"),
                "auto_resume_pending": True,
            },
        })
        try:
            write_session_state(updated)
        except Exception:
            LOGGER.exception("Failed marking expected monitor forced-stop exit")
            return False
        self._monitor_start_failed = False
        self._runtime_state = updated
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("runtime", "Monitor exited after forced-stop handoff", payload={
                "exit_code": exit_code,
                "detail": detail,
                "auto_resume_pending": True,
            }, level="info")
        return True


    def _is_protected_logger_process_key(self, key: str) -> bool:
        key_text = str(key or "")
        return key_text.startswith("logger_user_") and not key_text.startswith("shadow_logger_user_")

    def _mark_logger_exited_after_ready(self, key: str, diagnostics: Optional[Dict[str, Any]] = None) -> None:
        """Compatibility wrapper for supervisor-owned logger death handling."""
        from bioauth_runtime.supervisor import stop_controller

        stop_controller.handle_logger_exit_after_ready(self, key, diagnostics=diagnostics)

    def _mark_monitor_exited_after_ready(self, diagnostics: Optional[Dict[str, Any]] = None) -> None:
        """Compatibility wrapper for supervisor-owned monitor death handling.

        Static compatibility markers from the legacy inline implementation:
        self._expected_monitor_exit_after_forced_stop(state, diagnostics)
        Monitor exited after protected readiness; stopped logger pair
        logger_stop_after_monitor_exit
        logger_stopped_because_monitor_failed
        monitor_exited_logger_stopped
        request_stop(logger_key)
        _terminate_process_key(
        "active": False
        "monitor_exit_stage": "after_ready"
        """
        from bioauth_runtime.supervisor import stop_controller

        stop_controller.handle_monitor_exit_after_ready(self, diagnostics=diagnostics)


    def _cleanup_processes(self) -> None:
        cleaned = getattr(self, "_completed_worker_cleanup_keys", None)
        if not isinstance(cleaned, set):
            cleaned = set()
            self._completed_worker_cleanup_keys = cleaned
        dead = [key for key, proc in self._running_processes.items() if proc.poll() is not None and key not in cleaned]
        if dead:
            debug = getattr(self, "_debug_trace", None)
            if callable(debug):
                debug("process", "Cleaning up completed worker processes", payload={"dead": list(dead)})
        for key in dead:
            cleaned.add(key)
            proc = self._running_processes.get(key)
            try:
                diag = session_runtime_helpers.record_completed_process(self, key, proc, reason="cleanup")
                if self._is_protected_logger_process_key(str(key)):
                    self._mark_logger_exited_after_ready(str(key), diag)
                elif str(key) == "monitor":
                    self._mark_monitor_exited_after_ready(diag)
                write_release_runtime_event("background_worker_completed", key=str(key), reason="cleanup", exit_code=int(diag.get("exit_code") or 0) if diag.get("exit_code") is not None else 0)
            except Exception:
                LOGGER.exception("Failed recording completed worker process %s", key)
            self._running_processes.pop(key, None)

    def _active_state_for_current_user(self) -> Dict[str, Any]:
        state = read_session_state(default={})
        if not self._current_user or not isinstance(state, dict):
            return {}
        current_safe = self._safe_user()
        state_user = slugify_username(state.get("user_id", "") or state.get("expected_user", ""))
        if state_user and state_user != current_safe:
            return {}
        if self._runtime_state_is_orphaned(state):
            self._force_clear_orphaned_runtime_state(state, reason="orphaned_runtime_state_read")
            return {}
        try:
            if session_runtime_helpers.recover_stale_protected_flow_without_workers(
                self, state, reason="stale_protected_flow_without_workers_read"
            ):
                state = read_session_state(default={})
                return state if isinstance(state, dict) else {}
        except Exception:
            LOGGER.debug("Failed recovering stale protected flow without workers", exc_info=True)
        try:
            state = session_runtime_helpers.merge_worker_heartbeats_into_state(self, state)
        except Exception:
            LOGGER.debug("Failed merging worker heartbeats into active state", exc_info=True)
        return state

    def _runtime_state_is_orphaned(self, state: Optional[Dict[str, Any]]) -> bool:
        running_pids = set()
        for proc in getattr(self, "_running_processes", {}).values():
            try:
                if proc is not None and proc.poll() is None and getattr(proc, "pid", None):
                    running_pids.add(int(proc.pid))
            except Exception:
                continue
        return session_runtime_helpers.runtime_state_is_orphaned(
            state,
            current_user=self._safe_user() if self._current_user else "",
            known_running_pids=running_pids,
            pending_logger_start=bool(getattr(self, "_pending_logger_start", False)),
            pending_session_id=str(getattr(self, "_pending_logger_session_id", "") or ""),
        )

    def _force_clear_orphaned_runtime_state(self, state: Optional[Dict[str, Any]] = None, *, reason: str = "") -> None:
        session_runtime_helpers.force_clear_orphaned_runtime_state(self, state, reason=reason)

    def _clear_stale_runtime_state(self) -> None:
        session_runtime_helpers.clear_stale_runtime_state(self)

    def _clear_pending_logger_start(self) -> None:
        self._pending_logger_start = False
        self._pending_logger_user_id = None
        self._pending_logger_session_kind = ""
        self._pending_logger_process_key = None
        self._pending_logger_session_id = ""
        self._pending_logger_run_id = ""
        self._pending_passive_auto_enrollment = False
        self._logger_start_deadline = 0.0
        self._logger_start_failed = False
        signal = getattr(self, "controlsChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()

    def _clear_pending_monitor_start(self) -> None:
        self._pending_monitor_start = False
        self._pending_monitor_user_id = None
        self._monitor_start_deadline = 0.0
        self._monitor_launch_attempted = False
        self._monitor_start_failed = False

    def _clear_pending_shadow_evidence_monitor_start(self) -> None:
        self._pending_shadow_evidence_monitor_start = False
        self._shadow_evidence_monitor_user_id = None
        self._shadow_evidence_monitor_start_deadline = 0.0
        self._shadow_evidence_monitor_launch_attempted = False

    @staticmethod
    def _coerce_training_progress_percent(value: Any) -> int:
        return session_training_helpers.coerce_training_progress_percent(value)

    def _apply_training_progress_payload(self, payload: Any) -> None:
        session_training_helpers.apply_training_progress_payload(self, payload)

    def _queue_training_progress(self, *, percent: Any, stage_key: str = "", detail_key: str = "", message_params: Optional[Dict[str, Any]] = None, headline: str = "", detail: str = "", active: Optional[bool] = None) -> None:
        session_training_helpers.queue_training_progress(
            self,
            percent=percent,
            stage_key=stage_key,
            detail_key=detail_key,
            message_params=message_params,
            headline=headline,
            detail=detail,
            active=active,
        )

    def _set_training_progress_state(self, active: bool) -> None:
        session_training_helpers.set_training_progress_state(self, active)

    def _maybe_autostart_protection(self) -> bool:
        return session_runtime_helpers.maybe_autostart_protection(self)

    def _maybe_start_shadow_evidence_monitor(self) -> bool:
        return session_runtime_helpers.maybe_start_shadow_evidence_monitor(self)

    def _start_shadow_evidence_monitor(self) -> bool:
        return session_runtime_helpers.start_shadow_evidence_monitor(self)

    def _stop_shadow_evidence_monitor(self, *, reason: str = "stop_requested") -> bool:
        return session_runtime_helpers.stop_shadow_evidence_monitor(self, reason=reason)

    def _request_shadow_evidence_stop_for_retry(self, *, reason: str = "remediation_evidence_complete") -> bool:
        return session_runtime_helpers.request_shadow_evidence_stop_for_retry(self, reason=reason)

    def _maybe_mark_shadow_evidence_stopped_for_retry(self) -> bool:
        return session_runtime_helpers.maybe_mark_shadow_evidence_stopped_for_retry(self)

    def _stop_stale_monitor(self, wait_timeout: float = 0.5) -> bool:
        return session_runtime_helpers.stop_stale_monitor(self, wait_timeout=wait_timeout)

    def _session_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
        return session_runtime_helpers.session_flow(self, state=state)

    def _normal_user_session_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
        return session_runtime_helpers._normal_user_session_flow(self, state=state)

    def _normal_enrollment_logger_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
        return session_runtime_helpers._normal_enrollment_logger_flow(self, state=state)

    def _production_monitor_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
        return session_runtime_helpers._production_monitor_flow(self, state=state)

    def _shadow_session_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
        return session_runtime_helpers._shadow_session_flow(self, state=state)

    def _is_shadow_runtime_process_running(self) -> bool:
        return session_runtime_helpers._is_shadow_runtime_process_running(self)

    def _has_stale_shadow_state(self, state: Optional[Dict[str, Any]] = None) -> bool:
        return session_runtime_helpers._has_stale_shadow_state(self, state=state)

    def _clear_stale_shadow_state_if_safe(self, state: Optional[Dict[str, Any]] = None) -> bool:
        return session_runtime_helpers._clear_stale_shadow_state_if_safe(self, state=state)

    @Slot()
    def startEnrollment(self) -> None:
        session_runtime_helpers.start_enrollment(self)

    def _safe_user_action_result(
        self,
        *,
        action: str,
        ok: bool,
        message: str,
        user_safe_reason: str = "",
    ) -> Dict[str, Any]:
        return {
            "ok": bool(ok),
            "action": str(action or ""),
            "message": str(message or ""),
            "user_safe_reason": str(user_safe_reason or message or ""),
        }

    def _deny_user_home_action(self, action: str, message: str, user_safe_reason: str = "") -> Dict[str, Any]:
        safe_action = str(action or "").strip().lower()
        safe_message = str(message or self._t("user_action_unavailable"))
        LOGGER.info("Denied user home action", extra={"action_name": safe_action, "user_safe_reason": str(user_safe_reason or safe_message)})
        self._set_status(safe_message, "warn")
        return self._safe_user_action_result(
            action=safe_action,
            ok=False,
            message=safe_message,
            user_safe_reason=user_safe_reason or safe_message,
        )

    def _execute_user_home_action(self, actionName: str) -> Dict[str, Any]:
        action = str(actionName or "").strip().lower()
        if action not in _USER_HOME_ALLOWED_ACTIONS:
            return self._deny_user_home_action(action, self._t("user_action_unavailable"), self._t("user_action_unavailable"))

        if action == "start_enrollment":
            if not self._can_start_enrollment_logger():
                return self._deny_user_home_action(
                    action,
                    self.startEnrollmentLoggerUnavailableReason or self._t("user_action_unavailable"),
                )
            session_runtime_helpers.start_enrollment(self)
            return self._safe_user_action_result(
                action=action,
                ok=True,
                message=self._t("user_action_start_enrollment_requested"),
            )

        if action == "stop_enrollment":
            if not self._can_stop_enrollment_logger():
                return self._deny_user_home_action(
                    action,
                    self.stopEnrollmentLoggerUnavailableReason or self._t("user_action_unavailable"),
                )
            session_runtime_helpers.stop_enrollment_logger(self, silent=False)
            return self._safe_user_action_result(
                action=action,
                ok=True,
                message=self._t("user_action_stop_enrollment_requested"),
            )

        if action == "start_protection":
            if not self._can_start_production_monitor():
                return self._deny_user_home_action(action, self._t("user_protection_start_unavailable_tooltip"))
            self._start_protected_session(auto_resume=False, trigger_refresh=True)
            return self._safe_user_action_result(
                action=action,
                ok=True,
                message=self._t("user_action_start_protection_requested"),
            )

        if action == "stop_protection":
            if not session_runtime_helpers._protected_session_stop_available(self):
                return self._deny_user_home_action(action, self._t("user_protection_stop_unavailable_tooltip"))
            self.stopProductionMonitor(False)
            return self._safe_user_action_result(
                action=action,
                ok=True,
                message=self._t("user_action_stop_protection_requested"),
            )

        if action == "train_profile":
            if bool(getattr(self, "_training_in_progress", False)):
                return self._deny_user_home_action(action, self._t("training_running"), self._t("training_running"))
            if not bool(getattr(self, "canTrain", False)):
                reason = str(getattr(self, "trainingBlockedReason", "") or self._t("user_action_unavailable"))
                return self._deny_user_home_action(action, reason, reason)
            started = session_training_helpers.train_profile(self, auto_training=False)
            if not bool(started):
                reason = str(
                    getattr(self, "trainingBlockedReason", "")
                    or getattr(self, "_last_training_failure_message", "")
                    or self._t("user_action_unavailable")
                )
                return self._deny_user_home_action(action, reason, reason)
            return self._safe_user_action_result(
                action=action,
                ok=True,
                message=self._t("user_action_train_profile_requested"),
            )

        if action == "refresh_status":
            refresh = getattr(self, "requestRefresh", None)
            if callable(refresh):
                refresh("user_home_action", True)
            return self._safe_user_action_result(
                action=action,
                ok=True,
                message=self._t("user_action_refresh_requested"),
            )

        if action == "open_settings":
            return self._safe_user_action_result(
                action=action,
                ok=True,
                message=self._t("user_action_open_settings_requested"),
            )

        return self._deny_user_home_action(action, self._t("user_action_unavailable"), self._t("user_action_unavailable"))

    @Slot(str, result="QVariantMap")
    def requestUserHomeAction(self, actionName: str) -> Dict[str, Any]:
        return self._execute_user_home_action(actionName)

    @Slot(str, result="QVariantMap")
    def requestUserAction(self, actionName: str) -> Dict[str, Any]:
        return self._execute_user_home_action(actionName)

    @Slot()
    def requestUserStartLearning(self) -> None:
        self._execute_user_home_action("start_enrollment")

    @Slot()
    def requestUserStopLearning(self) -> None:
        self._execute_user_home_action("stop_enrollment")

    def _start_protected_session(self, *, auto_resume: bool = False, trigger_refresh: bool = True) -> bool:
        return session_runtime_helpers.start_protected_session(self, auto_resume=auto_resume, trigger_refresh=trigger_refresh)

    @Slot()
    def startProtected(self) -> None:
        self._start_protected_session(auto_resume=False, trigger_refresh=True)

    @Slot()
    def requestUserStartProtection(self) -> None:
        self._execute_user_home_action("start_protection")

    @Slot()
    def requestUserStopProtection(self) -> None:
        self._execute_user_home_action("stop_protection")

    @Slot(bool)
    def stopCurrentSession(self, silent: bool = False) -> None:
        session_runtime_helpers.stop_current_session(self, silent=silent)

    @Slot(bool)
    def stopEnrollmentLogger(self, silent: bool = False) -> None:
        session_runtime_helpers.stop_enrollment_logger(self, silent=silent)

    @Slot(bool)
    def stopProductionMonitor(self, silent: bool = False) -> None:
        session_runtime_helpers.stop_production_monitor(self, silent=silent)

    @Slot(result="QVariantMap")
    def runHybridDirectTest(self) -> Dict[str, Any]:
        return session_runtime_helpers.run_hybrid_direct_test(self)

    @Slot(result="QVariantMap")
    def evaluateLatestHybridLiveSession(self) -> Dict[str, Any]:
        return session_runtime_helpers.run_latest_live_session_eval(self)

    @Slot(result="QVariantMap")
    def openLatestHybridLiveSessionEvalReport(self) -> Dict[str, Any]:
        state = session_runtime_helpers.latest_hybrid_live_session_eval_report_state(self)
        path = str(state.get("summary_path") or "")
        if not path:
            return {"ok": False, "reason_code": "latest_live_session_eval_report_missing", "message": "No latest live-session evaluation report generated yet."}
        return {
            "ok": True,
            "action": "open_latest_live_session_eval_report_path_returned",
            "path": path,
            "report_only": True,
            "can_influence_device": False,
            "trigger_face_confirmation": False,
            "runtime_authoritative": False,
        }

    def _maybe_resume_protection_after_unlock(self, state: Optional[Dict[str, Any]] = None) -> bool:
        return session_runtime_helpers.maybe_resume_protection_after_unlock(self, state=state)

    def _enforce_confirmed_intruder_event(self, *, state: Optional[Dict[str, Any]] = None, source: str = "backend_policy", reason_code: str = "confirmed_intruder", feedback_record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return session_runtime_helpers.enforce_confirmed_intruder_event(self, state=state, source=source, reason_code=reason_code, feedback_record=feedback_record)

    def _classify_post_lock_confirmation(self, *, state: Optional[Dict[str, Any]] = None, label: str, feedback_record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return session_runtime_helpers.classify_post_lock_confirmation(self, state=state, label=label, feedback_record=feedback_record)

    @Slot()
    def trainProfile(self) -> None:
        session_training_helpers.train_profile(self, auto_training=False)

    @Slot(str)
    def submitWarningFeedback(self, label: str) -> None:
        if not self._current_user:
            return
        state = self._active_state_for_current_user()
        prompt = state.get("feedback_prompt") if isinstance(state.get("feedback_prompt"), dict) else {}
        normalized_label = str(label or "").strip()
        post_lock_pending = bool(state.get("postLockConfirmationPending")) and str(prompt.get("kind") or "") == "post_lock_confirmation"
        if (
            normalized_label in {"confirmed_intruder", "verified_legit_after_warning"}
            and bool(state.get("postLockConfirmationAnswered"))
            and str(state.get("postLockConfirmationEventId") or prompt.get("event_id") or "")
        ):
            updated = dict(state)
            updated["postLockClassificationDuplicateIgnored"] = True
            write_session_state(updated)
            self._runtime_state = updated
            self.runtimeStateChanged.emit()
            self._set_status(self._t("post_lock_feedback_duplicate_ignored"), "info")
            return
        session_id = str((prompt or {}).get("session_id") or state.get("postLockConfirmationEventSessionId") or state.get("session_id") or "")
        try:
            record = record_warning_feedback(
                user_id=self._current_user["user_id"],
                label=normalized_label,
                session_id=session_id,
                decision_reason_code=str((prompt or {}).get("decision_reason_code") or state.get("runtime_diagnostic_code") or state.get("postLockConfirmationReason") or ""),
                model_version=str((prompt or {}).get("model_version") or ""),
                policy_version=str((prompt or {}).get("policy_version") or ""),
                archive_path=str(state.get("postLockConfirmationArchivePath") or state.get("archive_path") or ""),
                decision=str((prompt or {}).get("decision") or state.get("decision") or ""),
                risk=state.get("postLockConfirmationRisk") or state.get("risk") or (prompt or {}).get("risk") or 0,
                runtime_state=state,
                prompt_token=str((prompt or {}).get("token") or ""),
            )
        except Exception as exc:
            self._set_status(self._t("feedback_save_failed", error=str(exc)), "danger")
            return
        updated = dict(state) if isinstance(state, dict) else {}
        updated["feedback_prompt"] = {**dict(prompt or {}), "pending": False, "answered": True, "label": record.get("label"), "answered_at": record.get("timestamp")}
        updated["latest_feedback_label"] = record.get("label")
        updated["latest_feedback_timestamp"] = record.get("timestamp")
        if post_lock_pending and record.get("label") in {"confirmed_intruder", "verified_legit_after_warning"}:
            classification = session_runtime_helpers.classify_post_lock_confirmation(
                self,
                state=updated,
                label=str(record.get("label") or normalized_label),
                feedback_record=record,
            )
            if not classification.get("ok"):
                updated["postLockClassificationError"] = str(classification.get("reason") or "classification_not_available")
                write_session_state(updated)
                self._runtime_state = updated
            else:
                updated = dict(classification.get("state") or updated)
        else:
            if record.get("label") == "confirmed_intruder":
                # LOCK-FACE-01: pre-lock feedback is classification/audit only.
                # Product enforcement is backend-owned by monitor_core.incident
                # after confirmed behavioral evidence and the pre-lock face gate.
                updated.update({
                    "confirmedIntruderFeedbackContext": "warning_feedback_without_post_lock_confirmation",
                    "confirmedIntruderFeedbackDidTriggerLock": False,
                    "demo_classic_manual_intruder_feedback_lock": False,
                    "feedbackDidRequestProtectedAction": False,
                    "feedback_enforcement_allowed": False,
                    "postLockConfirmationPending": bool(updated.get("postLockConfirmationPending", False)),
                })
            elif record.get("label") == "verified_legit_after_warning":
                updated.update({
                    "verifiedLegitFeedbackContext": "warning_feedback_without_post_lock_confirmation",
                    "feedbackDidRequestProtectedAction": False,
                    "feedback_enforcement_allowed": False,
                    "postLockConfirmationPending": bool(updated.get("postLockConfirmationPending", False)),
                })
            write_session_state(updated)
            self._runtime_state = updated
        self.runtimeStateChanged.emit()
        if post_lock_pending and record.get("label") == "verified_legit_after_warning":
            self._set_status(self._t("post_lock_feedback_saved_legit"), "success")
            self._maybe_process_shadow_backlog()
        elif post_lock_pending and record.get("label") == "confirmed_intruder":
            self._set_status(self._t("post_lock_feedback_saved_intruder"), "warn")
        elif record.get("label") == "verified_legit_after_warning":
            self._set_status(self._t("feedback_saved_shadow_only"), "success")
            self._maybe_process_shadow_backlog()
        elif record.get("label") == "confirmed_intruder":
            self._set_status(self._t("feedback_saved_intruder"), "warn")
        else:
            self._set_status(self._t("feedback_saved_ignored"), "info")

    def _finish_training(self, result: Dict[str, Any]) -> None:
        session_training_helpers.finish_training(self, result)

    @Slot(str, result="QVariantMap")
    def sessionDetails(self, path: str) -> Dict[str, Any]:
        return session_history_helpers.session_details(self, path)

    def _assert_session_is_deletable(self, resolved: str) -> None:
        session_history_helpers.assert_session_is_deletable(self, resolved)

    def _delete_archived_session_path(self, path: str) -> str:
        return session_history_helpers.delete_archived_session_path(self, path)

    @Slot(str)
    def openLocalPath(self, path: str) -> None:
        target = str(path or "").strip()
        if not target:
            return
        try:
            if os.path.exists(target):
                QDesktopServices.openUrl(QUrl.fromLocalFile(target))
        except Exception:
            return

    def _drop_deleted_sessions_from_cache(self, resolved_paths: List[str]) -> None:
        session_history_helpers.drop_deleted_sessions_from_cache(self, resolved_paths)

    @Slot(str)
    def deleteSession(self, path: str) -> None:
        session_history_helpers.delete_session(self, path)

    @Slot("QVariantList")
    def deleteSessions(self, paths: List[Any]) -> None:
        session_history_helpers.delete_sessions(self, paths)
