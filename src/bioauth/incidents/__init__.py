"""Incident identity and idempotency contracts for BioAuth.

This module owns the rules that prevent a single high-risk incident from
triggering Windows Lock more than once, and from re-opening the post-lock
feedback dialog for an already-consumed incident.

Rules:
  1. Every intruder lock event has a stable incident_id derived from
     (session_id, reason_code, started_at).  The same incident_id must not
     cause a second Windows Lock call.

  2. Before calling LockWorkStation(), the monitor reads session_state and
     checks: if session_state["app_locked"] is already True, skip the call.

  3. The feedback dialog is identified by postLockConfirmationEventId.  The
     bridge tracks the last emitted feedback prompt event-id and does not
     re-emit the warningFeedbackPromptRequested signal for the same id.

  4. Post-lock auto-resume uses a new session_id / run_id, so a resumed
     session cannot re-trigger the previous incident's UI state.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional


# ── Incident identity ────────────────────────────────────────────────────────

def build_incident_id(
    session_id: str,
    reason_code: str,
    started_at: Any = "",
) -> str:
    """Return a stable, privacy-safe incident identifier.

    The ID is a short SHA-256 prefix over (session_id, reason_code, started_at).
    It is safe to store in session_state without revealing sensitive content.
    """
    raw = f"{session_id or 'unknown'}|{reason_code or 'intruder'}|{started_at or ''}"
    return "inc-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ── Lock idempotency guard ───────────────────────────────────────────────────

def session_already_locked(state: Dict[str, Any]) -> bool:
    """Return True if session_state already records a successful lock.

    Used by the monitor before calling LockWorkStation() to prevent
    double-locking a workstation for the same incident.
    """
    if not isinstance(state, dict):
        return False
    return (
        bool(state.get("app_locked"))
        or bool(state.get("screen_locked"))
        or bool(state.get("lockSucceeded"))
        or bool(state.get("windowsLockSucceeded"))
    )


def lock_is_already_consumed(state: Dict[str, Any], incident_id: str) -> bool:
    """Return True when this specific incident has already been locked.

    Checks both the locked flag and the enforcement-id for precise idempotency.
    """
    if session_already_locked(state):
        stored_id = str(state.get("lastIntruderEnforcementId") or "")
        if not stored_id or not incident_id:
            return True  # locked but unknown id — treat as consumed
        return stored_id == incident_id
    return False


# ── Feedback dialog dedup guard ──────────────────────────────────────────────

class FeedbackPromptGuard:
    """Prevents the post-lock feedback dialog from opening twice for the same incident.

    The bridge holds one instance of this guard.  Each time the refresh loop
    wants to emit warningFeedbackPromptRequested, it calls should_emit().
    The guard tracks the last emitted event-id and suppresses duplicates.

    Usage in the bridge::

        _feedback_guard = FeedbackPromptGuard()

        # In the refresh loop, before emitting:
        if _feedback_guard.should_emit(event_id):
            self.warningFeedbackPromptRequested.emit(payload)

        # When the user answers the dialog:
        _feedback_guard.mark_answered(event_id)
    """

    def __init__(self) -> None:
        self._last_emitted_id: str = ""
        self._answered_ids: set[str] = set()

    def should_emit(self, event_id: str) -> bool:
        """Return True iff this event_id should trigger a new feedback dialog."""
        eid = str(event_id or "").strip()
        if not eid:
            return False
        if eid in self._answered_ids:
            return False
        if eid == self._last_emitted_id:
            return False
        return True

    def record_emitted(self, event_id: str) -> None:
        """Call this after emitting the signal for event_id."""
        eid = str(event_id or "").strip()
        if eid:
            self._last_emitted_id = eid

    def mark_answered(self, event_id: str) -> None:
        """Call this when the user answers (or dismisses) the feedback dialog."""
        eid = str(event_id or "").strip()
        if eid:
            self._answered_ids.add(eid)
            if self._last_emitted_id == eid:
                self._last_emitted_id = ""

    def reset(self) -> None:
        """Clear all state — call when a new protected session starts."""
        self._last_emitted_id = ""
        self._answered_ids.clear()

    @property
    def last_emitted_id(self) -> str:
        return self._last_emitted_id
