from __future__ import annotations

import json
from pathlib import Path

import pytest

from metadata_core import production_evidence_pipeline as pipe
from shadow_core.background_contracts import shadow_evidence_ledger_path, shadow_eval_report_path


def _set_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))


def _record(**overrides) -> dict:
    payload = {
        "window_id": "window-1",
        "user_id": "owner",
        "candidate_artifact_digest": "sha256:candidate",
        "baseline_artifact_digest": "sha256:baseline",
        "runtime_schema_version": "runtime-v1",
        "feature_schema_version": "runtime-v1",
        "candidate_decision": "trusted",
        "baseline_decision": "trusted",
        "candidate_risk_bucket": "low",
        "baseline_risk_bucket": "low",
        "candidate_would_lock_if_production": False,
        "baseline_would_lock_if_production": False,
        "is_trusted_window": True,
        "feature_quality_ok": True,
        "source": "runtime_shadow_evidence",
    }
    payload.update(overrides)
    return payload


def test_shadow_ledger_writes_envelope_and_latest_report(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    ledger = shadow_evidence_ledger_path("owner")
    report_path = shadow_eval_report_path("owner")

    record = pipe.append_evidence_record("owner", _record(), ledger_path=ledger)

    assert record["shadow_ledger_schema_version"] == pipe.SHADOW_EVIDENCE_LEDGER_SCHEMA_VERSION
    assert record["shadow_ledger_policy_version"] == pipe.SHADOW_EVIDENCE_LEDGER_POLICY_VERSION
    assert record["ledger_kind"] == "shadow_evidence"
    assert record["ledger_record_kind"] == "runtime_shadow_evidence"
    assert Path(ledger).exists()
    assert Path(report_path).exists()

    raw_line = json.loads(Path(ledger).read_text(encoding="utf-8").strip())
    assert raw_line["shadow_ledger_schema_version"] == pipe.SHADOW_EVIDENCE_LEDGER_SCHEMA_VERSION
    validation = pipe.validate_shadow_evidence_ledger("owner")
    assert validation["ok"] is True
    assert validation["records_valid"] == 1
    assert validation["raw_field_violations"] == 0

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["schema_version"] == pipe.SHADOW_EVIDENCE_LEDGER_SCHEMA_VERSION
    assert report["records_total"] == 1
    assert report["unique_window_count"] == 1
    assert report["quality_ok_windows"] == 1


def test_production_ledger_does_not_get_shadow_envelope(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    record = pipe.append_evidence_record("owner", _record(source="runtime_monitor"))
    assert "shadow_ledger_schema_version" not in record
    raw_line = json.loads(Path(pipe.evidence_ledger_path("owner")).read_text(encoding="utf-8").strip())
    assert "shadow_ledger_schema_version" not in raw_line


def test_shadow_ledger_rotation_moves_old_file_without_deleting(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    monkeypatch.setenv("BIOAUTH_SHADOW_EVIDENCE_LEDGER_MAX_BYTES", "1024")
    ledger = Path(shadow_evidence_ledger_path("owner"))
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("x" * 2048, encoding="utf-8")

    record = pipe.append_evidence_record("owner", _record(window_id="after-rotation"), ledger_path=str(ledger))

    assert record["rotated_before_append"] is True
    rotated = list(ledger.parent.glob("shadow_evidence_ledger.jsonl.*.rotated"))
    assert len(rotated) == 1
    assert rotated[0].read_text(encoding="utf-8") == "x" * 2048
    active = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert active["window_id"] == "after-rotation"


def test_shadow_ledger_privacy_validation_rejects_raw_biometric_fields(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    payload = _record(raw_keyboard=["secret"], window_id="bad-window")
    with pytest.raises(ValueError):
        pipe.append_evidence_record("owner", payload, ledger_path=shadow_evidence_ledger_path("owner"))
