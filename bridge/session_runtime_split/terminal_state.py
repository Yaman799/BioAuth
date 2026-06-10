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

def stop_stale_monitor(self, wait_timeout: float = 0.5) -> bool:
    facade = _facade()
    self._clear_pending_monitor_start()
    facade.request_stop("monitor")
    proc = self._running_processes.get("monitor")
    if proc is None:
        return True
    if proc.poll() is None:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        except OSError as exc:
            LOGGER.warning("Failed terminating stale monitor process: %s", exc)

        def _wait_for_exit() -> None:
            try:
                proc.wait(timeout=max(0.25, wait_timeout))
            except facade.subprocess.TimeoutExpired:
                LOGGER.warning("Stale monitor process did not exit within %.2fs; forcing kill", wait_timeout)
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    LOGGER.warning("Failed killing stale monitor process: %s", exc)
                try:
                    proc.wait(timeout=max(0.25, wait_timeout))
                except facade.subprocess.TimeoutExpired:
                    LOGGER.error("Stale monitor process remained alive after kill timeout")
            except OSError as exc:
                LOGGER.warning("Failed waiting for stale monitor process: %s", exc)
            try:
                self._cleanup_processes()
            except Exception:
                LOGGER.exception("Failed cleaning up stale monitor process")

        facade.threading.Thread(target=_wait_for_exit, daemon=True).start()
        return True
    self._cleanup_processes()
    return True

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)

def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)

def _lock_current_session_result_for_enforcement() -> Dict[str, Any]:
    try:
        from bio_platform.lock_screen import lock_current_session_result

        return dict(lock_current_session_result())
    except Exception as exc:
        LOGGER.exception("Windows lock helper failed during intruder enforcement")
        return {
            "lockRequested": True,
            "lockAttempted": False,
            "lockSucceeded": False,
            "lockErrorKind": type(exc).__name__,
            "lockUnavailableReason": "lock_helper_exception",
            "windowsLockRequested": True,
            "windowsLockAttempted": False,
            "windowsLockSucceeded": False,
            "windowsLockErrorKind": type(exc).__name__,
            "windowsLockUnavailableReason": "lock_helper_exception",
        }

def _lock_result_fields(lock_result: Dict[str, Any]) -> Dict[str, Any]:
    result = lock_result if isinstance(lock_result, dict) else {}
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

def _load_settings_for_enforcement() -> Dict[str, Any]:
    try:
        from app_settings import load_settings

        return dict(load_settings())
    except Exception:
        LOGGER.warning("Failed loading settings for intruder enforcement; using safe empty settings.", exc_info=True)
        return {}

