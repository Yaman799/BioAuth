from __future__ import annotations

import importlib
import sys
import types
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator


@contextmanager
def _isolated_monitor_module() -> Iterator[types.ModuleType]:
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
                "risk": 96,
            }
        ],
    }


def test_demo_classic_04_non_demo_calibration_immature_still_suppresses_lock(monkeypatch):
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", raising=False)
    with _isolated_monitor_module() as monitor:
        gate = monitor._runtime_lock_safety_gate(_immature_prediction(), _quality_diag())
        assert gate["locking_allowed"] is False
        assert gate["primary_reason"] == "calibration_immature"

        result = monitor._resolve_runtime_escalation(
            model_decision="intruder",
            recent_decisions=deque(["intruder", "intruder", "intruder"]),
            recent_risks=deque([95.0, 97.0, 98.0]),
            risk=98,
            avg_risk=96.0,
            ml=1,
            elapsed=120.0,
            warnings=3,
            config=monitor.resolve_runtime_escalation_config(None, None),
            locking_allowed=gate["locking_allowed"],
            locking_reason=f"lock_suppressed_by_{gate['primary_reason']}",
            quality_lock_ok_windows=4,
        )

    assert result["confirmed_intruder"] is False
    assert result["effective_decision"] == "suspicious"
    assert result["decision_reason_code"] == "downgraded_intruder_snapshot"
    assert result["protected_action_requested"] is False
    assert result["confirmation_diagnostics"]["matched_rule"] == "lock_suppressed_by_calibration_immature"


