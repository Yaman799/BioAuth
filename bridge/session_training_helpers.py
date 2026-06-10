from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Optional

from metadata_core.auto_training_scheduler import (
    AUTO_TRAINING_FAILURE_COOLDOWN_SECONDS,
    auto_training_should_start,
    training_readiness_signature,
)
from metadata_core.auto_enrollment import is_passive_auto_enrollment_state
from metadata_core.training_attempts import (
    load_training_attempt_state,
    normalize_training_attempt_result,
    record_training_attempt,
    training_attempt_blocks_auto_retry,
)
from metadata_core.shadow_loop import (
    SHADOW_LOOP_RETRY_COOLDOWN_SECONDS,
    shadow_retraining_gate,
    trusted_sessions_signature,
)


def _facade():
    return import_module("bridge.session_mixin")


def _demo_classic_training_enabled() -> bool:
    try:
        from app_settings import demo_classic_protected_enabled

        return bool(demo_classic_protected_enabled())
    except Exception:
        return False


def _request_refresh(self, reason: str, force: bool = False) -> None:
    request = getattr(self, "requestRefresh", None)
    if callable(request):
        request(reason, force)
        return
    legacy = getattr(self, "refreshNow", None)
    if callable(legacy):
        legacy()


def coerce_training_progress_percent(value: Any) -> int:
    try:
        percent = int(round(float(value)))
    except Exception:
        percent = 0
    return max(0, min(100, percent))


def apply_training_progress_payload(self, payload: Any) -> None:
    current = dict(getattr(self, "_training_progress", {}) or {})
    incoming = dict(payload or {}) if isinstance(payload, dict) else {}
    lang = str(getattr(self, "_language", "en") or "en")
    params = dict(incoming.get("message_params") or {}) if isinstance(incoming.get("message_params"), dict) else {}
    stage_key = str(incoming.get("stage_key") or current.get("stage_key") or "")
    detail_key = str(incoming.get("detail_key") or current.get("detail_key") or "")
    headline = str(incoming.get("headline") or "")
    detail = str(incoming.get("detail") or "")
    facade = _facade()
    if not headline and stage_key:
        headline = facade.translate_string(lang, stage_key, **params)
    if not detail and detail_key:
        detail = facade.translate_string(lang, detail_key, **params)
    next_payload = {
        "percent": coerce_training_progress_percent(incoming.get("percent", current.get("percent", 0))),
        "headline": headline,
        "detail": detail,
        "stage_key": stage_key,
        "detail_key": detail_key,
        "message_params": params,
        "active": bool(incoming.get("active", getattr(self, "_training_in_progress", False))),
    }
    if next_payload == current:
        return
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        progress_payload = {
            "percent": next_payload.get("percent", 0),
            "stage_key": stage_key,
            "detail_key": detail_key,
            "message_params": params,
        }
        message_text = f"{headline} :: {detail}" if headline and detail else (headline or detail or "training progress update")
        debug("training", message_text, payload=progress_payload)
    self._training_progress = next_payload
    training_signal = getattr(self, "trainingChanged", None)
    if training_signal is not None and hasattr(training_signal, "emit"):
        training_signal.emit()


def queue_training_progress(self, *, percent: Any, stage_key: str = "", detail_key: str = "", message_params: Optional[Dict[str, Any]] = None, headline: str = "", detail: str = "", active: Optional[bool] = None) -> None:
    payload: Dict[str, Any] = {
        "percent": percent,
        "stage_key": str(stage_key or ""),
        "detail_key": str(detail_key or ""),
        "message_params": dict(message_params or {}),
        "headline": str(headline or ""),
        "detail": str(detail or ""),
    }
    if active is not None:
        payload["active"] = bool(active)
    reporter = getattr(self, "trainingProgressReported", None)
    if reporter is not None and hasattr(reporter, "emit"):
        reporter.emit(payload)
        return
    apply_training_progress_payload(self, payload)


def set_training_progress_state(self, active: bool) -> None:
    next_state = bool(active)
    changed = bool(getattr(self, "_training_in_progress", False)) != next_state
    self._training_in_progress = next_state
    current_progress = dict(getattr(self, "_training_progress", {}) or {})
    if current_progress.get("active") != next_state:
        current_progress["active"] = next_state
        self._training_progress = current_progress
        changed = True
    if changed:
        training_signal = getattr(self, "trainingChanged", None)
        if training_signal is not None and hasattr(training_signal, "emit"):
            training_signal.emit()
        controls_signal = getattr(self, "controlsChanged", None)
        if controls_signal is not None and hasattr(controls_signal, "emit"):
            controls_signal.emit()
    updater = getattr(self, "_update_refresh_timer", None)
    if callable(updater):
        updater(force=True)


def _current_auto_training_signature(self) -> str:
    user_id = ""
    try:
        user_id = str((getattr(self, "_current_user", {}) or {}).get("user_id", "") or "")
    except Exception:
        user_id = ""
    return training_readiness_signature(
        user_id=user_id,
        profile=getattr(self, "_profile", {}) if isinstance(getattr(self, "_profile", None), dict) else {},
        sessions=getattr(self, "_sessions", []) if isinstance(getattr(self, "_sessions", None), list) else [],
    )



