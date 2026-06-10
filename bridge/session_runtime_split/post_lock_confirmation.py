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

def _history_or_archive_pending_recent(self, state: Optional[Dict[str, Any]], *, now: float, elapsed: Optional[float]) -> bool:
    data = state if isinstance(state, dict) else {}
    history_pending = bool(getattr(self, "_history_sync_pending", False))
    archive_pending = bool(data.get("archive_pending") or data.get("archive_requested"))
    if not history_pending and not archive_pending:
        return False
    if history_pending:
        started_at = float(getattr(self, "_history_sync_started_at", 0.0) or 0.0)
        hard_deadline = float(getattr(self, "_history_sync_hard_deadline", 0.0) or 0.0)
        if hard_deadline and now < hard_deadline:
            return True
        if started_at and (now - started_at) < PASSIVE_FINALIZATION_RECOVERY_MAX_SECONDS:
            return True
    if archive_pending and (elapsed is None or elapsed < PASSIVE_FINALIZATION_RECOVERY_MAX_SECONDS):
        return True
    return False

def detect_stale_passive_finalization(self, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    facade = _facade()
    data = state if isinstance(state, dict) else self._active_state_for_current_user()
    data = data if isinstance(data, dict) else {}
    now = facade.time.time()
    if not data:
        return {"stale": False, "reason": "no_state"}
    if not _is_passive_auto_enrollment_state(data):
        return {"stale": False, "reason": "not_passive_auto_enrollment"}
    if not bool(data.get("active")):
        return {"stale": False, "reason": "not_active"}
    if str(data.get("session_kind") or "").strip().lower() != "enrollment":
        return {"stale": False, "reason": "not_enrollment"}
    if self._session_flow(data) != "enrollment_active":
        return {"stale": False, "reason": "flow_not_enrollment_active"}
    if not bool(data.get("auto_enrollment_finalizing")):
        return {"stale": False, "reason": "not_finalizing"}
    if bool(getattr(self, "_training_in_progress", False)):
        return {"stale": False, "reason": "training_active"}
    if bool(getattr(self, "_pending_logger_start", False)):
        return {"stale": False, "reason": "logger_start_pending"}
    if _session_logger_process_alive(self):
        return {"stale": False, "reason": "logger_process_alive"}
    elapsed = _passive_finalization_elapsed_seconds(self, data)
    if _history_or_archive_pending_recent(self, data, now=now, elapsed=elapsed):
        return {"stale": False, "reason": "archive_pending", "elapsed_finalizing_seconds": elapsed}
    if elapsed is None:
        return {"stale": False, "reason": "finalization_observed_grace", "elapsed_finalizing_seconds": None}
    if elapsed < PASSIVE_FINALIZATION_RECOVERY_GRACE_SECONDS:
        return {"stale": False, "reason": "finalization_grace", "elapsed_finalizing_seconds": elapsed}
    return {
        "stale": True,
        "reason": "stale_finalization_recovered",
        "elapsed_finalizing_seconds": elapsed,
        "session_id": str(data.get("session_id") or ""),
    }

def _safe_recovery_timestamp(now: float) -> str:
    try:
        return _facade().time.strftime("%Y-%m-%d %H:%M:%S", _facade().time.localtime(now))
    except (AttributeError, TypeError, ValueError, OSError):
        return str(now)

def _write_passive_recovery_metadata_marker(self, state: Dict[str, Any], *, recovered_at: float, recovered_at_text: str) -> bool:
    archive_path = str(state.get("archive_path") or "").strip()
    if not archive_path:
        return False
    facade = _facade()
    try:
        archive_real = facade.os.path.realpath(archive_path)
        sessions_root = facade.os.path.realpath(facade.sessions_dir())
        if facade.os.path.commonpath([archive_real, sessions_root]) != sessions_root:
            LOGGER.warning("Refusing stale passive recovery metadata write outside sessions root: %s", archive_path)
            return False
        metadata_path = facade.os.path.join(archive_real, "metadata.json")
        if not facade.os.path.exists(metadata_path):
            return False
        with open(metadata_path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            LOGGER.warning("Refusing stale passive recovery metadata write for non-object metadata: %s", metadata_path)
            return False
        loaded.update(
            {
                "auto_enrollment_recovery_reason": "stale_finalization_recovered",
                "auto_enrollment_recovered_after_restart": True,
                "auto_enrollment_recovered_at": recovered_at,
                "auto_enrollment_recovered_at_text": recovered_at_text,
                "auto_enrollment_stop_reason": "stale_finalization_recovered",
                "archive_status": loaded.get("archive_status") or "recovered_incomplete",
                "training_eligible": False,
            }
        )
        from security import atomic_write_text, save_metadata_hash

        atomic_write_text(metadata_path, json.dumps(loaded, ensure_ascii=False, indent=2))
        save_metadata_hash(metadata_path)
        return True
    except (OSError, json.JSONDecodeError, TypeError, ValueError, ImportError) as exc:
        LOGGER.warning("Failed writing stale passive finalization recovery metadata marker: %s", exc)
        return False

def _emit_passive_recovery_signals(self) -> None:
    for name in (
        "autoEnrollmentChanged",
        "modelReadinessChanged",
        "runtimeStateChanged",
        "statusChanged",
        "controlsChanged",
        "sessionsChanged",
        "dashboardStateChanged",
    ):
        signal = getattr(self, name, None)
        if signal is not None and hasattr(signal, "emit"):
            try:
                signal.emit()
            except (RuntimeError, TypeError):
                LOGGER.debug("Failed emitting %s after passive finalization recovery", name, exc_info=True)

def recover_stale_passive_auto_enrollment_finalization(self, state: Optional[Dict[str, Any]] = None, *, source: str = "refresh") -> bool:
    facade = _facade()
    data = state if isinstance(state, dict) else self._active_state_for_current_user()
    data = dict(data) if isinstance(data, dict) else {}
    detection = detect_stale_passive_finalization(self, data)
    if not bool(detection.get("stale")):
        return False
    now = facade.time.time()
    now_text = _safe_recovery_timestamp(now)
    recovered = dict(data)
    recovered.update(
        {
            "active": False,
            "status": "recovered_incomplete",
            "decision": recovered.get("decision") or "interrupted",
            "final_decision": recovered.get("final_decision") or "interrupted",
            "archive_label": recovered.get("archive_label") or "interrupted",
            "archive_status": recovered.get("archive_status") or "recovered_incomplete",
            "auto_enrollment_finalizing": False,
            "auto_enrollment_stop_requested": False,
            "stop_requested": False,
            "archive_requested": False,
            "archive_pending": False,
            "auto_enrollment_recovery_reason": "stale_finalization_recovered",
            "auto_enrollment_recovered_after_restart": True,
            "auto_enrollment_recovered_at": now,
            "auto_enrollment_recovered_at_text": now_text,
            "auto_enrollment_stop_reason": "stale_finalization_recovered",
            "training_eligible": False,
            "logger_ready": False,
            "monitor_ready": False,
        }
    )
    facade.write_session_state(recovered)
    metadata_marked = _write_passive_recovery_metadata_marker(self, recovered, recovered_at=now, recovered_at_text=now_text)
    self._runtime_state = recovered
    self._passive_auto_enrollment_finalizing = False
    self._last_passive_auto_enrollment_finalize_reason = "stale_finalization_recovered"
    self._last_passive_auto_enrollment_block_reason = "stale_finalization_recovered"
    self._active_live_session_dir = None
    setattr(self, "_passive_finalization_observed_signature", "")
    setattr(self, "_passive_finalization_observed_since", 0.0)
    try:
        self._clear_history_archive_watch()
    except AttributeError:
        setattr(self, "_history_sync_pending", False)
    facade.clear_stop("monitor")
    if self._current_user:
        facade.clear_stop(self._logger_key())
    facade.invalidate_session_discovery_cache()
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        message = "Recovered stale passive Auto Enrollment finalization from manual stop" if source == "manual_stop" else "Recovered stale passive Auto Enrollment finalization"
        debug(
            "auto_enrollment",
            message,
            payload={**detection, "source": str(source or "refresh"), "metadata_marked": bool(metadata_marked)},
            level="warn",
        )
    set_status = getattr(self, "_set_status", None)
    if callable(set_status):
        set_status(self._t("passive_finalization_recovered"), "info")
    refresh_timer = getattr(self, "_update_refresh_timer", None)
    if callable(refresh_timer):
        refresh_timer(force=True)
    _emit_passive_recovery_signals(self)
    _request_refresh(self, "auto_enrollment:stale_finalization_recovered", True)
    return True

def _debug_skip_duplicate_passive_finalization(self, *, reason: str, state: Optional[Dict[str, Any]] = None) -> None:
    debug = getattr(self, "_debug_trace", None)
    if not callable(debug):
        return
    now = _facade().time.time()
    elapsed = _passive_finalization_elapsed_seconds(self, state if isinstance(state, dict) else getattr(self, "_runtime_state", {}))
    session_id = ""
    if isinstance(state, dict):
        session_id = str(state.get("session_id") or "")
    key = f"{session_id}:{reason or 'already_finalizing'}"
    last_key = str(getattr(self, "_last_passive_duplicate_finalization_log_key", "") or "")
    last_at = float(getattr(self, "_last_passive_duplicate_finalization_log_at", 0.0) or 0.0)
    repeated = bool(key == last_key and (now - last_at) < PASSIVE_FINALIZATION_ALREADY_LOG_INTERVAL_SECONDS)
    if not repeated:
        setattr(self, "_last_passive_duplicate_finalization_log_key", key)
        setattr(self, "_last_passive_duplicate_finalization_log_at", now)
    debug(
        "auto_enrollment",
        "Skipping passive Auto Enrollment finalization because session is already finalizing",
        payload={"reason": str(reason or "already_finalizing"), "elapsed_finalizing_seconds": elapsed},
        level="debug" if repeated else "info",
    )
