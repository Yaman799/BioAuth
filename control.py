import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid

_SESSION_STATE_LOCK = threading.Lock()
_SESSION_STATE_CACHE = {"sig": None, "value": None}
_SESSION_STATE_DIAGNOSTICS = {"last_issue": None, "detail": "", "path": "", "timestamp": 0.0, "lock": {}}
LOGGER = logging.getLogger(__name__)


def _record_session_state_issue(issue: str, detail: str = "", *, lock: dict | None = None):
    _SESSION_STATE_DIAGNOSTICS["last_issue"] = str(issue or "unknown")
    _SESSION_STATE_DIAGNOSTICS["detail"] = str(detail or "")
    _SESSION_STATE_DIAGNOSTICS["path"] = SESSION_STATE_FILE
    _SESSION_STATE_DIAGNOSTICS["timestamp"] = time.time()
    _SESSION_STATE_DIAGNOSTICS["lock"] = dict(lock or {})
    if lock:
        LOGGER.warning("Session state recovery triggered (%s): %s | lock=%s", issue, detail, lock)
    else:
        LOGGER.warning("Session state recovery triggered (%s): %s", issue, detail)


def session_state_diagnostics() -> dict:
    out = dict(_SESSION_STATE_DIAGNOSTICS)
    out["lock"] = dict(out.get("lock") or {})
    return out


def _clear_session_state_issue() -> None:
    _SESSION_STATE_DIAGNOSTICS["last_issue"] = None
    _SESSION_STATE_DIAGNOSTICS["detail"] = ""
    _SESSION_STATE_DIAGNOSTICS["path"] = SESSION_STATE_FILE
    _SESSION_STATE_DIAGNOSTICS["timestamp"] = 0.0
    _SESSION_STATE_DIAGNOSTICS["lock"] = {}


def current_boot_time_epoch():
    """Best-effort system boot epoch used to detect stale session state after reboot."""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            uptime_ms = int(ctypes.windll.kernel32.GetTickCount64())
            return max(0.0, float(time.time()) - (uptime_ms / 1000.0))
    except Exception:
        pass

    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("btime "):
                    return float(line.split()[1])
    except Exception:
        pass

    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            uptime_sec = float((f.read().strip().split() or [""])[0])
        return max(0.0, float(time.time()) - uptime_sec)
    except Exception:
        pass

    if sys.platform == "darwin":
        try:
            output = subprocess.check_output(["sysctl", "-n", "kern.boottime"], text=True, stderr=subprocess.DEVNULL)
            match = re.search(r"sec\s*=\s*(\d+)", output)
            if match:
                return float(match.group(1))
        except Exception:
            pass

    return None


def current_boot_marker() -> str:
    """Stable per-boot marker suitable for session-state stale detection."""
    try:
        with open("/proc/sys/kernel/random/boot_id", "r", encoding="utf-8") as f:
            value = f.read().strip()
        if value:
            return value
    except Exception:
        pass

    boot_epoch = current_boot_time_epoch()
    if boot_epoch is None:
        return ""
    # Bucket to 5 seconds to avoid harmless sub-second jitter across reads.
    bucket = int(round(float(boot_epoch) / 5.0) * 5)
    return f"boot-{bucket}"

from paths import control_dir

CONTROL_DIR = control_dir()

# -------------------------
# Stop control system
# -------------------------


def _control_path(name: str) -> str:
    return os.path.join(CONTROL_DIR, f"{name}.json")




def _canonical_stop_reason(reason: str) -> str:
    value = str(reason or "").strip().lower()
    mapping = {
        "user_requested": "user_stop",
        "stop_requested": "user_stop",
        "protected_stop_requested": "user_stop",
        "session_stop_requested": "user_stop",
        "app_close": "app_shutdown",
        "shutdown": "app_shutdown",
        "logger_exited_after_ready": "logger_failed_pair_stop",
        "monitor_exited_after_ready": "monitor_failed_pair_stop",
    }
    return mapping.get(value, value or "supervisor_stop")

def _current_session_scope() -> dict:
    try:
        state = read_session_state(default={})
    except Exception:
        state = {}
    if not isinstance(state, dict):
        return {}
    return {
        "user_id": state.get("user_id") or state.get("user") or state.get("expected_user") or "",
        "session_id": state.get("session_id") or "",
        "run_id": state.get("run_id") or "",
        "session_kind": state.get("session_kind") or "",
    }


def request_stop(
    name: str,
    *,
    worker_key: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    reason: str = "supervisor_stop",
    source_module: str = "",
    source_function: str = "",
):
    """Create a session-scoped stop flag for a running module.

    Older call sites may still pass only ``name``.  When a protected session is
    active, this helper scopes the stop marker from session_state so new workers
    can ignore stale unscoped files left by older builds.
    """
    path = _control_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    now = time.time()
    scope = _current_session_scope()
    payload = {
        "stop": True,
        "ts": now,
        "timestamp": now,
        "created_at": now,
        "created_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "worker_key": str(worker_key or name or ""),
        "user_id": str(user_id if user_id is not None else scope.get("user_id") or ""),
        "session_id": str(session_id if session_id is not None else scope.get("session_id") or ""),
        "run_id": str(run_id if run_id is not None else scope.get("run_id") or ""),
        "session_kind": str(scope.get("session_kind") or ""),
        "reason": _canonical_stop_reason(reason),
        "source_module": str(source_module or "control"),
        "source_function": str(source_function or "request_stop"),
    }
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def clear_stop(name: str):
    """Remove stop flag."""
    path = _control_path(name)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def read_stop_control(name: str) -> dict:
    """Read a raw stop-control payload without deciding whether it is valid."""
    path = _control_path(name)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return dict(data or {}) if isinstance(data, dict) else {"malformed": True}
    except Exception as exc:
        return {"malformed": True, "error": str(exc)}


