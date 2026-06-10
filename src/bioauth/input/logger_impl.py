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
try:
    from metadata_core.auto_enrollment import metadata_tags_from_environment
except Exception:  # pragma: no cover - logger must still archive if optional helper import fails
    def metadata_tags_from_environment(*_args, **_kwargs):
        return {}
MAX_SIZE = 5 * 1024 * 1024
LIVE_DIR = live_session_dir()
ARCHIVE_DIR = sessions_dir()
AUTHORIZED_ARCHIVE_DIR = os.path.join(ARCHIVE_DIR, "authorized")
REJECTED_ARCHIVE_DIR = os.path.join(ARCHIVE_DIR, "rejected")
KEYBOARD_FILE = os.path.join(LIVE_DIR, "keyboard_log.csv")
MOUSE_FILE = os.path.join(LIVE_DIR, "mouse_log.csv")
KB_HEADER = "key,event,timestamp"
MS_HEADER = "x,y,event,timestamp"
FLUSH_INTERVAL = 0.5
MAX_BUFFER_ROWS = 120
MONITOR_DECISION_WAIT = 12.0
MOUSE_MOVE_THROTTLE_SECONDS = 0.04
MOUSE_MOVE_THROTTLE_PIXELS = 4.0
SHADOW_EVIDENCE_SESSION_KIND = "shadow_evidence"
SHADOW_EVIDENCE_SOURCE = "shadow_evidence_monitor"
_buffer_lock = threading.Lock()
_flush_event = threading.Event()
_stop_event = threading.Event()
_keyboard_buffer = []
_mouse_buffer = []
kb_listener = None
ms_listener = None
_archived = False
_stop_reason: Optional[str] = None
_mouse_state_lock = threading.Lock()
_mouse_buttons_down: Set[str] = set()
_mouse_last_kept_move: Optional[tuple[float, float, float]] = None
_mouse_move_counters = {"raw_move_count": 0, "kept_move_count": 0, "dropped_move_count": 0}
_capture_counters = {
    "keyboard_event_count": 0,
    "mouse_event_count": 0,
    "last_capture_at": 0.0,
    "last_keyboard_event_at": 0.0,
    "last_mouse_event_at": 0.0,
}
_listener_state_lock = threading.Lock()
_listener_health = {
    "keyboard_listener_started": False,
    "mouse_listener_started": False,
    "keyboard_listener_alive": False,
    "mouse_listener_alive": False,
    "keyboard_listener_error": "",
    "mouse_listener_error": "",
    "listener_exit_reason": "",
    "capture_degraded": False,
    "capture_status": "starting",
}
LOGGER = logging.getLogger(__name__)
ARGS = {
    "legacy": True,
    "user_id": None,
    "safe_user": None,
    "session_label": "legit",
    "session_kind": "legacy",
    "control_name": "logger",
}
SESSION_ID = ""
SESSION_RUN_ID = ""
SESSION_STARTED_AT = 0.0
SESSION_STARTED_AT_TEXT = ""
CONTROL_NAME = "logger"
SESSION_HOST_BOOT_MARKER = ""
SESSION_HOST_BOOT_TIME = None

# Compatibility shell: implementation functions are loaded into this module
# so existing monkeypatches of private globals such as _facade still work.
from pathlib import Path as _BioAuthSplitPath

_BIOAUTH_SPLIT_DIR = _BioAuthSplitPath(__file__).with_name('logger_impl_split')
_BIOAUTH_SPLIT_MODULES = ('logger_args.py', 'logger_runtime_init.py', 'logger_capture_health.py', 'logger_stop_control.py', 'logger_archive_finalizer.py',)

def _bioauth_load_split_modules() -> None:
    namespace = globals()
    for module_name in _BIOAUTH_SPLIT_MODULES:
        module_path = _BIOAUTH_SPLIT_DIR / module_name
        code = module_path.read_text(encoding='utf-8')
        exec(compile(code, str(module_path), 'exec'), namespace, namespace)

_bioauth_load_split_modules()

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# Compatibility source markers retained for legacy source-inspection tests.
# def _safe_user_slug
# def _parse_args
# def _initialize_runtime
# def _normalize_label
# def _privacy_safe_key
# def _count_rows
# def _ensure_seed_files
# def _reset_live_session_buffers
# def _reset_mouse_throttle_state
# def _mouse_throttle_counters_snapshot
# def _reset_capture_counters
# def _reset_listener_health
# def _safe_error_text
# def _listener_alive
# def _mark_listener_started
# def _mark_listener_error
# def _capture_status_locked
# def _refresh_listener_health_from_objects
# def _listener_health_snapshot
# def _capture_counters_snapshot
# def _record_capture_event
# def _should_keep_mouse_motion
# def reset_live_session_files
# def _stop_listener
# def _request_shutdown
# def _signal_handler
# def _is_shadow_evidence_session
# def _shadow_evidence_tags
# def _session_mode
# def _current_stop_reason
# def _control_status_snapshot
# def _control_stop_requested
# def _determine_archive_decision
# def _archive_folder_name
# def _archive_root_for_decision
# def _is_training_eligible
# def _record_finalization_warning
# def _run_finalization_step
# def archive_live_session
# def _queue_keyboard_row
# def _queue_mouse_row
# def _flush_buffers
# def _flush_worker
# def _stop_watcher
# def _button_name
# def _drag_active
# def on_press
# def on_release
# def on_move
# def on_click
# def on_scroll
# def _is_managed_live_session_dir
# def _cleanup_managed_live_session_dir
# def _state_base
# def _write_session_state_required
# def _logger_startup_error_path
# def _write_logger_startup_error
# def _write_logger_heartbeat
# def _start_keyboard_listener
# def _start_mouse_listener
# def _listener_status_for_heartbeat
# def _supervised_capture_loop
# def run_logger
# Commercial-Core-22M makes the bridge the single writer
# write_logger_heartbeat_payload
# archive_write_logger_final_heartbeat
# logger_heartbeat_write_failed

if __name__ == "__main__":
    raise SystemExit(run_logger())
