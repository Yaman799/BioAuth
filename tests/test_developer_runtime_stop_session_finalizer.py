from __future__ import annotations

import subprocess
import types

import bridge.session_runtime_helpers as helpers


class DummySignal:
    def __init__(self):
        self.count = 0

    def emit(self):
        self.count += 1


class DummyProcess:
    def __init__(self, *, exits_on_terminate: bool = True):
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.exits_on_terminate = exits_on_terminate
        self.wait_calls = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if self.exits_on_terminate:
            self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.returncode is None:
            raise subprocess.TimeoutExpired(cmd="dummy", timeout=timeout)
        return self.returncode


class FakeFacade:
    def __init__(self, state=None):
        self.state = dict(state or {})
        self.stop_requests = []
        self.stop_clears = []
        self.cache_invalidated = 0
        self.os = __import__("os")
        self.subprocess = subprocess
        self.time = __import__("time")
        self.writes = []

    def request_stop(self, name):
        self.stop_requests.append(name)

    def clear_stop(self, name):
        self.stop_clears.append(name)

    def read_session_state(self, default=None):
        return dict(self.state or (default or {}))

    def write_session_state(self, data):
        self.state = dict(data)
        self.writes.append(dict(data))
        return True

    def invalidate_session_discovery_cache(self):
        self.cache_invalidated += 1


class BackendStub:
    def __init__(self, facade, processes):
        self._current_user = {"user_id": "yaman"}
        self._running_processes = dict(processes)
        self._pending_monitor_start = True
        self._pending_logger_start = True
        self._pending_logger_session_kind = "protected"
        self._active_live_session_dir = facade.state.get("live_session_dir", "")
        self._last_alert_signature = "stale-alert"
        self._runtime_state = dict(facade.state)
        self.runtimeStateChanged = DummySignal()
        self.controlsChanged = DummySignal()
        self.dashboardStateChanged = DummySignal()
        self.status_messages = []
        self.refreshes = []
        self.debug_events = []
        self.dashboard_invalidated = 0
        self.history_cleared = 0
        self.cleanup_count = 0

    def _active_state_for_current_user(self):
        return dict(self._runtime_state)

    def _safe_user(self):
        return "yaman"

    def _logger_key(self):
        return "logger_user_yaman"

    def _logger_process_key(self):
        return "logger_user_yaman"

    def _clear_pending_monitor_start(self):
        self._pending_monitor_start = False

    def _clear_pending_logger_start(self):
        self._pending_logger_start = False
        self._pending_logger_session_kind = ""

    def _clear_history_archive_watch(self):
        self.history_cleared += 1

    def _invalidate_dashboard_snapshot_cache(self):
        self.dashboard_invalidated += 1

    def _cleanup_processes(self):
        self.cleanup_count += 1
        for key, proc in list(self._running_processes.items()):
            if proc.poll() is not None:
                self._running_processes.pop(key, None)

    def _debug_trace(self, category, message, payload=None, level="info"):
        self.debug_events.append((category, message, payload or {}, level))

    def _set_status(self, message, tone):
        self.status_messages.append((message, tone))

    def _update_refresh_timer(self, force=False):
        self.refreshes.append(("timer", force))

    def requestRefresh(self, reason, force=False):
        self.refreshes.append((reason, force))

    def _session_flow(self):
        return helpers._normal_user_session_flow(self, self._runtime_state)

    def _t(self, key):
        return key


def active_protected_state(tmp_path):
    return {
        "active": True,
        "session_id": "sid-1",
        "run_id": "run-1",
        "user_id": "yaman",
        "session_kind": "protected",
        "status": "transitioning",
        "decision": "pending",
        "monitor_ready": True,
        "logger_ready": True,
        "live_session_dir": str(tmp_path),
        "runtime_recent_decisions": ["suspicious"],
        "runtime_recent_risks": [75.0],
        "runtime_diag_code": "pending_state",
        "runtime_diag_reason": "awaiting evidence",
        "runtime_transition_status": "transitioning",
        "runtime_window_count": 4,
        "runtime_warning_count": 2,
        "production_ready": False,
        "approval_status": "approved_for_shadow",
    }


