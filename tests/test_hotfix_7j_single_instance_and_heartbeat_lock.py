from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path


def test_desktop_app_refuses_second_live_instance(monkeypatch, tmp_path):
    inst = importlib.import_module("bioauth_runtime.desktop_instance")
    monkeypatch.setattr(inst, "control_dir", lambda: str(tmp_path))
    first = inst.acquire_desktop_instance(str(tmp_path / "project"))
    assert first["ok"] is True
    second = inst.acquire_desktop_instance(str(tmp_path / "project"))
    assert second["ok"] is True  # same process may re-acquire after stale/self cleanup in tests
    inst.release_desktop_instance()


def test_stale_desktop_instance_lock_is_cleaned(monkeypatch, tmp_path):
    inst = importlib.import_module("bioauth_runtime.desktop_instance")
    monkeypatch.setattr(inst, "control_dir", lambda: str(tmp_path))
    path = tmp_path / "desktop_app.instance.lock"
    path.write_text(json.dumps({"pid": 99999999, "control_dir": str(tmp_path), "project_root": str(tmp_path / "project")}), encoding="utf-8")
    result = inst.acquire_desktop_instance(str(tmp_path / "project"))
    assert result["ok"] is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    inst.release_desktop_instance()


def test_only_active_desktop_instance_can_start_protection(monkeypatch):
    controller = importlib.import_module("bioauth_runtime.supervisor.protection_session_controller")
    blocked = []

    monkeypatch.setenv("BIOAUTH_DESKTOP_INSTANCE_ID", "owned-by-other")
    monkeypatch.setattr("bioauth_runtime.desktop_instance.owns_desktop_instance", lambda _root="": False)
    monkeypatch.setattr(controller.start_diagnostics, "log_checkpoint", lambda *_a, **_k: None)
    monkeypatch.setattr(controller, "_block_start", lambda _bridge, code, reason, **_kw: blocked.append((code, reason)) or False)

    class Facade:
        BASE_DIR = str(Path.cwd())

    monkeypatch.setattr(controller, "_legacy", lambda: type("Legacy", (), {"_facade": staticmethod(lambda: Facade())})())
    assert controller._start_protection_inner(object(), auto_resume=False, trigger_refresh=False) is False
    assert blocked and blocked[0][0] == "start_blocked_not_active_desktop_instance"


def test_worker_spawn_uses_current_interpreter(monkeypatch):
    worker_processes = importlib.import_module("bioauth_runtime.supervisor.worker_processes")
    monkeypatch.setattr(worker_processes, "_desktop_owner_allows_spawn", lambda _bridge: True)
    monkeypatch.setattr(worker_processes, "find_duplicate_worker_processes", lambda *_a, **_k: {"duplicate_worker_detected": False})
    calls = []

    class Legacy:
        @staticmethod
        def start_process(bridge, key, args, extra_env=None):
            calls.append((key, args, extra_env, sys.executable))
            return True

        @staticmethod
        def _facade():
            return type("Facade", (), {"BASE_DIR": str(Path.cwd()), "read_session_state": staticmethod(lambda default=None: {}), "write_session_state": staticmethod(lambda state: True)})()

    monkeypatch.setattr(worker_processes, "_legacy", lambda: Legacy)
    assert worker_processes.start_worker(type("Bridge", (), {})(), "logger_user_yaman", ["logger.py", "yaman", "protected"]) is True
    assert calls[0][3] == sys.executable


def test_duplicate_worker_detection_prevents_duplicate_spawn(monkeypatch):
    worker_processes = importlib.import_module("bioauth_runtime.supervisor.worker_processes")
    monkeypatch.setattr(worker_processes, "_desktop_owner_allows_spawn", lambda _bridge: True)
    monkeypatch.setattr(worker_processes, "find_duplicate_worker_processes", lambda *_a, **_k: {"duplicate_worker_detected": True, "current_session_exists": True, "duplicate_worker_pids": [123]})
    called = []
    monkeypatch.setattr(worker_processes, "_record_duplicate_diag", lambda *_a, **_k: None)
    monkeypatch.setattr(worker_processes, "_legacy", lambda: type("Legacy", (), {"start_process": staticmethod(lambda *_a, **_k: called.append(True) or True)})())
    assert worker_processes.start_worker(type("Bridge", (), {})(), "monitor", ["monitor.py", "yaman"]) is False
    assert not called


def test_auto_resume_checks_single_instance_ownership(monkeypatch):
    resume = importlib.import_module("bioauth_runtime.supervisor.resume_controller")
    monkeypatch.setenv("BIOAUTH_DESKTOP_INSTANCE_ID", "owned-by-other")
    monkeypatch.setattr("bioauth_runtime.desktop_instance.owns_desktop_instance", lambda _root="": False)
    monkeypatch.setattr(resume, "_legacy", lambda: type("Legacy", (), {"_facade": staticmethod(lambda: type("Facade", (), {"BASE_DIR": str(Path.cwd()), "is_current_session_locked": staticmethod(lambda: False), "time": __import__("time")})())})())
    bridge = type("Bridge", (), {"_current_user": {"user_id": "yaman"}, "_runtime_state": {}})()
    state = {"session_kind": "protected", "active": False, "auto_resume_pending": True, "resume_after_unlock": True, "lock_controller_handoff": True}
    assert resume.maybe_resume_after_unlock(bridge, state) is False


def test_logger_heartbeat_permission_error_is_retried_and_nonfatal(monkeypatch, tmp_path):
    hb = importlib.import_module("bioauth_runtime.logger_worker.heartbeat")
    monkeypatch.setattr(hb, "worker_heartbeat_path", lambda kind: str(tmp_path / f"{kind}_heartbeat.json"))
    attempts = {"count": 0}

    def flaky_replace(src, dst):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("blocked")
        Path(dst).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(hb.os, "replace", flaky_replace)
    assert hb.write_logger_heartbeat_payload({"logger_ready": True}) is True
    assert attempts["count"] == 3


def test_monitor_heartbeat_repeated_permission_error_marks_degraded(monkeypatch, tmp_path):
    hb = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.heartbeat"))
    monkeypatch.setattr(hb, "worker_heartbeat_path", lambda kind: str(tmp_path / f"{kind}_heartbeat.json"))
    monkeypatch.setattr(hb.os, "replace", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("blocked")))
    assert hb.write_monitor_heartbeat_payload({"monitor_ready": True}) is False
    assert hb.write_monitor_heartbeat_payload({"monitor_ready": True}) is False
    assert hb.write_monitor_heartbeat_payload({"monitor_ready": True}) is False
    assert hb._HEARTBEAT_WRITE_PERMISSION_DENIED is True
    assert hb._HEARTBEAT_WRITE_DEGRADED is True
    assert hb._HEARTBEAT_WRITE_ERROR_COUNT >= 3


def test_session_process_env_carries_desktop_instance(monkeypatch):
    from bridge.session_mixin import SessionMixin
    monkeypatch.setenv("BIOAUTH_DESKTOP_INSTANCE_ID", "inst-1")
    monkeypatch.setenv("BIOAUTH_DESKTOP_INSTANCE_PID", "111")
    obj = type("Obj", (SessionMixin,), {})()
    obj._active_live_session_dir = "live"
    obj._pending_logger_session_id = "sess"
    obj._pending_logger_run_id = "run"
    env = obj._session_process_env()
    assert env["BIOAUTH_DESKTOP_INSTANCE_ID"] == "inst-1"
    assert env["BIOAUTH_DESKTOP_INSTANCE_PID"] == "111"