def test_demo_classic_04_bypasses_calibration_immature_for_intruder(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    with _isolated_monitor_module() as monitor:
        gate = monitor._runtime_lock_safety_gate(_immature_prediction(), _quality_diag())
        result = monitor._resolve_runtime_escalation(
            model_decision="intruder",
            recent_decisions=deque(["intruder", "intruder", "intruder"]),
            recent_risks=deque([95.0, 97.0, 98.0]),
            risk=98,
            avg_risk=96.0,
            ml=1,
            elapsed=120.0,
            warnings=3,
            config=monitor.resolve_runtime_escalation_config(None, None),
            locking_allowed=gate["locking_allowed"],
            locking_reason=f"lock_suppressed_by_{gate['primary_reason']}",
            quality_lock_ok_windows=4,
        )

    assert result["confirmed_intruder"] is True
    assert result["effective_decision"] == "intruder"
    assert result["protected_action_requested"] is True
    assert result["final_action"] == "pre_lock_face_confirmation_required"
    assert result["face_confirmation_required_before_lock"] is True
    assert result["protected_action_phase"] == "pre_lock_face_confirmation_required"
    assert result["lock_reason"] == "demo_classic_intruder_high_risk_lock"
    assert result["confirmation_diagnostics"]["matched_rule"] == "demo_classic_lock_override"
    assert result["confirmation_diagnostics"]["calibration_immature_lock_bypassed_for_demo"] is True
    assert result["runtime_locking_allowed_after_demo_override"] is True


def test_demo_classic_04_repeated_suspicious_high_risk_locks(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    with _isolated_monitor_module() as monitor:
        result = monitor._resolve_runtime_escalation(
            model_decision="suspicious",
            recent_decisions=deque(["suspicious", "suspicious", "suspicious"]),
            recent_risks=deque([90.0, 95.0, 97.0]),
            risk=98,
            avg_risk=95.0,
            ml=1,
            elapsed=30.0,
            warnings=3,
            config=monitor.resolve_runtime_escalation_config(None, None),
            locking_allowed=False,
            locking_reason="lock_suppressed_by_calibration_immature",
            quality_lock_ok_windows=3,
        )

    assert result["confirmed_intruder"] is True
    assert result["effective_decision"] == "intruder"
    assert result["protected_action_requested"] is True
    assert result["final_action"] == "pre_lock_face_confirmation_required"
    assert result["face_confirmation_required_before_lock"] is True
    assert result["protected_action_phase"] == "pre_lock_face_confirmation_required"



def test_demo_classic_04_low_quality_safety_gate_is_not_bypassed(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    with _isolated_monitor_module() as monitor:
        result = monitor._resolve_runtime_escalation(
            model_decision="intruder",
            recent_decisions=deque(["intruder", "intruder", "intruder"]),
            recent_risks=deque([95.0, 97.0, 98.0]),
            risk=98,
            avg_risk=96.0,
            ml=1,
            elapsed=120.0,
            warnings=3,
            config=monitor.resolve_runtime_escalation_config(None, None),
            locking_allowed=False,
            locking_reason="lock_suppressed_by_low_quality_window",
            quality_lock_ok_windows=0,
        )

    assert result["confirmed_intruder"] is False
    assert result["effective_decision"] == "suspicious"
    assert result["protected_action_requested"] is False
    assert result["confirmation_diagnostics"]["matched_rule"] == "lock_suppressed_by_low_quality_window"

def test_demo_classic_04_low_risk_does_not_lock(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    with _isolated_monitor_module() as monitor:
        result = monitor._resolve_runtime_escalation(
            model_decision="legit",
            recent_decisions=deque(["legit", "legit", "legit"]),
            recent_risks=deque([15.0, 21.0, 24.0]),
            risk=24,
            avg_risk=20.0,
            ml=0,
            elapsed=120.0,
            warnings=0,
            config=monitor.resolve_runtime_escalation_config(None, None),
            locking_allowed=True,
            locking_reason="",
            quality_lock_ok_windows=3,
        )

    assert result["confirmed_intruder"] is False
    assert result["protected_action_requested"] is False
    assert result["effective_decision"] == "legit"


def test_demo_classic_04_manual_someone_else_feedback_is_audit_only_before_post_lock(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    import bridge.session_mixin as session_mixin
    import bridge.session_runtime_helpers as runtime_helpers

    saved_states: list[dict] = []
    enforcement_calls: list[dict] = []

    class Signal:
        def emit(self):
            return None

    class DummyBridge(session_mixin.SessionMixin):
        def __init__(self):
            self._current_user = {"user_id": "owner"}
            self._runtime_state = {}
            self.runtimeStateChanged = Signal()
            self.statuses: list[tuple[str, str]] = []

        def _active_state_for_current_user(self):
            return {
                "active": True,
                "session_kind": "protected",
                "session_id": "sess-1",
                "decision": "suspicious",
                "risk": 97,
                "avg_risk": 94.0,
                "feedback_prompt": {"pending": True, "session_id": "sess-1", "decision": "suspicious", "risk": 97},
            }

        def _set_status(self, message, tone):
            self.statuses.append((message, tone))

        def _t(self, key, **kwargs):
            return key

        def _maybe_process_shadow_backlog(self):
            return None

    def fake_record_warning_feedback(**kwargs):
        return {"label": "confirmed_intruder", "timestamp": "2026-05-30 12:00:00"}

    def fake_enforce(self, *, state=None, source="", reason_code="", feedback_record=None):
        enforcement_calls.append({"state": dict(state or {}), "source": source, "reason_code": reason_code})
        return {"ok": True, "state": dict(state or {})}

    monkeypatch.setattr(session_mixin, "record_warning_feedback", fake_record_warning_feedback)
    monkeypatch.setattr(session_mixin, "write_session_state", lambda state: saved_states.append(dict(state or {})))
    monkeypatch.setattr(runtime_helpers, "enforce_confirmed_intruder_event", fake_enforce)

    bridge = DummyBridge()
    bridge.submitWarningFeedback("confirmed_intruder")

    assert enforcement_calls == []
    assert saved_states[-1]["demo_classic_manual_intruder_feedback_lock"] is False
    assert saved_states[-1]["confirmedIntruderFeedbackDidTriggerLock"] is False
    assert saved_states[-1]["feedbackDidRequestProtectedAction"] is False
    assert "lock_reason" not in saved_states[-1]


def test_demo_classic_04_windows_lock_module_still_compiles():
    source = Path("bio_platform/lock_screen.py").read_text(encoding="utf-8")
    assert "def lock_current_session" in source
    compile(source, "bio_platform/lock_screen.py", "exec")


def test_demo_classic_04_observed_lock_quality_risk_bypasses_capped_decision_risk(monkeypatch):
    """Regression for real log: decision risk was capped around 70 while top lock-quality windows were 94-95."""
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    with _isolated_monitor_module() as monitor:
        result = monitor._resolve_runtime_escalation(
            model_decision="suspicious",
            recent_decisions=deque(["suspicious", "suspicious"]),
            recent_risks=deque([69.0, 69.0]),
            risk=70,
            avg_risk=69.5,
            ml=1,
            elapsed=40.0,
            warnings=1,
            config=monitor.resolve_runtime_escalation_config(None, None),
            locking_allowed=False,
            locking_reason="lock_suppressed_by_calibration_immature",
            quality_lock_ok_windows=4,
            observed_risk=95.0,
            observed_lock_quality_risks=[95.0, 95.0, 94.0],
        )

    assert result["confirmed_intruder"] is True
    assert result["effective_decision"] == "intruder"
    assert result["protected_action_requested"] is True
    assert result["final_action"] == "pre_lock_face_confirmation_required"
    assert result["face_confirmation_required_before_lock"] is True
    assert result["protected_action_phase"] == "pre_lock_face_confirmation_required"
    assert result["confirmation_diagnostics"]["matched_rule"] == "demo_classic_lock_override"
    assert result["confirmation_diagnostics"]["observed_peak_risk"] == 95.0
    assert result["confirmation_diagnostics"]["decision_risk_before_demo_override"] == 70.0


def test_observed_lock_quality_risk_evidence_ignores_transition_and_low_quality(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    with _isolated_monitor_module() as monitor:
        evidence = monitor._observed_lock_quality_risk_evidence({
            "window_diagnostics": [
                {"index": 1, "risk": 99, "quality_lock_ok": False, "context": "mouse_heavy"},
                {"index": 2, "risk": 98, "quality_lock_ok": True, "transition_flag": True, "context": "mouse_heavy"},
                {"index": 3, "risk": 95, "base_risk": 96, "quality_lock_ok": True, "context": "mouse_heavy"},
            ],
            "window_diagnostics_summary": {
                "top_risky_windows": [
                    {"index": 4, "risk": 94, "base_risk": 95, "quality_lock_ok": True, "context": "mouse_heavy"},
                ]
            },
        })

    assert evidence["peak_risk"] == 96.0
    assert evidence["high90_count"] == 2
    assert evidence["risks"] == [96.0, 95.0]
