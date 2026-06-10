from __future__ import annotations

import json
import os
import pickle
import shutil
from pathlib import Path

from evaluation_core.production_evidence import build_production_evidence_report
from metadata_core.auto_promotion import approve_production_model_switch, safe_auto_promote_production_bundle
from metadata_core.constants import ACTIVE_WINDOW_SCALES, FEATURE_SCHEMA_VERSION, FEATURE_WINDOW_STRATEGY
from metadata_core.paths import _active_runtime_pointer_path, _user_model_paths
from metadata_core.production_approval import build_production_approval_state
from metadata_core.runtime import resolve_active_runtime_paths_with_validation


def _security_helpers():
    import security as _security

    return _security


def _passing_evidence(candidate: str = "sha256:phase7-candidate") -> dict:
    return build_production_evidence_report(
        candidate_artifact_digest=candidate,
        baseline_artifact_digest="sha256:phase7-baseline",
        evaluation_report_digest="sha256:phase7-eval",
        runtime_schema_version="runtime-schema-v1",
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


def _metadata(*, status: str = "approved_for_production", candidate: str = "sha256:phase7-candidate", partial: bool = False) -> dict:
    evidence = _passing_evidence(candidate)
    if partial:
        evidence["gate"] = {"status": "partial", "promotion_effect": "shadow_only", "reason_codes": ["production_evidence_partial"]}
    return {
        "model_status": status,
        "bundle_role": "candidate",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_window_strategy": FEATURE_WINDOW_STRATEGY,
        "active_window_scales": list(ACTIVE_WINDOW_SCALES),
        "candidate_artifact_digest": candidate,
        "baseline_artifact_digest": "sha256:phase7-baseline",
        "evaluation_report_digest": "sha256:phase7-eval",
        "runtime_schema_version": "runtime-schema-v1",
        "rollback_ready": True,
        "policy_details": {
            "gate_results": {"minimum_support": True, "f1": True, "far": True, "frr": True, "precision": True, "recall": True, "auc": True},
            "safety_gate_results": {"safety_metrics_present": True, "false_lock_count": True, "warning_per_hour": True, "low_quality_decision_rate": True, "data_coverage": True, "raw_data_absent": True},
        },
        "rollout_details": {"allowed_modes": ["classic", "auto"], "rollback_to_classic_on_failure": True},
        "production_evidence": evidence,
    }


def _write_candidate_bundle(user: str, metadata: dict) -> dict:
    paths = _user_model_paths(user)
    shutil.rmtree(Path(paths["base"]).parent, ignore_errors=True)
    security = _security_helpers()
    os.makedirs(paths["base"], exist_ok=True)
    Path(paths["model"]).write_bytes(pickle.dumps({"kind": "phase7-model", "user": user}))
    security.save_model_hash(paths["model"])
    security.atomic_write_text(paths["metadata"], json.dumps(metadata, indent=2, ensure_ascii=False))
    security.save_metadata_hash(paths["metadata"])
    security.atomic_write_text(paths["evaluation_report"], json.dumps({"evaluation_report_digest": metadata["evaluation_report_digest"]}, indent=2))
    security.atomic_write_text(paths["evaluation_summary"], "phase7 evaluation summary\n")
    return paths


def test_candidate_training_success_is_not_production_readiness() -> None:
    state = build_production_approval_state(
        candidate_paths={},
        candidate_metadata=_metadata(status="approved_for_shadow"),
        runtime_validation={"ok": False, "reason": "model_not_approved_for_production"},
    )
    assert state["modelStatus"] == "approved_for_shadow"
    assert state["productionReady"] is False
    assert state["protectedSessionsAvailable"] is False
    assert state["productionApprovalPassed"] is False


def test_evidence_gate_success_without_runtime_validation_stays_pending_user_approval() -> None:
    metadata = _metadata()
    state = build_production_approval_state(
        candidate_paths={},
        candidate_metadata=metadata,
        runtime_validation={"ok": False, "reason": "runtime_pointer_missing", "metadata": metadata},
    )
    assert state["productionEvidencePassed"] is True
    assert state["productionReadyPendingUserApproval"] is True
    assert state["productionReady"] is False
    assert state["protectedSessionsAvailable"] is False
    assert "runtime_validation_runtime_pointer_missing" in state["productionEligibilityBlockers"]


def test_auto_path_reports_pending_user_approval_and_does_not_write_pointer() -> None:
    user = "phase7_gate_pending"
    metadata = _metadata()
    _write_candidate_bundle(user, metadata)
    result = safe_auto_promote_production_bundle(user, settings={"auto_promote_when_production_safe_enabled": True}, runtime_validation={"ok": False})
    assert result["reason"] == "production_ready_pending_user_approval"
    assert result["changed"] is False
    assert result["protectedSessionsAvailable"] is False
    assert not os.path.exists(_active_runtime_pointer_path(user))


def test_user_approved_exact_digest_is_required_before_protected_sessions_unlock() -> None:
    user = "phase7_gate_approval"
    metadata = _metadata()
    _write_candidate_bundle(user, metadata)
    wrong = approve_production_model_switch(user, "sha256:not-the-candidate", user_approved=True)
    assert wrong["ok"] is False
    assert wrong["reason"] == "candidate_digest_mismatch"
    assert not os.path.exists(_active_runtime_pointer_path(user))

    approved = approve_production_model_switch(user, metadata["candidate_artifact_digest"], user_approved=True)
    assert approved["ok"] is True
    assert approved["protectedSessionsAvailable"] is True
    paths, validation = resolve_active_runtime_paths_with_validation(user)
    assert paths is not None
    assert validation["ok"] is True
    assert validation["metadata"]["user_approved_model_switch"] is True


def test_partial_evidence_candidate_cannot_unlock_even_with_approved_status() -> None:
    metadata = _metadata(partial=True)
    state = build_production_approval_state(
        candidate_paths={},
        candidate_metadata=metadata,
        runtime_validation={"ok": True, "reason": "ok", "metadata": metadata},
        runtime_paths={"base": "/tmp/phase7-runtime"},
    )
    assert state["productionEvidencePassed"] is False
    assert state["productionReady"] is False
    assert state["protectedSessionsAvailable"] is False
    assert "production_evidence_partial" in state["productionEligibilityBlockers"]
