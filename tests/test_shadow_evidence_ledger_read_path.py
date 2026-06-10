from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation_core.production_evidence import ProductionEvidenceStatus
from metadata_core import production_evidence_pipeline as pipe
from shadow_core.background_contracts import shadow_evidence_ledger_path


def _set_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))


def _record(window_id: str = "window-1") -> pipe.ProductionEvidenceRecord:
    return pipe.ProductionEvidenceRecord(
        window_id=window_id,
        user_id="owner",
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        runtime_schema_version="runtime-v1",
        candidate_decision="trusted",
        baseline_decision="trusted",
        candidate_risk_bucket="low",
        baseline_risk_bucket="low",
        is_trusted_window=True,
        trusted_anchor_type="post_unlock",
        is_post_unlock_window=True,
        feature_quality_ok=True,
        source="shadow_evidence_monitor",
    )


def test_default_production_evidence_ledger_is_still_read(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    pipe.append_evidence_record("owner", _record("production-ledger-window"))

    records = pipe.read_all_evidence_records_for_user("owner")
    report = pipe.build_production_evidence_report_for_user(
        "owner",
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        runtime_schema_version="runtime-v1",
    )

    assert [record["window_id"] for record in records] == ["production-ledger-window"]
    assert report.post_unlock_evidence.trusted_window_count == 1


def test_shadow_evidence_ledger_only_record_is_visible_to_report_and_summary(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    shadow_ledger = shadow_evidence_ledger_path("owner")
    pipe.append_runtime_monitor_evidence_record(
        user_id="owner",
        state={
            "session_id": "shadow-ledger-window",
            "runtime_telemetry_seq": 1,
            "session_kind": "shadow_evidence",
            "runtime_mode": "shadow_evidence",
            "evidence_source": "shadow_evidence_monitor",
            "model_decision": "legit",
            "risk": 8,
            "post_unlock_trusted_window": True,
            "baseline_decision": "trusted",
            "baseline_risk_bucket": "low",
            "runtime_quality_ok_windows": 1,
            "runtime_low_quality_windows": 0,
        },
        runtime={"metadata": {"runtime_schema_version": "runtime-v1", "artifact_digest": "sha256:candidate"}},
        prediction={"final": "legit"},
        ledger_path=shadow_ledger,
    )

    assert not Path(pipe.evidence_ledger_path("owner")).exists()
    assert Path(shadow_ledger).exists()

    report = pipe.build_production_evidence_report_for_user(
        "owner",
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        runtime_schema_version="runtime-v1",
    )
    summary = pipe.load_shadow_evidence_summary_for_candidate(
        "owner",
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        runtime_schema_version="runtime-v1",
    )

    assert report.post_unlock_evidence.trusted_window_count == 1
    assert summary["records_total"] == 1
    assert summary["records_accepted"] == 1
    assert summary["windows_collected"] == 1
    assert summary["quality_ok_windows"] == 1
    assert summary["production_evidence"]["gate"]["status"] != ProductionEvidenceStatus.PASS.value


def test_missing_shadow_evidence_ledger_returns_safely(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    pipe.append_evidence_record("owner", _record("production-only-window"))
    shadow_path = Path(shadow_evidence_ledger_path("owner"))

    assert not shadow_path.exists()
    records = pipe.read_all_evidence_records_for_user("owner")
    summary = pipe.load_shadow_evidence_summary_for_candidate(
        "owner",
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        runtime_schema_version="runtime-v1",
    )

    assert [record["window_id"] for record in records] == ["production-only-window"]
    assert summary["records_total"] == 1


def test_duplicate_records_across_ledgers_are_reported_once(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    record = _record("duplicate-window")
    pipe.append_evidence_record("owner", record)
    pipe.append_evidence_record("owner", record, ledger_path=shadow_evidence_ledger_path("owner"))

    records = pipe.read_all_evidence_records_for_user("owner")
    summary = pipe.load_shadow_evidence_summary_for_candidate(
        "owner",
        candidate_artifact_digest="sha256:candidate",
        baseline_artifact_digest="sha256:baseline",
        runtime_schema_version="runtime-v1",
    )

    assert [record["window_id"] for record in records] == ["duplicate-window"]
    assert summary["records_total"] == 1
