from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_wrapper_guard_blocks_inherited_same_wrapper_relaunch(monkeypatch, tmp_path):
    guard = importlib.import_module("bioauth_runtime.wrapper_guard")
    root = tmp_path / "project"
    root.mkdir()
    script = root / "desktop_app.py"
    script.write_text("", encoding="utf-8")
    monkeypatch.setenv(guard._env_key("desktop_app", "PID"), "4242")
    monkeypatch.setenv(guard._env_key("desktop_app", "EXE"), r"D:\\project\\.venv\\Scripts\\python.exe")
    monkeypatch.setenv(guard._env_key("desktop_app", "SCRIPT"), str(script))
    monkeypatch.setenv(guard._env_key("desktop_app", "PROJECT_ROOT"), str(root))
    monkeypatch.setattr(guard, "_pid_alive", lambda pid: True)
    result = guard.enter_root_wrapper("desktop_app", project_root=str(root), script_path=str(script))
    assert result["ok"] is False
    assert result["wrapper_relaunch_blocked"] is True
    assert result["wrapper_name"] == "desktop_app"
    assert result["reason"] == "current_venv_already_active"


def test_wrapper_guard_replaces_dead_inherited_owner(monkeypatch, tmp_path):
    guard = importlib.import_module("bioauth_runtime.wrapper_guard")
    root = tmp_path / "project"
    root.mkdir()
    script = root / "logger.py"
    script.write_text("", encoding="utf-8")
    monkeypatch.setenv(guard._env_key("logger", "PID"), "4242")
    monkeypatch.setenv(guard._env_key("logger", "SCRIPT"), str(script))
    monkeypatch.setenv(guard._env_key("logger", "PROJECT_ROOT"), str(root))
    monkeypatch.setattr(guard, "_pid_alive", lambda pid: False)
    result = guard.enter_root_wrapper("logger", project_root=str(root), script_path=str(script))
    assert result["ok"] is True
    assert os.environ[guard._env_key("logger", "PID")] == str(os.getpid())


def test_desktop_wrapper_guards_before_importing_qt_impl():
    source = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    assert "enter_root_wrapper" in source
    assert source.index("enter_root_wrapper") < source.index("import_module(\"bioauth.app.desktop_app_impl\")")
    assert "subprocess.Popen" not in source
    assert "os.exec" not in source
    assert "runpy" not in source


def test_logger_and_monitor_wrappers_do_not_spawn_or_relaunch():
    for name in ("logger.py", "monitor.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "enter_root_wrapper" in source
        assert "subprocess" not in source
        assert "Popen" not in source
        assert "os.exec" not in source
        assert "runpy" not in source
        assert "raise SystemExit(main())" in source


def test_worker_bootstrap_prefers_owner_desktop_executable(monkeypatch):
    worker_bootstrap = importlib.reload(importlib.import_module("worker_bootstrap"))
    old_exe = sys.executable
    monkeypatch.setenv("BIOAUTH_DESKTOP_EXECUTABLE", r"D:\\project\\.venv\\Scripts\\python.exe")
    sys.executable = r"C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python311\\python.exe"
    try:
        result = worker_bootstrap.worker_python_executable(lambda path: True)
    finally:
        sys.executable = old_exe
    assert result == r"D:\\project\\.venv\\Scripts\\python.exe"


def test_worker_bootstrap_converts_owner_pythonw_to_console_python(monkeypatch):
    worker_bootstrap = importlib.reload(importlib.import_module("worker_bootstrap"))
    monkeypatch.setenv("BIOAUTH_DESKTOP_EXECUTABLE", r"D:\\project\\.venv\\Scripts\\pythonw.exe")
    result = worker_bootstrap.worker_python_executable(lambda path: path.endswith("python.exe"))
    assert result.lower().endswith(r"scripts\python.exe")
    assert "pythonw.exe" not in result.lower()


def test_worker_process_spawn_diag_uses_owner_desktop_executable(monkeypatch):
    worker_processes = importlib.import_module("bioauth_runtime.supervisor.worker_processes")
    monkeypatch.setenv("BIOAUTH_DESKTOP_EXECUTABLE", r"D:\\project\\.venv\\Scripts\\python.exe")
    monkeypatch.setattr(worker_processes.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(worker_processes, "_legacy", lambda: type("Legacy", (), {"_facade": staticmethod(lambda: type("Facade", (), {"read_session_state": staticmethod(lambda default=None: {}), "write_session_state": staticmethod(lambda state: True)})())})())
    bridge = type("Bridge", (), {})()
    worker_processes._record_spawn_diag(bridge, "logger_user_yaman")
    assert bridge._expected_worker_executable == r"D:\\project\\.venv\\Scripts\\python.exe"
    assert bridge._last_worker_spawn_executable == r"D:\\project\\.venv\\Scripts\\python.exe"
