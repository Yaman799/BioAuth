from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metadata_core.remediation_loop import (
    RemediationAction,
    RemediationFailureKind,
    RemediationRetryEligibility,
    RemediationPlan,
    build_remediation_plan,
)


def test_insufficient_post_unlock_evidence_generates_post_unlock_collection_plan():
    plan = build_remediation_plan(reason_codes=["insufficient_post_unlock_evidence"], source_gate="production_evidence_gate_v2")

    assert plan.failure_kind == RemediationFailureKind.DATA_REMEDIABLE
    assert plan.action == RemediationAction.COLLECT_POST_UNLOCK_TRUSTED_WINDOWS
    assert plan.retry_eligibility == RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE
    assert plan.required_new_evidence["post_unlock_windows"] == 3
    assert plan.retry_allowed is False
    assert plan.starts_collection is False
    assert plan.starts_training is False


def test_runtime_bundle_invalid_generates_no_collection_runtime_fix_plan():
    plan = build_remediation_plan(reason_codes=["runtime_bundle_invalid"], source_gate="production_approval")

    assert plan.failure_kind == RemediationFailureKind.RUNTIME_REMEDIABLE
    assert plan.action == RemediationAction.NO_COLLECTION_FIX_RUNTIME
    assert plan.retry_eligibility == RemediationRetryEligibility.BLOCKED_RUNTIME_FIX
    assert plan.collection_may_be_requested_later is False
    assert plan.retry_allowed is False
    assert "do_not_collect_until_runtime_or_code_issue_is_fixed" in plan.safety_notes


def test_feature_schema_mismatch_generates_no_collection_schema_fix_plan():
    plan = build_remediation_plan(reason_codes=["feature_schema_mismatch"], source_gate="runtime_validation")

    assert plan.failure_kind == RemediationFailureKind.RUNTIME_REMEDIABLE
    assert plan.action == RemediationAction.NO_COLLECTION_FIX_SCHEMA
    assert plan.retry_eligibility == RemediationRetryEligibility.BLOCKED_SCHEMA_FIX
    assert plan.required_new_evidence == {}
    assert plan.starts_collection is False


def test_confirmed_intruder_low_risk_generates_hard_negative_remediation():
    plan = build_remediation_plan(reason_codes=["confirmed_intruder_low_risk"], source_gate="production_evidence_gate_v2")

    assert plan.failure_kind == RemediationFailureKind.NEGATIVE_REMEDIABLE
    assert plan.action == RemediationAction.HARD_NEGATIVE_REMEDIATION_REQUIRED
    assert plan.retry_eligibility == RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE
    assert plan.required_new_evidence["hard_negative_events"] == 1
    assert "confirmed_intruder_must_not_become_owner_positive_training_data" in plan.safety_notes
    assert plan.retry_allowed is False


def test_feature_quality_too_low_generates_high_quality_owner_collection():
    plan = build_remediation_plan(reason_codes=["feature_quality_too_low"], source_gate="production_evidence_gate_v2")

    assert plan.failure_kind == RemediationFailureKind.DATA_REMEDIABLE
    assert plan.action == RemediationAction.COLLECT_HIGHER_QUALITY_OWNER_SESSIONS
    assert plan.required_new_evidence["trusted_owner_sessions"] == 2
    assert plan.collection_may_be_requested_later is True
    assert plan.starts_collection is False


def test_unknown_rate_too_high_generates_diverse_owner_collection():
    plan = build_remediation_plan(reason_codes=["unknown_rate_too_high"], source_gate="production_evidence_gate_v2")

    assert plan.failure_kind == RemediationFailureKind.DATA_REMEDIABLE
    assert plan.action == RemediationAction.COLLECT_DIVERSE_OWNER_SESSIONS
    assert plan.required_new_evidence["context_diversity_sessions"] == 2
    assert plan.retry_allowed is False


def test_remediation_plan_retry_not_allowed_without_new_evidence():
    plan = build_remediation_plan(reason_codes=["insufficient_model_agreement"], current_new_evidence={})

    assert plan.action == RemediationAction.COLLECT_MORE_SHADOW_COMPARISON_WINDOWS
    assert plan.retry_eligibility == RemediationRetryEligibility.REQUIRES_NEW_EVIDENCE
    assert plan.retry_allowed is False

    satisfied = build_remediation_plan(
        reason_codes=["insufficient_model_agreement"],
        current_new_evidence={"shadow_comparison_windows": 5},
    )
    assert satisfied.retry_allowed is True


def test_remediation_plan_serialization_roundtrip():
    plan = build_remediation_plan(
        reason_codes=["simulated_false_lock_detected"],
        source_gate="production_evidence_gate_v2",
        candidate_artifact_digest="sha256:candidate",
        training_data_signature="sha256:training",
        evidence_report_digest="sha256:evidence",
        current_new_evidence={"reauth_or_unlock_owner_windows": 1},
    )

    payload = plan.to_dict()
    restored = RemediationPlan.from_dict(payload)

    assert restored == plan
    assert payload["starts_collection"] is False
    assert payload["starts_training"] is False
    assert "keyboard_events" not in str(payload)
    assert "mouse_events" not in str(payload)
    assert "feature_vector" not in str(payload)


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("8 remediation loop plan-engine tests passed", flush=True)
    import os
    os._exit(0)
