
from __future__ import annotations

import json
import os
from pathlib import Path

import control
from bridge import refresh_runtime_helpers
from bridge import refresh_dashboard_helpers


class _Signal:
    def __init__(self):
        self.count = 0
    def emit(self, *args, **kwargs):
        self.count += 1


def _configure_control_storage(tmp_path: Path, monkeypatch) -> Path:
    control_dir = tmp_path / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    session_file = control_dir / "session_state.json"
    monkeypatch.setattr(control, "CONTROL_DIR", str(control_dir))
    monkeypatch.setattr(control, "SESSION_STATE_FILE", str(session_file))
    control.clear_session_state()
    return session_file


def test_prepare_session_state_removes_dead_owner_lock(monkeypatch, tmp_path) -> None:
    session_file = _configure_control_storage(tmp_path, monkeypatch)
    lock_path = Path(str(session_file) + ".lock")
    lock_path.write_text(json.dumps({"pid": 99999999, "created_at": 1}), encoding="utf-8")
    monkeypatch.setattr(control, "_safe_pid_running", lambda pid: False)

    result = control.prepare_session_state_for_new_runtime("test", stale_after_sec=0.1)

    assert result["ok"] is True
    assert result["action"].startswith("removed_lock")
    assert not lock_path.exists()


def test_prepare_session_state_preserves_live_owner_lock(monkeypatch, tmp_path) -> None:
    session_file = _configure_control_storage(tmp_path, monkeypatch)
    lock_path = Path(str(session_file) + ".lock")
    lock_path.write_text(json.dumps({"pid": os.getpid(), "created_at": 1}), encoding="utf-8")
    monkeypatch.setattr(control, "_safe_pid_running", lambda pid: True)

    result = control.prepare_session_state_for_new_runtime("test", stale_after_sec=0.0)

    assert result["ok"] is False
    assert result["reason"] == "lock_owner_running"
    assert lock_path.exists()


class _Proc:
    def __init__(self, alive=True):
        self.alive = alive
        self.terminated = False
    def poll(self):
        return None if self.alive else 0
    def terminate(self):
        self.terminated = True
        self.alive = False


class _FakeFacade:
    def __init__(self):
        import time
        self.time = time
        self.state = {"active": True, "session_kind": "protected", "logger_ready": False, "status": "starting", "user_id": "alice"}
        self.stops = []
        self.writes = []
        self.MONITOR_START_GRACE_SEC = 6.0
        self.MONITOR_SCRIPT = "monitor.py"
    def slugify_username(self, value):
        return str(value or "").lower()
    def request_stop(self, name):
        self.stops.append(str(name))
    def write_session_state(self, data):
        self.state = dict(data)
        self.writes.append(dict(data))
        return True
    def runtime_status_is_technical_failure(self, status):
        return str(status or "").lower() in {"logger_unavailable", "monitor_unavailable", "failed"}
    def runtime_status_awaits_evidence(self, status):
        return False
    def runtime_status_key(self, status, *, active=False, restricted=False):
        if str(status or "").lower() == "logger_unavailable":
            return "runtime_status_logger_unavailable"
        if not active:
            return "status_idle"
        return "status_active"
    def runtime_status_detail_key(self, status):
        return "runtime_detail_logger_unavailable" if str(status or "").lower() == "logger_unavailable" else ""
    def runtime_decision_key(self, decision):
        return f"decision_{str(decision or 'idle').lower()}"


