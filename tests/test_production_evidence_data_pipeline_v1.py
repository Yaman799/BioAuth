from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation_core.production_evidence import (
    ProductionEvidenceReasonCode,
    ProductionEvidenceStatus,
    contains_raw_biometric_fields,
)
from metadata_core.production_evidence_pipeline import (
    ProductionEvidenceRecord,
    aggregate_evidence_records,
    append_evidence_record,
    append_runtime_monitor_evidence_record,
    append_shadow_evaluation_record,
    build_production_evidence_report_from_records,
    read_evidence_records,
)
from metadata_core.production_approval import build_production_approval_state


def _pass_records(candidate="sha256:candidate", baseline="sha256:baseline", schema="runtime-v1"):
    records = []
    for idx in range(4):
        records.append(
            ProductionEvidenceRecord(
                window_id=f"agree-{idx}",
                user_id="alice",
                candidate_artifact_digest=candidate,
                baseline_artifact_digest=baseline,
                runtime_schema_version=schema,
                candidate_decision="trusted",
                baseline_decision="trusted",
                candidate_risk_bucket="low",
                baseline_risk_bucket="low",
                is_trusted_window=True,
                feature_quality_ok=True,
                source="shadow_evaluation",
            ).to_dict()
        )
    for idx in range(3):
        records.append(
            ProductionEvidenceRecord(
                window_id=f"unlock-{idx}",
                user_id="alice",
                candidate_artifact_digest=candidate,
                baseline_artifact_digest=baseline,
                runtime_schema_version=schema,
                candidate_decision="trusted",
                baseline_decision="trusted",
                candidate_risk_bucket="low",
                baseline_risk_bucket="low",
                is_trusted_window=True,
                trusted_anchor_type="post_unlock",
                is_post_unlock_window=True,
                feature_quality_ok=True,
                source="runtime_monitor",
            ).to_dict()
        )
    return records


def _report(records, candidate="sha256:candidate", baseline="sha256:baseline", schema="runtime-v1"):
    return build_production_evidence_report_from_records(
        records,
        candidate_artifact_digest=candidate,
        baseline_artifact_digest=baseline,
        evaluation_report_digest="sha256:evaluation",
        runtime_schema_version=schema,
    )


def test_shadow_evidence_record_serialization_no_raw_biometric_data():
    record = ProductionEvidenceRecord(
        window_id="safe-1",
        user_id="Alice Example",
        candidate_artifact_digest="sha256:candidate",
        candidate_decision="trusted",
        candidate_risk_bucket="low",
        is_trusted_window=True,
        feature_quality_ok=True,
    ).to_dict()

    assert contains_raw_biometric_fields(record) is False
    assert "keyboard_events" not in str(record)
    assert "mouse_events" not in str(record)
    assert "feature_vector" not in str(record)

    try:
        ProductionEvidenceRecord.from_dict({"window_id": "bad", "keyboard_events": [{"key": "A"}]})
    except ValueError:
        pass
    else:
        raise AssertionError("raw behavioral fields must be rejected")


def test_shadow_candidate_baseline_decisions_aggregate_model_agreement():
    records = _pass_records()[:3]
    records.append(
        ProductionEvidenceRecord(
            window_id="mismatch",
            user_id="alice",
            candidate_artifact_digest="sha256:candidate",
            baseline_artifact_digest="sha256:baseline",
            runtime_schema_version="runtime-v1",
            candidate_decision="warning",
            baseline_decision="trusted",
            candidate_risk_bucket="warning",
            baseline_risk_bucket="low",
            is_trusted_window=False,
            feature_quality_ok=True,
        ).to_dict()
    )
    report = _report(records + _pass_records()[4:])

    assert report.model_agreement.overall_agreement_rate < 1.0
    assert report.model_agreement.overall_agreement_rate >= 0.75


def test_trusted_window_agreement_aggregates_from_real_records():
    records = _pass_records()[:2]
    records.append(
        ProductionEvidenceRecord(
            window_id="trusted-mismatch",
            user_id="alice",
            candidate_artifact_digest="sha256:candidate",
            baseline_artifact_digest="sha256:baseline",
            runtime_schema_version="runtime-v1",
            candidate_decision="warning",
            baseline_decision="trusted",
            candidate_risk_bucket="warning",
            baseline_risk_bucket="low",
            is_trusted_window=True,
            feature_quality_ok=True,
        ).to_dict()
    )
    report = _report(records + _pass_records()[4:])

    assert 0.0 < report.model_agreement.trusted_window_agreement_rate < 1.0
    assert ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT in report.gate.reason_codes


