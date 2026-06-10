from __future__ import annotations

import os

from model_runtime.diagnostics import _build_window_diagnostics
from model_runtime.dynamic_fusion import (
    DYNAMIC_FUSION_POLICY_VERSION,
    apply_dynamic_fusion_v1,
    dynamic_fusion_v1_enabled,
)


def _sample(*, kb: float = 0.5, ms: float = 0.5, events: int = 120, switch: float = 0.25, coverage: float = 1.0) -> dict[str, float]:
    return {
        "window_seconds": 10.0,
        "requested_seconds": 10.0,
        "window_total_events": float(events),
        "session_events_per_sec": float(events) / 10.0,
        "session_kb_share": float(kb),
        "session_ms_share": float(ms),
        "session_modality_switch_ratio": float(switch),
        "multiscale_scale_coverage": float(coverage),
        "transition_flag": 0.0,
        "transition_session_start_flag": 0.0,
        "transition_post_idle_flag": 0.0,
    }


def test_dynamic_fusion_default_enabled_and_has_non_enforcement_contract(monkeypatch) -> None:
    monkeypatch.delenv("BIOAUTH_DISABLE_DYNAMIC_FUSION_V1", raising=False)
    assert dynamic_fusion_v1_enabled(metadata={}, settings={}) is True
    result = apply_dynamic_fusion_v1(
        window_samples=[_sample()],
        route_records=[{"context": "mixed", "confidence": 0.95}],
        used_contexts=["mixed"],
        risk_values=[55.0],
        classifier_probs=[0.45],
        metadata={},
        settings={},
    )
    summary = result["summary"]
    assert summary["enabled"] is True
    assert summary["policy_version"] == DYNAMIC_FUSION_POLICY_VERSION
    assert summary["can_lock"] is False
    assert summary["can_change_threshold"] is False
    assert summary["can_change_model_pointer"] is False


def test_dynamic_fusion_caps_low_evidence_high_risk_without_increasing_scores(monkeypatch) -> None:
    monkeypatch.delenv("BIOAUTH_DISABLE_DYNAMIC_FUSION_V1", raising=False)
    result = apply_dynamic_fusion_v1(
        window_samples=[_sample(kb=0.02, ms=0.98, events=8, switch=0.01)],
        route_records=[{"context": "mouse_heavy", "confidence": 0.95}],
        used_contexts=["global_fallback"],
        risk_values=[96.0],
        classifier_probs=[0.93],
        metadata={},
        settings={},
    )
    assert result["risk_values"][0] < 96.0
    assert result["classifier_probs"][0] < 0.93
    assert result["risk_values"][0] <= 96.0
    assert result["classifier_probs"][0] <= 0.93
    record = result["records"][0]
    assert record["applied"] is True
    assert "low_event_count" in record["reason_codes"]
    assert "dynamic_fusion_quality_cap" in record["reason_codes"]
    assert result["summary"]["applied_window_count"] == 1


def test_dynamic_fusion_does_not_change_high_quality_context_specific_window(monkeypatch) -> None:
    monkeypatch.delenv("BIOAUTH_DISABLE_DYNAMIC_FUSION_V1", raising=False)
    result = apply_dynamic_fusion_v1(
        window_samples=[_sample(kb=0.84, ms=0.16, events=180, switch=0.10)],
        route_records=[{"context": "keyboard_heavy", "confidence": 0.96}],
        used_contexts=["keyboard_heavy"],
        risk_values=[72.0],
        classifier_probs=[0.66],
        metadata={},
        settings={},
    )
    assert result["risk_values"][0] == 72.0
    assert result["classifier_probs"][0] == 0.66
    assert result["records"][0]["applied"] is False
    assert result["records"][0]["keyboard_weight"] > result["records"][0]["mouse_weight"]


def test_dynamic_fusion_can_be_disabled_by_env(monkeypatch) -> None:
    monkeypatch.setenv("BIOAUTH_DISABLE_DYNAMIC_FUSION_V1", "1")
    result = apply_dynamic_fusion_v1(
        window_samples=[_sample(kb=0.01, ms=0.99, events=5)],
        route_records=[{"context": "mouse_heavy", "confidence": 1.0}],
        used_contexts=["global_fallback"],
        risk_values=[99.0],
        classifier_probs=[0.99],
        metadata={},
        settings={},
    )
    assert result["summary"]["enabled"] is False
    assert result["risk_values"][0] == 99.0
    assert result["classifier_probs"][0] == 0.99
    assert "dynamic_fusion_disabled" in result["records"][0]["reason_codes"]


def test_window_diagnostics_surface_dynamic_fusion_fields(monkeypatch) -> None:
    monkeypatch.delenv("BIOAUTH_DISABLE_DYNAMIC_FUSION_V1", raising=False)
    samples = [_sample(kb=0.01, ms=0.99, events=8)]
    dynamic = apply_dynamic_fusion_v1(
        window_samples=samples,
        route_records=[{"context": "mouse_heavy", "confidence": 0.95}],
        used_contexts=["global_fallback"],
        risk_values=[95.0],
        classifier_probs=[0.91],
        metadata={},
        settings={},
    )
    diagnostics, summary = _build_window_diagnostics(
        samples,
        raw_values=[1.0],
        risk_values=list(dynamic["risk_values"]),
        classifier_probs=list(dynamic["classifier_probs"]),
        route_records=[{"context": "mouse_heavy", "confidence": 0.95}],
        used_contexts=["global_fallback"],
        base_risk_values=[95.0],
        dynamic_fusion_records=list(dynamic["records"]),
    )
    assert diagnostics[0]["dynamic_fusion_enabled"] is True
    assert diagnostics[0]["dynamic_fusion_applied"] is True
    assert diagnostics[0]["dynamic_fusion_policy_version"] == DYNAMIC_FUSION_POLICY_VERSION
    assert summary["dynamic_fusion_applied_count"] == 1
