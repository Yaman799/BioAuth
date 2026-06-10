from __future__ import annotations

import ntpath
import os
import sys
from typing import Callable, List


def _console_python_for(executable: str, path_exists: Callable[[str], bool]) -> str:
    base = ntpath.basename(str(executable or "")).lower()
    if base == "pythonw.exe":
        candidate = ntpath.join(ntpath.dirname(executable), "python.exe")
        if path_exists(candidate):
            return candidate
    return executable


def worker_python_executable(path_exists: Callable[[str], bool]) -> str:
    executable = str(getattr(sys, "executable", "") or "")
    if getattr(sys, "frozen", False) or not executable:
        return executable or sys.executable
    owner_executable = str(os.environ.get("BIOAUTH_DESKTOP_EXECUTABLE") or "")
    if owner_executable:
        owner_console = _console_python_for(owner_executable, path_exists)
        if path_exists(owner_executable) or path_exists(owner_console):
            return owner_console
    return _console_python_for(executable, path_exists)


def spawn_command(worker: str, logger_script: str, monitor_script: str, path_exists: Callable[[str], bool], *args: str) -> List[str]:
    executable = worker_python_executable(path_exists)
    if getattr(sys, "frozen", False):
        return [executable, worker, *args]
    if worker == "--worker-logger":
        return [executable, logger_script, *args]
    if worker == "--worker-monitor":
        return [executable, monitor_script, *args]
    return [executable, *args]


def run_worker_if_requested(argv: list[str], logger_script: str, monitor_script: str, run_logger: Callable[[], int], run_monitor: Callable[[], int | None]) -> None:
    if len(argv) < 2:
        return
    worker = argv[1]
    if worker == "--worker-logger":
        sys.argv = [logger_script, *argv[2:]]
        raise SystemExit(run_logger())
    if worker == "--worker-monitor":
        sys.argv = [monitor_script, *argv[2:]]
        code = run_monitor()
        raise SystemExit(code if isinstance(code, int) else 0)
