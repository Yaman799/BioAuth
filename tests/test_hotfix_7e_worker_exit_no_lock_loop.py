from __future__ import annotations

import time

from bioauth_runtime.monitor_worker import lock_controller
from bioauth_runtime.supervisor import resume_controller, stop_controller, worker_processes


class _Facade:
    def __init__(self):
        self.time = time
        self.state = {}
        self.writes = []
        self.stops = []
        self.heartbeats = {}
        self.locked = False

    def read_session_state(self, default=None):
        return dict(self.state or (default or {}))

    def write_session_state(self, state):
        self.state = dict(state or {})
        self.writes.append(dict(self.state))
        return True

    def request_stop(self, name):
        self.stops.append(str(name))

    def read_worker_heartbeat(self, kind, default=None):
        return dict(self.heartbeats.get(kind) or (default or {}))

    def should_stop(self, name):
        return False

    def invalidate_session_discovery_cache(self):
        pass

    def is_current_session_locked(self):
        return self.locked


class _Legacy:
    def __init__(self, facade):
        self.facade = facade
        self.refreshes = []
        self.diagnostics = {
            "exit_code": 0,
            "stdout_tail": ["[Logger] Archived session at C:/BioAuth/archive/session"],
            "stderr_tail": [],
            "reason": "cleanup",
        }

    def _facade(self):
        return self.facade

    def worker_failure_detail(self, _bridge, key, fallback):
        return f"{fallback} (exit code 0)", dict(self.diagnostics)

    def worker_diagnostics_snapshot(self, _bridge, key):
        return dict(self.diagnostics)

    def _request_refresh(self, _bridge, reason, force):
        self.refreshes.append((reason, force))


class _Bridge:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._runtime_state = {}
        self._running_processes = {}
        self._debug_events = []
        self._last_auto_resume_attempt_at = 0.0
        self._auto_resume_inflight = False

    def _logger_key(self):
        return "logger_user_alice"

    def _logger_process_key(self):
        return "logger_user_alice"

    def _update_refresh_timer(self, force=False):
        self.refresh_force = bool(force)

    def _debug_trace(self, category, message, payload=None, level="info"):
        self._debug_events.append((category, message, dict(payload or {}), level))


def _protected_active_state():
    return {
        "schema_version": 2,
        "user_id": "alice",
        "session_id": "sess-7e",
        "run_id": "run-7e",
        "session_kind": "protected",
        "active": True,
        "flow": "protected_active",
        "status": "ok",
        "runtime_status": "collecting",
        "runtime_decision": "pending",
        "logger_ready": True,
        "monitor_ready": True,
        "awaiting_evidence": True,
        "auto_resume_pending": False,
        "resume_after_unlock": False,
        "forced_stop": False,
        "app_locked": False,
        "screen_locked": False,
    }


def _install(monkeypatch):
    facade = _Facade()
    legacy = _Legacy(facade)
    bridge = _Bridge()
    facade.state = _protected_active_state()
    bridge._runtime_state = dict(facade.state)
    facade.heartbeats["logger"] = {
        "status": "stopped",
        "archived": True,
        "archive_path": "C:/BioAuth/archive/session",
        "archive_label": "interrupted",
        "archive_group": "rejected",
        "final_bucket": "rejected",
        "stop_reason": "listener_exit",
    }
    monkeypatch.setattr(stop_controller, "_legacy", lambda: legacy)
    monkeypatch.setattr(resume_controller, "_legacy", lambda: legacy)
    return facade, legacy, bridge


def test_logger_exited_after_ready_stops_monitor_once_and_clears_resume(monkeypatch):
    facade, _legacy, bridge = _install(monkeypatch)
    stops = []
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda *args, **kwargs: stops.append(kwargs) or {"monitor": {"ok": True}, "logger": {"ok": True}})

    stop_controller.handle_logger_exit_after_ready(bridge, "logger_user_alice", diagnostics={"exit_code": 0, "stdout_tail": ["archived"], "stderr_tail": []})

    assert len(stops) == 1
    assert facade.state["active"] is False
    assert facade.state["status"] == "logger_exited_after_ready"
    assert facade.state["runtime_status"] == "logger_exited_after_ready"
    assert facade.state["runtime_decision"] == "failed"
    assert facade.state["auto_resume_pending"] is False
    assert facade.state["resume_after_unlock"] is False
    assert facade.state["forced_stop"] is False
    assert facade.state["screen_locked"] is False
    assert facade.state["postLockConfirmationPending"] is False


def test_logger_exit_does_not_call_lock_controller(monkeypatch):
    facade, _legacy, bridge = _install(monkeypatch)
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda *args, **kwargs: {})
    monkeypatch.setattr(lock_controller, "request_windows_lock", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("lock must not run")))

    stop_controller.handle_logger_exit_after_ready(bridge, "logger_user_alice", diagnostics={"exit_code": 0})

    assert facade.state["runtime_diag_code"] == "logger_exited_after_ready"
    assert facade.state["lock_reason"] == ""


