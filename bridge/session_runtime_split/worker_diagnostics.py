"""Extracted implementation section for `bridge/session_runtime_helpers.py`."""
from __future__ import annotations
import json
import logging
import os
import re
import signal
import threading
import time
from collections import deque
from importlib import import_module
from typing import Any, Dict, List, Optional
from release_runtime import startup_protected_session_decision, write_release_runtime_event

def _record_worker_start(self, key: str, *, cmd: List[str], args: List[str], pid: int = 0) -> None:
    cleaned = getattr(self, "_completed_worker_cleanup_keys", None)
    if isinstance(cleaned, set):
        cleaned.discard(str(key))
    diag = _ensure_worker_diag(self, key)
    diag.update({
        "key": str(key),
        "cmd": [str(part) for part in (cmd or [])],
        "script": str(args[0]) if args else str(key),
        "pid": int(pid or 0),
        "started_at": time.time(),
        "exit_code": None,
        "completed_at": None,
        "reason": "running",
    })
    diag["stdout_tail"].clear()
    diag["stderr_tail"].clear()

def record_completed_process(self, key: str, proc: Any, *, reason: str = "completed") -> Dict[str, Any]:
    diag = _ensure_worker_diag(self, key)
    exit_code = None
    try:
        exit_code = proc.poll() if proc is not None else None
    except (AttributeError, OSError):
        LOGGER.debug("Worker %s poll failed while recording completion", key, exc_info=True)
        exit_code = None
    diag.update({"key": str(key), "exit_code": exit_code, "completed_at": time.time(), "reason": str(reason or "completed")})
    return worker_diagnostics_snapshot(self, key)

def worker_diagnostics_snapshot(self, key: str) -> Dict[str, Any]:
    return _user_runtime().worker_diagnostics_snapshot(self, key)

def worker_failure_detail(self, key: str, *, fallback: str) -> tuple[str, Dict[str, Any]]:
    return _user_runtime().worker_failure_detail(self, key, fallback=fallback)

