from __future__ import annotations

import importlib
import sys
import types
from collections import deque
from contextlib import contextmanager
from typing import Any, Dict, Iterator


@contextmanager
def _isolated_monitor_module() -> Iterator[types.ModuleType]:
    """Import monitor with a tiny bridge.shared stub, then restore sys.modules.

    The monitor safety-gate and escalation helpers are backend code.  These
    tests do not need a real Qt runtime, so the fixture keeps PySide/QML out of
    the test process while preserving production imports for every other test.
    """

    guarded_names = ("monitor", "bridge.shared")
    saved = {name: sys.modules.get(name) for name in guarded_names}
    for name in guarded_names:
        sys.modules.pop(name, None)

    shared = types.ModuleType("bridge.shared")
    shared.runtime_status_is_technical_failure = lambda status: str(status or "").lower() in {
        "error",
        "runtime_error",
        "technical_failure",
        "model_unavailable",
    }
    shared.runtime_status_awaits_evidence = lambda status: str(status or "").lower() in {
        "awaiting_evidence",
        "pending_evidence",
        "not_ready",
    }
    sys.modules["bridge.shared"] = shared

    try:
        monitor = importlib.import_module("monitor")
        yield monitor
    finally:
        for name in guarded_names:
            sys.modules.pop(name, None)
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module


def _mature_prediction() -> Dict[str, Any]:
    return {
        "calibration_maturity": {
            "mature": True,
            "lock_allowed": True,
            "progressive_phase": "mature_lock_allowed",
            "reason_codes": [],
        }
    }


def _immature_prediction() -> Dict[str, Any]:
    return {
        "calibration_maturity": {
            "mature": False,
            "lock_allowed": False,
            "progressive_phase": "immature_warning_only",
            "reason_codes": ["needs_more_trusted_sessions"],
        }
    }


def _quality_diag(*, lock_quality_allowed: bool = True, last_quality_lock_ok: bool = True) -> Dict[str, Any]:
    return {
        "quality": {
            "window_count": 4,
            "quality_ok_window_count": 4 if lock_quality_allowed else 1,
            "quality_lock_ok_window_count": 4 if lock_quality_allowed else 0,
            "lock_quality_allowed": bool(lock_quality_allowed),
            "blocked_reason_codes": [] if lock_quality_allowed else ["low_quality_window"],
        },
        "window_diagnostics": [
            {
                "index": 4,
                "quality_ok": bool(lock_quality_allowed),
                "quality_lock_ok": bool(last_quality_lock_ok),
                "transition_flag": False,
                "session_start_flag": False,
                "post_idle_flag": False,
                "event_count": 64,
                "context": "keyboard_heavy",
                "risk": 92,
            }
        ],
    }


def test_legitimate_owner_low_risk_stays_unlocked_and_resets_warning_pressure() -> None:
    with _isolated_monitor_module() as monitor:
        gate = monitor._runtime_lock_safety_gate(_mature_prediction(), _quality_diag())
        assert gate["locking_allowed"] is True
        assert gate["reason_codes"] == []

        result = monitor._resolve_runtime_escalation(
            model_decision="legit",
            recent_decisions=deque(["legit", "legit", "legit"]),
            recent_risks=deque([9.0, 12.0, 14.0]),
            risk=11,
            avg_risk=15.0,
            ml=1,
            elapsed=120.0,
            warnings=1,
            config=monitor.resolve_runtime_escalation_config(None, None),
            locking_allowed=gate["locking_allowed"],
            locking_reason=gate["primary_reason"],
        )

    assert result["confirmed_intruder"] is False
    assert result["effective_decision"] == "legit"
    assert result["decision_reason_code"] == "warning_reset"
    assert result["warnings"] == 0
    assert result["confirmation_diagnostics"]["confirmed"] is False


def test_persistent_clear_intruder_reaches_lock_eligible_state_when_gates_pass() -> None:
    with _isolated_monitor_module() as monitor:
        gate = monitor._runtime_lock_safety_gate(_mature_prediction(), _quality_diag())
        assert gate["locking_allowed"] is True

        config = monitor.resolve_runtime_escalation_config(None, None)
        result = monitor._resolve_runtime_escalation(
            model_decision="intruder",
            recent_decisions=deque(["intruder", "intruder", "intruder"]),
            recent_risks=deque([92.0, 94.0, 95.0]),
            risk=96,
            avg_risk=93.0,
            ml=1,
            elapsed=90.0,
            warnings=0,
            config=config,
            locking_allowed=gate["locking_allowed"],
            locking_reason=gate["primary_reason"],
        )

    assert result["confirmed_intruder"] is True
    assert result["effective_decision"] == "intruder"
    assert result["decision_reason_code"] == "lock_confirmed"
    assert result["confirmation_diagnostics"]["locking_allowed"] is True
    assert result["confirmation_diagnostics"]["matched_rule"] in {
        "suspicious_fast_lock",
        "high_risk_cluster_override",
        "intruder_recent_cluster",
        "intruder_ml_cluster",
        "intruder_severe_cluster",
        "alert_cluster_with_intruder_vote",
    }