def _poll_process_alive(process: Any) -> bool:
    if process is None:
        return False
    poll = getattr(process, "poll", None)
    if callable(poll):
        try:
            return poll() is None
        except (OSError, RuntimeError, ValueError):
            return True
    return True


def _logger_process_alive(self) -> bool:
    processes = getattr(self, "_running_processes", {})
    if not isinstance(processes, dict):
        return False
    expected_key = ""
    key_fn = getattr(self, "_logger_process_key", None)
    if callable(key_fn):
        try:
            expected_key = str(key_fn() or "")
        except (TypeError, RuntimeError, ValueError):
            expected_key = ""
    if not expected_key:
        return False
    process = processes.get(expected_key)
    return bool(_poll_process_alive(process))


def _runtime_training_guard_state(self) -> Dict[str, Any]:
    runtime = dict(getattr(self, "_runtime_state", {}) or {}) if isinstance(getattr(self, "_runtime_state", None), dict) else {}
    active_state_fn = getattr(self, "_active_state_for_current_user", None)
    if callable(active_state_fn):
        try:
            active_state = active_state_fn()
        except (OSError, RuntimeError, ValueError, TypeError):
            active_state = {}
        if isinstance(active_state, dict):
            for key in (
                "active",
                "session_kind",
                "auto_enrollment",
                "collection_source",
                "auto_enrollment_finalizing",
                "auto_enrollment_stop_requested",
                "archive_requested",
                "stop_requested",
            ):
                if key not in runtime and key in active_state:
                    runtime[key] = active_state.get(key)
    runtime["logger_process_alive"] = bool(_logger_process_alive(self) or getattr(self, "_pending_logger_start", False))
    processes = getattr(self, "_running_processes", {})
    monitor_proc = processes.get("monitor") if isinstance(processes, dict) else None
    runtime["monitor_process_alive"] = bool(_poll_process_alive(monitor_proc))
    runtime["pending_monitor_start"] = bool(getattr(self, "_pending_monitor_start", False))
    runtime["protected_session_stopping"] = bool(getattr(self, "_protected_session_stopping", False))
    runtime["pending_shadow_evidence_monitor_start"] = bool(getattr(self, "_pending_shadow_evidence_monitor_start", False))
    runtime["retry_handoff_state"] = str(getattr(self, "_retry_handoff_state", "") or "")
    runtime["retry_handoff_blockers"] = list(getattr(self, "_retry_handoff_blockers", []) or [])
    runtime["retry_handoff_last_error"] = str(getattr(self, "_retry_handoff_last_error", "") or "")
    shadow_running = getattr(self, "_shadow_evidence_monitor_running", None)
    if callable(shadow_running):
        try:
            runtime["shadow_evidence_monitor_active"] = bool(shadow_running())
        except (TypeError, RuntimeError, ValueError):
            runtime["shadow_evidence_monitor_active"] = False
    runtime["history_sync_pending"] = bool(getattr(self, "_history_sync_pending", False))
    if bool(getattr(self, "_passive_auto_enrollment_finalizing", False)):
        runtime["auto_enrollment_finalizing"] = True
    return runtime



def _current_remediation_plan(self) -> Dict[str, Any]:
    """Return backend-owned remediation plan metadata if the dashboard exposed it.

    This helper only forwards a plan to the scheduler. It does not start
    collection, train, approve production, or unlock Protected Sessions.
    """

    candidates = []
    direct = getattr(self, "_remediation_plan", None)
    if isinstance(direct, dict):
        candidates.append(direct)
    profile = getattr(self, "_profile", None)
    if isinstance(profile, dict):
        candidates.append(profile)
        for key in (
            "model_readiness_state",
            "modelReadinessState",
            "production_approval_state",
            "productionApprovalState",
            "remediation_state",
            "remediationState",
        ):
            nested = profile.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)
    for item in candidates:
        for key in ("remediation_plan", "remediationPlan", "production_remediation_plan", "productionRemediationPlan"):
            value = item.get(key)
            if isinstance(value, dict):
                return dict(value)
        if str(item.get("failure_kind") or item.get("action") or item.get("retry_eligibility") or "").strip():
            return dict(item)
    return {}


def _current_production_evidence_summary(self) -> Dict[str, Any]:
    """Return the latest backend-owned aggregate ProductionEvidenceSummary.

    This is intentionally aggregate-only. It forwards the same safe ledger-backed
    counters used by the dashboard to the auto-training scheduler so retry
    eligibility does not fall back to stale session-only remediation progress.
    """

    profile = getattr(self, "_profile", None)
    if not isinstance(profile, dict):
        return {}
    candidates = [profile]
    for key in ("production_approval_state", "productionApprovalState", "model_readiness_state", "modelReadinessState"):
        nested = profile.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    for item in candidates:
        for key in (
            "production_evidence_summary",
            "productionEvidenceSummary",
            "production_evidence_state",
            "productionEvidenceState",
            "evidence_gate_state",
            "evidenceGateState",
        ):
            value = item.get(key)
            if isinstance(value, dict):
                return dict(value)
    return {}


def _evaluation_active(self) -> bool:
    return bool(
        getattr(self, "_evaluation_in_progress", False)
        or getattr(self, "_candidate_evaluation_active", False)
        or getattr(self, "_model_evaluation_active", False)
    )


def _current_user_id(self) -> str:
    return str((getattr(self, "_current_user", {}) or {}).get("user_id", "") or "")


