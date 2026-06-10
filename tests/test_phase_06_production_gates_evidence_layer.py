from __future__ import annotations

import json
import os
import pickle
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation_core.production_evidence import build_production_evidence_report
from metadata_core.production_approval import build_production_approval_state, build_production_eligibility_state
from metadata_core import auto_promotion
from metadata_core.constants import ACTIVE_WINDOW_SCALES, FEATURE_SCHEMA_VERSION, FEATURE_WINDOW_STRATEGY
from metadata_core.paths import _active_runtime_pointer_path, _user_model_paths
from security import atomic_write_text, save_metadata_hash, save_model_hash

TMP_HOME = tempfile.mkdtemp(prefix="bioauth_phase06_")
os.environ["BIOAUTH_HOME"] = TMP_HOME


def _security_helpers():
    import security as _security

    return _security


def _cleanup() -> None:
    import shutil
    shutil.rmtree(TMP_HOME, ignore_errors=True)


def _passing_evidence(*, candidate: str = "sha256:candidate-a", runtime_schema: str = "runtime-schema-v1") -> dict:
    return build_production_evidence_report(
        candidate_artifact_digest=candidate,
        baseline_artifact_digest="sha256:baseline-a",
        evaluation_report_digest="sha256:evaluation-a",
        runtime_schema_version=runtime_schema,
        model_comparison_windows=[{"window_id": f"m{idx}", "candidate_decision": "trusted", "baseline_decision": "trusted", "trusted_window": True} for idx in range(4)],
        post_unlock_windows=[{"window_id": f"u{idx}", "trusted_window": True, "warning_triggered": False, "simulated_false_lock": False, "feature_quality_ok": True} for idx in range(3)],
        confirmed_intruder_events=[],
        runtime_decision_summaries=[{"decision_id": f"r{idx}", "truth": "owner", "candidate_decision": "trusted", "unknown": False, "simulated_false_lock": False, "feature_quality_ok": True} for idx in range(4)],
    ).to_dict()


def _partial_evidence() -> dict:
    report = _passing_evidence()
    report["gate"] = {"status": "partial", "promotion_effect": "shadow_only", "reason_codes": ["production_evidence_partial"]}
    return report


def _metadata(*, evidence: dict | None = None, candidate: str = "sha256:candidate-a", runtime_schema: str = "runtime-schema-v1") -> dict:
    return {
        "model_status": "approved_for_production",
        "candidate_artifact_digest": candidate,
        "baseline_artifact_digest": "sha256:baseline-a",
        "evaluation_report_digest": "sha256:evaluation-a",
        "runtime_schema_version": runtime_schema,
        "rollback_ready": True,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_window_strategy": FEATURE_WINDOW_STRATEGY,
        "active_window_scales": list(ACTIVE_WINDOW_SCALES),
        "policy_details": {
            "gate_results": {"minimum_support": True, "f1": True, "far": True, "frr": True, "precision": True, "recall": True, "auc": True},
            "safety_gate_results": {"safety_metrics_present": True, "false_lock_count": True, "warning_per_hour": True, "low_quality_decision_rate": True, "data_coverage": True, "raw_data_absent": True},
        },
        "rollout_details": {"allowed_modes": ["classic"], "rollback_to_classic_on_failure": True},
        "production_evidence": evidence if evidence is not None else _passing_evidence(candidate=candidate, runtime_schema=runtime_schema),
    }


def _runtime(ok: bool = True, *, metadata: dict | None = None, reason: str = "ok") -> dict:
    return {"ok": ok, "reason": reason if ok else reason or "runtime_bundle_invalid", "metadata": metadata or {}}


def test_missing_evidence_fails_closed() -> None:
    meta = _metadata(evidence={})
    state = build_production_eligibility_state(candidate_metadata=meta, runtime_validation=_runtime(metadata=meta), rollback_available=True)
    assert state["eligible"] is False
    assert any(item.startswith("production_evidence_") for item in state["blockers"])
    assert state["protectedSessionsAvailable"] is False
    assert state["activeRuntimePointerWritten"] is False


def test_mismatched_candidate_digest_fails_closed() -> None:
    meta = _metadata(evidence=_passing_evidence(candidate="sha256:evidence-candidate"), candidate="sha256:metadata-candidate")
    state = build_production_eligibility_state(candidate_metadata=meta, runtime_validation=_runtime(metadata=meta), rollback_available=True)
    assert state["eligible"] is False
    assert "candidate_digest_mismatch" in state["blockers"]
    assert state["candidateDigestMatched"] is False