def test_stop_finalizer_stops_monitor_and_logger_and_resets_telemetry(monkeypatch, tmp_path):
    facade = FakeFacade(active_protected_state(tmp_path))
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    backend = BackendStub(
        facade,
        {
            "monitor": DummyProcess(),
            "logger_user_yaman": DummyProcess(),
        },
    )

    result = helpers.finalize_protected_session_stop(backend, reason="user_requested")

    assert result["ok"] is True
    assert facade.stop_requests == ["monitor", "logger_user_yaman"]
    assert result["monitor"]["terminated"] is True
    assert result["logger"]["terminated"] is True
    assert backend._pending_monitor_start is False
    assert backend._pending_logger_start is False
    assert backend._active_live_session_dir is None
    assert backend._last_alert_signature is None
    assert facade.state["active"] is False
    assert facade.state["session_state"] == "stopped"
    assert facade.state["flow"] == "idle"
    assert facade.state["runtime_status"] == "idle"
    assert facade.state["decision"] == "stopped"
    assert facade.state["runtime_recent_decisions"] == []
    assert facade.state["runtime_recent_risks"] == []
    assert facade.state["runtime_diag_code"] == ""
    assert facade.state["runtime_window_count"] == 0
    assert facade.state["runtime_warning_count"] == 0
    assert facade.state["production_ready"] is False
    assert facade.state["approval_status"] == "approved_for_shadow"
    assert helpers._normal_user_session_flow(backend, facade.state) == "idle"
    assert (tmp_path / "session_terminal_state.json").exists()
    assert backend.runtimeStateChanged.count >= 1
    assert backend.controlsChanged.count >= 1
    assert any(event[1] == "protected_session_finalized" for event in backend.debug_events)


def test_stop_finalizer_is_idempotent_without_processes(monkeypatch, tmp_path):
    stopped = active_protected_state(tmp_path)
    stopped.update({"active": False, "session_state": "stopped", "status": "stopped", "decision": "stopped"})
    facade = FakeFacade(stopped)
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    backend = BackendStub(facade, {})

    first = helpers.finalize_protected_session_stop(backend, reason="user_requested")
    second = helpers.finalize_protected_session_stop(backend, reason="user_requested")

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["monitor"]["found"] is False
    assert second["logger"]["found"] is False
    assert facade.state["active"] is False
    assert facade.state["flow"] == "idle"
    assert helpers._normal_user_session_flow(backend, facade.state) == "idle"


def test_stop_finalizer_force_kills_orphan_logger_when_monitor_already_dead(monkeypatch, tmp_path):
    facade = FakeFacade(active_protected_state(tmp_path))
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    monitor = DummyProcess()
    monitor.returncode = 0
    stuck_logger = DummyProcess(exits_on_terminate=False)
    backend = BackendStub(facade, {"monitor": monitor, "logger_user_yaman": stuck_logger})

    result = helpers.finalize_protected_session_stop(backend, reason="user_requested", wait_timeout=0.01)

    assert result["monitor"]["was_alive"] is False
    assert result["logger"]["was_alive"] is True
    assert result["logger"]["forced"] is True
    assert stuck_logger.killed is True
    assert facade.state["active"] is False
    assert facade.state["runtime_status"] == "idle"
    assert helpers._normal_user_session_flow(backend, facade.state) == "idle"


def test_stop_production_monitor_delegates_to_finalizer(monkeypatch, tmp_path):
    facade = FakeFacade(active_protected_state(tmp_path))
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    backend = BackendStub(facade, {"monitor": DummyProcess(), "logger_user_yaman": DummyProcess()})

    helpers.stop_production_monitor(backend, silent=False)

    assert facade.state["session_state"] == "stopped"
    assert facade.state["active"] is False
    assert any(msg == "Protected session stopped. Ready to start monitoring again." for msg, _tone in backend.status_messages)
    assert ("session:protected_stop_finalized", True) in backend.refreshes


def test_stop_available_for_orphan_logger_without_monitor(monkeypatch, tmp_path):
    facade = FakeFacade(active_protected_state(tmp_path))
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    backend = BackendStub(facade, {"logger_user_yaman": DummyProcess()})

    assert helpers._protected_session_stop_available(backend) is True


def test_stop_available_for_stale_active_protected_state_without_processes(monkeypatch, tmp_path):
    facade = FakeFacade(active_protected_state(tmp_path))
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    backend = BackendStub(facade, {})

    assert helpers._protected_session_stop_available(backend) is True
    result = helpers.finalize_protected_session_stop(backend, reason="user_requested")
    assert result["ok"] is True
    assert helpers._protected_session_stop_available(backend) is False
    assert helpers._normal_user_session_flow(backend, facade.state) == "idle"


def test_stop_unavailable_for_shadow_state_with_shadow_logger_only(monkeypatch, tmp_path):
    shadow_state = active_protected_state(tmp_path)
    shadow_state.update({"session_kind": "shadow_evidence", "runtime_mode": "shadow_evidence"})
    facade = FakeFacade(shadow_state)
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    backend = BackendStub(facade, {"shadow_logger_user_yaman": DummyProcess()})
    backend._pending_logger_start = False
    backend._pending_logger_session_kind = ""

    assert helpers._protected_session_stop_available(backend) is False
