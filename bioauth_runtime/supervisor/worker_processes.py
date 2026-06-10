"""Narrow worker process operations for commercial runtime supervision."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)


def _legacy():
    from bridge import session_runtime_helpers
    return session_runtime_helpers


def start_worker(bridge: Any, key: str, args: List[str], *, extra_env: Optional[Dict[str, str]] = None) -> bool:
    """Start one worker through the existing process registry."""
    if not _desktop_owner_allows_spawn(bridge):
        _record_duplicate_diag(bridge, {"reason": "not_active_desktop_instance", "key": str(key)})
        return False
    duplicate = find_duplicate_worker_processes(bridge, key, args, extra_env=extra_env)
    if duplicate.get("current_session_exists"):
        _record_duplicate_diag(bridge, duplicate)
        return False
    stale_pids = list(duplicate.get("stale_worker_pids") or [])
    if stale_pids:
        _cleanup_stale_duplicate_workers(stale_pids)
        duplicate["stale_worker_cleanup_pids"] = stale_pids
        _record_duplicate_diag(bridge, duplicate)
    _record_spawn_diag(bridge, key)
    return bool(_legacy().start_process(bridge, key, args, extra_env=extra_env))


def process_alive(bridge: Any, key: str) -> bool:
    """Return True when a registered worker handle is still running."""
    try:
        proc = (getattr(bridge, "_running_processes", {}) or {}).get(str(key))
        return proc is not None and proc.poll() is None
    except Exception:
        return False


def stop_worker(bridge: Any, key: str, *, stop_name: str = "", wait_timeout: float = 1.0, reason: str = "supervisor_stop") -> Dict[str, Any]:
    """Request worker stop and terminate the registered process if needed."""
    facade = _legacy()._facade()
    name = str(stop_name or key)
    try:
        if name:
            state = {}
            try:
                state = facade.read_session_state(default={})
            except Exception:
                state = {}
            state = state if isinstance(state, dict) else {}
            facade.request_stop(
                name,
                worker_key=name,
                user_id=str(state.get("user_id") or state.get("user") or ""),
                session_id=str(state.get("session_id") or ""),
                run_id=str(state.get("run_id") or ""),
                reason=str(reason or "supervisor_stop"),
                source_module=__name__,
                source_function="stop_worker",
            )
    except Exception:
        LOGGER.debug("Failed requesting worker stop", exc_info=True)
    try:
        return dict(
            _legacy()._terminate_process_key(
                bridge,
                str(key),
                graceful_timeout=max(0.1, float(wait_timeout)),
                force_timeout=0.5,
                terminate_first=False,
            )
            or {}
        )
    except Exception as exc:
        LOGGER.debug("Failed stopping worker", exc_info=True)
        return {"ok": False, "key": str(key), "error": str(exc)}


def stop_pair(bridge: Any, *, reason: str = "supervisor_stop", wait_timeout: float = 1.0) -> Dict[str, Any]:
    """Stop monitor and logger as one supervised commercial pair."""
    logger_key = bridge._logger_process_key() if getattr(bridge, "_current_user", None) else ""
    logger_stop = bridge._logger_key() if getattr(bridge, "_current_user", None) else ""
    monitor = stop_worker(bridge, "monitor", stop_name="monitor", wait_timeout=wait_timeout, reason=reason)
    logger = stop_worker(bridge, logger_key, stop_name=logger_stop, wait_timeout=wait_timeout, reason=reason) if logger_key else {}
    _forget_completed_workers(bridge, ["monitor", logger_key])
    return {"reason": str(reason or "supervisor_stop"), "monitor": monitor, "logger": logger}


def find_duplicate_worker_processes(bridge: Any, key: str, args: List[str], *, extra_env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Best-effort duplicate worker scan for the same project/user."""
    processes = getattr(bridge, "_running_processes", {}) if hasattr(bridge, "_running_processes") else {}
    proc = processes.get(str(key)) if isinstance(processes, dict) else None
    if proc is not None:
        try:
            if proc.poll() is None:
                return {"duplicate_worker_detected": True, "current_session_exists": True, "duplicate_worker_pids": [int(getattr(proc, "pid", 0) or 0)], "key": str(key)}
        except Exception:
            pass
    script = os.path.basename(str(args[0] if args else key)).lower()
    user = str(args[1] if len(args or []) > 1 else "").lower()
    project = str(getattr(_legacy()._facade(), "BASE_DIR", os.getcwd()) or os.getcwd()).lower()
    matches: List[int] = []
    for item in _iter_processes():
        pid = int(item.get("pid") or 0)
        if pid <= 0 or pid == os.getpid():
            continue
        cmd = str(item.get("command_line") or "").lower()
        if project and project not in cmd:
            continue
        if script and script not in cmd:
            continue
        if user and user not in cmd:
            continue
        matches.append(pid)
    return {"duplicate_worker_detected": bool(matches), "current_session_exists": False, "stale_worker_pids": matches, "duplicate_worker_pids": matches, "key": str(key)}


