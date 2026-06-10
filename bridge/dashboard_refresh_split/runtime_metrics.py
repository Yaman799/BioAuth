"""Extracted implementation section for `bridge/refresh_dashboard_helpers.py`."""
from __future__ import annotations
import logging
import os
from importlib import import_module
from typing import Any, Dict, List
from bioauth_runtime import runtime_boundary
from bridge.runtime_labels import runtime_policy_display_fields
from bridge import refresh_runtime_helpers as _refresh_state
from bridge.qt_thread_dispatch import dispatch_to_qt_thread



def _runtime_optional_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_user_risk(value: float | None) -> str:
    if value is None:
        return "--"
    rounded = round(float(value), 1)
    if abs(rounded - round(rounded)) < 0.05:
        return str(int(round(rounded)))
    return f"{rounded:.1f}"


def _select_user_display_risk(
    state: Dict[str, Any],
    *,
    decision_risk_available: bool,
    observed_risk_value: Any,
) -> tuple[float | None, str]:
    """Pick the single user-facing risk source without exposing internals."""
    for key in ("display_risk", "action_risk"):
        value = _runtime_optional_float(state.get(key))
        if value is not None:
            return value, key
    if decision_risk_available:
        for key in ("decision_risk", "risk"):
            value = _runtime_optional_float(state.get(key))
            if value is not None:
                return value, key
    observed = _runtime_optional_float(observed_risk_value)
    if observed is not None:
        return observed, "observed_model_risk"
    return None, ""


def _smooth_user_display_risk(self: Any, state: Dict[str, Any], value: float | None) -> float | None:
    """Smooth display-only risk; never feed this value back into decisions."""
    if value is None:
        return None
    session_id = str(state.get("session_id") or "")
    previous_session = str(getattr(self, "_last_user_display_risk_session_id", "") or "")
    previous = _runtime_optional_float(getattr(self, "_last_user_display_risk_value", None))
    current = float(value)
    if previous is None or (session_id and previous_session and session_id != previous_session):
        smoothed = current
    else:
        alpha = 0.45 if current >= 80.0 else 0.35 if current >= previous else 0.50
        smoothed = previous + alpha * (current - previous)
    setattr(self, "_last_user_display_risk_session_id", session_id)
    setattr(self, "_last_user_display_risk_value", float(smoothed))
    return round(float(smoothed), 1)

