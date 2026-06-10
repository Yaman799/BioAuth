from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation_core.production_evidence import ProductionEvidenceReasonCode
from metadata_core.production_evidence_pipeline import (
    ProductionEvidenceRecord,
    aggregate_evidence_records,
    append_evidence_record,
    load_shadow_evidence_summary_for_candidate,
)
from metadata_core.production_approval import build_production_eligibility_state


def _record(*, candidate="sha256:current", schema="runtime-v1", window="w1", baseline_decision="trusted") -> dict:
    return ProductionEvidenceRecord(
        window_id=window,
        user_id="alice",
        candidate_artifact_digest=candidate,
        baseline_artifact_digest="sha256:baseline" if baseline_decision else "",
        runtime_schema_version=schema,
        feature_schema_version=schema,
        candidate_decision="trusted",
        baseline_decision=baseline_decision,
        candidate_risk_bucket="low",
        baseline_risk_bucket="low" if baseline_decision else "unknown",
        candidate_would_lock_if_production=False,
        baseline_would_lock_if_production=False,
        is_trusted_window=True,
        feature_quality_ok=True,
        schema_ok=True,
        source="runtime_shadow_evidence",
    ).to_dict()


def test_stale_candidate_digest_records_are_ignored_not_gate_blocking() -> None:
    summary = aggregate_evidence_records(
        [_record(candidate="sha256:old", window="old"), _record(candidate="sha256:current", window="new")],
        candidate_artifact_digest="sha256:current",
        baseline_artifact_digest="sha256:baseline",
        runtime_schema_version="runtime-v1",
    )

    assert summary["pipeline_record_count"] == 2
    assert summary["pipeline_accepted_record_count"] == 1
    assert summary["pipeline_ignored_candidate_digest_record_count"] == 1
    assert ProductionEvidenceReasonCode.CANDIDATE_DIGEST_MISMATCH not in summary["pipeline_reason_codes"]
    assert len(summary["model_comparison_windows"]) == 1


def test_all_stale_candidate_digest_records_do_not_report_mismatch_reason() -> None:
    summary = aggregate_evidence_records(
        [_record(candidate="sha256:old", window="old")],
        candidate_artifact_digest="sha256:current",
        baseline_artifact_digest="sha256:baseline",
        runtime_schema_version="runtime-v1",
    )

    assert summary["pipeline_accepted_record_count"] == 0
    assert summary["pipeline_ignored_candidate_digest_record_count"] == 1
    assert ProductionEvidenceReasonCode.CANDIDATE_DIGEST_MISMATCH not in summary["pipeline_reason_codes"]
    assert summary["model_comparison_windows"] == []


def test_shadow_summary_exposes_identity_filter_without_sensitive_data(monkeypatch, tmp_path: Path) -> None:
    from metadata_core import production_evidence_pipeline as pipe

    monkeypatch.setattr(pipe.paths, "evidence_dir", lambda: str(tmp_path / "evidence"))
    append_evidence_record("alice", ProductionEvidenceRecord.from_dict(_record(candidate="sha256:old", window="old")))
    append_evidence_record("alice", ProductionEvidenceRecord.from_dict(_record(candidate="sha256:current", window="new")))

    summary = load_shadow_evidence_summary_for_candidate(
        "alice",
        candidate_artifact_digest="sha256:current",
        baseline_artifact_digest="sha256:baseline",
        runtime_schema_version="runtime-v1",
    )

    assert summary["records_total"] == 2
    assert summary["records_accepted"] == 1
    assert summary["records_ignored_for_candidate_digest"] == 1
    assert summary["identity_filter"]["current_candidate_artifact_digest"] == "sha256:current"
    assert "raw" not in str(summary).lower()


def test_production_eligibility_treats_old_nested_evidence_as_stale_not_digest_mismatch(tmp_path: Path) -> None:
    state = build_production_eligibility_state(
        candidate_paths={"model": str(tmp_path / "missing.pkl")},
        candidate_metadata={"model_status": "approved_for_production", "artifact_digest": "sha256:current"},
        evaluation_report={
            "production_evidence": {
                "schema_version": 1,
                "candidate_artifact_digest": "sha256:old",
                "baseline_artifact_digest": "sha256:baseline",
                "evaluation_report_digest": "sha256:report",
                "runtime_schema_version": "runtime-v1",
                "model_agreement": {},
                "post_unlock_evidence": {},
                "confirmed_intruder_evidence": {},
                "runtime_safety": {},
                "gate": {"status": "partial", "promotion_effect": "shadow_only", "reason_codes": ["production_evidence_partial"]},
            }
        },
        runtime_validation={"ok": False, "reason": "runtime_validation_missing", "metadata": {"runtime_schema_version": "runtime-v1"}},
        runtime_paths={},
    )

    assert "candidate_digest_mismatch" not in state["blockers"]
    assert "production_evidence_stale_for_previous_candidate" in state["blockers"]
