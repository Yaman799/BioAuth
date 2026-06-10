from __future__ import annotations

from feature_extractors.context import classify_behavior_context
from model_runtime.diagnostics import _build_window_diagnostics, _quality_gate_status


def _sample(
    *,
    kb_share: float,
    ms_share: float,
    events: float = 180.0,
    eps: float = 15.0,
    seconds: float = 12.0,
    requested: float = 12.0,
    switches: float = 0.18,
    coverage: float = 1.0,
) -> dict[str, float]:
    return {
        "multiscale_scale_coverage": coverage,
        "multiscale_active_scale_count": 2.0 if coverage >= 1.0 else 1.0,
        "multiscale_requested_scale_count": 2.0,
        "scale_12s_active": 1.0,
        "scale_12s_requested_seconds": requested,
        "scale_12s_window_seconds": seconds,
        "scale_12s_window_total_events": events,
        "scale_12s_session_events_per_sec": eps,
        "scale_12s_session_kb_share": kb_share,
        "scale_12s_session_ms_share": ms_share,
        "scale_12s_session_modality_switch_ratio": switches,
    }


def test_keyboard_heavy_context_is_not_collapsed_to_mixed() -> None:
    route = classify_behavior_context(_sample(kb_share=0.72, ms_share=0.28, eps=12.0, switches=0.08))

    assert route["context"] == "keyboard_heavy"
    assert route["routing_quality"] == "stable"
    assert route["dominance_margin"] >= 0.18
    assert "keyboard_share_high" in route["reason_codes"]
    assert "dominant_modality_margin_met" in route["reason_codes"]


def test_mouse_heavy_context_is_deterministic() -> None:
    route = classify_behavior_context(_sample(kb_share=0.12, ms_share=0.88, eps=13.0, switches=0.06))

    assert route["context"] == "mouse_heavy"
    assert route["routing_quality"] == "stable"
    assert "mouse_share_high" in route["reason_codes"]


def test_balanced_or_switching_window_routes_to_mixed() -> None:
    route = classify_behavior_context(_sample(kb_share=0.56, ms_share=0.44, eps=14.0, switches=0.45))

    assert route["context"] == "mixed"
    assert route["routing_quality"] == "stable"
    assert "dominant_modality_margin_not_met" in route["reason_codes"]


def test_idle_window_is_explainable_and_routes_to_safe_short_session_bucket() -> None:
    route = classify_behavior_context(_sample(kb_share=0.0, ms_share=0.0, events=0.0, eps=0.0, switches=0.0))

    assert route["context"] == "short_session"
    assert route["routing_quality"] == "idle"
    assert "idle_or_near_empty_window" in route["reason_codes"]
    assert "below_min_routable_events" in route["reason_codes"]


def test_low_quality_window_is_not_routed_to_heavy_context_model() -> None:
    route = classify_behavior_context(_sample(kb_share=0.92, ms_share=0.08, events=24.0, eps=2.0, switches=0.02))

    assert route["context"] == "short_session"
    assert route["routing_quality"] == "low_quality"
    assert "insufficient_routing_evidence" in route["reason_codes"]
    assert "keyboard_share_high" in route["reason_codes"]


def test_short_partial_window_remains_non_production_route() -> None:
    route = classify_behavior_context(
        _sample(kb_share=0.74, ms_share=0.26, events=100.0, eps=16.0, seconds=6.0, requested=12.0, coverage=0.5)
    )

    assert route["context"] == "short_session"
    assert route["routing_quality"] == "short_session"
    assert "short_or_partial_window" in route["reason_codes"]


def test_low_quality_context_diagnostics_fail_closed_for_lock_quality() -> None:
    sample = _sample(kb_share=0.92, ms_share=0.08, events=24.0, eps=2.0, switches=0.02)
    route = classify_behavior_context(sample)
    diagnostics, summary = _build_window_diagnostics(
        [sample],
        raw_values=[-0.9],
        risk_values=[88.0],
        classifier_probs=[0.95],
        route_records=[route],
        used_contexts=["global_fallback"],
    )

    assert diagnostics[0]["context"] == "short_session"
    assert diagnostics[0]["routing_quality"] == "low_quality"
    assert diagnostics[0]["quality_lock_ok"] is False
    assert summary["quality"]["lock_quality_allowed"] is False
    gate = _quality_gate_status(summary)
    assert gate["applied"] is True
    assert gate["status"] == "insufficient_evidence"