def test_short_unusual_behavior_warns_but_does_not_confirm_lock() -> None:
    with _isolated_monitor_module() as monitor:
        gate = monitor._runtime_lock_safety_gate(_mature_prediction(), _quality_diag())
        assert gate["locking_allowed"] is True

        result = monitor._resolve_runtime_escalation(
            model_decision="suspicious",
            recent_decisions=deque(["legit", "legit", "legit"]),
            recent_risks=deque([18.0, 22.0, 26.0]),
            risk=72,
            avg_risk=44.0,
            ml=0,
            elapsed=4.0,
            warnings=0,
            config=monitor.resolve_runtime_escalation_config(None, None),
            locking_allowed=gate["locking_allowed"],
            locking_reason=gate["primary_reason"],
        )

    assert result["confirmed_intruder"] is False
    assert result["effective_decision"] == "suspicious"
    assert result["decision_reason_code"] == "soft_suspicious_warning"
    assert result["warnings"] == 1
    assert result["alert_code"] == "suspicious_behavior"
    assert result["confirmation_diagnostics"]["matched_rule"] in {None, ""}


def test_immature_calibration_fails_closed_and_downgrades_intruder_snapshot() -> None:
    with _isolated_monitor_module() as monitor:
        gate = monitor._runtime_lock_safety_gate(_immature_prediction(), _quality_diag())
        assert gate["locking_allowed"] is False
        assert gate["primary_reason"] == "calibration_immature"

        result = monitor._resolve_runtime_escalation(
            model_decision="intruder",
            recent_decisions=deque(["intruder", "intruder", "intruder"]),
            recent_risks=deque([93.0, 94.0, 95.0]),
            risk=96,
            avg_risk=93.0,
            ml=1,
            elapsed=120.0,
            warnings=0,
            config=monitor.resolve_runtime_escalation_config(None, None),
            locking_allowed=gate["locking_allowed"],
            locking_reason=f"lock_suppressed_by_{gate['primary_reason']}",
        )

    assert result["confirmed_intruder"] is False
    assert result["effective_decision"] == "suspicious"
    assert result["decision_reason_code"] == "downgraded_intruder_snapshot"
    assert result["confirmation_diagnostics"]["matched_rule"] == "lock_suppressed_by_calibration_immature"
    assert "suppressed" in result["decision_reason"]


def test_low_quality_current_window_blocks_lock_even_for_persistent_intruder() -> None:
    with _isolated_monitor_module() as monitor:
        low_quality_diag = _quality_diag(lock_quality_allowed=False, last_quality_lock_ok=False)
        gate = monitor._runtime_lock_safety_gate(_mature_prediction(), low_quality_diag)
        assert gate["locking_allowed"] is False
        assert gate["primary_reason"] == "low_quality_window"
        assert "current_window_not_lock_quality" in gate["reason_codes"]

        result = monitor._resolve_runtime_escalation(
            model_decision="intruder",
            recent_decisions=deque(["intruder", "intruder", "intruder"]),
            recent_risks=deque([93.0, 94.0, 95.0]),
            risk=96,
            avg_risk=93.0,
            ml=1,
            elapsed=120.0,
            warnings=0,
            config=monitor.resolve_runtime_escalation_config(None, None),
            locking_allowed=gate["locking_allowed"],
            locking_reason=f"lock_suppressed_by_{gate['primary_reason']}",
        )

    assert result["confirmed_intruder"] is False
    assert result["effective_decision"] == "suspicious"
    assert result["confirmation_diagnostics"]["matched_rule"] == "lock_suppressed_by_low_quality_window"
    assert "runtime safety gate" in result["decision_reason"]


def test_mouse_heavy_global_fallback_guard_requires_strong_repeated_evidence() -> None:
    with _isolated_monitor_module() as monitor:
        guarded_diag = {
            "window_diagnostics": [
                {
                    "index": idx,
                    "guard_applied": True,
                    "context": "mouse_heavy",
                    "used_context": "global_fallback",
                    "transition_flag": False,
                    "base_risk": 61.0,
                    "base_classifier_prob": 0.41,
                }
                for idx in range(1, 5)
            ]
        }
        guard = monitor._mouse_fallback_lock_guard(
            guarded_diag,
            monitor.resolve_runtime_escalation_config(None, None),
        )

    assert guard["active"] is True
    assert guard["locking_allowed"] is False
    assert guard["guarded_window_count"] == 4
    assert guard["strong_window_count"] == 0
