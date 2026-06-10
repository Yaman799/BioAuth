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

def enforce_confirmed_intruder_event(
    self,
    *,
    state: Optional[Dict[str, Any]] = None,
    source: str = "backend_policy",
    reason_code: str = "confirmed_intruder",
    feedback_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Force the confirmed-intruder lifecycle from a backend-owned event.

    This is the bridge-side counterpart to monitor-confirmed enforcement. It is
    intentionally entered only from backend Python after an explicit user
    confirmation or backend policy decision; QML passes feedback intent only.
    """
    facade = _facade()
    if not self._current_user:
        return {"ok": False, "reason": "no_current_user"}
    current_state = state if isinstance(state, dict) else self._active_state_for_current_user()
    current_state = dict(current_state) if isinstance(current_state, dict) else {}
    if not current_state:
        return {"ok": False, "reason": "no_active_state"}
    if str(current_state.get("session_kind") or "").strip().lower() != "protected":
        return {"ok": False, "reason": "not_protected_session"}

    session_id = str(current_state.get("session_id") or "").strip() or f"manual-{facade.uuid.uuid4().hex[:8]}"
    reason_code = str(reason_code or "confirmed_intruder").strip() or "confirmed_intruder"
    source = str(source or "backend_policy").strip() or "backend_policy"
    enforcement_id = _intruder_enforcement_id(source=source, reason_code=reason_code, session_id=session_id)
    now = facade.time.time()
    now_text = facade.time.strftime("%Y-%m-%d %H:%M:%S", facade.time.localtime(now)) if hasattr(facade.time, "localtime") else str(now)
    feedback_record = dict(feedback_record or {})

    if _intruder_enforcement_already_applied(current_state, enforcement_id):
        updated = dict(current_state)
        if feedback_record:
            updated["latest_feedback_label"] = feedback_record.get("label") or updated.get("latest_feedback_label")
            updated["latest_feedback_timestamp"] = feedback_record.get("timestamp") or updated.get("latest_feedback_timestamp")
        updated["intruderEnforcementDuplicateIgnored"] = True
        updated["lastIntruderEnforcementDuplicateAt"] = now
        facade.write_session_state(updated)
        self._runtime_state = updated
        return {"ok": True, "already_enforced": True, "enforcement_id": enforcement_id, "state": updated}

    settings = _load_settings_for_enforcement()
    risk = _safe_int(current_state.get("risk"), 0)
    avg_risk = _safe_number(current_state.get("avg_risk"), 0.0)
    ml = _safe_int(current_state.get("ml"), 0)
    evidence_event = {
        "session_id": session_id,
        "user_id": self._current_user.get("user_id") or current_state.get("user_id") or "",
        "incident_type": "confirmed_intruder",
        "trigger_reason": reason_code,
        "risk": risk,
        "avg_risk": round(avg_risk, 2),
        "ml": ml,
        "source": source,
    }
    evidence_result = _capture_incident_evidence_for_enforcement(evidence_event, settings)
    lock_result = _lock_current_session_result_for_enforcement()
    lock_fields = _lock_result_fields(lock_result)
    screen_locked = bool(lock_fields.get("lockSucceeded") or lock_fields.get("windowsLockSucceeded"))
    incident_path = str(evidence_result.get("incident_path") or "") if isinstance(evidence_result, dict) else ""
    if incident_path:
        updated_payload = _update_incident_record_for_enforcement(
            incident_path,
            lock_status=_lock_status_for_incident(lock_fields),
            archive_status="pending",
        )
        if updated_payload:
            evidence_result["payload"] = updated_payload

    prompt = current_state.get("feedback_prompt") if isinstance(current_state.get("feedback_prompt"), dict) else {}
    updated = dict(current_state)
    updated.update(
        {
            "mode": "monitored",
            "active": True,
            "source": "bridge",
            "session_id": session_id,
            "user_id": current_state.get("user_id") or self._current_user.get("user_id"),
            "session_kind": "protected",
            "decision": "intruder",
            "model_decision": current_state.get("model_decision") or "intruder",
            "status": "resume_pending",
            "forced_stop": True,
            "app_locked": True,
            "screen_locked": screen_locked,
            "decision_finalized": True,
            "final_decision": "intruder",
            "archive_label": "intruder",
            "final_bucket": "rejected",
            "training_eligible": False,
            "stop_reason": reason_code,
            "monitor_holding": True,
            "restriction_active": True,
            "auto_resume_pending": True,
            "resume_after_unlock": True,
            "resume_reason": "intruder_lock",
            "archive_requested": True,
            "archive_request_reason": reason_code,
            "archive_requested_at": now,
            "runtime_confirmation_rule": reason_code,
            "runtime_diagnostic_code": reason_code,
            "runtime_diagnostic_reason": "The signed-in user confirmed this protected session is controlled by someone else.",
            "lastIntruderEnforcementReason": reason_code,
            "lastIntruderEnforcementSource": source,
            "lastIntruderEnforcementId": enforcement_id,
            "lastIntruderEnforcementAt": now,
            "lastIntruderEnforcementAtText": now_text,
            "lastIntruderEnforcementApplied": True,
            "intruderEnforcementDuplicateIgnored": False,
            "alert_code": "session_locked",
            "alert_title_key": "alert_lock_title",
            "alert_message_key": "alert_screen_lock_msg" if screen_locked else "alert_lock_msg",
            "alert_title": "",
            "alert_message": "",
            "alert_token": f"lock-{session_id}-{int(now)}",
            "feedback_prompt": {**dict(prompt or {}), "pending": False, "answered": True, "label": "confirmed_intruder", "answered_at": feedback_record.get("timestamp") or now_text},
            "latest_feedback_label": feedback_record.get("label") or updated.get("latest_feedback_label") or "confirmed_intruder",
            "latest_feedback_timestamp": feedback_record.get("timestamp") or updated.get("latest_feedback_timestamp") or now_text,
            "incident_evidence": evidence_result.get("payload") if isinstance(evidence_result, dict) else None,
            "incident_evidence_status": evidence_result.get("status") if isinstance(evidence_result, dict) else None,
            "incident_evidence_notice": _incident_notice(evidence_result),
            "incident_evidence_saved_count": _safe_int(evidence_result.get("saved_file_count") if isinstance(evidence_result, dict) else 0, 0),
            "incident_evidence_dir": evidence_result.get("incident_dir") if isinstance(evidence_result, dict) else "",
            "incident_evidence_id": evidence_result.get("incident_id") if isinstance(evidence_result, dict) else "",
            "incident_evidence_hashes_path": evidence_result.get("hashes_path") if isinstance(evidence_result, dict) else "",
            **lock_fields,
        }
    )
    if _demo_classic_protected_enabled():
        updated.update(
            {
                "active": False,
                "status": "resume_pending",
                "forced_stop": True,
                "auto_resume_pending": True,
                "resume_after_unlock": True,
                "resume_reason": "demo_classic_intruder_lock",
                "demo_classic_protected": True,
                "demo_classic_post_unlock_resume_pending": True,
                "demo_classic_stale_intruder_state": True,
                "demo_classic_stale_intruder_state_cleared": False,
            }
        )
    facade.write_session_state(updated)
    self._runtime_state = updated
    try:
        from metadata_core.production_evidence_pipeline import append_runtime_monitor_evidence_record

        append_runtime_monitor_evidence_record(
            user_id=str(current_state.get("user_id") or self._current_user.get("user_id") or ""),
            state={**updated, "confirmedIntruderAfterLock": True},
            runtime={},
            prediction={"final": updated.get("model_decision") or updated.get("decision") or "intruder"},
        )
    except Exception:
        # Evidence ledger writes are diagnostic-only and must never interrupt
        # backend-owned confirmed-intruder enforcement.
        pass

    self._clear_pending_logger_start()
    self._clear_pending_monitor_start()
    _request_stop_for_current_session(self)
    monitor_proc = getattr(self, "_running_processes", {}).get("monitor") if isinstance(getattr(self, "_running_processes", None), dict) else None
    if monitor_proc is not None:
        try:
            if monitor_proc.poll() is None:
                monitor_proc.terminate()
        except (AttributeError, OSError, ProcessLookupError):
            pass
    begin_watch = getattr(self, "_begin_history_archive_watch", None)
    if callable(begin_watch):
        begin_watch()
    try:
        facade.invalidate_session_discovery_cache()
    except Exception:
        LOGGER.debug("Failed invalidating session discovery cache after terminal stop.", exc_info=True)
    invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
    if callable(invalidate):
        invalidate()
    self._last_alert_signature = None
    refresh_timer = getattr(self, "_update_refresh_timer", None)
    if callable(refresh_timer):
        refresh_timer(force=True)
    return {
        "ok": True,
        "already_enforced": False,
        "enforcement_id": enforcement_id,
        "lock": lock_fields,
        "evidence_status": updated.get("incident_evidence_status"),
        "state": updated,
    }
