from __future__ import annotations

import json

import pandas as pd

from feature_extractors.windows import extract_multi_scale_window_feature_samples
from metadata_core.constants import ACTIVE_WINDOW_SCALES, MIN_WINDOW_EVENTS, WINDOW_STEP_SECONDS
from metadata_core.feature_schema_contract import (
    FEATURE_SCHEMA_CONTRACT_VERSION,
    FEATURE_VALUE_POLICY_VERSION,
    WINDOW_SCHEMA_VERSION,
    build_feature_schema_contract,
    feature_family_for_name,
    validate_feature_names,
    validate_feature_sample,
)
from metadata_core.production_evidence_pipeline import append_runtime_monitor_evidence_record


def _sample_windows() -> list[dict[str, float]]:
    kb_rows = []
    ts = 0.0
    for idx, key in enumerate("abcdefghijklmnopqrstuvwx"):
        kb_rows.append({"timestamp": ts, "key": key, "event": "press"})
        ts += 0.05
        kb_rows.append({"timestamp": ts, "key": key, "event": "release"})
        ts += 0.08
    ms_rows = [
        {"timestamp": idx * 0.12, "x": float(idx), "y": float(idx % 9), "event": "move"}
        for idx in range(90)
    ]
    samples = extract_multi_scale_window_feature_samples(
        pd.DataFrame(kb_rows),
        pd.DataFrame(ms_rows),
        window_scales=ACTIVE_WINDOW_SCALES,
        step_seconds=WINDOW_STEP_SECONDS,
        min_total_events=MIN_WINDOW_EVENTS,
        max_windows=3,
    )
    assert samples
    return samples


def test_phase5_feature_schema_contract_is_deterministic_and_versioned() -> None:
    first = build_feature_schema_contract()
    second = build_feature_schema_contract()

    assert first["contract_version"] == FEATURE_SCHEMA_CONTRACT_VERSION
    assert first["window_schema_version"] == WINDOW_SCHEMA_VERSION
    assert first["feature_value_policy_version"] == FEATURE_VALUE_POLICY_VERSION
    assert first["schema_digest"] == second["schema_digest"]
    assert first["feature_window_strategy"]
    assert first["expected_scaled_base_feature_count"] > 0
    assert first["active_window_scales"] == [float(scale) for scale in ACTIVE_WINDOW_SCALES]


def test_phase5_runtime_window_samples_validate_against_frozen_schema() -> None:
    sample = _sample_windows()[0]
    names_result = validate_feature_names(sorted(sample.keys()), require_multiscale=True)
    sample_result = validate_feature_sample(sample, require_multiscale=True)

    assert names_result["ok"], names_result
    assert sample_result["ok"], sample_result
    assert sample_result["value_policy_version"] == FEATURE_VALUE_POLICY_VERSION
    assert feature_family_for_name("scale_6s_kb_dwell_mean") == "keyboard_behavior"
    assert feature_family_for_name("scale_6s_ms_velocity_mean") == "mouse_behavior"
    assert feature_family_for_name("scale_6s_session_kb_share") == "session_modality_fusion"


def test_phase5_schema_rejects_raw_or_unknown_feature_names() -> None:
    result = validate_feature_names(["multiscale_anchor_end", "raw_key_text", "unknown_metric"], require_multiscale=False)

    assert not result["ok"]
    assert "prohibited_raw_field_names_present" in result["errors"]
    assert "unknown_feature_names_present" in result["errors"]


def test_phase5_runtime_shadow_evidence_records_schema_identity(tmp_path) -> None:
    contract = build_feature_schema_contract()
    ledger_path = tmp_path / "shadow_evidence_ledger.jsonl"

    record = append_runtime_monitor_evidence_record(
        user_id="phase5-user",
        state={
            "runtime_telemetry_seq": "window-1",
            "evidence_source": "runtime_shadow_evidence",
            "model_decision": "trusted",
            "avg_risk": 21,
            "runtime_quality_ok_windows": 1,
            "runtime_low_quality_windows": 0,
            "runtime_schema_version": contract["feature_schema_version"],
            "feature_schema_contract_version": contract["contract_version"],
            "window_schema_version": contract["window_schema_version"],
            "feature_schema_digest": contract["schema_digest"],
        },
        runtime={
            "metadata": {
                "runtime_schema_version": contract["feature_schema_version"],
                "feature_schema_contract_version": contract["contract_version"],
                "window_schema_version": contract["window_schema_version"],
                "feature_schema_digest": contract["schema_digest"],
            },
            "paths": {},
        },
        prediction={"final": "trusted", "risk": 21},
        ledger_path=str(ledger_path),
    )

    assert record["feature_schema_contract_version"] == FEATURE_SCHEMA_CONTRACT_VERSION
    assert record["window_schema_version"] == WINDOW_SCHEMA_VERSION
    assert record["feature_schema_digest"] == contract["schema_digest"]
    assert record["shadow_ledger_schema_version"] == "shadow-evidence-ledger-v1"

    persisted = json.loads(ledger_path.read_text(encoding="utf-8").strip())
    assert persisted["feature_schema_contract_version"] == FEATURE_SCHEMA_CONTRACT_VERSION
    assert persisted["window_schema_version"] == WINDOW_SCHEMA_VERSION
    assert persisted["feature_schema_digest"] == contract["schema_digest"]