def build_runtime_state_view(self, state: Dict[str, Any]) -> Dict[str, Any]:
    facade = _facade()
    flow = self._session_flow(state)
    active = bool(state.get("active"))
    elapsed = self._format_elapsed(state.get("started_at")) if active else "--"
    raw_status = str(state.get("status") or ("ok" if active else "idle")).strip().lower()
    pending_logger_kind = str(getattr(self, "_pending_logger_session_kind", "") or "").strip().lower()
    pending_shadow_evidence_start = bool(getattr(self, "_pending_shadow_evidence_monitor_start", False)) or (bool(getattr(self, "_pending_logger_start", False)) and pending_logger_kind == "shadow_evidence")
    pending_logger_start = bool(getattr(self, "_pending_logger_start", False)) and pending_logger_kind == "protected"
    pending_monitor_start = bool(getattr(self, "_pending_monitor_start", False)) or pending_shadow_evidence_start
    logger_ready = bool(state.get("logger_ready"))
    monitor_ready = bool(state.get("monitor_ready"))
    logger_failed = bool(state.get("logger_failed")) or bool(getattr(self, "_logger_start_failed", False)) or raw_status in {"logger_unavailable", "logger_start_lost", "logger_runtime_error", "logger_exited_after_ready"}
    monitor_failed = bool(state.get("monitor_failed")) or bool(getattr(self, "_monitor_start_failed", False)) or raw_status in {"monitor_unavailable", "monitor_runtime_error", "monitor_exited_after_ready", "risk_engine_stopped", "failed"}
    restricted = flow == "protected_forced_stop"
    technical_failure = bool(state.get("technical_failure")) or flow == "protected_technical_failure" or logger_failed or monitor_failed or facade.runtime_status_is_technical_failure(raw_status)
    if technical_failure and raw_status in {"", "idle", "ok", "starting"}:
        diag_status = str(state.get("runtime_diagnostic_code") or state.get("protected_failure_reason") or "").strip().lower()
        if diag_status in {"monitor_exited_after_ready", "risk_engine_stopped", "monitor_unavailable", "monitor_process_lost"}:
            raw_status = "monitor_exited_after_ready" if diag_status == "monitor_exited_after_ready" else diag_status
            monitor_failed = True
        elif diag_status in {"logger_exited_after_ready", "logger_unavailable", "logger_start_lost"}:
            raw_status = diag_status
            logger_failed = True
        else:
            raw_status = "logger_unavailable" if logger_failed else "monitor_unavailable" if monitor_failed else "failed"
    awaiting_evidence = bool(state.get("awaiting_evidence")) or facade.runtime_status_awaits_evidence(raw_status)
    status_active = bool(active or technical_failure or pending_logger_start or pending_monitor_start)
    status_label = self._t(facade.runtime_status_key(raw_status, active=status_active, restricted=restricted))
    status_detail_key = facade.runtime_status_detail_key(raw_status)
    status_detail = self._t(status_detail_key) if status_detail_key else ""
    monitor_error = str(state.get("monitor_error") or state.get("protected_failure_reason") or "").strip()
    diagnostic_text = self._t("runtime_diagnostic_prefix", detail=monitor_error) if monitor_error else ""

    now = facade.time.time()
    telemetry_source_at = state.get("updated_at") or state.get("monitor_heartbeat_at") or state.get("logger_heartbeat_at")
    telemetry_age_sec = _runtime_age_seconds(now, telemetry_source_at)
    logger_heartbeat_age_sec = _runtime_age_seconds(now, state.get("logger_heartbeat_at"))
    monitor_heartbeat_age_sec = _runtime_age_seconds(now, state.get("monitor_heartbeat_at"))
    capture_age_sec = _runtime_age_seconds(now, state.get("last_capture_at"))
    capture_event_count = _runtime_int(state.get("capture_event_count"), 0)
    keyboard_event_count = _runtime_int(state.get("keyboard_event_count"), 0)
    mouse_event_count = _runtime_int(state.get("mouse_event_count"), 0)
    telemetry_seq = _runtime_int(state.get("runtime_telemetry_seq"), 0)
    telemetry_fresh = bool(active and telemetry_age_sec is not None and telemetry_age_sec <= 15.0)
    logger_heartbeat_fresh = bool(active and logger_heartbeat_age_sec is not None and logger_heartbeat_age_sec <= 8.0)
    monitor_heartbeat_fresh = bool(active and monitor_heartbeat_age_sec is not None and monitor_heartbeat_age_sec <= 20.0)
    capture_fresh = bool(active and capture_event_count > 0 and capture_age_sec is not None and capture_age_sec <= 10.0)
    live_tick = int(now)
    elapsed_sec = _runtime_elapsed_seconds(now, state.get("started_at")) if active else None
    policy_display = runtime_policy_display_fields(
        state,
        flow=flow,
        active=active,
        technical_failure=technical_failure,
        awaiting_evidence=awaiting_evidence,
        monitor_ready=monitor_ready,
        monitor_heartbeat_fresh=monitor_heartbeat_fresh,
        capture_fresh=capture_fresh,
        elapsed_sec=elapsed_sec,
    )

    if flow == "enrollment_active":
        protected_startup_phase = "enrollment_capture"
    elif logger_failed:
        protected_startup_phase = "logger_failed"
    elif monitor_failed:
        protected_startup_phase = "monitor_failed"
    elif pending_shadow_evidence_start:
        protected_startup_phase = "collecting_evidence" if logger_ready else "starting_logger"
    elif pending_logger_start:
        protected_startup_phase = "starting_logger"
    elif pending_monitor_start and not monitor_ready:
        protected_startup_phase = "starting_monitor" if logger_ready else "starting_logger"
    elif active and technical_failure:
        protected_startup_phase = "logger_failed" if raw_status in {"logger_unavailable", "logger_start_lost", "logger_runtime_error"} else "monitor_failed"
    elif active and awaiting_evidence:
        protected_startup_phase = "collecting_evidence"
    elif active and monitor_ready and not telemetry_fresh:
        protected_startup_phase = "telemetry_unavailable"
    elif active and monitor_ready:
        protected_startup_phase = "live"
    elif active:
        protected_startup_phase = "starting_monitor" if logger_ready else "starting_logger"
    else:
        protected_startup_phase = "idle"

    phase_key = {
        "idle": "runtime_phase_idle",
        "starting_logger": "runtime_phase_starting_logger",
        "starting_monitor": "runtime_phase_starting_monitor",
        "collecting_evidence": "runtime_phase_collecting_evidence",
        "live": "runtime_phase_live",
        "logger_failed": "runtime_phase_logger_failed",
        "monitor_failed": "runtime_phase_monitor_failed",
        "telemetry_unavailable": "runtime_phase_telemetry_unavailable",
        "enrollment_capture": "runtime_phase_enrollment_capture",
    }.get(protected_startup_phase, "runtime_phase_idle")
    phase_status_text = self._t(phase_key)
    runtime_status_text = phase_status_text
    policy_display_phase = str(policy_display.get("runtimeDisplayPhase") or "")
    if protected_startup_phase != "telemetry_unavailable" and (
        policy_display_phase.startswith("shadow_evidence")
        or policy_display_phase in {
            "enrollment_capture",
            "suspicious_lock_delayed",
            "suspicious_warning",
            "waiting_for_settled_evidence",
            "post_resume_verification",
            "lock_confirmed",
            "collecting_quality_evidence",
        }
    ):
        runtime_status_text = str(policy_display.get("runtimeDisplayText") or runtime_status_text)

    decision_text = str(state.get("decision") or ("pending" if active or pending_logger_start or pending_monitor_start else "idle"))
    decision_label = self._t(facade.runtime_decision_key(decision_text))
    if flow == "enrollment_active":
        status_label = "Enrollment active"
        status_detail = str(policy_display.get("evidenceWaitingReasonText") or "Enrollment is recording behavior for profile training.")
        trust_text = "enrollment_capture"
        trust_label = "Capturing behavior"
    elif technical_failure or awaiting_evidence:
        trust_text = raw_status or decision_text or "pending"
        trust_label = status_label
    else:
        trust_text = decision_text
        trust_label = decision_label

    history_sync_pending = bool(getattr(self, "_history_sync_pending", False))
    history_sync_status = str(getattr(self, "_history_sync_status", "") or "").strip()
    history_sync_warning = str(getattr(self, "_history_sync_warning", "") or "").strip()
    history_finalizing = bool(
        history_sync_pending
        and history_sync_status not in {"synced", "archive_unavailable"}
    )
    history_sync_status_text = ""
    if history_finalizing:
        history_sync_status_text = self._t("history_archive_finalizing_delayed" if history_sync_status == "finalizing_delayed" else "history_archive_finalizing")
    elif history_sync_warning:
        history_sync_status_text = self._t(history_sync_warning)

    if history_finalizing:
        runtime_status_text = history_sync_status_text

    if not active:
        status_tone = "warn" if history_finalizing else "neutral"
        trust_tone = "neutral"
    elif technical_failure:
        status_tone = "danger"
        trust_tone = "danger"
    elif restricted:
        status_tone = "danger"
        trust_tone = "danger"
    elif flow == "enrollment_active":
        status_tone = "info"
        trust_tone = "info"
    elif awaiting_evidence:
        status_tone = "warn"
        trust_tone = "warn"
    elif decision_text.lower() == "legit":
        status_tone = "info"
        trust_tone = "success"
    elif decision_text.lower() == "suspicious":
        status_tone = "warn"
        trust_tone = "warn"
    elif decision_text.lower() == "intruder":
        status_tone = "danger"
        trust_tone = "danger"
    else:
        status_tone = "info"
        trust_tone = "info"

    raw_risk_available = state.get("risk") not in (None, "")
    raw_avg_risk_available = state.get("avg_risk") not in (None, "")
    protected_runtime_active = bool(active and flow != "enrollment_active")
    decision_risk_available_for_engine = bool(protected_runtime_active and monitor_ready and telemetry_fresh and not technical_failure and not awaiting_evidence and raw_risk_available)
    avg_risk_available = bool(protected_runtime_active and monitor_ready and telemetry_fresh and not technical_failure and not awaiting_evidence and raw_avg_risk_available)
    if protected_startup_phase in {"collecting_evidence", "telemetry_unavailable"}:
        risk_unavailable_text = phase_status_text
    else:
        risk_unavailable_text = runtime_status_text if protected_startup_phase != "live" else self._t("runtime_phase_telemetry_unavailable")
    avg_risk_unavailable_text = risk_unavailable_text
    avg_risk_text = str(state.get("avg_risk")) if avg_risk_available else "--"
    observed_risk_value = policy_display.get("observed_risk")
    observed_risk_text = str(policy_display.get("observed_risk_text") or "--") if observed_risk_value is not None else "--"
    decision_risk_value = state.get("risk") if decision_risk_available_for_engine else None
    decision_risk_text = _format_user_risk(_runtime_optional_float(decision_risk_value)) if decision_risk_value is not None else "--"
    display_risk_candidate, display_risk_source = _select_user_display_risk(
        state,
        decision_risk_available=decision_risk_available_for_engine,
        observed_risk_value=observed_risk_value,
    )
    display_risk_available = bool(protected_runtime_active and monitor_ready and telemetry_fresh and not technical_failure and display_risk_candidate is not None)
    display_risk_value = _smooth_user_display_risk(self, state, display_risk_candidate) if display_risk_available else None
    display_risk_text = _format_user_risk(display_risk_value) if display_risk_available else "--"
    risk_display_mode = "display_risk" if display_risk_available else "no_risk_available"
    risk_text = display_risk_text
    primary_risk_text = display_risk_text
    primary_risk_is_observed = False
    drift_live_cards = _build_drift_live_cards(
        state,
        active=active,
        technical_failure=technical_failure,
        awaiting_evidence=awaiting_evidence,
        telemetry_fresh=telemetry_fresh,
        capture_fresh=capture_fresh,
        keyboard_event_count=keyboard_event_count,
        mouse_event_count=mouse_event_count,
        risk_text=risk_text,
        avg_risk_text=avg_risk_text,
        runtime_policy_display=policy_display,
    )

    if str(policy_display.get("runtimeDisplayTone") or "") in {"neutral", "info", "warn", "danger", "success"} and not technical_failure and not restricted:
        status_tone = str(policy_display.get("runtimeDisplayTone") or status_tone)
    active_text = runtime_status_text if (active or pending_logger_start or pending_monitor_start or technical_failure or history_finalizing) else self._t("status_idle")
    return {
        **state,
        **policy_display,
        "flow": flow,
        "elapsed": elapsed,
        "statusCode": raw_status,
        "statusLabel": status_label,
        "statusTone": status_tone,
        "statusDetail": status_detail,
        "diagnosticText": diagnostic_text,
        "technicalFailure": technical_failure,
        "awaitingEvidence": awaiting_evidence,
        "protectedStartupPhase": protected_startup_phase,
        "loggerReady": logger_ready,
        "monitorReady": monitor_ready,
        "loggerFailed": logger_failed,
        "monitorFailed": monitor_failed,
        "runtimeStatusText": runtime_status_text,
        "protectedFailureReason": str(state.get("protected_failure_reason") or monitor_error or ""),
        "monitorExitCode": state.get("monitor_exit_code"),
        "processPairState": str(state.get("process_pair_state") or ""),
        "processPairFailed": bool(state.get("process_pair_failed")),
        "loggerStoppedBecauseMonitorFailed": bool(state.get("logger_stopped_because_monitor_failed")),
        "loggerStopAfterMonitorExit": state.get("logger_stop_after_monitor_exit") if isinstance(state.get("logger_stop_after_monitor_exit"), dict) else {},
        "monitorExitStage": str(state.get("monitor_exit_stage") or ""),
        "monitorStartupErrorKind": str(state.get("monitor_startup_error_kind") or ""),
        "monitorStartExitReason": str(state.get("monitor_start_exit_reason") or ""),
        "monitorExitReason": str(state.get("monitor_exit_reason") or ""),
        "monitorExitDetail": dict(state.get("monitor_exit_detail") or {}) if isinstance(state.get("monitor_exit_detail"), dict) else {},
        "monitorStartStateStatus": state.get("monitor_start_state_status"),
        "monitorStartStateActive": state.get("monitor_start_state_active"),
        "monitorStartStateSessionId": state.get("monitor_start_state_session_id"),
        "riskAvailable": display_risk_available,
        "avgRiskAvailable": avg_risk_available,
        "observedRiskAvailable": bool(observed_risk_value is not None),
        "observedRiskText": observed_risk_text,
        "observedRiskSource": str(policy_display.get("observed_risk_source") or ""),
        "observedRiskReasonCodes": list(policy_display.get("observed_risk_reason_codes") or []),
        "observedRiskQualityOk": policy_display.get("observed_risk_quality_ok"),
        "observedRiskQualityLockOk": policy_display.get("observed_risk_quality_lock_ok"),
        "observedRiskDecisionQualified": bool(policy_display.get("observed_risk_decision_qualified")),
        "observedRiskDisplayOnly": True,
        "decisionRiskAvailable": bool(decision_risk_value is not None),
        "displayRiskAvailable": bool(display_risk_available),
        "displayRiskText": display_risk_text,
        "displayRiskValue": display_risk_value,
        "displayRiskSource": display_risk_source,
        "decisionRiskText": decision_risk_text,
        "decisionRiskSource": "state.risk" if decision_risk_value is not None else "",
        "riskDisplayMode": risk_display_mode,
        "riskUnavailableText": risk_unavailable_text,
        "avgRiskUnavailableText": avg_risk_unavailable_text,
        "activeText": active_text,
        "decisionText": decision_text,
        "decisionLabel": decision_label,
        "trustText": trust_text,
        "trustLabel": trust_label,
        "trustTone": trust_tone,
        "riskText": primary_risk_text,
        "riskTextIsObserved": False,
        "primaryRiskText": primary_risk_text,
        "avgRiskText": avg_risk_text,
        "driftLiveCards": drift_live_cards,
        "telemetryAgeSec": telemetry_age_sec,
        "telemetryFresh": telemetry_fresh,
        "loggerHeartbeatAgeSec": logger_heartbeat_age_sec,
        "loggerHeartbeatFresh": logger_heartbeat_fresh,
        "monitorHeartbeatAgeSec": monitor_heartbeat_age_sec,
        "monitorHeartbeatFresh": monitor_heartbeat_fresh,
        "captureAgeSec": capture_age_sec,
        "captureFresh": capture_fresh,
        "captureEventCount": capture_event_count,
        "keyboardEventCount": keyboard_event_count,
        "mouseEventCount": mouse_event_count,
        "telemetrySeq": telemetry_seq,
        "liveTick": live_tick,
        "runtimeTelemetrySource": str(state.get("runtime_telemetry_source") or state.get("source") or ""),
        "historySyncPending": history_sync_pending,
        "historyFinalizing": history_finalizing,
        "historySyncStatus": history_sync_status,
        "historySyncStatusText": history_sync_status_text,
        "historySyncWarning": history_sync_warning,
        "updatedAt": state.get("updated_at"),
        "loggerHeartbeatAt": state.get("logger_heartbeat_at"),
        "monitorHeartbeatAt": state.get("monitor_heartbeat_at"),
        "lastCaptureAt": state.get("last_capture_at"),
        "shadowEvidenceMonitorStatus": ("skipped" if str(getattr(self, "_last_shadow_evidence_monitor_skipped_reason", "") or "") else ("pending" if pending_shadow_evidence_start else ("running" if str(state.get("session_kind") or "").strip().lower() == "shadow_evidence" and active else "blocked" if str(getattr(self, "_last_shadow_evidence_monitor_block_reason", "") or "") else "idle"))),
        "shadowEvidenceBlockedReason": str(getattr(self, "_last_shadow_evidence_monitor_block_reason", "") or state.get("shadow_evidence_blocked_reason") or ""),
        "shadowMonitorSkippedReason": str(getattr(self, "_last_shadow_evidence_monitor_skipped_reason", "") or state.get("shadow_monitor_skipped_reason") or ""),
        "shadow_monitor_skipped_reason": str(getattr(self, "_last_shadow_evidence_monitor_skipped_reason", "") or state.get("shadow_monitor_skipped_reason") or ""),
        "shadowEvidenceWindowsCollected": _runtime_int(state.get("runtime_window_count"), 0),
        "shadowEvidenceReasonCodes": list(state.get("runtime_lock_safety_reasons") or state.get("production_evidence_reason_codes") or []),
        "shadowEvidenceNextAction": "collect_shadow_runtime_evidence" if pending_shadow_evidence_start or str(state.get("session_kind") or "").strip().lower() == "shadow_evidence" else "",
        "retryHandoffState": str(state.get("retry_handoff_state") or getattr(self, "_retry_handoff_state", "") or "idle"),
        "retryHandoffBlockers": list(state.get("retry_handoff_blockers") or getattr(self, "_retry_handoff_blockers", []) or []),
        "retryHandoffLastError": str(state.get("retry_handoff_last_error") or getattr(self, "_retry_handoff_last_error", "") or ""),
        "shadowEvidenceStoppedForRetry": bool(state.get("shadow_evidence_stopped_for_retry") or getattr(self, "_shadow_evidence_stopped_for_retry", False)),
    }
