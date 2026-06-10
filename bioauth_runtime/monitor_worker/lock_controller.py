"""Windows lock handoff for the monitor worker."""
from __future__ import annotations

import time
from typing import Any, Callable, Mapping


def request_windows_lock(
    *,
    session_id: str,
    risk: int,
    avg_risk: float,
    ml: int,
    lock_reason: str,
    previous_state: Mapping[str, Any] | None,
    lock_workstation_result: Callable[[], Mapping[str, Any]] | None = None,
    write_monitor_state: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Request Windows lock and publish terminal resume-pending state."""
    previous = dict(previous_state or {})
    if _recent_same_lock_attempt(previous, session_id=session_id, lock_reason=lock_reason):
        payload = dict(previous)
        payload.update({
            "lock_loop_guard_blocked": True,
            "lock_loop_guard_reason": "recent_same_session_reason",
            "final_action": payload.get("final_action") or "windows_lock_throttled",
            "lock_reason": str(lock_reason or payload.get("lock_reason") or "lock_loop_guard"),
        })
        return {"skipped": True, "payload": payload, "lock_fields": _lock_fields(previous)}
    if bool(previous.get("app_locked")) or bool(previous.get("windowsLockSucceeded")):
        return {"skipped": True, "payload": dict(previous), "lock_fields": _lock_fields(previous)}
    if _is_return_verification_session(previous):
        lock_fields = _lock_fields({
            "lockRequested": False,
            "lockAttempted": False,
            "lockSucceeded": False,
            "windowsLockRequested": False,
            "windowsLockAttempted": False,
            "windowsLockSucceeded": False,
        })
        payload = build_return_verification_blocked_payload(
            session_id=session_id,
            risk=risk,
            avg_risk=avg_risk,
            ml=ml,
            previous_state=previous,
            lock_fields=lock_fields,
            lock_reason=lock_reason,
        )
        if callable(write_monitor_state):
            write_monitor_state(decision="pending", extra=payload)
        return {"skipped": True, "blocked": True, "payload": payload, "lock_fields": lock_fields}
    lock_fields = _lock_fields(_call_lock(lock_workstation_result))
    locked = bool(lock_fields.get("lockSucceeded") or lock_fields.get("windowsLockSucceeded"))
    payload = build_terminal_lock_payload(
        session_id=session_id,
        risk=risk,
        avg_risk=avg_risk,
        ml=ml,
        screen_locked=locked,
        previous_state=previous,
        lock_fields=lock_fields,
        lock_reason=lock_reason,
    )
    if callable(write_monitor_state):
        write_monitor_state(decision="intruder", extra=payload)
    return {"skipped": False, "payload": payload, "lock_fields": lock_fields}


def build_terminal_lock_payload(
    *,
    session_id: str,
    risk: int,
    avg_risk: float,
    ml: int,
    screen_locked: bool,
    previous_state: Mapping[str, Any] | None,
    lock_fields: Mapping[str, Any] | None,
    lock_reason: str,
) -> dict[str, Any]:
    """Build terminal forced-stop/resume-pending fields for a lock event."""
    previous = dict(previous_state or {})
    fields = _lock_fields(lock_fields)
    final_action = "windows_locked" if screen_locked else "windows_lock_requested"
    resumed_session = bool(previous.get("return_verification") or previous.get("auto_resume_loop_guard_armed"))
    allow_auto_resume = not resumed_session
    return {
        "session_id": session_id,
        "active": False,
        "session_state": "resume_pending",
        "flow": "protected_forced_stop",
        "forced_stop": True,
        "status": "resume_pending",
        "runtime_status": "resume_pending",
        "avg_risk": round(float(avg_risk), 2),
        "risk": int(risk),
        "ml": int(ml),
        "app_locked": True,
        "screen_locked": bool(screen_locked),
        "protected_action_requested": True,
        "protected_action_phase": previous.get("protected_action_phase") or "face_failed_closed_locking",
        "face_pre_lock_status": previous.get("face_pre_lock_status") or "not_verified",
        "face_pre_lock_fallback_reason": previous.get("face_pre_lock_fallback_reason") or "",
        "face_required": True,
        "high_risk_evidence": True,
        "final_action": final_action,
        "lock_reason": str(lock_reason or previous.get("lock_reason") or "face_confirmation_error"),
        "lock_controller_handoff": True,
        "lock_handoff_id": _post_lock_event_id(session_id, str(lock_reason or "lock"), str(previous.get("started_at") or previous.get("started_at_text") or "")),
        "lock_controller_last_attempt_at": time.time(),
        "lock_controller_last_attempt_session_id": str(session_id or ""),
        "lock_controller_last_attempt_reason": str(lock_reason or previous.get("lock_reason") or "face_confirmation_error"),
        "lock_suppressed": False,
        "verified_owner_after_anomaly": False,
        "face_confirmation_lock_suppressed": False,
        **fields,
        **post_lock_confirmation_fields(session_id, fields, previous),
        "decision_finalized": True,
        "final_decision": "intruder",
        "archive_label": "intruder",
        "final_bucket": "rejected",
        "training_eligible": False,
        "stop_reason": "monitor_intruder",
        "monitor_holding": True,
        "restriction_active": True,
        "auto_resume_pending": bool(allow_auto_resume),
        "resume_after_unlock": bool(allow_auto_resume),
        "resume_reason": "intruder_lock" if allow_auto_resume else "auto_resume_loop_guard_blocked",
        "lock_loop_guard_block_auto_resume": bool(resumed_session),
        "lock_loop_guard_reason": "auto_resumed_session_high_risk" if resumed_session else "",
        "auto_resume_attempt_count": previous.get("auto_resume_attempt_count") or previous.get("lock_loop_guard_auto_resume_attempt_count") or 0,
        "forced_stop_expected_monitor_exit": True,
        "monitor_exit_expected": True,
        "monitor_exit_expected_reason": "confirmed_high_risk_forced_stop",
        "started_at": previous.get("started_at"),
        "started_at_text": previous.get("started_at_text"),
        "alert_code": "session_locked",
        "alert_title_key": "alert_lock_title",
        "alert_message_key": "alert_screen_lock_msg" if screen_locked else "alert_lock_msg",
        "alert_title": "",
        "alert_message": "",
        "alert_token": f"lock-{session_id}-{int(time.time())}",
    }



def build_return_verification_blocked_payload(
    *,
    session_id: str,
    risk: int,
    avg_risk: float,
    ml: int,
    previous_state: Mapping[str, Any] | None,
    lock_fields: Mapping[str, Any] | None,
    lock_reason: str,
) -> dict[str, Any]:
    """Build a terminal state that blocks repeated Windows locks after auto-resume.

    A returned user verification session has already followed one successful
    high-risk lock handoff. If it immediately becomes high risk again, locking
    Windows a second time creates a user-visible loop. The safe action is to
    stop protection, preserve diagnostics, and require a manual restart.
    """
    previous = dict(previous_state or {})
    fields = _lock_fields(lock_fields)
    reason = "High-risk repeated during return verification; protection stopped to prevent repeated locking. Start protection manually after confirming identity."
    now = time.time()
    return {
        "session_id": session_id,
        "active": False,
        "session_state": "stopped",
        "flow": "resume_blocked",
        "forced_stop": True,
        "status": "auto_resume_high_risk_blocked",
        "runtime_status": "resume_blocked",
        "runtime_decision": "pending",
        "decision": "pending",
        "avg_risk": round(float(avg_risk), 2),
        "risk": int(risk),
        "ml": int(ml),
        "app_locked": False,
        "screen_locked": False,
        "protected_action_requested": False,
        "protected_action_phase": "return_verification_high_risk_blocked",
        "face_required": False,
        "high_risk_evidence": True,
        "final_action": "auto_resume_high_risk_blocked",
        "lock_reason": str(lock_reason or previous.get("lock_reason") or "post_unlock_high_risk"),
        "lock_controller_handoff": True,
        "lock_handoff_id": _post_lock_event_id(session_id, "auto_resume_high_risk_blocked", str(previous.get("started_at") or previous.get("started_at_text") or "")),
        "lock_controller_last_attempt_at": now,
        "lock_controller_last_attempt_session_id": str(session_id or ""),
        "lock_controller_last_attempt_reason": str(lock_reason or previous.get("lock_reason") or "post_unlock_high_risk"),
        "lock_suppressed": True,
        "lock_suppressed_reason": "auto_resume_high_risk_blocked",
        "verified_owner_after_anomaly": False,
        "face_confirmation_lock_suppressed": True,
        **fields,
        "decision_finalized": True,
        "final_decision": "pending",
        "archive_label": "interrupted",
        "final_bucket": "rejected",
        "training_eligible": False,
        "stop_reason": "auto_resume_high_risk_blocked",
        "monitor_holding": False,
        "restriction_active": False,
        "auto_resume_pending": False,
        "resume_after_unlock": False,
        "auto_resume_in_progress": False,
        "resume_in_progress": False,
        "return_verification": False,
        "resume_reason": "auto_resume_high_risk_blocked",
        "lock_loop_guard_block_auto_resume": True,
        "lock_loop_guard_blocked": True,
        "lock_loop_guard_reason": "auto_resumed_session_high_risk",
        "auto_resume_loop_guard_armed": False,
        "auto_resume_attempt_count": previous.get("auto_resume_attempt_count") or previous.get("lock_loop_guard_auto_resume_attempt_count") or 1,
        "lock_loop_guard_auto_resume_attempt_count": previous.get("lock_loop_guard_auto_resume_attempt_count") or previous.get("auto_resume_attempt_count") or 1,
        "forced_stop_expected_monitor_exit": True,
        "monitor_exit_expected": True,
        "monitor_exit_expected_reason": "auto_resume_high_risk_blocked",
        "started_at": previous.get("started_at"),
        "started_at_text": previous.get("started_at_text"),
        "runtime_diag_code": "auto_resume_high_risk_blocked",
        "runtime_diag_reason": reason,
        "runtime_diagnostic_code": "auto_resume_high_risk_blocked",
        "runtime_diagnostic_reason": reason,
        "status_message": "High risk repeated after unlock. Protection was stopped to prevent repeated locking. Start protection again manually.",
        "alert_code": "auto_resume_high_risk_blocked",
        "alert_title_key": "alert_auto_resume_blocked_title",
        "alert_message_key": "alert_auto_resume_blocked_msg",
        "alert_title": "",
        "alert_message": "",
        "alert_token": f"auto-resume-blocked-{session_id}-{int(now)}",
    }

def post_lock_confirmation_fields(session_id: str, lock_fields: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, Any]:
    """Return post-unlock confirmation flags only after lock succeeds."""
    locked = bool(lock_fields.get("windowsLockSucceeded") or lock_fields.get("lockSucceeded"))
    reason_code = str(previous.get("runtime_confirmation_rule") or "warning_followup_lock")
    event_id = _post_lock_event_id(session_id, reason_code, previous.get("started_at") or previous.get("started_at_text") or "")
    unavailable = str(lock_fields.get("windowsLockUnavailableReason") or lock_fields.get("lockUnavailableReason") or "")
    error_kind = str(lock_fields.get("windowsLockErrorKind") or lock_fields.get("lockErrorKind") or "")
    return {
        "runtime_confirmation_rule": reason_code,
        "lastIntruderEnforcementReason": reason_code,
        "lastIntruderEnforcementSource": "backend_policy",
        "lastIntruderEnforcementId": event_id,
        "lastIntruderEnforcementAt": time.time(),
        "postLockConfirmationPending": bool(locked),
        "postLockConfirmationPromptAfterUnlock": bool(locked),
        "postLockConfirmationEventId": event_id if locked else "",
        "postLockConfirmationEventSessionId": str(session_id or ""),
        "postLockConfirmationReason": reason_code,
        "postLockConfirmationStage": "locked_awaiting_unlock" if locked else "lock_failed_no_prompt",
        "postLockConfirmationUnavailableReason": "" if locked else (unavailable or error_kind or "lock_not_confirmed"),
        "postLockConfirmationAnswered": False,
        "postLockConfirmationAnsweredAt": "",
        "postLockConfirmationAnswer": "",
    }




def _is_return_verification_session(previous: Mapping[str, Any]) -> bool:
    """Return true for sessions created by post-unlock auto-resume."""
    if not isinstance(previous, Mapping):
        return False
    if bool(previous.get("return_verification") or previous.get("auto_resume_loop_guard_armed") or previous.get("auto_resume_source")):
        return True
    if str(previous.get("flow") or previous.get("status") or "").strip().lower() == "verifying_return":
        return True
    if str(previous.get("runtime_status") or "").strip().lower() == "verifying_return":
        return True
    if str(previous.get("auto_resume_from_lock_handoff_id") or "").strip():
        return True
    try:
        return max(
            int(previous.get("auto_resume_attempt_count") or 0),
            int(previous.get("lock_loop_guard_auto_resume_attempt_count") or 0),
        ) >= 1
    except (TypeError, ValueError):
        return False

def _recent_same_lock_attempt(previous: Mapping[str, Any], *, session_id: str, lock_reason: str) -> bool:
    """Prevent repeated Windows lock attempts for the same session/reason burst."""
    try:
        last_at = float(previous.get("lock_controller_last_attempt_at") or previous.get("lastLockAttemptAt") or 0.0)
    except (TypeError, ValueError):
        last_at = 0.0
    if last_at <= 0.0 or time.time() - last_at > 45.0:
        return False
    last_session = str(previous.get("lock_controller_last_attempt_session_id") or previous.get("session_id") or "")
    last_reason = str(previous.get("lock_controller_last_attempt_reason") or previous.get("lock_reason") or "")
    return last_session == str(session_id or "") and last_reason == str(lock_reason or "")

def _call_lock(lock_workstation_result: Callable[[], Mapping[str, Any]] | None) -> Mapping[str, Any]:
    if callable(lock_workstation_result):
        return dict(lock_workstation_result() or {})
    from bio_platform.lock_screen import lock_current_session_result

    return dict(lock_current_session_result() or {})


def _lock_fields(lock_result: Mapping[str, Any] | None) -> dict[str, Any]:
    result = dict(lock_result or {})
    return {
        "lockRequested": bool(result.get("lockRequested", True)),
        "lockAttempted": bool(result.get("lockAttempted")),
        "lockSucceeded": bool(result.get("lockSucceeded")),
        "lockErrorKind": str(result.get("lockErrorKind") or ""),
        "lockUnavailableReason": str(result.get("lockUnavailableReason") or ""),
        "windowsLockRequested": bool(result.get("windowsLockRequested", True)),
        "windowsLockAttempted": bool(result.get("windowsLockAttempted")),
        "windowsLockSucceeded": bool(result.get("windowsLockSucceeded")),
        "windowsLockErrorKind": str(result.get("windowsLockErrorKind") or ""),
        "windowsLockUnavailableReason": str(result.get("windowsLockUnavailableReason") or ""),
    }


def _post_lock_event_id(session_id: str, reason_code: str, started_at: object = "") -> str:
    safe_session = str(session_id or "unknown").strip() or "unknown"
    safe_reason = str(reason_code or "warning_followup_lock").strip().lower() or "warning_followup_lock"
    safe_started = str(started_at or "").strip().replace(" ", "_") or str(int(time.time()))
    return f"post-lock:{safe_reason}:{safe_session}:{safe_started}"
