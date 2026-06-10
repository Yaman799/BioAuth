from __future__ import annotations

import logging
import time
from importlib import import_module
from typing import Any, Dict, Optional

from bioauth_runtime.monitor_worker import face_gate, lock_controller
from bioauth_runtime import runtime_boundary

LOGGER = logging.getLogger(__name__)

try:
    from monitor_core.context import MonitorContext, make_context_from_monitor_module
    _CONTEXT_AVAILABLE = True
except ImportError:
    _CONTEXT_AVAILABLE = False
    MonitorContext = None  # type: ignore[assignment,misc]


def _facade():
    """Legacy fallback that returns the live monitor module."""
    return import_module("monitor")


def _ctx_or_facade(ctx: "Optional[MonitorContext]") -> Any:
    """Return ctx if provided, otherwise fall back to the legacy facade.

    This shim lets individual functions migrate incrementally.
    """
    if ctx is not None:
        return ctx
    return _facade()


def _signal_monitor_start_failure(reason: str, existing: Optional[Dict[str, Any]] = None) -> None:
    facade = _facade()
    state = dict(existing) if isinstance(existing, dict) else {}
    if state:
        facade._write_monitor_state(
            decision=state.get("decision"),
            extra={
                "active": bool(state.get("active", True)),
                "session_id": state.get("session_id"),
                "user_id": state.get("user_id") or facade.EXPECTED_USER_SLUG,
                "session_kind": state.get("session_kind", "protected"),
                "started_at": state.get("started_at"),
                "started_at_text": state.get("started_at_text"),
                "monitor_ready": False,
                "monitor_failed": True,
                "technical_failure": True,
                "awaiting_evidence": False,
                "monitor_error": reason,
                "protected_failure_reason": reason,
                "runtime_diagnostic_code": reason,
                "runtime_diagnostic_reason": reason,
                "status": "monitor_unavailable",
            },
        )
    facade._stop_logger_for_context()


def _stop_logger_for_context():
    facade = _facade()
    if facade.EXPECTED_USER_SLUG:
        facade.request_stop(f"logger_user_{facade.EXPECTED_USER_SLUG}")
    facade.request_stop("logger_legit")
    facade.request_stop("logger_intruder")


def _capture_intruder_evidence(session_id: str, risk: int, avg_risk: float, ml: int) -> Dict[str, Any]:
    facade = _facade()
    settings = facade.load_settings()
    event = {
        "session_id": session_id,
        "user_id": facade.EXPECTED_USER_SLUG or "",
        "incident_type": "confirmed_intruder",
        "trigger_reason": "confirmed_intruder",
        "risk": int(risk),
        "avg_risk": round(float(avg_risk), 2),
        "ml": int(ml),
    }
    try:
        return facade.capture_incident_evidence(event, settings=settings, archive_status="pending", lock_status="pending")
    except Exception as exc:
        LOGGER.warning("Incident evidence capture failed for session %s: %s", session_id, exc, exc_info=True)
        return {
            "enabled": bool(settings.get("incident_evidence_enabled", False)),
            "status": "failed",
            "reason": f"capture_exception: {exc}",
            "incident_type": "confirmed_intruder",
        }


def _lock_workstation_result() -> Dict[str, Any]:
    helper = getattr(_facade(), "lock_current_session_result", None)
    if callable(helper):
        return dict(helper())
    succeeded = bool(_facade().lock_current_session())
    return {
        "lockRequested": True,
        "lockAttempted": True,
        "lockSucceeded": succeeded,
        "lockErrorKind": "" if succeeded else "legacy_lock_returned_false",
        "lockUnavailableReason": "",
        "windowsLockRequested": True,
        "windowsLockAttempted": True,
        "windowsLockSucceeded": succeeded,
        "windowsLockErrorKind": "" if succeeded else "legacy_lock_returned_false",
        "windowsLockUnavailableReason": "",
    }


def _lock_workstation() -> bool:
    return bool(_lock_workstation_result().get("lockSucceeded"))


def _lock_fields(lock_result: Dict[str, Any]) -> Dict[str, Any]:
    return lock_controller._lock_fields(lock_result)

def _face_status(face_result: Dict[str, Any]) -> str:
    status = str((face_result or {}).get("status") or "not_verified").strip().lower()
    return status or "not_verified"


