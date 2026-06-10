"""Extracted implementation section for `monitor_core/common.py`."""
from __future__ import annotations
import json
import logging
import os
import time
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Optional

def _load_runtime_model():
    facade = _facade()
    if facade.EXPECTED_USER:
        if _shadow_evidence_mode():
            return _load_shadow_evidence_candidate_bundle(facade.EXPECTED_USER)
        bundle = facade._load_user_runtime_bundle(facade.EXPECTED_USER)
        if isinstance(bundle, dict):
            return bundle
        return {
            "model": None,
            "metadata": None,
            "classifier": None,
            "metadata_file": None,
            "classifier_file": None,
        }
    return {
        "model": facade.load_model(),
        "metadata": facade.load_metadata(),
        "classifier": facade.load_classifier(),
        "metadata_file": None,
        "classifier_file": None,
    }

def _predict_runtime(runtime):
    facade = _facade()
    model = runtime.get("model") if isinstance(runtime, dict) else None
    if model is None:
        return {"final": "unknown", "raw": 0.0, "risk": 0, "ml": 0, "status": "model_unavailable", "window_count": 0}
    metadata = runtime.get("metadata") if isinstance(runtime, dict) else None
    classifier = runtime.get("classifier") if isinstance(runtime, dict) else None
    metadata_file = runtime.get("metadata_file") if isinstance(runtime, dict) else None
    classifier_file = runtime.get("classifier_file") if isinstance(runtime, dict) else None
    session_path = _current_live_session_dir(facade)
    live_input = _live_input_snapshot(session_path)
    prediction = facade.predict_from_session_details(
        model,
        session_path,
        metadata_file=metadata_file or None,
        classifier_file=classifier_file or None,
        metadata=metadata,
        classifier=classifier,
    )
    if isinstance(prediction, dict):
        prediction["live_input"] = live_input
        perf = dict(prediction.get("runtime_performance") or {})
        counts = dict(perf.get("counts") or {})
        counts.setdefault("live_keyboard_counter", int(live_input.get("keyboard_counter") or 0))
        counts.setdefault("live_mouse_counter", int(live_input.get("mouse_counter") or 0))
        counts.setdefault("live_keyboard_rows", int(live_input.get("keyboard_rows") or 0))
        counts.setdefault("live_mouse_rows", int(live_input.get("mouse_rows") or 0))
        perf["counts"] = counts
        prediction["runtime_performance"] = perf
    return prediction

def _current_live_session_dir(facade: Any) -> str:
    env_dir = str(os.environ.get("BIOAUTH_LIVE_SESSION_DIR") or "").strip()
    if env_dir:
        return env_dir
    try:
        state = facade.read_session_state(default={})
    except Exception:
        state = {}
    if isinstance(state, dict):
        state_dir = str(state.get("live_session_dir") or "").strip()
        if state_dir:
            return state_dir
    return str(getattr(facade, "LIVE_SESSION_DIR", "") or "")

def _live_input_snapshot(session_path: str) -> Dict[str, Any]:
    try:
        from bioauth_runtime.monitor_worker.live_input_reader import live_input_snapshot

        return live_input_snapshot(session_path)
    except Exception as exc:
        return {"live_session_dir": str(session_path or ""), "readable": False, "error": type(exc).__name__}

