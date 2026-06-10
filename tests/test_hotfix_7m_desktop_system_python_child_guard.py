from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_guard_blocks_system_python_desktop_child_of_project_venv(monkeypatch, tmp_path):
    guard = importlib.reload(importlib.import_module("bioauth_runtime.desktop_relaunch_guard"))
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(guard.os, "name", "nt", raising=False)
    monkeypatch.setattr(guard.os, "getppid", lambda: 20872)
    monkeypatch.setattr(guard.os, "getpid", lambda: 16352)
    monkeypatch.setattr(guard.sys, "executable", r"C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe")
    monkeypatch.setattr(guard.sys, "argv", [str(root / "desktop_app.py")])

    def process_info(pid):
        assert pid == 20872
        return {
            "ProcessId": 20872,
            "ExecutablePath": str(root / ".venv" / "Scripts" / "python.exe"),
            "CommandLine": f'"{root / ".venv" / "Scripts" / "python.exe"}" "{root / "desktop_app.py"}"',
        }

    result = guard.guard_desktop_system_python_child(project_root=str(root), process_info=process_info)

    assert result["blocked"] is True
    assert result["reason"] == "system_python_child_of_project_venv_desktop"


def test_guard_allows_project_venv_desktop_parent_process(monkeypatch, tmp_path):
    guard = importlib.reload(importlib.import_module("bioauth_runtime.desktop_relaunch_guard"))
    root = tmp_path / "project"
    root.mkdir()
    venv_python = str(root / ".venv" / "Scripts" / "python.exe")
    monkeypatch.setattr(guard.os, "name", "nt", raising=False)
    monkeypatch.setattr(guard.os, "getppid", lambda: 111)
    monkeypatch.setattr(guard.sys, "executable", venv_python)
    monkeypatch.setattr(guard.sys, "argv", [str(root / "desktop_app.py")])

    result = guard.guard_desktop_system_python_child(
        project_root=str(root),
        process_info=lambda _pid: {"ExecutablePath": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", "CommandLine": "powershell"},
    )

    assert result["blocked"] is False


def test_desktop_wrapper_runs_relaunch_guard_before_qt_impl_import():
    source = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    assert "guard_desktop_system_python_child" in source
    assert source.index("guard_desktop_system_python_child") < source.index("import_module(\"bioauth.app.desktop_app_impl\")")
    assert "subprocess.Popen" not in source
    assert "os.exec" not in source
    assert "os.spawn" not in source
    assert "runpy" not in source


def test_no_project_source_launches_desktop_app_internally():
    launch_tokens = ("subprocess.Popen", "subprocess.run", "os.system", "os.exec", "os.spawn", "QProcess", "multiprocessing")
    for path in [
        ROOT / "desktop_app.py",
        ROOT / "src" / "bioauth" / "app" / "desktop_app_impl.py",
        ROOT / "bridge" / "pyside_bootstrap.py",
    ]:
        source = path.read_text(encoding="utf-8")
        for token in launch_tokens:
            assert token not in source
