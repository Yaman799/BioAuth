from __future__ import annotations

from pathlib import Path

from evaluation_core.production_evidence import (
    ProductionEvidencePromotionEffect,
    ProductionEvidenceReasonCode,
    ProductionEvidenceStatus,
    build_production_evidence_report,
)
from metadata_core.auto_promotion import auto_promotion_block_reason
from metadata_core.production_approval import build_production_approval_state
from model_policy import evaluate_model_policy

ROOT = Path(__file__).resolve().parent.parent


def _matching_model_windows(count: int = 4):
    return [
        {"window_id": f"w{idx}", "candidate_decision": "trusted", "baseline_decision": "trusted", "trusted_window": True}
        for idx in range(count)
    ]


def _post_unlock_windows(count: int = 3):
    return [
        {"window_id": f"u{idx}", "trusted_window": True, "warning_triggered": False, "simulated_false_lock": False, "feature_quality_ok": True}
        for idx in range(count)
    ]


def _runtime_decisions(count: int = 4):
    return [
        {"decision_id": f"r{idx}", "truth": "owner", "candidate_decision": "trusted", "unknown": False, "simulated_false_lock": False, "feature_quality_ok": True}
        for idx in range(count)
    ]


def _passing_evidence() -> dict:
    return build_production_evidence_report(
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        evaluation_report_digest="sha256:evaluation",
        runtime_schema_version="runtime-schema-v1",
        model_comparison_windows=_matching_model_windows(),
        post_unlock_windows=_post_unlock_windows(),
        confirmed_intruder_events=[],
        runtime_decision_summaries=_runtime_decisions(),
    ).to_dict()


def _partial_evidence() -> dict:
    return build_production_evidence_report(candidate_artifact_digest="sha256:candidate").to_dict()


def _failed_intruder_evidence() -> dict:
    return build_production_evidence_report(
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        evaluation_report_digest="sha256:evaluation",
        runtime_schema_version="runtime-schema-v1",
        model_comparison_windows=_matching_model_windows(),
        post_unlock_windows=_post_unlock_windows(),
        confirmed_intruder_events=[
            {"event_id": "intruder-1", "confirmed_intruder": True, "candidate_decision": "trusted", "candidate_risk": 0.01}
        ],
        runtime_decision_summaries=_runtime_decisions(),
    ).to_dict()


def _policy_report(*, evidence: dict, safety_ready: bool = False, include_safety: bool = True) -> dict:
    payload = {
        "primary_evaluation": "candidate_bundle",
        "evaluations": {
            "candidate_bundle": {
                "metrics": {
                    "session_count": 8,
                    "legitimate_session_count": 6,
                    "intruder_session_count": 2,
                    "auc": 0.92,
                    "f1": 0.82,
                    "far": 0.01,
                    "frr": 0.02,
                    "precision": 0.91,
                    "recall": 0.90,
                }
            }
        },
        "production_evidence": evidence,
    }
    if include_safety:
        payload["safety_metrics"] = {
            "false_lock_count": 0,
            "warning_per_hour": None,
            "low_quality_decision_rate": 0.0,
            "raw_biometric_data_included": False,
            "data_coverage": {
                "closed_beta_ready": bool(safety_ready),
                "missing": [] if safety_ready else ["minimum_20_beta_users", "windows_device_coverage", "diversity_coverage", "minimum_observation_hours"],
            },
        }
    return payload


def _state_from_meta(meta: dict, *, runtime_ok: bool = False) -> dict:
    return build_production_approval_state(
        candidate_paths={},
        candidate_metadata=meta,
        runtime_validation={"ok": runtime_ok, "reason": "ok" if runtime_ok else "runtime_pointer_missing", "metadata": meta},
        runtime_paths={"base": "/tmp/runtime"} if runtime_ok else {},
    )


def _legacy_closed_beta_blocked_meta() -> dict:
    meta = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False))
    meta["model_status"] = "approved_for_shadow"
    meta["approval_reason"] = (
        "Production promotion blocked by closed-beta safety gate: warning_per_hour (None), "
        "data_coverage (minimum_20_beta_users, windows_device_coverage). Candidate remains eligible for shadow validation only."
    )
    meta.setdefault("policy_details", {})["safety_gate_results"] = {
        "safety_metrics_present": True,
        "false_lock_count": True,
        "warning_per_hour": False,
        "low_quality_decision_rate": True,
        "data_coverage": False,
        "raw_data_absent": True,
    }
    meta["policy_details"]["closed_beta_coverage"] = {"closed_beta_ready": False, "missing": ["minimum_20_beta_users"]}
    return meta


