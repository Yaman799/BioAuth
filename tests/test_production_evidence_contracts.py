from __future__ import annotations

import pytest

from evaluation_core.production_evidence import (
    ConfirmedIntruderEvidenceMetrics,
    ModelAgreementMetrics,
    PostUnlockEvidenceMetrics,
    ProductionEvidenceGateResult,
    ProductionEvidencePromotionEffect,
    ProductionEvidenceReasonCode,
    ProductionEvidenceReport,
    ProductionEvidenceStatus,
    RuntimeSafetyMetrics,
    contains_raw_biometric_fields,
)


def _walk_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def test_production_evidence_contract_defaults_to_shadow_only():
    report = ProductionEvidenceReport.missing_evidence(candidate_artifact_digest="sha256:candidate")
    payload = report.to_dict()

    assert payload["candidate_artifact_digest"] == "sha256:candidate"
    assert payload["gate"]["status"] == ProductionEvidenceStatus.PARTIAL.value
    assert payload["gate"]["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value
    assert payload["gate"]["reason_codes"] == [ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_MISSING]
    assert report.gate.allows_production_eligibility is False
    assert "productionReady" not in payload
    assert "protectedSessionsAvailable" not in payload


def test_production_evidence_serialization_roundtrip():
    report = ProductionEvidenceReport(
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        evaluation_report_digest="sha256:evaluation",
        runtime_schema_version="runtime-schema-v1",
        model_agreement=ModelAgreementMetrics(
            overall_agreement_rate=0.91,
            trusted_window_agreement_rate=0.93,
            critical_disagreement_count=0,
            high_risk_disagreement_count=0,
        ),
        post_unlock_evidence=PostUnlockEvidenceMetrics(
            trusted_window_count=4,
            warning_rate=0.01,
            simulated_false_locks=0,
            feature_quality_rate=0.87,
        ),
        confirmed_intruder_evidence=ConfirmedIntruderEvidenceMetrics(
            available=True,
            confirmed_intruder_count=2,
            confirmed_intruder_low_risk_count=0,
        ),
        runtime_safety=RuntimeSafetyMetrics(
            simulated_false_lock_count=0,
            unknown_rate=0.18,
            low_quality_decision_rate=0.09,
        ),
        gate=ProductionEvidenceGateResult(
            status=ProductionEvidenceStatus.PASS,
            promotion_effect=ProductionEvidencePromotionEffect.PRODUCTION_ELIGIBLE,
            reason_codes=(ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PASSED,),
        ),
    )

    payload = report.to_dict()
    restored = ProductionEvidenceReport.from_dict(payload)

    assert restored == report
    assert restored.to_dict() == payload
    assert restored.gate.allows_production_eligibility is True
    assert "protectedSessionsAvailable" not in payload


def test_production_evidence_no_raw_biometric_fields():
    payload = ProductionEvidenceReport.missing_evidence().to_dict()
    keys = set(_walk_keys(payload))

    assert "keyboard_events" not in keys
    assert "mouse_events" not in keys
    assert "feature_vector" not in keys
    assert "raw_feature_values" not in keys
    assert contains_raw_biometric_fields(payload) is False

    with pytest.raises(ValueError, match="raw biometric"):
        ProductionEvidenceReport.from_dict({"keyboard_events": [{"key": "A", "down_ms": 3}]})


def test_production_evidence_unknown_reason_codes_are_stable_or_rejected_safely():
    unsafe_pass_payload = {
        "gate": {
            "status": "pass",
            "promotion_effect": "production_eligible",
            "reason_codes": ["future_unreviewed_reason"],
        }
    }

    with pytest.raises(ValueError, match="unknown production evidence reason"):
        ProductionEvidenceReport.from_dict(unsafe_pass_payload)

    restored = ProductionEvidenceReport.from_dict(unsafe_pass_payload, allow_unknown_reason_codes=True)
    assert restored.gate.status == ProductionEvidenceStatus.PARTIAL
    assert restored.gate.promotion_effect == ProductionEvidencePromotionEffect.SHADOW_ONLY
    assert restored.gate.reason_codes == (ProductionEvidenceReasonCode.UNKNOWN_REASON_CODE,)
    assert restored.gate.allows_production_eligibility is False