def _sync_training_attempt_state(self) -> Dict[str, Any]:
    user_id = _current_user_id(self)
    if not user_id:
        return {}
    state = load_training_attempt_state(user_id)
    if state:
        self._last_attempted_training_signature = str(state.get("last_attempted_training_signature") or getattr(self, "_last_attempted_training_signature", "") or "")
        self._last_attempted_training_result = str(state.get("last_attempted_training_result") or getattr(self, "_last_attempted_training_result", "") or "")
        self._last_attempted_training_status = str(state.get("last_attempted_training_status") or getattr(self, "_last_attempted_training_status", "") or "")
        self._last_attempted_training_rejection_reason = str(state.get("last_attempted_training_rejection_reason") or getattr(self, "_last_attempted_training_rejection_reason", "") or "")
        self._last_successful_training_signature = str(state.get("last_successful_training_signature") or getattr(self, "_last_successful_training_signature", "") or "")
        self._auto_training_last_signature = str(state.get("last_auto_training_signature") or getattr(self, "_auto_training_last_signature", "") or "")
    return state


def _training_start_block_reason(self) -> str:
    runtime = _runtime_training_guard_state(self)
    runtime_session_kind = str(runtime.get("session_kind") or runtime.get("runtime_mode") or "").strip().lower()
    shadow_runtime_state = runtime_session_kind == "shadow_evidence" or bool(runtime.get("pending_shadow_evidence_monitor_start"))
    if shadow_runtime_state:
        shadow_running_fn = getattr(self, "_is_shadow_runtime_process_running", None)
        shadow_running = False
        if callable(shadow_running_fn):
            try:
                shadow_running = bool(shadow_running_fn())
            except (TypeError, RuntimeError, ValueError):
                shadow_running = False
        if not shadow_running:
            cleanup = getattr(self, "_clear_stale_shadow_state_if_safe", None)
            if callable(cleanup):
                try:
                    cleanup(runtime)
                except (TypeError, RuntimeError, ValueError):
                    pass
            runtime["active"] = False
            runtime["session_kind"] = ""
            runtime["runtime_mode"] = ""
            runtime["pending_shadow_evidence_monitor_start"] = False
        else:
            return "active_session_running"
    if bool(getattr(self, "_training_in_progress", False)):
        return "training_active"
    if is_passive_auto_enrollment_state(runtime) and bool(runtime.get("active")):
        return "passive_auto_enrollment_active"
    if bool(runtime.get("auto_enrollment_finalizing") or runtime.get("auto_enrollment_stop_requested") or runtime.get("history_sync_pending") or runtime.get("archive_requested") or runtime.get("archive_pending")):
        return "session_archive_pending"
    if bool(runtime.get("logger_process_alive")):
        return "logger_process_active"
    if bool(runtime.get("monitor_process_alive")):
        return "monitor_process_active"
    if bool(runtime.get("pending_monitor_start")):
        return "pending_monitor_start"
    if bool(runtime.get("protected_session_stopping")):
        return "protected_session_stopping"
    flow_fn = getattr(self, "_normal_user_session_flow", None)
    if not callable(flow_fn):
        flow_fn = getattr(self, "_session_flow", None)
    flow = "idle"
    if callable(flow_fn):
        try:
            flow = str(flow_fn() or "idle")
        except (TypeError, RuntimeError, ValueError):
            flow = "unknown"
    if flow != "idle":
        return "session_not_idle"
    if bool(runtime.get("active")):
        return "runtime_session_active"
    return ""


def _candidate_status_from_profile(profile: Dict[str, Any]) -> str:
    candidates = [
        profile.get("candidate_model_status"),
        profile.get("approval_status"),
        profile.get("model_status"),
        profile.get("modelStatus"),
    ]
    for key in ("production_approval_state", "productionApprovalState", "model_readiness_state", "modelReadinessState"):
        nested = profile.get(key)
        if isinstance(nested, dict):
            candidates.extend([
                nested.get("candidate_status"),
                nested.get("candidateStatus"),
                nested.get("modelStatus"),
                nested.get("model_status"),
                nested.get("approval_status"),
            ])
    for value in candidates:
        text = str(value or "").strip().lower()
        if text:
            return text
    return ""


