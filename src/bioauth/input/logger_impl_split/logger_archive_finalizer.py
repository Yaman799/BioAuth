"""Extracted implementation section for `src/bioauth/input/logger_impl.py`."""
from __future__ import annotations
import atexit
import logging
import json
import math
import os
import shutil
import signal
import sys
import threading
import time
import traceback
import uuid
from typing import Optional, Set
from pynput import keyboard, mouse
from control import clear_stop, current_boot_marker, current_boot_time_epoch, read_session_state, session_state_diagnostics
from bioauth_runtime.logger_worker.config import parse_logger_config
from bioauth_runtime.logger_worker.heartbeat import clean_stale_logger_temp_heartbeats, write_logger_heartbeat_payload
from bioauth_runtime.logger_worker.keyboard_capture import privacy_safe_key as _worker_privacy_safe_key
from bioauth_runtime.logger_worker.mouse_capture import button_name as _worker_button_name
from bioauth_runtime.logger_worker.shutdown import logger_stop_control_status, should_stop_logger
from evidence_capture import update_incident_record
from paths import data_dir, live_session_dir, sessions_dir
from shadow_core.background_contracts import shadow_evidence_paths
from security import append_encrypted_rows, atomic_write_text, compact_chunks, read_decrypted, rotate_encrypted, save_metadata_hash, write_encrypted
from utils.identity import slugify_username

