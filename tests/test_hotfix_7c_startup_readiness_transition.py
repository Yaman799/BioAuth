from __future__ import annotations

import inspect
import time

from bioauth_runtime.supervisor import heartbeat_store
from bioauth_runtime.supervisor import protection_session_controller as start_ctl
from bridge import refresh_runtime_helpers, session_runtime_helpers


class _Signal:
    def emit(self):
        pass


class _FakeFacade:
    LOGGER_SCRIPT = "logger.py"
    MONITOR_SCRIPT = "monitor.py"
    LOGGER_START_GRACE_SEC = 3.0
    MONITOR_START_GRACE_SEC = 3.0

    def __init__(self, tmp_path):
        import uuid

        self.time = time
        self.uuid = uuid
        self.state = {}
        self.writes = []
        self.heartbeats = {}
        self.tmp_path = tmp_path

    def slugify_username(self, value):
        return str(value or "").lower()

    def read_worker_heartbeat(self, kind, default=None):
        return dict(self.heartbeats.get(kind) or (default or {}))

    def write_session_state(self, state):
        self.state = dict(state or {})
        self.writes.append(dict(self.state))
        return True

    def read_session_state(self, default=None):
        return dict(self.state or (default or {}))


class _Bridge:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._pending_logger_session_id = "sess-1"
        self._pending_logger_user_id = "alice"
        self._pending_monitor_user_id = "alice"
        self._pending_monitor_start = True
        self._pending_logger_start = False
        self._runtime_state = {}
        self._debug_events = []
        self._running_processes = {}

    def _debug_trace(self, category, message, payload=None, level="info"):
        self._debug_events.append((category, message, dict(payload or {}), level))

    def _clear_pending_monitor_start(self):
        self._pending_monitor_start = False

    def _logger_process_key(self):
        return "logger_user_alice"

    def _active_state_for_current_user(self):
        return dict(self._runtime_state)


class _FakeLegacy:
    def __init__(self, facade):
        self.facade = facade

    def _facade(self):
        return self.facade

    def _read_matching_worker_heartbeat(self, bridge, kind, state=None):
        return session_runtime_helpers._read_matching_worker_heartbeat(bridge, kind, state or {})

    def merge_worker_heartbeats_into_state(self, bridge, state=None, persist=False):
        return session_runtime_helpers.merge_worker_heartbeats_into_state(bridge, state or {}, persist=persist)


def _base_state():
    return {
        "schema_version": 2,
        "user_id": "alice",
        "session_id": "sess-1",
        "run_id": "run-1",
        "session_kind": "protected",
        "active": True,
        "status": "starting",
        "flow": "protected_starting",
        "runtime_status": "starting",
        "runtime_decision": "pending",
        "pending_monitor_start": True,
        "worker_heartbeat_waiting_for": "logger",
        "logger_ready": False,
        "monitor_ready": False,
        "awaiting_evidence": True,
        "runtime_diag_code": "protected_starting",
        "runtime_diag_reason": "Waiting for logger readiness.",
    }


def _install(monkeypatch, tmp_path):
    facade = _FakeFacade(tmp_path)
    legacy = _FakeLegacy(facade)
    monkeypatch.setattr(session_runtime_helpers, "_facade", lambda: facade)
    monkeypatch.setattr(heartbeat_store, "_legacy", lambda: legacy)
    monkeypatch.setattr(start_ctl, "_legacy", lambda: legacy)
    return facade, _Bridge()


def _ready_heartbeats(session_id="sess-1"):
    now = time.time()
    return {
        "logger": {
            "worker_kind": "logger",
            "session_id": session_id,
            "user_id": "alice",
            "session_kind": "protected",
            "logger_ready": True,
            "active": True,
            "heartbeat_at": now,
        },
        "monitor": {
            "worker_kind": "monitor",
            "session_id": session_id,
            "user_id": "alice",
            "session_kind": "protected",
            "monitor_ready": True,
            "status": "ok",
            "heartbeat_at": now,
        },
    }