def test_incomplete_gates_fail_closed() -> None:
    meta = _metadata(evidence=_partial_evidence())
    state = build_production_eligibility_state(candidate_metadata=meta, runtime_validation=_runtime(metadata=meta), rollback_available=True)
    assert state["eligible"] is False
    assert "production_evidence_partial" in state["blockers"]
    assert state["promotionEffect"] == "shadow_only"


def test_runtime_validation_missing_fails_closed_even_with_passing_evidence() -> None:
    meta = _metadata()
    state = build_production_eligibility_state(candidate_metadata=meta, runtime_validation={}, rollback_available=True)
    assert state["eligible"] is False
    assert "runtime_validation_missing" in state["blockers"]
    assert state["runtimeValidationRequired"] is True


def test_rollback_readiness_missing_fails_closed() -> None:
    meta = _metadata()
    meta.pop("rollback_ready", None)
    meta["rollout_details"] = {"allowed_modes": ["classic"]}
    state = build_production_eligibility_state(candidate_metadata=meta, runtime_validation=_runtime(metadata=meta))
    assert state["eligible"] is False
    assert "rollback_readiness_missing" in state["blockers"]


def test_passing_artifact_matched_evidence_is_backend_eligible_only() -> None:
    meta = _metadata()
    state = build_production_eligibility_state(candidate_metadata=meta, runtime_validation=_runtime(metadata=meta), rollback_available=True)
    assert state["eligible"] is True
    assert state["candidateDigestMatched"] is True
    assert state["runtimeValidationOk"] is True
    assert state["rollbackReady"] is True
    assert state["protectedSessionsAvailable"] is False
    assert state["activeRuntimePointerWritten"] is False


def test_evidence_gate_pass_alone_does_not_unlock_protected_sessions() -> None:
    meta = _metadata()
    state = build_production_approval_state(candidate_paths={}, candidate_metadata=meta, runtime_validation={"ok": False, "reason": "runtime_bundle_invalid", "metadata": meta})
    assert state["productionEvidencePassed"] is True
    assert state["productionEligibilityPassed"] is False
    assert state["protectedSessionsAvailable"] is False
    assert state["productionReady"] is False
    assert "runtime_validation_runtime_bundle_invalid" in state["productionEligibilityBlockers"]


def test_safe_auto_promotion_blocks_mismatched_artifact_before_pointer_write() -> None:
    user = "phase06_digest_mismatch"
    candidate_paths = _user_model_paths(user)
    os.makedirs(candidate_paths["base"], exist_ok=True)
    Path(candidate_paths["model"]).write_bytes(pickle.dumps({"kind": "phase06"}))
    _security_helpers().save_model_hash(candidate_paths["model"])
    meta = _metadata(evidence=_passing_evidence(candidate="sha256:evidence-only"), candidate="sha256:metadata-other")
    _security_helpers().atomic_write_text(candidate_paths["metadata"], json.dumps(meta, indent=2))
    _security_helpers().save_metadata_hash(candidate_paths["metadata"])
    _security_helpers().atomic_write_text(candidate_paths["evaluation_report"], json.dumps({"primary_evaluation": "candidate"}, indent=2))
    _security_helpers().atomic_write_text(candidate_paths["evaluation_summary"], "summary\n")
    result = auto_promotion.safe_auto_promote_production_bundle(user, settings={"auto_promote_when_production_safe_enabled": True}, runtime_validation={"ok": False, "reason": "runtime_pointer_missing"})
    assert result["ok"] is False
    assert result["changed"] is False
    assert "production_eligibility_blocked:candidate_digest_mismatch" in result["reason"]
    assert result["protectedSessionsAvailable"] is False
    assert not os.path.exists(_active_runtime_pointer_path(user))


def test_qml_still_does_not_compute_production_eligibility() -> None:
    qml = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (ROOT / "qml").rglob("*.qml"))
    for needle in ["productionEligibilityPassed:", "production_eligibility_passed:", "function productionEligibility", "var productionEligibility", "productionEvidencePassed &&"]:
        assert needle not in qml


if __name__ == "__main__":
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
        print("9 phase 06 production evidence layer tests passed", flush=True)
    finally:
        _cleanup()
    os._exit(0)
