from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation_core.production_evidence import (
    SelectionPromotionReasonCode,
    SelectionPromotionThresholds,
    build_production_evidence_report,
    build_selection_based_promotion_gate,
)
from metadata_core.production_approval import build_production_eligibility_state


def _base_evidence(selection_gate=None, *, candidate: str = "sha256:phase6-candidate", runtime_schema: str = "runtime-schema-v1") -> dict:
    report = build_production_evidence_report(
        candidate_artifact_digest=candidate,
        baseline_artifact_digest="sha256:phase6-baseline",
        evaluation_report_digest="sha256:phase6-eval",
        runtime_schema_version=runtime_schema,
        model_comparison_windows=[
            {"window_id": f"m{idx}", "candidate_decision": "trusted", "baseline_decision": "trusted", "trusted_window": True}
            for idx in range(4)
        ],
        post_unlock_windows=[
            {"window_id": f"u{idx}", "trusted_window": True, "warning_triggered": False, "simulated_false_lock": False, "feature_quality_ok": True}
            for idx in range(3)
        ],
        confirmed_intruder_events=[],
        runtime_decision_summaries=[
            {"decision_id": f"r{idx}", "truth": "owner", "candidate_decision": "trusted", "unknown": False, "simulated_false_lock": False, "feature_quality_ok": True}
            for idx in range(4)
        ],
    ).to_dict()
    if selection_gate is not None:
        report["selection_promotion_gate"] = selection_gate.to_dict()
    return report


def _metadata(evidence: dict) -> dict:
    return {
        "model_status": "approved_for_production",
        "candidate_artifact_digest": "sha256:phase6-candidate",
        "baseline_artifact_digest": "sha256:phase6-baseline",
        "evaluation_report_digest": "sha256:phase6-eval",
        "runtime_schema_version": "runtime-schema-v1",
        "rollback_ready": True,
        "production_evidence": evidence,
    }


def _runtime(meta: dict) -> dict:
    return {"ok": True, "reason": "ok", "metadata": meta}


def test_selection_gate_passes_for_better_candidate_and_is_manual_approval_only() -> None:
    gate = build_selection_based_promotion_gate(
        candidate_artifact_digest="sha256:phase6-candidate",
        baseline_artifact_digest="sha256:phase6-baseline",
        runtime_schema_version="runtime-schema-v1",
        expected_candidate_artifact_digest="sha256:phase6-candidate",
        expected_runtime_schema_version="runtime-schema-v1",
        candidate_metrics={
            "eer": 0.08,
            "far": 0.006,
            "frr_at_target_far": 0.12,
            "false_lock_rate": 0.0002,
            "time_to_detect": 7.0,
            "adjudicated_disagreement_rate": 0.04,
            "shadow_pipeline_failure_rate": 0.001,
        },
        champion_metrics={
            "eer": 0.10,
            "far": 0.006,
            "frr_at_target_far": 0.15,
            "false_lock_rate": 0.0004,
            "time_to_detect": 9.0,
            "adjudicated_disagreement_rate": 0.08,
            "shadow_pipeline_failure_rate": 0.002,
        },
        evidence_volume={"total_windows": 800, "adjudicated_high_risk_events": 80},
        thresholds=SelectionPromotionThresholds(min_total_evidence_windows=500, min_adjudicated_high_risk_events=50),
    )
    assert gate.allows_selection_promotion is True
    assert gate.status == "pass"
    assert gate.promotion_effect == "production_eligible_after_approval"
    assert gate.weighted_score >= gate.min_weighted_score
    assert gate.reason_codes == (SelectionPromotionReasonCode.PASSED,)

    meta = _metadata(_base_evidence(gate))
    state = build_production_eligibility_state(candidate_metadata=meta, runtime_validation=_runtime(meta), rollback_available=True)
    assert state["eligible"] is True
    assert state["selectionPromotionPassed"] is True
    assert state["protectedSessionsAvailable"] is False
    assert state["activeRuntimePointerWritten"] is False


def test_selection_gate_blocks_false_lock_regression_even_if_evidence_passes() -> None:
    gate = build_selection_based_promotion_gate(
        candidate_artifact_digest="sha256:phase6-candidate",
        baseline_artifact_digest="sha256:phase6-baseline",
        runtime_schema_version="runtime-schema-v1",
        expected_candidate_artifact_digest="sha256:phase6-candidate",
        expected_runtime_schema_version="runtime-schema-v1",
        candidate_metrics={
            "eer": 0.06,
            "far": 0.006,
            "frr_at_target_far": 0.10,
            "false_lock_rate": 0.01,
            "time_to_detect": 5.0,
            "adjudicated_disagreement_rate": 0.03,
            "shadow_pipeline_failure_rate": 0.001,
        },
        champion_metrics={
            "eer": 0.09,
            "far": 0.006,
            "frr_at_target_far": 0.14,
            "false_lock_rate": 0.0001,
            "time_to_detect": 8.0,
            "adjudicated_disagreement_rate": 0.05,
            "shadow_pipeline_failure_rate": 0.001,
        },
        evidence_volume={"total_windows": 800, "adjudicated_high_risk_events": 80},
        thresholds=SelectionPromotionThresholds(min_total_evidence_windows=500, min_adjudicated_high_risk_events=50),
    )
    assert gate.allows_selection_promotion is False
    assert SelectionPromotionReasonCode.FALSE_LOCK_REGRESSION in gate.reason_codes

    meta = _metadata(_base_evidence(gate))
    state = build_production_eligibility_state(candidate_metadata=meta, runtime_validation=_runtime(meta), rollback_available=True)
    assert state["eligible"] is False
    assert "selection_promotion_gate_blocked" in state["blockers"]
    assert SelectionPromotionReasonCode.FALSE_LOCK_REGRESSION in state["blockers"]
    assert state["protectedSessionsAvailable"] is False
    assert state["activeRuntimePointerWritten"] is False


def test_missing_selection_gate_is_backward_compatible_with_existing_evidence_contract() -> None:
    meta = _metadata(_base_evidence())
    state = build_production_eligibility_state(candidate_metadata=meta, runtime_validation=_runtime(meta), rollback_available=True)
    assert state["eligible"] is True
    assert state["selectionPromotionPassed"] is False
    assert state["selectionPromotionGate"]["status"] == "not_evaluated"


def test_selection_gate_rejects_raw_biometric_or_feature_payloads() -> None:
    try:
        build_selection_based_promotion_gate(
            candidate_metrics={"eer": 0.1, "feature_vector": [1, 2, 3]},
            champion_metrics={"eer": 0.2},
        )
    except ValueError as exc:
        assert "raw biometric" in str(exc).lower() or "behavioral" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("raw feature vector must be rejected")
