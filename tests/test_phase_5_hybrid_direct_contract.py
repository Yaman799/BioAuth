from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "qml"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_default_hybrid_direct_contract_is_safe_and_backend_owned() -> None:
    from hybrid_direct_contract import (
        EXPERIMENT_CAN_LOCK_ALONE,
        NO_SINGLE_MODEL_CAN_LOCK,
        build_default_hybrid_direct_state,
    )

    state = build_default_hybrid_direct_state(timestamp="2026-05-04T00:00:00Z")
    assert state["enabled"] is False
    assert state["mode"] == "off"
    assert state["can_influence_device"] is False
    assert state["experiment_can_lock_alone"] is False
    assert state["no_single_model_can_lock"] is True
    assert EXPERIMENT_CAN_LOCK_ALONE is False
    assert NO_SINGLE_MODEL_CAN_LOCK is True
    assert state["face_required"] is False
    assert state["final_action"] == "none"
    assert state["fusion_state"] == "unavailable"
    assert state["agreement_count"] == 0
    assert "developer_direct_disabled" in state["reason_codes"]
    assert "device_influence_disabled" in state["reason_codes"]
    assert "single_model_lock_forbidden" in state["reason_codes"]
    assert "experiment_can_lock_alone_false" in state["reason_codes"]


def test_default_model_results_are_unavailable_abstain_and_cannot_lock() -> None:
    from hybrid_direct_contract import build_default_hybrid_direct_state

    state = build_default_hybrid_direct_state(timestamp="2026-05-04T00:00:00Z")
    for key in ("classic_risk", "keyboard_risk", "mouse_risk", "combined_risk"):
        payload = state[key]
        assert payload["available"] is False
        assert payload["status"] == "unavailable"
        assert payload["decision"] == "abstain"
        assert payload["can_lock"] is False
        assert payload["can_influence_device"] is False
        assert payload["reason_codes"] == ["no_model_result"]


def test_safety_gate_results_include_no_single_lock_and_disabled_influence() -> None:
    from hybrid_direct_contract import build_default_hybrid_direct_state

    gates = build_default_hybrid_direct_state(timestamp="2026-05-04T00:00:00Z")["safety_gate_results"]
    assert gates["developer_direct_enabled"]["passed"] is False
    assert gates["device_influence"]["passed"] is False
    assert gates["no_single_model_lock"]["passed"] is True
    assert gates["experiment_can_lock_alone_false"]["passed"] is True


def test_runtime_policy_exports_phase_5_safety_constants() -> None:
    import runtime_policy

    assert runtime_policy.DEVELOPER_DIRECT_TEST_ENABLED_DEFAULT is False
    assert runtime_policy.HYBRID_DIRECT_CAN_INFLUENCE_DEVICE_DEFAULT is False
    assert runtime_policy.EXPERIMENT_CAN_LOCK_ALONE is False
    assert runtime_policy.NO_SINGLE_MODEL_CAN_LOCK is True


def test_desktop_app_exposes_qvariantmap_property_and_refresh_slot() -> None:
    desktop = _read("desktop_app.py")
    assert "from hybrid_direct_contract import build_default_hybrid_direct_state, normalize_hybrid_direct_state" in desktop
    assert "hybridDirectChanged = Signal()" in desktop
    assert "self._hybrid_direct_state: Dict[str, Any] = build_default_hybrid_direct_state()" in desktop
    assert '@Property("QVariantMap", notify=hybridDirectChanged)' in desktop
    assert "def hybridDirectState(self) -> Dict[str, Any]:" in desktop
    assert '@Slot(result="QVariantMap")' in desktop
    assert "def refreshHybridDirectState(self) -> Dict[str, Any]:" in desktop


def test_refresh_emit_all_notifies_hybrid_direct_observers() -> None:
    text = _read("bridge/refresh_runtime_helpers.py")
    assert 'hybrid_direct_signal = getattr(self, "hybridDirectChanged", None)' in text
    assert "hybrid_direct_signal.emit()" in text


def test_hybrid_direct_qml_displays_backend_state_without_methods_or_local_fusion() -> None:
    qml = _read("qml/pages/HybridDirectTestPage.qml")
    assert "backend.hybridDirectState" in qml
    assert "readonly property var hybridState" in qml
    assert "QML does not decide pass/fail" in qml
    assert "onClicked: backend.runHybridDirectTest()" in qml
    assert "Timer {" not in qml
    allowed_backend_refs = qml.replace("backend.theme", "").replace("backend.hybridDirectState", "").replace("backend.latestHybridDirectTestResult", "").replace("backend.hybridDirectCandidateGroups", "").replace("backend.hybridDirectGroupVotes", "").replace("backend.latestHybridDirectReportState", "").replace("backend.latestHybridLiveSessionEvalResult", "").replace("backend.latestHybridLiveSessionEvalReportState", "").replace("backend.liveCandidateObserverState", "").replace("backend.canRunHybridDirectTest", "").replace("backend.hybridDirectTestRunning", "").replace("backend.hybridDirectTestUnavailableReason", "").replace("backend.runHybridDirectTest()", "").replace("backend.evaluateLatestHybridLiveSession()", "").replace("backend.openLatestHybridDirectReport()", "").replace("backend.openLatestHybridLiveSessionEvalReport()", "").replace("backend.exportHybridDirectCsv()", "").replace("backend.clearHybridDirectTestResults()", "")
    assert "backend." not in allowed_backend_refs
    forbidden = [
        r"function\s+\w*fusion\w*\(",
        r"function\s+\w*readiness\w*\(",
        r"productionReady\s*:",
        r"protectedSessionsAvailable\s*:",
        r"modelReady\s*:",
        r"approvalPassed\s*:",
    ]
    for pattern in forbidden:
        assert re.search(pattern, qml) is None


def test_no_qml_local_readiness_or_production_approval_computation_added() -> None:
    qml_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in QML.rglob("*.qml"))
    forbidden = (
        r"function\s+\w*productionReady\w*\s*\(",
        r"\b(?:var|let|const|property\s+bool)\s+productionReady\b",
        r"^\s*productionReady\s*:",
        r"function\s+\w*protectedSessionsAvailable\w*\s*\(",
        r"\b(?:var|let|const|property\s+bool)\s+protectedSessionsAvailable\b",
        r"^\s*protectedSessionsAvailable\s*:",
        r"function\s+\w*compute\w*Fusion\w*\s*\(",
    )
    for pattern in forbidden:
        assert re.search(pattern, qml_text, flags=re.MULTILINE) is None
