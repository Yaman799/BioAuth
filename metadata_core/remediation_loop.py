"""Reason-code-driven remediation planning for BioAuth model gates.

This module is intentionally plan-only. It classifies failed policy, runtime,
shadow, and Production Evidence Gate reason codes into safe remediation plans,
but it never starts passive collection, never starts training, never changes
production approval, and never unlocks Protected Sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Mapping, Sequence


REMEDIATION_PLAN_SCHEMA_VERSION = 1


class RemediationFailureKind(str, Enum):
    """High-level categories used to decide whether data collection is safe."""

    DATA_REMEDIABLE = "data_remediable"
    NEGATIVE_REMEDIABLE = "negative_remediable"
    RUNTIME_REMEDIABLE = "runtime_remediable"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    NON_RETRYABLE_UNTIL_CODE_FIX = "non_retryable_until_code_fix"


class RemediationAction(str, Enum):
    """Safe next actions emitted by the plan engine.

    Actions describe what a future orchestration layer may request. This module
    does not execute these actions.
    """

    COLLECT_POST_UNLOCK_TRUSTED_WINDOWS = "collect_post_unlock_trusted_windows"
    COLLECT_MORE_SHADOW_COMPARISON_WINDOWS = "collect_more_shadow_comparison_windows"
    COLLECT_HIGHER_QUALITY_OWNER_SESSIONS = "collect_higher_quality_owner_sessions"
    COLLECT_DIVERSE_OWNER_SESSIONS = "collect_diverse_owner_sessions"
    COLLECT_TRUSTED_OWNER_REAUTH_OR_UNLOCK_WINDOWS = "collect_trusted_owner_reauth_or_unlock_windows"
    HARD_NEGATIVE_REMEDIATION_REQUIRED = "hard_negative_remediation_required"
    NO_COLLECTION_FIX_RUNTIME = "no_collection_fix_runtime"
    NO_COLLECTION_FIX_SCHEMA = "no_collection_fix_schema"
    INSPECT_OFFLINE_SUB_REASONS = "inspect_offline_sub_reasons"
    WAIT_FOR_MANUAL_REVIEW = "wait_for_manual_review"
    NO_RETRY_UNTIL_CODE_FIX = "no_retry_until_code_fix"


class RemediationRetryEligibility(str, Enum):
    """Whether retraining/re-evaluation may be attempted for this plan."""

    NOT_ALLOWED = "not_allowed"
    REQUIRES_NEW_EVIDENCE = "requires_new_evidence"
    BLOCKED_RUNTIME_FIX = "blocked_runtime_fix"
    BLOCKED_SCHEMA_FIX = "blocked_schema_fix"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    BLOCKED_CODE_FIX = "blocked_code_fix"


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _normalize_reason_code(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_reason_codes(reason_codes: Sequence[Any] | str | None) -> tuple[str, ...]:
    """Normalize, dedupe, and preserve reason codes as stable strings."""

    if reason_codes is None:
        return tuple()
    if isinstance(reason_codes, str):
        raw_items: Sequence[Any] = [reason_codes]
    elif isinstance(reason_codes, Sequence):
        raw_items = reason_codes
    else:
        raw_items = [reason_codes]

    normalized: list[str] = []
    for item in raw_items:
        code = _normalize_reason_code(item)
        if code and code not in normalized:
            normalized.append(code)
    return tuple(normalized)


def _first_present(source: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in source:
            return source.get(key)
    return None


@dataclass(frozen=True)
class RemediationPlan:
    """Serializable plan produced after a candidate/gate failure.

    The plan is privacy-safe and aggregate-only. It contains no raw keyboard,
    mouse, or biometric feature values, and it is not executable by itself.
    """

    schema_version: int = REMEDIATION_PLAN_SCHEMA_VERSION
    failure_kind: RemediationFailureKind = RemediationFailureKind.MANUAL_REVIEW_REQUIRED
    action: RemediationAction = RemediationAction.WAIT_FOR_MANUAL_REVIEW
    retry_eligibility: RemediationRetryEligibility = RemediationRetryEligibility.NOT_ALLOWED
    retry_allowed: bool = False
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    source_gate: str = "unknown"
    candidate_artifact_digest: str = ""
    training_data_signature: str = ""
    evidence_report_digest: str = ""
    status: str = "planned"
    required_new_evidence: Mapping[str, int] = field(default_factory=dict)
    current_new_evidence: Mapping[str, int] = field(default_factory=dict)
    next_action: str = "wait_for_manual_review"
    safety_notes: tuple[str, ...] = field(default_factory=tuple)

    COLLECTION_ACTIONS: ClassVar[frozenset[RemediationAction]] = frozenset(
        {
            RemediationAction.COLLECT_POST_UNLOCK_TRUSTED_WINDOWS,
            RemediationAction.COLLECT_MORE_SHADOW_COMPARISON_WINDOWS,
            RemediationAction.COLLECT_HIGHER_QUALITY_OWNER_SESSIONS,
            RemediationAction.COLLECT_DIVERSE_OWNER_SESSIONS,
            RemediationAction.COLLECT_TRUSTED_OWNER_REAUTH_OR_UNLOCK_WINDOWS,
        }
    )

    def __post_init__(self) -> None:
        kind = self.failure_kind if isinstance(self.failure_kind, RemediationFailureKind) else RemediationFailureKind(str(self.failure_kind))
        action = self.action if isinstance(self.action, RemediationAction) else RemediationAction(str(self.action))
        retry = self.retry_eligibility if isinstance(self.retry_eligibility, RemediationRetryEligibility) else RemediationRetryEligibility(str(self.retry_eligibility))
        object.__setattr__(self, "failure_kind", kind)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "retry_eligibility", retry)
        object.__setattr__(self, "reason_codes", normalize_reason_codes(self.reason_codes))
        required = {str(k): max(0, _as_int(v)) for k, v in dict(self.required_new_evidence or {}).items()}
        current = {str(k): max(0, _as_int(v)) for k, v in dict(self.current_new_evidence or {}).items()}
        object.__setattr__(self, "required_new_evidence", required)
        object.__setattr__(self, "current_new_evidence", current)
        notes = tuple(str(item) for item in (self.safety_notes or ()) if str(item).strip())
        object.__setattr__(self, "safety_notes", notes)
        object.__setattr__(self, "retry_allowed", bool(self._computed_retry_allowed()))

    @property
    def starts_collection(self) -> bool:
        """Plans never start collection; this only marks action type."""

        return False

    @property
    def collection_may_be_requested_later(self) -> bool:
        return self.action in self.COLLECTION_ACTIONS

    @property
    def starts_training(self) -> bool:
        return False

    def _computed_retry_allowed(self) -> bool:
        if self.retry_eligibility is not RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE:
            return False
        if not self.required_new_evidence:
            return False
        for key, required in self.required_new_evidence.items():
            if required > 0 and _as_int(self.current_new_evidence.get(key)) < required:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "failure_kind": self.failure_kind.value,
            "action": self.action.value,
            "retry_eligibility": self.retry_eligibility.value,
            "retry_allowed": bool(self.retry_allowed),
            "reason_codes": list(self.reason_codes),
            "source_gate": self.source_gate,
            "candidate_artifact_digest": self.candidate_artifact_digest,
            "training_data_signature": self.training_data_signature,
            "evidence_report_digest": self.evidence_report_digest,
            "status": self.status,
            "required_new_evidence": dict(self.required_new_evidence),
            "current_new_evidence": dict(self.current_new_evidence),
            "next_action": self.next_action,
            "safety_notes": list(self.safety_notes),
            "starts_collection": False,
            "starts_training": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "RemediationPlan":
        data = _as_mapping(payload)
        return cls(
            schema_version=_as_int(data.get("schema_version"), REMEDIATION_PLAN_SCHEMA_VERSION),
            failure_kind=RemediationFailureKind(str(data.get("failure_kind") or RemediationFailureKind.MANUAL_REVIEW_REQUIRED.value)),
            action=RemediationAction(str(data.get("action") or RemediationAction.WAIT_FOR_MANUAL_REVIEW.value)),
            retry_eligibility=RemediationRetryEligibility(str(data.get("retry_eligibility") or RemediationRetryEligibility.NOT_ALLOWED.value)),
            reason_codes=normalize_reason_codes(data.get("reason_codes")),
            source_gate=str(data.get("source_gate") or "unknown"),
            candidate_artifact_digest=str(data.get("candidate_artifact_digest") or ""),
            training_data_signature=str(data.get("training_data_signature") or ""),
            evidence_report_digest=str(data.get("evidence_report_digest") or ""),
            status=str(data.get("status") or "planned"),
            required_new_evidence=_as_mapping(data.get("required_new_evidence")),
            current_new_evidence=_as_mapping(data.get("current_new_evidence")),
            next_action=str(data.get("next_action") or "wait_for_manual_review"),
            safety_notes=tuple(data.get("safety_notes") or ()),
        )


_REASON_ACTION_TABLE: dict[str, tuple[RemediationFailureKind, RemediationAction, RemediationRetryEligibility, Mapping[str, int]]] = {
    "insufficient_post_unlock_evidence": (
        RemediationFailureKind.DATA_REMEDIABLE,
        RemediationAction.COLLECT_POST_UNLOCK_TRUSTED_WINDOWS,
        RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE,
        {"post_unlock_windows": 3},
    ),
    "insufficient_model_agreement": (
        RemediationFailureKind.DATA_REMEDIABLE,
        RemediationAction.COLLECT_MORE_SHADOW_COMPARISON_WINDOWS,
        RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE,
        {"shadow_comparison_windows": 5},
    ),
    "insufficient_shadow_windows": (
        RemediationFailureKind.DATA_REMEDIABLE,
        RemediationAction.COLLECT_MORE_SHADOW_COMPARISON_WINDOWS,
        RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE,
        {"shadow_comparison_windows": 5},
    ),
    "insufficient_model_agreement_data": (
        RemediationFailureKind.DATA_REMEDIABLE,
        RemediationAction.COLLECT_MORE_SHADOW_COMPARISON_WINDOWS,
        RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE,
        {"shadow_comparison_windows": 5},
    ),
    "baseline_decision_missing": (
        RemediationFailureKind.DATA_REMEDIABLE,
        RemediationAction.COLLECT_MORE_SHADOW_COMPARISON_WINDOWS,
        RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE,
        {"shadow_comparison_windows": 5},
    ),
    "feature_quality_too_low": (
        RemediationFailureKind.DATA_REMEDIABLE,
        RemediationAction.COLLECT_HIGHER_QUALITY_OWNER_SESSIONS,
        RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE,
        {"trusted_owner_sessions": 2},
    ),
    "unknown_rate_too_high": (
        RemediationFailureKind.DATA_REMEDIABLE,
        RemediationAction.COLLECT_DIVERSE_OWNER_SESSIONS,
        RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE,
        {"context_diversity_sessions": 2},
    ),
    "simulated_false_lock_detected": (
        RemediationFailureKind.DATA_REMEDIABLE,
        RemediationAction.COLLECT_TRUSTED_OWNER_REAUTH_OR_UNLOCK_WINDOWS,
        RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE,
        {"reauth_or_unlock_owner_windows": 3},
    ),
    "post_unlock_false_lock_detected": (
        RemediationFailureKind.DATA_REMEDIABLE,
        RemediationAction.COLLECT_TRUSTED_OWNER_REAUTH_OR_UNLOCK_WINDOWS,
        RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE,
        {"post_unlock_windows": 3},
    ),
    "confirmed_intruder_low_risk": (
        RemediationFailureKind.NEGATIVE_REMEDIABLE,
        RemediationAction.HARD_NEGATIVE_REMEDIATION_REQUIRED,
        RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE,
        {"hard_negative_events": 1},
    ),
    "runtime_bundle_invalid": (
        RemediationFailureKind.RUNTIME_REMEDIABLE,
        RemediationAction.NO_COLLECTION_FIX_RUNTIME,
        RemediationRetryEligibility.BLOCKED_RUNTIME_FIX,
        {},
    ),
    "feature_schema_mismatch": (
        RemediationFailureKind.RUNTIME_REMEDIABLE,
        RemediationAction.NO_COLLECTION_FIX_SCHEMA,
        RemediationRetryEligibility.BLOCKED_SCHEMA_FIX,
        {},
    ),
    "artifact_digest_mismatch": (
        RemediationFailureKind.NON_RETRYABLE_UNTIL_CODE_FIX,
        RemediationAction.NO_RETRY_UNTIL_CODE_FIX,
        RemediationRetryEligibility.BLOCKED_CODE_FIX,
        {},
    ),
    "serialization_failed": (
        RemediationFailureKind.NON_RETRYABLE_UNTIL_CODE_FIX,
        RemediationAction.NO_RETRY_UNTIL_CODE_FIX,
        RemediationRetryEligibility.BLOCKED_CODE_FIX,
        {},
    ),
    "auto_promotion_disabled": (
        RemediationFailureKind.MANUAL_REVIEW_REQUIRED,
        RemediationAction.WAIT_FOR_MANUAL_REVIEW,
        RemediationRetryEligibility.MANUAL_REVIEW_REQUIRED,
        {},
    ),
    "manual_approval_required": (
        RemediationFailureKind.MANUAL_REVIEW_REQUIRED,
        RemediationAction.WAIT_FOR_MANUAL_REVIEW,
        RemediationRetryEligibility.MANUAL_REVIEW_REQUIRED,
        {},
    ),
    "production_manual_review_required": (
        RemediationFailureKind.MANUAL_REVIEW_REQUIRED,
        RemediationAction.WAIT_FOR_MANUAL_REVIEW,
        RemediationRetryEligibility.MANUAL_REVIEW_REQUIRED,
        {},
    ),
}


_PRIORITY = {
    RemediationFailureKind.NON_RETRYABLE_UNTIL_CODE_FIX: 0,
    RemediationFailureKind.RUNTIME_REMEDIABLE: 1,
    RemediationFailureKind.NEGATIVE_REMEDIABLE: 2,
    RemediationFailureKind.MANUAL_REVIEW_REQUIRED: 3,
    RemediationFailureKind.DATA_REMEDIABLE: 4,
}


def _offline_sub_reason_plan(reason_codes: tuple[str, ...]) -> tuple[RemediationFailureKind, RemediationAction, RemediationRetryEligibility, Mapping[str, int]]:
    sub_reasons = tuple(code for code in reason_codes if code != "offline_approval_rejected")
    if any(code in {"runtime_bundle_invalid", "feature_schema_mismatch", "artifact_digest_mismatch"} for code in sub_reasons):
        return _select_plan_tuple(sub_reasons)
    if any(code in {"far_too_high", "frr_too_high", "candidate_unstable", "production_margin_not_met"} for code in sub_reasons):
        return (
            RemediationFailureKind.DATA_REMEDIABLE,
            RemediationAction.COLLECT_HIGHER_QUALITY_OWNER_SESSIONS,
            RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE,
            {"trusted_owner_sessions": 2},
        )
    return (
        RemediationFailureKind.MANUAL_REVIEW_REQUIRED,
        RemediationAction.INSPECT_OFFLINE_SUB_REASONS,
        RemediationRetryEligibility.MANUAL_REVIEW_REQUIRED,
        {},
    )


def _select_plan_tuple(reason_codes: tuple[str, ...]) -> tuple[RemediationFailureKind, RemediationAction, RemediationRetryEligibility, Mapping[str, int]]:
    selected: tuple[RemediationFailureKind, RemediationAction, RemediationRetryEligibility, Mapping[str, int]] | None = None
    selected_priority = 99
    for code in reason_codes:
        if code == "offline_approval_rejected":
            candidate = _offline_sub_reason_plan(reason_codes)
        else:
            candidate = _REASON_ACTION_TABLE.get(code)
        if candidate is None:
            continue
        priority = _PRIORITY[candidate[0]]
        if selected is None or priority < selected_priority:
            selected = candidate
            selected_priority = priority
    if selected is not None:
        return selected
    return (
        RemediationFailureKind.MANUAL_REVIEW_REQUIRED,
        RemediationAction.WAIT_FOR_MANUAL_REVIEW,
        RemediationRetryEligibility.MANUAL_REVIEW_REQUIRED,
        {},
    )


def _collect_current_new_evidence(source: Mapping[str, Any]) -> dict[str, int]:
    data = _as_mapping(_first_present(source, "current_new_evidence", "new_evidence", "evidence_progress"))
    result = {str(key): max(0, _as_int(value)) for key, value in data.items()}
    aliases = {
        "post_unlock_windows": ("post_unlock_windows", "post_unlock_trusted_window_count"),
        "shadow_comparison_windows": ("shadow_comparison_windows", "shadow_windows", "shadow_window_count"),
        "trusted_owner_sessions": ("trusted_owner_sessions", "new_trusted_owner_sessions"),
        "context_diversity_sessions": ("context_diversity_sessions", "diverse_owner_sessions"),
        "reauth_or_unlock_owner_windows": ("reauth_or_unlock_owner_windows", "trusted_reauth_windows"),
        "hard_negative_events": ("hard_negative_events", "confirmed_intruder_hard_negative_events"),
    }
    for target, keys in aliases.items():
        if target not in result:
            value = _first_present(source, *keys)
            if value is not None:
                result[target] = max(0, _as_int(value))
    return result



def remediation_evidence_progress_from_summary(
    production_evidence_summary: Mapping[str, Any] | None,
    remediation_plan: RemediationPlan | Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Extract aggregate remediation progress from a privacy-safe evidence summary.

    This helper intentionally consumes only aggregate counters produced by the
    evidence pipeline. It does not read raw events or raw feature values, and it
    does not decide production readiness.
    """

    summary = _as_mapping(production_evidence_summary)
    progress = _as_mapping(_first_present(summary, "remediation_progress", "remediationProgress"))
    counts: dict[str, int] = {str(k): max(0, _as_int(v)) for k, v in progress.items()}
    if not counts:
        return {}
    plan_payload = _as_mapping(remediation_plan.to_dict() if isinstance(remediation_plan, RemediationPlan) else remediation_plan)
    required = _as_mapping(plan_payload.get("required_new_evidence"))
    if required:
        return {key: value for key, value in counts.items() if key in required and value > 0}
    return {key: value for key, value in counts.items() if value > 0}


