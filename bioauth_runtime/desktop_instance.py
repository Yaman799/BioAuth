"""Single desktop-instance ownership for one BioAuth control directory."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from paths import control_dir

_LOCK_NAME = "desktop_app.instance.lock"
_CURRENT: Dict[str, Any] = {}


def lock_path() -> Path:
    return Path(control_dir()) / _LOCK_NAME


def current_instance() -> Dict[str, Any]:
    return dict(_CURRENT)


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


def _read_lock(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return dict(data or {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _payload(project_root: str) -> Dict[str, Any]:
    now = time.time()
    return {
        "schema_version": 1,
        "instance_id": uuid.uuid4().hex,
        "pid": os.getpid(),
        "project_root": str(Path(project_root).resolve()),
        "control_dir": str(Path(control_dir()).resolve()),
        "executable_path": sys.executable or "",
        "command_line": " ".join([sys.executable or "python", *sys.argv]),
        "started_at": now,
        "started_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
    }


def acquire_desktop_instance(project_root: str) -> Dict[str, Any]:
    """Acquire the single desktop instance lock for this control directory."""
    global _CURRENT
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = _payload(project_root)
    encoded = json.dumps(current, ensure_ascii=False, indent=2).encode("utf-8")
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, encoded)
                try:
                    os.fsync(fd)
                except OSError:
                    pass
            finally:
                os.close(fd)
            _CURRENT = dict(current)
            os.environ["BIOAUTH_DESKTOP_INSTANCE_ID"] = str(current["instance_id"])
            os.environ["BIOAUTH_DESKTOP_INSTANCE_PID"] = str(current["pid"])
            os.environ["BIOAUTH_DESKTOP_EXECUTABLE"] = str(current.get("executable_path") or "")
            return {"ok": True, "path": str(path), "owner": dict(current), "duplicate_desktop_app_detected": False}
        except FileExistsError:
            owner = _read_lock(path)
            owner_pid = int(owner.get("pid") or 0) if owner else 0
            same_scope = str(owner.get("control_dir") or "") == str(current.get("control_dir") or "")
            if owner_pid and _pid_alive(owner_pid) and same_scope and owner_pid != os.getpid():
                return {
                    "ok": False,
                    "path": str(path),
                    "owner": owner,
                    "current": current,
                    "duplicate_desktop_app_detected": True,
                    "reason": "live_desktop_instance_exists",
                }
            try:
                path.unlink(missing_ok=True)
            except Exception as exc:
                return {"ok": False, "path": str(path), "owner": owner, "current": current, "reason": f"stale_lock_remove_failed:{exc}"}
        except OSError as exc:
            return {"ok": False, "path": str(path), "current": current, "reason": str(exc)}


def owns_desktop_instance(project_root: str | None = None) -> bool:
    """Return True when this process owns the active desktop lock."""
    path = lock_path()
    owner = _read_lock(path)
    if not owner:
        return False
    if int(owner.get("pid") or 0) != os.getpid():
        return False
    instance_id = str(owner.get("instance_id") or "")
    env_instance = str(os.environ.get("BIOAUTH_DESKTOP_INSTANCE_ID") or "")
    if env_instance and instance_id != env_instance:
        return False
    if project_root:
        try:
            if str(Path(owner.get("project_root") or "").resolve()) != str(Path(project_root).resolve()):
                return False
        except Exception:
            return False
    return True


def release_desktop_instance() -> None:
    """Release the lock if this process still owns it."""
    global _CURRENT
    path = lock_path()
    owner = _read_lock(path)
    try:
        if int(owner.get("pid") or 0) == os.getpid():
            path.unlink(missing_ok=True)
    except Exception:
        pass
    os.environ.pop("BIOAUTH_DESKTOP_INSTANCE_ID", None)
    os.environ.pop("BIOAUTH_DESKTOP_INSTANCE_PID", None)
    os.environ.pop("BIOAUTH_DESKTOP_EXECUTABLE", None)
    _CURRENT = {}
