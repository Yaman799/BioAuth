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

def _safe_user_slug(value: str) -> str:
    return slugify_username(value) or "user"

def _parse_args():
    return parse_logger_config(sys.argv[1:]).to_legacy_args()

def _initialize_runtime() -> None:
    global ARGS, SESSION_ID, SESSION_RUN_ID, SESSION_STARTED_AT, SESSION_STARTED_AT_TEXT, CONTROL_NAME, SESSION_HOST_BOOT_MARKER, SESSION_HOST_BOOT_TIME, _archived, _stop_reason
    os.makedirs(LIVE_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.makedirs(AUTHORIZED_ARCHIVE_DIR, exist_ok=True)
    os.makedirs(REJECTED_ARCHIVE_DIR, exist_ok=True)
    cfg = parse_logger_config(sys.argv[1:])
    ARGS = cfg.to_legacy_args()
    SESSION_ID = cfg.session_id
    SESSION_RUN_ID = cfg.run_id
    clean_stale_logger_temp_heartbeats()
    SESSION_STARTED_AT = time.time()
    SESSION_STARTED_AT_TEXT = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(SESSION_STARTED_AT))
    CONTROL_NAME = ARGS["control_name"]
    SESSION_HOST_BOOT_MARKER = current_boot_marker()
    SESSION_HOST_BOOT_TIME = current_boot_time_epoch()
    _archived = False
    _stop_reason = None
    _stop_event.clear()
    _flush_event.clear()
    _reset_capture_counters()
    _reset_listener_health()
    _reset_mouse_throttle_state()

def _normalize_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in ("legit", "legitimate", "accepted"):
        return "legit"
    if v == "suspicious":
        return "suspicious"
    if v == "intruder":
        return "intruder"
    if v in ("rejected", "unauthorized"):
        return "rejected"
    if v in ("interrupted", "unknown", "pending", ""):
        return None
    return None

def _privacy_safe_key(key) -> str:
    return _worker_privacy_safe_key(key)

def _count_rows(filepath: str, header: str) -> int:
    try:
        text = read_decrypted(filepath, header).strip()
        if not text or text == header:
            return 0
        return max(0, len(text.splitlines()) - 1)
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        LOGGER.warning("Failed counting encrypted rows for %s: %s", filepath, exc)
        return 0

def _ensure_seed_files() -> None:
    write_encrypted(KEYBOARD_FILE, [], KB_HEADER)
    write_encrypted(MOUSE_FILE, [], MS_HEADER)

def _reset_live_session_buffers() -> None:
    with _buffer_lock:
        _keyboard_buffer.clear()
        _mouse_buffer.clear()

def _reset_mouse_throttle_state() -> None:
    global _mouse_last_kept_move
    with _mouse_state_lock:
        _mouse_buttons_down.clear()
        _mouse_last_kept_move = None
        _mouse_move_counters["raw_move_count"] = 0
        _mouse_move_counters["kept_move_count"] = 0
        _mouse_move_counters["dropped_move_count"] = 0

def _mouse_throttle_counters_snapshot() -> dict[str, int]:
    with _mouse_state_lock:
        return {
            "raw_move_count": int(_mouse_move_counters.get("raw_move_count", 0)),
            "kept_move_count": int(_mouse_move_counters.get("kept_move_count", 0)),
            "dropped_move_count": int(_mouse_move_counters.get("dropped_move_count", 0)),
        }

def _reset_capture_counters() -> None:
    with _mouse_state_lock:
        _capture_counters["keyboard_event_count"] = 0
        _capture_counters["mouse_event_count"] = 0
        _capture_counters["last_capture_at"] = 0.0
        _capture_counters["last_keyboard_event_at"] = 0.0
        _capture_counters["last_mouse_event_at"] = 0.0

def _reset_listener_health() -> None:
    with _listener_state_lock:
        _listener_health.update({
            "keyboard_listener_started": False,
            "mouse_listener_started": False,
            "keyboard_listener_alive": False,
            "mouse_listener_alive": False,
            "keyboard_listener_error": "",
            "mouse_listener_error": "",
            "listener_exit_reason": "",
            "capture_degraded": False,
            "capture_status": "starting",
        })

def _safe_error_text(exc: BaseException | str | None) -> str:
    if exc is None:
        return ""
    text = str(exc)
    if not text and not isinstance(exc, str):
        text = type(exc).__name__
    return text[:240]

def _listener_alive(listener) -> bool:
    if listener is None:
        return False
    try:
        alive = listener.is_alive()
        return bool(alive)
    except AttributeError:
        return True
    except Exception:
        return False

def _mark_listener_started(kind: str) -> None:
    key = "keyboard" if str(kind).lower().startswith("key") else "mouse"
    with _listener_state_lock:
        _listener_health[f"{key}_listener_started"] = True
        _listener_health[f"{key}_listener_alive"] = True
        _listener_health[f"{key}_listener_error"] = ""
        _listener_health["capture_status"] = _capture_status_locked()

def _mark_listener_error(kind: str, exc: BaseException | str, *, fatal: bool = False) -> None:
    key = "keyboard" if str(kind).lower().startswith("key") else "mouse"
    with _listener_state_lock:
        _listener_health[f"{key}_listener_error"] = _safe_error_text(exc)
        _listener_health[f"{key}_listener_alive"] = False
        if fatal or not _listener_health.get("listener_exit_reason"):
            _listener_health["listener_exit_reason"] = f"{key}_listener_failed"
        _listener_health["capture_status"] = _capture_status_locked()

