"""Safe background auto-training scheduler decisions for BioAuth.

This module is intentionally side-effect free. It does not train models, evaluate
artifacts, promote bundles, or decide runtime protection. The PySide bridge uses
these helpers to decide whether it may call the existing training path once for
the current trusted enrollment data snapshot.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Iterable, Mapping

from metadata_core.passive_quality import session_meets_passive_trusted_minimum_floor_if_needed
from metadata_core.remediation_loop import (
    RemediationAction,
    RemediationPlan,
    RemediationRetryEligibility,
    remediation_evidence_progress_from_summary,
)
from metadata_core.training_attempts import remediation_training_signature, training_attempt_blocks_auto_retry

AUTO_TRAINING_FAILURE_COOLDOWN_SECONDS = 30 * 60


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_bool(source: Mapping[str, Any], key: str, default: bool = False) -> bool:
    if not isinstance(source, Mapping) or key not in source:
        return bool(default)
    return bool(source.get(key))


def _safe_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)





def _plan_payload(remediation_plan: RemediationPlan | Mapping[str, Any] | None) -> Dict[str, Any]:
    if isinstance(remediation_plan, RemediationPlan):
        return remediation_plan.to_dict()
    return _as_dict(remediation_plan)


def _normal_text(value: Any) -> str:
    return str(value or "").strip()


def _normal_action(value: Any) -> str:
    return _normal_text(value).lower()


def _remediation_plan_id(remediation_plan: RemediationPlan | Mapping[str, Any] | None) -> str:
    payload = _plan_payload(remediation_plan)
    for key in ("remediation_plan_id", "plan_id", "id"):
        text = _normal_text(payload.get(key))
        if text:
            return text
    for key in ("evidence_report_digest", "candidate_artifact_digest", "training_data_signature"):
        text = _normal_text(payload.get(key))
        if text:
            return text
    return ""


def _remediation_required_evidence(remediation_plan: RemediationPlan | Mapping[str, Any] | None) -> Dict[str, int]:
    payload = _plan_payload(remediation_plan)
    return {str(k): max(0, _safe_int(v)) for k, v in _as_dict(payload.get("required_new_evidence")).items()}


def _remediation_current_evidence(remediation_plan: RemediationPlan | Mapping[str, Any] | None) -> Dict[str, int]:
    payload = _plan_payload(remediation_plan)
    return {str(k): max(0, _safe_int(v)) for k, v in _as_dict(payload.get("current_new_evidence")).items()}


def _merge_evidence_counts(*sources: Mapping[str, Any] | None) -> Dict[str, int]:
    merged: Dict[str, int] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key, value in source.items():
            text = str(key or "").strip()
            if not text:
                continue
            merged[text] = max(merged.get(text, 0), max(0, _safe_int(value)))
    return merged


def _session_is_trusted_owner_evidence(session: Mapping[str, Any]) -> bool:
    if bool(session.get("excluded_from_positive_training")):
        return False
    return _is_trusted_enrollment_session(session)


def _session_is_hard_negative_evidence(session: Mapping[str, Any]) -> bool:
    if not isinstance(session, Mapping):
        return False
    action = _normal_action(session.get("targeted_collection_action"))
    evidence_source = _normal_action(session.get("evidence_source"))
    trust_level = _normal_action(session.get("trust_level"))
    if action != RemediationAction.HARD_NEGATIVE_REMEDIATION_REQUIRED.value and evidence_source != "hard_negative_remediation" and trust_level != "hard_negative":
        return False
    if not bool(session.get("excluded_from_positive_training")):
        return False
    return session_meets_passive_trusted_minimum_floor_if_needed(session)


def remediation_evidence_progress_from_sessions(
    sessions: Iterable[Mapping[str, Any]] | None,
    remediation_plan: RemediationPlan | Mapping[str, Any] | None = None,
) -> Dict[str, int]:
    """Count accepted remediation evidence without using raw behavioral data."""

    payload = _plan_payload(remediation_plan)
    expected_action = _normal_action(payload.get("action") or payload.get("targeted_collection_action") or payload.get("next_action"))
    counts: Dict[str, int] = {}
    seen: set[str] = set()
    for session in sessions or []:
        if not isinstance(session, Mapping):
            continue
        identity = _session_identity(session)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        action = _normal_action(session.get("targeted_collection_action"))
        if expected_action and action and action != expected_action:
            continue
        if _session_is_hard_negative_evidence(session):
            counts["hard_negative_events"] = counts.get("hard_negative_events", 0) + 1
            continue
        if not _session_is_trusted_owner_evidence(session):
            continue
        if action == RemediationAction.COLLECT_POST_UNLOCK_TRUSTED_WINDOWS.value or bool(session.get("post_unlock_trusted_window")):
            counts["post_unlock_windows"] = counts.get("post_unlock_windows", 0) + 1
        elif action == RemediationAction.COLLECT_MORE_SHADOW_COMPARISON_WINDOWS.value or bool(session.get("shadow_comparison_window")):
            counts["shadow_comparison_windows"] = counts.get("shadow_comparison_windows", 0) + 1
        elif action == RemediationAction.COLLECT_HIGHER_QUALITY_OWNER_SESSIONS.value:
            counts["trusted_owner_sessions"] = counts.get("trusted_owner_sessions", 0) + 1
        elif action == RemediationAction.COLLECT_DIVERSE_OWNER_SESSIONS.value:
            counts["context_diversity_sessions"] = counts.get("context_diversity_sessions", 0) + 1
        elif action == RemediationAction.COLLECT_TRUSTED_OWNER_REAUTH_OR_UNLOCK_WINDOWS.value:
            counts["reauth_or_unlock_owner_windows"] = counts.get("reauth_or_unlock_owner_windows", 0) + 1
        for key in (
            "trusted_owner_sessions",
            "post_unlock_windows",
            "shadow_comparison_windows",
            "context_diversity_sessions",
            "reauth_or_unlock_owner_windows",
            "hard_negative_events",
        ):
            if key in session:
                counts[key] = max(counts.get(key, 0), max(0, _safe_int(session.get(key))))
    return counts


def remediation_requirements_met(
    remediation_plan: RemediationPlan | Mapping[str, Any] | None,
    current_new_evidence: Mapping[str, Any] | None = None,
) -> bool:
    payload = _plan_payload(remediation_plan)
    if not payload:
        return True
    retry = _normal_text(payload.get("retry_eligibility"))
    if retry != RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE.value:
        return False
    required = _remediation_required_evidence(payload)
    current = _merge_evidence_counts(_remediation_current_evidence(payload), current_new_evidence)
    if not required:
        return False
    for key, required_value in required.items():
        if required_value > 0 and current.get(key, 0) < required_value:
            return False
    return True


def remediation_retry_signature(
    *,
    base_training_signature: Any,
    remediation_plan: RemediationPlan | Mapping[str, Any] | None,
    current_new_evidence: Mapping[str, Any] | None = None,
) -> str:
    payload = _plan_payload(remediation_plan)
    if not payload:
        return _normal_text(base_training_signature)
    current = _merge_evidence_counts(_remediation_current_evidence(payload), current_new_evidence)
    return remediation_training_signature(
        training_data_digest=_normal_text(payload.get("training_data_signature")) or _normal_text(base_training_signature),
        evidence_report_digest=payload.get("evidence_report_digest"),
        candidate_artifact_digest=payload.get("candidate_artifact_digest"),
        remediation_plan_id=_remediation_plan_id(payload),
        current_new_evidence=current,
        source_gate=payload.get("source_gate"),
        action=payload.get("action"),
    )


def remediation_retry_block_reason(
    remediation_plan: RemediationPlan | Mapping[str, Any] | None,
    current_new_evidence: Mapping[str, Any] | None = None,
) -> str:
    payload = _plan_payload(remediation_plan)
    if not payload:
        return ""
    retry = _normal_text(payload.get("retry_eligibility"))
    action = _normal_action(payload.get("action"))
    if retry == RemediationRetryEligibility.BLOCKED_RUNTIME_FIX.value or action == RemediationAction.NO_COLLECTION_FIX_RUNTIME.value:
        return "remediation_runtime_fix_required"
    if retry == RemediationRetryEligibility.BLOCKED_SCHEMA_FIX.value or action == RemediationAction.NO_COLLECTION_FIX_SCHEMA.value:
        return "remediation_schema_fix_required"
    if retry == RemediationRetryEligibility.BLOCKED_CODE_FIX.value or action == RemediationAction.NO_RETRY_UNTIL_CODE_FIX.value:
        return "remediation_code_fix_required"
    if retry == RemediationRetryEligibility.MANUAL_REVIEW_REQUIRED.value:
        return "remediation_manual_review_required"
    if retry != RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE.value:
        return "remediation_retry_not_allowed"
    if not remediation_requirements_met(payload, current_new_evidence):
        return "remediation_new_evidence_required"
    return ""


def _is_passive_auto_enrollment_runtime_state(runtime_state: Mapping[str, Any] | None) -> bool:
    runtime_payload = _as_dict(runtime_state)
    if not bool(runtime_payload.get("active")):
        return False
    session_kind = str(runtime_payload.get("session_kind") or "").strip().lower()
    source = str(runtime_payload.get("collection_source") or "").strip().lower()
    return bool(session_kind == "enrollment" and (bool(runtime_payload.get("auto_enrollment")) or source == "passive_auto_enrollment"))


def _runtime_stop_or_archive_pending(runtime_state: Mapping[str, Any] | None) -> bool:
    runtime_payload = _as_dict(runtime_state)
    return bool(
        runtime_payload.get("auto_enrollment_finalizing")
        or runtime_payload.get("auto_enrollment_stop_requested")
        or runtime_payload.get("stop_requested")
        or runtime_payload.get("archive_requested")
        or runtime_payload.get("archive_pending")
        or runtime_payload.get("history_sync_pending")
    )


def _runtime_logger_process_alive(runtime_state: Mapping[str, Any] | None) -> bool:
    runtime_payload = _as_dict(runtime_state)
    return bool(
        runtime_payload.get("logger_process_alive")
        or runtime_payload.get("active_logger_process")
        or runtime_payload.get("logger_user_process_alive")
    )


def _runtime_monitor_process_alive(runtime_state: Mapping[str, Any] | None) -> bool:
    runtime_payload = _as_dict(runtime_state)
    return bool(
        runtime_payload.get("monitor_process_alive")
        or runtime_payload.get("active_monitor_process")
        or runtime_payload.get("monitor_user_process_alive")
    )


def _runtime_is_shadow_evidence(runtime_state: Mapping[str, Any] | None) -> bool:
    runtime_payload = _as_dict(runtime_state)
    session_kind = str(runtime_payload.get("session_kind") or runtime_payload.get("runtime_mode") or runtime_payload.get("mode") or "").strip().lower()
    evidence_source = str(runtime_payload.get("evidence_source") or runtime_payload.get("source") or "").strip().lower()
    flow = str(runtime_payload.get("flow") or runtime_payload.get("session_flow") or "").strip().lower()
    return bool(
        session_kind == "shadow_evidence"
        or evidence_source == "shadow_evidence_monitor"
        or flow.startswith("shadow_evidence")
        or runtime_payload.get("shadow_evidence_monitor_active")
        or runtime_payload.get("pending_shadow_evidence_monitor_start")
    )


def _runtime_retry_handoff_state(runtime_state: Mapping[str, Any] | None) -> str:
    runtime_payload = _as_dict(runtime_state)
    return str(runtime_payload.get("retry_handoff_state") or runtime_payload.get("retryHandoffState") or "").strip().lower()


def runtime_has_active_shadow_evidence_process(runtime_state: Mapping[str, Any] | None) -> bool:
    runtime_payload = _as_dict(runtime_state)
    # Phase 1 non-blocking contract: stale shadow_evidence state by itself is
    # not an active process. Only explicit process/heartbeat signals may block
    # retry training. This prevents approved_for_shadow remnants from trapping
    # the app in an active-session state after a crash.
    return bool(
        _runtime_is_shadow_evidence(runtime_payload)
        and (
            _runtime_logger_process_alive(runtime_payload)
            or _runtime_monitor_process_alive(runtime_payload)
            or bool(runtime_payload.get("shadow_evidence_monitor_active"))
        )
    )


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


def _profile_session_count(profile: Mapping[str, Any], trusted_sessions: list[Mapping[str, Any]]) -> int:
    return max(0, _safe_int(profile.get("session_count"), len(trusted_sessions)))


def training_readiness_signature(*, user_id: Any, profile: Mapping[str, Any] | None, sessions: Iterable[Mapping[str, Any]] | None) -> str:
    """Stable signature for the current trusted enrollment data snapshot.

    The signature intentionally includes trusted session identities and aggregate
    counts only. It does not include raw keyboard/mouse samples.
    """

    profile_payload = _as_dict(profile)
    trusted_sessions = _dedupe_trusted_sessions(sessions)
    session_ids = sorted(_session_identity(item) for item in trusted_sessions if _session_identity(item))
    payload = {
        "user_id": str(user_id or ""),
        "accepted_sessions": _profile_session_count(profile_payload, trusted_sessions),
        "minimum_session_count": _safe_int(profile_payload.get("minimum_session_count"), 8),
        "recommended_session_count": _safe_int(profile_payload.get("recommended_session_count"), 15),
        "trusted_session_ids": session_ids,
        "training_ready": bool(profile_payload.get("training_can_start")),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def auto_training_block_reason(
    *,
    settings: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    runtime_state: Mapping[str, Any] | None,
    consent_satisfied: bool,
    authenticated: bool,
    training_active: bool,
    session_flow: str,
    evaluation_active: bool = False,
    app_locked: bool = False,
    cooldown_until: float = 0.0,
    last_completed_signature: str = "",
    last_attempted_signature: str = "",
    last_attempted_training_result: str = "",
    last_attempted_training_status: str = "",
    current_signature: str = "",
    force_retry: bool = False,
    remediation_plan: RemediationPlan | Mapping[str, Any] | None = None,
    remediation_current_new_evidence: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> str:
    settings_payload = _as_dict(settings)
    profile_payload = _as_dict(profile)
    runtime_payload = _as_dict(runtime_state)
    if not authenticated:
        return "not_authenticated"
    if not _safe_bool(settings_payload, "auto_train_when_ready_enabled", False):
        return "auto_training_disabled"
    if not _safe_bool(settings_payload, "smart_auto_enrollment_enabled", False):
        return "smart_auto_enrollment_disabled"
    if not consent_satisfied:
        return "consent_required"
    if bool(training_active):
        return "training_active"
    if bool(evaluation_active):
        return "evaluation_active"
    if _is_passive_auto_enrollment_runtime_state(runtime_payload):
        return "passive_auto_enrollment_active"
    if bool(runtime_payload.get("auto_enrollment_finalizing")):
        return "passive_auto_enrollment_finalizing"
    handoff_state = _runtime_retry_handoff_state(runtime_payload)
    if handoff_state in {"shadow_evidence_settling_for_retry", "settling_for_retry"}:
        return "shadow_evidence_handoff_in_progress"
    remediation_progress_for_runtime = _merge_evidence_counts(
        _remediation_current_evidence(remediation_plan),
        remediation_current_new_evidence,
    )
    remediation_reason_for_runtime = remediation_retry_block_reason(remediation_plan, remediation_progress_for_runtime)
    if runtime_has_active_shadow_evidence_process(runtime_payload):
        if remediation_plan is None:
            return "logger_process_active"
        if remediation_reason_for_runtime:
            return remediation_reason_for_runtime
        return "shadow_evidence_handoff_required"
    if _runtime_logger_process_alive(runtime_payload):
        return "logger_process_active"
    if _runtime_monitor_process_alive(runtime_payload):
        return "monitor_process_active"
    if _runtime_stop_or_archive_pending(runtime_payload):
        return "session_archive_pending"
    # App passcode lock is a UI anti-tamper lock only. It does not represent
    # an identity-trust failure and must not block readiness-gated background
    # auto-training by itself; consent/auth/session/runtime checks remain
    # authoritative below.
    if str(session_flow or "idle").strip().lower() != "idle":
        return "session_not_idle"
    if bool(runtime_payload.get("active")):
        return "runtime_session_active"
    if bool(profile_payload.get("production_ready")):
        return "production_ready"
    if not bool(profile_payload.get("training_can_start")):
        return str(profile_payload.get("training_block_reason") or "training_not_ready")
    clock = time.time() if now is None else float(now)
    if float(cooldown_until or 0.0) > clock:
        return "cooldown_active"
    if not str(current_signature or "").strip():
        return "missing_training_signature"
    remediation_reason = remediation_retry_block_reason(remediation_plan, remediation_current_new_evidence)
    if remediation_reason:
        return remediation_reason
    if (
        (not bool(force_retry) or remediation_plan is not None)
        and str(current_signature or "") == str(last_attempted_signature or "")
        and training_attempt_blocks_auto_retry(last_attempted_training_result, last_attempted_training_status)
    ):
        return "already_attempted_current_training_data"
    if str(current_signature or "") == str(last_completed_signature or ""):
        return "already_trained_for_current_data"
    return ""


def auto_training_should_start(
    *,
    settings: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    runtime_state: Mapping[str, Any] | None,
    sessions: Iterable[Mapping[str, Any]] | None,
    user_id: Any,
    consent_satisfied: bool,
    authenticated: bool,
    training_active: bool,
    session_flow: str,
    evaluation_active: bool = False,
    app_locked: bool = False,
    cooldown_until: float = 0.0,
    last_completed_signature: str = "",
    last_attempted_signature: str = "",
    last_attempted_training_result: str = "",
    last_attempted_training_status: str = "",
    force_retry: bool = False,
    remediation_plan: RemediationPlan | Mapping[str, Any] | None = None,
    remediation_current_new_evidence: Mapping[str, Any] | None = None,
    production_evidence_summary: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> tuple[bool, str, str]:
    base_signature = training_readiness_signature(user_id=user_id, profile=profile, sessions=sessions)
    remediation_progress = {}
    if remediation_plan is not None:
        remediation_progress = _merge_evidence_counts(
            remediation_evidence_progress_from_sessions(sessions, remediation_plan),
            remediation_evidence_progress_from_summary(production_evidence_summary, remediation_plan),
            remediation_current_new_evidence,
        )
    signature = remediation_retry_signature(base_training_signature=base_signature, remediation_plan=remediation_plan, current_new_evidence=remediation_progress) if remediation_plan is not None else base_signature
    reason = auto_training_block_reason(
        settings=settings,
        profile=profile,
        runtime_state=runtime_state,
        consent_satisfied=consent_satisfied,
        authenticated=authenticated,
        training_active=training_active,
        session_flow=session_flow,
        evaluation_active=evaluation_active,
        app_locked=app_locked,
        cooldown_until=cooldown_until,
        last_completed_signature=last_completed_signature,
        last_attempted_signature=last_attempted_signature,
        last_attempted_training_result=last_attempted_training_result,
        last_attempted_training_status=last_attempted_training_status,
        current_signature=signature,
        force_retry=force_retry,
        remediation_plan=remediation_plan,
        remediation_current_new_evidence=remediation_progress,
        now=now,
    )
    return (not bool(reason), reason or "ready", signature)


def background_action_from_status(
    *,
    auto_training_enabled: bool,
    training_ready: bool,
    training_active: bool,
    active_training_source: str = "",
    cooldown_until: float = 0.0,
    now: float | None = None,
    last_reason: str = "",
) -> str:
    clock = time.time() if now is None else float(now)
    if bool(training_active) and str(active_training_source or "").strip().lower() == "auto":
        return "training_in_background"
    if bool(cooldown_until or 0.0) and float(cooldown_until or 0.0) > clock:
        return "training_cooldown"
    if not bool(auto_training_enabled):
        return "auto_training_disabled"
    if not bool(training_ready):
        return "collecting_until_training_ready"
    if str(last_reason or "") in {"already_trained_for_current_data", "already_attempted_current_training_data", "latest_training_attempt_rejected_for_current_data"}:
        return "waiting_for_new_trusted_sessions"
    return "ready_for_background_training"


__all__ = [
    "AUTO_TRAINING_FAILURE_COOLDOWN_SECONDS",
    "auto_training_block_reason",
    "auto_training_should_start",
    "background_action_from_status",
    "remediation_evidence_progress_from_sessions",
    "remediation_requirements_met",
    "remediation_retry_block_reason",
    "remediation_retry_signature",
    "training_readiness_signature",
    "runtime_has_active_shadow_evidence_process",
]