def stop_control_status(
    name: str,
    *,
    worker_key: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    worker_started_at: float | None = None,
    allowed_reasons: set[str] | tuple[str, ...] | list[str] | None = None,
) -> dict:
    """Return a scoped stop-control decision and diagnostics for a worker."""
    path = _control_path(name)
    data = read_stop_control(name)
    exists = bool(data) and os.path.exists(path)
    allowed = {str(r or "") for r in (allowed_reasons or []) if str(r or "")}
    status = {
        "control_file_seen": bool(exists),
        "control_file_valid": False,
        "control_file_path": path if exists else "",
        "control_file_reason": str(data.get("reason") or "") if isinstance(data, dict) else "",
        "control_file_source_module": str(data.get("source_module") or "") if isinstance(data, dict) else "",
        "control_file_source_function": str(data.get("source_function") or "") if isinstance(data, dict) else "",
        "control_file_session_id": str(data.get("session_id") or "") if isinstance(data, dict) else "",
        "control_file_run_id": str(data.get("run_id") or "") if isinstance(data, dict) else "",
        "control_file_worker_key": str(data.get("worker_key") or "") if isinstance(data, dict) else "",
        "control_file_timestamp": float(data.get("ts") or data.get("timestamp") or data.get("created_at") or 0.0) if isinstance(data, dict) else 0.0,
        "ignored_stale_control_file": False,
        "ignore_reason": "",
        "should_stop": False,
    }
    if not exists:
        return status
    if not isinstance(data, dict) or not bool(data.get("stop")):
        status["ignore_reason"] = "stop_flag_missing"
        return status

    expected_worker = str(worker_key or name or "")
    actual_worker = str(data.get("worker_key") or "")
    current_session = str(session_id or "")
    current_run = str(run_id or "")
    reason = str(data.get("reason") or "")

    # No session context means legacy behavior for non-protected/test flows.
    if not current_session and not current_run:
        if allowed and reason and reason not in allowed:
            status.update({"ignored_stale_control_file": True, "ignore_reason": "reason_not_allowed"})
            return status
        status.update({"control_file_valid": True, "should_stop": True})
        return status

    if not actual_worker or actual_worker != expected_worker:
        status.update({"ignored_stale_control_file": True, "ignore_reason": "worker_key_mismatch_or_missing"})
        return status
    if not status["control_file_session_id"] or status["control_file_session_id"] != current_session:
        status.update({"ignored_stale_control_file": True, "ignore_reason": "session_id_mismatch_or_missing"})
        return status
    if current_run and (not status["control_file_run_id"] or status["control_file_run_id"] != current_run):
        status.update({"ignored_stale_control_file": True, "ignore_reason": "run_id_mismatch_or_missing"})
        return status
    if worker_started_at and status["control_file_timestamp"] and status["control_file_timestamp"] < float(worker_started_at):
        status.update({"ignored_stale_control_file": True, "ignore_reason": "control_file_older_than_worker"})
        return status
    if allowed and reason not in allowed:
        status.update({"ignored_stale_control_file": True, "ignore_reason": "reason_not_allowed"})
        return status
    status.update({"control_file_valid": True, "should_stop": True})
    return status


def should_stop_for_worker(name: str, **kwargs) -> bool:
    return bool(stop_control_status(name, **kwargs).get("should_stop"))


def should_stop(name: str) -> bool:
    """Legacy stop check.  Session-aware workers use should_stop_for_worker."""
    path = _control_path(name)
    if not os.path.exists(path):
        return False
    try:
        data = read_stop_control(name)
        return bool(data.get("stop", False))
    except Exception:
        return True




# -------------------------
# Worker heartbeat files
# -------------------------

def _worker_heartbeat_dir() -> str:
    path = os.path.join(CONTROL_DIR, "worker_heartbeats")
    os.makedirs(path, exist_ok=True)
    return path

def _safe_worker_kind(kind: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(kind or "worker")).strip("._-")
    return value or "worker"

def worker_heartbeat_path(kind: str) -> str:
    return os.path.join(_worker_heartbeat_dir(), f"{_safe_worker_kind(kind)}_heartbeat.json")

def write_worker_heartbeat(kind: str, data: dict) -> bool:
    """Atomically write a worker-owned heartbeat file.

    Commercial-Core-22M keeps session_state.json coordinator-owned. Logger and
    monitor workers publish liveness/runtime facts here; the bridge merges them
    into session_state. These payloads are intentionally small, copy-safe JSON.

    Windows-safe: on PermissionError (winerror 5/32/33) during os.replace,
    retries up to 3 times with 25ms backoff before giving up.  A single failed
    heartbeat write does not stop the worker — the caller receives False and
    the worker continues its loop.
    """
    if not isinstance(data, dict):
        data = {}
    payload = dict(data)
    payload.setdefault("worker_kind", _safe_worker_kind(kind))
    payload.setdefault("heartbeat_at", time.time())
    path = worker_heartbeat_path(kind)
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        # Retry os.replace on Windows transient file-in-use errors.
        _delay = 0.025
        for _attempt in range(3):
            try:
                os.replace(tmp, path)
                tmp = ""
                return True
            except PermissionError as _exc:
                _winerr = getattr(_exc, "winerror", None)
                if _winerr not in {5, 32, 33} or _attempt >= 2:
                    raise
                time.sleep(_delay)
                _delay *= 2
        return True  # reached only if loop exits without raise
    except Exception as exc:
        LOGGER.warning("Failed writing %s worker heartbeat: %s", kind, exc)
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False

