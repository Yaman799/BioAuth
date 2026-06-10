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

def merge_worker_heartbeats_into_state(self, state: Optional[Dict[str, Any]] = None, *, persist: bool = False) -> Dict[str, Any]:
    """Merge worker heartbeat files into the coordinator-owned runtime state.

    Logger/monitor workers are no longer allowed to write session_state.json in
    the protected runtime.  This helper is called from bridge reads/refreshes and
    is the only place where worker facts are overlaid onto the authoritative
    state.
    """
    facade = _facade()
    merged: Dict[str, Any] = dict(state or {}) if isinstance(state, dict) else {}
    if not merged and not getattr(self, "_current_user", None):
        return merged
    if _is_terminal_protected_state(merged):
        # Commercial-Core-22O: terminal/stopped protected state is authoritative.
        # Stale worker heartbeat files from a previously closed UI must not revive
        # it back into protected_starting/protected_active.
        return merged
    logger_hb = _read_matching_worker_heartbeat(self, "logger", merged)
    monitor_hb = _read_matching_worker_heartbeat(self, "monitor", merged)
    lock_handoff_hb = _lock_handoff_heartbeat(logger_hb, monitor_hb)
    if lock_handoff_hb:
        return _merge_lock_handoff_worker_heartbeat(self, merged, lock_handoff_hb, persist=persist)
    changed = False
    now = time.time()
    technical_failure = bool(merged.get("technical_failure") or merged.get("monitor_failed") or merged.get("logger_failed"))

    if logger_hb:
        logger_age = _heartbeat_age_sec(logger_hb)
        merged["logger_heartbeat_age_sec"] = round(logger_age, 3)
        merged["logger_heartbeat_source"] = "worker_heartbeat"
        for key in (
            "session_id", "run_id", "user_id", "session_kind", "live_session_dir", "logger_pid",
            "logger_heartbeat_at", "logger_heartbeat_at_text", "keyboard_event_count", "mouse_event_count",
            "keyboard_rows", "mouse_rows", "mouse_throttle", "logger_finalized", "logger_finalized_at",
            "archive_path", "archived", "archive_label", "archive_group", "final_bucket",
            "training_eligible", "stop_reason", "finalization_warnings",
        ):
            if key in logger_hb:
                merged[key] = logger_hb.get(key)
                changed = True
        if not technical_failure:
            merged["active"] = bool(logger_hb.get("active", merged.get("active", True)))
            merged["logger_ready"] = bool(logger_hb.get("logger_ready", True))
            if not merged.get("status") or str(merged.get("status")).strip().lower() in {"starting", "logger_unavailable"}:
                merged["status"] = str(logger_hb.get("status") or "ok")
            changed = True

    if monitor_hb:
        monitor_age = _heartbeat_age_sec(monitor_hb)
        merged["monitor_heartbeat_age_sec"] = round(monitor_age, 3)
        merged["monitor_heartbeat_source"] = "worker_heartbeat"
        for key, value in monitor_hb.items():
            if key in {"_integrity"}:
                continue
            if key in {"active", "logger_ready"}:
                continue
            if technical_failure and key in {"status", "runtime_status", "decision", "risk", "avg_risk", "monitor_ready"}:
                continue
            merged[key] = value
            changed = True
        if not technical_failure:
            merged.setdefault("mode", "monitored")
            merged.setdefault("source", "monitor")
            merged["monitor_ready"] = bool(monitor_hb.get("monitor_ready", merged.get("monitor_ready", False)))
            changed = True

    if changed:
        try:
            from bioauth_runtime.supervisor.heartbeat_store import normalize_protected_startup_ready_state

            normalized, normalized_changed = normalize_protected_startup_ready_state(merged)
            if normalized_changed:
                merged = normalized
                changed = True
        except Exception:
            LOGGER.debug("Failed normalizing protected startup readiness state", exc_info=True)

    if changed:
        merged["worker_heartbeat_merge_at"] = now
        merged["worker_heartbeat_single_writer"] = True
        if persist:
            try:
                facade.write_session_state(merged)
            except Exception:
                LOGGER.debug("Failed persisting merged worker heartbeat state", exc_info=True)
    return merged


def _lock_handoff_heartbeat(logger_hb: Dict[str, Any], monitor_hb: Dict[str, Any]) -> Dict[str, Any]:
    """Return the worker heartbeat that carries a lock/resume handoff."""
    for payload in (monitor_hb, logger_hb):
        data = payload if isinstance(payload, dict) else {}
        if not data:
            continue
        if _heartbeat_payload_is_lock_handoff(data):
            return dict(data)
    return {}