def _capture_incident_evidence_for_enforcement(event: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from evidence_capture import capture_incident_evidence

        return dict(capture_incident_evidence(event, settings=settings, archive_status="pending", lock_status="pending"))
    except Exception as exc:
        LOGGER.exception("Incident evidence capture failed during intruder enforcement")
        return {
            "enabled": bool((settings or {}).get("incident_evidence_enabled", False)),
            "status": "failed",
            "reason": f"capture_exception: {type(exc).__name__}",
            "incident_type": "confirmed_intruder",
        }

def _update_incident_record_for_enforcement(incident_path: str, **changes: Any) -> Dict[str, Any]:
    try:
        from evidence_capture import update_incident_record

        return dict(update_incident_record(incident_path, **changes))
    except Exception:
        LOGGER.warning("Failed updating incident record for intruder enforcement.", exc_info=True)
        return {}

def _intruder_enforcement_id(*, source: str, reason_code: str, session_id: str) -> str:
    safe_source = str(source or "backend_policy").strip().lower() or "backend_policy"
    safe_reason = str(reason_code or "confirmed_intruder").strip().lower() or "confirmed_intruder"
    safe_session = str(session_id or "unknown").strip() or "unknown"
    return f"{safe_source}:{safe_reason}:{safe_session}"

def _intruder_enforcement_already_applied(state: Dict[str, Any], enforcement_id: str) -> bool:
    return bool(
        str(state.get("lastIntruderEnforcementId") or "") == str(enforcement_id or "")
        and bool(state.get("lastIntruderEnforcementApplied"))
        and (bool(state.get("forced_stop")) or str(state.get("final_decision") or "").lower() == "intruder")
        and bool(state.get("auto_resume_pending") or state.get("resume_after_unlock"))
    )

def _incident_notice(evidence_result: Dict[str, Any]) -> str:
    result = evidence_result if isinstance(evidence_result, dict) else {}
    if result.get("enabled") and result.get("status") in {"success", "partial_success"}:
        return "Local incident evidence was saved for this event."
    if result.get("enabled") and result.get("status") == "failed":
        return "Incident evidence capture was attempted but could not save files before lock."
    return ""

def _lock_status_for_incident(lock_fields: Dict[str, Any]) -> str:
    if bool(lock_fields.get("windowsLockSucceeded") or lock_fields.get("lockSucceeded")):
        return "screen_locked"
    if bool(lock_fields.get("windowsLockAttempted") or lock_fields.get("lockAttempted")):
        return "lock_attempted"
    return "lock_unavailable"

def _post_lock_event_id(*, session_id: str, reason_code: str = "warning_followup_lock", started_at: Any = "") -> str:
    safe_session = str(session_id or "unknown").strip() or "unknown"
    safe_reason = str(reason_code or "warning_followup_lock").strip().lower() or "warning_followup_lock"
    safe_started = str(started_at or "").strip().replace(" ", "_")
    suffix = safe_started if safe_started else "event"
    return f"post-lock:{safe_reason}:{safe_session}:{suffix}"

def _post_lock_confirmation_fields(
    *,
    session_id: str,
    reason_code: str,
    lock_fields: Dict[str, Any],
    now: Optional[float] = None,
    started_at: Any = "",
) -> Dict[str, Any]:
    """Build safe state fields for a prompt that is shown only after lock recovery.

    The prompt is classification-only: backend monitor enforcement already made the
    lock/archive decision. A failed or unavailable lock must not create a prompt
    that implies the workstation was locked.
    """
    locked = bool(lock_fields.get("windowsLockSucceeded") or lock_fields.get("lockSucceeded"))
    event_id = _post_lock_event_id(session_id=session_id, reason_code=reason_code, started_at=started_at or (now or ""))
    unavailable = str(lock_fields.get("windowsLockUnavailableReason") or lock_fields.get("lockUnavailableReason") or "")
    error_kind = str(lock_fields.get("windowsLockErrorKind") or lock_fields.get("lockErrorKind") or "")
    return {
        "postLockConfirmationPending": bool(locked),
        "postLockConfirmationPromptAfterUnlock": bool(locked),
        "postLockConfirmationEventId": event_id if locked else "",
        "postLockConfirmationEventSessionId": str(session_id or ""),
        "postLockConfirmationReason": str(reason_code or "warning_followup_lock"),
        "postLockConfirmationStage": "locked_awaiting_unlock" if locked else "lock_failed_no_prompt",
        "postLockConfirmationUnavailableReason": "" if locked else (unavailable or error_kind or "lock_not_confirmed"),
        "postLockConfirmationAnswered": False,
        "postLockConfirmationAnsweredAt": "",
        "postLockConfirmationAnswer": "",
    }

def _make_post_lock_feedback_prompt(state: Dict[str, Any]) -> Dict[str, Any]:
    event_id = str(state.get("postLockConfirmationEventId") or "").strip()
    session_id = str(state.get("postLockConfirmationEventSessionId") or state.get("session_id") or "").strip()
    if not event_id or not bool(state.get("postLockConfirmationPending")):
        return {}
    return {
        "pending": True,
        "kind": "post_lock_confirmation",
        "token": f"post-lock-confirmation-{event_id}",
        "event_id": event_id,
        "session_id": session_id,
        "decision": "intruder",
        "risk": _safe_int(state.get("postLockConfirmationRisk", state.get("risk")), 0),
        "decision_reason_code": str(state.get("postLockConfirmationReason") or "warning_followup_lock"),
        "model_version": str(state.get("postLockConfirmationModelVersion") or ""),
        "policy_version": str(state.get("postLockConfirmationPolicyVersion") or ""),
        "options": ["verified_legit_after_warning", "confirmed_intruder"],
    }