class _App:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._pending_monitor_start = True
        self._pending_shadow_evidence_monitor_start = False
        self._pending_monitor_user_id = "alice"
        import time
        self._monitor_start_deadline = time.time() + 100.0
        self._monitor_launch_attempted = False
        self._running_processes = {"logger_user_alice": _Proc(alive=True)}
        self._runtime_state = {}
        self._logger_start_failed = False
        self._monitor_start_failed = False
        self.monitor_cleared = False
        self.statuses = []
        self.refreshes = []
        self.runtimeStateChanged = _Signal()
        self.controlsChanged = _Signal()
        self.profileChanged = _Signal()
        self.effectiveProductionReadyChanged = _Signal()
        self.dashboardStateChanged = _Signal()
    def _active_state_for_current_user(self):
        return dict(_FACADE.state)
    def _logger_process_key(self):
        return "logger_user_alice"
    def _logger_key(self):
        return "logger_user_alice"
    def _clear_pending_monitor_start(self):
        self.monitor_cleared = True
        self._pending_monitor_start = False
    def _fail_pending_monitor_start(self, **kwargs):
        return refresh_runtime_helpers.fail_pending_monitor_start(self, **kwargs)
    def _clear_pending_logger_start(self):
        self._pending_logger_start = False
    def _start_process(self, *args, **kwargs):
        raise AssertionError("monitor must not start before logger_ready")
    def _set_status(self, message, tone):
        self.statuses.append((message, tone))
    def _update_refresh_timer(self, force=False):
        self.refreshes.append(force)
    def _t(self, key, **kwargs):
        return key.format(**kwargs) if kwargs else key
    def _debug_trace(self, *args, **kwargs):
        pass
    def _session_flow(self, state=None):
        data = state if isinstance(state, dict) else {}
        return "protected_active" if data.get("active") and data.get("session_kind") == "protected" else "idle"
    def _format_elapsed(self, value):
        return "--"


_FACADE = _FakeFacade()


def test_monitor_does_not_start_before_logger_ready(monkeypatch) -> None:
    app = _App()
    _FACADE.state = {"active": True, "session_kind": "protected", "logger_ready": False, "status": "starting", "user_id": "alice"}
    monkeypatch.setattr(refresh_runtime_helpers, "_facade", lambda: _FACADE)

    refresh_runtime_helpers.maybe_finish_pending_monitor_start(app)

    assert app._pending_monitor_start is True
    assert "monitor" not in app._running_processes


def test_logger_ready_timeout_cleans_pending_monitor_without_spawning(monkeypatch) -> None:
    app = _App()
    _FACADE.state = {"active": True, "session_kind": "protected", "logger_ready": False, "status": "starting", "user_id": "alice"}
    app._monitor_start_deadline = 1.0
    monkeypatch.setattr(refresh_runtime_helpers, "_facade", lambda: _FACADE)
    monkeypatch.setattr(_FACADE.time, "time", lambda: 10.0)

    refresh_runtime_helpers.maybe_finish_pending_monitor_start(app)

    assert app.monitor_cleared is True
    assert _FACADE.writes[-1]["active"] is True
    assert _FACADE.writes[-1]["monitor_startup_error_kind"] == "logger_ready_timeout"
    assert "monitor" not in app._running_processes


def test_inactive_logger_failure_status_is_not_active(monkeypatch) -> None:
    app = _App()
    app._logger_start_failed = True
    monkeypatch.setattr(refresh_dashboard_helpers, "_facade", lambda: _FACADE)
    view = refresh_dashboard_helpers.build_runtime_state_view(
        app,
        {"active": False, "session_kind": "protected", "status": "idle", "technical_failure": True, "logger_failed": True},
    )

    assert view["statusCode"] == "logger_unavailable"
    assert view["statusLabel"] == "runtime_status_logger_unavailable"
    assert view["statusLabel"] != "Active"


def test_write_session_state_removes_fresh_dead_owner_lock(monkeypatch, tmp_path) -> None:
    session_file = _configure_control_storage(tmp_path, monkeypatch)
    lock_path = Path(str(session_file) + ".lock")
    lock_path.write_text(json.dumps({"pid": 99999998, "created_at": 1}), encoding="utf-8")
    monkeypatch.setattr(control, "_safe_pid_running", lambda pid: False)

    assert control.write_session_state({"active": False, "status": "ok"}) is True
    assert not lock_path.exists()
    assert control.read_session_state(default={}).get("status") == "ok"


def test_write_session_state_timeout_reports_lock_owner(monkeypatch, tmp_path) -> None:
    session_file = _configure_control_storage(tmp_path, monkeypatch)
    lock_path = Path(str(session_file) + ".lock")
    lock_path.write_text(json.dumps({"pid": os.getpid(), "created_at": 1}), encoding="utf-8")
    monkeypatch.setattr(control, "_safe_pid_running", lambda pid: True)

    assert control.write_session_state({"active": False}, timeout_sec=0.05, diagnostic_context="unit") is False
    diag = control.session_state_diagnostics()
    assert diag["last_issue"] == "session_state_write_failed"
    assert "owner_pid" in diag["detail"]
    assert diag["lock"]["owner_pid"] == os.getpid()


