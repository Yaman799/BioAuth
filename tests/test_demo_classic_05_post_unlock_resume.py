from __future__ import annotations

import importlib
import os
import sys
import types
from collections import deque
from contextlib import contextmanager
from typing import Any, Dict, Iterator


class _FakeTime:
    def __init__(self, now: float = 1000.0):
        self._now = float(now)

    def time(self) -> float:
        return self._now


class _FakeFacade:
    def __init__(self, *, locked: bool = False, now: float = 1000.0):
        self.os = os
        self.time = _FakeTime(now)
        self.locked = bool(locked)
        self.written_states: list[dict] = []

    def is_current_session_locked(self) -> bool:
        return self.locked

    def write_session_state(self, state: Dict[str, Any]) -> None:
        self.written_states.append(dict(state or {}))


class _DummyBridge:
    def __init__(self):
        self._current_user = {"user_id": "owner"}
        self._runtime_state: Dict[str, Any] = {}
        self.started: list[dict] = []
        self.debug_events: list[dict] = []
        self._last_auto_resume_attempt_at = 0.0

    def _start_protected_session(self, *, auto_resume: bool = False, trigger_refresh: bool = True) -> bool:
        self.started.append({"auto_resume": bool(auto_resume), "trigger_refresh": bool(trigger_refresh)})
        return True

    def _debug_trace(self, category: str, event: str, payload: Dict[str, Any] | None = None, level: str = "info") -> None:
        self.debug_events.append({"category": category, "event": event, "payload": dict(payload or {}), "level": level})


def _stale_intruder_resume_state() -> Dict[str, Any]:
    return {
        "active": True,
        "forced_stop": True,
        "auto_resume_pending": True,
        "resume_after_unlock": True,
        "session_kind": "protected",
        "decision": "intruder",
        "final_decision": "intruder",
        "status": "resume_pending",
        "archive_path": "",
    }


@contextmanager
def _isolated_monitor_module() -> Iterator[types.ModuleType]:
    guarded_names = ("monitor", "bridge.shared")
    saved = {name: sys.modules.get(name) for name in guarded_names}
    for name in guarded_names:
        sys.modules.pop(name, None)

    shared = types.ModuleType("bridge.shared")
    shared.runtime_status_is_technical_failure = lambda status: False
    shared.runtime_status_awaits_evidence = lambda status: False
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


def test_demo_classic_05_non_demo_active_forced_stop_still_blocks_resume(monkeypatch):
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", raising=False)
    import bridge.session_runtime_helpers as helpers

    fake_facade = _FakeFacade(locked=False)
    monkeypatch.setattr(helpers, "_facade", lambda: fake_facade)

    bridge = _DummyBridge()
    state = _stale_intruder_resume_state()

    assert helpers.maybe_resume_protection_after_unlock(bridge, state=state) is False
    assert bridge.started == []
    assert fake_facade.written_states == []


def test_demo_classic_05_demo_forced_stop_resumes_even_if_stale_active(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    import bridge.session_runtime_helpers as helpers

    fake_facade = _FakeFacade(locked=False, now=2000.0)
    monkeypatch.setattr(helpers, "_facade", lambda: fake_facade)

    bridge = _DummyBridge()
    state = _stale_intruder_resume_state()

    assert helpers.maybe_resume_protection_after_unlock(bridge, state=state) is True
    assert fake_facade.written_states[-1]["active"] is False
    assert fake_facade.written_states[-1]["demo_classic_post_unlock_resume_pending"] is True
    assert bridge.started == [{"auto_resume": True, "trigger_refresh": False}]


def test_demo_classic_05_waits_while_windows_is_still_locked(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    import bridge.session_runtime_helpers as helpers

    fake_facade = _FakeFacade(locked=True, now=2000.0)
    monkeypatch.setattr(helpers, "_facade", lambda: fake_facade)

    bridge = _DummyBridge()
    state = _stale_intruder_resume_state()

    assert helpers.maybe_resume_protection_after_unlock(bridge, state=state) is False
    assert bridge.started == []
    assert any(event["event"] == "demo_classic_post_unlock_resume_waiting_for_unlock" for event in bridge.debug_events)


def test_demo_classic_05_auto_resume_overlay_clears_stale_intruder_ui(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    import bridge.session_runtime_helpers as helpers

    overlay = helpers._demo_classic_post_unlock_resume_overlay(3000.0)

    assert overlay["decision"] == "pending"
    assert overlay["model_decision"] == ""
    assert overlay["final_decision"] == ""
    assert overlay["forced_stop"] is False
    assert overlay["runtime_recent_risks"] == []
    assert overlay["runtime_recent_decisions"] == []
    assert overlay["runtime_window_count"] == 0
    assert overlay["status"] == "verifying_return"
    assert overlay["runtime_confirmation_rule"] == "demo_classic_post_unlock_resume"
    assert overlay["demo_classic_post_unlock_resumed"] is True
    assert overlay["demo_classic_stale_intruder_state_cleared"] is True
    assert overlay["demo_classic_resume_cooldown_until"] == 3008.0
    assert overlay["lock_recovery_cooldown_until"] == 3008.0


def test_demo_classic_05_cooldown_blocks_immediate_demo_relock(monkeypatch):
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
            locking_reason="demo_classic_post_unlock_resume_cooldown",
            quality_lock_ok_windows=4,
        )

    assert result["confirmed_intruder"] is False
    assert result["protected_action_requested"] is False
    assert result["effective_decision"] == "suspicious"
    assert result["confirmation_diagnostics"]["matched_rule"] == "demo_classic_post_unlock_resume_cooldown"
    assert result["confirmation_diagnostics"]["demo_classic_lock_override_reason"] == "demo_classic_lock_override_non_calibration_safety_gate_preserved"