def _capture_status_locked() -> str:
    kb_started = bool(_listener_health.get("keyboard_listener_started"))
    ms_started = bool(_listener_health.get("mouse_listener_started"))
    kb_alive = bool(_listener_health.get("keyboard_listener_alive"))
    ms_alive = bool(_listener_health.get("mouse_listener_alive"))
    if kb_alive and ms_alive:
        return "capture_ok"
    if ms_alive and (kb_started or not kb_alive):
        return "capture_degraded_keyboard_listener_failed"
    if kb_alive and (ms_started or not ms_alive):
        return "capture_degraded_mouse_listener_failed"
    if kb_started or ms_started:
        return "capture_failed_all_listeners_dead"
    return "starting"

def _refresh_listener_health_from_objects() -> dict[str, object]:
    with _listener_state_lock:
        previous_kb_alive = bool(_listener_health.get("keyboard_listener_alive"))
        previous_ms_alive = bool(_listener_health.get("mouse_listener_alive"))
        kb_started = bool(_listener_health.get("keyboard_listener_started"))
        ms_started = bool(_listener_health.get("mouse_listener_started"))
    kb_alive = _listener_alive(kb_listener) if kb_started else False
    ms_alive = _listener_alive(ms_listener) if ms_started else False
    with _listener_state_lock:
        _listener_health["keyboard_listener_alive"] = kb_alive
        _listener_health["mouse_listener_alive"] = ms_alive
        if kb_started and previous_kb_alive and not kb_alive and not _listener_health.get("keyboard_listener_error"):
            _listener_health["keyboard_listener_error"] = "listener_stopped_unexpectedly"
            if not _listener_health.get("listener_exit_reason"):
                _listener_health["listener_exit_reason"] = "keyboard_listener_stopped"
        if ms_started and previous_ms_alive and not ms_alive and not _listener_health.get("mouse_listener_error"):
            _listener_health["mouse_listener_error"] = "listener_stopped_unexpectedly"
            if not _listener_health.get("listener_exit_reason"):
                _listener_health["listener_exit_reason"] = "mouse_listener_stopped"
        _listener_health["capture_status"] = _capture_status_locked()
        _listener_health["capture_degraded"] = _listener_health["capture_status"] not in {"capture_ok", "starting"}
        return dict(_listener_health)

def _listener_health_snapshot() -> dict[str, object]:
    with _listener_state_lock:
        snap = dict(_listener_health)
    snap.setdefault("protected_mode", ARGS.get("session_kind") == "protected")
    return snap

def _capture_counters_snapshot() -> dict[str, object]:
    with _mouse_state_lock:
        keyboard_count = int(_capture_counters.get("keyboard_event_count", 0) or 0)
        mouse_count = int(_capture_counters.get("mouse_event_count", 0) or 0)
        last_capture = float(_capture_counters.get("last_capture_at", 0.0) or 0.0)
        last_keyboard = float(_capture_counters.get("last_keyboard_event_at", 0.0) or 0.0)
        last_mouse = float(_capture_counters.get("last_mouse_event_at", 0.0) or 0.0)
    return {
        "keyboard_event_count": keyboard_count,
        "mouse_event_count": mouse_count,
        "capture_event_count": keyboard_count + mouse_count,
        "last_capture_at": last_capture,
        "last_capture_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_capture)) if last_capture > 0 else "",
        "last_keyboard_event_at": last_keyboard,
        "last_keyboard_event_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_keyboard)) if last_keyboard > 0 else "",
        "last_mouse_event_at": last_mouse,
        "last_mouse_event_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_mouse)) if last_mouse > 0 else "",
    }

def _record_capture_event(kind: str, ts: Optional[float] = None) -> None:
    event_time = float(ts if ts is not None else time.time())
    with _mouse_state_lock:
        if str(kind or "").lower() == "keyboard":
            _capture_counters["keyboard_event_count"] = int(_capture_counters.get("keyboard_event_count", 0) or 0) + 1
            _capture_counters["last_keyboard_event_at"] = event_time
        elif str(kind or "").lower() == "mouse":
            _capture_counters["mouse_event_count"] = int(_capture_counters.get("mouse_event_count", 0) or 0) + 1
            _capture_counters["last_mouse_event_at"] = event_time
        _capture_counters["last_capture_at"] = event_time

def _should_keep_mouse_motion(x: float, y: float, ts: float, *, drag: bool) -> bool:
    global _mouse_last_kept_move
    with _mouse_state_lock:
        _mouse_move_counters["raw_move_count"] += 1
        if drag:
            _mouse_move_counters["kept_move_count"] += 1
            _mouse_last_kept_move = (float(x), float(y), float(ts))
            return True

        if _mouse_last_kept_move is None:
            _mouse_move_counters["kept_move_count"] += 1
            _mouse_last_kept_move = (float(x), float(y), float(ts))
            return True

        last_x, last_y, last_ts = _mouse_last_kept_move
        elapsed = float(ts) - float(last_ts)
        distance = math.hypot(float(x) - float(last_x), float(y) - float(last_y))
        if elapsed < 0.0 or elapsed >= MOUSE_MOVE_THROTTLE_SECONDS or distance >= MOUSE_MOVE_THROTTLE_PIXELS:
            _mouse_move_counters["kept_move_count"] += 1
            _mouse_last_kept_move = (float(x), float(y), float(ts))
            return True

        _mouse_move_counters["dropped_move_count"] += 1
        return False

def reset_live_session_files() -> None:
    _reset_live_session_buffers()
    _ensure_seed_files()
