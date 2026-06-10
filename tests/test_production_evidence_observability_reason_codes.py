from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation_core.production_evidence import (
    ProductionEvidencePromotionEffect,
    ProductionEvidenceReasonCode,
    ProductionEvidenceStatus,
    build_production_evidence_report,
)
from metadata_core.production_approval import (
    build_production_approval_state,
    production_approval_observability_payload,
)


def _candidate_paths():
    return {"metadata": "", "evaluation_report": "", "evaluation_summary": ""}


def _matching_model_windows(count: int = 4):
    return [
        {
            "window_id": f"w{idx}",
            "candidate_decision": "trusted",
            "baseline_decision": "trusted",
            "trusted_window": True,
        }
        for idx in range(count)
    ]


def _post_unlock_windows(count: int = 3):
    return [
        {
            "window_id": f"unlock{idx}",
            "trusted_window": True,
            "warning_triggered": False,
            "simulated_false_lock": False,
            "feature_quality_ok": True,
        }
        for idx in range(count)
    ]


def _runtime_decisions(count: int = 4):
    return [
        {
            "decision_id": f"r{idx}",
            "truth": "owner",
            "candidate_decision": "trusted",
            "unknown": False,
            "simulated_false_lock": False,
            "feature_quality_ok": True,
        }
        for idx in range(count)
    ]


def _passing_evidence():
    return build_production_evidence_report(
        candidate_artifact_digest="sha256:candidate-pass",
        baseline_artifact_digest="sha256:baseline",
        evaluation_report_digest="sha256:evaluation",
        runtime_schema_version="runtime-schema-v1",
        model_comparison_windows=_matching_model_windows(),
        post_unlock_windows=_post_unlock_windows(),
        confirmed_intruder_events=[],
        runtime_decision_summaries=_runtime_decisions(),
    ).to_dict()


def _partial_evidence():
    return build_production_evidence_report(
        candidate_artifact_digest="sha256:candidate-partial",
        model_comparison_windows=[
            {
                "window_id": "w-low-1",
                "candidate_decision": "warning",
                "baseline_decision": "trusted",
                "trusted_window": True,
            }
        ],
        post_unlock_windows=[],
        confirmed_intruder_events=[],
        runtime_decision_summaries=[],
    ).to_dict()


def _failed_evidence():
    return build_production_evidence_report(
        candidate_artifact_digest="sha256:candidate-failed",
        model_comparison_windows=_matching_model_windows(),
        post_unlock_windows=_post_unlock_windows(),
        confirmed_intruder_events=[
            {
                "event_id": "intruder-1",
                "confirmed_intruder": True,
                "candidate_decision": "trusted",
                "candidate_risk": 0.01,
            }
        ],
        runtime_decision_summaries=_runtime_decisions(),
    ).to_dict()


def _state_for(evidence, *, model_status="approved_for_production", safety_gate_results=None):
    return build_production_approval_state(
        candidate_paths=_candidate_paths(),
        candidate_metadata={
            "model_status": model_status,
            "production_evidence": evidence,
            "policy_details": {
                "gate_results": {"f1": True, "far": True, "frr": True},
                "safety_gate_results": safety_gate_results or {},
            },
        },
        runtime_validation={"ok": False, "reason": "runtime_bundle_invalid", "metadata": {}},
    )


def _walk_keys(payload):
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield str(key)
            yield from _walk_keys(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            yield from _walk_keys(item)


def test_production_evidence_reason_codes_exposed():
    state = _state_for(_failed_evidence())

    assert state["productionEvidenceStatus"] == ProductionEvidenceStatus.FAIL.value
    assert state["productionEvidencePromotionEffect"] == ProductionEvidencePromotionEffect.BLOCKED.value
    assert ProductionEvidenceReasonCode.CONFIRMED_INTRUDER_LOW_RISK in state["productionEvidenceReasonCodes"]
    assert ProductionEvidenceReasonCode.CONFIRMED_INTRUDER_LOW_RISK in state["productionEvidenceSummary"]["reason_codes"]
    assert state["productionEvidenceCandidateDigest"] == "sha256:candidate-failed"


def test_existing_production_reason_codes_preserved():
    state = _state_for(
        _partial_evidence(),
        safety_gate_results={"false_lock_count": False, "data_coverage": True},
    )

    failed = state["failedProductionGates"]
    assert "closed_beta_safety_gate" not in failed
    assert "safety_gate_failed" in failed
    assert "safety_false_lock_count" in failed
    assert "production_evidence_fail" in failed
    assert ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT in state["productionEvidenceReasonCodes"]
    assert ProductionEvidenceReasonCode.INSUFFICIENT_POST_UNLOCK_EVIDENCE in state["productionEvidenceReasonCodes"]


def test_evidence_observability_no_raw_biometric_data():
    state = _state_for(_passing_evidence())
    state.update(
        {
            "raw_keyboard_events": [{"key": "secret"}],
            "mouse_events": [{"x": 1, "y": 2}],
            "feature_vector": [0.1, 0.2, 0.3],
        }
    )

    payload = production_approval_observability_payload(state)
    joined_keys = " ".join(_walk_keys(payload)).lower()
    for forbidden in ("raw_keyboard", "keyboard_events", "mouse_events", "feature_vector", "feature_values"):
        assert forbidden not in joined_keys
    assert payload["production_evidence_summary"]["status"] == ProductionEvidenceStatus.PASS.value
    assert payload["production_evidence_summary"]["model_agreement"]["overall_agreement_rate"] == 1.0
    assert payload["production_evidence_summary"]["runtime_safety"]["unknown_rate"] == 0.0


def test_backend_owned_production_approval_state_contains_evidence_summary():
    state = _state_for(_passing_evidence())
    summary = state["productionEvidenceSummary"]

    assert state["productionEvidencePassed"] is True
    assert state["productionReady"] is False
    assert state["protectedSessionsAvailable"] is False
    assert summary["status"] == ProductionEvidenceStatus.PASS.value
    assert summary["promotion_effect"] == ProductionEvidencePromotionEffect.PRODUCTION_ELIGIBLE.value
    assert summary["reason_codes"] == [ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PASSED]
    assert summary["candidate_artifact_digest"] == "sha256:candidate-pass"
    assert summary["post_unlock_evidence"]["trusted_window_count"] == 3
    assert summary["confirmed_intruder_evidence"]["confirmed_intruder_count"] == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("4 focused production evidence observability tests passed", flush=True)