def _face_fallback(face_result: Dict[str, Any]) -> str:
    fallback = str((face_result or {}).get("fallback_reason") or (face_result or {}).get("reason") or "").strip().lower()
    return fallback


def _face_result_suppresses_lock(face_result: Dict[str, Any]) -> bool:
    if not isinstance(face_result, dict):
        return False
    status = _face_status(face_result)
    verified = bool(face_result.get("verified", False)) or status == "verified_owner"
    return bool(
        verified
        and bool(face_result.get("lock_suppressed", False))
        and bool(face_result.get("verified_owner_after_anomaly", False))
    )


def _safe_face_result(face_result: Dict[str, Any]) -> Dict[str, Any]:
    safe = dict(face_result or {})
    for forbidden in ("frame", "frames", "image", "images", "embedding", "template", "template_digest", "source_frame_paths"):
        safe.pop(forbidden, None)
    safe.setdefault("raw_images_stored", False)
    return safe


def _write_pre_lock_face_pending(session_id: str, risk: int, avg_risk: float, ml: int) -> None:
    facade = _facade()
    try:
        facade._write_monitor_state(
            decision="intruder",
            extra={
                "session_id": session_id,
                "user_id": facade.EXPECTED_USER_SLUG or "",
                "risk": int(risk),
                "avg_risk": round(float(avg_risk), 2),
                "ml": int(ml),
                "protected_action_requested": True,
                "protected_action_phase": "pre_lock_face_confirmation",
                "face_pre_lock_status": "checking",
                "face_pre_lock_fallback_reason": "",
                "final_action": "pre_lock_face_confirmation_pending",
                "face_confirmation_lock_suppressed": False,
                "lock_suppressed": False,
                "verified_owner_after_anomaly": False,
                "app_locked": False,
                "screen_locked": False,
            },
        )
    except Exception:
        LOGGER.debug("pre_lock_face_pending_state_write_failed", exc_info=True)


def _write_pre_lock_face_failed_closed(session_id: str, risk: int, avg_risk: float, ml: int, face_result: Dict[str, Any]) -> None:
    facade = _facade()
    safe = _safe_face_result(face_result)
    status = _face_status(safe)
    fallback = _face_fallback(safe)
    try:
        facade._write_monitor_state(
            decision="intruder",
            extra={
                "session_id": session_id,
                "user_id": facade.EXPECTED_USER_SLUG or "",
                "risk": int(risk),
                "avg_risk": round(float(avg_risk), 2),
                "ml": int(ml),
                "protected_action_requested": True,
                "protected_action_phase": "face_failed_closed_locking",
                "face_pre_lock_status": status,
                "face_pre_lock_fallback_reason": fallback,
                "face_confirmation": safe,
                "face_confirmation_status": status,
                "face_confirmation_lock_suppressed": False,
                "lock_suppressed": False,
                "verified_owner_after_anomaly": False,
                "final_action": "lock_required_face_failed_closed",
                "lock_controller_final_action": "windows_lock_requested",
                "lock_reason": str(safe.get("lock_reason") or face_gate.map_face_result(safe).get("lock_reason") or "face_confirmation_error"),
            },
        )
    except Exception:
        LOGGER.debug("pre_lock_face_failed_state_write_failed", exc_info=True)


def _post_lock_event_id(session_id: str, reason_code: str, started_at: object = "") -> str:
    return lock_controller._post_lock_event_id(session_id, reason_code, started_at)


