from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

_RUNTIME_TECHNICAL_FAILURE_STATUSES = {
    "logger_unavailable",
    "logger_start_lost",
    "monitor_unavailable",
    "model_unavailable",
    "metadata_invalid",
    "artifact_integrity_failed",
    "input_read_failed",
    "prediction_failed",
    "monitor_runtime_error",
    "monitor_exited_after_ready",
    "monitor_process_lost",
    "monitor_start_session_inactive",
    "monitor_start_session_id_mismatch",
    "monitor_start_stop_requested",
    "monitor_start_runtime_exception",
    "monitor_start_stale_lock_recovered",
    "risk_engine_stopped",
    "failed",
    "logger_runtime_error",
    "logger_exited_after_ready",
}

_RUNTIME_AWAITING_EVIDENCE_STATUSES = {"insufficient_windows", "insufficient_evidence", "transitioning"}


def runtime_status_is_technical_failure(status: Any) -> bool:
    return str(status or "").strip().lower() in _RUNTIME_TECHNICAL_FAILURE_STATUSES


def runtime_status_awaits_evidence(status: Any) -> bool:
    return str(status or "").strip().lower() in _RUNTIME_AWAITING_EVIDENCE_STATUSES


def runtime_status_key(status: Any, *, active: bool = False, restricted: bool = False) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "resume_pending":
        return "runtime_status_resume_pending"
    if normalized == "verifying_return":
        return "runtime_status_verifying_return"
    if restricted:
        return "status_restricted"
    if not active:
        return "status_idle"
    if normalized == "transitioning":
        return "runtime_status_transitioning"
    if normalized in _RUNTIME_AWAITING_EVIDENCE_STATUSES:
        return "runtime_status_collecting_evidence"
    if normalized in {"logger_unavailable", "logger_start_lost", "logger_runtime_error", "logger_exited_after_ready"}:
        return "runtime_status_logger_unavailable"
    if normalized in {"monitor_unavailable", "monitor_exited_after_ready", "monitor_process_lost", "monitor_start_session_inactive", "monitor_start_session_id_mismatch", "monitor_start_stop_requested", "monitor_start_runtime_exception", "monitor_start_stale_lock_recovered", "risk_engine_stopped"}:
        return "runtime_status_monitor_unavailable"
    if normalized == "model_unavailable":
        return "runtime_status_model_unavailable"
    if normalized == "metadata_invalid":
        return "runtime_status_metadata_invalid"
    if normalized == "artifact_integrity_failed":
        return "runtime_status_artifact_integrity_failed"
    if normalized == "input_read_failed":
        return "runtime_status_input_read_failed"
    if normalized == "prediction_failed":
        return "runtime_status_prediction_failed"
    if normalized in {"monitor_runtime_error", "failed"}:
        return "runtime_status_monitor_runtime_error"
    return "status_active"


def runtime_status_detail_key(status: Any) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "resume_pending":
        return "runtime_detail_resume_pending"
    if normalized == "verifying_return":
        return "runtime_detail_verifying_return"
    if normalized == "transitioning":
        return "runtime_detail_transitioning"
    if normalized in _RUNTIME_AWAITING_EVIDENCE_STATUSES:
        return "runtime_detail_collecting_evidence"
    if normalized == "logger_exited_after_ready":
        return "runtime_detail_logger_exited_after_ready"
    if normalized in {"logger_unavailable", "logger_start_lost", "logger_runtime_error"}:
        return "runtime_detail_logger_unavailable"
    if normalized in {"monitor_exited_after_ready", "risk_engine_stopped"}:
        return "runtime_detail_monitor_exited_after_ready"
    if normalized == "monitor_start_session_inactive":
        return "runtime_detail_monitor_start_session_inactive"
    if normalized == "monitor_start_session_id_mismatch":
        return "runtime_detail_monitor_start_session_id_mismatch"
    if normalized == "monitor_start_stop_requested":
        return "runtime_detail_monitor_start_stop_requested"
    if normalized == "monitor_start_runtime_exception":
        return "runtime_detail_monitor_start_runtime_exception"
    if normalized == "monitor_start_stale_lock_recovered":
        return "runtime_detail_monitor_start_stale_lock_recovered"
    if normalized == "monitor_process_lost":
        return "runtime_detail_monitor_process_lost"
    if normalized == "monitor_unavailable":
        return "runtime_detail_monitor_unavailable"
    if normalized == "model_unavailable":
        return "runtime_detail_model_unavailable"
    if normalized == "metadata_invalid":
        return "runtime_detail_metadata_invalid"
    if normalized == "artifact_integrity_failed":
        return "runtime_detail_artifact_integrity_failed"
    if normalized == "input_read_failed":
        return "runtime_detail_input_read_failed"
    if normalized == "prediction_failed":
        return "runtime_detail_prediction_failed"
    if normalized in {"monitor_runtime_error", "failed"}:
        return "runtime_detail_monitor_runtime_error"
    return ""


