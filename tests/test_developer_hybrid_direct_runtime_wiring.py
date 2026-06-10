from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_snapshot_populates_combined_hybrid_direct_payload() -> None:
    from hybrid_direct_contract import build_hybrid_direct_state_from_runtime

    state = build_hybrid_direct_state_from_runtime(
        {
            "active": True,
            "flow": "protected_active",
            "monitorReady": True,
            "runtime_status": "legitimate",
            "decision": "legit",
            "risk": 7,
            "avg_risk": 6,
            "runtime_window_count": 4,
            "runtime_diag_code": "warning_reset",
            "updatedAt": "2026-05-09T16:03:36Z",
        },
        developer_simulation=True,
        production_ready_real=False,
        production_ready_effective=True,
        runtime_bundle_source="developer_shadow_candidate",
    )

    assert state["enabled"] is False
    assert state["can_influence_device"] is False
    assert state["no_single_model_can_lock"] is True
    assert state["experiment_can_lock_alone"] is False
    assert state["combined_risk"]["available"] is True
    assert state["combined_risk"]["decision"] == "legit"
    assert state["combined_risk"]["risk"] == 7.0
    assert state["combined_risk"]["runtime_authoritative"] is False  # normalized contract always prevents QML authority
    assert state["combined_risk"]["can_lock"] is False
    assert state["runtime_bundle_source"] == "developer_shadow_candidate"
    assert state["dev_production_ready_simulation"] is True
    assert state["production_ready_real"] is False
    assert state["production_ready_effective"] is True
    assert "runtime_snapshot_available" in state["reason_codes"]
    assert "developer_shadow_candidate_runtime" in state["reason_codes"]
    assert "no_available_model_results" not in state["reason_codes"]


def test_runtime_snapshot_does_not_fake_missing_layer_breakdowns() -> None:
    from hybrid_direct_contract import build_hybrid_direct_state_from_runtime

    state = build_hybrid_direct_state_from_runtime(
        {
            "active": True,
            "flow": "protected_warning",
            "monitorReady": True,
            "runtime_status": "suspicious",
            "decision": "suspicious",
            "runtime_recent_risks": [59, 67, 75],
            "runtime_window_count": 4,
        },
        developer_simulation=True,
        production_ready_effective=True,
        runtime_bundle_source="developer_shadow_candidate",
    )

    assert state["combined_risk"]["available"] is True
    assert state["combined_risk"]["decision"] == "suspicious"
    assert state["combined_risk"]["risk"] == 75.0
    for key in ("classic_risk", "keyboard_risk", "mouse_risk"):
        payload = state[key]
        assert payload["available"] is False
        assert payload["decision"] == "abstain"
        assert payload["can_lock"] is False
        assert payload["reason_codes"] == ["runtime_snapshot_available_no_layer_breakdown"]


def test_inactive_runtime_keeps_hybrid_direct_fail_closed() -> None:
    from hybrid_direct_contract import build_hybrid_direct_state_from_runtime

    state = build_hybrid_direct_state_from_runtime({"active": False, "flow": "idle"})
    assert state["combined_risk"]["available"] is False
    assert state["final_action"] == "none"
    assert state["can_influence_device"] is False
    assert "protected_runtime_inactive" in state["reason_codes"]


def test_refresh_dashboard_helper_wires_runtime_snapshot_to_hybrid_state() -> None:
    helper = (ROOT / "bridge" / "refresh_dashboard_helpers.py").read_text(encoding="utf-8")
    assert "build_hybrid_direct_state_from_runtime" in helper
    assert "self._hybrid_direct_state = current_hybrid" in helper
    assert "hybridDirectChanged" in helper
    assert "developer_shadow_candidate" in helper


def test_hybrid_direct_qml_stays_read_only_backend_bound() -> None:
    qml = (ROOT / "qml" / "pages" / "HybridDirectTestPage.qml").read_text(encoding="utf-8")
    assert "backend.hybridDirectState" in qml
    assert "readonly property var hybridState" in qml
    assert "onClicked: backend.runHybridDirectTest()" in qml
    assert "Timer {" not in qml
    for pattern in (
        r"function\s+\w*fusion\w*\(",
        r"function\s+\w*lock\w*\(",
        r"function\s+\w*productionReady\w*\(",
    ):
        assert re.search(pattern, qml) is None
