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

def _queue_mouse_row(row):
    try:
        _record_capture_event("mouse", float(row[3]) if len(row) > 3 else None)
    except Exception:
        _record_capture_event("mouse")
    with _buffer_lock:
        _mouse_buffer.append(row)
        should_flush = len(_mouse_buffer) >= MAX_BUFFER_ROWS
    if should_flush:
        _flush_event.set()

def _flush_buffers() -> None:
    with _buffer_lock:
        kb = _keyboard_buffer[:]
        ms = _mouse_buffer[:]
        _keyboard_buffer.clear()
        _mouse_buffer.clear()
    if kb:
        rotate_encrypted(KEYBOARD_FILE, KB_HEADER, MAX_SIZE)
        append_encrypted_rows(KEYBOARD_FILE, kb, KB_HEADER)
    if ms:
        rotate_encrypted(MOUSE_FILE, MS_HEADER, MAX_SIZE)
        append_encrypted_rows(MOUSE_FILE, ms, MS_HEADER)

def _flush_worker() -> None:
    while not _stop_event.is_set():
        if _control_stop_requested():
            print("[Logger] Stop requested", flush=True)
            _request_shutdown("control_stop")
            break
        _flush_event.wait(timeout=FLUSH_INTERVAL)
        _flush_event.clear()
        _flush_buffers()
        _write_logger_heartbeat("ok")
    _flush_buffers()

def _stop_watcher() -> None:
    while not _stop_event.is_set():
        if _control_stop_requested():
            _request_shutdown("control_stop")
            break
        time.sleep(0.5)

def _button_name(button) -> str:
    return _worker_button_name(button)

def _drag_active() -> bool:
    with _mouse_state_lock:
        return bool(_mouse_buttons_down)

def on_press(key):
    try:
        _queue_keyboard_row([_privacy_safe_key(key), "press", time.time()])
    except Exception as exc:
        _mark_listener_error("keyboard", exc)
        LOGGER.exception("Keyboard press callback failed")

def on_release(key):
    try:
        _queue_keyboard_row([_privacy_safe_key(key), "release", time.time()])
    except Exception as exc:
        _mark_listener_error("keyboard", exc)
        LOGGER.exception("Keyboard release callback failed")

def on_move(x, y):
    try:
        ts = time.time()
        drag = _drag_active()
        event = "drag" if drag else "move"
        if not _should_keep_mouse_motion(float(x), float(y), ts, drag=drag):
            return
        _queue_mouse_row([x, y, event, ts])
    except Exception as exc:
        _mark_listener_error("mouse", exc)
        LOGGER.exception("Mouse move callback failed")

def on_click(x, y, button, pressed):
    try:
        name = _button_name(button)
        with _mouse_state_lock:
            if pressed:
                _mouse_buttons_down.add(name)
            else:
                _mouse_buttons_down.discard(name)
        event = f"click_{'press' if pressed else 'release'}_{name}"
        _queue_mouse_row([x, y, event, time.time()])
    except Exception as exc:
        _mark_listener_error("mouse", exc)
        LOGGER.exception("Mouse click callback failed")

def on_scroll(x, y, dx, dy):
    try:
        if abs(dy) >= abs(dx):
            direction = "up" if dy > 0 else "down"
        else:
            direction = "right" if dx > 0 else "left"
        _queue_mouse_row([x, y, f"scroll_{direction}", time.time()])
    except Exception as exc:
        _mark_listener_error("mouse", exc)
        LOGGER.exception("Mouse scroll callback failed")

def _is_managed_live_session_dir(path: str) -> bool:
    try:
        target = os.path.realpath(path or "")
        managed_root = os.path.realpath(os.path.join(data_dir(), "live_session_runs"))
        return bool(target) and os.path.commonpath([target, managed_root]) == managed_root
    except Exception:
        return False

def _cleanup_managed_live_session_dir() -> None:
    if not _is_managed_live_session_dir(LIVE_DIR):
        reset_live_session_files()
        return
    shutil.rmtree(LIVE_DIR, ignore_errors=True)

def _state_base(*, active: bool, logger_ready: bool, status: str) -> dict:
    now = time.time()
    passive_tags = metadata_tags_from_environment()
    shadow_tags = _shadow_evidence_tags()
    mode = shadow_tags.get("mode") or "standalone"
    source = shadow_tags.get("source") or "logger"
    return {
        "schema_version": 2,
        "session_id": SESSION_ID,
        "run_id": SESSION_RUN_ID,
        "mode": mode,
        "decision": "pending" if ARGS["session_kind"] in {"protected", SHADOW_EVIDENCE_SESSION_KIND} else None,
        "active": bool(active),
        "logger_ready": bool(logger_ready),
        "source": source,
        "command_label": ARGS["session_label"],
        "user_id": ARGS["safe_user"],
        "session_kind": ARGS["session_kind"],
        "started_at": SESSION_STARTED_AT,
        "started_at_text": SESSION_STARTED_AT_TEXT,
        "host_boot_marker": SESSION_HOST_BOOT_MARKER,
        "host_boot_time": SESSION_HOST_BOOT_TIME,
        "status": str(status or "ok"),
        "logger_pid": os.getpid(),
        "logger_heartbeat_at": now,
        "logger_heartbeat_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "live_session_dir": LIVE_DIR,
        **_capture_counters_snapshot(),
        **_listener_health_snapshot(),
        **passive_tags,
        **shadow_tags,
    }

def _write_session_state_required(payload: dict, stage: str) -> None:
    """Publish logger startup/readiness without writing session_state.json.

    Commercial-Core-22M makes the bridge the single writer of session_state.json.
    The logger now writes worker_heartbeats/logger_heartbeat.json and the bridge
    merges that heartbeat into the authoritative session state.
    """
    heartbeat = dict(payload or {})
    heartbeat.update({
        "worker_kind": "logger",
        "stage": str(stage or "logger_state"),
        "heartbeat_at": time.time(),
        "heartbeat_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
        "logger_pid": os.getpid(),
    })
    if not write_logger_heartbeat_payload(heartbeat):
        LOGGER.warning("logger_heartbeat_write_failed at stage %s; capture will keep running", stage or "logger_state")
        return

def _logger_startup_error_path() -> str:
    safe_user = _safe_user_slug(ARGS.get("safe_user") or ARGS.get("session_label") or "user")
    directory = os.path.join(data_dir(), "control", "logger_startup_errors")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"logger_startup_error_{safe_user}.json")

def _write_logger_startup_error(stage: str, exc: BaseException) -> None:
    """Persist a copy-safe explanation when logger.py exits before readiness."""
    try:
        payload = {
            "stage": str(stage or "logger_startup_failure"),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "user_id": ARGS.get("safe_user") or "",
            "session_kind": ARGS.get("session_kind") or "",
            "session_id": SESSION_ID,
            "run_id": SESSION_RUN_ID,
            "pid": os.getpid(),
            "created_at": time.time(),
            "created_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
            "session_state_diagnostics": session_state_diagnostics(),
            "traceback_tail": traceback.format_exception_only(type(exc), exc)[-3:],
        }
        path = _logger_startup_error_path()
        tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        LOGGER.debug("Failed writing logger startup error diagnostics", exc_info=True)