_LOCK_SUPPRESSION_TEXTS: Dict[str, Tuple[str, str]] = {
    "lock_suppressed_by_recovery_cooldown": (
        "recovery_cooldown",
        "Locking is temporarily delayed during recovery cooldown after unlock to avoid an immediate false lock.",
    ),
    "lock_suppressed_by_mouse_fallback_guard": (
        "mouse_heavy_guard",
        "Mouse-heavy evidence is treated conservatively and needs stronger confirmation before lock.",
    ),
    "lock_suppressed_by_current_window_not_lock_quality": (
        "current_window_not_lock_quality",
        "The latest window is not lock-quality evidence yet.",
    ),
    "lock_suppressed_by_low_quality_window": (
        "current_window_not_lock_quality",
        "The latest window is not lock-quality evidence yet.",
    ),
    "lock_suppressed_by_startup_window": (
        "startup_window",
        "BioAuth is ignoring startup-only evidence until the session has enough settled behavior.",
    ),
    "lock_suppressed_by_session_start_window": (
        "session_start_window",
        "The current evidence comes from the session start and is not lock-quality yet.",
    ),
    "lock_suppressed_by_transition_window": (
        "transition_window",
        "BioAuth detected an activity transition and is waiting for settled evidence before escalating.",
    ),
    "lock_suppressed_by_post_idle_window": (
        "transition_window",
        "BioAuth detected an activity transition and is waiting for settled evidence before escalating.",
    ),
    "lock_suppressed_by_calibration_immature": (
        "conservative_mode_threshold",
        "Conservative runtime policy requires stronger calibrated evidence before locking.",
    ),
}

_EVIDENCE_REASON_TEXTS: Dict[str, str] = {
    "pending_state": "BioAuth is still collecting enough live behavioral evidence before making a trust decision.",
    "insufficient_windows": "BioAuth is waiting for the first complete live behavior windows.",
    "insufficient_evidence": "Live capture is active, but the monitor needs more quality-approved windows before it can lock.",
    "startup_window": "BioAuth is ignoring startup-only evidence until the session has enough settled behavior.",
    "session_start_window": "The current evidence comes from the session start and is not lock-quality yet.",
    "transition_window": "BioAuth detected an activity transition and is waiting for settled evidence before escalating.",
    "short_window": "The current behavior window is too short for a lock decision.",
    "transitioning": "BioAuth is waiting for settled evidence after an activity transition.",
    "lock_suppressed_by_recovery_cooldown": "Locking is temporarily delayed during recovery cooldown after unlock to avoid an immediate false lock.",
    "lock_suppressed_by_mouse_fallback_guard": "Mouse-heavy evidence is treated conservatively and needs stronger confirmation before lock.",
    "lock_suppressed_by_current_window_not_lock_quality": "The latest window is not lock-quality evidence yet.",
    "risk_below_lock_threshold": "Suspicious behavior was detected, but current risk is below the configured lock threshold.",
    "conservative_mode_threshold": "Conservative mode requires stronger evidence before locking.",
    "warning_followup_lock": "High-risk behavior was confirmed by follow-up evidence.",
    "post_resume_verification": "BioAuth resumed protection and is verifying the returning user with fresh evidence.",
}

