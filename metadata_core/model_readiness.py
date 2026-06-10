"""Backend-owned model readiness strategy for BioAuth auto-readiness."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

from metadata_core.passive_quality import session_meets_passive_trusted_minimum_floor_if_needed

_TIME_OF_DAY_BUCKETS = ("morning", "afternoon", "evening", "night")


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _is_trusted_enrollment_session(session: Mapping[str, Any]) -> bool:
    if not isinstance(session, Mapping):
        return False
    if str(session.get("session_kind") or "").strip().lower() != "enrollment":
        return False
    if bool(session.get("training_counts_toward_minimum")):
        return session_meets_passive_trusted_minimum_floor_if_needed(session)
    bucket = str(session.get("bucket") or session.get("archive_group") or "").strip().lower()
    return bool(session.get("metadata_trusted")) and bucket in {"accepted", "authorized", "legit"} and session_meets_passive_trusted_minimum_floor_if_needed(session)


def _session_identity(session: Mapping[str, Any]) -> str:
    for key in ("session_id", "path", "archive_path"):
        text = str(session.get(key) or "").strip()
        if text:
            return f"{key}:{text}"
    return ""


def _dedupe_trusted_sessions(sessions: Iterable[Mapping[str, Any]] | None) -> list[Dict[str, Any]]:
    result: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for session in sessions or []:
        if not isinstance(session, Mapping) or not _is_trusted_enrollment_session(session):
            continue
        identity = _session_identity(session)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        result.append(dict(session))
    return result


def _coverage_strength(count: int) -> str:
    count = max(0, _safe_int(count))
    if count <= 0:
        return "none"
    if count < 30:
        return "weak"
    if count < 90:
        return "partial"
    return "strong"


def _mixed_strength(keyboard_rows: int, mouse_rows: int) -> str:
    keyboard_rows = max(0, _safe_int(keyboard_rows))
    mouse_rows = max(0, _safe_int(mouse_rows))
    if keyboard_rows <= 0 or mouse_rows <= 0:
        return "none"
    lower = min(keyboard_rows, mouse_rows)
    higher = max(keyboard_rows, mouse_rows)
    if lower < 30:
        return "weak"
    if higher and (lower / float(higher)) < 0.20:
        return "partial"
    return "strong"


def _input_coverage(sessions: Iterable[Mapping[str, Any]]) -> Dict[str, str]:
    keyboard_rows = 0
    mouse_rows = 0
    for session in sessions:
        keyboard_rows += _safe_int(session.get("keyboard_rows")) if isinstance(session, Mapping) else 0
        mouse_rows += _safe_int(session.get("mouse_rows")) if isinstance(session, Mapping) else 0
    return {"keyboard": _coverage_strength(keyboard_rows), "mouse": _coverage_strength(mouse_rows), "mixed": _mixed_strength(keyboard_rows, mouse_rows)}


def _time_coverage(sessions: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    coverage = {bucket: 0 for bucket in _TIME_OF_DAY_BUCKETS}
    for session in sessions:
        if not isinstance(session, Mapping):
            continue
        bucket = str(session.get("time_of_day_bucket") or "").strip().lower()
        if bucket in coverage:
            coverage[bucket] += 1
    return coverage


def _dominant_input_context(production_approval: Mapping[str, Any], input_coverage: Mapping[str, Any]) -> str:
    active_contexts = _safe_list(production_approval.get("activeRoutedContexts"))
    for context in ("mouse_heavy", "keyboard_heavy", "mixed", "short_session"):
        if context in active_contexts:
            return context
    keyboard = str(input_coverage.get("keyboard") or "none")
    mouse = str(input_coverage.get("mouse") or "none")
    mixed = str(input_coverage.get("mixed") or "none")
    if mouse in {"partial", "strong"} and keyboard in {"none", "weak"}:
        return "mouse_heavy"
    if keyboard in {"partial", "strong"} and mouse in {"none", "weak"}:
        return "keyboard_heavy"
    if mixed in {"partial", "strong"}:
        return "mixed"
    return "insufficient_behavior"


def _has_gate(failed_gates: list[str], gate: str) -> bool:
    return gate in failed_gates or any(item.endswith("_" + gate) for item in failed_gates)


def _strategy_from_sources(*, profile: Mapping[str, Any], production_approval: Mapping[str, Any], failed_gates: list[str], dominant_context: str, time_coverage: Mapping[str, int]) -> tuple[str, str, str]:
    model_status = str(production_approval.get("modelStatus") or profile.get("candidate_model_status") or "untrained").strip().lower()
    production_ready = bool(production_approval.get("protectedSessionsAvailable")) and bool(production_approval.get("productionReady"))
    training_ready = bool(profile.get("training_can_start"))
    training_block_reason = str(profile.get("training_block_reason") or "").strip()
    runtime_reason = str(production_approval.get("runtimeValidationReason") or profile.get("production_ready_reason") or "").strip()
    covered_buckets = sum(1 for count in time_coverage.values() if _safe_int(count) > 0)
    if production_ready:
        return "production_ready", "none", "safe_promotion_ready"
    if model_status == "approved_for_production":
        return "runtime_blocked", runtime_reason or "runtime_validation_required", "verify_runtime_bundle"
    if dominant_context == "mouse_heavy":
        return "targeted_collection", "mouse_heavy", "collect_keyboard_mixed_sessions"
    if dominant_context == "keyboard_heavy":
        return "targeted_collection", "keyboard_heavy", "collect_mouse_mixed_sessions"
    if _has_gate(failed_gates, "production_margin_not_met"):
        return "targeted_collection", "production_margin_not_met", "collect_diverse_high_quality_sessions"
    if "insufficient_context_coverage" in failed_gates or any(item.endswith("context_coverage") for item in failed_gates):
        return "targeted_collection", "insufficient_context_coverage", "collect_context_diversity_sessions"
    if "insufficient_time_spread" in failed_gates or (training_ready and covered_buckets > 0 and covered_buckets < 2):
        return "targeted_collection", "insufficient_time_spread", "collect_time_distributed_sessions"
    if "benchmark_not_run" in failed_gates:
        return "device_check_required", "benchmark_not_run", "run_device_check"
    if model_status == "approved_for_shadow":
        return "shadow_validation", "approved_for_shadow", "continue_shadow_validation_collect_targeted_sessions"
    if model_status == "rejected":
        return "collecting", "candidate_rejected", "collect_more_high_quality_sessions"
    if not training_ready:
        return "collecting", training_block_reason or "need_more_trusted_sessions", "collect_more_trusted_sessions"
    if model_status in {"pending_evaluation", "missing", "untrained", ""}:
        return "training_ready", "not_evaluated", "train_and_evaluate_manually"
    return "needs_attention", "unknown", "review_advanced_diagnostics"


def _text_for_action(action: str) -> str:
    return {
        "safe_promotion_ready": "The model is production-ready. Use the existing safe production runtime path; no policy bypass is required.",
        "verify_runtime_bundle": "Verify or repair the active production runtime bundle before Protected Sessions can start.",
        "collect_keyboard_mixed_sessions": "Collect more keyboard and mixed keyboard/mouse sessions before retraining.",
        "collect_mouse_mixed_sessions": "Collect more mouse and mixed keyboard/mouse sessions before retraining.",
        "collect_diverse_high_quality_sessions": "Collect more diverse, high-quality trusted sessions before retraining and re-evaluation.",
        "collect_context_diversity_sessions": "Collect sessions across more behavior contexts before retraining.",
        "collect_time_distributed_sessions": "Use BioAuth across different times of day so trusted sessions cover more time buckets.",
        "run_device_check": "Run the device check before relying on enhanced runtime or production-readiness decisions.",
        "continue_shadow_validation_collect_targeted_sessions": "Continue shadow validation and collect targeted trusted sessions; Protected Sessions remain locked.",
        "collect_more_high_quality_sessions": "Collect more high-quality trusted enrollment sessions before retraining.",
        "collect_more_trusted_sessions": "Collect more trusted enrollment sessions through existing quality gates.",
        "train_and_evaluate_manually": "Training is ready through the existing manual path or safe background auto-training when enabled.",
    }.get(action, "Review advanced diagnostics before deciding the next step.")


def _safe_user_message(readiness_level: str, action: str) -> str:
    if readiness_level == "production_ready":
        return "Protected Sessions are ready after production approval and runtime validation."
    if action == "train_and_evaluate_manually":
        return "Your trusted behavior profile is ready for the existing training path."
    return "BioAuth is improving your protection model in the background."


def build_model_readiness_state(*, profile: Mapping[str, Any] | None, production_approval: Mapping[str, Any] | None, sessions: Iterable[Mapping[str, Any]] | None, background_action: str = "", shadow_loop_state: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    profile_payload = _as_dict(profile)
    production_payload = _as_dict(production_approval)
    shadow_loop_payload = _as_dict(shadow_loop_state)
    remediation_payload = _as_dict(profile_payload.get("remediation_state") or profile_payload.get("remediationState"))
    if remediation_payload:
        current_counts = _as_dict(remediation_payload.get("current_counts") or remediation_payload.get("currentCounts") or remediation_payload.get("current_new_evidence") or remediation_payload.get("currentNewEvidence"))
        required_counts = _as_dict(remediation_payload.get("required_counts") or remediation_payload.get("requiredCounts") or remediation_payload.get("required_new_evidence") or remediation_payload.get("requiredNewEvidence"))
        remediation_payload.setdefault("current_counts", current_counts)
        remediation_payload.setdefault("currentCounts", current_counts)
        remediation_payload.setdefault("current_new_evidence", current_counts)
        remediation_payload.setdefault("currentNewEvidence", current_counts)
        remediation_payload.setdefault("required_counts", required_counts)
        remediation_payload.setdefault("requiredCounts", required_counts)
        remediation_payload.setdefault("required_new_evidence", required_counts)
        remediation_payload.setdefault("requiredNewEvidence", required_counts)
        retry_allowed_value = bool(remediation_payload.get("retry_allowed", remediation_payload.get("retryAllowed", False)))
        remediation_payload.setdefault("retry_allowed", retry_allowed_value)
        remediation_payload.setdefault("retryAllowed", retry_allowed_value)
    evidence_gate_payload = _as_dict(profile_payload.get("evidence_gate_state") or profile_payload.get("production_evidence_dashboard_state"))
    trusted_sessions = _dedupe_trusted_sessions(sessions)
    input_coverage = _input_coverage(trusted_sessions)
    time_coverage = _time_coverage(trusted_sessions)
    failed_gates = _safe_list(production_payload.get("failedProductionGates"))
    active_contexts = _safe_list(production_payload.get("activeRoutedContexts"))
    dominant_context = _dominant_input_context(production_payload, input_coverage)
    readiness_level, current_blocker, next_action = _strategy_from_sources(profile=profile_payload, production_approval=production_payload, failed_gates=failed_gates, dominant_context=dominant_context, time_coverage=time_coverage)
    training_ready = bool(profile_payload.get("training_can_start"))
    production_ready = bool(production_payload.get("protectedSessionsAvailable")) and bool(production_payload.get("productionReady"))
    accepted_sessions = _safe_int(profile_payload.get("session_count"), len(trusted_sessions))
    required_sessions = max(1, _safe_int(profile_payload.get("minimum_session_count"), 8))
    recommended_sessions = max(required_sessions, _safe_int(profile_payload.get("recommended_session_count"), 15))
    session_quality_summary = {
        "acceptedSessions": accepted_sessions,
        "requiredSessions": required_sessions,
        "recommendedSessions": recommended_sessions,
        "savedSessions": _safe_int(profile_payload.get("saved_session_count"), accepted_sessions),
        "trustedSessions": _safe_int(profile_payload.get("trusted_session_count"), accepted_sessions),
        "untrustedSessions": _safe_int(profile_payload.get("untrusted_session_count"), 0),
        "trainingBlockReason": str(profile_payload.get("training_block_reason") or ""),
        "trainingBlockDetail": str(profile_payload.get("training_block_detail") or ""),
        "selectedEnrollmentSessions": _safe_int(profile_payload.get("training_selected_enrollment_count"), 0),
        "selectedProtectedSessions": _safe_int(profile_payload.get("training_selected_protected_count"), 0),
    }
    advanced_parts = [f"readiness={readiness_level}", f"blocker={current_blocker}", f"action={next_action}", f"model_status={str(production_payload.get('modelStatus') or profile_payload.get('candidate_model_status') or 'untrained')}"]
    if failed_gates:
        advanced_parts.append("failed_gates=" + ",".join(failed_gates))
    if active_contexts:
        advanced_parts.append("active_contexts=" + ",".join(active_contexts))
    if background_action:
        advanced_parts.append("background_action=" + str(background_action))
    if evidence_gate_payload:
        advanced_parts.append("evidence_status=" + str(evidence_gate_payload.get("status") or "partial"))
    if remediation_payload:
        advanced_parts.append("remediation_action=" + str(remediation_payload.get("next_action") or remediation_payload.get("action") or ""))
    if shadow_loop_payload:
        shadow_phase = str(shadow_loop_payload.get("phase") or "")
        shadow_action = str(shadow_loop_payload.get("targetedCollectionAction") or "")
        if shadow_phase:
            advanced_parts.append("shadow_loop_phase=" + shadow_phase)
        if shadow_action:
            advanced_parts.append("shadow_loop_action=" + shadow_action)
    safe_message = "Training your protection model in the background." if str(background_action or "") == "training_in_background" else _safe_user_message(readiness_level, next_action)
    if bool(shadow_loop_payload.get("active")) and str(background_action or "") != "training_in_background":
        safe_message = str(shadow_loop_payload.get("safeUserMessage") or "BioAuth is validating your protection model safely in the background.")
    if bool(shadow_loop_payload.get("active")) and shadow_loop_payload.get("targetedCollectionAction"):
        next_action = str(shadow_loop_payload.get("targetedCollectionAction") or next_action)
    return {
        "readinessLevel": readiness_level,
        "trainingReady": bool(training_ready),
        "productionReady": bool(production_ready),
        "currentBlocker": current_blocker,
        "failedProductionGates": failed_gates,
        "dominantInputContext": dominant_context,
        "inputCoverage": input_coverage,
        "timeOfDayCoverage": time_coverage,
        "sessionQualitySummary": session_quality_summary,
        "nextBestAction": next_action,
        "nextBestActionText": _text_for_action(next_action),
        "backgroundAction": str(background_action or ""),
        "safeUserMessage": safe_message,
        "shadowLoopState": dict(shadow_loop_payload),
        "productionEvidenceState": dict(evidence_gate_payload),
        "evidenceGateState": dict(evidence_gate_payload),
        "evidenceGateStatus": str(evidence_gate_payload.get("status") or profile_payload.get("evidence_gate_status") or "partial"),
        "evidencePromotionEffect": str(evidence_gate_payload.get("promotion_effect") or profile_payload.get("evidence_promotion_effect") or "shadow_only"),
        "evidenceReasonCodes": _safe_list(evidence_gate_payload.get("reason_codes") or profile_payload.get("evidence_reason_codes")),
        "remediationState": dict(remediation_payload),
        "remediationStatus": str(remediation_payload.get("status") or profile_payload.get("remediation_status") or "planned"),
        "remediationNextAction": str(remediation_payload.get("next_action") or remediation_payload.get("nextAction") or remediation_payload.get("action") or profile_payload.get("remediation_next_action") or ""),
        "remediationRequiredCounts": _as_dict(remediation_payload.get("required_counts") or remediation_payload.get("requiredCounts") or remediation_payload.get("required_new_evidence") or remediation_payload.get("requiredNewEvidence") or profile_payload.get("remediation_required_counts")),
        "remediationCurrentCounts": _as_dict(remediation_payload.get("current_counts") or remediation_payload.get("currentCounts") or remediation_payload.get("current_new_evidence") or remediation_payload.get("currentNewEvidence") or profile_payload.get("remediation_current_counts")),
        "retryAllowed": bool(remediation_payload.get("retry_allowed", remediation_payload.get("retryAllowed", profile_payload.get("retry_allowed", False)))),
        "advancedDiagnosticText": " | ".join(advanced_parts),
    }


__all__ = ["build_model_readiness_state"]