def build_remediation_plan(
    *,
    reason_codes: Sequence[Any] | str | None,
    source_gate: str = "unknown",
    candidate_artifact_digest: str = "",
    training_data_signature: str = "",
    evidence_report_digest: str = "",
    current_new_evidence: Mapping[str, Any] | None = None,
) -> RemediationPlan:
    """Build a safe, deterministic remediation plan from gate reason codes."""

    normalized = normalize_reason_codes(reason_codes)
    kind, action, retry, required = _select_plan_tuple(normalized)
    current = {str(k): max(0, _as_int(v)) for k, v in dict(current_new_evidence or {}).items()}
    notes = [
        "plan_only_no_collection_started",
        "plan_only_no_training_started",
        "auto_enrollment_remains_collector_not_decision_maker",
    ]
    if kind is RemediationFailureKind.NEGATIVE_REMEDIABLE:
        notes.append("confirmed_intruder_must_not_become_owner_positive_training_data")
    if kind in {RemediationFailureKind.RUNTIME_REMEDIABLE, RemediationFailureKind.NON_RETRYABLE_UNTIL_CODE_FIX}:
        notes.append("do_not_collect_until_runtime_or_code_issue_is_fixed")
    status = "requires_new_evidence" if retry is RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE else "blocked"
    if retry is RemediationRetryEligibility.MANUAL_REVIEW_REQUIRED:
        status = "manual_review_required"
    return RemediationPlan(
        failure_kind=kind,
        action=action,
        retry_eligibility=retry,
        reason_codes=normalized,
        source_gate=str(source_gate or "unknown"),
        candidate_artifact_digest=str(candidate_artifact_digest or ""),
        training_data_signature=str(training_data_signature or ""),
        evidence_report_digest=str(evidence_report_digest or ""),
        status=status,
        required_new_evidence=required,
        current_new_evidence=current,
        next_action=action.value,
        safety_notes=tuple(notes),
    )