def _final_monitor_state(previous: Dict[str, Any], session_id: str, previous_decision: str | None, final_bucket: str) -> Dict[str, Any]:
    facade = _facade()
    shadow_mode = str(previous.get("session_kind") or "").strip().lower() == SHADOW_EVIDENCE_SESSION_KIND or _shadow_evidence_mode()
    return {
        "mode": SHADOW_EVIDENCE_SESSION_KIND if shadow_mode else "monitored",
        "active": False,
        "source": SHADOW_EVIDENCE_SOURCE if shadow_mode else "monitor",
        "evidence_source": SHADOW_EVIDENCE_SOURCE if shadow_mode else previous.get("evidence_source"),
        "runtime_mode": SHADOW_EVIDENCE_SESSION_KIND if shadow_mode else previous.get("runtime_mode"),
        "session_id": session_id,
        "user_id": previous.get("user_id") or facade.EXPECTED_USER_SLUG,
        "expected_user": facade.EXPECTED_USER_SLUG,
        "session_kind": previous.get("session_kind", "protected"),
        "risk": previous.get("risk"),
        "avg_risk": previous.get("avg_risk"),
        "raw_score": previous.get("raw_score"),
        "ml": previous.get("ml"),
        "status": previous.get("status"),
        "model_decision": previous.get("model_decision"),
        "warning_count": previous.get("warning_count"),
        "intruder_vote_count": previous.get("intruder_vote_count"),
        "evidence_samples": previous.get("evidence_samples"),
        "forced_stop": previous.get("forced_stop", False),
        "app_locked": previous.get("app_locked", False),
        "screen_locked": previous.get("screen_locked", False),
        "decision_finalized": previous.get("decision_finalized", False),
        "final_decision": previous_decision,
        "archive_label": previous.get("archive_label") or previous_decision,
        "final_bucket": final_bucket,
        "training_eligible": False if shadow_mode else previous.get("training_eligible", False),
        "excluded_from_positive_training": True if shadow_mode else previous.get("excluded_from_positive_training", False),
        "training_counts_toward_minimum": False if shadow_mode else previous.get("training_counts_toward_minimum", False),
        "metadata_trusted": False if shadow_mode else previous.get("metadata_trusted", False),
        "trust_level": "shadow_runtime" if shadow_mode else previous.get("trust_level", ""),
        "stop_reason": previous.get("stop_reason"),
        "monitor_holding": previous.get("monitor_holding", False),
        "restriction_active": previous.get("restriction_active", False),
        "auto_resume_pending": previous.get("auto_resume_pending", False),
        "resume_after_unlock": previous.get("resume_after_unlock", False),
        "resume_reason": previous.get("resume_reason"),
        "archive_requested": previous.get("archive_requested", False),
        "archive_request_reason": previous.get("archive_request_reason"),
        "lockRequested": previous.get("lockRequested", False),
        "lockAttempted": previous.get("lockAttempted", False),
        "lockSucceeded": previous.get("lockSucceeded", False),
        "lockErrorKind": previous.get("lockErrorKind", ""),
        "lockUnavailableReason": previous.get("lockUnavailableReason", ""),
        "windowsLockRequested": previous.get("windowsLockRequested", False),
        "windowsLockAttempted": previous.get("windowsLockAttempted", False),
        "windowsLockSucceeded": previous.get("windowsLockSucceeded", False),
        "windowsLockErrorKind": previous.get("windowsLockErrorKind", ""),
        "windowsLockUnavailableReason": previous.get("windowsLockUnavailableReason", ""),
        "lastIntruderEnforcementReason": previous.get("lastIntruderEnforcementReason", ""),
        "lastIntruderEnforcementSource": previous.get("lastIntruderEnforcementSource", ""),
        "lastIntruderEnforcementId": previous.get("lastIntruderEnforcementId", ""),
        "lastIntruderEnforcementAt": previous.get("lastIntruderEnforcementAt"),
        "postLockConfirmationPending": previous.get("postLockConfirmationPending", False),
        "postLockConfirmationPromptAfterUnlock": previous.get("postLockConfirmationPromptAfterUnlock", False),
        "postLockConfirmationEventId": previous.get("postLockConfirmationEventId", ""),
        "postLockConfirmationEventSessionId": previous.get("postLockConfirmationEventSessionId", ""),
        "postLockConfirmationReason": previous.get("postLockConfirmationReason", ""),
        "postLockConfirmationStage": previous.get("postLockConfirmationStage", ""),
        "postLockConfirmationUnavailableReason": previous.get("postLockConfirmationUnavailableReason", ""),
        "postLockConfirmationAnswered": previous.get("postLockConfirmationAnswered", False),
        "postLockConfirmationAnsweredAt": previous.get("postLockConfirmationAnsweredAt", ""),
        "postLockConfirmationAnswer": previous.get("postLockConfirmationAnswer", ""),
        "alert_title_key": previous.get("alert_title_key"),
        "alert_message_key": previous.get("alert_message_key"),
        "alert_title": previous.get("alert_title"),
        "alert_message": previous.get("alert_message"),
        "alert_token": previous.get("alert_token"),
        "started_at": previous.get("started_at"),
        "started_at_text": previous.get("started_at_text"),
        "monitor_ready": False,
        "monitor_failed": previous.get("monitor_failed", False),
        "technical_failure": previous.get("technical_failure", False),
        "awaiting_evidence": previous.get("awaiting_evidence", False),
        "monitor_error": previous.get("monitor_error"),
        "incident_evidence": previous.get("incident_evidence"),
        "incident_evidence_status": previous.get("incident_evidence_status"),
        "incident_evidence_notice": previous.get("incident_evidence_notice"),
        "incident_evidence_saved_count": previous.get("incident_evidence_saved_count"),
        "incident_evidence_dir": previous.get("incident_evidence_dir"),
    }
