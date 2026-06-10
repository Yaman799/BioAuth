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

def _stop_listener(listener, name: str, *, join_timeout: Optional[float] = None) -> None:
    if listener is None:
        return
    try:
        listener.stop()
    except (AttributeError, OSError, RuntimeError) as exc:
        LOGGER.warning("Failed stopping %s listener: %s", name, exc)
    if join_timeout is None:
        return
    try:
        listener.join(timeout=join_timeout)
    except (AttributeError, OSError, RuntimeError) as exc:
        LOGGER.warning("Failed joining %s listener: %s", name, exc)

def _request_shutdown(reason: Optional[str] = None) -> None:
    global kb_listener, ms_listener, _stop_reason
    if reason and _stop_reason is None:
        _stop_reason = reason
    _stop_event.set()
    _flush_event.set()
    with _mouse_state_lock:
        _mouse_buttons_down.clear()
    _stop_listener(kb_listener, "keyboard")
    _stop_listener(ms_listener, "mouse")

def _signal_handler(*_args):
    _request_shutdown("signal")

def _is_shadow_evidence_session() -> bool:
    return str(ARGS.get("session_kind") or "").strip().lower() == SHADOW_EVIDENCE_SESSION_KIND

def _shadow_evidence_tags() -> dict:
    if not _is_shadow_evidence_session():
        return {}
    return {
        "mode": SHADOW_EVIDENCE_SESSION_KIND,
        "runtime_mode": SHADOW_EVIDENCE_SESSION_KIND,
        "source": SHADOW_EVIDENCE_SOURCE,
        "evidence_source": SHADOW_EVIDENCE_SOURCE,
        "trust_level": "shadow_runtime",
        "excluded_from_positive_training": True,
        "training_counts_toward_minimum": False,
        "metadata_trusted": False,
        "owner_positive_training_allowed": False,
        "protected_sessions_available": False,
        "production_ready": False,
        "production_approval_allowed": False,
        "production_promotion_allowed": False,
    }

def _session_mode() -> str:
    state = read_session_state(default={})
    if not isinstance(state, dict):
        return SHADOW_EVIDENCE_SESSION_KIND if _is_shadow_evidence_session() else "standalone"
    mode = str(state.get("mode", "standalone")).strip().lower()
    if _is_shadow_evidence_session() and mode in {"", "standalone"}:
        return SHADOW_EVIDENCE_SESSION_KIND
    return mode

def _current_stop_reason() -> str:
    return _stop_reason or "listener_exit"

def _control_status_snapshot() -> dict[str, object]:
    try:
        status = logger_stop_control_status(
            CONTROL_NAME,
            session_id=SESSION_ID,
            run_id=SESSION_RUN_ID,
            worker_started_at=SESSION_STARTED_AT,
        )
    except Exception as exc:
        return {
            "control_file_seen": False,
            "control_file_valid": False,
            "control_file_error": str(exc)[:240],
            "stop_requested": False,
            "final_stop_reason": _current_stop_reason(),
        }
    out = dict(status or {})
    out["stop_requested"] = bool(out.get("should_stop"))
    out["final_stop_reason"] = _current_stop_reason()
    out["logger_session_id"] = SESSION_ID
    out["logger_run_id"] = SESSION_RUN_ID
    return out

def _control_stop_requested() -> bool:
    status = _control_status_snapshot()
    if bool(status.get("ignored_stale_control_file")):
        try:
            _write_logger_heartbeat(_listener_status_for_heartbeat())
        except Exception:
            LOGGER.debug("Failed publishing stale control-file diagnostic", exc_info=True)
    if bool(status.get("should_stop")):
        return True
    # Keep tests and legacy non-file stop hooks working; real session-scoped
    # workers still receive the same scoped decision from should_stop_logger.
    if not bool(status.get("control_file_seen")):
        try:
            return bool(should_stop_logger(CONTROL_NAME))
        except Exception:
            return False
    return False

def _determine_archive_decision() -> tuple[str, str]:
    mode = _session_mode()
    last_seen = None

    if mode == "monitored":
        deadline = time.time() + MONITOR_DECISION_WAIT
        while time.time() < deadline:
            state = read_session_state(default={})
            if not isinstance(state, dict):
                time.sleep(0.5)
                continue

            decision = _normalize_label(state.get("decision"))
            if decision:
                last_seen = decision

            if state.get("forced_stop") or state.get("app_locked"):
                if decision == "intruder":
                    return "intruder", "monitor"
                if decision in ("suspicious", "rejected"):
                    return decision, "monitor"
                return "rejected", "monitor"

            if decision in ("intruder", "suspicious", "rejected"):
                return decision, "monitor"

            if decision == "legit" and not state.get("active"):
                return "legit", "monitor"

            time.sleep(0.5)

        if last_seen in ("intruder", "suspicious", "rejected"):
            return last_seen, "monitor"
        return "interrupted", "fallback"

    if ARGS["legacy"]:
        return _normalize_label(ARGS["session_label"]) or "legit", "legacy"

    if ARGS["session_kind"] == "protected":
        return "interrupted", "fallback"

    return "legit", "fallback"

def _archive_folder_name(archive_decision: str) -> str:
    normalized = _normalize_label(archive_decision) or "interrupted"
    if ARGS["legacy"]:
        return f"{normalized}_{SESSION_ID}"
    return f"{ARGS['safe_user']}_{ARGS['session_kind']}_{normalized}_{SESSION_ID}"

def _archive_root_for_decision(archive_decision: str) -> str:
    normalized = _normalize_label(archive_decision) or "interrupted"
    if _is_shadow_evidence_session():
        base = shadow_evidence_paths(ARGS.get("safe_user") or "user")["base"]
        return os.path.join(base, "sessions")
    if normalized == "legit":
        return AUTHORIZED_ARCHIVE_DIR
    return os.path.join(REJECTED_ARCHIVE_DIR, normalized)

def _is_training_eligible(archive_decision: str) -> bool:
    normalized = _normalize_label(archive_decision)
    if ARGS["legacy"]:
        return False
    if ARGS["session_kind"] != "enrollment":
        return False
    if normalized != "legit":
        return False
    if _current_stop_reason() != "control_stop":
        return False
    return (_count_rows(KEYBOARD_FILE, KB_HEADER) + _count_rows(MOUSE_FILE, MS_HEADER)) > 0

def _record_finalization_warning(stage: str, exc: BaseException) -> None:
    LOGGER.exception("Logger finalization step failed during %s", stage, exc_info=exc)
    try:
        state = read_session_state(default={})
        payload = dict(state) if isinstance(state, dict) else {}
        warnings = list(payload.get("finalization_warnings") or [])
        warnings.append({
            "stage": str(stage or "finalization"),
            "error": str(exc),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        payload["finalization_warnings"] = warnings[-8:]
        payload["logger_finalization_warning"] = str(stage or "finalization")
        if payload:
            write_logger_heartbeat_payload({
                **dict(payload),
                "worker_kind": "logger",
                "heartbeat_at": time.time(),
                "logger_finalization_warning": str(stage or "finalization"),
            })
    except Exception:
        LOGGER.exception("Failed persisting logger finalization warning for %s", stage)

def _run_finalization_step(stage: str, func, *args, **kwargs):
    try:
        return True, func(*args, **kwargs)
    except Exception as exc:
        _record_finalization_warning(stage, exc)
        return False, None
