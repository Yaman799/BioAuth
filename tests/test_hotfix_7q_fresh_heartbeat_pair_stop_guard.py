from __future__ import annotations

import time
from types import SimpleNamespace

from bioauth_runtime.supervisor import fresh_heartbeat_guard, stop_controller
from bioauth.workers.supervision import worker_pair_status


class _Facade:
    def __init__(self, state, heartbeats):
        self.state = dict(state)
        self.heartbeats = {str(k): dict(v) for k, v in heartbeats.items()}
        self.writes = []
        self.invalidated = False

    def read_session_state(self, default=None):
        return dict(self.state or (default or {}))

    def write_session_state(self, state):
        self.state = dict(state)
        self.writes.append(dict(state))
        return True

    def read_worker_heartbeat(self, kind, default=None):
        return dict(self.heartbeats.get(str(kind), default or {}))

    def invalidate_session_discovery_cache(self):
        self.invalidated = True


class _Legacy:
    def __init__(self, facade):
        self.facade = facade
        self.refreshes = []

    def _facade(self):
        return self.facade

    def _read_matching_worker_heartbeat(self, _bridge, kind, state):
        hb = self.facade.read_worker_heartbeat(kind, default={})
        if not hb:
            return {}
        if state.get("session_id") and hb.get("session_id") != state.get("session_id"):
            return {}
        if state.get("user_id") and hb.get("user_id") != state.get("user_id"):
            return {}
        return hb

    def worker_failure_detail(self, _bridge, _key, fallback):
        return fallback, {"exit_code": 1}

    def worker_diagnostics_snapshot(self, _bridge, _key):
        return {}

    def _request_refresh(self, bridge, reason, force):
        self.refreshes.append((bridge, reason, force))


class _Proc:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code


class _Bridge:
    def __init__(self):
        self._runtime_state = {}
        self._running_processes = {
            "logger_user_alice": _Proc(0),
            "monitor": _Proc(None),
        }
        self._worker_pair_status_cache = {}

    def _logger_process_key(self):
        return "logger_user_alice"

    def _logger_key(self):
        return "logger_user_alice"

    def _update_refresh_timer(self, force=False):
        self.refresh_force = bool(force)

    def _clear_pending_logger_start(self):
        self.clear_logger = True

    def _clear_pending_monitor_start(self):
        self.clear_monitor = True


def _state():
    return {
        "active": True,
        "session_kind": "protected",
        "session_id": "sess-7q",
        "run_id": "run-7q",
        "user_id": "alice",
        "flow": "protected_active",
        "logger_ready": True,
        "monitor_ready": True,
    }


def _heartbeats(age=0.0):
    stamp = time.time() - age
    return {
        "logger": {
            "worker_kind": "logger",
            "session_id": "sess-7q",
            "user_id": "alice",
            "heartbeat_at": stamp,
            "logger_ready": True,
            "capture_status": "capture_ok",
        },
        "monitor": {
            "worker_kind": "monitor",
            "session_id": "sess-7q",
            "user_id": "alice",
            "heartbeat_at": stamp,
            "monitor_ready": True,
            "runtime_status": "collecting",
            "runtime_decision": "pending",
        },
    }


def _install(monkeypatch, state=None, heartbeats=None):
    facade = _Facade(state or _state(), heartbeats or _heartbeats())
    legacy = _Legacy(facade)
    monkeypatch.setattr(stop_controller, "_legacy", lambda: legacy)
    monkeypatch.setattr(fresh_heartbeat_guard, "_legacy", lambda: legacy)
    return facade, legacy


def test_fresh_pair_heartbeats_block_logger_failed_pair_stop(monkeypatch):
    facade, _legacy = _install(monkeypatch)
    bridge = _Bridge()
    stop_calls = []
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda *_a, **_k: stop_calls.append(_k) or {})

    stop_controller.handle_logger_exit_after_ready(
        bridge,
        "logger_user_alice",
        diagnostics={"exit_code": 0, "reason": "cleanup"},
    )

    assert stop_calls == []
    assert facade.state["active"] is True
    assert facade.state["technical_failure"] is False
    assert facade.state["worker_pair_stop_blocked_by_fresh_heartbeats"] is True
    assert facade.state["failed_worker_candidate"] == "logger"
    assert bridge._worker_pair_status_cache["worker_pair_stop_blocked_by_fresh_heartbeats"] is True


def test_fresh_pair_heartbeats_block_monitor_failed_pair_stop(monkeypatch):
    facade, _legacy = _install(monkeypatch)
    bridge = _Bridge()
    bridge._running_processes["monitor"] = _Proc(0)
    stop_calls = []
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda *_a, **_k: stop_calls.append(_k) or {})

    stop_controller.handle_monitor_exit_after_ready(
        bridge,
        diagnostics={"exit_code": 0, "reason": "cleanup"},
    )

    assert stop_calls == []
    assert facade.state["active"] is True
    assert facade.state["worker_pair_stop_blocked_by_fresh_heartbeats"] is True
    assert facade.state["failed_worker_candidate"] == "monitor"


def test_stale_heartbeats_still_allow_worker_failure_path(monkeypatch):
    facade, _legacy = _install(monkeypatch, heartbeats=_heartbeats(age=45.0))
    bridge = _Bridge()
    stop_calls = []
    failure_calls = []
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda *_a, **_k: stop_calls.append(_k) or {"reason": _k.get("reason")})
    monkeypatch.setattr(stop_controller, "_write_failure_state", lambda *_a, **_k: failure_calls.append((_a, _k)))

    stop_controller.handle_logger_exit_after_ready(
        bridge,
        "logger_user_alice",
        diagnostics={"exit_code": 1, "reason": "cleanup"},
    )

    assert stop_calls and stop_calls[0]["reason"] == "logger_exited_after_ready"
    assert failure_calls
    assert "worker_pair_stop_blocked_by_fresh_heartbeats" not in facade.state


def test_worker_pair_status_treats_fresh_matching_heartbeats_as_alive(monkeypatch):
    import bioauth.workers.supervision as supervision

    bridge = SimpleNamespace(_running_processes={"logger_user_alice": _Proc(0), "monitor": _Proc(0)})
    monkeypatch.setattr(supervision, "read_heartbeat", lambda kind: _heartbeats()["logger" if kind == "logger_user_alice" else "monitor"])

    status = worker_pair_status(
        bridge,
        logger_key="logger_user_alice",
        monitor_key="monitor",
        session_id="sess-7q",
        user_id="alice",
        now=time.time(),
    )

    assert status["recommended_action"] == "ok"
    assert status["pair_healthy"] is True