def read_worker_heartbeat(kind: str, default=None):
    path = worker_heartbeat_path(kind)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else ({} if default is None else default)
    except Exception:
        return {} if default is None else default

def clear_worker_heartbeat(kind: str | None = None) -> None:
    try:
        if kind:
            paths = [worker_heartbeat_path(kind)]
        else:
            directory = _worker_heartbeat_dir()
            paths = [os.path.join(directory, name) for name in os.listdir(directory) if name.endswith("_heartbeat.json")]
        for path in paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
    except Exception:
        pass

# -------------------------
# Session state system
# (for dashboard ↔ logger ↔ monitor sync)
# -------------------------

SESSION_STATE_FILE = os.path.join(CONTROL_DIR, "session_state.json")
SESSION_STATE_LOCK_TIMEOUT_SEC = 1.5
SESSION_STATE_REPLACE_ATTEMPTS = 8
SESSION_STATE_READ_ATTEMPTS = 4
SESSION_STATE_LOCK_STALE_SEC = 30.0
SESSION_STATE_TEMP_STALE_SEC = 600.0
# Startup-only recovery for a live-but-stale BioAuth owner.  This handles the
# Windows case where an old python/BioAuth process remains alive while holding
# session_state.json.lock for minutes, blocking every new protected session.
SESSION_STATE_LIVE_STALE_OWNER_SEC = 60.0
SESSION_STATE_LIVE_STALE_TERMINATE_TIMEOUT_SEC = 2.0


class SessionStateWriteError(RuntimeError):
    """Controlled safe failure for session_state persistence errors."""


def _session_state_lock_file() -> str:
    return f"{SESSION_STATE_FILE}.lock"


def _session_state_tmp_pattern() -> re.Pattern[str]:
    base = re.escape(os.path.basename(SESSION_STATE_FILE))
    return re.compile(rf"^{base}\.\d+\.\d+\.[0-9a-f]{{32}}\.tmp$")


def _safe_pid_running(pid: int) -> bool:
    """Return whether a PID currently exists.

    This is intentionally only a liveness probe.  It does *not* prove that the
    process is the same process that originally created a BioAuth lock because
    operating systems may reuse PIDs.  Session-state lock ownership must be
    verified with ``_session_lock_owner_is_alive`` below, which also checks the
    owner's recorded process creation time when available.
    """
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError, OverflowError):
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
        # On platforms where probing is unavailable, avoid deleting the lock as live.
        return True


def _process_created_at_for_pid(pid: int) -> float:
    """Best-effort process birth timestamp for PID-reuse-safe lock checks."""
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if pid <= 0:
        return 0.0
    try:
        import psutil  # type: ignore

        return float(psutil.Process(pid).create_time())
    except Exception:
        pass
    if os.name != "nt":
        try:
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
                fields = handle.read().split()
            if len(fields) >= 22:
                start_ticks = float(fields[21])
                ticks_per_second = float(os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK")))
                boot_epoch = current_boot_time_epoch()
                if boot_epoch is not None and ticks_per_second > 0:
                    return float(boot_epoch) + (start_ticks / ticks_per_second)
        except Exception:
            pass
        return 0.0
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$p=Get-CimInstance Win32_Process -Filter 'ProcessId = %d'; "
                    "if ($p) { "
                    "$dt=[Management.ManagementDateTimeConverter]::ToDateTime($p.CreationDate); "
                    "[Console]::Out.WriteLine(([DateTimeOffset]$dt).ToUnixTimeSeconds()) "
                    "}"
                ) % pid,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = (completed.stdout or "").strip().splitlines()
        return float(text[-1]) if text else 0.0
    except Exception:
        return 0.0


def _current_process_created_at() -> float:
    value = _process_created_at_for_pid(os.getpid())
    return value if value > 0 else time.time()


def _timestamps_match(expected: float, actual: float, *, tolerance_sec: float = 2.0) -> bool:
    try:
        expected_f = float(expected or 0.0)
        actual_f = float(actual or 0.0)
    except (TypeError, ValueError, OverflowError):
        return False
    if expected_f <= 0.0 or actual_f <= 0.0:
        return False
    return abs(expected_f - actual_f) <= max(0.1, float(tolerance_sec))


def _session_lock_expected_process_created_at(owner: dict) -> float:
    """Return the process-birth timestamp recorded in a lock payload.

    New Phase-0 locks write ``process_created_at``.  Older locks only have
    ``created_at`` which represented the lock acquisition time, so it must not
    be treated as a reliable process identity value.
    """
    if not isinstance(owner, dict):
        return 0.0
    for key in ("process_created_at", "process_create_time", "process_birth_time"):
        try:
            value = float(owner.get(key) or 0.0)
        except (TypeError, ValueError, OverflowError):
            value = 0.0
        if value > 0.0:
            return value
    return 0.0


