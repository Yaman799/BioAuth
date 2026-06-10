from __future__ import annotations

import os
import sys
from typing import List

from paths import runtime_base_dir
from worker_bootstrap import (
    run_worker_if_requested as _shared_run_worker_if_requested,
    spawn_command as _shared_spawn_command,
    worker_python_executable as _shared_worker_python_executable,
)

BASE_DIR = runtime_base_dir()
LOGGER_SCRIPT = os.path.join(BASE_DIR, "logger.py")
MONITOR_SCRIPT = os.path.join(BASE_DIR, "monitor.py")


def _worker_python_executable() -> str:
    return _shared_worker_python_executable(os.path.exists)


def _spawn_command(worker: str, *args: str) -> List[str]:
    return _shared_spawn_command(worker, LOGGER_SCRIPT, MONITOR_SCRIPT, os.path.exists, *args)


def _run_worker_if_requested() -> None:
    """Dispatch worker subprocess entry points without importing workers during UI startup."""
    if len(sys.argv) < 2:
        return
    worker = sys.argv[1]
    if worker == "--worker-logger":
        from logger import run_logger

        return _shared_run_worker_if_requested(sys.argv, LOGGER_SCRIPT, MONITOR_SCRIPT, run_logger, lambda: 0)
    if worker == "--worker-monitor":
        from monitor import monitor

        return _shared_run_worker_if_requested(sys.argv, LOGGER_SCRIPT, MONITOR_SCRIPT, lambda: 0, monitor)
    return


__all__ = [
    "BASE_DIR",
    "LOGGER_SCRIPT",
    "MONITOR_SCRIPT",
    "_run_worker_if_requested",
    "_spawn_command",
    "_worker_python_executable",
]
