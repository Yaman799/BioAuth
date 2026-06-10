from __future__ import annotations

import subprocess

import bridge.session_runtime_helpers as helpers


class DummySignal:
    def __init__(self):
        self.count = 0

    def emit(self):
        self.count += 1


class DummyProcess:
    def __init__(self, *, exits_on_terminate: bool = True, pid: int = 1234):
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.exits_on_terminate = exits_on_terminate
        self.pid = pid

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
        self.cleared = 0

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

    def clear_session_state(self):
        self.state = {}
        self.cleared += 1

    def invalidate_session_discovery_cache(self):
        self.cache_invalidated += 1

    def slugify_username(self, value):
        return str(value or "").strip().lower().replace(" ", "_")


class BackendStub:
    def __init__(self, facade, processes):
        self._current_user = {"user_id": "yaman"}
        self._running_processes = dict(processes)
        self._pending_monitor_start = True
        self._pending_logger_start = True
        self._pending_logger_session_kind = "protected"
        self._active_live_session_dir = facade.state.get("live_session_dir", "")
        self._last_alert_signature = "old-alert"
        self._runtime_state = dict(facade.state)
        self.runtimeStateChanged = DummySignal()
        self.controlsChanged = DummySignal()
        self.dashboardStateChanged = DummySignal()
        self.refreshes = []
        self.debug_events = []
        self.history_cleared = 0
        self.cleanup_count = 0

    def _safe_user(self):
        return "yaman"

    def _logger_key(self):
        return "logger_user_yaman"

    def _logger_process_key(self):
        return "logger_user_yaman"

    def _active_state_for_current_user(self):
        return dict(self._runtime_state)

    def _clear_pending_monitor_start(self):
        self._pending_monitor_start = False

    def _clear_pending_logger_start(self):
        self._pending_logger_start = False
        self._pending_logger_session_kind = ""

    def _clear_pending_shadow_evidence_monitor_start(self):
        self.shadow_pending_cleared = True

    def _clear_history_archive_watch(self):
        self.history_cleared += 1

    def _cleanup_processes(self):
        self.cleanup_count += 1
        for key, proc in list(self._running_processes.items()):
            if proc.poll() is not None:
                self._running_processes.pop(key, None)

    def _debug_trace(self, category, message, payload=None, level="info"):
        self.debug_events.append((category, message, payload or {}, level))

    def _set_status(self, message, tone):
        pass

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
        "status": "ok",
        "decision": "pending",
        "monitor_ready": True,
        "logger_ready": True,
        "live_session_dir": str(tmp_path),
        "runtime_recent_decisions": ["suspicious"],
        "runtime_recent_risks": [89.0],
        "runtime_window_count": 7,
        "auto_resume_pending": True,
        "resume_after_unlock": True,
        "return_verification": True,
        "forced_stop": True,
        "app_locked": True,
        "screen_locked": True,
        "feedback_prompt": {"kind": "post_lock_confirmation"},
    }


def test_shutdown_cleanup_stops_tracked_monitor_and_logger_and_disables_next_launch_resume(monkeypatch, tmp_path):
    facade = FakeFacade(active_protected_state(tmp_path))
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    monkeypatch.setattr(helpers, "_pid_is_running", lambda _pid: False)
    backend = BackendStub(
        facade,
        {
            "monitor": DummyProcess(pid=1111),
            "logger_user_yaman": DummyProcess(pid=2222),
        },
    )

    result = helpers.shutdown_runtime_workers(backend, reason="app_shutdown", wait_timeout=0.01)

    assert result["ok"] is True
    assert "monitor" in facade.stop_requests
    assert "logger_user_yaman" in facade.stop_requests
    assert facade.state["active"] is False
    assert facade.state["flow"] == "idle"
    assert facade.state["session_state"] == "stopped"
    assert facade.state["auto_resume_pending"] is False
    assert facade.state["resume_after_unlock"] is False
    assert facade.state["return_verification"] is False
    assert facade.state["forced_stop"] is False
    assert facade.state["feedback_prompt"] == {}
    assert backend._pending_monitor_start is False
    assert backend._pending_logger_start is False
    assert backend._running_processes == {}


def test_stop_finalizer_leaves_stop_controls_when_no_process_handle_or_pid(monkeypatch, tmp_path):
    state = active_protected_state(tmp_path)
    state.pop("logger_pid", None)
    state.pop("monitor_pid", None)
    facade = FakeFacade(state)
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    monkeypatch.setattr(helpers, "_pid_is_running", lambda _pid: False)
    backend = BackendStub(facade, {})

    result = helpers.finalize_protected_session_stop(backend, reason="user_requested", wait_timeout=0.01)

    assert result["ok"] is True
    assert facade.state["active"] is False
    assert "monitor" in facade.stop_requests
    assert "logger_user_yaman" in facade.stop_requests
    # No local Popen handle and no PID means an older orphan worker may still
    # need the stop file; do not clear it immediately.
    assert "monitor" not in facade.stop_clears
    assert "logger_user_yaman" not in facade.stop_clears


def test_terminal_protected_state_clears_resume_and_lock_fields(tmp_path):
    facade = FakeFacade(active_protected_state(tmp_path))
    backend = BackendStub(facade, {})

    terminal = helpers._terminal_protected_session_state(backend, facade.state, reason="app_shutdown")

    assert terminal["active"] is False
    assert terminal["flow"] == "idle"
    assert terminal["auto_resume_pending"] is False
    assert terminal["resume_after_unlock"] is False
    assert terminal["return_verification"] is False
    assert terminal["forced_stop"] is False
    assert terminal["app_locked"] is False
    assert terminal["screen_locked"] is False
    assert terminal["feedback_prompt"] == {}
