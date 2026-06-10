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

def run_hybrid_direct_monitor_smoke_test(self) -> Dict[str, Any]:
    report_path = _hybrid_direct_test_report_path(self)
    result = _hybrid_removed_from_commercial_flow_payload(self, report_path=report_path)
    setattr(self, "_latest_hybrid_direct_test_result", result)
    setattr(self, "_hybrid_direct_test_running", False)
    signal = getattr(self, "hybridDirectChanged", None)
    if signal is not None and hasattr(signal, "emit"):
        signal.emit()
    try:
        self._set_status("Hybrid Direct monitor smoke test is removed from the commercial flow.", "info")
    except Exception:
        pass
    return dict(result)

    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    blockers = hybrid_direct_monitor_smoke_test_blockers(self)
    report_path = _hybrid_direct_test_report_path(self)
    if blockers:
        result = _hybrid_direct_test_result_payload(self, passed=False, reason_codes=blockers, report_path=report_path)
        _write_backend_hybrid_direct_test_report(self, result, report_path)
        setattr(self, "_latest_hybrid_direct_test_result", result)
        signal = getattr(self, "hybridDirectChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        try:
            self._set_status(_hybrid_result_status_message(self, result), "warn")
        except Exception:
            pass
        return dict(result)
    setattr(self, "_hybrid_direct_test_running", True)
    signal = getattr(self, "hybridDirectChanged", None)
    controls = getattr(self, "controlsChanged", None)
    if signal is not None and hasattr(signal, "emit"):
        signal.emit()
    if controls is not None and hasattr(controls, "emit"):
        controls.emit()
    env = facade.os.environ.copy()
    env.update({
        "BIOAUTH_RUNTIME_MODE": HYBRID_DIRECT_TEST_SESSION_KIND,
        "BIOAUTH_HYBRID_TEST_ONLY": "1",
        "BIOAUTH_DEVICE_INFLUENCE_ALLOWED": "0",
        "BIOAUTH_HYBRID_TEST_REPORT_PATH": report_path,
    })
    command = facade._spawn_command("--worker-monitor", self._current_user["user_id"])
    if callable(debug):
        debug("runtime", "hybrid_direct_test_starting", payload={"command": list(command), "report_path": report_path, "process_key": _hybrid_direct_test_process_key(self)}, level="info")
    try:
        proc = facade.subprocess.run(command, cwd=facade.BASE_DIR, env=env, stdout=facade.subprocess.PIPE, stderr=facade.subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=HYBRID_DIRECT_TEST_TIMEOUT_SECONDS)
        report = _read_hybrid_direct_test_report(report_path)
        if report:
            report = _normalize_hybrid_direct_test_report_safety(report)
            report.setdefault("process", {})
            if isinstance(report.get("process"), dict):
                report["process"].update({"returncode": int(getattr(proc, "returncode", 0) or 0), "key": _hybrid_direct_test_process_key(self)})
            report.setdefault("reason_codes", [])
            if int(getattr(proc, "returncode", 0) or 0) != 0 and "monitor_returncode_nonzero" not in report["reason_codes"]:
                report["reason_codes"].append("monitor_returncode_nonzero")
                report["passed"] = False
        else:
            report = _hybrid_direct_test_result_payload(self, passed=False, reason_codes=["hybrid_direct_report_missing"], report_path=report_path)
        report.setdefault("stdout_tail", str(getattr(proc, "stdout", "") or "")[-800:])
        report.setdefault("stderr_tail", str(getattr(proc, "stderr", "") or "")[-800:])
        report.setdefault("report_path", report_path)
        _write_backend_hybrid_direct_test_report(self, report, report_path)
        setattr(self, "_latest_hybrid_direct_test_result", report)
        try:
            self._hybrid_direct_state = self._hybrid_direct_state if isinstance(getattr(self, "_hybrid_direct_state", None), dict) else {}
            merged = dict(self._hybrid_direct_state)
            merged.update({"mode": HYBRID_DIRECT_TEST_SESSION_KIND, "enabled": False, "can_influence_device": False, "latest_result": dict(report), "reason_codes": list(report.get("reason_codes") or []), "errors": list(report.get("errors") or []), "timestamp": str(report.get("timestamp") or ""), "latency_ms": ((report.get("result") or {}) if isinstance(report.get("result"), dict) else {}).get("latency_ms")})
            self._hybrid_direct_state = merged
        except Exception:
            LOGGER.debug("Failed updating hybrid direct display state", exc_info=True)
        try:
            self._set_status(_hybrid_result_status_message(self, report), "success" if bool(report.get("passed")) else "warn")
        except Exception:
            pass
        return dict(report)
    except facade.subprocess.TimeoutExpired:
        result = _hybrid_direct_test_result_payload(self, passed=False, reason_codes=["hybrid_direct_test_timeout"], report_path=report_path)
        _write_backend_hybrid_direct_test_report(self, result, report_path)
        setattr(self, "_latest_hybrid_direct_test_result", result)
        try:
            self._set_status(_hybrid_result_status_message(self, result), "warn")
        except Exception:
            pass
        return dict(result)
    except Exception as exc:
        LOGGER.exception("Hybrid Direct Test failed to run")
        result = _hybrid_direct_test_result_payload(self, passed=False, reason_codes=["hybrid_direct_test_process_error"], report_path=report_path, extra={"error": type(exc).__name__})
        _write_backend_hybrid_direct_test_report(self, result, report_path)
        setattr(self, "_latest_hybrid_direct_test_result", result)
        try:
            self._set_status(_hybrid_result_status_message(self, result), "danger")
        except Exception:
            pass
        return dict(result)
    finally:
        setattr(self, "_hybrid_direct_test_running", False)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        if controls is not None and hasattr(controls, "emit"):
            controls.emit()
        _request_refresh(self, "hybrid_direct_test:finished", True)

def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None

def _valid_epoch(value: Optional[float], *, now: Optional[float] = None) -> bool:
    if value is None:
        return False
    if now is None:
        now = _facade().time.time()
    # 2000-01-01 guards corrupted zero/negative values; now+60 tolerates small clock skew.
    return 946684800.0 <= float(value) <= (float(now) + 60.0)

def _state_pid(state: Dict[str, Any]) -> Optional[int]:
    try:
        pid = int(state.get("logger_pid") or state.get("pid") or 0)
        return pid if pid > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None

def _state_pid_for(state: Dict[str, Any], *keys: str) -> Optional[int]:
    state = state if isinstance(state, dict) else {}
    for key in keys:
        try:
            pid = int(state.get(str(key)) or 0)
        except (TypeError, ValueError, OverflowError):
            pid = 0
        if pid > 0:
            return pid
    return None

def _pid_is_running(pid: int) -> bool:
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    if pid <= 0:
        return False
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
        return False

def _terminate_pid_best_effort(pid: Optional[int], *, label: str, wait_timeout: float = 0.75) -> Dict[str, Any]:
    """Best-effort termination for a worker PID recorded in session_state.json.

    This is used only when the UI process has lost the Popen handle, for example
    after the user closed the app before monitor/logger completed their stop loop.
    """
    result: Dict[str, Any] = {
        "label": str(label or "worker"),
        "pid": int(pid or 0) if pid else 0,
        "found": False,
        "terminated": False,
        "forced": False,
        "still_alive": False,
        "error": "",
    }
    if not pid:
        return result
    try:
        pid_value = int(pid)
    except (TypeError, ValueError, OverflowError):
        return result
    result["pid"] = pid_value
    if pid_value <= 0 or pid_value == os.getpid():
        return result
    if not _pid_is_running(pid_value):
        return result
    result["found"] = True
    try:
        os.kill(pid_value, signal.SIGTERM)
        result["terminated"] = True
    except ProcessLookupError:
        result["found"] = False
        return result
    except Exception as exc:
        result["error"] = str(exc)

    deadline = time.time() + max(0.1, float(wait_timeout or 0.75))
    while time.time() < deadline:
        if not _pid_is_running(pid_value):
            result["still_alive"] = False
            return result
        time.sleep(0.05)

    if _pid_is_running(pid_value):
        try:
            if os.name == "nt":
                subprocess_mod = getattr(_facade(), "subprocess", None)
                if subprocess_mod is not None:
                    subprocess_mod.run(
                        ["taskkill", "/PID", str(pid_value), "/T", "/F"],
                        stdout=subprocess_mod.DEVNULL,
                        stderr=subprocess_mod.DEVNULL,
                        timeout=max(0.5, float(wait_timeout or 0.75)),
                        check=False,
                    )
                    result["forced"] = True
            else:
                os.kill(pid_value, signal.SIGKILL)
                result["forced"] = True
        except Exception as exc:
            result["error"] = str(exc)
    result["still_alive"] = _pid_is_running(pid_value)
    return result

def _logger_stop_name_from_state(self, state: Optional[Dict[str, Any]] = None) -> str:
    state = state if isinstance(state, dict) else {}
    try:
        user = str(state.get("user_id") or state.get("expected_user") or (getattr(self, "_current_user", {}) or {}).get("user_id") or "")
        safe = _facade().slugify_username(user)
    except Exception:
        safe = _current_safe_user(self)
    if not safe:
        safe = _current_safe_user(self) or "user"
    return f"logger_user_{safe}"
