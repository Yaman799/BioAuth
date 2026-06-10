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

def _terminal_protected_session_state(self, state: Optional[Dict[str, Any]], *, reason: str) -> Dict[str, Any]:
    facade = _facade()
    current = dict(state or {}) if isinstance(state, dict) else {}
    if not current:
        try:
            loaded = facade.read_session_state(default={})
            current = dict(loaded) if isinstance(loaded, dict) else {}
        except Exception:
            current = {}
    now = facade.time.time()
    stopped_at_text = facade.time.strftime("%Y-%m-%d %H:%M:%S", facade.time.localtime(now))
    user_id = str((getattr(self, "_current_user", {}) or {}).get("user_id") or current.get("user_id") or "")
    live_dir = str(current.get("live_session_dir") or getattr(self, "_active_live_session_dir", "") or "").strip()
    terminal = dict(current)
    terminal.update({
        "active": False,
        "session_state": "stopped",
        "flow": "idle",
        "status": "stopped",
        "runtime_status": "idle",
        "decision": "stopped",
        "final_decision": str(current.get("final_decision") or "stopped"),
        "stop_reason": str(reason or "user_requested"),
        "stopped_at": now,
        "stopped_at_text": stopped_at_text,
        "stop_requested": False,
        "logger_ready": False,
        "monitor_ready": False,
        "awaiting_evidence": False,
        "monitor_holding": False,
        "restriction_active": False,
        "pending_monitor_start": False,
        "runtime_decision": "",
        "runtime_diag_code": "",
        "runtime_diag_reason": "",
        "runtime_diag_summary": "",
        "runtime_recent_decisions": [],
        "runtime_recent_risks": [],
        "runtime_recent_ages_sec": [],
        "runtime_transition_status": "stopped",
        "runtime_transition_active": False,
        "runtime_transition_recent_windows": 0,
        "runtime_transition_recent_settled_windows": 0,
        "runtime_transition_strength": 0.0,
        "runtime_window_count": 0,
        "runtime_warning_count": 0,
        "runtime_top_risky_windows": [],
        "runtime_last_window_diag": {},
        "runtime_window_diag_summary": "",
        "runtime_diagnostics": {},
        "runtime_locking_allowed": False,
        "runtime_lock_suppressed_for_sec": 0.0,
        "runtime_legit_streak": 0,
        "auto_resume_pending": False,
        "resume_after_unlock": False,
        "return_verification": False,
        "resume_reason": "",
        "app_locked": False,
        "screen_locked": False,
        "forced_stop": False,
        "lockRequested": False,
        "lockAttempted": False,
        "lockSucceeded": False,
        "windowsLockRequested": False,
        "windowsLockAttempted": False,
        "windowsLockSucceeded": False,
        "postLockConfirmationPending": False,
        "postLockConfirmationPromptAfterUnlock": False,
        "postLockConfirmationEventId": "",
        "postLockConfirmationEventSessionId": "",
        "feedback_prompt": {},
    })
    if user_id:
        terminal["user_id"] = user_id
    if live_dir:
        terminal["live_session_dir"] = live_dir
    terminal.setdefault("session_kind", "protected")
    return terminal

def _write_terminal_live_session_marker(state: Dict[str, Any]) -> str:
    facade = _facade()
    live_dir = str((state or {}).get("live_session_dir") or "").strip()
    if not live_dir:
        return ""
    try:
        facade.os.makedirs(live_dir, exist_ok=True)
        marker_path = facade.os.path.join(live_dir, "session_terminal_state.json")
        payload = {
            "session_state": state.get("session_state"),
            "flow": state.get("flow"),
            "runtime_status": state.get("runtime_status"),
            "decision": state.get("decision"),
            "stop_reason": state.get("stop_reason"),
            "stopped_at": state.get("stopped_at"),
            "stopped_at_text": state.get("stopped_at_text"),
            "session_id": state.get("session_id"),
            "run_id": state.get("run_id"),
            "user_id": state.get("user_id"),
            "session_kind": state.get("session_kind"),
        }
        tmp_path = marker_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        facade.os.replace(tmp_path, marker_path)
        return marker_path
    except Exception:
        LOGGER.debug("Failed writing protected session terminal marker", exc_info=True)
        return ""
