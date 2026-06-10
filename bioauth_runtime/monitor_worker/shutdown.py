"""Monitor stop-signal helpers."""
from __future__ import annotations

import os
import time
from typing import Any, Dict

from control import should_stop, stop_control_status

_WORKER_STARTED_AT = time.time()
_ALLOWED_MONITOR_STOP_REASONS = {
    "user_stop",
    "app_shutdown",
    "supervisor_stop",
    "logger_failed_pair_stop",
    "test_stop",
}


def monitor_stop_control_status(
    control_name: str = "monitor",
    *,
    session_id: str | None = None,
    run_id: str | None = None,
    worker_started_at: float | None = None,
) -> Dict[str, Any]:
    """Return session-scoped monitor stop-control diagnostics."""
    return stop_control_status(
        str(control_name or "monitor"),
        worker_key=str(control_name or "monitor"),
        session_id=str(session_id if session_id is not None else os.environ.get("BIOAUTH_SESSION_ID", "")),
        run_id=str(run_id if run_id is not None else os.environ.get("BIOAUTH_RUN_ID", "")),
        worker_started_at=float(worker_started_at if worker_started_at is not None else _WORKER_STARTED_AT),
        allowed_reasons=_ALLOWED_MONITOR_STOP_REASONS,
    )


def should_stop_monitor(control_name: str = "monitor") -> bool:
    """Return True only for a valid current-session monitor stop marker."""
    status = monitor_stop_control_status(control_name)
    if bool(status.get("should_stop")):
        return True
    if not bool(status.get("control_file_seen")):
        try:
            return bool(should_stop(str(control_name or "monitor")))
        except Exception:
            return False
    return False