def test_post_unlock_windows_aggregate_from_pipeline_records():
    report = _report(_pass_records())

    assert report.post_unlock_evidence.trusted_window_count == 3
    assert report.post_unlock_evidence.warning_rate == 0.0


def test_confirmed_intruder_low_risk_from_pipeline_blocks_evidence():
    records = _pass_records()
    records.append(
        ProductionEvidenceRecord(
            window_id="intruder-low",
            user_id="alice",
            candidate_artifact_digest="sha256:candidate",
            baseline_artifact_digest="sha256:baseline",
            runtime_schema_version="runtime-v1",
            candidate_decision="trusted",
            baseline_decision="lock",
            candidate_risk_bucket="low",
            baseline_risk_bucket="high",
            is_confirmed_intruder_window=True,
            feature_quality_ok=True,
            source="confirmed_intruder_feedback",
        ).to_dict()
    )
    report = _report(records)

    assert report.confirmed_intruder_evidence.confirmed_intruder_low_risk_count == 1
    assert report.gate.status == ProductionEvidenceStatus.FAIL
    assert ProductionEvidenceReasonCode.CONFIRMED_INTRUDER_LOW_RISK in report.gate.reason_codes


def test_simulated_false_lock_from_trusted_window_blocks_or_shadow_only():
    records = _pass_records()
    records.append(
        ProductionEvidenceRecord(
            window_id="false-lock",
            user_id="alice",
            candidate_artifact_digest="sha256:candidate",
            baseline_artifact_digest="sha256:baseline",
            runtime_schema_version="runtime-v1",
            candidate_decision="lock",
            baseline_decision="trusted",
            candidate_risk_bucket="high",
            baseline_risk_bucket="low",
            candidate_would_lock_if_production=True,
            is_trusted_window=True,
            is_post_unlock_window=True,
            feature_quality_ok=True,
        ).to_dict()
    )
    report = _report(records)

    assert report.runtime_safety.simulated_false_lock_count >= 1
    assert report.gate.status == ProductionEvidenceStatus.FAIL
    assert ProductionEvidenceReasonCode.SIMULATED_FALSE_LOCK_DETECTED in report.gate.reason_codes


def test_unknown_and_low_quality_windows_do_not_count_as_positive_evidence():
    records = _pass_records()
    for idx in range(4):
        records.append(
            ProductionEvidenceRecord(
                window_id=f"unknown-low-quality-{idx}",
                user_id="alice",
                candidate_artifact_digest="sha256:candidate",
                baseline_artifact_digest="sha256:baseline",
                runtime_schema_version="runtime-v1",
                candidate_decision="unknown",
                baseline_decision="trusted",
                candidate_risk_bucket="unknown",
                baseline_risk_bucket="low",
                is_trusted_window=False,
                feature_quality_ok=False,
                unknown_or_abstain=True,
            ).to_dict()
        )
    report = _report(records)

    assert ProductionEvidenceReasonCode.UNKNOWN_RATE_TOO_HIGH in report.gate.reason_codes
    assert ProductionEvidenceReasonCode.FEATURE_QUALITY_TOO_LOW in report.gate.reason_codes
    assert report.gate.status != ProductionEvidenceStatus.PASS


def test_candidate_digest_mismatch_marks_evidence_partial_or_fail_safe():
    report = _report(_pass_records(candidate="sha256:old"), candidate="sha256:new")

    assert report.gate.status != ProductionEvidenceStatus.PASS
    assert ProductionEvidenceReasonCode.CANDIDATE_DIGEST_MISMATCH in report.gate.reason_codes


def test_runtime_schema_mismatch_marks_evidence_partial_or_fail_safe():
    report = _report(_pass_records(schema="runtime-v0"), schema="runtime-v1")

    assert report.gate.status != ProductionEvidenceStatus.PASS
    assert ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH in report.gate.reason_codes


def test_missing_baseline_decisions_do_not_fake_model_agreement():
    records = []
    for idx in range(4):
        records.append(
            ProductionEvidenceRecord(
                window_id=f"baseline-missing-{idx}",
                user_id="alice",
                candidate_artifact_digest="sha256:candidate",
                runtime_schema_version="runtime-v1",
                candidate_decision="trusted",
                candidate_risk_bucket="low",
                is_trusted_window=True,
                feature_quality_ok=True,
            ).to_dict()
        )
    report = _report(records)

    assert report.model_agreement.overall_agreement_rate == 0.0
    assert report.gate.status != ProductionEvidenceStatus.PASS
    assert ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING in report.gate.reason_codes
    assert ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA in report.gate.reason_codes


