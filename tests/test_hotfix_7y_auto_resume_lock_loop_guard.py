from __future__ import annotations

from types import SimpleNamespace

from bioauth_runtime.monitor_worker import lock_controller
from bioauth_runtime.supervisor import resume_controller, stop_controller


class _Facade:
    class time:
        @staticmethod
        def time():
            return 1000.0

    def __init__(self):
        self.state = {}

    def write_session_state(self, payload):
        self.state = dict(payload)
        return True

    def read_session_state(self, default=None):
        return dict(self.state or (default or {}))

    @staticmethod
    def is_current_session_locked():
        return False


class _Legacy:
    def __init__(self, facade):
        self.facade = facade

    def _facade(self):
        return self.facade


class _Bridge(SimpleNamespace):
    def __init__(self):
        super().__init__(
            _current_user={"user_id": "alice"},
            _runtime_state={},
            _last_auto_resume_attempt_at=0.0,
            _auto_resume_inflight=False,
            _logger_process_key=lambda: "logger_user_alice",
        )


def test_resume_controller_blocks_second_auto_resume_for_same_handoff(monkeypatch):
    facade = _Facade()
    monkeypatch.setattr(resume_controller, "_legacy", lambda: _Legacy(facade), raising=False)
    monkeypatch.setattr(resume_controller.worker_processes, "process_alive", lambda *_a, **_k: False)

    state = {
        "session_id": "sess-7y",
        "session_kind": "protected",
        "active": False,
        "status": "resume_pending",
        "runtime_status": "resume_pending",
        "forced_stop": True,
        "protected_action_requested": True,
        "final_action": "windows_locked",
        "lock_controller_handoff": True,
        "lock_handoff_id": "handoff-7y",
        "auto_resume_pending": True,
        "resume_after_unlock": True,
        "auto_resume_attempt_count": 1,
    }

    assert resume_controller.maybe_resume_after_unlock(_Bridge(), state=state) is False
    assert facade.state["flow"] == "resume_blocked"
    assert facade.state["auto_resume_pending"] is False
    assert facade.state["resume_after_unlock"] is False
    assert facade.state["runtime_diag_code"] == "auto_resume_loop_guard"


def test_lock_controller_blocks_windows_lock_for_auto_resumed_session():
    calls = []
    result = lock_controller.request_windows_lock(
        session_id="sess-7y-return",
        risk=95,
        avg_risk=91.0,
        ml=1,
        lock_reason="post_unlock_high_risk",
        previous_state={
            "session_id": "sess-7y-return",
            "return_verification": True,
            "auto_resume_loop_guard_armed": True,
            "auto_resume_attempt_count": 1,
        },
        lock_workstation_result=lambda: calls.append(True) or {
            "lockAttempted": True,
            "lockSucceeded": True,
            "windowsLockAttempted": True,
            "windowsLockSucceeded": True,
        },
    )

    payload = result["payload"]
    assert result["skipped"] is True
    assert result["blocked"] is True
    assert calls == []
    assert payload["final_action"] == "auto_resume_high_risk_blocked"
    assert payload["runtime_diag_code"] == "auto_resume_high_risk_blocked"
    assert payload["flow"] == "resume_blocked"
    assert payload["runtime_status"] == "resume_blocked"
    assert payload["lock_loop_guard_block_auto_resume"] is True
    assert payload["auto_resume_pending"] is False
    assert payload["resume_after_unlock"] is False
    assert payload["windowsLockAttempted"] is False


def test_resume_controller_claims_resume_before_async_worker(monkeypatch):
    facade = _Facade()
    started = []
    monkeypatch.setattr(resume_controller, "_legacy", lambda: _Legacy(facade), raising=False)
    monkeypatch.setattr(resume_controller.worker_processes, "process_alive", lambda *_a, **_k: False)

    class _Thread:
        def __init__(self, *args, **kwargs):
            started.append((args, kwargs))
        def start(self):
            started.append("started")

    monkeypatch.setattr(resume_controller.threading, "Thread", _Thread)

    state = {
        "session_id": "sess-claim",
        "session_kind": "protected",
        "active": False,
        "status": "resume_pending",
        "runtime_status": "resume_pending",
        "forced_stop": True,
        "protected_action_requested": True,
        "final_action": "windows_locked",
        "lock_controller_handoff": True,
        "lock_handoff_id": "handoff-claim",
        "auto_resume_pending": True,
        "resume_after_unlock": True,
    }

    bridge = _Bridge()
    assert resume_controller.maybe_resume_after_unlock(bridge, state=state) is True
    assert started
    assert facade.state["auto_resume_in_progress"] is True
    assert facade.state["resume_in_progress"] is True
    assert facade.state["auto_resume_pending"] is False
    assert facade.state["resume_after_unlock"] is False
    assert facade.state["auto_resume_attempt_count"] == 1
    assert facade.state["runtime_diag_code"] == "auto_resume_claimed"


