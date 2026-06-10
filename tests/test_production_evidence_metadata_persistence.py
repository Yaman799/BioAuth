from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from evaluation_core.production_evidence import build_production_evidence_report
from metadata_core.production_approval import build_production_eligibility_state
from training_core import pipeline


def _passing_evidence(*, candidate: str = "sha256:candidate-a", runtime_schema: str = "runtime-schema-v1") -> dict:
    return build_production_evidence_report(
        candidate_artifact_digest=candidate,
        baseline_artifact_digest="sha256:baseline-a",
        evaluation_report_digest="sha256:evaluation-a",
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


def _metadata(*, evidence: dict | None = None, candidate: str = "sha256:candidate-a") -> dict:
    meta = {
        "model_status": "approved_for_production",
        "candidate_artifact_digest": candidate,
        "runtime_schema_version": "runtime-schema-v1",
        "rollback_ready": True,
        "rollout_details": {"rollback_to_classic_on_failure": True},
    }
    if evidence is not None:
        meta["production_evidence"] = evidence
    return meta


def _runtime(meta: dict) -> dict:
    return {"ok": True, "reason": "ok", "metadata": dict(meta)}


def test_training_pipeline_persists_artifact_matched_production_evidence_metadata(tmp_path, monkeypatch):
    paths = {
        "base": str(tmp_path),
        "model": str(tmp_path / "model.pkl"),
        "metadata": str(tmp_path / "metadata.json"),
        "classifier": str(tmp_path / "classifier.pkl"),
        "evaluation_report": str(tmp_path / "evaluation_report.json"),
        "evaluation_summary": str(tmp_path / "evaluation_summary.md"),
    }
    Path(paths["model"]).write_bytes(b"candidate-model")
    Path(paths["classifier"]).write_bytes(b"classifier")
    Path(paths["metadata"]).write_text(json.dumps({"deep_runtime": {}, "candidate_artifact_digest": "sha256:candidate-a"}), encoding="utf-8")
    Path(paths["evaluation_report"]).write_text("{}", encoding="utf-8")
    Path(paths["evaluation_summary"]).write_text("# summary\n", encoding="utf-8")

    evaluation_report = {
        "schema_version": "eval-v1",
        "primary_evaluation": "candidate_bundle",
        "production_evidence": _passing_evidence(candidate="sha256:candidate-a"),
    }
    policy_decision = {
        "model_status": "approved_for_production",
        "policy_version": "policy-v1",
        "approval_reason": "passed",
        "policy_metrics": {},
        "policy_gate": {"passed": True},
        "rollout_status": "classic_only_ready",
        "rollout_details": {"production_decision_enabled": False, "rollback_to_classic_on_failure": True},
    }

    artifact_integrity = types.ModuleType("artifact_integrity")
    artifact_integrity.load_metadata = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
    model_evaluation = types.ModuleType("model_evaluation")
    model_evaluation.evaluate_candidate_model = lambda **kwargs: evaluation_report
    model_policy = types.ModuleType("model_policy")
    model_policy.evaluate_model_policy = lambda report: policy_decision
    monkeypatch.setitem(sys.modules, "artifact_integrity", artifact_integrity)
    monkeypatch.setitem(sys.modules, "model_evaluation", model_evaluation)
    monkeypatch.setitem(sys.modules, "model_policy", model_policy)

    writes: list[str] = []

    def atomic_write_text(path: str, text: str) -> None:
        Path(path).write_text(text, encoding="utf-8")
        writes.append(path)

    result = pipeline._evaluate_and_publish_candidate(
        safe="owner",
        paths=paths,
        positives=["p1", "p2", "p3"],
        negative_sessions=["n1"],
        selection_summary={"selection_version": "selection-v1", "negative_pool": {}},
        report_progress_fn=lambda *args, **kwargs: None,
        stage_progress_factory=lambda *args, **kwargs: (lambda *a, **k: None),
        allow_expensive_offline_evaluation_fn=lambda positives, negatives: False,
        atomic_write_text_fn=atomic_write_text,
        save_metadata_hash_fn=lambda path: None,
        publish_initial_production_bundle_if_approved_fn=lambda *args, **kwargs: False,
        context_routing_version="context-v1",
        logger=types.SimpleNamespace(warning=lambda *args, **kwargs: None),
    )

    assert result["evaluation_report"] is evaluation_report
    persisted = json.loads(Path(paths["metadata"]).read_text(encoding="utf-8"))
    assert paths["metadata"] in writes
    assert persisted["production_evidence"]["candidate_artifact_digest"] == "sha256:candidate-a"
    assert persisted["candidate_artifact_digest"] == "sha256:candidate-a"
    assert persisted["baseline_artifact_digest"] == "sha256:baseline-a"
    assert persisted["evaluation_report_digest"] == "sha256:evaluation-a"
    assert persisted["runtime_schema_version"] == "runtime-schema-v1"


def test_metadata_persisted_evidence_makes_backend_eligibility_computable_without_in_memory_report():
    meta = _metadata(evidence=_passing_evidence())
    state = build_production_eligibility_state(candidate_metadata=meta, evaluation_report={}, runtime_validation=_runtime(meta), rollback_available=True)

    assert state["eligible"] is True
    assert state["candidateDigestMatched"] is True
    assert state["productionEligibilityPassed"] is True
    assert state["protectedSessionsAvailable"] is False
    assert state["activeRuntimePointerWritten"] is False


def test_metadata_evidence_candidate_digest_mismatch_fails_closed():
    meta = _metadata(evidence=_passing_evidence(candidate="sha256:evidence-candidate"), candidate="sha256:metadata-candidate")
    state = build_production_eligibility_state(candidate_metadata=meta, evaluation_report={}, runtime_validation=_runtime(meta), rollback_available=True)

    assert state["eligible"] is False
    assert "candidate_digest_mismatch" in state["blockers"]
    assert state["candidateDigestMatched"] is False


def test_missing_metadata_production_evidence_fails_closed():
    meta = _metadata(evidence=None)
    state = build_production_eligibility_state(candidate_metadata=meta, evaluation_report={}, runtime_validation=_runtime(meta), rollback_available=True)

    assert state["eligible"] is False
    assert any(item.startswith("production_evidence_") for item in state["blockers"])
    assert state["protectedSessionsAvailable"] is False


def test_raw_behavioral_payload_is_not_persisted_to_candidate_metadata():
    unsafe = _passing_evidence()
    unsafe["raw_keyboard_events"] = [{"key": "secret"}]

    fields = pipeline._production_evidence_metadata_fields_from_report({"production_evidence": unsafe})

    assert fields == {}


def test_existing_metadata_artifact_identity_is_preserved_on_evidence_mismatch():
    metadata = {"candidate_artifact_digest": "sha256:metadata-candidate"}
    fields = pipeline._production_evidence_metadata_fields_from_report(
        {"production_evidence": _passing_evidence(candidate="sha256:evidence-candidate")}
    )

    pipeline._merge_production_evidence_metadata_fields(metadata, fields)

    assert metadata["candidate_artifact_digest"] == "sha256:metadata-candidate"
    assert metadata["production_evidence"]["candidate_artifact_digest"] == "sha256:evidence-candidate"
