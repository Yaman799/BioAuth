"""Monitor-only heartbeat publisher with atomic writes and lock hardening."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Mapping

from control import worker_heartbeat_path

LOGGER = logging.getLogger(__name__)
_PERMISSION_WARN_INTERVAL = 5.0
_REPLACE_ATTEMPTS = 6
_last_permission_warning_at = 0.0
_HEARTBEAT_WRITE_ERROR_COUNT = 0
_HEARTBEAT_WRITE_LAST_ERROR = ""
_HEARTBEAT_WRITE_PERMISSION_DENIED = False
_HEARTBEAT_WRITE_DEGRADED = False


def write_monitor_heartbeat_payload(payload: Mapping[str, object] | None) -> bool:
    """Write monitor heartbeat atomically; retry WinError 5 without stopping runtime."""
    global _HEARTBEAT_WRITE_ERROR_COUNT, _HEARTBEAT_WRITE_LAST_ERROR, _HEARTBEAT_WRITE_PERMISSION_DENIED, _HEARTBEAT_WRITE_DEGRADED
    data = dict(payload or {})
    data.setdefault("worker_kind", "monitor")
    data.setdefault("heartbeat_at", time.time())
    data.update({
        "heartbeat_write_error_count": _HEARTBEAT_WRITE_ERROR_COUNT,
        "heartbeat_write_last_error": _HEARTBEAT_WRITE_LAST_ERROR,
        "heartbeat_write_permission_denied": bool(_HEARTBEAT_WRITE_PERMISSION_DENIED),
        "heartbeat_degraded": bool(_HEARTBEAT_WRITE_DEGRADED),
        "heartbeat_file_path": worker_heartbeat_path("monitor"),
    })
    path = Path(worker_heartbeat_path("monitor"))
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    data["heartbeat_temp_path"] = str(tmp)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)
        _HEARTBEAT_WRITE_LAST_ERROR = ""
        _HEARTBEAT_WRITE_PERMISSION_DENIED = False
        return True
    except PermissionError as exc:
        _HEARTBEAT_WRITE_ERROR_COUNT += 1
        _HEARTBEAT_WRITE_LAST_ERROR = str(exc)
        _HEARTBEAT_WRITE_PERMISSION_DENIED = True
        _HEARTBEAT_WRITE_DEGRADED = _HEARTBEAT_WRITE_ERROR_COUNT >= 3
        _warn_permission_error(exc, str(path))
        _safe_unlink(tmp)
        return False
    except Exception as exc:
        _HEARTBEAT_WRITE_ERROR_COUNT += 1
        _HEARTBEAT_WRITE_LAST_ERROR = str(exc)
        _HEARTBEAT_WRITE_DEGRADED = _HEARTBEAT_WRITE_ERROR_COUNT >= 3
        LOGGER.exception("Failed writing monitor heartbeat")
        _safe_unlink(tmp)
        return False


def clean_stale_monitor_temp_heartbeats() -> int:
    """Remove stale monitor heartbeat temp files only."""
    path = Path(worker_heartbeat_path("monitor"))
    path.parent.mkdir(parents=True, exist_ok=True)
    removed = 0
    for candidate in path.parent.glob(f"{path.name}.*.tmp"):
        if _safe_unlink(candidate):
            removed += 1
    return removed


def _replace_with_retry(tmp: Path, path: Path) -> None:
    delay = 0.025
    last_error: PermissionError | None = None
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(str(tmp), str(path))
            return
        except PermissionError as exc:
            last_error = exc
            if not _is_transient_permission_error(exc) or attempt >= _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2.0, 0.25)
    if last_error is not None:
        raise last_error


def _is_transient_permission_error(exc: PermissionError) -> bool:
    # On Windows WinError 5/32/33 are common when another app/worker briefly
    # has the heartbeat open.  In tests and some Python builds winerror/errno
    # may be absent, so any PermissionError is treated as retryable.
    return True


def _warn_permission_error(exc: PermissionError, path: str) -> None:
    global _last_permission_warning_at
    now = time.time()
    if now - _last_permission_warning_at < _PERMISSION_WARN_INTERVAL:
        return
    _last_permission_warning_at = now
    LOGGER.warning("Monitor heartbeat write was blocked by the OS; will retry: %s (%s)", path, exc)


def _safe_unlink(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
        return True
    except Exception:
        LOGGER.debug("Could not remove monitor heartbeat temp file %s", path, exc_info=True)
        return False