def test_pipeline_feeds_existing_production_evidence_gate():
    report = _report(_pass_records())

    assert report.gate.status == ProductionEvidenceStatus.PASS
    assert ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PASSED in report.gate.reason_codes


def test_pipeline_preserves_approved_for_shadow_never_unlocks_protected_sessions():
    report = _report(_pass_records())
    state = build_production_approval_state(
        candidate_paths={"metadata": "", "model": "", "evaluation_report": "", "evaluation_summary": ""},
        candidate_metadata={"model_status": "approved_for_shadow", "production_evidence": report.to_dict()},
        runtime_validation={"ok": True, "reason": "ok", "metadata": {}},
    )

    assert state["productionEvidencePassed"] is True
    assert state["productionReady"] is False
    assert state["protectedSessionsAvailable"] is False


def test_qml_does_not_compute_evidence_or_readiness():
    root = Path(__file__).resolve().parent.parent
    qml_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (root / "qml").rglob("*.qml"))

    forbidden = [
        "property bool productionReady",
        "property bool protectedSessionsAvailable",
        "property bool modelReady",
        "property bool approvalPassed",
        "function computeProduction",
        "function computeEvidence",
    ]
    assert all(token not in qml_text for token in forbidden)


def test_confirmed_intruder_pipeline_does_not_create_owner_positive_training():
    record = ProductionEvidenceRecord(
        window_id="intruder-negative",
        user_id="alice",
        candidate_artifact_digest="sha256:candidate",
        runtime_schema_version="runtime-v1",
        candidate_decision="trusted",
        candidate_risk_bucket="low",
        is_confirmed_intruder_window=True,
        feature_quality_ok=True,
        source="confirmed_intruder_feedback",
    ).to_dict()
    summary = aggregate_evidence_records([record], candidate_artifact_digest="sha256:candidate", runtime_schema_version="runtime-v1")
    report = build_production_evidence_report_from_records([record], candidate_artifact_digest="sha256:candidate", runtime_schema_version="runtime-v1")

    assert "training_counts_toward_minimum" not in record
    assert "owner_positive" not in str(record)
    assert len(summary["confirmed_intruder_events"]) == 1
    assert report.confirmed_intruder_evidence.confirmed_intruder_low_risk_count == 1


def test_shadow_runtime_appenders_persist_safe_records():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["HOME"] = tmp
        model_path = Path(tmp) / "candidate.pkl"
        baseline_path = Path(tmp) / "baseline.pkl"
        model_path.write_bytes(b"candidate")
        baseline_path.write_bytes(b"baseline")
        shadow_payload = append_shadow_evaluation_record(
            user_id="alice",
            session_metadata={"session_id": "s1", "metadata_trusted": True, "final_decision": "accepted", "post_unlock_trusted_window": True},
            session_path=str(Path(tmp) / "session"),
            candidate_artifact_digest="sha256:candidate",
            baseline_artifact_digest="sha256:baseline",
            runtime_schema_version="runtime-v1",
            candidate_decision="trusted",
            baseline_decision="trusted",
            candidate_risk=10,
            baseline_risk=12,
        )
        runtime_payload = append_runtime_monitor_evidence_record(
            user_id="alice",
            state={"runtime_telemetry_seq": 2, "decision": "legit", "avg_risk": 10, "runtime_quality_ok_windows": 3, "runtime_low_quality_windows": 0},
            runtime={"metadata": {"feature_schema_version": "runtime-v1"}, "paths": {"model": str(model_path)}},
            prediction={"final": "legit"},
        )
        records = read_evidence_records("alice")

    assert shadow_payload["source"] == "shadow_evaluation"
    assert runtime_payload["source"] == "runtime_monitor"
    assert len(records) >= 2
    assert contains_raw_biometric_fields({"records": records}) is False


if __name__ == "__main__":
    tests = [name for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = []
    for name in tests:
        try:
            globals()[name]()
        except Exception as exc:  # pragma: no cover - direct runner reporting
            failures.append((name, exc))
            print(f"FAILED {name}: {type(exc).__name__}: {exc}")
    if failures:
        raise SystemExit(1)
    print(f"{len(tests)} production evidence data pipeline tests passed")