_REASON_PRIORITY = (
    "post_resume_verification",
    "lock_suppressed_by_recovery_cooldown",
    "lock_suppressed_by_mouse_fallback_guard",
    "transition_window",
    "transitioning",
    "startup_window",
    "session_start_window",
    "short_window",
    "lock_suppressed_by_current_window_not_lock_quality",
    "insufficient_windows",
    "insufficient_evidence",
    "risk_below_lock_threshold",
    "conservative_mode_threshold",
    "pending_state",
)


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def _risk_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return max(0.0, min(100.0, number))


def _risk_text(value: Any) -> str:
    number = _risk_float(value)
    if number is None:
        return "--"
    if abs(number - round(number)) < 0.05:
        return str(int(round(number)))
    return f"{number:.1f}".rstrip("0").rstrip(".")


def _observed_risk_candidate(value: Any, source: str, *, reason_codes: Any = None, quality_ok: Any = None, quality_lock_ok: Any = None) -> Dict[str, Any] | None:
    risk = _risk_float(value)
    if risk is None:
        return None
    return {
        "observed_risk": risk,
        "observed_risk_source": source,
        "observed_risk_reason_codes": _unique_codes(reason_codes or []),
        "observed_risk_quality_ok": None if quality_ok is None else _bool(quality_ok),
        "observed_risk_quality_lock_ok": None if quality_lock_ok is None else _bool(quality_lock_ok),
    }


def _observed_decision_qualified(state: Dict[str, Any], observed: Dict[str, Any]) -> bool:
    status = _lower(state.get("status") or state.get("statusCode"))
    decision = _lower(state.get("decision") or state.get("decisionText"))
    if status in {"", "insufficient_evidence", "insufficient_windows", "transitioning", "verifying_return", "resume_pending"}:
        return False
    if decision in {"", "pending", "monitoring", "starting", "idle", "inactive", "stopped"}:
        return False
    quality_lock_ok = observed.get("observed_risk_quality_lock_ok")
    if quality_lock_ok is False:
        return False
    blockers = {
        "insufficient_evidence",
        "insufficient_windows",
        "transition_window",
        "transitioning",
        "post_idle_window",
        "startup_window",
        "session_start_window",
        "short_window",
        "lock_suppressed_by_current_window_not_lock_quality",
        "lock_suppressed_by_low_quality_window",
    }
    codes = set(_unique_codes(observed.get("observed_risk_reason_codes") or [], _window_reason_codes(state)))
    if codes.intersection(blockers):
        return False
    return True