def test_resume_controller_uses_persisted_claim_over_stale_refresh_state(monkeypatch):
    facade = _Facade()
    facade.state = {
        "session_id": "sess-stale",
        "session_kind": "protected",
        "active": False,
        "status": "resume_in_progress",
        "runtime_status": "resume_in_progress",
        "forced_stop": True,
        "protected_action_requested": True,
        "final_action": "windows_locked",
        "lock_controller_handoff": True,
        "lock_handoff_id": "handoff-stale",
        "auto_resume_pending": False,
        "resume_after_unlock": False,
        "auto_resume_in_progress": True,
        "resume_in_progress": True,
        "auto_resume_attempt_count": 1,
        "auto_resume_claim_id": "claim-stale",
        "auto_resume_claimed_at": 999.0,
    }
    monkeypatch.setattr(resume_controller, "_legacy", lambda: _Legacy(facade), raising=False)
    monkeypatch.setattr(resume_controller.worker_processes, "process_alive", lambda *_a, **_k: False)

    stale_state = {
        "session_id": "sess-stale",
        "session_kind": "protected",
        "active": False,
        "status": "resume_pending",
        "runtime_status": "resume_pending",
        "forced_stop": True,
        "protected_action_requested": True,
        "final_action": "windows_locked",
        "lock_controller_handoff": True,
        "lock_handoff_id": "handoff-stale",
        "auto_resume_pending": True,
        "resume_after_unlock": True,
    }

    assert resume_controller.maybe_resume_after_unlock(_Bridge(), state=stale_state) is False
    assert facade.state["auto_resume_in_progress"] is True
    assert facade.state["auto_resume_attempt_count"] == 1


def test_manual_high_risk_still_requests_windows_lock():
    calls = []
    result = lock_controller.request_windows_lock(
        session_id="sess-manual",
        risk=95,
        avg_risk=91.0,
        ml=1,
        lock_reason="manual_high_risk",
        previous_state={"session_id": "sess-manual"},
        lock_workstation_result=lambda: calls.append(True) or {
            "lockAttempted": True,
            "lockSucceeded": True,
            "windowsLockAttempted": True,
            "windowsLockSucceeded": True,
        },
    )

    payload = result["payload"]
    assert result["skipped"] is False
    assert calls == [True]
    assert payload["final_action"] == "windows_locked"
    assert payload["auto_resume_pending"] is True
    assert payload["resume_after_unlock"] is True


def test_expected_exit_after_auto_resume_block_writes_resume_blocked(monkeypatch):
    state = {
        "session_id": "sess-blocked",
        "run_id": "run-blocked",
        "user_id": "alice",
        "session_kind": "protected",
        "active": True,
        "flow": "protected_active",
        "status": "ok",
    }
    monitor_hb = lock_controller.build_return_verification_blocked_payload(
        session_id="sess-blocked",
        risk=96,
        avg_risk=91.0,
        ml=1,
        previous_state={
            "session_id": "sess-blocked",
            "return_verification": True,
            "auto_resume_loop_guard_armed": True,
            "auto_resume_attempt_count": 1,
        },
        lock_fields={"windowsLockAttempted": False, "windowsLockSucceeded": False},
        lock_reason="post_unlock_high_risk",
    )
    written = []

    class Facade:
        def read_session_state(self, default=None):
            return dict(state)
        def write_session_state(self, payload):
            written.append(dict(payload))
            return True
        def read_worker_heartbeat(self, kind, default=None):
            return dict(monitor_hb) if kind == "monitor" else {}

    class Legacy:
        def _facade(self):
            return Facade()

    class Bridge:
        _runtime_state = {}
        def requestRefresh(self, reason, force=False):
            pass

    monkeypatch.setattr(stop_controller, "_legacy", lambda: Legacy())

    ok = stop_controller._expected_exit_after_lock_handoff(Bridge(), "monitor", {"exit_code": 0})

    assert ok is True
    assert written
    latest = written[-1]
    assert latest["flow"] == "resume_blocked"
    assert latest["status"] == "auto_resume_high_risk_blocked"
    assert latest["runtime_status"] == "resume_blocked"
    assert latest["auto_resume_pending"] is False
    assert latest["resume_after_unlock"] is False
    assert latest["technical_failure"] is False
