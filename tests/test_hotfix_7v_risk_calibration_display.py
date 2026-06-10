from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from bioauth_model.scoring import compute_risk
from bridge.dashboard_refresh_split import runtime_metrics
from bridge.runtime_labels import runtime_policy_display_fields
from training_core.calibration import _score_percentiles_dict


def test_compute_risk_preserves_float_precision_for_percentile_path() -> None:
    meta = {
        "score_percentiles": {
            "p50": 0.0,
            "p75": 1.0,
            "p90": 2.0,
            "p95": 3.0,
            "p98": 4.0,
            "tail_high": 5.0,
        }
    }

    risk = compute_risk(0.5, meta)

    assert isinstance(risk, float)
    assert risk == 22.5


def test_compute_risk_preserves_float_precision_for_legacy_fallback() -> None:
    risk = compute_risk(0.333, {"p10": 0.0, "p90": 1.0})

    assert isinstance(risk, float)
    assert risk == pytest.approx(33.3)


def test_score_percentiles_include_true_p10_for_legacy_fallback_metadata() -> None:
    stats = _score_percentiles_dict(np.arange(10.0))

    assert "p10" in stats
    assert stats["p10"] < stats["p50"] < stats["p90"] < stats["p95"]


def test_runtime_policy_text_no_longer_exposes_observed_risk_wording() -> None:
    fields = runtime_policy_display_fields(
        {
            "active": True,
            "status": "insufficient_evidence",
            "decision": "pending",
            "risk": 69.8,
            "runtime_last_window_diag": {"risk": 69.8, "quality_ok": True, "quality_lock_ok": False},
            "runtime_window_count": 2,
            "runtime_quality_ok_windows": 0,
        },
        flow="protected_active",
        active=True,
        awaiting_evidence=True,
        monitor_ready=True,
        monitor_heartbeat_fresh=True,
        capture_fresh=True,
        elapsed_sec=30.0,
    )

    assert "Observed" not in fields["runtimeDisplayText"]
    assert "Decision Risk" not in fields["runtimeDisplayText"]
    assert fields["risk_display_mode"] == "display_risk_pending"


def test_user_display_risk_prefers_smoothed_display_risk_over_avg_or_observed() -> None:
    bridge = SimpleNamespace(_last_user_display_risk_session_id="", _last_user_display_risk_value=None)
    value, source = runtime_metrics._select_user_display_risk(
        {
            "session_id": "sid",
            "display_risk": 41.4,
            "avg_risk": 69.8,
            "risk": 87.0,
        },
        decision_risk_available=True,
        observed_risk_value=90.0,
    )

    assert value == 41.4
    assert source == "display_risk"
    assert runtime_metrics._smooth_user_display_risk(bridge, {"session_id": "sid"}, value) == 41.4
    assert runtime_metrics._format_user_risk(41.4) == "41.4"
