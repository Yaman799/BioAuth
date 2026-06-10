from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation_core.production_evidence import ProductionEvidenceStatus, assert_privacy_safe_payload
from metadata_core import production_evidence_pipeline as pipe


_FORBIDDEN_SUMMARY_KEYS = {
    "raw",
    "raw_score",
    "raw_scores",
    "raw_sample",
    "raw_samples",
    "sample",
    "samples",
    "tensor",
    "tensors",
    "embedding",
    "embeddings",
    "feature",
    "features",
    "feature_vector",
    "feature_vectors",
    "feature_values",
    "raw_feature_values",
    "keyboard_event",
    "keyboard_events",
    "raw_keyboard",
    "raw_keyboard_events",
    "mouse_event",
    "mouse_events",
    "raw_mouse",
    "raw_mouse_events",
    "biometric_sample",
    "biometric_samples",
    "biometric_features",
    "window_samples",
}


def _append_runtime_record(tmp_path: Path, *, prediction: dict, state: dict | None = None) -> dict:
    ledger = tmp_path / "runtime_evidence.jsonl"
    payload = {
        "session_id": "runtime-summary-session",
        "runtime_telemetry_seq": 10,
        "session_kind": "shadow_evidence",
        "runtime_mode": "shadow_evidence",
        "evidence_source": "shadow_evidence_monitor",
        "model_decision": "legit",
        "risk": 11,
        "runtime_quality_ok_windows": 1,
        "runtime_low_quality_windows": 0,
    }
    if state:
        payload.update(state)
    pipe.append_runtime_monitor_evidence_record(
        user_id="alice",
        state=payload,
        runtime={"metadata": {"runtime_schema_version": "runtime-v1", "artifact_digest": "sha256:candidate"}, "paths": {}},
        prediction=prediction,
        ledger_path=str(ledger),
    )
    records = pipe.read_evidence_records("alice", ledger_path=str(ledger))
    assert len(records) == 1
    assert_privacy_safe_payload(records[0])
    return records[0]


def _loads_summary(record: dict, key: str) -> dict:
    value = record.get(key) or ""
    assert value, f"{key} should not be empty"
    return json.loads(value)


def _walk_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key).strip().lower()
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def test_append_runtime_monitor_evidence_record_serializes_deep_sequence_summary(tmp_path):
    record = _append_runtime_record(
        tmp_path,
        prediction={
            "final": "legit",
            "status": "trusted",
            "risk": 11,
            "deep_sequence": {
                "used": True,
                "available": True,
                "probability": 0.91,
                "risk": 9,
                "decision": "trusted",
                "status": "ready",
                "reason": "sequence_shadow_ok",
                "backend": "deep_sequence",
                "sequence_length": 24,
                "confidence_bucket": "high",
                "risk_bucket": "low",
            },
        },
    )

    classic = _loads_summary(record, "classic_decision_summary")
    sequence = _loads_summary(record, "sequence_decision_summary")

    assert classic["final"] == "legit"
    assert classic["risk"] == 11
    assert sequence["deep_sequence"]["used"] is True
    assert sequence["deep_sequence"]["probability"] == 0.91
    assert sequence["deep_sequence"]["sequence_length"] == 24


def test_append_runtime_monitor_evidence_record_serializes_hybrid_shadow_summary(tmp_path):
    record = _append_runtime_record(
        tmp_path,
        prediction={
            "final": "legit",
            "status": "trusted",
            "risk": 12,
            "hybrid_shadow": {
                "available": True,
                "used": True,
                "final": "legit",
                "risk": 12,
                "decision": "trusted",
                "shadow_only": True,
                "used_for_decision": False,
                "backend": "hybrid_shadow",
                "confidence_bucket": "medium",
                "risk_bucket": "low",
            },
        },
    )

    hybrid = _loads_summary(record, "hybrid_decision_summary")

    assert hybrid["hybrid_shadow"]["available"] is True
    assert hybrid["hybrid_shadow"]["final"] == "legit"
    assert hybrid["hybrid_shadow"]["shadow_only"] is True
    assert hybrid["hybrid_shadow"]["used_for_decision"] is False


def test_runtime_evidence_summaries_omit_raw_behavioral_payload_keys(tmp_path):
    record = _append_runtime_record(
        tmp_path,
        prediction={
            "final": "legit",
            "status": "trusted",
            "risk": 10,
            "deep_sequence": {
                "used": True,
                "probability": 0.8,
                "sequence_length": 8,
                "feature_vector": [0.1, 0.2, 0.3],
                "keyboard_events": [{"key": "A", "down_ms": 3}],
                "raw_samples": [{"secret": "sample"}],
                "tensor": [[1, 2, 3]],
            },
            "hybrid_shadow": {
                "available": True,
                "final": "legit",
                "risk": 10,
                "mouse_events": [{"x": 1, "y": 2}],
                "feature_values": [1, 2, 3],
                "window_samples": [{"raw": True}],
            },
            "feature_vector": [9, 9, 9],
            "keyboard_events": [{"key": "B"}],
        },
    )

    summaries = {
        "classic": _loads_summary(record, "classic_decision_summary"),
        "sequence": _loads_summary(record, "sequence_decision_summary"),
        "hybrid": _loads_summary(record, "hybrid_decision_summary"),
    }
    observed_keys = {key for summary in summaries.values() for key in _walk_keys(summary)}

    assert _FORBIDDEN_SUMMARY_KEYS.isdisjoint(observed_keys)
    assert "feature_vector" not in record["sequence_decision_summary"]
    assert "keyboard_events" not in record["sequence_decision_summary"]
    assert "mouse_events" not in record["hybrid_decision_summary"]


def test_missing_deep_sequence_summary_remains_empty_and_fails_closed(tmp_path):
    record = _append_runtime_record(
        tmp_path,
        prediction={"final": "legit", "status": "trusted", "risk": 10},
        state={"baseline_decision": "", "post_unlock_trusted_window": False},
    )

    assert record["sequence_decision_summary"] == ""
    assert record["hybrid_decision_summary"] == ""
    report = pipe.build_production_evidence_report_from_records([record], runtime_schema_version="runtime-v1")

    assert report.gate.status is not ProductionEvidenceStatus.PASS
    assert "baseline_decision_missing" in report.gate.reason_codes


def test_runtime_evidence_summary_serialization_round_trips_through_ledger(tmp_path):
    record = _append_runtime_record(
        tmp_path,
        prediction={
            "final": "legit",
            "status": "trusted",
            "risk": 9,
            "deep_sequence": {"used": True, "probability": 0.77, "sequence_length": 12, "risk_bucket": "low"},
            "hybrid_shadow": {"available": True, "used": True, "final": "legit", "risk": 9, "shadow_only": True},
        },
    )

    assert json.loads(record["sequence_decision_summary"])["deep_sequence"]["probability"] == 0.77
    assert json.loads(record["hybrid_decision_summary"])["hybrid_shadow"]["risk"] == 9
    summaries = pipe.aggregate_evidence_records([record], runtime_schema_version="runtime-v1")
    runtime_summary = summaries["runtime_decision_summaries"][0]

    assert runtime_summary["sequence_decision_summary"] == record["sequence_decision_summary"]
    assert runtime_summary["hybrid_decision_summary"] == record["hybrid_decision_summary"]