def _heartbeat_payload_is_lock_handoff(data: Dict[str, Any]) -> bool:
    """Detect lock-controller handoff fields published through worker heartbeat."""
    if not isinstance(data, dict) or not data:
        return False
    status_values = {
        str(data.get("status") or "").strip().lower(),
        str(data.get("runtime_status") or "").strip().lower(),
        str(data.get("session_state") or "").strip().lower(),
    }
    explicit = bool(data.get("lock_controller_handoff") or data.get("lock_handoff_id"))
    resume_pending = bool(data.get("auto_resume_pending") or data.get("resume_after_unlock") or "resume_pending" in status_values)
    forced_lock = bool(data.get("forced_stop") or data.get("app_locked") or data.get("screen_locked") or data.get("protected_action_requested"))
    expected_exit = bool(data.get("forced_stop_expected_monitor_exit") or data.get("monitor_exit_expected"))
    final_intruder = str(data.get("final_decision") or data.get("archive_label") or data.get("decision") or "").strip().lower() == "intruder"
    return bool(explicit or expected_exit or (resume_pending and forced_lock) or (final_intruder and resume_pending))


def _merge_lock_handoff_worker_heartbeat(self, state: Dict[str, Any], heartbeat: Dict[str, Any], *, persist: bool = False) -> Dict[str, Any]:
    """Preserve inactive lock handoff over stale active logger heartbeats.

    After the monitor requests Windows lock it can only publish the terminal
    state through its heartbeat.  The logger may still be alive briefly and
    publish active=True.  That active logger heartbeat must not revive the
    session or create a repeated lock loop.
    """
    facade = _facade()
    merged: Dict[str, Any] = dict(state or {}) if isinstance(state, dict) else {}
    hb = dict(heartbeat or {})
    now = time.time()
    for key, value in hb.items():
        if key in {"_integrity"}:
            continue
        merged[key] = value
    merged.update({
        "active": False,
        "session_state": "resume_pending",
        "flow": "protected_forced_stop",
        "status": "resume_pending",
        "runtime_status": "resume_pending",
        "runtime_decision": merged.get("runtime_decision") or merged.get("decision") or "intruder",
        "decision": merged.get("decision") or "intruder",
        "final_decision": merged.get("final_decision") or "intruder",
        "archive_label": merged.get("archive_label") or "intruder",
        "final_bucket": merged.get("final_bucket") or "rejected",
        "forced_stop": True,
        "protected_action_requested": True,
        "auto_resume_pending": True,
        "resume_after_unlock": True,
        "forced_stop_expected_monitor_exit": True,
        "monitor_exit_expected": True,
        "technical_failure": False,
        "logger_failed": False,
        "monitor_failed": False,
        "risk_engine_stopped": False,
        "process_pair_failed": False,
        "worker_heartbeat_lock_handoff_preserved": True,
        "worker_heartbeat_merge_at": now,
        "worker_heartbeat_single_writer": True,
    })
    if not merged.get("resume_reason"):
        merged["resume_reason"] = "intruder_lock"
    if not merged.get("stop_reason"):
        merged["stop_reason"] = "monitor_intruder"
    try:
        from bioauth_runtime.monitor_worker.decision_engine import merge_runtime_decision_payload

        merged = merge_runtime_decision_payload(merged)
    except Exception:
        LOGGER.debug("Failed merging runtime decision payload for lock handoff heartbeat", exc_info=True)
    if persist:
        try:
            facade.write_session_state(merged)
        except Exception:
            LOGGER.debug("Failed persisting lock handoff heartbeat state", exc_info=True)
    return merged

def _effective_production_ready(self) -> bool:
    helper = getattr(self, "_effective_production_ready", None)
    if callable(helper):
        try:
            return bool(helper())
        except (TypeError, RuntimeError, ValueError):
            LOGGER.debug("Failed resolving effective production readiness; falling back to real profile readiness", exc_info=True)
    profile = getattr(self, "_profile", {}) if isinstance(getattr(self, "_profile", None), dict) else {}
    return bool(profile.get("production_ready"))

def _developer_production_ready_simulation_active(self) -> bool:
    helper = getattr(self, "_developer_production_ready_simulation_active", None)
    if callable(helper):
        try:
            return bool(helper())
        except (TypeError, RuntimeError, ValueError):
            LOGGER.debug("Failed resolving developer production-ready simulation state", exc_info=True)
    return False

def _current_safe_user(self) -> str:
    try:
        safe = str(self._safe_user() or "").strip()
    except Exception:
        safe = ""
    if not safe:
        try:
            facade = _facade()
            safe = facade.slugify_username((getattr(self, "_current_user", {}) or {}).get("user_id", "") or "")
        except Exception:
            safe = ""
    return safe or "user"

