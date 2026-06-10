"""Backend-owned autonomous readiness loop state coordinator.

This module is deliberately side-effect-free. It coordinates existing BioAuth
helpers by exposing a conservative state and one suggested next backend action;
it never promotes models, lowers gates, or unlocks Protected Sessions.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _setting_enabled(settings: Mapping[str, Any], *keys: str) -> bool:
    for key in keys:
        value = settings.get(key)
        if isinstance(value, bool):
            return value
        if str(value or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _safe_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value)]


def _remediation_complete(remediation_state: Mapping[str, Any]) -> bool:
    if bool(remediation_state.get("retry_allowed") or remediation_state.get("retryAllowed")):
        return True
    required = _as_dict(remediation_state.get("required_counts") or remediation_state.get("requiredCounts") or remediation_state.get("required_new_evidence"))
    current = _as_dict(remediation_state.get("current_counts") or remediation_state.get("currentCounts") or remediation_state.get("current_new_evidence"))
    if not required:
        return False
    for key, needed in required.items():
        try:
            n = int(needed or 0)
            c = int(current.get(key, 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        if c < n:
            return False
    return True


def _active_runtime_blockers(*, session_flow: str, runtime_state: Mapping[str, Any], training_active: bool, evaluation_active: bool) -> list[str]:
    blockers: list[str] = []
    flow = str(session_flow or runtime_state.get("flow") or "idle")
    kind = str(runtime_state.get("session_kind") or runtime_state.get("sessionKind") or runtime_state.get("runtime_mode") or "").lower()
    if training_active:
        blockers.append("training_active")
    if evaluation_active:
        blockers.append("evaluation_active")
    if "passive" in flow or "enrollment_active" == flow or kind == "passive_auto_enrollment":
        blockers.append("passive_collection_active")
    if "protected" in flow or kind == "protected":
        blockers.append("protected_session_active")
    return blockers


def build_autonomous_readiness_loop_state(
    *,
    settings: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    runtime_state: Mapping[str, Any] | None,
    sessions: Sequence[Mapping[str, Any]] | None = None,
    consent_satisfied: bool = False,
    authenticated: bool = False,
    training_active: bool = False,
    evaluation_active: bool = False,
    session_flow: str = "idle",
    remediation_state: Mapping[str, Any] | None = None,
    production_approval: Mapping[str, Any] | None = None,
    auto_training_last_reason: str = "",
) -> Dict[str, Any]:
    settings = _as_dict(settings)
    profile = _as_dict(profile)
    runtime_state = _as_dict(runtime_state)
    remediation_state = _as_dict(remediation_state)
    production_approval = _as_dict(production_approval)
    sessions = list(sessions or [])
    independent_shadow_evidence_enabled = _setting_enabled(
        settings,
        "enable_independent_shadow_evidence_monitor",
        "independent_shadow_evidence_monitor_enabled",
        "developer_independent_shadow_evidence_monitor",
    )

    blockers: list[str] = []
    state = "waiting_for_sign_in"
    action = "none"

    if not authenticated:
        blockers.append("not_authenticated")
    elif not consent_satisfied:
        state = "waiting_for_consent"
    elif not bool(settings.get("smart_auto_enrollment_enabled", False)):
        state = "blocked_by_smart_collection_disabled"
        blockers.append("smart_collection_disabled")
    elif not bool(settings.get("auto_train_when_ready_enabled", False)):
        state = "blocked_by_auto_training_disabled"
        blockers.append("auto_training_disabled")
    else:
        runtime_blockers = _active_runtime_blockers(
            session_flow=session_flow,
            runtime_state=runtime_state,
            training_active=training_active,
            evaluation_active=evaluation_active,
        )
        model_status = str(production_approval.get("modelStatus") or production_approval.get("candidate_status") or profile.get("candidate_model_status") or "").lower()
        evidence = _as_dict(production_approval.get("production_evidence_summary") or production_approval.get("productionEvidenceSummary"))
        evidence_status = str(evidence.get("status") or production_approval.get("productionEvidenceStatus") or "").lower()
        promotion_effect = str(evidence.get("promotion_effect") or production_approval.get("productionEvidencePromotionEffect") or "").lower()
        reason_codes = set(_safe_list(evidence.get("reason_codes") or production_approval.get("productionEvidenceReasonCodes")))
        protected_available = bool(production_approval.get("protectedSessionsAvailable") or production_approval.get("protected_sessions_available"))
        if protected_available:
            state = "protected_sessions_ready"
        elif training_active:
            state = "training_in_progress"
            blockers.append("training_active")
        elif evaluation_active:
            state = "evaluating_candidate"
            blockers.append("evaluation_active")
        elif any(code in reason_codes for code in {"runtime_schema_mismatch", "candidate_digest_mismatch"}):
            state = "blocked_non_retryable_runtime_fix_required"
            blockers.append("runtime_or_artifact_fix_required")
        elif "confirmed_intruder_low_risk" in reason_codes:
            state = "blocked_manual_review_required"
            blockers.append("confirmed_intruder_low_risk")
        elif model_status == "approved_for_shadow" and evidence_status in {"partial", "failed", "fail"} and promotion_effect == "shadow_only":
            if _remediation_complete(remediation_state):
                if "shadow_evidence" in str(session_flow).lower() or str(runtime_state.get("session_kind") or "").lower() == "shadow_evidence":
                    state = "retry_handoff_pending"
                    action = "request_retry_handoff"
                    blockers.append("shadow_evidence_handoff_required")
                elif str(auto_training_last_reason or "") in {"duplicate_signature", "same_signature", "signature_unchanged", "retry_signature_unchanged"}:
                    state = "collecting_remediation_evidence"
                    blockers.append("retry_signature_unchanged")
                else:
                    state = "retry_training_allowed"
                    action = "start_auto_training"
            else:
                state = "collecting_remediation_evidence"
                if independent_shadow_evidence_enabled and (not runtime_blockers or "shadow_evidence" in str(session_flow).lower()):
                    action = "start_shadow_evidence_monitor" if "shadow_evidence" not in str(session_flow).lower() else "none"
                else:
                    action = "none"
                    if not independent_shadow_evidence_enabled:
                        blockers.append("independent_shadow_evidence_monitor_disabled")
                blockers.extend(runtime_blockers)
        elif model_status == "approved_for_shadow":
            state = "approved_for_shadow"
            if independent_shadow_evidence_enabled and not runtime_blockers:
                action = "start_shadow_evidence_monitor"
            else:
                action = "none"
                if not independent_shadow_evidence_enabled:
                    blockers.append("independent_shadow_evidence_monitor_disabled")
            blockers.extend(runtime_blockers)
        elif bool(profile.get("training_can_start")):
            if runtime_blockers:
                state = "ready_for_initial_training"
                blockers.extend(runtime_blockers)
            else:
                state = "ready_for_initial_training"
                action = "start_auto_training"
        else:
            state = "collecting_initial_sessions"
            action = "start_passive_collection"

    payload = {
        "autonomous_loop_state": state,
        "autonomousLoopState": state,
        "autonomous_loop_next_action": action,
        "autonomousLoopNextAction": action,
        "autonomous_loop_blockers": blockers,
        "autonomousLoopBlockers": list(blockers),
        "independent_shadow_evidence_monitor_enabled": bool(independent_shadow_evidence_enabled),
        "independentShadowEvidenceMonitorEnabled": bool(independent_shadow_evidence_enabled),
        "autonomous_loop_retry_attempt_count": int(profile.get("retry_attempt_count") or profile.get("auto_training_retry_attempt_count") or 0),
        "autonomousLoopRetryAttemptCount": int(profile.get("retry_attempt_count") or profile.get("auto_training_retry_attempt_count") or 0),
        "autonomous_loop_last_transition": state,
        "autonomousLoopLastTransition": state,
        "sessions_observed": len(sessions),
    }
    return payload


__all__ = ["build_autonomous_readiness_loop_state"]
