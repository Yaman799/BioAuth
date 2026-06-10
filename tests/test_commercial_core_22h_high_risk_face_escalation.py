from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_calibration_immature_high_risk_cluster_escalates_to_face_confirmation() -> None:
    import monitor

    result = monitor._resolve_runtime_escalation(
        model_decision="intruder",
        recent_decisions=deque(["intruder", "suspicious", "intruder"]),
        recent_risks=deque([86.0, 89.0, 90.0]),
        risk=89,
        avg_risk=85.8,
        ml=1,
        elapsed=72.0,
        warnings=4,
        config=monitor.resolve_runtime_escalation_config(None, None),
        locking_allowed=False,
        locking_reason="lock_suppressed_by_calibration_immature",
        lock_safety_reason_codes=["calibration_immature"],
        quality_lock_ok_windows=5,
        observed_risk=90.0,
        observed_lock_quality_risks=[90.0, 89.0, 86.0],
    )

    assert result["confirmed_intruder"] is True
    assert result["effective_decision"] == "intruder"
    assert result["protected_action_requested"] is True
    assert result["face_confirmation_required_before_lock"] is True
    assert result["protected_action_phase"] == "pre_lock_face_confirmation_required"
    assert result["final_action"] == "pre_lock_face_confirmation_required"
    diag = result["confirmation_diagnostics"]
    assert diag["matched_rule"] == "high_risk_face_escalation_calibration_immature"
    assert diag["calibration_immature_face_escalation_bypass"] is True
    assert diag["runtime_confirmation_rule_before_face_escalation"] == "lock_suppressed_by_calibration_immature"


def test_calibration_immature_does_not_bypass_other_safety_reasons() -> None:
    import monitor

    result = monitor._resolve_runtime_escalation(
        model_decision="intruder",
        recent_decisions=deque(["intruder", "intruder", "intruder"]),
        recent_risks=deque([96.0, 97.0, 98.0]),
        risk=99,
        avg_risk=97.0,
        ml=1,
        elapsed=120.0,
        warnings=5,
        config=monitor.resolve_runtime_escalation_config(None, None),
        locking_allowed=False,
        locking_reason="lock_suppressed_by_calibration_immature",
        lock_safety_reason_codes=["calibration_immature", "transition_window"],
        quality_lock_ok_windows=0,
        observed_risk=99.0,
        observed_lock_quality_risks=[99.0],
    )

    assert result["confirmed_intruder"] is False
    assert result["effective_decision"] == "suspicious"
    diag = result["confirmation_diagnostics"]
    assert diag["matched_rule"] == "lock_suppressed_by_calibration_immature"
    assert diag["calibration_immature_face_escalation_bypass"] is False


def test_monitor_impl_passes_lock_safety_reason_codes_and_exit_detail() -> None:
    source = Path("src/bioauth/runtime/monitor_impl.py").read_text(encoding="utf-8")
    assert "lock_safety_reason_codes=list(lock_safety_gate.get(\"reason_codes\") or [])" in source
    assert "monitor_exit_detail: Dict[str, Any] = {}" in source
    assert "expected_session_id" in source
    assert "state_stop_reason" in source
    assert "monitor_exit_detail" in source