def _session_lock_owner_is_alive(owner: dict, *, details: dict | None = None) -> bool:
    """Return True only when the lock owner is still the same process.

    PID-only checks caused false live-lock decisions after PID reuse.  This
    function keeps legacy locks safe while making new locks PID-reuse-safe:
    - new locks: PID must be alive and process creation time must match;
    - legacy locks: PID must be alive and, when process details are available,
      the process must look like BioAuth rather than an unrelated reused PID.
    """
    owner = owner if isinstance(owner, dict) else {}
    try:
        pid = int(owner.get("pid") or 0)
    except (TypeError, ValueError, OverflowError):
        pid = 0
    if pid <= 0:
        return False
    if not _safe_pid_running(pid):
        return False
    expected_created_at = _session_lock_expected_process_created_at(owner)
    if expected_created_at > 0.0:
        actual_created_at = _process_created_at_for_pid(pid)
        if actual_created_at > 0.0:
            return _timestamps_match(expected_created_at, actual_created_at)
        # Could not verify the birth time on this platform. Preserve the lock
        # only if the process still appears to be a BioAuth process.
        details = details if isinstance(details, dict) else _process_details_for_pid(pid)
        return _is_bioauth_lock_owner_process(pid, details) or pid == os.getpid()
    # Legacy lock: no process birth timestamp exists. Avoid preserving a lock
    # if the PID now clearly belongs to a non-BioAuth process.
    if pid == os.getpid():
        return True
    details = details if isinstance(details, dict) else _process_details_for_pid(pid)
    if details.get("command_line") or details.get("executable"):
        return _is_bioauth_lock_owner_process(pid, details)
    # No reliable identity details were available; keep old conservative
    # behavior instead of deleting a possibly live lock.
    return True


def _current_project_root_markers() -> tuple[str, ...]:
    markers = []
    try:
        markers.append(os.path.abspath(os.getcwd()).lower())
    except Exception:
        pass
    try:
        markers.append(os.path.abspath(os.path.dirname(__file__)).lower())
    except Exception:
        pass
    # Deduplicate while preserving order.
    out = []
    for marker in markers:
        if marker and marker not in out:
            out.append(marker)
    return tuple(out)


def _process_details_for_pid(pid: int) -> dict:
    """Best-effort, copy-safe details for a process that owns session_state.lock."""
    pid = int(pid or 0)
    details = {
        "pid": pid,
        "alive": bool(pid and _safe_pid_running(pid)),
        "command_line": "",
        "executable": "",
        "source": "",
        "created_at": 0.0,
    }
    if pid <= 0 or not details["alive"]:
        return details
    if pid == os.getpid():
        details.update({
            "command_line": " ".join([sys.executable or "python", *sys.argv]),
            "executable": sys.executable or "",
            "source": "current_process",
            "created_at": _current_process_created_at(),
        })
        return details
    if os.name != "nt":
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                raw = handle.read().replace(b"\x00", b" ").strip()
            details["command_line"] = raw.decode("utf-8", "replace")
            details["source"] = "procfs"
        except Exception:
            pass
        try:
            details["executable"] = os.readlink(f"/proc/{pid}/exe")
        except Exception:
            pass
        details["created_at"] = _process_created_at_for_pid(pid)
        return details
    # Windows: use PowerShell CIM when available.  Keep the command short and
    # non-fatal; diagnostics must never block startup for long.
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$p=Get-CimInstance Win32_Process -Filter 'ProcessId = %d'; "
                    "if ($p) { "
                    "$dt=[Management.ManagementDateTimeConverter]::ToDateTime($p.CreationDate); "
                    "[Console]::Out.WriteLine('ExecutablePath=' + $p.ExecutablePath); "
                    "[Console]::Out.WriteLine('CommandLine=' + $p.CommandLine); "
                    "[Console]::Out.WriteLine('CreatedAt=' + ([DateTimeOffset]$dt).ToUnixTimeSeconds()) "
                    "}"
                ) % pid,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for line in (completed.stdout or "").splitlines():
            if line.startswith("ExecutablePath="):
                details["executable"] = line.split("=", 1)[1].strip()
            elif line.startswith("CommandLine="):
                details["command_line"] = line.split("=", 1)[1].strip()
            elif line.startswith("CreatedAt="):
                try:
                    details["created_at"] = float(line.split("=", 1)[1].strip())
                except (TypeError, ValueError, OverflowError):
                    details["created_at"] = 0.0
        if details["command_line"] or details["executable"]:
            details["source"] = "powershell_cim"
    except Exception:
        pass
    return details


def _is_bioauth_lock_owner_process(pid: int, details: dict | None = None) -> bool:
    """Return True only for processes that are safe to treat as BioAuth-owned."""
    pid = int(pid or 0)
    if pid <= 0 or pid == os.getpid():
        return False
    details = details if isinstance(details, dict) else _process_details_for_pid(pid)
    haystack = " ".join([
        str(details.get("command_line") or ""),
        str(details.get("executable") or ""),
    ]).lower()
    if not haystack:
        return False
    bioauth_terms = (
        "bioauth",
        "desktop_app.py",
        "start_app.py",
        "start_app.pyw",
        "logger.py",
        "monitor.py",
        "bioauthdesktop",
        "bioauth_democlassicprotected",
    )
    if any(term in haystack for term in bioauth_terms):
        return True
    return any(marker and marker in haystack for marker in _current_project_root_markers())


def _terminate_process_for_stale_session_lock(pid: int, *, timeout_sec: float = SESSION_STATE_LIVE_STALE_TERMINATE_TIMEOUT_SEC) -> bool:
    """Terminate a known BioAuth stale lock owner and wait briefly for exit."""
    pid = int(pid or 0)
    if pid <= 0 or pid == os.getpid():
        return False
    if not _safe_pid_running(pid):
        return True
    deadline = time.monotonic() + max(0.1, float(timeout_sec))
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(1.0, float(timeout_sec)),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            import signal
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return True
    except Exception:
        try:
            os.kill(pid, 9 if os.name != "nt" else 1)
        except Exception:
            pass
    while time.monotonic() < deadline:
        if not _safe_pid_running(pid):
            return True
        time.sleep(0.05)
    return not _safe_pid_running(pid)


