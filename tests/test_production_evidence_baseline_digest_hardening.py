from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation_core.production_evidence import ProductionEvidenceReasonCode
from metadata_core.production_evidence_pipeline import ProductionEvidenceRecord, aggregate_evidence_records


def _comparable_record(*, candidate: str = "sha256:candidate", baseline: str = "sha256:baseline", schema: str = "runtime-v1") -> dict:
    return ProductionEvidenceRecord(
        window_id="baseline-window",
        user_id="alice",
        candidate_artifact_digest=candidate,
        baseline_artifact_digest=baseline,
        runtime_schema_version=schema,
        candidate_decision="trusted",
        baseline_decision="trusted",
        candidate_risk_bucket="low",
        baseline_risk_bucket="low",
        candidate_would_lock_if_production=False,
        baseline_would_lock_if_production=False,
        is_trusted_window=True,
        feature_quality_ok=True,
        schema_ok=True,
        source="runtime_monitor",
    ).to_dict()


def test_matching_baseline_artifact_digest_counts_model_window() -> None:
    summary = aggregate_evidence_records(
        [_comparable_record()],
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        runtime_schema_version="runtime-v1",
    )

    assert summary["pipeline_accepted_record_count"] == 1
    assert len(summary["model_comparison_windows"]) == 1
    assert ProductionEvidenceReasonCode.BASELINE_ARTIFACT_DIGEST_MISMATCH not in summary["pipeline_reason_codes"]


def test_mismatching_baseline_artifact_digest_is_excluded_from_model_agreement() -> None:
    summary = aggregate_evidence_records(
        [_comparable_record(baseline="sha256:old-baseline")],
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:expected-baseline",
        runtime_schema_version="runtime-v1",
    )

    assert summary["pipeline_accepted_record_count"] == 1
    assert summary["model_comparison_windows"] == []
    assert len(summary["runtime_decision_summaries"]) == 1
    assert ProductionEvidenceReasonCode.BASELINE_ARTIFACT_DIGEST_MISMATCH in summary["pipeline_reason_codes"]
    assert ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA in summary["pipeline_reason_codes"]


def test_missing_baseline_artifact_digest_fails_closed_when_expected_digest_required() -> None:
    summary = aggregate_evidence_records(
        [_comparable_record(baseline="")],
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:expected-baseline",
        runtime_schema_version="runtime-v1",
    )

    assert summary["model_comparison_windows"] == []
    assert ProductionEvidenceReasonCode.BASELINE_ARTIFACT_DIGEST_MISMATCH in summary["pipeline_reason_codes"]
    assert ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA in summary["pipeline_reason_codes"]


def test_no_expected_baseline_artifact_digest_preserves_legacy_model_window_behavior() -> None:
    summary = aggregate_evidence_records(
        [_comparable_record(baseline="")],
        candidate_artifact_digest="sha256:candidate",
        runtime_schema_version="runtime-v1",
    )

    assert len(summary["model_comparison_windows"]) == 1
    assert ProductionEvidenceReasonCode.BASELINE_ARTIFACT_DIGEST_MISMATCH not in summary["pipeline_reason_codes"]


def test_candidate_digest_and_runtime_schema_validation_ignore_stale_identity_records() -> None:
    summary = aggregate_evidence_records(
        [_comparable_record(candidate="sha256:other", schema="runtime-old")],
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        runtime_schema_version="runtime-v1",
    )

    assert summary["pipeline_accepted_record_count"] == 0
    assert summary["model_comparison_windows"] == []
    assert summary["pipeline_ignored_candidate_digest_record_count"] == 1
    assert summary["pipeline_ignored_runtime_schema_record_count"] == 1
    assert ProductionEvidenceReasonCode.CANDIDATE_DIGEST_MISMATCH not in summary["pipeline_reason_codes"]
    assert ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH not in summary["pipeline_reason_codes"]
