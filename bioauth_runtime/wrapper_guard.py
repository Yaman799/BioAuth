"""Root wrapper re-entry guard for source launches.

This module has one job: prevent a root wrapper that is already active in a
parent process from relaunching the same wrapper in a child interpreter.  It is
intentionally small and does not own desktop instance or worker lifecycle.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

_PREFIX = "BIOAUTH_ROOT_WRAPPER"


def _env_key(wrapper_name: str, suffix: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(wrapper_name or "wrapper")).upper()
    return f"{_PREFIX}_{safe}_{suffix}"


def _pid_alive(pid: int) -> bool:
    try:
        pid = int(pid or 0)
    except Exception:
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    except Exception:
        return True


def _same_project(a: str, b: str) -> bool:
    if not a or not b:
        return True
    try:
        return str(Path(a).resolve()).casefold() == str(Path(b).resolve()).casefold()
    except Exception:
        return str(a).casefold() == str(b).casefold()


def enter_root_wrapper(wrapper_name: str, *, project_root: str | None = None, script_path: str | None = None) -> Dict[str, Any]:
    """Register this root wrapper process and block inherited self-relaunches."""
    root = str(Path(project_root or Path.cwd()).resolve())
    script = str(Path(script_path or (sys.argv[0] if sys.argv else wrapper_name)).resolve())
    current_exe = str(sys.executable or "")
    pid_key = _env_key(wrapper_name, "PID")
    exe_key = _env_key(wrapper_name, "EXE")
    script_key = _env_key(wrapper_name, "SCRIPT")
    root_key = _env_key(wrapper_name, "PROJECT_ROOT")

    owner_pid_raw = os.environ.get(pid_key, "")
    owner_pid = int(owner_pid_raw) if str(owner_pid_raw).isdigit() else 0
    owner_exe = str(os.environ.get(exe_key) or "")
    owner_script = str(os.environ.get(script_key) or "")
    owner_root = str(os.environ.get(root_key) or "")

    inherited_live_owner = owner_pid and owner_pid != os.getpid() and _pid_alive(owner_pid)
    same_scope = _same_project(owner_root, root) and _same_project(owner_script, script)
    if inherited_live_owner and same_scope:
        diag = {
            "ok": False,
            "wrapper_relaunch_blocked": True,
            "wrapper_name": str(wrapper_name),
            "reason": "current_venv_already_active",
            "owner_pid": owner_pid,
            "owner_executable": owner_exe,
            "current_executable": current_exe,
            "attempted_executable": current_exe,
            "project_root": root,
            "script_path": script,
            "current_pid": os.getpid(),
        }
        try:
            print("[BioAuth] wrapper_relaunch_blocked " + json.dumps(diag, ensure_ascii=False, default=str), file=sys.stderr)
        except Exception:
            pass
        return diag

    now = time.time()
    os.environ[pid_key] = str(os.getpid())
    os.environ[exe_key] = current_exe
    os.environ[script_key] = script
    os.environ[root_key] = root
    if str(wrapper_name or "").strip().lower() == "desktop_app" and current_exe:
        os.environ["BIOAUTH_DESKTOP_EXECUTABLE"] = current_exe
    return {
        "ok": True,
        "wrapper_relaunch_blocked": False,
        "wrapper_name": str(wrapper_name),
        "pid": os.getpid(),
        "current_executable": current_exe,
        "script_path": script,
        "project_root": root,
        "entered_at": now,
    }


__all__ = ["enter_root_wrapper"]