def start_process(self, key: str, args: List[str], extra_env: Optional[Dict[str, str]] = None) -> bool:
    facade = _facade()
    self._last_process_start_error = ""
    debug = getattr(self, "_debug_trace", None)
    try:
        self._cleanup_processes()
    except Exception:
        LOGGER.debug("Failed cleanup before worker launch", exc_info=True)
    proc = self._running_processes.get(key)
    if proc is not None and proc.poll() is None:
        if callable(debug):
            debug("process", "Launch skipped because process is already running", payload={"key": key, "args": list(args or [])}, level="warn")
        return False
    if args and facade.os.path.basename(args[0]) == "logger.py":
        cmd = facade._spawn_command("--worker-logger", *args[1:])
    elif args and facade.os.path.basename(args[0]) == "monitor.py":
        cmd = facade._spawn_command("--worker-monitor", *args[1:])
    else:
        cmd = [facade.sys.executable] + args
    creationflags = getattr(facade.subprocess, "CREATE_NO_WINDOW", 0) if facade.os.name == "nt" else 0
    env = facade.os.environ.copy()
    if cmd:
        env.setdefault("BIOAUTH_DESKTOP_EXECUTABLE", str(cmd[0] or ""))
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items() if v is not None})
    if callable(debug):
        debug("process", "Starting worker process", payload={"key": key, "cmd": list(cmd or []), "extra_env": dict(extra_env or {})})
    try:
        popen_kwargs = {"cwd": facade.BASE_DIR, "creationflags": creationflags, "env": env}
        try:
            popen_kwargs.update({
                "stdout": facade.subprocess.PIPE,
                "stderr": facade.subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 1,
            })
        except AttributeError:
            pass
        proc = facade.subprocess.Popen(cmd, **popen_kwargs)
        self._running_processes[key] = proc
        _record_worker_start(self, key, cmd=cmd, args=args, pid=int(getattr(proc, "pid", 0) or 0))
        _start_worker_output_reader(self, key, getattr(proc, "stdout", None), "stdout")
        _start_worker_output_reader(self, key, getattr(proc, "stderr", None), "stderr")
        if callable(debug):
            debug("process", "Worker process spawned", payload={"key": key, "pid": int(getattr(proc, "pid", 0) or 0)})
    except (OSError, TypeError, ValueError) as exc:
        LOGGER.exception("Failed starting process %s", key)
        if callable(debug):
            debug("process", "Worker process failed to start", payload={"key": key, "error": str(exc)}, level="error")
        self._last_process_start_error = str(exc)
        write_release_runtime_event("background_worker_start_failed", key=str(key), process=facade.os.path.basename(args[0]) if args else str(key), reason="start_failed", detail=str(exc))
        self._set_status(
            facade.translate_string(
                getattr(self, "_language", "en"),
                "process_start_failed",
                process=facade.os.path.basename(args[0]),
                error=str(exc),
            ),
            "danger",
        )
        self._running_processes.pop(key, None)
        return False

    exit_code = proc.poll()
    if exit_code is not None:
        diag = record_completed_process(self, key, proc, reason="exited_immediately")
        if callable(debug):
            debug("process", "Worker process exited immediately", payload={"key": key, "exit_code": exit_code, "stderr_tail": list(diag.get("stderr_tail") or [])}, level="error")
        self._running_processes.pop(key, None)
        self._last_process_start_error = facade.translate_string(
            getattr(self, "_language", "en"),
            "process_exited_immediately",
            process=facade.os.path.basename(args[0]),
            code=exit_code,
        )
        self._set_status(self._last_process_start_error, "danger")
        write_release_runtime_event("background_worker_exited_immediately", key=str(key), process=facade.os.path.basename(args[0]) if args else str(key), reason="exited_immediately", exit_code=int(exit_code or 0))
        return False

    process_name = facade.os.path.basename(args[0]) if args else key
    if process_name == "logger.py" and len(args) >= 3:
        self._pending_logger_start = True
        self._pending_logger_user_id = args[1]
        self._pending_logger_session_kind = str(args[2] or "").strip().lower()
        self._pending_logger_process_key = key
        env_payload = dict(extra_env or {})
        self._pending_logger_session_id = str(env_payload.get("BIOAUTH_SESSION_ID") or "")
        self._pending_logger_run_id = str(env_payload.get("BIOAUTH_RUN_ID") or "")
        self._logger_start_deadline = facade.time.monotonic() + facade.LOGGER_START_GRACE_SEC
        self._logger_start_failed = False
        signal = getattr(self, "controlsChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        if callable(debug):
            debug("process", "Logger worker pending readiness", payload={"key": key, "user": args[1], "session_kind": self._pending_logger_session_kind})
        refresh_timer = getattr(self, "_update_refresh_timer", None)
        if callable(refresh_timer):
            refresh_timer(force=True)
        return True

    if callable(debug):
        debug("process", "Worker process launch completed", payload={"key": key, "args": list(args or [])})
    return True

def _hybrid_direct_test_report_path(self) -> str:
    facade = _facade()
    try:
        from paths import evidence_dir
        base = facade.os.path.join(evidence_dir(), "hybrid_direct_test")
    except Exception:
        base = facade.os.path.join(facade.BASE_DIR, "reports", "hybrid_direct_test")
    facade.os.makedirs(base, exist_ok=True)
    return facade.os.path.join(base, f"hybrid_direct_test_report_{_current_safe_user(self)}.json")

def _hybrid_direct_test_process_key(self) -> str:
    return f"hybrid_direct_test_monitor_user_{_current_safe_user(self)}"

def _hybrid_direct_replay_sessions_root() -> str:
    try:
        from paths import sessions_dir

        return str(sessions_dir())
    except Exception:
        try:
            from hybrid_candidates.replay_loader import resolve_replay_sessions_root

            return str(resolve_replay_sessions_root())
        except Exception:
            return ""

def hybrid_direct_test_blockers(self) -> List[str]:
    """Hybrid Direct Test is removed from the commercial flow.

    Keep a legacy blocker code so old UI/tests can query the slot safely, but
    never allow this feature to start capture/monitor/replay work in product.
    """
    return ["hybrid_direct_removed_from_commercial_flow"]

def hybrid_direct_monitor_smoke_test_blockers(self) -> List[str]:
    blockers = list(hybrid_direct_test_blockers(self))
    if not _effective_production_ready(self):
        blockers.append("production_model_not_ready")
    return list(dict.fromkeys(blockers))

def can_run_hybrid_direct_test(self) -> bool:
    return False

def _hybrid_removed_from_commercial_flow_payload(self, *, report_path: Optional[str] = None) -> Dict[str, Any]:
    """Return a safe legacy Hybrid Direct payload after commercial removal.

    Hybrid Direct Test is no longer part of the commercial training, runtime,
    production approval, or device-control flow.  The legacy slot/report shape
    remains so older QML/tests/imports fail closed without starting workers.
    """
    if report_path is None:
        try:
            report_path = _hybrid_direct_test_report_path(self)
        except Exception:
            report_path = ""
    reason_codes = ["hybrid_direct_removed_from_commercial_flow", "hybrid_test_not_required"]
    return {
        "ok": False,
        "passed": False,
        "status": "removed",
        "mode": "commercial_removed",
        "source": "commercial_core_22a",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user": _current_safe_user(self),
        "profile": str((getattr(self, "_current_user", {}) or {}).get("user_id") or _current_safe_user(self)),
        "reason_code": "hybrid_direct_removed_from_commercial_flow",
        "reason_codes": reason_codes,
        "report_path": str(report_path or ""),
        "hybrid_removed_from_commercial_flow": True,
        "hybrid_required_for_training": False,
        "training_sample_source": "normal_enrollment_archives_only",
        "report_only": True,
        "can_influence_device": False,
        "production_promotion_allowed": False,
        "protected_sessions_unlock_allowed": False,
        "active_runtime_pointer_write_allowed": False,
        "monitor": {
            "runtime_mode": "commercial_removed",
            "source": "commercial_core_22a",
            "process_started": False,
        },
        "safety": {
            "device_influence_disabled": True,
            "face_confirmation_disabled": True,
            "training_gate_disabled": True,
            "protected_sessions_unlock_allowed": False,
            "production_promotion_allowed": False,
            "production_approval_allowed": False,
            "production_pointer_write_allowed": False,
            "active_runtime_pointer_write_allowed": False,
            "can_influence_device": False,
        },
    }