def extract_observed_risk(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return display-only observed risk fields without affecting runtime decisions.

    Observed risk is the latest/highest model-window score visible in runtime
    diagnostics, even when the window is not decision-qualified. It must never
    be used by callers to request lock or change decisions.
    """

    state = state if isinstance(state, dict) else {}
    last_window = state.get("runtime_last_window_diag") if isinstance(state.get("runtime_last_window_diag"), dict) else {}
    candidates: List[Dict[str, Any]] = []
    if last_window:
        for key in ("risk", "base_risk"):
            candidate = _observed_risk_candidate(
                last_window.get(key),
                f"runtime_last_window_diag.{key}",
                reason_codes=(last_window.get("reason_codes") or []) + (last_window.get("quality_reason_codes") or []),
                quality_ok=last_window.get("quality_ok"),
                quality_lock_ok=last_window.get("quality_lock_ok"),
            )
            if candidate is not None:
                candidates.append(candidate)

    top_windows = state.get("runtime_top_risky_windows")
    if isinstance(top_windows, list):
        best: Dict[str, Any] | None = None
        for window in top_windows:
            if not isinstance(window, dict):
                continue
            for key in ("risk", "base_risk"):
                candidate = _observed_risk_candidate(
                    window.get(key),
                    "runtime_top_risky_windows.max",
                    reason_codes=(window.get("reason_codes") or []) + (window.get("quality_reason_codes") or []),
                    quality_ok=window.get("quality_ok"),
                    quality_lock_ok=window.get("quality_lock_ok"),
                )
                if candidate is not None and (best is None or float(candidate["observed_risk"]) > float(best["observed_risk"])):
                    best = candidate
        if best is not None:
            candidates.append(best)

    if not candidates:
        observed = {
            "observed_risk": None,
            "observed_risk_source": "",
            "observed_risk_reason_codes": [],
            "observed_risk_quality_ok": None,
            "observed_risk_quality_lock_ok": None,
        }
    else:
        # Prefer the most recent window diagnostic when available; fall back to
        # the highest top-risky-window score when no latest diagnostic exists.
        observed = candidates[0] if candidates[0]["observed_risk_source"].startswith("runtime_last_window_diag") else max(candidates, key=lambda item: float(item["observed_risk"]))

    observed["observed_risk_decision_qualified"] = _observed_decision_qualified(state, observed) if observed.get("observed_risk") is not None else False
    observed["observed_risk_display_only"] = True
    observed["observed_risk_text"] = _risk_text(observed.get("observed_risk")) if observed.get("observed_risk") is not None else "--"
    return observed


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _unique_codes(*groups: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for group in groups:
        if not isinstance(group, (list, tuple, set)):
            continue
        for item in group:
            code = _lower(item)
            if code and code not in seen:
                seen.add(code)
                result.append(code)
    return result


def _window_reason_codes(state: Dict[str, Any]) -> List[str]:
    last_window = state.get("runtime_last_window_diag") if isinstance(state.get("runtime_last_window_diag"), dict) else {}
    return _unique_codes(
        (last_window or {}).get("reason_codes") or [],
        (last_window or {}).get("quality_reason_codes") or [],
        state.get("runtime_lock_safety_reasons") or [],
    )


def _first_known_reason(codes: Iterable[str]) -> str:
    code_list = [_lower(code) for code in codes if _lower(code)]
    code_set = set(code_list)
    for code in _REASON_PRIORITY:
        if code in code_set:
            return code
    return code_list[0] if code_list else ""


def _normalize_suppression_rule(rule: str) -> tuple[str, str]:
    normalized = _lower(rule)
    if normalized in _LOCK_SUPPRESSION_TEXTS:
        return _LOCK_SUPPRESSION_TEXTS[normalized]
    if normalized.startswith("lock_suppressed_by_"):
        suffix = normalized.removeprefix("lock_suppressed_by_")
        if suffix in _EVIDENCE_REASON_TEXTS:
            return suffix, _EVIDENCE_REASON_TEXTS[suffix]
        return suffix or normalized, "Locking is delayed by the active runtime safety policy."
    if normalized in _EVIDENCE_REASON_TEXTS:
        return normalized, _EVIDENCE_REASON_TEXTS[normalized]
    return normalized or "", ""


def runtime_policy_display_fields(
    state: Dict[str, Any],
    *,
    flow: str = "",
    active: bool | None = None,
    technical_failure: bool = False,
    awaiting_evidence: bool | None = None,
    monitor_ready: bool = False,
    monitor_heartbeat_fresh: bool = False,
    capture_fresh: bool = False,
    elapsed_sec: float | None = None,
) -> Dict[str, Any]:
    """Map monitor/backend policy fields to user-safe display fields.

    This function does not change decisions, thresholds, gates, or lock policy.
    It only explains the current backend state for QML/runtimeState consumers.
    """

    state = state if isinstance(state, dict) else {}
    flow_norm = _lower(flow)
    session_kind = _lower(state.get("session_kind"))
    active_bool = _bool(state.get("active")) if active is None else bool(active)
    status = _lower(state.get("status") or state.get("statusCode"))
    decision = _lower(state.get("decision") or state.get("decisionText"))
    confirmation_rule = _lower(state.get("runtime_confirmation_rule"))
    locking_allowed = _bool(state.get("runtime_locking_allowed", True))
    suppressed_for = max(0.0, _float(state.get("runtime_lock_suppressed_for_sec"), 0.0))
    window_count = _int(state.get("runtime_window_count"), 0)
    quality_lock_ok_windows = _int(state.get("runtime_quality_lock_ok_windows"), 0)
    warning_count = _int(state.get("runtime_warning_count", state.get("warning_count", 0)), 0)
    transition_status = _lower(state.get("runtime_transition_status"))
    transition_active = _bool(state.get("runtime_transition_active")) or transition_status == "transitioning"
    mouse_guard_active = _bool(state.get("runtime_mouse_guard_active"))
    reason_codes = _window_reason_codes(state)
    awaiting_bool = bool(runtime_status_awaits_evidence(status) or _bool(state.get("awaiting_evidence"))) if awaiting_evidence is None else bool(awaiting_evidence)
    post_resume = status in {"verifying_return", "resume_pending"} or _bool(state.get("auto_resume_pending") or state.get("resume_after_unlock"))
    shadow_evidence_mode = bool(
        session_kind == "shadow_evidence"
        or flow_norm.startswith("shadow_evidence")
        or _lower(state.get("runtime_mode")) == "shadow_evidence"
        or _bool(state.get("shadow_evidence_only"))
    )
    observed_risk_fields = extract_observed_risk(state)

    if session_kind == "enrollment" or flow_norm == "enrollment_active":
        return {
            "runtimeDisplayPhase": "enrollment_capture",
            "runtimeDisplayText": "Enrollment active · Capturing behavior",
            "runtimeDisplayTone": "info",
            "lockSuppressionActive": False,
            "lockSuppressionReasonCode": "",
            "lockSuppressionReasonText": "",
            "lockSuppressionTone": "neutral",
            "lockSuppressionSecondsRemaining": 0.0,
            "escalationState": "enrollment_capture",
            "escalationPolicyText": "Enrollment captures behavior for training; monitor risk decisions are not run during enrollment.",
            "canLockNow": False,
            "lockBlockedBy": "enrollment_capture",
            "evidenceWaitingReasonCode": "",
            "evidenceWaitingReasonText": "Enrollment is recording behavior for profile training, not making live lock decisions.",
            "evidenceStallActive": False,
            "evidenceStallReasonCode": "",
            "evidenceStallReasonText": "",
            "postResumeVerificationActive": False,
            "secondsSinceLastRuntimeWindow": None,
            "expectedNextWindowHint": "Stop enrollment when enough behavior has been captured.",
        }

    if not active_bool:
        return {
            "runtimeDisplayPhase": "idle",
            "runtimeDisplayText": "Protection idle",
            "runtimeDisplayTone": "neutral",
            "lockSuppressionActive": False,
            "lockSuppressionReasonCode": "",
            "lockSuppressionReasonText": "",
            "lockSuppressionTone": "neutral",
            "lockSuppressionSecondsRemaining": 0.0,
            "escalationState": "idle",
            "escalationPolicyText": "Start protected mode to monitor live behavior.",
            "canLockNow": False,
            "lockBlockedBy": "inactive",
            "evidenceWaitingReasonCode": "",
            "evidenceWaitingReasonText": "",
            "evidenceStallActive": False,
            "evidenceStallReasonCode": "",
            "evidenceStallReasonText": "",
            "postResumeVerificationActive": False,
            "secondsSinceLastRuntimeWindow": None,
            "expectedNextWindowHint": "Start protected mode to collect runtime windows.",
        }

    if technical_failure:
        monitor_exit = status in {"monitor_exited_after_ready", "risk_engine_stopped"} or _bool(state.get("risk_engine_stopped"))
        return {
            "runtimeDisplayPhase": "technical_failure",
            "runtimeDisplayText": "Risk engine stopped" if monitor_exit else "Monitor needs attention",
            "runtimeDisplayTone": "danger",
            "lockSuppressionActive": False,
            "lockSuppressionReasonCode": "technical_failure",
            "lockSuppressionReasonText": "Runtime locking is unavailable until the monitor error is resolved.",
            "lockSuppressionTone": "danger",
            "lockSuppressionSecondsRemaining": 0.0,
            "escalationState": "technical_failure",
            "escalationPolicyText": "BioAuth surfaces monitor failures instead of fabricating decisions.",
            "canLockNow": False,
            "lockBlockedBy": "technical_failure",
            "evidenceWaitingReasonCode": "technical_failure",
            "evidenceWaitingReasonText": "Runtime evidence is unavailable because the risk monitor stopped." if monitor_exit else "Runtime evidence is unavailable because the monitor reported a technical failure.",
            "evidenceStallActive": False,
            "evidenceStallReasonCode": "",
            "evidenceStallReasonText": "",
            "postResumeVerificationActive": False,
            "secondsSinceLastRuntimeWindow": None,
            "expectedNextWindowHint": "Resolve the monitor diagnostic, then resume protected mode.",
        }

    candidate_codes: List[str] = []
    if post_resume:
        candidate_codes.append("post_resume_verification")
    if confirmation_rule:
        candidate_codes.append(confirmation_rule)
    if transition_active:
        candidate_codes.append("transitioning")
    candidate_codes.extend(reason_codes)
    if mouse_guard_active:
        candidate_codes.append("lock_suppressed_by_mouse_fallback_guard")
    if status in {"insufficient_windows", "insufficient_evidence", "transitioning"}:
        candidate_codes.append(status)
    if window_count <= 0:
        candidate_codes.append("insufficient_windows")
    if quality_lock_ok_windows <= 0 and window_count > 0:
        candidate_codes.append("lock_suppressed_by_current_window_not_lock_quality")
    if awaiting_bool and not candidate_codes:
        candidate_codes.append("pending_state")

    primary_reason = _first_known_reason(candidate_codes)
    if confirmation_rule.startswith("lock_suppressed_by_"):
        suppression_code, suppression_text = _normalize_suppression_rule(confirmation_rule)
    elif not locking_allowed or suppressed_for > 0:
        reason_for_suppression = primary_reason or "lock_suppressed_by_recovery_cooldown"
        suppression_code, suppression_text = _normalize_suppression_rule(reason_for_suppression)
    elif mouse_guard_active:
        suppression_code, suppression_text = _normalize_suppression_rule("lock_suppressed_by_mouse_fallback_guard")
    else:
        suppression_code, suppression_text = "", ""

    lock_suppression_active = bool(suppression_code and (not locking_allowed or suppressed_for > 0 or confirmation_rule.startswith("lock_suppressed_by_") or mouse_guard_active))
    if not suppression_text and suppression_code:
        suppression_text = _EVIDENCE_REASON_TEXTS.get(suppression_code, "Locking is delayed by the active runtime safety policy.")

    evidence_code = primary_reason
    if not evidence_code and status in {"ok", "legit", "legitimate"}:
        evidence_text = "Runtime evidence is live."
    else:
        evidence_text = _EVIDENCE_REASON_TEXTS.get(evidence_code, "BioAuth is still collecting enough live behavioral evidence before making a trust decision.")

    if decision == "intruder" or flow_norm == "protected_forced_stop" or confirmation_rule == "warning_followup_lock":
        display_phase = "lock_confirmed"
        display_text = "Lock confirmed · High-risk behavior confirmed"
        display_tone = "danger"
        escalation_state = "confirmed_intruder"
        policy_text = _EVIDENCE_REASON_TEXTS["warning_followup_lock"] if confirmation_rule == "warning_followup_lock" else "BioAuth confirmed high-risk behavior from backend monitor evidence."
    elif decision == "suspicious" and lock_suppression_active:
        display_phase = "suspicious_lock_delayed"
        display_text = "Suspicious · lock delayed by policy"
        display_tone = "warn"
        escalation_state = "lock_suppressed"
        policy_text = suppression_text or evidence_text
    elif decision == "suspicious":
        display_phase = "suspicious_warning"
        display_text = "Suspicious · warning active"
        display_tone = "warn"
        escalation_state = "warning_active"
        if locking_allowed:
            policy_text = "Warning state is active; BioAuth is waiting for follow-up evidence required by the current lock policy."
        else:
            policy_text = suppression_text or "Suspicious behavior was detected, but the current policy is delaying lock."
    elif post_resume:
        display_phase = "post_resume_verification"
        display_text = "Verifying return · waiting for fresh evidence"
        display_tone = "warn"
        escalation_state = "post_resume_verification"
        policy_text = _EVIDENCE_REASON_TEXTS["post_resume_verification"]
        evidence_code = "post_resume_verification"
        evidence_text = policy_text
    elif transition_active or evidence_code in {"transition_window", "transitioning"}:
        display_phase = "waiting_for_settled_evidence"
        display_text = "Collecting evidence · waiting for settled behavior"
        display_tone = "warn"
        escalation_state = "waiting_for_settled_evidence"
        policy_text = evidence_text
    elif awaiting_bool or window_count <= 0 or quality_lock_ok_windows <= 0:
        display_phase = "collecting_quality_evidence"
        display_text = "Collecting evidence · waiting for lock-quality windows"
        display_tone = "warn"
        escalation_state = "awaiting_quality_evidence"
        policy_text = evidence_text
    elif decision in {"legit", "legitimate", "accepted", "safe"}:
        display_phase = "live_legit"
        display_text = "Live protected · Legit"
        display_tone = "success"
        escalation_state = "legit"
        policy_text = "Runtime evidence is live and currently matches the enrolled user."
    else:
        display_phase = "live_monitoring"
        display_text = "Live protected · Monitoring"
        display_tone = "info"
        escalation_state = "monitoring"
        policy_text = evidence_text or "Runtime evidence is live."

    seconds_since_window = None
    if state.get("runtime_last_window_at") not in (None, "") and state.get("now") not in (None, ""):
        seconds_since_window = max(0.0, _float(state.get("now")) - _float(state.get("runtime_last_window_at")))
    elif state.get("runtime_last_window_age_sec") not in (None, ""):
        seconds_since_window = max(0.0, _float(state.get("runtime_last_window_age_sec")))
    elif window_count <= 0 and elapsed_sec is not None:
        seconds_since_window = max(0.0, float(elapsed_sec))

    stall_active = bool(
        active_bool
        and monitor_ready
        and monitor_heartbeat_fresh
        and capture_fresh
        and not technical_failure
        and (window_count <= 0)
        and seconds_since_window is not None
        and seconds_since_window >= 45.0
    )
    stall_code = "waiting_for_runtime_windows" if stall_active else ""
    stall_text = "Live capture is fresh, but the monitor has not published a complete runtime window yet." if stall_active else ""

    can_lock_now = bool(locking_allowed and not lock_suppression_active and not awaiting_bool and decision in {"suspicious", "intruder"})
    if lock_suppression_active:
        lock_blocked_by = suppression_code
    elif awaiting_bool or display_phase.startswith("collecting") or display_phase == "waiting_for_settled_evidence":
        lock_blocked_by = evidence_code or "awaiting_quality_evidence"
    elif not locking_allowed:
        lock_blocked_by = "runtime_policy"
    elif decision not in {"suspicious", "intruder"}:
        lock_blocked_by = "not_alert_state"
    else:
        lock_blocked_by = ""

    if warning_count > 0 and decision == "suspicious" and not lock_suppression_active:
        policy_text = f"Warning state is active with {warning_count} warning(s); BioAuth needs follow-up evidence before locking."

    decision_risk_number = _risk_float(state.get("risk"))
    decision_risk_available = bool(
        decision_risk_number is not None
        and decision not in {"", "pending", "monitoring", "starting", "idle", "inactive", "stopped"}
        and not awaiting_bool
        and status not in {"insufficient_windows", "insufficient_evidence", "transitioning", "verifying_return", "resume_pending"}
    )
    decision_risk = decision_risk_number if decision_risk_available else None
    observed_risk = observed_risk_fields.get("observed_risk")
    if decision_risk is not None:
        risk_display_mode = "decision_risk"
    elif observed_risk is not None:
        risk_display_mode = "observed_risk_pending"
    else:
        risk_display_mode = "no_risk_available"

    if (
        not shadow_evidence_mode
        and decision_risk is None
        and observed_risk is not None
        and display_phase in {
            "post_resume_verification",
            "waiting_for_settled_evidence",
            "collecting_quality_evidence",
            "live_monitoring",
        }
    ):
        # Hotfix 7V: keep observed/decision details internal. The user UI
        # gets one smoothed Risk value from dashboard runtime metrics.
        risk_display_mode = "display_risk_pending"

    if shadow_evidence_mode:
        if decision in {"suspicious", "warning", "warn"}:
            display_phase = "shadow_evidence_simulated_warning"
            display_text = "Shadow evidence · Suspicious simulated"
            display_tone = "warn"
            escalation_state = "shadow_evidence_simulated_warning"
        elif decision in {"intruder", "blocked", "restricted", "lock", "locked"}:
            display_phase = "shadow_evidence_simulated_lock"
            display_text = "Shadow evidence · Would lock simulated"
            display_tone = "warn"
            escalation_state = "shadow_evidence_simulated_lock"
        elif decision in {"legit", "legitimate", "accepted", "safe"}:
            display_phase = "shadow_evidence_live_legit"
            display_text = "Shadow evidence · Legit"
            display_tone = "success"
            escalation_state = "shadow_evidence_legit"
        elif awaiting_bool or window_count <= 0 or quality_lock_ok_windows <= 0:
            display_phase = "shadow_evidence_collecting"
            display_text = "Shadow monitor · Pending · waiting for evidence"
            display_tone = "warn"
            escalation_state = "shadow_evidence_collecting"
        else:
            display_phase = "shadow_evidence_monitoring"
            display_text = "Shadow monitor · Simulated only"
            display_tone = "info"
            escalation_state = "shadow_evidence_monitoring"
        policy_text = (policy_text + " " if policy_text else "") + "Shadow evidence is simulated only; Protected Sessions and lock enforcement remain disabled."
        can_lock_now = False
        lock_blocked_by = "shadow_evidence_simulated_only"
        if candidate_codes and not evidence_code:
            evidence_code = primary_reason
        if not evidence_text or "live behavioral evidence" in evidence_text:
            evidence_text = "Shadow monitor is collecting simulated runtime evidence without enabling lock enforcement."

    return {
        "runtimeDisplayPhase": display_phase,
        "runtimeDisplayText": display_text,
        "runtimeDisplayTone": display_tone,
        "observed_risk": observed_risk_fields.get("observed_risk"),
        "observed_risk_source": observed_risk_fields.get("observed_risk_source", ""),
        "observed_risk_reason_codes": list(observed_risk_fields.get("observed_risk_reason_codes") or []),
        "observed_risk_quality_ok": observed_risk_fields.get("observed_risk_quality_ok"),
        "observed_risk_quality_lock_ok": observed_risk_fields.get("observed_risk_quality_lock_ok"),
        "observed_risk_decision_qualified": bool(observed_risk_fields.get("observed_risk_decision_qualified")),
        "observed_risk_display_only": True,
        "observed_risk_text": observed_risk_fields.get("observed_risk_text", "--"),
        "decision_risk": decision_risk,
        "decision_risk_source": "state.risk" if decision_risk is not None else "",
        "risk_display_mode": risk_display_mode,
        "lockSuppressionActive": lock_suppression_active,
        "lockSuppressionReasonCode": suppression_code,
        "lockSuppressionReasonText": suppression_text,
        "lockSuppressionTone": "warn" if lock_suppression_active else "neutral",
        "lockSuppressionSecondsRemaining": round(suppressed_for, 1),
        "escalationState": escalation_state,
        "escalationPolicyText": policy_text,
        "canLockNow": can_lock_now,
        "lockBlockedBy": lock_blocked_by,
        "evidenceWaitingReasonCode": evidence_code,
        "evidenceWaitingReasonText": evidence_text,
        "evidenceStallActive": stall_active,
        "evidenceStallReasonCode": stall_code,
        "evidenceStallReasonText": stall_text,
        "postResumeVerificationActive": bool(post_resume),
        "secondsSinceLastRuntimeWindow": round(seconds_since_window, 1) if seconds_since_window is not None else None,
        "expectedNextWindowHint": "Keep using the device naturally so BioAuth can publish the next complete lock-quality behavior window.",
    }


def runtime_decision_key(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"legit", "legitimate", "accepted", "safe"}:
        return "decision_legit"
    if normalized in {"suspicious", "warning", "warn"}:
        return "decision_suspicious"
    if normalized in {"intruder", "blocked", "restricted", "lock", "locked"}:
        return "decision_intruder"
    if normalized in {"pending", "monitoring", "starting"}:
        return "decision_pending"
    if normalized in {"", "idle", "inactive", "stopped"}:
        return "decision_idle"
    return "decision_unknown"


__all__ = [
    "extract_observed_risk",
    "runtime_decision_key",
    "runtime_policy_display_fields",
    "runtime_status_awaits_evidence",
    "runtime_status_detail_key",
    "runtime_status_is_technical_failure",
    "runtime_status_key",
]
