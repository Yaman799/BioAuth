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

def archive_live_session() -> None:
    global _archived
    if _archived:
        return

    archive_decision, decision_source = _determine_archive_decision()
    normalized_decision = _normalize_label(archive_decision) or "interrupted"
    archive_group = "authorized" if normalized_decision == "legit" else "rejected"
    training_eligible = _is_training_eligible(normalized_decision)
    if _is_shadow_evidence_session():
        archive_group = "shadow_evidence"
        training_eligible = False
    stop_reason = _current_stop_reason()
    archive_warnings = []

    session_archive = os.path.join(_archive_root_for_decision(normalized_decision), _archive_folder_name(normalized_decision))
    archive_available = True
    try:
        os.makedirs(session_archive, exist_ok=True)
    except Exception as exc:
        archive_available = False
        session_archive = ""
        archive_warnings.append({"stage": "archive_prepare", "error": str(exc)})
        _record_finalization_warning("archive_prepare", exc)

    for stage, target, header in (
        ("archive_compact_keyboard", KEYBOARD_FILE, KB_HEADER),
        ("archive_compact_mouse", MOUSE_FILE, MS_HEADER),
    ):
        ok, _ = _run_finalization_step(stage, compact_chunks, target, header)
        if not ok:
            archive_warnings.append({"stage": stage, "error": "compact_failed"})

    copied_any = False
    if archive_available and session_archive:
        if os.path.exists(KEYBOARD_FILE):
            ok, _ = _run_finalization_step("archive_copy_keyboard", shutil.copy2, KEYBOARD_FILE, os.path.join(session_archive, "keyboard_log.csv"))
            copied_any = copied_any or ok
            if not ok:
                archive_warnings.append({"stage": "archive_copy_keyboard", "error": "copy_failed"})
        if os.path.exists(MOUSE_FILE):
            ok, _ = _run_finalization_step("archive_copy_mouse", shutil.copy2, MOUSE_FILE, os.path.join(session_archive, "mouse_log.csv"))
            copied_any = copied_any or ok
            if not ok:
                archive_warnings.append({"stage": "archive_copy_mouse", "error": "copy_failed"})

    keyboard_row_count = _count_rows(KEYBOARD_FILE, KB_HEADER)
    mouse_row_count = _count_rows(MOUSE_FILE, MS_HEADER)

    meta = {
        "session_id": SESSION_ID,
        "command_label": ARGS["session_label"],
        "archive_label": normalized_decision,
        "final_decision": normalized_decision,
        "archive_group": archive_group,
        "bucket": archive_group,
        "mode": _session_mode(),
        "decision_source": decision_source,
        "stop_reason": stop_reason,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": SESSION_STARTED_AT,
        "started_at_text": SESSION_STARTED_AT_TEXT,
        "duration_seconds": max(0, int(time.time() - SESSION_STARTED_AT)),
        "keyboard_rows": keyboard_row_count,
        "mouse_rows": mouse_row_count,
        **_mouse_throttle_counters_snapshot(),
        "mouse_throttle": _mouse_throttle_counters_snapshot(),
        **_capture_counters_snapshot(),
        **_listener_health_snapshot(),
        **_control_status_snapshot(),
        "keyboard_bytes": os.path.getsize(KEYBOARD_FILE) if os.path.exists(KEYBOARD_FILE) else 0,
        "mouse_bytes": os.path.getsize(MOUSE_FILE) if os.path.exists(MOUSE_FILE) else 0,
        "training_eligible": training_eligible,
        "feature_capture_version": "v2_windowed",
    }
    meta.update(metadata_tags_from_environment(keyboard_rows=keyboard_row_count, mouse_rows=mouse_row_count))
    meta.update(_shadow_evidence_tags())
    if not ARGS["legacy"]:
        meta.update(
            {
                "user_id": ARGS["safe_user"],
                "session_kind": ARGS["session_kind"],
                "privacy_mode": "hashed_keys",
                "started_at": SESSION_STARTED_AT,
                "started_at_text": SESSION_STARTED_AT_TEXT,
                "host_boot_marker": SESSION_HOST_BOOT_MARKER,
                "host_boot_time": SESSION_HOST_BOOT_TIME,
            }
        )

    previous_state = read_session_state(default={}) if not ARGS["legacy"] else {}
    previous_state = previous_state if isinstance(previous_state, dict) else {}

    latest_feedback_label = str(previous_state.get("latest_feedback_label") or "").strip().lower()
    if latest_feedback_label:
        meta["feedback_label"] = latest_feedback_label
        meta["feedback_timestamp"] = previous_state.get("latest_feedback_timestamp")
        meta["feedback_policy_version"] = str(((previous_state.get("feedback_prompt") or {}) if isinstance(previous_state.get("feedback_prompt"), dict) else {}).get("policy_version") or "phase4-feedback-v1")
        meta["feedback_shadow_only"] = latest_feedback_label == "verified_legit_after_warning"
        if latest_feedback_label in {"verified_legit_after_warning", "confirmed_intruder", "user_ignored_feedback"}:
            meta["training_eligible"] = False
            training_eligible = False

    evidence_meta = previous_state.get("incident_evidence") if isinstance(previous_state.get("incident_evidence"), dict) else None
    if evidence_meta:
        evidence_record_path = os.path.join(str(previous_state.get("incident_evidence_dir") or evidence_meta.get("incident_directory") or ""), "incident.json")
        updated_evidence_meta = update_incident_record(
            evidence_record_path,
            archive_status="archived",
            archive_path=session_archive,
        ) if evidence_record_path else {}
        if isinstance(updated_evidence_meta, dict) and updated_evidence_meta:
            evidence_meta = updated_evidence_meta
        meta["incident_evidence"] = evidence_meta
        meta["incident_evidence_status"] = previous_state.get("incident_evidence_status")
        meta["incident_evidence_saved_count"] = previous_state.get("incident_evidence_saved_count")
        meta["incident_evidence_dir"] = previous_state.get("incident_evidence_dir")

    metadata_written = False
    if archive_available and session_archive:
        metadata_path = os.path.join(session_archive, "metadata.json")
        ok, _ = _run_finalization_step("archive_write_metadata", atomic_write_text, metadata_path, json.dumps(meta, ensure_ascii=False, indent=2))
        metadata_written = bool(ok)
        if not ok:
            archive_warnings.append({"stage": "archive_write_metadata", "error": "write_failed"})
        if metadata_written:
            ok, _ = _run_finalization_step("archive_hash_metadata", save_metadata_hash, metadata_path)
            if not ok:
                archive_warnings.append({"stage": "archive_hash_metadata", "error": "hash_failed"})
    archived_ok = bool(archive_available and session_archive and (metadata_written or copied_any))

    state_payload = {
        "session_id": SESSION_ID,
        "mode": "monitored" if meta["mode"] == "monitored" else "standalone",
        "decision": normalized_decision,
        "final_decision": normalized_decision,
        "active": False,
        "archived": archived_ok,
        "archive_label": normalized_decision,
        "archive_group": archive_group,
        "final_bucket": archive_group,
        "training_eligible": training_eligible,
        "stop_reason": stop_reason,
        "archive_path": session_archive if archived_ok else "",
        "user_id": ARGS["safe_user"],
        "session_kind": ARGS["session_kind"],
        "started_at": SESSION_STARTED_AT,
        "started_at_text": SESSION_STARTED_AT_TEXT,
        "host_boot_marker": SESSION_HOST_BOOT_MARKER,
        "host_boot_time": SESSION_HOST_BOOT_TIME,
        **_mouse_throttle_counters_snapshot(),
        "mouse_throttle": _mouse_throttle_counters_snapshot(),
        **_capture_counters_snapshot(),
        **_listener_health_snapshot(),
        **_control_status_snapshot(),
        "latest_feedback_label": previous_state.get("latest_feedback_label"),
        "latest_feedback_timestamp": previous_state.get("latest_feedback_timestamp"),
        "feedback_prompt": previous_state.get("feedback_prompt"),
        "forced_stop": previous_state.get("forced_stop", False),
        "app_locked": previous_state.get("app_locked", False),
        "screen_locked": previous_state.get("screen_locked", False),
        "decision_finalized": previous_state.get("decision_finalized", False),
        "monitor_holding": previous_state.get("monitor_holding", False),
        "restriction_active": previous_state.get("restriction_active", False),
        "auto_resume_pending": previous_state.get("auto_resume_pending", False),
        "resume_after_unlock": previous_state.get("resume_after_unlock", False),
        "resume_reason": previous_state.get("resume_reason"),
        "status": "resume_pending" if previous_state.get("auto_resume_pending") else previous_state.get("status"),
        "alert_title_key": previous_state.get("alert_title_key"),
        "alert_message_key": previous_state.get("alert_message_key"),
        "alert_title": previous_state.get("alert_title"),
        "alert_message": previous_state.get("alert_message"),
        "alert_token": previous_state.get("alert_token"),
        "monitor_ready": previous_state.get("monitor_ready", False),
        "monitor_failed": previous_state.get("monitor_failed", False),
        "technical_failure": previous_state.get("technical_failure", False),
        "incident_evidence": previous_state.get("incident_evidence"),
        "incident_evidence_status": previous_state.get("incident_evidence_status"),
        "incident_evidence_notice": previous_state.get("incident_evidence_notice"),
        "incident_evidence_saved_count": previous_state.get("incident_evidence_saved_count"),
        "incident_evidence_dir": previous_state.get("incident_evidence_dir"),
        "logger_failed": previous_state.get("logger_failed", False),
        "logger_error": previous_state.get("logger_error"),
        "monitor_error": previous_state.get("monitor_error"),
    }
    state_payload.update(_shadow_evidence_tags())
    if _is_shadow_evidence_session():
        state_payload.update({
            "archive_group": "shadow_evidence",
            "final_bucket": "shadow_evidence",
            "training_eligible": False,
            "app_locked": False,
            "screen_locked": False,
            "forced_stop": False,
            "monitor_holding": False,
            "restriction_active": False,
            "protected_sessions_available": False,
            "production_ready": False,
            "production_approval_allowed": False,
            "production_promotion_allowed": False,
            "shadow_isolation_reason_code": "shadow_evidence_hidden_logger_isolated",
        })
    if archive_warnings:
        state_payload["finalization_warnings"] = list(previous_state.get("finalization_warnings") or []) + archive_warnings

    _run_finalization_step("archive_write_logger_final_heartbeat", write_logger_heartbeat_payload, {
        **dict(state_payload),
        "worker_kind": "logger",
        "logger_ready": False,
        "logger_finalized": True,
        "logger_finalized_at": time.time(),
        "heartbeat_at": time.time(),
    })
    print(f"[Logger] Archived session at {session_archive or '<unavailable>'}", flush=True)
    _archived = True

def _queue_keyboard_row(row):
    try:
        _record_capture_event("keyboard", float(row[2]) if len(row) > 2 else None)
    except Exception:
        _record_capture_event("keyboard")
    with _buffer_lock:
        _keyboard_buffer.append(row)
        should_flush = len(_keyboard_buffer) >= MAX_BUFFER_ROWS
    if should_flush:
        _flush_event.set()