def _iter_processes() -> List[Dict[str, Any]]:
    if os.name != "nt":
        out = []
        proc_dir = "/proc"
        try:
            for name in os.listdir(proc_dir):
                if not name.isdigit():
                    continue
                path = os.path.join(proc_dir, name, "cmdline")
                try:
                    raw = open(path, "rb").read().replace(b"\x00", b" ").strip()
                    out.append({"pid": int(name), "command_line": raw.decode("utf-8", "replace")})
                except Exception:
                    continue
        except Exception:
            pass
        return out
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | ForEach-Object { Write-Output ($_.ProcessId.ToString() + '|' + $_.CommandLine) }",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = []
        for line in (completed.stdout or "").splitlines():
            pid, _, cmd = line.partition("|")
            if pid.strip().isdigit():
                out.append({"pid": int(pid.strip()), "command_line": cmd})
        return out
    except Exception:
        return []


def _cleanup_stale_duplicate_workers(pids: List[int]) -> None:
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0)
            else:
                os.kill(int(pid), 15)
        except Exception:
            LOGGER.debug("Failed cleanup for stale duplicate worker pid=%s", pid, exc_info=True)


def _desktop_owner_allows_spawn(bridge: Any) -> bool:
    try:
        from bioauth_runtime.desktop_instance import owns_desktop_instance
        return owns_desktop_instance(getattr(_legacy()._facade(), "BASE_DIR", ""))
    except Exception:
        LOGGER.debug("Desktop instance ownership check failed safely", exc_info=True)
        return True


def _expected_worker_executable() -> str:
    try:
        from worker_bootstrap import worker_python_executable
        return str(worker_python_executable(os.path.exists) or sys.executable or "")
    except Exception:
        return str(sys.executable or "")


def _record_spawn_diag(bridge: Any, key: str) -> None:
    expected = _expected_worker_executable()
    setattr(bridge, "_last_worker_spawn_executable", expected)
    setattr(bridge, "_expected_worker_executable", expected)
    try:
        state = _legacy()._facade().read_session_state(default={})
        if isinstance(state, dict):
            state.update({"worker_spawn_executable": expected, "expected_worker_executable": expected, "desktop_instance_pid": os.getpid()})
            _legacy()._facade().write_session_state(state)
    except Exception:
        pass


def _record_duplicate_diag(bridge: Any, diag: Dict[str, Any]) -> None:
    setattr(bridge, "_last_duplicate_worker_diagnostics", dict(diag or {}))
    try:
        state = _legacy()._facade().read_session_state(default={})
        if isinstance(state, dict):
            state.update({k: v for k, v in dict(diag or {}).items() if k in {"duplicate_worker_detected", "duplicate_worker_pids", "stale_worker_cleanup_pids"}})
            _legacy()._facade().write_session_state(state)
    except Exception:
        pass


def _forget_completed_workers(bridge: Any, keys: List[str]) -> None:
    """Remove stopped/dead process handles so cleanup logs do not spam."""
    processes = getattr(bridge, "_running_processes", None)
    if not isinstance(processes, dict):
        return
    for key in [str(k or "") for k in keys if str(k or "")]:
        proc = processes.get(key)
        if proc is None:
            continue
        try:
            alive = proc.poll() is None
        except Exception:
            alive = False
        if not alive:
            processes.pop(key, None)
