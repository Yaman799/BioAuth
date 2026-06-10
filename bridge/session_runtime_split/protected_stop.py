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

def _carry_post_lock_confirmation_for_resume(previous: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(previous, dict) or not bool(previous.get("postLockConfirmationPending")):
        return {}
    if not bool(previous.get("windowsLockSucceeded") or previous.get("lockSucceeded") or previous.get("screen_locked")):
        return {}
    event_id = str(previous.get("postLockConfirmationEventId") or "").strip()
    if not event_id:
        return {}
    fields = {
        "postLockConfirmationPending": True,
        "postLockConfirmationPromptAfterUnlock": True,
        "postLockConfirmationEventId": event_id,
        "postLockConfirmationEventSessionId": str(previous.get("postLockConfirmationEventSessionId") or previous.get("session_id") or ""),
        "postLockConfirmationReason": str(previous.get("postLockConfirmationReason") or previous.get("runtime_confirmation_rule") or "warning_followup_lock"),
        "postLockConfirmationStage": "after_unlock_prompt_pending",
        "postLockConfirmationUnavailableReason": "",
        "postLockConfirmationAnswered": False,
        "postLockConfirmationAnsweredAt": "",
        "postLockConfirmationAnswer": "",
        "postLockConfirmationRisk": previous.get("risk"),
        "postLockConfirmationAvgRisk": previous.get("avg_risk"),
        "postLockConfirmationArchivePath": str(previous.get("archive_path") or ""),
        "lastIntruderEnforcementReason": str(previous.get("lastIntruderEnforcementReason") or previous.get("runtime_confirmation_rule") or "warning_followup_lock"),
        "lastIntruderEnforcementSource": str(previous.get("lastIntruderEnforcementSource") or "backend_policy"),
        "lastIntruderEnforcementId": str(previous.get("lastIntruderEnforcementId") or event_id),
        "lastIntruderEnforcementAt": previous.get("lastIntruderEnforcementAt"),
        "windowsLockRequested": bool(previous.get("windowsLockRequested")),
        "windowsLockAttempted": bool(previous.get("windowsLockAttempted")),
        "windowsLockSucceeded": bool(previous.get("windowsLockSucceeded")),
        "windowsLockErrorKind": str(previous.get("windowsLockErrorKind") or ""),
        "windowsLockUnavailableReason": str(previous.get("windowsLockUnavailableReason") or ""),
        "lockRequested": bool(previous.get("lockRequested")),
        "lockAttempted": bool(previous.get("lockAttempted")),
        "lockSucceeded": bool(previous.get("lockSucceeded")),
        "lockErrorKind": str(previous.get("lockErrorKind") or ""),
        "lockUnavailableReason": str(previous.get("lockUnavailableReason") or ""),
    }
    prompt = _make_post_lock_feedback_prompt(fields)
    if prompt:
        fields["feedback_prompt"] = prompt
    return fields

def classify_post_lock_confirmation(
    self,
    *,
    state: Optional[Dict[str, Any]] = None,
    label: str,
    feedback_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Classify an already-enforced, already-locked event after unlock.

    This function deliberately does not request another workstation lock, does
    not start another archive, and does not stop current fresh monitoring. It
    only records the user's post-lock classification on the backend state.
    """
    facade = _facade()
    if not self._current_user:
        return {"ok": False, "reason": "no_current_user"}
    current_state = state if isinstance(state, dict) else self._active_state_for_current_user()
    current_state = dict(current_state) if isinstance(current_state, dict) else {}
    prompt = current_state.get("feedback_prompt") if isinstance(current_state.get("feedback_prompt"), dict) else {}
    event_id = str(current_state.get("postLockConfirmationEventId") or prompt.get("event_id") or "").strip()
    if not bool(current_state.get("postLockConfirmationPending")) or not event_id:
        return {"ok": False, "reason": "no_post_lock_confirmation_pending"}
    if bool(current_state.get("postLockConfirmationAnswered")):
        return {"ok": True, "already_classified": True, "event_id": event_id, "state": current_state}
    raw_label = str(label or "").strip()
    if raw_label == "confirmed_intruder":
        classification = "confirmed_intruder"
        user_verified = False
        status_note = "confirmed_intruder_after_lock"
    elif raw_label == "verified_legit_after_warning":
        classification = "verified_legit_after_lock"
        user_verified = True
        status_note = "false_positive_review"
    else:
        return {"ok": False, "reason": "unsupported_post_lock_confirmation_label"}

    now = facade.time.time()
    now_text = facade.time.strftime("%Y-%m-%d %H:%M:%S", facade.time.localtime(now)) if hasattr(facade.time, "localtime") else str(now)
    feedback_record = dict(feedback_record or {})
    updated = dict(current_state)
    answered_prompt = {**dict(prompt or {}), "pending": False, "answered": True, "label": raw_label, "classification": classification, "answered_at": feedback_record.get("timestamp") or now_text}
    updated.update(
        {
            "feedback_prompt": answered_prompt,
            "latest_feedback_label": feedback_record.get("label") or raw_label,
            "latest_feedback_timestamp": feedback_record.get("timestamp") or now_text,
            "postLockConfirmationPending": False,
            "postLockConfirmationPromptAfterUnlock": False,
            "postLockConfirmationStage": "classified",
            "postLockConfirmationAnswered": True,
            "postLockConfirmationAnsweredAt": feedback_record.get("timestamp") or now_text,
            "postLockConfirmationAnswer": classification,
            "postLockConfirmationUserVerified": bool(user_verified),
            "postLockConfirmationEventId": event_id,
            "blockedEventClassification": classification,
            "blockedEventClassificationAt": now,
            "blockedEventClassificationAtText": now_text,
            "blockedEventTrainingEligible": False,
            "training_eligible": False,
            "postLockClassificationStatus": status_note,
            "postLockClassificationDuplicateIgnored": False,
            "runtime_diagnostic_code": status_note,
        }
    )
    if classification == "confirmed_intruder":
        updated.update(
            {
                "confirmedIntruderAfterLock": True,
                "falsePositiveReview": False,
                "archive_label": updated.get("archive_label") or "intruder",
                "final_bucket": updated.get("final_bucket") or "rejected",
                "postLockConfirmationSummary": "The user confirmed the already-blocked event was controlled by someone else.",
            }
        )
    else:
        updated.update(
            {
                "confirmedIntruderAfterLock": False,
                "falsePositiveReview": True,
                "verifiedLegitAfterLock": True,
                "postLockConfirmationSummary": "The user reported the already-blocked event was them; retain for false-positive review only.",
            }
        )
    try:
        from metadata_core.production_evidence_pipeline import append_post_lock_feedback_shadow_evidence_record

        shadow_record = append_post_lock_feedback_shadow_evidence_record(
            user_id=str(self._current_user.get("user_id") or ""),
            state=updated,
            label=raw_label,
            feedback_record=feedback_record,
            timestamp=feedback_record.get("timestamp") or now_text,
        )
        updated["postLockShadowEvidenceRecorded"] = True
        updated["postLockShadowEvidenceSource"] = str(shadow_record.get("source") or "post_lock_confirmation_feedback")
        updated["postLockShadowEvidenceWindowId"] = str(shadow_record.get("window_id") or event_id)
    except Exception as exc:
        # Post-lock feedback evidence is diagnostic/shadow-only. A ledger failure
        # must never block classification state updates, monitoring resume, or
        # production enforcement.
        updated["postLockShadowEvidenceRecorded"] = False
        updated["postLockShadowEvidenceError"] = type(exc).__name__
    facade.write_session_state(updated)
    self._runtime_state = updated
    return {"ok": True, "already_classified": False, "event_id": event_id, "classification": classification, "state": updated}