def _call_shadow_identity_helper(self, helper_name: str, fallback_prefix: str) -> str:
    helper = getattr(self, helper_name, None)
    if callable(helper):
        try:
            value = str(helper() or "").strip()
            if value:
                return value
        except Exception:
            LOGGER.debug("Failed resolving %s; using fallback shadow identity", helper_name, exc_info=True)
    return f"{fallback_prefix}_{_current_safe_user(self)}"

def _shadow_logger_process_key(self) -> str:
    return _call_shadow_identity_helper(self, "_shadow_logger_process_key", "shadow_logger_user")

def _shadow_monitor_process_key(self) -> str:
    return _call_shadow_identity_helper(self, "_shadow_monitor_process_key", "shadow_monitor_user")

def _shadow_logger_stop_control_name(self) -> str:
    return _call_shadow_identity_helper(self, "_shadow_logger_stop_control_name", "shadow_logger_user")

def _shadow_monitor_stop_control_name(self) -> str:
    return _call_shadow_identity_helper(self, "_shadow_monitor_stop_control_name", "shadow_monitor_user")

def _clear_shadow_stop_controls(self) -> None:
    facade = _facade()
    for name in (_shadow_logger_stop_control_name(self), _shadow_monitor_stop_control_name(self)):
        try:
            facade.clear_stop(name)
        except Exception:
            LOGGER.debug("Failed clearing shadow stop control %s", name, exc_info=True)

def _request_shadow_stop_controls(self) -> None:
    facade = _facade()
    for name in (_shadow_logger_stop_control_name(self), _shadow_monitor_stop_control_name(self)):
        try:
            facade.request_stop(name)
        except Exception:
            LOGGER.exception("Failed requesting shadow stop control %s", name)
            raise

def _state_is_shadow_evidence(state: Optional[Dict[str, Any]] = None) -> bool:
    state = state if isinstance(state, dict) else {}
    return str(state.get("session_kind") or state.get("runtime_mode") or state.get("mode") or "").strip().lower() == SHADOW_EVIDENCE_SESSION_KIND

def _pending_logger_kind(self) -> str:
    return str(getattr(self, "_pending_logger_session_kind", "") or "").strip().lower()

def _shadow_logger_start_pending(self) -> bool:
    return bool(getattr(self, "_pending_logger_start", False)) and _pending_logger_kind(self) in SHADOW_PENDING_LOGGER_SESSION_KINDS

def _normal_logger_start_pending(self) -> bool:
    return bool(getattr(self, "_pending_logger_start", False)) and not _shadow_logger_start_pending(self)

def _normal_logger_process_key(self) -> str:
    for helper_name in ("_logger_process_key", "_logger_key"):
        key_fn = getattr(self, helper_name, None)
        if callable(key_fn):
            try:
                key = str(key_fn() or "").strip()
                if key:
                    return key
            except Exception:
                LOGGER.debug("Failed resolving %s; using explicit user fallback", helper_name, exc_info=True)
    return f"logger_user_{_current_safe_user(self)}"

def _normal_logger_process_running(self) -> bool:
    processes = getattr(self, "_running_processes", {})
    if not isinstance(processes, dict):
        return False
    return _process_is_alive(processes.get(_normal_logger_process_key(self)))

def _is_shadow_runtime_process_running(self) -> bool:
    """Return True only for exact hidden shadow runtime process identities.

    Normal UI state must never use substring matching or generic session flow
    to infer whether a user-facing logger or production monitor is active.
    """
    if not getattr(self, "_current_user", None):
        return False
    processes = getattr(self, "_running_processes", {})
    if not isinstance(processes, dict):
        return False
    for key in (_shadow_logger_process_key(self), _shadow_monitor_process_key(self)):
        if _process_is_alive(processes.get(key)):
            return True
    return False

def _has_stale_shadow_state(self, state: Optional[Dict[str, Any]] = None) -> bool:
    state = state if isinstance(state, dict) else None
    if state is None:
        try:
            state = self._active_state_for_current_user()
        except Exception:
            state = {}
    shadow_state = _state_is_shadow_evidence(state) or str((state or {}).get("retry_handoff_state") or "").strip().lower().startswith("shadow_evidence_")
    shadow_pending = bool(getattr(self, "_pending_shadow_evidence_monitor_start", False))
    shadow_pending = shadow_pending or _shadow_logger_start_pending(self)
    if not (shadow_state or shadow_pending):
        return False
    return not _is_shadow_runtime_process_running(self)