def build_remediation_plan_from_gate_state(gate_state: Mapping[str, Any] | None) -> RemediationPlan:
    """Build a plan from policy/production approval style dictionaries."""

    source = _as_mapping(gate_state)
    reason_codes = []
    for key in (
        "reason_codes",
        "reasonCodes",
        "productionEvidenceReasonCodes",
        "production_evidence_reason_codes",
        "failedProductionGates",
        "failed_production_gates",
    ):
        reason_codes.extend(normalize_reason_codes(source.get(key)))
    single_reason = _first_present(source, "reason_code", "reasonCode", "block_reason", "blockReason")
    reason_codes.extend(normalize_reason_codes(single_reason))
    return build_remediation_plan(
        reason_codes=reason_codes,
        source_gate=str(_first_present(source, "source_gate", "sourceGate", "phase") or "unknown"),
        candidate_artifact_digest=str(_first_present(source, "candidate_artifact_digest", "candidateArtifactDigest", "productionEvidenceCandidateDigest") or ""),
        training_data_signature=str(_first_present(source, "training_data_signature", "trainingDataSignature") or ""),
        evidence_report_digest=str(_first_present(source, "evidence_report_digest", "evidenceReportDigest") or ""),
        current_new_evidence=_collect_current_new_evidence(source),
    )


REMEDIATION_REASON_CODE_MAPPING_TABLE: Mapping[str, Mapping[str, str]] = {
    code: {
        "failure_kind": value[0].value,
        "action": value[1].value,
        "retry_eligibility": value[2].value,
    }
    for code, value in _REASON_ACTION_TABLE.items()
}


__all__ = [
    "REMEDIATION_PLAN_SCHEMA_VERSION",
    "REMEDIATION_REASON_CODE_MAPPING_TABLE",
    "RemediationAction",
    "RemediationFailureKind",
    "RemediationPlan",
    "RemediationRetryEligibility",
    "build_remediation_plan",
    "remediation_evidence_progress_from_summary",
    "build_remediation_plan_from_gate_state",
    "normalize_reason_codes",
]
