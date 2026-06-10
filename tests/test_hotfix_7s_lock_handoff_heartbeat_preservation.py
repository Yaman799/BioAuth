from __future__ import annotations

import time

from bioauth_runtime.monitor_worker.lock_controller import build_terminal_lock_payload
from bridge import session_runtime_helpers


class _Facade:
    def __init__(self, state, heartbeats):
        self.state = dict(state)
        self.heartbeats = {str(k): dict(v) for k, v in heartbeats.items()}
        self.writes = []

    def read_worker_heartbeat(self, kind, default=None):
        return dict(self.heartbeats.get(str(kind), default or {}))

    def write_session_state(self, state):
        self.state = dict(state or {})
        self.writes.append(dict(self.state))
        return True

    def slugify_username(self, value):
        return str(value or "").lower()


class _Bridge:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._pending_logger_session_id = "sess-7s"
        self._pending_logger_user_id = "alice"
        self._pending_monitor_user_id = "alice"


def _active_state():
    return {
        "active": True,
        "session_kind": "protected",
        "session_id": "sess-7s",
        "run_id": "run-7s",
        "user_id": "alice",
        "flow": "protected_active",
        "status": "ok",
        "runtime_status": "ok",
        "runtime_decision": "pending",
        "decision": "pending",
        "logger_ready": True,
        "monitor_ready": True,
    }


def test_lock_payload_is_explicit_resume_pending_handoff():
    payload = build_terminal_lock_payload(
        session_id="sess-7s",
        risk=95,
        avg_risk=92.5,
        ml=95,
        screen_locked=True,
        previous_state={"started_at": 123.0},
        lock_fields={"lockSucceeded": True, "windowsLockSucceeded": True},
        lock_reason="test_high_risk",
    )

    assert payload["active"] is False
    assert payload["session_state"] == "resume_pending"
    assert payload["flow"] == "protected_forced_stop"
    assert payload["status"] == "resume_pending"
    assert payload["runtime_status"] == "resume_pending"
    assert payload["auto_resume_pending"] is True
    assert payload["resume_after_unlock"] is True


def test_monitor_lock_handoff_heartbeat_beats_stale_active_logger(monkeypatch):
    now = time.time()
    state = _active_state()
    monitor_hb = {
        **state,
        "worker_kind": "monitor",
        "heartbeat_at": now,
        "monitor_ready": True,
        "active": False,
        "session_state": "resume_pending",
        "flow": "protected_forced_stop",
        "status": "resume_pending",
        "runtime_status": "resume_pending",
        "runtime_decision": "intruder",
        "decision": "intruder",
        "final_decision": "intruder",
        "archive_label": "intruder",
        "forced_stop": True,
        "protected_action_requested": True,
        "auto_resume_pending": True,
        "resume_after_unlock": True,
        "forced_stop_expected_monitor_exit": True,
        "monitor_exit_expected": True,
        "lock_controller_handoff": True,
        "lock_handoff_id": "lock-sess-7s",
    }
    logger_hb = {
        "worker_kind": "logger",
        "session_id": "sess-7s",
        "run_id": "run-7s",
        "user_id": "alice",
        "session_kind": "protected",
        "heartbeat_at": now,
        "active": True,
        "status": "ok",
        "logger_ready": True,
        "keyboard_event_count": 25,
        "mouse_event_count": 30,
    }
    facade = _Facade(state, {"logger": logger_hb, "monitor": monitor_hb})
    monkeypatch.setattr(session_runtime_helpers, "_facade", lambda: facade)

    merged = session_runtime_helpers.merge_worker_heartbeats_into_state(
        _Bridge(),
        dict(state),
        persist=True,
    )

    assert merged["active"] is False
    assert merged["flow"] == "protected_forced_stop"
    assert merged["session_state"] == "resume_pending"
    assert merged["status"] == "resume_pending"
    assert merged["runtime_status"] == "resume_pending"
    assert merged["auto_resume_pending"] is True
    assert merged["resume_after_unlock"] is True
    assert merged["technical_failure"] is False
    assert merged["worker_heartbeat_lock_handoff_preserved"] is True
    assert facade.writes[-1]["active"] is False
    assert facade.writes[-1]["flow"] == "protected_forced_stop"
