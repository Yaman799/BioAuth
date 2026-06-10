from __future__ import annotations

import pytest

from evaluation_core.production_evidence import (
    ProductionEvidencePromotionEffect,
    ProductionEvidenceReasonCode,
    ProductionEvidenceStatus,
    build_production_evidence_report,
    contains_raw_biometric_fields,
)


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


def _passing_report():
    return build_production_evidence_report(
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        evaluation_report_digest="sha256:evaluation",
        runtime_schema_version="runtime-schema-v1",
        model_comparison_windows=_matching_model_windows(),
        post_unlock_windows=_post_unlock_windows(),
        confirmed_intruder_events=[],
        runtime_decision_summaries=_runtime_decisions(),
    )


def test_model_agreement_rate_passes_with_sufficient_agreement():
    report = _passing_report()

    assert report.model_agreement.overall_agreement_rate == 1.0
    assert report.model_agreement.trusted_window_agreement_rate == 1.0
    assert report.gate.status == ProductionEvidenceStatus.PASS
    assert report.gate.promotion_effect == ProductionEvidencePromotionEffect.PRODUCTION_ELIGIBLE
    assert report.gate.reason_codes == (ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PASSED,)
    assert "protectedSessionsAvailable" not in report.to_dict()


def test_model_agreement_rate_low_adds_reason_code():
    model_windows = _matching_model_windows(2) + [
        {"candidate_decision": "trusted", "baseline_decision": "review", "trusted_window": True},
        {"candidate_decision": "review", "baseline_decision": "trusted", "trusted_window": True},
    ]

    report = build_production_evidence_report(
        model_comparison_windows=model_windows,
        post_unlock_windows=_post_unlock_windows(),
        confirmed_intruder_events=[],
        runtime_decision_summaries=_runtime_decisions(),
    )

    assert report.model_agreement.overall_agreement_rate == 0.5
    assert ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT in report.gate.reason_codes
    assert report.gate.status != ProductionEvidenceStatus.PASS
    assert report.gate.promotion_effect == ProductionEvidencePromotionEffect.SHADOW_ONLY


def test_missing_evidence_defaults_to_partial_shadow_only():
    report = build_production_evidence_report(candidate_artifact_digest="sha256:candidate")

    assert report.gate.status == ProductionEvidenceStatus.PARTIAL
    assert report.gate.promotion_effect == ProductionEvidencePromotionEffect.SHADOW_ONLY
    assert ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT in report.gate.reason_codes
    assert ProductionEvidenceReasonCode.INSUFFICIENT_POST_UNLOCK_EVIDENCE in report.gate.reason_codes
    assert ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PARTIAL in report.gate.reason_codes
    assert report.gate.allows_production_eligibility is False


def test_confirmed_intruder_low_risk_blocks_evidence():
    report = build_production_evidence_report(
        model_comparison_windows=_matching_model_windows(),
        post_unlock_windows=_post_unlock_windows(),
        confirmed_intruder_events=[
            {
                "event_id": "intruder-1",
                "confirmed_intruder": True,
                "candidate_decision": "trusted",
                "candidate_risk": 0.02,
            }
        ],
        runtime_decision_summaries=_runtime_decisions(),
    )

    assert report.confirmed_intruder_evidence.confirmed_intruder_count == 1
    assert report.confirmed_intruder_evidence.confirmed_intruder_low_risk_count == 1
    assert report.gate.status == ProductionEvidenceStatus.FAIL
    assert report.gate.promotion_effect == ProductionEvidencePromotionEffect.BLOCKED
    assert ProductionEvidenceReasonCode.CONFIRMED_INTRUDER_LOW_RISK in report.gate.reason_codes


def test_simulated_false_lock_adds_blocking_reason():
    runtime = _runtime_decisions()
    runtime.append(
        {
            "decision_id": "false-lock-1",
            "truth": "owner",
            "candidate_decision": "lock",
            "simulated_false_lock": True,
            "feature_quality_ok": True,
        }
    )

    report = build_production_evidence_report(
        model_comparison_windows=_matching_model_windows(),
        post_unlock_windows=_post_unlock_windows(),
        confirmed_intruder_events=[],
        runtime_decision_summaries=runtime,
    )

    assert report.runtime_safety.simulated_false_lock_count == 1
    assert report.gate.status == ProductionEvidenceStatus.FAIL
    assert report.gate.promotion_effect == ProductionEvidencePromotionEffect.BLOCKED
    assert ProductionEvidenceReasonCode.SIMULATED_FALSE_LOCK_DETECTED in report.gate.reason_codes


def test_unknown_rate_too_high_adds_reason():
    runtime = _runtime_decisions(2) + [
        {"decision_id": "unknown-1", "unknown": True, "feature_quality_ok": True},
        {"decision_id": "unknown-2", "candidate_decision": "unknown", "feature_quality_ok": True},
    ]

    report = build_production_evidence_report(
        model_comparison_windows=_matching_model_windows(),
        post_unlock_windows=_post_unlock_windows(),
        confirmed_intruder_events=[],
        runtime_decision_summaries=runtime,
    )

    assert report.runtime_safety.unknown_rate == 0.5
    assert report.gate.status == ProductionEvidenceStatus.PARTIAL
    assert report.gate.promotion_effect == ProductionEvidencePromotionEffect.SHADOW_ONLY
    assert ProductionEvidenceReasonCode.UNKNOWN_RATE_TOO_HIGH in report.gate.reason_codes


def test_feature_quality_too_low_adds_reason():
    runtime = [
        {"decision_id": "good", "candidate_decision": "trusted", "feature_quality_ok": True},
        {"decision_id": "bad", "candidate_decision": "trusted", "feature_quality_ok": False},
    ]

    report = build_production_evidence_report(
        model_comparison_windows=_matching_model_windows(),
        post_unlock_windows=_post_unlock_windows(),
        confirmed_intruder_events=[],
        runtime_decision_summaries=runtime,
    )

    assert report.post_unlock_evidence.feature_quality_rate == 0.5
    assert report.runtime_safety.low_quality_decision_rate == 0.5
    assert report.gate.status == ProductionEvidenceStatus.PARTIAL
    assert ProductionEvidenceReasonCode.FEATURE_QUALITY_TOO_LOW in report.gate.reason_codes


def test_metrics_do_not_emit_raw_behavioral_data():
    report = _passing_report()
    payload = report.to_dict()

    assert contains_raw_biometric_fields(payload) is False
    assert "keyboard_events" not in str(payload)
    assert "mouse_events" not in str(payload)
    assert "feature_vector" not in str(payload)

    with pytest.raises(ValueError, match="raw biometric"):
        build_production_evidence_report(
            model_comparison_windows=[
                {
                    "candidate_decision": "trusted",
                    "baseline_decision": "trusted",
                    "keyboard_events": [{"key": "A", "down_ms": 3}],
                }
            ],
            post_unlock_windows=_post_unlock_windows(),
            confirmed_intruder_events=[],
            runtime_decision_summaries=_runtime_decisions(),
        )