def test_monitor_readiness_clears_pending_monitor_start(monkeypatch, tmp_path):
    facade, bridge = _install(monkeypatch, tmp_path)
    facade.state = _base_state()
    bridge._runtime_state = dict(facade.state)
    facade.heartbeats = _ready_heartbeats()

    merged = session_runtime_helpers.merge_worker_heartbeats_into_state(bridge, facade.state, persist=True)

    assert merged["logger_ready"] is True
    assert merged["monitor_ready"] is True
    assert merged["pending_monitor_start"] is False
    assert merged["worker_heartbeat_waiting_for"] == ""
    assert facade.state["pending_monitor_start"] is False


def test_both_workers_ready_advances_flow_out_of_protected_starting(monkeypatch, tmp_path):
    facade, bridge = _install(monkeypatch, tmp_path)
    facade.state = _base_state()
    bridge._runtime_state = dict(facade.state)
    facade.heartbeats = _ready_heartbeats()

    merged = session_runtime_helpers.merge_worker_heartbeats_into_state(bridge, facade.state, persist=True)

    assert merged["flow"] == "protected_active"
    assert merged["runtime_status"] in {"collecting", "ok", "insufficient_evidence"}
    assert merged["runtime_decision"] == "pending"


def test_runtime_diag_no_longer_waits_for_logger_after_monitor_ready(monkeypatch, tmp_path):
    facade, bridge = _install(monkeypatch, tmp_path)
    facade.state = _base_state()
    bridge._runtime_state = dict(facade.state)
    facade.heartbeats = _ready_heartbeats()

    merged = session_runtime_helpers.merge_worker_heartbeats_into_state(bridge, facade.state, persist=True)

    assert merged["runtime_diag_code"] == "collecting_evidence"
    assert "waiting for logger readiness" not in merged["runtime_diag_reason"].lower()
    assert "awaiting evidence" in merged["runtime_diag_reason"].lower()


def test_stale_monitor_heartbeat_wrong_session_does_not_advance_startup(monkeypatch, tmp_path):
    facade, bridge = _install(monkeypatch, tmp_path)
    facade.state = _base_state()
    bridge._runtime_state = dict(facade.state)
    heartbeats = _ready_heartbeats()
    heartbeats["monitor"] = _ready_heartbeats(session_id="old-session")["monitor"]
    facade.heartbeats = heartbeats

    merged = session_runtime_helpers.merge_worker_heartbeats_into_state(bridge, facade.state, persist=True)

    assert merged["logger_ready"] is True
    assert not merged.get("monitor_ready")
    assert merged["pending_monitor_start"] is True
    assert merged["flow"] == "protected_starting"
    assert merged["runtime_diag_reason"] == "Waiting for logger readiness."


def test_transition_does_not_start_another_monitor_or_logger(monkeypatch, tmp_path):
    facade, bridge = _install(monkeypatch, tmp_path)
    facade.state = _base_state()
    bridge._runtime_state = dict(facade.state)
    facade.heartbeats = _ready_heartbeats()
    calls = []
    monkeypatch.setattr(bridge, "_start_process", lambda *args, **kwargs: calls.append(args) or True, raising=False)

    session_runtime_helpers.merge_worker_heartbeats_into_state(bridge, facade.state, persist=True)

    assert calls == []


def test_finish_pending_monitor_start_normalizes_startup_state(monkeypatch, tmp_path):
    facade, bridge = _install(monkeypatch, tmp_path)
    facade.state = _base_state()
    bridge._runtime_state = dict(facade.state)
    facade.heartbeats = _ready_heartbeats()

    monkeypatch.setattr(refresh_runtime_helpers, "maybe_finish_pending_monitor_start", lambda b: b._clear_pending_monitor_start())

    assert start_ctl._finish_pending_monitor_start(bridge) is True
    assert facade.state["pending_monitor_start"] is False
    assert facade.state["flow"] == "protected_active"
    assert any(event[1] == "protected_startup_state_advanced" for event in bridge._debug_events)


def test_refresh_still_has_no_worker_lifecycle_ownership():
    source = inspect.getsource(refresh_runtime_helpers._perform_refresh_now)
    for token in (
        "_maybe_finish_pending_logger_start(",
        "_maybe_finish_pending_monitor_start(",
        "check_worker_pair_liveness(",
        "_start_process(",
        "request_stop(",
        "recover_stale_protected_flow_without_workers(",
        "stop_current_session(",
    ):
        assert token not in source
