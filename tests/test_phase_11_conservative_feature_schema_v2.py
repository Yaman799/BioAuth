from __future__ import annotations

import pandas as pd

from feature_extractors import CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION, extract_combined_features
from feature_extractors.windows import extract_multi_scale_window_feature_samples
from metadata_core.constants import ACTIVE_WINDOW_SCALES, MIN_WINDOW_EVENTS, WINDOW_STEP_SECONDS
from metadata_core.feature_schema_contract import (
    FEATURE_SCHEMA_CONTRACT_VERSION,
    WINDOW_SCHEMA_VERSION,
    build_feature_schema_contract,
    feature_family_for_name,
    validate_feature_sample,
)
from metadata_core.production_evidence_pipeline import append_runtime_monitor_evidence_record


def _sample_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    kb_rows = []
    ts = 0.0
    for idx, key in enumerate("abcde12345"):
        kb_rows.append({"timestamp": ts, "key": key, "event": "press"})
        ts += 0.04 + (idx % 3) * 0.01
        kb_rows.append({"timestamp": ts, "key": key, "event": "release"})
        ts += 0.09
    for key in ("backspace", "shift", "delete"):
        kb_rows.append({"timestamp": ts, "key": key, "event": "press"})
        ts += 0.05
        kb_rows.append({"timestamp": ts, "key": key, "event": "release"})
        ts += 0.08
    ms_rows = []
    for idx in range(120):
        ms_rows.append({"timestamp": idx * 0.05, "x": float(idx), "y": float((idx * idx) % 37), "event": "move"})
    for idx in range(3):
        ms_rows.append({"timestamp": 6.2 + idx * 0.3, "x": 100.0 + idx, "y": 40.0, "event": "click_press"})
    for idx in range(5):
        ms_rows.append({"timestamp": 7.0 + idx * 0.12, "x": 110.0, "y": 42.0, "event": "scroll", "wheel_delta": (-1) ** idx})
    return pd.DataFrame(kb_rows), pd.DataFrame(ms_rows)


def test_phase11_combined_features_include_conservative_v2_without_raw_fields() -> None:
    kb, ms = _sample_data()
    features = extract_combined_features(kb, ms)

    assert features["kb_v2_trigraph_latency_count"] > 0
    assert features["kb_v2_correction_key_rate"] > 0
    assert features["kb_v2_modifier_rate"] > 0
    assert features["ms_v2_jerk_count"] > 0
    assert features["ms_v2_direction_entropy"] > 0
    assert features["session_v2_evidence_density"] > 0
    assert features["session_v2_combined_quality_score"] > 0
    assert not any("raw" in name.lower() or "typed" in name.lower() for name in features)


def test_phase11_empty_features_are_deterministic_and_zero_filled() -> None:
    features = extract_combined_features(pd.DataFrame(), pd.DataFrame())

    expected = [
        "kb_v2_trigraph_latency_mean",
        "kb_v2_burst_duration_mean",
        "ms_v2_jerk_mean",
        "ms_v2_curvature_mean",
        "session_v2_combined_quality_score",
    ]
    for name in expected:
        assert name in features
        assert float(features[name]) == 0.0


def test_phase11_schema_contract_exposes_v2_extension_profile() -> None:
    contract = build_feature_schema_contract()

    assert contract["contract_version"] == FEATURE_SCHEMA_CONTRACT_VERSION
    assert contract["window_schema_version"] == WINDOW_SCHEMA_VERSION
    assert contract["feature_extension_profile"] == CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION
    assert contract["expected_scaled_base_feature_count"] > 200
    assert feature_family_for_name("kb_v2_pause_entropy") == "keyboard_conservative_v2"
    assert feature_family_for_name("ms_v2_direction_entropy") == "mouse_conservative_v2"
    assert feature_family_for_name("session_v2_combined_quality_score") == "session_conservative_v2"


def test_phase11_multiscale_windows_validate_with_v2_features() -> None:
    kb, ms = _sample_data()
    windows = extract_multi_scale_window_feature_samples(
        kb,
        ms,
        window_scales=ACTIVE_WINDOW_SCALES,
        step_seconds=WINDOW_STEP_SECONDS,
        min_total_events=MIN_WINDOW_EVENTS,
        max_windows=2,
    )

    assert windows
    sample = windows[0]
    assert any(name.startswith("scale_") and "_kb_v2_" in name for name in sample)
    assert any(name.startswith("scale_") and "_ms_v2_" in name for name in sample)
    assert any(name.startswith("scale_") and "_session_v2_" in name for name in sample)
    result = validate_feature_sample(sample, require_multiscale=True)
    assert result["ok"], result


def test_phase11_shadow_evidence_carries_v2_extension_profile(tmp_path) -> None:
    contract = build_feature_schema_contract()
    ledger = tmp_path / "shadow_evidence_ledger.jsonl"
    rec = append_runtime_monitor_evidence_record(
        user_id="phase11-user",
        state={
            "runtime_telemetry_seq": "window-v2",
            "evidence_source": "runtime_shadow_evidence",
            "model_decision": "trusted",
            "avg_risk": 18,
            "runtime_quality_ok_windows": 1,
            "runtime_low_quality_windows": 0,
            "runtime_schema_version": contract["feature_schema_version"],
            "feature_schema_contract_version": contract["contract_version"],
            "window_schema_version": contract["window_schema_version"],
            "feature_extension_profile": contract["feature_extension_profile"],
            "feature_schema_digest": contract["schema_digest"],
        },
        runtime={"metadata": {"feature_schema_contract": contract}, "paths": {}},
        prediction={"final": "trusted", "risk": 18},
        ledger_path=str(ledger),
    )

    assert rec["feature_extension_profile"] == CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION
    assert rec["feature_schema_contract_version"] == FEATURE_SCHEMA_CONTRACT_VERSION