def test_closed_beta_gate_missing_is_advisory_by_default(monkeypatch):
    monkeypatch.delenv("BIOAUTH_CLOSED_BETA_GATE_MODE", raising=False)
    monkeypatch.delenv("BIOAUTH_REQUIRE_CLOSED_BETA_GATE", raising=False)
    decision = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False))
    assert decision["model_status"] == "approved_for_production"
    details = decision["policy_details"]
    assert details["closed_beta_gate_required"] is False
    assert details["closed_beta_gate_blocking"] is False
    assert details["closed_beta_gate_status"] in {"optional_missing", "optional_partial"}


def test_closed_beta_gate_missing_does_not_override_evidence_reason_code(monkeypatch):
    decision = evaluate_model_policy(_policy_report(evidence=_partial_evidence(), safety_ready=False))
    assert decision["model_status"] == "approved_for_shadow"
    assert ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT in decision["production_evidence_reason_codes"]
    assert "closed-beta safety gate" not in decision["approval_reason"]


def test_closed_beta_gate_missing_does_not_block_production_approval_when_advisory(monkeypatch):
    decision = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False))
    assert decision["model_status"] == "approved_for_production"
    assert decision["policy_details"]["closed_beta_gate_blocking"] is False


def test_closed_beta_gate_advisory_state_exposed_in_backend_payload(monkeypatch):
    meta = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False))
    state = _state_from_meta(meta, runtime_ok=False)
    assert state["closedBetaGateRequired"] is False
    assert state["closedBetaGateBlocking"] is False
    assert state["closedBetaGateStatus"] in {"optional_missing", "optional_partial"}
    assert "minimum_20_beta_users" in state["closedBetaAdvisoryReasons"]


def test_closed_beta_gate_advisory_does_not_enable_protected_sessions(monkeypatch):
    meta = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False))
    state = _state_from_meta(meta, runtime_ok=False)
    assert state["protectedSessionsAvailable"] is False
    assert state["protected_sessions_available"] is False


def test_closed_beta_gate_advisory_does_not_enable_auto_promotion(monkeypatch):
    meta = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False))
    reason = auto_promotion_block_reason(settings={"auto_promote_when_production_safe_enabled": False}, candidate_metadata=meta, runtime_validation={"ok": False})
    assert reason == "auto_promotion_disabled"


def test_closed_beta_gate_required_mode_blocks_when_missing(monkeypatch):
    monkeypatch.setenv("BIOAUTH_CLOSED_BETA_GATE_MODE", "required")
    decision = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False))
    assert decision["model_status"] == "approved_for_shadow"
    assert decision["policy_details"]["closed_beta_gate_required"] is True
    assert decision["policy_details"]["closed_beta_gate_blocking"] is True
    assert "closed-beta safety gate" in decision["approval_reason"]


def test_closed_beta_gate_required_mode_preserves_existing_blocking_behavior(monkeypatch):
    monkeypatch.setenv("BIOAUTH_REQUIRE_CLOSED_BETA_GATE", "1")
    decision = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False))
    reason = auto_promotion_block_reason(
        settings={"auto_promote_when_production_safe_enabled": True},
        candidate_metadata=decision,
        runtime_validation={"ok": False},
    )
    assert decision["model_status"] == "approved_for_shadow"
    assert reason == "model_not_approved_for_production"


def test_evidence_partial_still_blocks_even_when_closed_beta_is_advisory(monkeypatch):
    decision = evaluate_model_policy(_policy_report(evidence=_partial_evidence(), safety_ready=False))
    assert decision["model_status"] == "approved_for_shadow"
    assert decision["policy_details"]["production_evidence_gate_results"]["allows_production_eligibility"] is False


def test_baseline_decision_missing_still_blocks_even_when_closed_beta_is_advisory(monkeypatch):
    decision = evaluate_model_policy(_policy_report(evidence=_partial_evidence(), safety_ready=False))
    codes = set(decision["production_evidence_reason_codes"])
    assert ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT in codes
    assert decision["model_status"] == "approved_for_shadow"


def test_insufficient_post_unlock_evidence_still_blocks_even_when_closed_beta_is_advisory(monkeypatch):
    decision = evaluate_model_policy(_policy_report(evidence=_partial_evidence(), safety_ready=False))
    assert ProductionEvidenceReasonCode.INSUFFICIENT_POST_UNLOCK_EVIDENCE in decision["production_evidence_reason_codes"]
    assert decision["model_status"] == "approved_for_shadow"