def _developer_effective_training_override(self, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Return the developer-only training gate override state.

    This override only affects Train/Calibrate eligibility.  It does not turn
    Hybrid Direct output, shadow evidence, or protected runtime windows into
    owner-positive training samples, and it never mutates production metadata.
    """

    effective_fn = getattr(self, "_effective_production_ready", None)
    simulation_fn = getattr(self, "_developer_production_ready_simulation_active", None)
    effective_state_fn = getattr(self, "_effective_production_ready_state", None)
    effective = False
    simulation = False
    effective_state: Dict[str, Any] = {}
    if callable(effective_state_fn):
        try:
            raw_state = effective_state_fn()
            effective_state = dict(raw_state or {}) if isinstance(raw_state, dict) else {}
        except Exception:
            effective_state = {}
    if callable(effective_fn):
        try:
            effective = bool(effective_fn())
        except Exception:
            effective = False
    else:
        effective = bool(effective_state.get("effectiveProductionReady") or effective_state.get("effective_production_ready"))
    if callable(simulation_fn):
        try:
            simulation = bool(simulation_fn())
        except Exception:
            simulation = False
    else:
        simulation = bool(effective_state.get("devProductionReadySimulation") or effective_state.get("dev_production_ready_simulation"))
    shadow_paused = bool(
        getattr(self, "_shadow_automation_paused", False)
        or effective_state.get("shadowPaused")
        or effective_state.get("shadow_paused")
    )
    candidate_status = _candidate_status_from_profile(profile)
    candidate_ok = candidate_status in {"approved_for_shadow", "shadow_validation", "approved_for_production", "production_ready"}
    allowed = bool(effective and simulation and shadow_paused and candidate_ok)
    reason = "developer_effective_readiness_training_gate" if allowed else "developer_effective_readiness_not_available"
    if not effective:
        reason = "effective_production_ready_false"
    elif not simulation:
        reason = "developer_simulation_inactive"
    elif not shadow_paused:
        reason = "shadow_not_paused"
    elif not candidate_ok:
        reason = "no_shadow_approved_candidate"
    return {
        "allowed": allowed,
        "reason_code": reason,
        "effective_production_ready": effective,
        "developer_simulation": simulation,
        "shadow_paused": shadow_paused,
        "candidate_status": candidate_status,
        "training_sample_source": "normal_enrollment_archives_only",
        "reason_codes": [reason],
    }


def latest_hybrid_direct_test_summary(self) -> Dict[str, Any]:
    try:
        runtime_helpers = import_module("bridge.session_runtime_helpers")
        result = runtime_helpers.validate_hybrid_direct_test_evidence(self)
    except Exception:
        return {
            "passed": True,
            "reason_code": "hybrid_test_not_required",
            "reason_codes": ["hybrid_test_not_required", "hybrid_direct_removed_from_commercial_flow"],
            "hybrid_removed_from_commercial_flow": True,
            "hybrid_required_for_training": False,
            "training_sample_source": "normal_enrollment_archives_only",
            "shadow_evidence_training_allowed": False,
            "hybrid_report_training_allowed": False,
            "protected_sessions_unlock_allowed": False,
            "production_promotion_allowed": False,
        }
    summary = result.get("summary") if isinstance(result, dict) else {}
    if not isinstance(summary, dict):
        summary = {}
    summary = dict(summary)
    summary.setdefault("passed", bool((result or {}).get("ok")) if isinstance(result, dict) else False)
    summary.setdefault("reason_code", "hybrid_test_not_required" if summary.get("passed") else str((result or {}).get("reason_code") or "hybrid_test_not_required"))
    summary.setdefault("training_sample_source", "normal_enrollment_archives_only")
    summary.setdefault("shadow_evidence_training_allowed", False)
    summary.setdefault("hybrid_report_training_allowed", False)
    summary.setdefault("protected_sessions_unlock_allowed", False)
    summary.setdefault("production_promotion_allowed", False)
    return summary


def training_gate_status(self) -> Dict[str, Any]:
    """Backend-owned Train/Calibrate gate for manual and auto training.

    The commercial gate requires normal enrollment readiness only.

    Hybrid Direct Test was removed from the commercial training flow in
    Commercial-Core-22A and remains as a legacy compatibility surface only.
    The gate still forbids shadow evidence, protected runtime windows, or
    confirmed-intruder evidence from becoming owner-positive training samples.
    """

    if not getattr(self, "_current_user", None):
        return {"can_train": False, "reason_code": "no_authenticated_user", "hybrid": latest_hybrid_direct_test_summary(self)}
    guard_reason = _training_start_block_reason(self)
    if guard_reason:
        if guard_reason in {"session_not_idle", "runtime_session_active"}:
            code = "active_session_running"
        elif guard_reason == "logger_process_active":
            code = "active_session_running"
        elif guard_reason == "passive_auto_enrollment_active":
            code = "active_session_running"
        else:
            code = guard_reason
        return {"can_train": False, "reason_code": code, "runtime_reason_code": guard_reason, "hybrid": latest_hybrid_direct_test_summary(self)}
    profile = getattr(self, "_profile", {}) if isinstance(getattr(self, "_profile", None), dict) else {}
    if not profile:
        try:
            profile = _facade().user_profile_status((getattr(self, "_current_user", {}) or {}).get("user_id", ""))
        except Exception:
            profile = {}
    if not bool(profile.get("training_can_start")):
        raw_reason = str(profile.get("training_block_reason") or "")
        return {"can_train": False, "reason_code": raw_reason or "missing_enrollment_data", "profile_reason_code": raw_reason, "hybrid": latest_hybrid_direct_test_summary(self)}
    hybrid = latest_hybrid_direct_test_summary(self)
    if _demo_classic_training_enabled():
        hybrid = dict(hybrid or {})
        hybrid.setdefault("passed", False)
        hybrid.setdefault("reason_code", str(hybrid.get("reason_code") or "hybrid_test_missing"))
        hybrid["demo_classic_training_gate"] = True
        return {
            "can_train": True,
            "reason_code": "",
            "reason_codes": ["demo_classic_training_gate"],
            "hybrid": hybrid,
            "demo_classic_protected": True,
            "production_approval_bypassed_for_demo": True,
            "training_sample_source": "normal_enrollment_archives_only",
            "status_label": "Train/Calibrate is available.",
        }
    if not bool(hybrid.get("passed")):
        developer_override = _developer_effective_training_override(self, profile)
        if bool(developer_override.get("allowed")):
            hybrid = dict(hybrid)
            hybrid.setdefault("passed", False)
            hybrid.setdefault("reason_code", str(hybrid.get("reason_code") or "hybrid_test_missing"))
            hybrid["developer_effective_readiness_used"] = True
            hybrid["developer_effective_readiness_reason"] = str(developer_override.get("reason_code") or "")
            return {
                "can_train": True,
                "reason_code": "",
                "reason_codes": ["developer_effective_readiness_training_gate"],
                "hybrid": hybrid,
                "developer_effective_readiness_used": True,
                "developer_effective_readiness": developer_override,
                "training_sample_source": "normal_enrollment_archives_only",
                "status_label": "Train/Calibrate is available through Developer Mode effective readiness.",
            }
        return {
            "can_train": False,
            "reason_code": str(hybrid.get("reason_code") or "hybrid_test_missing"),
            "reason_codes": [str(hybrid.get("reason_code") or "hybrid_test_missing")],
            "hybrid": hybrid,
            "developer_effective_readiness": developer_override,
        }
    return {"can_train": True, "reason_code": "", "reason_codes": ["hybrid_test_not_required"], "hybrid": hybrid, "training_sample_source": "normal_enrollment_archives_only", "status_label": "Train/Calibrate is available."}


def _set_training_start_block_status(self, reason: str, *, auto_training: bool = False) -> None:
    if reason in {"passive_auto_enrollment_active", "logger_process_active"}:
        if not bool(auto_training):
            stopper = getattr(self, "_stop_passive_auto_enrollment_if_active", None)
            if callable(stopper):
                stopper(reason="manual_training_requested")
        self._set_status(self._t("training_blocked_passive_enrollment_active"), "warn")
        return
    if reason in {"session_archive_pending", "passive_auto_enrollment_finalizing"}:
        self._set_status(self._t("training_blocked_archive_pending"), "info")
        return
    if reason == "training_active":
        self._set_status(self._t("training_running"), "warn")
        return
    if reason in {"missing_enrollment_data", "need_more_trusted_sessions"}:
        self._set_status(self._t("training_need_more_sessions", minimum=_facade().MIN_ENROLLMENT_SESSIONS), "warn")
        return
    if reason == "need_higher_quality_sessions":
        self._set_status(self._t("training_need_higher_quality_sessions"), "warn")
        return
    if reason in {"hybrid_test_missing", "hybrid_test_failed", "hybrid_test_stale", "hybrid_test_wrong_user", "hybrid_test_malformed", "active_session_running", "shadow_collection_active", "model_runtime_unavailable", "no_authenticated_user", "monitor_process_active", "pending_monitor_start", "protected_session_stopping"}:
        self._set_status(self._t(reason), "warn")
        return
    self._set_status(self._t("training_busy_session"), "warn")


def _training_rejection_reason(result: Dict[str, Any]) -> str:
    for key in (
        "offline_approval_rejection_reason",
        "approval_rejection_reason",
        "approval_reason",
        "rejection_reason",
        "message_key",
        "message",
        "error",
    ):
        value = str((result or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def _record_finished_training_attempt(self, *, result: Dict[str, Any], signature: str, source: str, attempt_result: str, model_status: str) -> Dict[str, Any]:
    user_id = _current_user_id(self)
    if not user_id or not signature:
        return {}
    state = record_training_attempt(
        user_id=user_id,
        signature=signature,
        result=attempt_result,
        status=model_status or attempt_result,
        rejection_reason=_training_rejection_reason(result),
        source=source,
        attempted_at=_facade().time.time(),
    )
    self._last_attempted_training_signature = str(state.get("last_attempted_training_signature") or "")
    self._last_attempted_training_result = str(state.get("last_attempted_training_result") or "")
    self._last_attempted_training_status = str(state.get("last_attempted_training_status") or "")
    self._last_attempted_training_rejection_reason = str(state.get("last_attempted_training_rejection_reason") or "")
    self._last_successful_training_signature = str(state.get("last_successful_training_signature") or getattr(self, "_last_successful_training_signature", "") or "")
    self._auto_training_last_signature = str(state.get("last_auto_training_signature") or getattr(self, "_auto_training_last_signature", "") or "")
    return state

def _accepted_session_count(self) -> int:
    profile = getattr(self, "_profile", {}) if isinstance(getattr(self, "_profile", None), dict) else {}
    try:
        return max(0, int(profile.get("session_count", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _reset_shadow_loop_tracking(self) -> None:
    self._shadow_loop_baseline_signature = ""
    self._shadow_loop_baseline_accepted_count = 0
    self._shadow_loop_cooldown_until = 0.0
    self._shadow_loop_repeated_shadow_count = 0
    self._shadow_loop_last_status = "inactive"


def maybe_start_auto_training(self) -> bool:
    """Start one safe background training job using the existing training path."""

    marker = getattr(self, "_maybe_mark_shadow_evidence_stopped_for_retry", None)
    if callable(marker):
        marker()
    if not getattr(self, "_current_user", None):
        return False
    flow = "idle"
    flow_fn = getattr(self, "_session_flow", None)
    if callable(flow_fn):
        try:
            flow = str(flow_fn() or "idle")
        except (TypeError, RuntimeError, ValueError):
            flow = "unknown"
    try:
        consent_satisfied = bool(self._privacy_consent_satisfied_for_auto_enrollment())
    except (TypeError, RuntimeError, ValueError, AttributeError):
        consent_satisfied = False
    persisted_attempt = _sync_training_attempt_state(self)
    runtime_guard = _runtime_training_guard_state(self)
    last_successful_signature = str(
        getattr(self, "_last_successful_training_signature", "")
        or persisted_attempt.get("last_successful_training_signature")
        or ""
    )
    if not last_successful_signature:
        last_successful_signature = str(getattr(self, "_auto_training_last_signature", "") or "")
    allowed, reason, signature = auto_training_should_start(
        settings=getattr(self, "_app_settings", {}) if isinstance(getattr(self, "_app_settings", None), dict) else {},
        profile=getattr(self, "_profile", {}) if isinstance(getattr(self, "_profile", None), dict) else {},
        runtime_state=runtime_guard,
        sessions=getattr(self, "_sessions", []) if isinstance(getattr(self, "_sessions", None), list) else [],
        user_id=_current_user_id(self),
        consent_satisfied=consent_satisfied,
        authenticated=bool(getattr(self, "_current_user", None)),
        training_active=bool(getattr(self, "_training_in_progress", False)),
        session_flow=flow,
        evaluation_active=_evaluation_active(self),
        app_locked=bool(getattr(self, "_app_passcode_locked", False)),
        cooldown_until=float(getattr(self, "_auto_training_cooldown_until", 0.0) or 0.0),
        last_completed_signature=last_successful_signature,
        last_attempted_signature=str(getattr(self, "_last_attempted_training_signature", "") or persisted_attempt.get("last_attempted_training_signature") or ""),
        last_attempted_training_result=str(getattr(self, "_last_attempted_training_result", "") or persisted_attempt.get("last_attempted_training_result") or ""),
        last_attempted_training_status=str(getattr(self, "_last_attempted_training_status", "") or persisted_attempt.get("last_attempted_training_status") or ""),
        remediation_plan=_current_remediation_plan(self),
        production_evidence_summary=_current_production_evidence_summary(self),
    )
    self._last_auto_training_decision_reason = str(reason or "")
    if not allowed:
        if str(reason or "") == "shadow_evidence_handoff_required":
            handoff = getattr(self, "_request_shadow_evidence_stop_for_retry", None)
            if callable(handoff):
                if handoff(reason="remediation_evidence_complete"):
                    self._auto_training_last_status = "blocked"
                    self._auto_training_last_reason = "shadow_evidence_settling_for_retry"
                    self._last_auto_training_decision_reason = "shadow_evidence_handoff_in_progress"
                else:
                    self._auto_training_last_status = "blocked"
                    self._auto_training_last_reason = "shadow_evidence_handoff_failed"
                    self._last_auto_training_decision_reason = str(getattr(self, "_retry_handoff_last_error", "") or "shadow_evidence_handoff_failed")
        return False
    profile_payload = getattr(self, "_profile", {}) if isinstance(getattr(self, "_profile", None), dict) else {}
    production_payload = profile_payload.get("production_approval_state") if isinstance(profile_payload, dict) else {}
    readiness_payload = profile_payload.get("model_readiness_state") if isinstance(profile_payload, dict) else {}
    shadow_allowed, shadow_reason, shadow_state = shadow_retraining_gate(
        production_approval=production_payload if isinstance(production_payload, dict) else {},
        model_readiness=readiness_payload if isinstance(readiness_payload, dict) else {},
        profile=profile_payload,
        sessions=getattr(self, "_sessions", []) if isinstance(getattr(self, "_sessions", None), list) else [],
        baseline_signature=str(getattr(self, "_shadow_loop_baseline_signature", "") or ""),
        baseline_accepted_count=int(getattr(self, "_shadow_loop_baseline_accepted_count", 0) or 0),
        cooldown_until=float(getattr(self, "_shadow_loop_cooldown_until", 0.0) or 0.0),
        repeated_shadow_count=int(getattr(self, "_shadow_loop_repeated_shadow_count", 0) or 0),
    )
    self._shadow_loop_last_status = str(shadow_reason or "")
    if not shadow_allowed:
        self._last_auto_training_decision_reason = str(shadow_reason or "")
        signal = getattr(self, "modelReadinessChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        return False
    self._auto_training_active_signature = signature
    started = train_profile(self, auto_training=True)
    if not started:
        self._auto_training_active_signature = ""
    return started


def train_profile(self, *, auto_training: bool = False) -> bool:
    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("action", "trainProfile requested", payload={"user": str((self._current_user or {}).get("user_id", "") or ""), "flow": self._session_flow()})
    if not self._current_user:
        return False
    guard_reason = _training_start_block_reason(self)
    if guard_reason:
        _set_training_start_block_status(self, guard_reason, auto_training=auto_training)
        if bool(auto_training):
            self._auto_training_last_status = "blocked"
            self._auto_training_last_reason = guard_reason
            self._last_auto_training_decision_reason = guard_reason
        return False
    gate = training_gate_status(self)
    if not bool(gate.get("can_train")):
        _set_training_start_block_status(self, str(gate.get("reason_code") or "missing_enrollment_data"), auto_training=auto_training)
        if bool(auto_training):
            self._auto_training_last_status = "blocked"
            self._auto_training_last_reason = str(gate.get("reason_code") or "training_gate_blocked")
            self._last_auto_training_decision_reason = str(gate.get("reason_code") or "training_gate_blocked")
        return False
    profile = self._profile if isinstance(getattr(self, "_profile", None), dict) and self._profile else facade.user_profile_status(self._current_user["user_id"])
    if self._training_in_progress:
        self._set_status(self._t("training_running"), "warn")
        return False
    self._last_training_failed = False
    self._last_training_failure_message = ""
    self._last_training_failure_tone = "danger"
    self._active_training_source = "auto" if auto_training else "manual"
    if auto_training:
        self._auto_training_job_active = True
        if not str(getattr(self, "_auto_training_active_signature", "") or ""):
            self._auto_training_active_signature = _current_auto_training_signature(self)
        self._auto_training_last_status = "running"
        self._auto_training_last_reason = "background_training_started"
        self._last_auto_training_decision_reason = "started"
        signal = getattr(self, "autoEnrollmentChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        readiness_signal = getattr(self, "modelReadinessChanged", None)
        if readiness_signal is not None and hasattr(readiness_signal, "emit"):
            readiness_signal.emit()
    self._set_training_progress_state(True)
    self._queue_training_progress(percent=2, stage_key="training_stage_preparing", detail_key="training_detail_scanning_sessions", message_params={"current": 0, "total": 0}, active=True)
    self._set_status("Training your protection model in the background." if auto_training else self._t("training_wait"), "info")
    user_id = self._current_user["user_id"]

    def worker() -> None:
        debug_worker = getattr(self, "_debug_trace", None)
        if callable(debug_worker):
            debug_worker("worker", "Training worker started", payload={"user": user_id})
        try:
            result = facade.train_user_model(
                user_id,
                min_sessions=facade.MIN_ENROLLMENT_SESSIONS,
                max_enrollment_sessions=facade.MAX_ENROLLMENT_SESSIONS,
                progress_callback=lambda payload: self._queue_training_progress(**dict(payload or {})),
            )
        except Exception as exc:
            if callable(debug_worker):
                debug_worker("worker", "Training worker crashed", payload={"user": user_id, "error": str(exc)}, level="error")
            result = {"ok": False, "message": f"Training crashed: {exc}", "message_key": "training_failed_before_publish", "error": str(exc)}
        else:
            if callable(debug_worker):
                debug_worker("worker", "Training worker finished", payload={"user": user_id, "ok": bool(result.get("ok"))})
        if isinstance(result, dict):
            result = dict(result)
            result.setdefault("training_source", "auto" if auto_training else "manual")
            if auto_training:
                result.setdefault("auto_training_signature", str(getattr(self, "_auto_training_active_signature", "") or ""))
        self.trainingFinished.emit(result)

    facade.threading.Thread(target=worker, daemon=True).start()
    return True


def _candidate_artifact_status_suffix(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict) or not result.get("ok"):
        return ""
    counts = result.get("status_counts") if isinstance(result.get("status_counts"), dict) else {}
    try:
        built = int(counts.get("trained", len(result.get("candidate_artifacts_built") or [])) or 0)
    except (TypeError, ValueError):
        built = 0
    try:
        skipped = int(counts.get("skipped", len(result.get("candidate_artifacts_skipped") or {})) or 0)
    except (TypeError, ValueError):
        skipped = 0
    try:
        failed = int(counts.get("failed", len(result.get("candidate_artifacts_failed") or {})) or 0)
    except (TypeError, ValueError):
        failed = 0
    if built == 0 and skipped == 0 and failed == 0:
        return ""
    return f" Candidate artifacts built: {built}; skipped: {skipped}; failed: {failed}."


def finish_training(self, result: Dict[str, Any]) -> None:
    facade = _facade()
    result = dict(result or {}) if isinstance(result, dict) else {}
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("training", "Training finished event received", payload=dict(result or {}), level="info" if result.get("ok") else "warn")
    training_source = str(result.get("training_source") or getattr(self, "_active_training_source", "") or "").strip().lower()
    auto_source = training_source == "auto"
    active_signature = str(result.get("auto_training_signature") or getattr(self, "_auto_training_active_signature", "") or "")
    if not active_signature:
        active_signature = _current_auto_training_signature(self)
    status_message = facade.translate_backend_result(getattr(self, "_language", "en"), result, default_key="training_wait")
    model_status = str(result.get("model_status") or "").strip().lower()
    attempt_result = normalize_training_attempt_result(ok=bool(result.get("ok")), model_status=model_status, message_key=result.get("message_key"))
    show_ready_dialog = False
    if result.get("ok") and _demo_classic_training_enabled():
        try:
            from metadata_core.demo_classic_runtime_activation import (
                activate_existing_candidate_runtime_for_demo,
            )

            activation = activate_existing_candidate_runtime_for_demo(
                (getattr(self, "_current_user", {}) or {}).get("user_id", "")
            )
            result["demo_classic_runtime_activation"] = activation
            if callable(debug):
                debug(
                    "training",
                    "demo_classic_runtime_activation_after_training",
                    payload={
                        "ok": bool(activation.get("ok")),
                        "activated": bool(activation.get("activated")),
                        "reason": str(activation.get("reason") or ""),
                        "active_runtime_pointer_path": str(activation.get("active_runtime_pointer_path") or ""),
                        "runtime_publish_source": str(activation.get("runtime_publish_source") or ""),
                        "demo_rejected_candidate_override": bool(activation.get("demo_rejected_candidate_override")),
                    },
                    level="info" if activation.get("ok") else "warn",
                )
        except Exception as exc:
            if callable(debug):
                debug(
                    "training",
                    "demo_classic_runtime_activation_after_training_failed",
                    payload={"error": str(exc)},
                    level="error",
                )
    if result.get("ok"):
        if model_status == "approved_for_production":
            tone = "success"
            status_message = self._t("training_finished_production_ready")
            progress_detail_key = "training_detail_production_approved"
            show_ready_dialog = True
        elif model_status == "approved_for_shadow":
            tone = "warn"
            status_message = self._t("training_finished_shadow_only")
            progress_detail_key = "training_detail_shadow_validation_pending"
        elif model_status == "rejected":
            tone = "warn"
            status_message = self._t("training_finished_rejected")
            progress_detail_key = "training_detail_offline_approval_rejected"
        else:
            tone = "info"
            status_message = self._t("training_finished_pending_approval")
            progress_detail_key = "training_detail_approval_pending"
        self._queue_training_progress(percent=100, stage_key="training_stage_complete", detail_key=progress_detail_key, active=False)
        self._last_training_failed = False
        self._last_training_failure_message = ""
        self._last_training_failure_tone = "danger"
    elif str(result.get("message_key") or "") in {"training_need_more_sessions", "training_need_higher_quality_sessions"}:
        tone = "warn"
        self._last_training_failed = False
        self._last_training_failure_message = ""
        self._last_training_failure_tone = tone
        self._queue_training_progress(percent=0, stage_key="training_stage_failed", detail_key="training_detail_failed", active=False)
    else:
        tone = "danger"
        self._last_training_failed = True
        self._last_training_failure_message = status_message
        self._last_training_failure_tone = tone
        self._queue_training_progress(percent=0, stage_key="training_stage_failed", detail_key="training_detail_failed", active=False)

    if active_signature:
        _record_finished_training_attempt(
            self,
            result=result,
            signature=active_signature,
            source=training_source or "manual",
            attempt_result=attempt_result,
            model_status=model_status or attempt_result,
        )

    if auto_source:
        self._auto_training_last_status = model_status or attempt_result or ("completed" if result.get("ok") else "failed")
        self._auto_training_last_reason = str(result.get("message_key") or result.get("error") or attempt_result or "completed")
        if result.get("ok"):
            self._auto_training_cooldown_until = 0.0
            if model_status == "approved_for_production":
                self._last_successful_training_signature = active_signature
                self._last_auto_training_decision_reason = "already_trained_for_current_data"
            elif training_attempt_blocks_auto_retry(attempt_result, model_status):
                self._last_auto_training_decision_reason = "already_attempted_current_training_data"
            else:
                self._last_auto_training_decision_reason = "completed"
        else:
            self._auto_training_cooldown_until = facade.time.time() + AUTO_TRAINING_FAILURE_COOLDOWN_SECONDS
            self._last_auto_training_decision_reason = "already_attempted_current_training_data" if training_attempt_blocks_auto_retry(attempt_result, model_status) else "cooldown_active"
        self._auto_training_job_active = False
        self._auto_training_active_signature = ""
    elif result.get("ok") and model_status == "approved_for_production":
        # A successful manual production-approved training run covers the current data snapshot.
        self._last_successful_training_signature = active_signature
        self._last_auto_training_decision_reason = "already_trained_for_current_data"
    elif training_attempt_blocks_auto_retry(attempt_result, model_status):
        self._last_auto_training_decision_reason = "already_attempted_current_training_data"

    if result.get("ok") and model_status == "approved_for_shadow":
        self._shadow_loop_baseline_signature = trusted_sessions_signature(getattr(self, "_sessions", []) if isinstance(getattr(self, "_sessions", None), list) else [])
        self._shadow_loop_baseline_accepted_count = _accepted_session_count(self)
        self._shadow_loop_cooldown_until = facade.time.time() + SHADOW_LOOP_RETRY_COOLDOWN_SECONDS
        self._shadow_loop_repeated_shadow_count = int(getattr(self, "_shadow_loop_repeated_shadow_count", 0) or 0) + 1
        self._shadow_loop_last_status = "approved_for_shadow_collecting"
    elif result.get("ok") and model_status == "approved_for_production":
        _reset_shadow_loop_tracking(self)
    self._active_training_source = ""
    self._set_training_progress_state(False)
    status_message = f"{status_message}{_candidate_artifact_status_suffix(result)}"
    self._set_status(status_message, tone)
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    _request_refresh(self, "training:finished", False)
    auto_signal = getattr(self, "autoEnrollmentChanged", None)
    if auto_signal is not None and hasattr(auto_signal, "emit"):
        auto_signal.emit()
    readiness_signal = getattr(self, "modelReadinessChanged", None)
    if readiness_signal is not None and hasattr(readiness_signal, "emit"):
        readiness_signal.emit()
    if show_ready_dialog:
        self.dialogMessage.emit(self._t("profile_ready_title"), self._t("profile_ready_msg"), "info")
