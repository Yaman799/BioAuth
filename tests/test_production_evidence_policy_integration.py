from __future__ import annotations

from pathlib import Path

from evaluation_core.candidate import evaluate_candidate_model
import evaluation_core.candidate as candidate_module
from evaluation_core.production_evidence import (
    ProductionEvidencePromotionEffect,
    ProductionEvidenceReasonCode,
    ProductionEvidenceStatus,
    build_production_evidence_report,
)
from metadata_core.auto_promotion import auto_promotion_block_reason
from metadata_core.production_approval import build_production_approval_state
from model_policy import evaluate_model_policy


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
        candidate_artifact_digest="sha256:candidate",
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
        candidate_artifact_digest="sha256:candidate",
    ).to_dict()


def _failed_evidence():
    return build_production_evidence_report(
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


def _policy_report(*, evidence, f1=0.82, far=0.01, frr=0.02, safety_ready=True):
    return {
        "primary_evaluation": "candidate_bundle",
        "evaluations": {
            "candidate_bundle": {
                "metrics": {
                    "session_count": 8,
                    "legitimate_session_count": 6,
                    "intruder_session_count": 2,
                    "auc": 0.92,
                    "f1": f1,
                    "far": far,
                    "frr": frr,
                    "precision": 0.91,
                    "recall": 0.90,
                }
            }
        },
        "safety_metrics": {
            "false_lock_count": 0,
            "warning_per_hour": 0.0,
            "low_quality_decision_rate": 0.0,
            "raw_biometric_data_included": False,
            "data_coverage": {"closed_beta_ready": bool(safety_ready), "missing": [] if safety_ready else ["windows"]},
        },
        "production_evidence": evidence,
    }


def _candidate_paths():
    return {"metadata": "", "evaluation_report": "", "evaluation_summary": ""}


def test_candidate_evaluation_report_includes_production_evidence_missing_when_no_summaries(tmp_path):
    class StubFacade:
        EVALUATION_SCHEMA_VERSION = "test-eval-v1"
        BETA_EVALUATION_REPORT_FILENAME = "closed_beta_report.md"

        @staticmethod
        def load_model(path):
            return object()

        @staticmethod
        def load_metadata(path):
            return {"feature_schema_version": "test-schema-v1"}

        @staticmethod
        def load_classifier(path):
            return None

        @staticmethod
        def _unique_paths(paths):
            return list(paths or [])

        @staticmethod
        def plan_session_holdout_split(positive, negative):
            return {}

        @staticmethod
        def plan_session_cross_validation_splits(positive, negative):
            return []

        @staticmethod
        def _emit_evaluation_progress(*args, **kwargs):
            return None

        @staticmethod
        def evaluate_model_bundle(*args, **kwargs):
            return {
                "metrics": {
                    "session_count": 4,
                    "legitimate_session_count": 4,
                    "intruder_session_count": 0,
                    "f1": 0.75,
                    "far": 0.0,
                    "frr": 0.05,
                    "precision": 1.0,
                    "recall": 0.95,
                },
                "session_results": [],
            }

        @staticmethod
        def _evaluate_current_production_bundle(**kwargs):
            return None

        @staticmethod
        def _now_timestamp():
            return "2026-05-01 00:00:00"

        @staticmethod
        def _safe_session_name(path):
            return Path(path).name

        @staticmethod
        def calculate_user_facing_safety_metrics(*args, **kwargs):
            return {
                "false_lock_count": 0,
                "warning_per_hour": 0.0,
                "low_quality_decision_rate": 0.0,
                "raw_biometric_data_included": False,
                "data_coverage": {"closed_beta_ready": True},
            }

        @staticmethod
        def _build_summary_markdown(report):
            return "# summary"

    original = candidate_module._facade
    model_file = tmp_path / "model.pkl"
    metadata_file = tmp_path / "metadata.json"
    classifier_file = tmp_path / "classifier.pkl"
    model_file.write_bytes(b"candidate-model")
    try:
        candidate_module._facade = lambda: StubFacade
        report = evaluate_candidate_model(
            positive_sessions=["session-a", "session-b", "session-c", "session-d"],
            negative_sessions=[],
            model_file=str(model_file),
            metadata_file=str(metadata_file),
            classifier_file=str(classifier_file),
            allow_temp_retraining=False,
            training_selection={},
        )
    finally:
        candidate_module._facade = original

    evidence = report["production_evidence"]
    assert evidence["candidate_artifact_digest"].startswith("sha256:")
    assert evidence["runtime_schema_version"] == "test-schema-v1"
    assert evidence["gate"]["status"] == ProductionEvidenceStatus.PARTIAL.value
    assert evidence["gate"]["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value
    assert ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PARTIAL in evidence["gate"]["reason_codes"]


def test_evidence_pass_existing_policy_fail_blocks_production():
    decision = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), f1=0.10, far=0.40))

    assert decision["model_status"] == "rejected"
    assert decision["policy_details"]["production_evidence_gate_results"]["allows_production_eligibility"] is True
    assert "offline" in decision["approval_reason"].lower() or "trade-off" in decision["approval_reason"].lower()


