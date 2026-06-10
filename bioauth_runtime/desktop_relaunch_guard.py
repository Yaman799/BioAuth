"""Fail-closed guard for Windows desktop wrapper self-relaunches."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict

_LOG_NAME = "bioauth_desktop_launch_diag.jsonl"


def _norm(value: Any) -> str:
    return str(value or "").replace("/", "\\").casefold()


def _mentions_desktop_app(command_line: str) -> bool:
    return "desktop_app.py" in _norm(command_line)


def _is_project_venv_python(executable: str, project_root: str) -> bool:
    expected = Path(project_root).resolve() / ".venv" / "Scripts"
    try:
        return str(Path(executable).resolve()).casefold().startswith(str(expected).casefold())
    except Exception:
        return _norm(str(expected)) in _norm(executable)


def _process_info_windows(pid: int) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    f"Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\" | "
                    "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | "
                    "ConvertTo-Json -Compress"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = (completed.stdout or "").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        return dict(data or {}) if isinstance(data, dict) else {}
    except Exception as exc:
        return {"query_error": str(exc)}


def _append_diag(project_root: str, payload: Dict[str, Any]) -> None:
    try:
        path = Path(project_root).resolve() / _LOG_NAME
        record = dict(payload)
        record.setdefault("timestamp", time.time())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _current_command_line() -> str:
    return " ".join([str(sys.executable or "python"), *[str(arg) for arg in sys.argv]])


def record_desktop_launch_path(
    *,
    project_root: str,
    launch_path: str,
    command: Any = "",
    selected_executable: Any = "",
    before_qt: bool = True,
) -> None:
    _append_diag(
        project_root,
        {
            "event": "desktop_launch_path",
            "launch_path": str(launch_path or ""),
            "command": command,
            "selected_executable": str(selected_executable or ""),
            "before_qt": bool(before_qt),
            "pid": os.getpid(),
            "current_executable": str(sys.executable or ""),
            "current_command_line": _current_command_line(),
        },
    )


def guard_desktop_system_python_child(
    *,
    project_root: str,
    process_info: Callable[[int], Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Exit a system-Python desktop child spawned below the project venv wrapper."""
    root = str(Path(project_root).resolve())
    current_exe = str(sys.executable or "")
    current_cmd = _current_command_line()
    parent_pid = os.getppid() if hasattr(os, "getppid") else 0
    query = process_info or (_process_info_windows if os.name == "nt" else (lambda _pid: {}))
    parent = query(parent_pid) if parent_pid else {}
    parent_exe = str(parent.get("ExecutablePath") or parent.get("executable_path") or "")
    parent_cmd = str(parent.get("CommandLine") or parent.get("command_line") or "")

    current_is_desktop = _mentions_desktop_app(current_cmd)
    parent_is_desktop = _mentions_desktop_app(parent_cmd)
    current_is_project_venv = _is_project_venv_python(current_exe, root)
    parent_is_project_venv = _is_project_venv_python(parent_exe, root)
    block = (
        os.name == "nt"
        and current_is_desktop
        and parent_is_desktop
        and parent_is_project_venv
        and not current_is_project_venv
    )
    diag = {
        "event": "desktop_launch_guard",
        "blocked": bool(block),
        "reason": "system_python_child_of_project_venv_desktop" if block else "allowed",
        "pid": os.getpid(),
        "parent_pid": parent_pid,
        "current_executable": current_exe,
        "current_command_line": current_cmd,
        "parent_executable": parent_exe,
        "parent_command_line": parent_cmd,
        "project_root": root,
    }
    _append_diag(root, diag)
    if block:
        try:
            print("[BioAuth] desktop_relaunch_blocked " + json.dumps(diag, ensure_ascii=False, default=str), file=sys.stderr)
        except Exception:
            pass
    return diag


__all__ = ["guard_desktop_system_python_child", "record_desktop_launch_path"]