def _read_lock_owner(lock_path: str) -> dict:
    try:
        with open(lock_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _maybe_cleanup_stale_session_state_lock(lock_path: str) -> None:
    try:
        os.stat(lock_path)
    except OSError:
        return
    info = inspect_session_state_lock()
    owner_pid = int(info.get("owner_pid") or 0)
    owner_alive = bool(info.get("owner_alive"))
    age = float(info.get("age_sec") or 0.0)
    # If the recorded owner process is definitely gone, the lock is orphaned
    # even when it is only milliseconds old.  This is the recovery path needed
    # after logger.py crashes while holding the inter-process lock.
    if owner_pid and not owner_alive:
        try:
            os.remove(lock_path)
            LOGGER.warning("Removed orphaned session_state lock from dead owner: %s | %s", lock_path, _compact_lock_diag(info))
        except OSError:
            pass
        return
    if owner_pid and owner_alive:
        return
    if age < SESSION_STATE_LOCK_STALE_SEC:
        return
    try:
        os.remove(lock_path)
        LOGGER.warning("Removed stale session_state lock file: %s | %s", lock_path, _compact_lock_diag(info))
    except OSError:
        pass


def _cleanup_stale_session_state_temps() -> None:
    directory = os.path.dirname(SESSION_STATE_FILE) or "."
    pattern = _session_state_tmp_pattern()
    try:
        names = os.listdir(directory)
    except OSError:
        return
    now = time.time()
    for name in names:
        if not pattern.match(name):
            continue
        path = os.path.join(directory, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if (now - float(stat.st_mtime)) < SESSION_STATE_TEMP_STALE_SEC:
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def _remove_session_state_temp_files(*, max_age_sec: float = 0.0) -> int:
    """Remove session_state temp files and return how many were deleted.

    The runtime startup path calls this with ``max_age_sec=0`` because temp
    files are never authoritative.  The normal write path still uses the
    older stale-only cleanup to avoid unnecessary churn.
    """
    directory = os.path.dirname(SESSION_STATE_FILE) or "."
    pattern = _session_state_tmp_pattern()
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    now = time.time()
    removed = 0
    for name in names:
        if not pattern.match(name):
            continue
        path = os.path.join(directory, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if max_age_sec > 0 and (now - float(stat.st_mtime)) < float(max_age_sec):
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return removed


def inspect_session_state_lock() -> dict:
    """Return copy-safe diagnostics about the inter-process session_state lock."""
    lock_path = _session_state_lock_file()
    result = {
        "lock_path": lock_path,
        "exists": False,
        "owner_pid": 0,
        "owner_alive": False,
        "owner_thread_id": 0,
        "owner_created_at": 0.0,
        "current_pid": os.getpid(),
        "age_sec": 0.0,
        "mtime": 0.0,
    }
    try:
        stat = os.stat(lock_path)
    except OSError:
        return result
    result["exists"] = True
    result["mtime"] = float(stat.st_mtime)
    result["age_sec"] = max(0.0, time.time() - float(stat.st_mtime))
    owner = _read_lock_owner(lock_path)
    try:
        owner_pid = int(owner.get("pid") or 0)
    except (TypeError, ValueError):
        owner_pid = 0
    try:
        owner_thread_id = int(owner.get("thread_id") or 0)
    except (TypeError, ValueError):
        owner_thread_id = 0
    try:
        owner_created_at = float(owner.get("created_at") or 0.0)
    except (TypeError, ValueError):
        owner_created_at = 0.0
    result["owner_pid"] = owner_pid
    result["owner_alive"] = bool(owner_pid and _session_lock_owner_is_alive(owner))
    result["owner_thread_id"] = owner_thread_id
    result["owner_created_at"] = owner_created_at
    try:
        result["owner_process_created_at"] = float(owner.get("process_created_at") or 0.0)
    except (TypeError, ValueError):
        result["owner_process_created_at"] = 0.0
    return result


def _compact_lock_diag(info: dict | None = None) -> str:
    info = info if isinstance(info, dict) else inspect_session_state_lock()
    if not bool(info.get("exists")):
        return f"lock_path={info.get('lock_path')}; exists=False"
    return (
        f"lock_path={info.get('lock_path')}; owner_pid={int(info.get('owner_pid') or 0)}; "
        f"owner_alive={bool(info.get('owner_alive'))}; age_sec={float(info.get('age_sec') or 0.0):.3f}; "
        f"current_pid={int(info.get('current_pid') or os.getpid())}"
    )


def prepare_session_state_for_new_runtime(reason: str = "runtime_start", *, stale_after_sec: float = 5.0) -> dict:
    """Prepare shared session_state storage before starting logger/monitor.

    This is used by the bridge before spawning a new protected runtime.  It
    only removes a lock when the recorded owner is definitely gone or when the
    lock has no usable owner and is old enough for startup recovery.  Live locks
    are preserved and reported so Start Protection can fail cleanly instead of
    launching half of the runtime.
    """
    action = "none"
    lock_path = _session_state_lock_file()
    with _SESSION_STATE_LOCK:
        os.makedirs(os.path.dirname(SESSION_STATE_FILE) or ".", exist_ok=True)
        temp_removed = _remove_session_state_temp_files(max_age_sec=0.0)
        info = inspect_session_state_lock()
        if bool(info.get("exists")):
            owner_pid = int(info.get("owner_pid") or 0)
            owner_alive = bool(info.get("owner_alive"))
            age = float(info.get("age_sec") or 0.0)
            owner_payload = _read_lock_owner(lock_path)
            owner_details = {}
            owner_identity_mismatch = False
            owner_expected_created_at = _session_lock_expected_process_created_at(owner_payload)
            if owner_pid and bool(info.get("exists")) and owner_pid != os.getpid():
                if owner_expected_created_at > 0.0 and _safe_pid_running(owner_pid):
                    actual_created_at = _process_created_at_for_pid(owner_pid)
                    owner_identity_mismatch = bool(actual_created_at > 0.0 and not _timestamps_match(owner_expected_created_at, actual_created_at))
                elif owner_alive and owner_expected_created_at <= 0.0:
                    owner_details = _process_details_for_pid(owner_pid)
                    owner_identity_mismatch = bool(
                        (owner_details.get("command_line") or owner_details.get("executable"))
                        and not _is_bioauth_lock_owner_process(owner_pid, owner_details)
                    )
            removable = False
            remove_reason = ""
            if owner_identity_mismatch:
                removable = True
                remove_reason = "owner_identity_mismatch_or_pid_reused"
            if (not removable) and owner_pid and not owner_alive:
                removable = True
                remove_reason = "owner_not_running"
            elif (not removable) and not owner_pid and age >= max(0.0, float(stale_after_sec)):
                removable = True
                remove_reason = "owner_missing_stale"
            elif (not removable) and age >= max(float(stale_after_sec), SESSION_STATE_LOCK_STALE_SEC):
                removable = not owner_alive
                remove_reason = "startup_stale_owner_not_running" if removable else "owner_running"
            if (not removable) and owner_alive and age >= max(float(stale_after_sec), SESSION_STATE_LIVE_STALE_OWNER_SEC):
                owner_details = owner_details or _process_details_for_pid(owner_pid)
                if _is_bioauth_lock_owner_process(owner_pid, owner_details):
                    terminated = _terminate_process_for_stale_session_lock(owner_pid)
                    if terminated:
                        try:
                            os.remove(lock_path)
                        except FileNotFoundError:
                            pass
                        except OSError as exc:
                            _SESSION_STATE_CACHE["sig"] = None
                            _SESSION_STATE_CACHE["value"] = None
                            _record_session_state_issue("session_state_live_stale_lock_remove_failed", str(exc), lock=info)
                            return {
                                "ok": False,
                                "reason": "live_stale_lock_remove_failed",
                                "detail": str(exc),
                                "action": "terminated_live_stale_owner_remove_failed",
                                "temp_files_removed": temp_removed,
                                "owner_process": owner_details,
                                **info,
                            }
                        action = f"recovered_live_stale_owner:pid={owner_pid}"
                        _record_session_state_issue(
                            "session_state_live_stale_owner_recovered",
                            f"terminated BioAuth lock owner pid={owner_pid}; age={age:.3f}s; reason={reason}",
                            lock=info,
                        )
                        info = inspect_session_state_lock()
                    else:
                        _SESSION_STATE_CACHE["sig"] = None
                        _SESSION_STATE_CACHE["value"] = None
                        _record_session_state_issue(
                            "session_state_live_stale_owner_termination_failed",
                            f"owner_pid={owner_pid}; age={age:.3f}s; reason={reason}",
                            lock=info,
                        )
                        return {
                            "ok": False,
                            "reason": "live_stale_owner_termination_failed",
                            "detail": "session_state is locked by an old BioAuth process that could not be terminated",
                            "action": "preserved_live_stale_lock",
                            "temp_files_removed": temp_removed,
                            "owner_process": owner_details,
                            **info,
                        }
                else:
                    _SESSION_STATE_CACHE["sig"] = None
                    _SESSION_STATE_CACHE["value"] = None
                    _record_session_state_issue(
                        "session_state_locked_by_non_bioauth_process",
                        f"owner_pid={owner_pid}; age={age:.3f}s; reason={reason}",
                        lock=info,
                    )
                    return {
                        "ok": False,
                        "reason": "lock_owner_running_non_bioauth",
                        "detail": "session_state is locked by a running process that is not recognized as BioAuth",
                        "action": "preserved_non_bioauth_live_lock",
                        "temp_files_removed": temp_removed,
                        "owner_process": owner_details,
                        **info,
                    }
            if str(action).startswith("recovered_live_stale_owner"):
                # The live stale owner was terminated and the lock removed.  Do
                # not fall through to the old owner_alive branch from the
                # pre-recovery inspection snapshot.
                pass
            elif removable:
                try:
                    os.remove(lock_path)
                    action = f"removed_lock:{remove_reason}"
                    info = inspect_session_state_lock()
                except OSError as exc:
                    _SESSION_STATE_CACHE["sig"] = None
                    _SESSION_STATE_CACHE["value"] = None
                    _record_session_state_issue("session_state_prepare_failed", str(exc))
                    return {
                        "ok": False,
                        "reason": "lock_remove_failed",
                        "detail": str(exc),
                        "action": action,
                        "temp_files_removed": temp_removed,
                        **info,
                    }
            elif owner_alive:
                owner_details = _process_details_for_pid(owner_pid) if age >= max(float(stale_after_sec), 10.0) else {}
                _SESSION_STATE_CACHE["sig"] = None
                _SESSION_STATE_CACHE["value"] = None
                _record_session_state_issue("session_state_busy", f"owner_pid={owner_pid}; age={age:.3f}s; reason={reason}", lock=info)
                return {
                    "ok": False,
                    "reason": "lock_owner_running",
                    "detail": "session_state is currently owned by a running process",
                    "action": "preserved_live_lock",
                    "temp_files_removed": temp_removed,
                    "owner_process": owner_details,
                    **info,
                }
            else:
                _SESSION_STATE_CACHE["sig"] = None
                _SESSION_STATE_CACHE["value"] = None
                _record_session_state_issue("session_state_busy", f"age={age:.3f}s; reason={reason}")
                return {
                    "ok": False,
                    "reason": "lock_recent_or_unverified",
                    "detail": "session_state lock is recent or cannot be safely removed yet",
                    "action": "preserved_recent_lock",
                    "temp_files_removed": temp_removed,
                    **info,
                }
        _SESSION_STATE_CACHE["sig"] = None
        _SESSION_STATE_CACHE["value"] = None
        _clear_session_state_issue()
        return {
            "ok": True,
            "reason": "prepared",
            "detail": "",
            "action": action,
            "temp_files_removed": temp_removed,
            **inspect_session_state_lock(),
        }


def _acquire_session_state_file_lock(timeout_sec: float = SESSION_STATE_LOCK_TIMEOUT_SEC) -> str:
    lock_path = _session_state_lock_file()
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    deadline = time.monotonic() + max(0.05, float(timeout_sec))
    delay = 0.025
    now = time.time()
    owner = {
        "pid": os.getpid(),
        "thread_id": threading.get_ident(),
        # Backward-compatible lock acquisition timestamp.
        "created_at": now,
        "lock_created_at": now,
        # Phase-0 PID-reuse guard: this is the process birth timestamp.
        "process_created_at": _current_process_created_at(),
        "instance_id": uuid.uuid4().hex,
        "role": "session_state_writer",
        "lock_version": 2,
    }
    encoded_owner = json.dumps(owner, ensure_ascii=False, sort_keys=True).encode("utf-8")

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, encoded_owner)
                try:
                    os.fsync(fd)
                except OSError:
                    pass
            finally:
                os.close(fd)
            return lock_path
        except FileExistsError:
            _maybe_cleanup_stale_session_state_lock(lock_path)
        except OSError as exc:
            raise SessionStateWriteError(f"session_state lock create failed: {exc}") from exc

        if time.monotonic() >= deadline:
            info = inspect_session_state_lock()
            raise SessionStateWriteError(f"session_state lock acquisition timed out; {_compact_lock_diag(info)}")
        time.sleep(delay)
        delay = min(delay * 2.0, 0.2)


def _release_session_state_file_lock(lock_path: str) -> None:
    if not lock_path:
        return
    try:
        owner = _read_lock_owner(lock_path)
        if int(owner.get("pid") or 0) not in (0, os.getpid()):
            return
    except Exception:
        pass
    try:
        os.remove(lock_path)
    except FileNotFoundError:
        pass
    except OSError:
        LOGGER.warning("Failed releasing session_state lock file: %s", lock_path)


def _unique_session_state_tmp_path() -> str:
    directory = os.path.dirname(SESSION_STATE_FILE) or "."
    base = os.path.basename(SESSION_STATE_FILE)
    return os.path.join(directory, f"{base}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp")


def _is_transient_replace_error(exc: BaseException) -> bool:
    if not isinstance(exc, PermissionError):
        return False
    winerror = getattr(exc, "winerror", None)
    if winerror in {5, 32, 33}:
        return True
    return getattr(exc, "errno", None) in {13, 16, 17}


def _replace_with_retry(src: str, dst: str) -> None:
    delay = 0.025
    last_error = None
    for attempt in range(1, SESSION_STATE_REPLACE_ATTEMPTS + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            last_error = exc
            if not _is_transient_replace_error(exc) or attempt >= SESSION_STATE_REPLACE_ATTEMPTS:
                raise
            time.sleep(delay)
            delay = min(delay * 2.0, 0.2)
    if last_error is not None:
        raise last_error


def _stat_signature(path: str) -> tuple[int, int]:
    stat = os.stat(path)
    return (int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))), int(stat.st_size))