def _write_logger_heartbeat(status: str = "ok") -> None:
    """Refresh logger liveness without clobbering monitor telemetry."""
    try:
        state = read_session_state(default={})
        payload = dict(state) if isinstance(state, dict) else {}
        if payload.get("session_id") and str(payload.get("session_id")) != SESSION_ID:
            return
        if ARGS["session_kind"] == "protected" and (
            bool(payload.get("technical_failure"))
            or bool(payload.get("monitor_failed"))
            or bool(payload.get("risk_engine_stopped"))
            or str(payload.get("status") or "").strip().lower() in {"monitor_exited_after_ready", "monitor_unavailable", "risk_engine_stopped", "logger_exited_after_ready"}
        ):
            # Commercial-Core-22L: once the bridge marks protected monitoring as
            # failed, the logger must not keep rewriting session_state back to
            # active/ok.  Shut down cleanly and let the existing failure state win.
            _request_shutdown("monitor_failed_pair_stop")
            try:
                payload.update({
                    "active": False,
                    "logger_ready": False,
                    "logger_stopped_because_monitor_failed": True,
                    "logger_exit_reason": "monitor_failed_pair_stop",
                    "logger_exit_detail": "Logger stopped because the protected monitor exited after readiness.",
                    "logger_heartbeat_at": time.time(),
                    "logger_pid": os.getpid(),
                })
                write_logger_heartbeat_payload({
                    **dict(payload),
                    "worker_kind": "logger",
                    "status": "stopped",
                    "heartbeat_at": time.time(),
                    "logger_ready": False,
                    "logger_stopped_because_monitor_failed": True,
                })
            except Exception:
                LOGGER.debug("Failed preserving monitor failure state from logger heartbeat", exc_info=True)
            return
        now = time.time()
        heartbeat = {
            "session_id": SESSION_ID,
            "run_id": SESSION_RUN_ID,
            "active": True,
            "logger_ready": True,
            "logger_pid": os.getpid(),
            "logger_heartbeat_at": now,
            "logger_heartbeat_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "live_session_dir": LIVE_DIR,
            "user_id": ARGS["safe_user"],
            "session_kind": ARGS["session_kind"],
        }
        heartbeat.update(_capture_counters_snapshot())
        heartbeat.update(_listener_health_snapshot())
        heartbeat.update(_control_status_snapshot())
        heartbeat["mouse_throttle"] = _mouse_throttle_counters_snapshot()
        monitored_runtime = (
            ARGS["session_kind"] in {"protected", SHADOW_EVIDENCE_SESSION_KIND}
            and str(payload.get("mode") or "").strip().lower() in {"monitored", SHADOW_EVIDENCE_SESSION_KIND}
            and bool(payload.get("monitor_ready"))
        )
        if monitored_runtime:
            payload.update(heartbeat)
            if _is_shadow_evidence_session():
                payload.update(_shadow_evidence_tags())
                payload.setdefault("status", status or SHADOW_EVIDENCE_SESSION_KIND)
            else:
                payload.setdefault("source", "monitor")
                payload.setdefault("mode", "monitored")
                payload.setdefault("status", status or "ok")
        else:
            base = _state_base(active=True, logger_ready=True, status=status)
            base.update(heartbeat)
            payload.update(base)
        write_logger_heartbeat_payload({
            **dict(payload),
            "worker_kind": "logger",
            "heartbeat_at": time.time(),
            "heartbeat_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception:
        LOGGER.exception("Failed writing logger heartbeat")

def _start_keyboard_listener():
    global kb_listener
    try:
        kb_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        kb_listener.start()
        _mark_listener_started("keyboard")
        return kb_listener
    except BaseException as exc:
        kb_listener = None
        _mark_listener_error("keyboard", exc)
        LOGGER.exception("Keyboard listener failed to start")
        return None

def _start_mouse_listener():
    global ms_listener
    try:
        ms_listener = mouse.Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll)
        ms_listener.start()
        _mark_listener_started("mouse")
        return ms_listener
    except BaseException as exc:
        ms_listener = None
        _mark_listener_error("mouse", exc)
        LOGGER.exception("Mouse listener failed to start")
        return None

def _listener_status_for_heartbeat() -> str:
    status = str(_listener_health_snapshot().get("capture_status") or "ok")
    if status in {"capture_ok", "starting"}:
        return "ok"
    if status == "capture_failed_all_listeners_dead":
        return "listener_failure"
    return status

def _supervised_capture_loop(*, poll_interval: float = 0.5, heartbeat_interval: float = 1.0, max_iterations: Optional[int] = None) -> str:
    """Keep protected logger alive while at least one listener source is usable."""
    iterations = 0
    next_heartbeat = 0.0
    while not _stop_event.is_set():
        if _control_stop_requested():
            _request_shutdown("control_stop")
            break
        health = _refresh_listener_health_from_objects()
        keyboard_started = bool(health.get("keyboard_listener_started"))
        mouse_started = bool(health.get("mouse_listener_started"))
        keyboard_alive = bool(health.get("keyboard_listener_alive"))
        mouse_alive = bool(health.get("mouse_listener_alive"))
        if (keyboard_started or mouse_started) and not (keyboard_alive or mouse_alive):
            _request_shutdown("listener_failure")
            _write_logger_heartbeat("listener_failure")
            break
        now = time.time()
        if now >= next_heartbeat:
            _write_logger_heartbeat(_listener_status_for_heartbeat())
            next_heartbeat = now + max(0.1, heartbeat_interval)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            return "test_limit"
        time.sleep(max(0.05, poll_interval))
    return _current_stop_reason()

def run_logger() -> int:
    _initialize_runtime()
    atexit.register(_request_shutdown)
    startup_error: Optional[BaseException] = None
    watcher = None
    flusher = None

    try:
        clear_stop(CONTROL_NAME)
        _write_session_state_required(_state_base(active=False, logger_ready=False, status="starting"), "logger_start_state_write_failed")
        reset_live_session_files()

        watcher = threading.Thread(target=_stop_watcher, daemon=True)
        watcher.start()
        flusher = threading.Thread(target=_flush_worker, daemon=True)
        flusher.start()

        _start_keyboard_listener()
        _start_mouse_listener()
        health = _refresh_listener_health_from_objects()
        if not (health.get("keyboard_listener_alive") or health.get("mouse_listener_alive")):
            raise RuntimeError("logger_listener_startup_failed")
        _write_session_state_required(_state_base(active=True, logger_ready=True, status=_listener_status_for_heartbeat()), "logger_ready_state_write_failed")

        print(f"[Logger] Started for {ARGS['session_label']} ({ARGS['session_kind']})", flush=True)
        _supervised_capture_loop()
    except BaseException as exc:
        startup_error = exc
        _write_logger_startup_error("logger_startup_or_runtime_failure", exc)
        LOGGER.exception("Logger worker failed for %s (%s)", ARGS["session_label"], ARGS["session_kind"])
        state = read_session_state(default={})
        if isinstance(state, dict):
            state.update(
                {
                    "active": False,
                    "logger_ready": False,
                    "technical_failure": True,
                    "logger_failed": True,
                    "logger_error": str(exc),
                    "status": "failed",
                    "host_boot_marker": SESSION_HOST_BOOT_MARKER,
                    "host_boot_time": SESSION_HOST_BOOT_TIME,
                    "logger_pid": os.getpid(),
                }
            )
            write_logger_heartbeat_payload({
                **dict(state),
                **_capture_counters_snapshot(),
                **_listener_health_snapshot(),
                "worker_kind": "logger",
                "heartbeat_at": time.time(),
                "logger_ready": False,
                "logger_failed": True,
            })
        _request_shutdown("startup_failure")
        print(f"[Logger] Startup/runtime failure: {exc}", file=sys.stderr, flush=True)
    finally:
        _request_shutdown()
        _run_finalization_step("stop_mouse_listener", _stop_listener, ms_listener, "mouse", join_timeout=2.0)
        _run_finalization_step("stop_keyboard_listener", _stop_listener, kb_listener, "keyboard", join_timeout=2.0)
        if flusher is not None:
            _run_finalization_step("join_flusher", flusher.join, timeout=2.0)
        _run_finalization_step("flush_buffers", _flush_buffers)
        _run_finalization_step("archive_live_session", archive_live_session)
        _run_finalization_step("clear_control_stop", clear_stop, CONTROL_NAME)
        _run_finalization_step("cleanup_live_session_dir", _cleanup_managed_live_session_dir)

    if startup_error is not None:
        return 1
    return 2 if _current_stop_reason() == "listener_failure" else 0