def test_prepare_session_state_recovers_live_stale_bioauth_owner(monkeypatch, tmp_path) -> None:
    session_file = _configure_control_storage(tmp_path, monkeypatch)
    lock_path = Path(str(session_file) + ".lock")
    lock_path.write_text(json.dumps({"pid": 4242, "created_at": 1}), encoding="utf-8")
    old_time = os.path.getmtime(lock_path) - 120
    os.utime(lock_path, (old_time, old_time))
    monkeypatch.setattr(control, "_safe_pid_running", lambda pid: True if int(pid) == 4242 else False)
    monkeypatch.setattr(control, "_process_details_for_pid", lambda pid: {
        "pid": int(pid),
        "alive": True,
        "command_line": r"C:\\Project\\BioAuth_P2I_Phase12_Companion_RC\\logger.py alakhrsss protected",
        "executable": r"C:\\Python311\\python.exe",
        "source": "test",
    })
    killed = []
    def fake_terminate(pid, *, timeout_sec=2.0):
        killed.append(int(pid))
        return True
    monkeypatch.setattr(control, "_terminate_process_for_stale_session_lock", fake_terminate)

    result = control.prepare_session_state_for_new_runtime("test", stale_after_sec=1.0)

    assert result["ok"] is True
    assert result["action"].startswith("recovered_live_stale_owner")
    assert killed == [4242]
    assert not lock_path.exists()


def test_prepare_session_state_removes_legacy_lock_when_pid_reused_by_non_bioauth_owner(monkeypatch, tmp_path) -> None:
    session_file = _configure_control_storage(tmp_path, monkeypatch)
    lock_path = Path(str(session_file) + ".lock")
    # Legacy lock: created_at was lock-acquisition time, not process birth time.
    # If Windows later reuses the PID for a non-BioAuth process, startup must
    # remove the stale BioAuth lock instead of preserving it forever.
    lock_path.write_text(json.dumps({"pid": 4343, "created_at": 1}), encoding="utf-8")
    old_time = os.path.getmtime(lock_path) - 120
    os.utime(lock_path, (old_time, old_time))
    monkeypatch.setattr(control, "_safe_pid_running", lambda pid: True if int(pid) == 4343 else False)
    monkeypatch.setattr(control, "_process_details_for_pid", lambda pid: {
        "pid": int(pid),
        "alive": True,
        "command_line": r"C:\\Windows\\System32\\notepad.exe",
        "executable": r"C:\\Windows\\System32\\notepad.exe",
        "source": "test",
        "created_at": 100.0,
    })
    monkeypatch.setattr(control, "_terminate_process_for_stale_session_lock", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not terminate non-BioAuth process")))

    result = control.prepare_session_state_for_new_runtime("test", stale_after_sec=1.0)

    assert result["ok"] is True
    assert result["action"] in {"removed_lock:owner_identity_mismatch_or_pid_reused", "removed_lock:owner_not_running"}
    assert not lock_path.exists()


def test_prepare_session_state_removes_new_lock_when_process_birth_mismatches(monkeypatch, tmp_path) -> None:
    session_file = _configure_control_storage(tmp_path, monkeypatch)
    lock_path = Path(str(session_file) + ".lock")
    lock_path.write_text(
        json.dumps({"pid": 5454, "created_at": 10, "process_created_at": 111.0, "lock_version": 2}),
        encoding="utf-8",
    )
    monkeypatch.setattr(control, "_safe_pid_running", lambda pid: True if int(pid) == 5454 else False)
    monkeypatch.setattr(control, "_process_created_at_for_pid", lambda pid: 222.0 if int(pid) == 5454 else 0.0)

    result = control.prepare_session_state_for_new_runtime("test", stale_after_sec=0.0)

    assert result["ok"] is True
    assert result["action"] == "removed_lock:owner_identity_mismatch_or_pid_reused"
    assert not lock_path.exists()


def test_acquire_session_state_lock_writes_process_identity(monkeypatch, tmp_path) -> None:
    session_file = _configure_control_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(control, "_current_process_created_at", lambda: 123456.0)

    lock_path = control._acquire_session_state_file_lock(timeout_sec=0.2)
    try:
        payload = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    finally:
        control._release_session_state_file_lock(lock_path)

    assert payload["pid"] == os.getpid()
    assert payload["process_created_at"] == 123456.0
    assert payload["lock_version"] == 2
    assert payload["role"] == "session_state_writer"
    assert payload.get("instance_id")