def test_confirmed_intruder_low_risk_still_blocks_even_when_closed_beta_is_advisory(monkeypatch):
    decision = evaluate_model_policy(_policy_report(evidence=_failed_intruder_evidence(), safety_ready=False))
    assert decision["model_status"] == "rejected"
    assert ProductionEvidenceReasonCode.CONFIRMED_INTRUDER_LOW_RISK in decision["production_evidence_reason_codes"]


def test_runtime_schema_mismatch_still_blocks_even_when_closed_beta_is_advisory(monkeypatch):
    evidence = build_production_evidence_report(
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        evaluation_report_digest="sha256:evaluation",
        runtime_schema_version="runtime-old",
        model_comparison_windows=_matching_model_windows(),
        post_unlock_windows=_post_unlock_windows(),
        confirmed_intruder_events=[],
        runtime_decision_summaries=_runtime_decisions(),
    ).to_dict()
    evidence["gate"]["reason_codes"].append(ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH)
    evidence["gate"]["status"] = ProductionEvidenceStatus.PARTIAL.value
    evidence["gate"]["promotion_effect"] = ProductionEvidencePromotionEffect.SHADOW_ONLY.value
    evidence["gate"]["allows_production_eligibility"] = False
    decision = evaluate_model_policy(_policy_report(evidence=evidence, safety_ready=False))
    assert decision["model_status"] == "approved_for_shadow"
    assert ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH in decision["production_evidence_reason_codes"]


def test_closed_beta_reasons_are_advisory_not_top_level_blocking_reason(monkeypatch):
    state = _state_from_meta(_legacy_closed_beta_blocked_meta())
    assert state["closedBetaGateRequired"] is False
    assert state["closedBetaGateBlocking"] is False
    assert "closed_beta_safety_gate" not in state["failedProductionGates"]
    assert not any(str(item).startswith("coverage_") for item in state["failedProductionGates"])


def test_protected_lock_reason_does_not_say_blocked_by_closed_beta_in_advisory_mode(monkeypatch):
    state = _state_from_meta(_legacy_closed_beta_blocked_meta())
    assert "blocked by closed-beta safety gate" not in state["approvalReasonText"]
    assert "blocked by closed-beta safety gate" not in state["reason_text"]
    assert "advisory" in state["approvalReasonText"].lower()


def test_protected_lock_reason_says_closed_beta_required_only_in_required_mode(monkeypatch):
    monkeypatch.setenv("BIOAUTH_CLOSED_BETA_GATE_MODE", "required")
    decision = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False))
    state = _state_from_meta(decision)
    assert state["closedBetaGateRequired"] is True
    assert "closed-beta safety gate" in state["approvalReasonText"]


def test_qml_does_not_compute_closed_beta_gate_or_production_readiness():
    qml_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (ROOT / "qml").rglob("*.qml"))
    forbidden = [
        "property bool productionReady",
        "property bool protectedSessionsAvailable",
        "property bool closed_beta_gate_required",
        "property bool closedBetaGateRequired",
        "function closedBeta",
        "function productionReady",
    ]
    assert not any(token in qml_text for token in forbidden)


def test_existing_production_approval_core_gate_flow_unchanged(monkeypatch):
    evidence = _passing_evidence()
    decision = evaluate_model_policy(_policy_report(evidence=evidence, safety_ready=True))
    decision["production_evidence"] = evidence
    assert decision["model_status"] == "approved_for_production"
    state = _state_from_meta(decision, runtime_ok=False)
    # Runtime validation is a backend production-eligibility gate. A passing
    # production evidence report may make the candidate available for explicit
    # user approval, but it must not mark production approval as passed while
    # the active runtime bundle is invalid or missing.
    assert state["productionApprovalPassed"] is False
    assert state["productionEligibilityPassed"] is False
    assert any(str(item).startswith("runtime_validation_") for item in state["productionEligibilityBlockers"])
    assert state["productionReadyPendingUserApproval"] is True
    assert state["productionReady"] is False
    assert state["protectedSessionsAvailable"] is False


def test_existing_shadow_evidence_collection_flow_unchanged():
    helper = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    refresh = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text(encoding="utf-8")
    assert "shadow_evidence" in helper
    assert "start_protected_session" not in helper[helper.find("start_shadow_evidence_monitor"): helper.find("def stop_shadow_evidence_monitor")]
    assert "BIOAUTH_SHADOW_EVIDENCE_ONLY" in refresh


def test_no_raw_biometric_data_in_closed_beta_observability(monkeypatch):
    state = _state_from_meta(evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False)))
    text = repr({k: v for k, v in state.items() if "closedBeta" in k or "closed_beta" in k})
    forbidden = ["raw_keyboard", "raw_mouse", "feature_vector", "raw_samples", "raw_event"]
    assert not any(token in text for token in forbidden)