def _cache_session_state_payload(payload: dict) -> None:
    try:
        sig = _stat_signature(SESSION_STATE_FILE)
        out = dict(payload)
        out.pop("_integrity", None)
        _SESSION_STATE_CACHE["sig"] = sig
        _SESSION_STATE_CACHE["value"] = out
    except OSError:
        _SESSION_STATE_CACHE["sig"] = None
        _SESSION_STATE_CACHE["value"] = None


def write_session_state(data: dict, *, timeout_sec: float | None = None, diagnostic_context: str = "") -> bool:
    """
    Save shared system state with HMAC integrity.

    The session file is shared by the backend, logger.py and monitor.py.  The
    write path therefore uses both an in-process lock and an inter-process lock
    file, writes through a unique same-directory temp file, and retries
    transient Windows file-in-use failures during atomic replacement.
    """
    from security import sign_session_state_payload

    tmp = ""
    file_lock = ""
    with _SESSION_STATE_LOCK:
        try:
            os.makedirs(os.path.dirname(SESSION_STATE_FILE) or ".", exist_ok=True)
            _cleanup_stale_session_state_temps()
            file_lock = _acquire_session_state_file_lock(SESSION_STATE_LOCK_TIMEOUT_SEC if timeout_sec is None else float(timeout_sec))
            payload = dict(data) if isinstance(data, dict) else {}
            payload.pop("_integrity", None)
            payload["_integrity"] = sign_session_state_payload(payload)
            tmp = _unique_session_state_tmp_path()
            fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            fd_owned = fd
            fd = -1
            with os.fdopen(fd_owned, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            _replace_with_retry(tmp, SESSION_STATE_FILE)
            tmp = ""
            _cache_session_state_payload(payload)
            _clear_session_state_issue()
            return True
        except Exception as exc:
            _SESSION_STATE_CACHE["sig"] = None
            _SESSION_STATE_CACHE["value"] = None
            context_prefix = f"{diagnostic_context}: " if diagnostic_context else ""
            _record_session_state_issue(
                "session_state_write_failed",
                f"{context_prefix}{exc}",
                lock=inspect_session_state_lock(),
            )
            return False
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            _release_session_state_file_lock(file_lock)


def read_session_state(default=None):
    """
    Read shared state safely; reject tampered or unsigned payloads.

    Readers only inspect the final session_state.json target.  Brief retries
    avoid treating transient replacement/file-sharing races as permanent
    corruption, while persistent malformed or unsigned files are still surfaced
    through session_state_diagnostics().
    """
    from security import verify_session_state_payload

    if default is None:
        default = {}

    with _SESSION_STATE_LOCK:
        last_issue = ""
        last_detail = ""
        for attempt in range(1, SESSION_STATE_READ_ATTEMPTS + 1):
            if not os.path.exists(SESSION_STATE_FILE):
                _SESSION_STATE_CACHE["sig"] = None
                _SESSION_STATE_CACHE["value"] = None
                return default

            try:
                sig = _stat_signature(SESSION_STATE_FILE)
            except OSError as exc:
                _SESSION_STATE_CACHE["sig"] = None
                _SESSION_STATE_CACHE["value"] = None
                last_issue = "read_unavailable"
                last_detail = str(exc)
                if attempt < SESSION_STATE_READ_ATTEMPTS:
                    time.sleep(0.025 * attempt)
                    continue
                _record_session_state_issue(last_issue, last_detail)
                return default

            if _SESSION_STATE_CACHE.get("sig") == sig and isinstance(_SESSION_STATE_CACHE.get("value"), dict):
                return dict(_SESSION_STATE_CACHE["value"])

            try:
                with open(SESSION_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
                last_issue = "malformed_json"
                last_detail = str(exc)
                if attempt < SESSION_STATE_READ_ATTEMPTS:
                    time.sleep(0.025 * attempt)
                    continue
                _SESSION_STATE_CACHE["sig"] = None
                _SESSION_STATE_CACHE["value"] = None
                _record_session_state_issue(last_issue, last_detail)
                return default

            if not isinstance(data, dict):
                _SESSION_STATE_CACHE["sig"] = sig
                _SESSION_STATE_CACHE["value"] = None
                _record_session_state_issue("invalid_format", "session_state payload is not a JSON object")
                return default
            if "_integrity" not in data:
                _SESSION_STATE_CACHE["sig"] = sig
                _SESSION_STATE_CACHE["value"] = None
                _record_session_state_issue("unsigned_payload", "session_state payload is missing _integrity")
                return default
            if not verify_session_state_payload(data):
                _SESSION_STATE_CACHE["sig"] = sig
                _SESSION_STATE_CACHE["value"] = None
                _record_session_state_issue("integrity_failed", "session_state integrity verification failed")
                return default
            out = dict(data)
            out.pop("_integrity", None)
            _SESSION_STATE_CACHE["sig"] = sig
            _SESSION_STATE_CACHE["value"] = dict(out)
            _clear_session_state_issue()
            return out

        _SESSION_STATE_CACHE["sig"] = None
        _SESSION_STATE_CACHE["value"] = None
        _record_session_state_issue(last_issue or "read_failed", last_detail)
        return default


def quarantine_session_state(reason: str = "orphaned", *, timeout_sec: float | None = None) -> str:
    """Move session_state.json aside for diagnostics instead of deleting it.

    Returns the quarantine path when a state file was moved, otherwise an empty string.
    """
    safe_reason = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(reason or "orphaned"))[:48] or "orphaned"
    file_lock = ""
    with _SESSION_STATE_LOCK:
        if not os.path.exists(SESSION_STATE_FILE):
            _SESSION_STATE_CACHE["sig"] = None
            _SESSION_STATE_CACHE["value"] = None
            return ""
        quarantine_dir = os.path.join(CONTROL_DIR, "quarantine")
        os.makedirs(quarantine_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        target = os.path.join(quarantine_dir, f"session_state_{stamp}_{safe_reason}.json")
        suffix = 1
        while os.path.exists(target):
            target = os.path.join(quarantine_dir, f"session_state_{stamp}_{safe_reason}_{suffix}.json")
            suffix += 1
        try:
            file_lock = _acquire_session_state_file_lock(SESSION_STATE_LOCK_TIMEOUT_SEC if timeout_sec is None else float(timeout_sec))
            _replace_with_retry(SESSION_STATE_FILE, target)
        except OSError:
            return ""
        except SessionStateWriteError as exc:
            _record_session_state_issue("session_state_quarantine_failed", str(exc))
            return ""
        finally:
            _release_session_state_file_lock(file_lock)
        _SESSION_STATE_CACHE["sig"] = None
        _SESSION_STATE_CACHE["value"] = None
        _record_session_state_issue("quarantined", f"{reason}: {target}")
        return target


def clear_session_state():
    """
    Reset system state (use on new session start)
    """
    file_lock = ""
    with _SESSION_STATE_LOCK:
        try:
            if os.path.exists(SESSION_STATE_FILE):
                file_lock = _acquire_session_state_file_lock(timeout_sec=SESSION_STATE_LOCK_TIMEOUT_SEC)
                os.remove(SESSION_STATE_FILE)
        except Exception as exc:
            _SESSION_STATE_CACHE["sig"] = None
            _SESSION_STATE_CACHE["value"] = None
            _record_session_state_issue("session_state_clear_failed", str(exc), lock=inspect_session_state_lock())
            return False
        finally:
            _release_session_state_file_lock(file_lock)
        _SESSION_STATE_CACHE["sig"] = None
        _SESSION_STATE_CACHE["value"] = None
        _clear_session_state_issue()
        return True
