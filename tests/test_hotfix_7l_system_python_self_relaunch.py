from __future__ import annotations

import importlib
import os
import time
from pathlib import Path


def test_desktop_wrapper_pins_owner_executable_for_children(monkeypatch, tmp_path):
    guard = importlib.reload(importlib.import_module("bioauth_runtime.wrapper_guard"))
    root = tmp_path / "project"
    root.mkdir()
    script = root / "desktop_app.py"
    script.write_text("", encoding="utf-8")
    expected = r"D:\project\.venv\Scripts\python.exe"
    monkeypatch.setattr(guard.sys, "executable", expected)
    monkeypatch.delenv("BIOAUTH_DESKTOP_EXECUTABLE", raising=False)

    result = guard.enter_root_wrapper("desktop_app", project_root=str(root), script_path=str(script))

    assert result["ok"] is True
    assert os.environ["BIOAUTH_DESKTOP_EXECUTABLE"] == expected


def test_start_process_uses_owner_venv_for_logger_worker(monkeypatch, tmp_path):
    helpers = importlib.import_module("bridge.session_runtime_helpers")
    owner = r"D:\project\.venv\Scripts\python.exe"
    calls = []

    class Proc:
        pid = 7311
        stdout = None
        stderr = None

        def poll(self):
            return None

    class Subprocess:
        CREATE_NO_WINDOW = 0
        PIPE = object()

        @staticmethod
        def Popen(cmd, **kwargs):
            calls.append((list(cmd), dict(kwargs)))
            return Proc()

    class Facade:
        BASE_DIR = str(tmp_path)
        LOGGER_SCRIPT = str(tmp_path / "logger.py")
        LOGGER_START_GRACE_SEC = 5.0
        os = os
        subprocess = Subprocess
        time = time

        @staticmethod
        def _spawn_command(worker, *args):
            assert worker == "--worker-logger"
            return [owner, str(tmp_path / "logger.py"), *args]

        @staticmethod
        def translate_string(_language, key, **kwargs):
            return key.format(**kwargs)

    class Bridge:
        _language = "en"

        def __init__(self):
            self._running_processes = {}
            self.statuses = []

        def _cleanup_processes(self):
            return None

        def _set_status(self, value):
            self.statuses.append(value)

    monkeypatch.setenv("BIOAUTH_DESKTOP_EXECUTABLE", owner)
    monkeypatch.setattr(helpers, "_facade", lambda: Facade)
    bridge = Bridge()

    assert helpers.start_process(bridge, "logger_user_alice", [Facade.LOGGER_SCRIPT, "alice", "protected"], extra_env={"BIOAUTH_LIVE_SESSION_DIR": "live"}) is True

    cmd, kwargs = calls[0]
    assert cmd == [owner, str(tmp_path / "logger.py"), "alice", "protected"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["BIOAUTH_DESKTOP_EXECUTABLE"] == owner
    assert kwargs["env"]["BIOAUTH_LIVE_SESSION_DIR"] == "live"
    assert bridge._worker_diagnostics["logger_user_alice"]["cmd"][0] == owner


def test_start_process_uses_owner_venv_for_monitor_worker(monkeypatch, tmp_path):
    helpers = importlib.import_module("bridge.session_runtime_helpers")
    owner = r"D:\project\.venv\Scripts\python.exe"
    calls = []

    class Proc:
        pid = 7312
        stdout = None
        stderr = None

        def poll(self):
            return None

    class Subprocess:
        CREATE_NO_WINDOW = 0
        PIPE = object()

        @staticmethod
        def Popen(cmd, **kwargs):
            calls.append((list(cmd), dict(kwargs)))
            return Proc()

    class Facade:
        BASE_DIR = str(tmp_path)
        MONITOR_SCRIPT = str(tmp_path / "monitor.py")
        os = os
        subprocess = Subprocess

        @staticmethod
        def _spawn_command(worker, *args):
            assert worker == "--worker-monitor"
            return [owner, str(tmp_path / "monitor.py"), *args]

        @staticmethod
        def translate_string(_language, key, **kwargs):
            return key.format(**kwargs)

    class Bridge:
        _language = "en"

        def __init__(self):
            self._running_processes = {}

        def _cleanup_processes(self):
            return None

        def _set_status(self, value):
            raise AssertionError(value)

    monkeypatch.setenv("BIOAUTH_DESKTOP_EXECUTABLE", owner)
    monkeypatch.setattr(helpers, "_facade", lambda: Facade)
    bridge = Bridge()

    assert helpers.start_process(bridge, "monitor", [Facade.MONITOR_SCRIPT, "alice"], extra_env={"BIOAUTH_LIVE_SESSION_DIR": "live"}) is True

    cmd, kwargs = calls[0]
    assert cmd == [owner, str(tmp_path / "monitor.py"), "alice"]
    assert kwargs["env"]["BIOAUTH_DESKTOP_EXECUTABLE"] == owner
    assert kwargs["env"]["BIOAUTH_LIVE_SESSION_DIR"] == "live"