def test_monitor_exit_after_ready_does_not_call_lock_controller(monkeypatch):
    facade, _legacy, bridge = _install(monkeypatch)
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda *args, **kwargs: {})
    monkeypatch.setattr(lock_controller, "request_windows_lock", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("lock must not run")))

    stop_controller.handle_monitor_exit_after_ready(bridge, diagnostics={"exit_code": 0, "stderr_tail": ["monitor ended"]})

    assert facade.state["runtime_diag_code"] == "monitor_exited_after_ready"
    assert facade.state["auto_resume_pending"] is False
    assert facade.state["resume_after_unlock"] is False


def test_resume_controller_refuses_worker_technical_terminal_states(monkeypatch):
    facade, _legacy, bridge = _install(monkeypatch)
    technical = dict(_protected_active_state())
    technical.update({
        "active": False,
        "status": "logger_exited_after_ready",
        "runtime_status": "logger_exited_after_ready",
        "auto_resume_pending": True,
        "resume_after_unlock": True,
        "technical_failure": True,
    })
    starts = []
    monkeypatch.setattr(resume_controller.protection_session_controller, "start_protection", lambda *args, **kwargs: starts.append(kwargs) or True)

    assert resume_controller.maybe_resume_after_unlock(bridge, technical) is False
    assert starts == []


def test_resume_controller_resumes_only_after_lock_controller_handoff(monkeypatch):
    facade, _legacy, bridge = _install(monkeypatch)
    locked = lock_controller.build_terminal_lock_payload(
        session_id="sess-7e",
        risk=90,
        avg_risk=90.0,
        ml=90,
        screen_locked=True,
        previous_state={"session_kind": "protected"},
        lock_fields={"windowsLockSucceeded": True, "lockSucceeded": True},
        lock_reason="camera_unavailable",
    )
    locked["session_kind"] = "protected"
    starts = []
    monkeypatch.setattr(resume_controller.worker_processes, "stop_pair", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(resume_controller.worker_processes, "process_alive", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(resume_controller.protection_session_controller, "start_protection", lambda *args, **kwargs: starts.append(kwargs) or True)

    assert resume_controller.maybe_resume_after_unlock(bridge, locked) is True
    assert len(starts) == 1


def test_lock_loop_guard_throttles_repeated_same_session_reason(monkeypatch):
    first = lock_controller.build_terminal_lock_payload(
        session_id="sess-7e",
        risk=90,
        avg_risk=90.0,
        ml=90,
        screen_locked=True,
        previous_state={"session_kind": "protected"},
        lock_fields={"windowsLockSucceeded": True, "lockSucceeded": True},
        lock_reason="camera_unavailable",
    )
    calls = []
    result = lock_controller.request_windows_lock(
        session_id="sess-7e",
        risk=95,
        avg_risk=95.0,
        ml=95,
        lock_reason="camera_unavailable",
        previous_state=first,
        lock_workstation_result=lambda: calls.append(True) or {"windowsLockSucceeded": True},
    )

    assert result["skipped"] is True
    assert result["payload"]["lock_loop_guard_blocked"] is True
    assert calls == []


def test_worker_death_before_valid_window_stops_instead_of_locking(monkeypatch):
    facade, _legacy, bridge = _install(monkeypatch)
    facade.state.update({"runtime_prediction_ready": False, "high_risk_evidence": False})
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda *args, **kwargs: {})
    stop_controller.handle_logger_exit_after_ready(bridge, "logger_user_alice", diagnostics={"exit_code": 0})

    assert facade.state["technical_failure"] is True
    assert facade.state["high_risk_evidence"] is False
    assert facade.state["auto_resume_pending"] is False
    assert facade.state["final_action"] == "worker_exited_after_ready"


def test_worker_cleanup_registry_forgets_dead_process_once():
    class _Proc:
        def poll(self):
            return 0

    bridge = _Bridge()
    bridge._running_processes = {"logger_user_alice": _Proc(), "monitor": _Proc()}
    worker_processes._forget_completed_workers(bridge, ["logger_user_alice", "monitor"])

    assert bridge._running_processes == {}


def test_status_mapping_is_not_normal_after_logger_exit(monkeypatch):
    facade, _legacy, bridge = _install(monkeypatch)
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda *args, **kwargs: {})
    stop_controller.handle_logger_exit_after_ready(bridge, "logger_user_alice", diagnostics={"exit_code": 0})

    assert facade.state["runtime_decision"] != "normal"
    assert facade.state["decision"] != "normal"
    assert facade.state["riskAvailable"] is False
    assert facade.state["decisionRiskAvailable"] is False


def test_logger_exit_diagnostics_include_exit_and_archive_context(monkeypatch):
    facade, _legacy, bridge = _install(monkeypatch)
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda *args, **kwargs: {})
    stop_controller.handle_logger_exit_after_ready(
        bridge,
        "logger_user_alice",
        diagnostics={"exit_code": 0, "stdout_tail": ["archived"], "stderr_tail": [""], "reason": "cleanup"},
    )

    diag = facade.state["worker_exit_diagnostics"]
    assert diag["exit_code"] == 0
    assert diag["stop_requested"] is False
    assert diag["stdout_tail"] == ["archived"]
    assert diag["archive_path"] == "C:/BioAuth/archive/session"
    assert diag["stop_reason"] == "listener_exit"