def _post_lock_confirmation_fields(session_id: str, lock_fields: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    return lock_controller.post_lock_confirmation_fields(session_id, lock_fields, previous)

def _lock_app_state(session_id: str, risk: int, avg_risk: float, ml: int, *,
                    ctx: "Optional[MonitorContext]" = None, lock_reason: str = "face_confirmation_error") -> None:
    """Delegate Windows lock handoff to the Phase 5 lock controller."""
    deps = _ctx_or_facade(ctx)
    previous = ctx.read_session_state(default={}) if ctx is not None else deps.read_session_state(default={})
    previous = previous if isinstance(previous, dict) else {}
    if bool(previous.get("app_locked")) or bool(previous.get("windowsLockSucceeded")):
        LOGGER.info("lock_idempotency_guard: skipping duplicate lock for session %s", str(session_id or ""))
        return
    lock_result_func = ctx.lock_workstation_result if ctx is not None else deps._lock_workstation_result
    writer = ctx.write_monitor_state if ctx is not None else deps._write_monitor_state
    lock_controller.request_windows_lock(
        session_id=session_id,
        risk=risk,
        avg_risk=avg_risk,
        ml=ml,
        lock_reason=lock_reason,
        previous_state=previous,
        lock_workstation_result=lock_result_func,
        write_monitor_state=writer,
    )


def _terminal_lock_extra(
    session_id: str, risk: int, avg_risk: float, ml: int,
    screen_locked: bool, previous: Dict[str, Any], lock_fields: Dict[str, Any],
) -> Dict[str, Any]:
    """Compatibility wrapper for old tests; lock_controller owns new payloads."""
    return lock_controller.build_terminal_lock_payload(
        session_id=session_id,
        risk=risk,
        avg_risk=avg_risk,
        ml=ml,
        screen_locked=screen_locked,
        previous_state=previous,
        lock_fields=lock_fields,
        lock_reason=str(previous.get("lock_reason") or "face_confirmation_error"),
    )

def _pre_lock_face_confirmation(session_id: str, risk: int, avg_risk: float, ml: int) -> Dict[str, Any]:
    """Run the Phase 5 face gate and return legacy-safe face metadata."""
    facade = _facade()
    settings = facade.load_settings()
    try:
        timeout = float(settings.get("face_confirmation_pre_lock_timeout_sec", 3.0) or 3.0)
    except Exception:
        timeout = 3.0
    settings_for_prelock = dict(settings if isinstance(settings, dict) else {})
    demo_classic = False
    try:
        demo_classic = runtime_boundary.demo_features_enabled() and bool(getattr(facade, "demo_classic_protected_enabled", lambda: False)())
    except Exception:
        demo_classic = False
    if demo_classic:
        timeout = max(timeout, 5.0)
        try:
            from app_settings import feature_flag_enabled, has_current_face_template_consent

            if (
                feature_flag_enabled(settings_for_prelock, "enable_face_confirmation")
                and has_current_face_template_consent(settings_for_prelock)
            ):
                settings_for_prelock["face_confirmation_enabled"] = True
                settings_for_prelock["face_confirmation_demo_prelock_override"] = True
        except Exception:
            LOGGER.debug("demo_classic_prelock_face_preference_override_skipped", exc_info=True)
    camera_factory = getattr(facade, "build_default_camera_provider", None)

    def _pre_lock_camera_factory():
        if not callable(camera_factory):
            return None
        try:
            return camera_factory(timeout_sec=min(timeout, 3.0 if demo_classic else 1.5), warmup_frames=3 if demo_classic else 2)
        except TypeError:
            try:
                return camera_factory(warmup_frames=3 if demo_classic else 2)
            except TypeError:
                return camera_factory()

    result = face_gate.confirm_before_lock(
        user_id=facade.EXPECTED_USER_SLUG or "",
        settings=settings_for_prelock,
        service_factory=getattr(facade, "build_default_identity_confirmation_service", None),
        camera_provider_factory=_pre_lock_camera_factory if callable(camera_factory) else None,
        timeout_sec=timeout,
        confirmation_func=getattr(facade, "confirm_identity_before_lock", None),
    )
    safe = dict(result.get("raw_result") or {})
    safe.update({
        "face_gate_status": result.get("status"),
        "should_lock": bool(result.get("should_lock", True)),
        "lock_reason": str(result.get("lock_reason") or ""),
        "face_gate_final_action": str(result.get("final_action") or ""),
        "duration_ms": result.get("duration_ms", safe.get("elapsed_ms", 0)),
    })
    safe.setdefault("attempted", False)
    safe.setdefault("method", "local_face_confirmation")
    safe.setdefault("status", "unavailable")
    safe.setdefault("lock_suppressed", False)
    safe.setdefault("fallback_reason", "")
    safe.setdefault("elapsed_ms", 0.0)
    safe.setdefault("verified_owner_after_anomaly", False)
    safe.setdefault("eligible_for_shadow_evidence", False)
    safe.setdefault("eligible_for_direct_production_training", False)
    safe.setdefault("raw_images_stored", False)
    safe.setdefault("face_confirmation_demo_prelock_override", bool(settings_for_prelock.get("face_confirmation_demo_prelock_override", False)))
    safe.setdefault("lock_integration_enabled", True)
    return safe

def _record_face_confirmed_false_positive(session_id: str, risk: int, avg_risk: float, ml: int, ts: str, face_result: Dict[str, Any]) -> None:
    facade = _facade()
    previous = facade.read_session_state(default={})
    previous = previous if isinstance(previous, dict) else {}
    state_extra = {
        "session_id": session_id,
        "user_id": previous.get("user_id") or facade.EXPECTED_USER_SLUG,
        "status": "face_confirmed_owner_lock_suppressed",
        "risk": int(risk),
        "avg_risk": round(float(avg_risk), 2),
        "ml": int(ml),
        "app_locked": False,
        "screen_locked": False,
        "forced_stop": False,
        "monitor_holding": False,
        "restriction_active": False,
        "auto_resume_pending": False,
        "resume_after_unlock": False,
        "decision_finalized": False,
        "final_decision": "verified_owner_after_anomaly",
        "archive_label": "false_positive_candidate",
        "final_bucket": "diagnostic_only",
        "training_eligible": False,
        "protected_action_requested": True,
        "protected_action_phase": "face_verified_lock_suppressed",
        "face_pre_lock_status": "verified_owner",
        "face_pre_lock_fallback_reason": "",
        "final_action": "continue_after_owner_face_verified",
        "lock_suppressed": True,
        "excluded_from_positive_training": True,
        "training_counts_toward_minimum": False,
        "face_confirmation": dict(face_result),
        "face_confirmation_status": str(face_result.get("status") or ""),
        "face_confirmation_lock_suppressed": True,
        "verified_owner_after_anomaly": True,
        "false_positive_candidate": True,
        "eligible_for_shadow_evidence": True,
        "eligible_for_direct_production_training": False,
        "production_decision_changed": False,
        "production_threshold_changed": False,
        "production_model_pointer_changed": False,
        "protected_sessions_unlocked": False,
        "source": "pre_lock_face_confirmation",
        "policy_version": "phase14-face-feedback-shadow-evidence-v1",
        "incident_evidence_status": "skipped_face_confirmed_owner",
        "alert_code": "face_confirmed_owner_lock_suppressed",
        "alert_title_key": "face_pre_lock_suppressed_title",
        "alert_message_key": "face_pre_lock_suppressed_msg",
        "alert_title": "",
        "alert_message": "",
        "alert_token": f"face-suppressed-{session_id}-{int(time.time())}",
        "started_at": previous.get("started_at"),
        "started_at_text": previous.get("started_at_text"),
    }
    facade._write_monitor_state(decision=previous.get("decision") or "suspicious", extra=state_extra)
    try:
        from metadata_core.production_evidence_pipeline import append_pre_lock_face_confirmation_shadow_evidence_record

        append_pre_lock_face_confirmation_shadow_evidence_record(
            user_id=str(state_extra.get("user_id") or facade.EXPECTED_USER_SLUG or ""),
            session_id=session_id,
            risk=risk,
            avg_risk=avg_risk,
            state={**previous, **state_extra},
            face_result=face_result,
            timestamp=ts,
        )
        LOGGER.info("pre_lock_face_confirmation_shadow_evidence_record_appended")
    except Exception:
        # Shadow evidence recording is diagnostic-only and must never alter the
        # protected-session response, production pointer, thresholds, or gates.
        LOGGER.warning("Pre-lock face confirmation shadow evidence append failed", exc_info=True)
    facade.append_log(
        {
            "time": ts,
            "status": "face_confirmed_owner_lock_suppressed",
            "risk": int(risk),
            "avg_risk": round(float(avg_risk), 2),
            "ml": int(ml),
            "expected_user": facade.EXPECTED_USER_SLUG,
            "session_id": session_id,
            "face_confirmation": dict(face_result),
            "false_positive_candidate": True,
            "eligible_for_shadow_evidence": True,
            "eligible_for_direct_production_training": False,
            "production_decision_changed": False,
            "production_threshold_changed": False,
            "production_model_pointer_changed": False,
            "protected_sessions_unlocked": False,
            "source": "pre_lock_face_confirmation",
            "policy_version": "phase14-face-feedback-shadow-evidence-v1",
        }
    )


def _lock_and_stop_for_intruder(session_id: str, risk: int, avg_risk: float, ml: int, ts: str) -> None:
    facade = _facade()
    _write_pre_lock_face_pending(session_id=session_id, risk=risk, avg_risk=avg_risk, ml=ml)
    face_result = _safe_face_result(facade._pre_lock_face_confirmation(session_id=session_id, risk=risk, avg_risk=avg_risk, ml=ml))
    try:
        LOGGER.info(
            "pre_lock_face_confirmation_result",
            extra={
                "status": str(face_result.get("status") or ""),
                "attempted": bool(face_result.get("attempted")),
                "lock_suppressed": bool(face_result.get("lock_suppressed")),
                "fallback_reason": str(face_result.get("fallback_reason") or ""),
                "elapsed_ms": float(face_result.get("elapsed_ms") or 0.0),
            },
        )
    except Exception:
        LOGGER.debug("pre_lock_face_confirmation_result_log_failed", exc_info=True)
    gate_result = face_gate.map_face_result(face_result)
    if not bool(gate_result.get("should_lock", True)):
        LOGGER.info("pre_lock_face_confirmation_suppressed_lock")
        facade._record_face_confirmed_false_positive(session_id=session_id, risk=risk, avg_risk=avg_risk, ml=ml, ts=ts, face_result=face_result)
        return
    _write_pre_lock_face_failed_closed(session_id=session_id, risk=risk, avg_risk=avg_risk, ml=ml, face_result=face_result)
    LOGGER.info(
        "pre_lock_face_confirmation_failed_closed",
        extra={
            "status": str(face_result.get("status") or "unknown"),
            "fallback_reason": str(face_result.get("fallback_reason") or face_result.get("status") or "unknown"),
            "attempted": bool(face_result.get("attempted", False)),
            "demo_prelock_override": bool(face_result.get("face_confirmation_demo_prelock_override", False)),
        },
    )
    evidence_result = facade._capture_intruder_evidence(session_id=session_id, risk=risk, avg_risk=avg_risk, ml=ml)
    saved_count = int(evidence_result.get("saved_file_count", 0) or 0)
    notice = ""
    if evidence_result.get("enabled") and evidence_result.get("status") in {"success", "partial_success"}:
        notice = "Local incident evidence was saved for this event."
    elif evidence_result.get("enabled") and evidence_result.get("status") == "failed":
        notice = "Incident evidence capture was attempted but could not save files before lock."
    facade._lock_app_state(session_id=session_id, risk=risk, avg_risk=avg_risk, ml=ml, lock_reason=str(gate_result.get("lock_reason") or "face_confirmation_error"))
    current = facade.read_session_state(default={})
    if evidence_result.get("incident_path"):
        lock_status = "screen_locked" if bool((current or {}).get("screen_locked")) else "lock_attempted"
        updated_payload = facade.update_incident_record(str(evidence_result.get("incident_path") or ""), lock_status=lock_status)
        if updated_payload:
            evidence_result["payload"] = updated_payload
    if isinstance(current, dict):
        extra = {
            "incident_evidence": evidence_result.get("payload") or None,
            "incident_evidence_status": evidence_result.get("status"),
            "incident_evidence_notice": notice,
            "incident_evidence_saved_count": saved_count,
            "incident_evidence_dir": evidence_result.get("incident_dir") or "",
        }
        if evidence_result.get("incident_id"):
            extra["incident_evidence_id"] = evidence_result.get("incident_id")
        if evidence_result.get("hashes_path"):
            extra["incident_evidence_hashes_path"] = evidence_result.get("hashes_path")
        facade._write_monitor_state(decision=current.get("decision"), extra=extra)
    facade._stop_logger_for_context()
    facade.append_log(
        {
            "time": ts,
            "status": "locked",
            "risk": risk,
            "avg_risk": round(avg_risk, 2),
            "ml": ml,
            "expected_user": facade.EXPECTED_USER_SLUG,
            "session_id": session_id,
            "incident_evidence_status": evidence_result.get("status"),
            "incident_evidence_saved_count": saved_count,
        }
    )