def test_evidence_pass_runtime_invalid_blocks_production():
    meta = evaluate_model_policy(_policy_report(evidence=_passing_evidence()))
    meta["production_evidence"] = _passing_evidence()
    meta["model_status"] = "approved_for_production"

    state = build_production_approval_state(
        candidate_paths=_candidate_paths(),
        candidate_metadata=meta,
        runtime_validation={"ok": False, "reason": "runtime_bundle_invalid", "metadata": {}},
    )

    assert state["productionEvidencePassed"] is True
    assert state["productionEligibilityPassed"] is False
    assert state["productionApprovalPassed"] is False
    assert state["productionReady"] is False
    assert state["protectedSessionsAvailable"] is False
    assert state["reason_code"] == "runtime_bundle_invalid"


def test_evidence_partial_keeps_shadow_only():
    decision = evaluate_model_policy(_policy_report(evidence=_partial_evidence()))

    assert decision["model_status"] == "approved_for_shadow"
    assert decision["policy_details"]["production_evidence_gate_results"]["status"] == ProductionEvidenceStatus.PARTIAL.value
    assert decision["policy_details"]["production_evidence_gate_results"]["allows_production_eligibility"] is False
    assert "shadow validation only" in decision["approval_reason"]


def test_evidence_fail_blocks_production():
    decision = evaluate_model_policy(_policy_report(evidence=_failed_evidence()))

    assert decision["model_status"] == "rejected"
    assert decision["policy_details"]["production_evidence_gate_results"]["status"] == ProductionEvidenceStatus.FAIL.value
    assert ProductionEvidenceReasonCode.CONFIRMED_INTRUDER_LOW_RISK in decision["production_evidence_reason_codes"]


def test_evidence_pass_all_existing_gates_required_for_production(monkeypatch):
    passing = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=True))
    advisory_missing = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False))

    assert passing["model_status"] == "approved_for_production"
    assert passing["policy_details"]["production_evidence_gate_results"]["allows_production_eligibility"] is True
    assert advisory_missing["model_status"] == "approved_for_production"
    assert advisory_missing["policy_details"]["closed_beta_gate_required"] is False
    assert advisory_missing["policy_details"]["closed_beta_gate_blocking"] is False
    assert "closed-beta safety gate" not in advisory_missing["approval_reason"]

    monkeypatch.setenv("BIOAUTH_CLOSED_BETA_GATE_MODE", "required")
    safety_blocked = evaluate_model_policy(_policy_report(evidence=_passing_evidence(), safety_ready=False))
    assert safety_blocked["model_status"] == "approved_for_shadow"
    assert safety_blocked["policy_details"]["production_evidence_gate_results"]["allows_production_eligibility"] is True
    assert safety_blocked["policy_details"]["closed_beta_gate_required"] is True
    assert safety_blocked["policy_details"]["closed_beta_gate_blocking"] is True
    assert "closed-beta safety gate" in safety_blocked["approval_reason"]


def test_approved_for_shadow_never_unlocks_protected_sessions():
    meta = evaluate_model_policy(_policy_report(evidence=_partial_evidence()))
    meta["production_evidence"] = _partial_evidence()
    meta["model_status"] = "approved_for_shadow"

    state = build_production_approval_state(
        candidate_paths=_candidate_paths(),
        candidate_metadata=meta,
        runtime_validation={"ok": True, "reason": "ok", "metadata": {}},
        shadow_status={"windows_collected": 0, "windows_required": 3},
    )

    assert state["productionReady"] is False
    assert state["protectedSessionsAvailable"] is False
    assert state["protected_sessions_available"] is False
    assert state["candidate_status"] == "approved_for_shadow"


def test_auto_promotion_does_not_promote_evidence_only_candidate():
    evidence_only_shadow_meta = {
        "model_status": "approved_for_shadow",
        "production_evidence": _passing_evidence(),
        "policy_details": {"gate_results": {}, "safety_gate_results": {}},
    }
    unsafe_missing_evidence_meta = {
        "model_status": "approved_for_production",
        "policy_details": {"gate_results": {}, "safety_gate_results": {}},
    }

    shadow_reason = auto_promotion_block_reason(
        settings={"auto_promote_when_production_safe_enabled": True},
        candidate_metadata=evidence_only_shadow_meta,
        runtime_validation={"ok": False},
    )
    missing_reason = auto_promotion_block_reason(
        settings={"auto_promote_when_production_safe_enabled": True},
        candidate_metadata=unsafe_missing_evidence_meta,
        runtime_validation={"ok": False},
    )

    assert shadow_reason == "model_not_approved_for_production"
    assert missing_reason == "production_evidence_missing"
