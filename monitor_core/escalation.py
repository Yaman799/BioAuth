from __future__ import annotations

import time
from collections import deque
from importlib import import_module
from typing import Any, Dict, Optional

try:
    from app_settings import demo_classic_protected_enabled
except Exception:  # pragma: no cover - demo helper must fail closed
    def demo_classic_protected_enabled(*_args: Any, **_kwargs: Any) -> bool:
        return False


def _facade():
    return import_module("monitor")


def _elapsed_seconds(started_at: Optional[float]) -> float:
    try:
        if started_at not in (None, ""):
            return max(0.0, time.time() - float(started_at))
    except (TypeError, ValueError, OverflowError):
        pass
    return 0.0


def _rolling_average(values: deque[float], count: int) -> float:
    recent = list(values)[-max(1, int(count)) :]
    if not recent:
        return 0.0
    return float(sum(float(v) for v in recent) / len(recent))


def _runtime_config_from_settings(settings: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    facade = _facade()
    settings = settings if isinstance(settings, dict) else facade.load_settings()
    overrides = settings.get("risk_threshold_overrides") if isinstance(settings.get("risk_threshold_overrides"), dict) else None
    return facade.resolve_runtime_escalation_config(settings.get("risk_sensitivity"), overrides)


def _runtime_int(config: Dict[str, Any], key: str, fallback: int) -> int:
    try:
        return int(config.get(key, fallback))
    except (TypeError, ValueError, OverflowError):
        return int(fallback)


def _runtime_float(config: Dict[str, Any], key: str, fallback: float) -> float:
    try:
        return float(config.get(key, fallback))
    except (TypeError, ValueError, OverflowError):
        return float(fallback)


def _round_list(values: list[Any], digits: int = 2) -> list[Any]:
    rounded: list[Any] = []
    for value in values:
        if isinstance(value, (int, float)):
            rounded.append(round(float(value), digits))
        else:
            rounded.append(value)
    return rounded


def _build_recent_evidence(
    *,
    model_decision: Optional[str],
    recent_decisions: deque[str],
    recent_risks: deque[float],
    recent_timestamps: Optional[deque[float]],
    risk: int,
    event_time: Optional[float],
    confirmation_window: float,
) -> Dict[str, Any]:
    history_limit = 4
    prior_decisions = list(recent_decisions)[-(history_limit - 1) :]
    prior_risks = list(recent_risks)[-len(prior_decisions) :]
    decisions = prior_decisions + ([str(model_decision)] if model_decision else [])
    risks = prior_risks + ([float(risk)] if model_decision else [])

    timestamps: list[float] = []
    if recent_timestamps is not None:
        prior_times = list(recent_timestamps)[-len(prior_decisions) :]
        if len(prior_times) == len(prior_decisions) and event_time is not None and model_decision:
            timestamps = [float(value) for value in prior_times] + [float(event_time)]

    filtered_decisions = list(decisions)
    filtered_risks = list(risks)
    filtered_times = list(timestamps)
    if timestamps and len(timestamps) == len(decisions):
        filtered = [
            (dec, value, ts)
            for dec, value, ts in zip(decisions, risks, timestamps)
            if float(event_time or time.time()) - float(ts) <= confirmation_window
        ]
        if filtered:
            filtered_decisions = [dec for dec, _value, _ts in filtered]
            filtered_risks = [float(value) for _dec, value, _ts in filtered]
            filtered_times = [float(ts) for _dec, _value, ts in filtered]

    ages_sec: list[float] = []
    if filtered_times and event_time is not None:
        ages_sec = [max(0.0, float(event_time) - float(ts)) for ts in filtered_times]

    recent3 = filtered_decisions[-3:]
    recent_risk3 = filtered_risks[-3:]
    intruder_hits4 = sum(dec == "intruder" for dec in filtered_decisions)
    intruder_hits3 = sum(dec == "intruder" for dec in recent3)
    alert_hits4 = sum(dec in {"intruder", "suspicious"} for dec in filtered_decisions)

    return {
        "decisions": filtered_decisions,
        "risks": filtered_risks,
        "times": filtered_times,
        "ages_sec": _round_list(ages_sec),
        "recent3_decisions": recent3,
        "recent3_risks": recent_risk3,
        "intruder_hits4": intruder_hits4,
        "intruder_hits3": intruder_hits3,
        "alert_hits4": alert_hits4,
    }



DEMO_CLASSIC_LOCK_OVERRIDE_RULE = "demo_classic_lock_override"
DEMO_CLASSIC_HIGH_RISK_LOCK_REASON = "demo_classic_intruder_high_risk_lock"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def _demo_classic_lock_override_decision(
    *,
    model_decision: Optional[str],
    effective_decision: Optional[str] = None,
    confirmation_rule: Optional[str] = None,
    locking_allowed: bool = True,
    risk: int = 0,
    avg_risk: float = 0.0,
    warnings: int = 0,
    recent_decisions: Optional[list[str]] = None,
    recent_risks: Optional[list[Any]] = None,
    quality_lock_ok_windows: Optional[int] = None,
    observed_risk: float = 0.0,
    observed_lock_quality_risks: Optional[list[Any]] = None,
    confirmed_intruder_feedback: bool = False,
    lock_safety_reason_codes: Optional[list[Any]] = None,
) -> Dict[str, Any]:
    """Return an embedded classic-runtime decision to bypass calibration-immature lock suppression.

    This helper is intentionally narrow and defaults off.  It never weakens the
    production safety gate because it requires BIOAUTH_DEMO_CLASSIC_PROTECTED.
    The caller must still use the existing protected-action/Windows-lock path.
    """

    if not demo_classic_protected_enabled():
        return {
            "should_lock": False,
            "reason": "demo_classic_protected_disabled",
            "demo_classic_protected": False,
        }

    decisions = [str(item or "").strip().lower() for item in list(recent_decisions or [])]
    risks = [_as_float(item, 0.0) for item in list(recent_risks or [])]
    observed_values = [_as_float(item, 0.0) for item in list(observed_lock_quality_risks or [])]
    current_decision = str(effective_decision or model_decision or "").strip().lower()
    model_decision = str(model_decision or "").strip().lower()
    rule = str(confirmation_rule or "").strip().lower()
    recent_alerts = [item for item in decisions if item in {"suspicious", "intruder"}]
    recent_avg = float(sum(risks) / len(risks)) if risks else float(avg_risk or risk or 0.0)
    high90_count = sum(1 for item in risks if float(item) >= 90.0)
    observed_peak = max([float(observed_risk or 0.0), *observed_values], default=0.0)
    observed_high90_count = sum(1 for item in observed_values if float(item) >= 90.0)
    quality_ok = None if quality_lock_ok_windows is None else int(quality_lock_ok_windows or 0)
    quality_lock_cluster_ok = quality_ok is None or quality_ok >= 3
    calibration_suppression = rule == "lock_suppressed_by_calibration_immature"

    if confirmed_intruder_feedback:
        # LOCK-FACE-01: user feedback is audit/post-lock classification only.
        # It must not create a manual pre-lock enforcement path, even in the embedded classic runtime path.
        return {
            "should_lock": False,
            "reason": "demo_classic_manual_intruder_feedback_disabled_feedback_is_audit_only",
            "demo_classic_protected": True,
            "demo_classic_manual_intruder_feedback_lock": False,
        }

    if not bool(locking_allowed) and not calibration_suppression:
        return {
            "should_lock": False,
            "reason": "demo_classic_lock_override_non_calibration_safety_gate_preserved",
            "demo_classic_protected": True,
            "runtime_confirmation_rule_before_demo_override": rule,
        }

    calibration_suppressed_intruder = (
        (current_decision == "intruder" or model_decision == "intruder")
        and calibration_suppression
        and not bool(locking_allowed)
    )
    if calibration_suppressed_intruder and (
        float(risk or 0) >= 90.0
        or float(avg_risk or 0.0) >= 85.0
        or high90_count >= 2
        or (quality_lock_cluster_ok and (observed_peak >= 90.0 or observed_high90_count >= 2))
    ):
        return {
            "should_lock": True,
            "reason": DEMO_CLASSIC_HIGH_RISK_LOCK_REASON,
            "rule": DEMO_CLASSIC_LOCK_OVERRIDE_RULE,
            "demo_classic_protected": True,
            "calibration_immature_lock_bypassed_for_demo": True,
        }

    repeated_observed_alerts = (
        calibration_suppression
        and current_decision in {"suspicious", "intruder"}
        and quality_lock_cluster_ok
        and (observed_peak >= 90.0 or observed_high90_count >= 2)
        and (len(recent_alerts) >= 2 or int(warnings or 0) >= 1)
    )
    if repeated_observed_alerts:
        return {
            "should_lock": True,
            "reason": DEMO_CLASSIC_HIGH_RISK_LOCK_REASON,
            "rule": DEMO_CLASSIC_LOCK_OVERRIDE_RULE,
            "demo_classic_protected": True,
            "calibration_immature_lock_bypassed_for_demo": True,
            "observed_peak_risk": round(float(observed_peak), 2),
            "observed_high90_count": int(observed_high90_count),
            "decision_risk_before_demo_override": round(float(risk or 0.0), 2),
        }

    repeated_alerts = len(recent_alerts) >= 3 and (recent_avg >= 85.0 or high90_count >= 2)
    if repeated_alerts:
        return {
            "should_lock": True,
            "reason": DEMO_CLASSIC_HIGH_RISK_LOCK_REASON,
            "rule": DEMO_CLASSIC_LOCK_OVERRIDE_RULE,
            "demo_classic_protected": True,
            "calibration_immature_lock_bypassed_for_demo": rule == "lock_suppressed_by_calibration_immature" or not bool(locking_allowed),
        }

    explicit_high_warning_pattern = (
        current_decision in {"suspicious", "intruder"}
        and float(risk or 0) >= 90.0
        and int(warnings or 0) >= 3
        and (quality_ok is None or quality_ok >= 3)
    )
    if explicit_high_warning_pattern:
        return {
            "should_lock": True,
            "reason": DEMO_CLASSIC_HIGH_RISK_LOCK_REASON,
            "rule": DEMO_CLASSIC_LOCK_OVERRIDE_RULE,
            "demo_classic_protected": True,
            "calibration_immature_lock_bypassed_for_demo": rule == "lock_suppressed_by_calibration_immature" or not bool(locking_allowed),
        }

    return {
        "should_lock": False,
        "reason": "demo_classic_lock_override_conditions_not_met",
        "demo_classic_protected": True,
        "recent_alert_count": int(len(recent_alerts)),
        "recent_avg_risk": round(float(recent_avg), 2),
        "high90_count": int(high90_count),
        "observed_peak_risk": round(float(observed_peak), 2),
        "observed_high90_count": int(observed_high90_count),
    }

def _intruder_confirmation_diagnostics(
    model_decision: Optional[str],
    recent_decisions: deque[str],
    recent_risks: deque[float],
    risk: int,
    avg_risk: float,
    ml: int,
    elapsed: float,
    config: Dict[str, Any],
    warnings: int = 0,
    *,
    recent_timestamps: Optional[deque[float]] = None,
    event_time: Optional[float] = None,
    locking_allowed: bool = True,
    locking_reason: Optional[str] = None,
    quality_lock_ok_windows: Optional[int] = None,
    observed_risk: float = 0.0,
    observed_lock_quality_risks: Optional[list[Any]] = None,
    confirmed_intruder_feedback: bool = False,
    lock_safety_reason_codes: Optional[list[Any]] = None,
) -> Dict[str, Any]:
    facade = _facade()
    confirmation_window = facade._runtime_float(config, "runtime_confirmation_window_seconds", 10.0)
    evidence = _build_recent_evidence(
        model_decision=model_decision,
        recent_decisions=recent_decisions,
        recent_risks=recent_risks,
        recent_timestamps=recent_timestamps,
        risk=risk,
        event_time=event_time,
        confirmation_window=confirmation_window,
    )

    recent4 = list(evidence["decisions"])
    recent_risk_values = [float(value) for value in evidence["risks"]]
    recent3 = list(evidence["recent3_decisions"])
    recent_risk3 = [float(value) for value in evidence["recent3_risks"]]
    intruder_hits4 = int(evidence["intruder_hits4"])
    intruder_hits3 = int(evidence["intruder_hits3"])
    alert_hits4 = int(evidence["alert_hits4"])

    recent_avg3 = float(sum(recent_risk3) / len(recent_risk3)) if recent_risk3 else 0.0
    recent_avg4 = float(sum(recent_risk_values) / len(recent_risk_values)) if recent_risk_values else 0.0
    severe_threshold = facade._runtime_float(config, "runtime_severe_hit_threshold", 80.0)
    severe_hits4 = sum(float(v) >= severe_threshold for v in recent_risk_values)

    min_elapsed = facade._runtime_float(config, "runtime_min_lock_elapsed_seconds", 30.0)
    secondary_elapsed = facade._runtime_float(config, "runtime_secondary_lock_elapsed_seconds", max(18.0, min_elapsed / 1.5))
    high_risk_elapsed = facade._runtime_float(config, "runtime_high_risk_min_elapsed_seconds", max(12.0, min_elapsed / 2.0))
    suspicious_fast_lock_risk = facade._runtime_float(config, "runtime_suspicious_fast_lock_risk", 90.0)
    suspicious_fast_lock_avg = facade._runtime_float(config, "runtime_suspicious_fast_lock_avg_risk", 85.0)
    suspicious_fast_lock_elapsed = facade._runtime_float(config, "runtime_suspicious_fast_lock_elapsed_seconds", high_risk_elapsed)
    suspicious_fast_lock_hits = facade._runtime_int(config, "runtime_suspicious_fast_lock_alert_hits", 2)
    warning_lock_hits = facade._runtime_int(config, "runtime_warning_lock_alert_hits", max(2, facade._runtime_int(config, "runtime_warning_escalation_alert_hits", 2)))
    warning_lock_peak = facade._runtime_float(config, "runtime_warning_lock_peak_risk", max(72.0, facade._runtime_float(config, "suspicious_window_risk", 60.0) + 16.0))
    warning_lock_alert_avg = facade._runtime_float(config, "runtime_warning_lock_alert_avg_risk", max(68.0, warning_lock_peak - 4.0))
    warning_lock_elapsed = facade._runtime_float(config, "runtime_warning_lock_elapsed_seconds", max(6.0, secondary_elapsed / 2.0))
    recent_alert_avg = float(sum(float(value) for dec, value in zip(recent4, recent_risk_values) if dec in {"intruder", "suspicious"}) / max(1, sum(dec in {"intruder", "suspicious"} for dec in recent4))) if recent4 else float(avg_risk)
    intruder_confirmations = facade._runtime_int(config, "runtime_intruder_confirmations", 2)
    alert_hits_threshold = facade._runtime_int(config, "runtime_alert_hits_threshold", 3)
    min_samples_for_action = facade._runtime_int(config, "runtime_min_samples_for_action", 3)
    high_risk_override = facade._runtime_float(config, "runtime_high_risk_override", 90.0)
    intruder_avg3_threshold = facade._runtime_float(config, "runtime_intruder_avg3_threshold", 66.0)
    intruder_avg4_ml_threshold = facade._runtime_float(config, "runtime_intruder_avg4_ml_threshold", 60.0)
    severe_hit_count = facade._runtime_int(config, "runtime_severe_hit_count", 2)
    intruder_avg4_severe_threshold = facade._runtime_float(config, "runtime_intruder_avg4_severe_threshold", 68.0)
    alert_avg4_threshold = facade._runtime_float(config, "runtime_alert_avg4_threshold", 68.0)
    alert_ml_avg4_threshold = facade._runtime_float(config, "runtime_alert_ml_avg4_threshold", 72.0)
    avg_risk_intruder_threshold = facade._runtime_float(config, "runtime_avg_risk_intruder_threshold", 74.0)
    recovery_override_risk = facade._runtime_float(config, "runtime_recovery_override_risk", 98.0)

    diagnostic = {
        "confirmed": False,
        "matched_rule": None,
        "matched_summary": "no lock rule matched",
        "model_decision": model_decision,
        "locking_allowed": bool(locking_allowed),
        "risk": int(risk),
        "avg_risk": round(float(avg_risk), 2),
        "ml": int(ml),
        "warnings": int(warnings),
        "elapsed_sec": round(float(elapsed), 2),
        "confirmation_window_sec": round(float(confirmation_window), 2),
        "recent_decisions": recent4,
        "recent_risks": _round_list(recent_risk_values),
        "recent_ages_sec": list(evidence["ages_sec"]),
        "intruder_hits3": intruder_hits3,
        "intruder_hits4": intruder_hits4,
        "alert_hits4": alert_hits4,
        "recent_avg3": round(recent_avg3, 2),
        "recent_avg4": round(recent_avg4, 2),
        "recent_alert_avg": round(recent_alert_avg, 2),
        "severe_hits4": severe_hits4,
        "observed_risk": round(float(observed_risk or 0.0), 2),
        "observed_lock_quality_risks": _round_list([_as_float(item, 0.0) for item in list(observed_lock_quality_risks or [])]),
        "thresholds": {
            "suspicious_fast_lock_risk": round(suspicious_fast_lock_risk, 2),
            "suspicious_fast_lock_avg": round(suspicious_fast_lock_avg, 2),
            "suspicious_fast_lock_elapsed": round(suspicious_fast_lock_elapsed, 2),
            "warning_lock_peak": round(warning_lock_peak, 2),
            "warning_lock_alert_avg": round(warning_lock_alert_avg, 2),
            "warning_lock_elapsed": round(warning_lock_elapsed, 2),
            "high_risk_override": round(high_risk_override, 2),
            "avg_risk_intruder_threshold": round(avg_risk_intruder_threshold, 2),
            "recovery_override_risk": round(recovery_override_risk, 2),
        },
        "lock_safety_reason_codes": [str(item) for item in list(lock_safety_reason_codes or []) if str(item or "").strip()],
        "calibration_immature_face_escalation_bypass": False,
    }

    def _confirm(rule: str, summary: str) -> Dict[str, Any]:
        diagnostic["confirmed"] = True
        diagnostic["matched_rule"] = rule
        diagnostic["matched_summary"] = summary
        return diagnostic

    lock_reason_text = str(locking_reason or "")
    hard_suppression_prefixes = (
        "lock_suppressed_by_calibration_immature",
        "lock_suppressed_by_low_quality_window",
        "lock_suppressed_by_current_window_not_lock_quality",
        "lock_suppressed_by_startup_window",
        "lock_suppressed_by_post_idle_window",
        "lock_suppressed_by_transition_window",
        "demo_classic_post_unlock_resume_cooldown",
        "lock_suppressed_by_demo_classic_post_unlock_resume_cooldown",
    )
    hard_suppression = any(lock_reason_text.startswith(prefix) for prefix in hard_suppression_prefixes)
    safety_reasons = {str(item).strip() for item in list(lock_safety_reason_codes or []) if str(item or "").strip()}
    calibration_only_suppression = (
        lock_reason_text.startswith("lock_suppressed_by_calibration_immature")
        and safety_reasons == {"calibration_immature"}
    )

    def _should_escalate_calibration_immature_to_face() -> bool:
        if not calibration_only_suppression:
            return False
        if model_decision not in {"intruder", "suspicious"}:
            return False
        # This is not a direct lock bypass.  It only allows the existing
        # pre-lock face-confirmation path to run after repeated strong evidence.
        # Face verified owner suppresses lock; unavailable/failed/wrong face still
        # fails closed to the normal protected response.
        min_alert_hits = max(2, min(alert_hits_threshold, suspicious_fast_lock_hits, warning_lock_hits))
        strong_decision_cluster = (
            len(recent4) >= min_alert_hits
            and alert_hits4 >= min_alert_hits
            and risk >= max(warning_lock_peak, severe_threshold)
            and recent_alert_avg >= max(warning_lock_alert_avg, severe_threshold - 4.0)
            and elapsed >= max(6.0, min(high_risk_elapsed, warning_lock_elapsed))
        )
        severe_intruder_cluster = (
            model_decision == "intruder"
            and len(recent4) >= max(2, severe_hit_count)
            and alert_hits4 >= max(2, severe_hit_count)
            and severe_hits4 >= max(1, severe_hit_count)
            and recent_avg4 >= max(intruder_avg4_severe_threshold, suspicious_fast_lock_avg)
            and elapsed >= high_risk_elapsed
        )
        observed_cluster = (
            float(observed_risk or 0.0) >= max(high_risk_override, suspicious_fast_lock_risk)
            or sum(float(value) >= max(high_risk_override, suspicious_fast_lock_risk) for value in list(observed_lock_quality_risks or [])) >= 1
        )
        return bool(strong_decision_cluster or severe_intruder_cluster or observed_cluster)

    demo_override = _demo_classic_lock_override_decision(
        model_decision=model_decision,
        effective_decision=model_decision,
        confirmation_rule=lock_reason_text,
        locking_allowed=locking_allowed,
        risk=risk,
        avg_risk=avg_risk,
        warnings=warnings,
        recent_decisions=recent4,
        recent_risks=recent_risk_values,
        quality_lock_ok_windows=quality_lock_ok_windows,
        observed_risk=observed_risk,
        observed_lock_quality_risks=observed_lock_quality_risks,
        confirmed_intruder_feedback=confirmed_intruder_feedback,
        lock_safety_reason_codes=lock_safety_reason_codes,
    )
    if bool(demo_override.get("should_lock")):
        diagnostic.update({
            "confirmed": True,
            "matched_rule": str(demo_override.get("rule") or DEMO_CLASSIC_LOCK_OVERRIDE_RULE),
            "matched_summary": "Classic protected runtime allowed escalation after repeated high-risk/intruder evidence.",
            "demo_classic_lock_override": True,
            "demo_classic_lock_override_reason": str(demo_override.get("reason") or DEMO_CLASSIC_HIGH_RISK_LOCK_REASON),
            "calibration_immature_lock_bypassed_for_demo": bool(demo_override.get("calibration_immature_lock_bypassed_for_demo", True)),
            "observed_peak_risk": round(float(demo_override.get("observed_peak_risk") or observed_risk or 0.0), 2),
            "observed_high90_count": int(demo_override.get("observed_high90_count") or 0),
            "decision_risk_before_demo_override": round(float(demo_override.get("decision_risk_before_demo_override") or risk or 0.0), 2),
            "runtime_confirmation_rule_before_demo_override": lock_reason_text,
            "runtime_confirmation_rule_after_demo_override": str(demo_override.get("rule") or DEMO_CLASSIC_LOCK_OVERRIDE_RULE),
            "runtime_locking_allowed_before_demo_override": bool(locking_allowed),
            "runtime_locking_allowed_after_demo_override": True,
            "protected_action_requested": True,
            "protected_action_phase": "pre_lock_face_confirmation_required",
            "face_confirmation_required_before_lock": True,
            "lock_reason": str(demo_override.get("reason") or DEMO_CLASSIC_HIGH_RISK_LOCK_REASON),
            "final_action": "pre_lock_face_confirmation_required",
        })
        return diagnostic
    diagnostic["demo_classic_lock_override"] = False
    diagnostic["demo_classic_lock_override_reason"] = str(demo_override.get("reason") or "")
    if not bool(locking_allowed) and _should_escalate_calibration_immature_to_face():
        diagnostic.update({
            "confirmed": True,
            "matched_rule": "high_risk_face_escalation_calibration_immature",
            "matched_summary": "repeated high-risk evidence bypassed calibration-only lock suppression for pre-lock face confirmation",
            "calibration_immature_face_escalation_bypass": True,
            "runtime_confirmation_rule_before_face_escalation": lock_reason_text,
            "runtime_locking_allowed_before_face_escalation": bool(locking_allowed),
            "runtime_locking_allowed_after_face_escalation": True,
            "protected_action_requested": True,
            "protected_action_phase": "pre_lock_face_confirmation_required",
            "face_confirmation_required_before_lock": True,
            "lock_reason": "high_risk_face_escalation_calibration_immature",
            "final_action": "pre_lock_face_confirmation_required",
        })
        return diagnostic
    if not locking_allowed and (hard_suppression or risk < recovery_override_risk):
        diagnostic["matched_rule"] = lock_reason_text or "lock_suppressed_by_recovery_cooldown"
        if lock_reason_text == "lock_suppressed_by_mouse_fallback_guard":
            diagnostic["matched_summary"] = "lock suppressed because only mouse-heavy global-fallback evidence was present and stronger evidence is required"
        elif hard_suppression:
            diagnostic["matched_summary"] = f"lock suppressed by runtime safety gate: {lock_reason_text}"
        else:
            diagnostic["matched_summary"] = f"lock suppressed during recovery cooldown because risk {risk} is below override {recovery_override_risk:.0f}"
        return diagnostic

    if model_decision in {"intruder", "suspicious"}:
        if len(recent4) >= max(2, suspicious_fast_lock_hits) and alert_hits4 >= suspicious_fast_lock_hits and risk >= suspicious_fast_lock_risk and avg_risk >= suspicious_fast_lock_avg and elapsed >= suspicious_fast_lock_elapsed:
            return _confirm("suspicious_fast_lock", "alert cluster met fast suspicious lock thresholds")
        if warnings >= 1 and len(recent4) >= max(2, warning_lock_hits) and alert_hits4 >= warning_lock_hits and risk >= warning_lock_peak and recent_alert_avg >= warning_lock_alert_avg and elapsed >= warning_lock_elapsed:
            return _confirm("warning_followup_lock", "warning-state follow-up alert cluster met warning lock thresholds")

    if model_decision == "intruder":
        if (
            risk >= high_risk_override
            and elapsed >= high_risk_elapsed
            and alert_hits4 >= max(2, severe_hit_count)
            and severe_hits4 >= severe_hit_count
            and recent_avg4 >= max(intruder_avg4_severe_threshold, suspicious_fast_lock_avg)
        ):
            return _confirm("high_risk_cluster_override", "high-risk evidence repeated across a severe alert cluster")
        if intruder_hits3 >= intruder_confirmations and recent_avg3 >= intruder_avg3_threshold and elapsed >= min_elapsed:
            return _confirm("intruder_recent_cluster", "recent intruder cluster met avg3 and elapsed thresholds")
        if intruder_hits4 >= intruder_confirmations and ml == 1 and recent_avg4 >= intruder_avg4_ml_threshold and elapsed >= secondary_elapsed:
            return _confirm("intruder_ml_cluster", "intruder cluster met supervised classifier-assisted avg4 threshold")
        if intruder_hits4 >= 1 and severe_hits4 >= severe_hit_count and recent_avg4 >= intruder_avg4_severe_threshold and elapsed >= secondary_elapsed:
            return _confirm("intruder_severe_cluster", "intruder evidence contained enough severe hits to confirm")

    if len(recent4) >= min_samples_for_action and model_decision in {"intruder", "suspicious"}:
        if alert_hits4 >= alert_hits_threshold and intruder_hits4 >= 1 and recent_avg4 >= alert_avg4_threshold and elapsed >= min_elapsed:
            return _confirm("alert_cluster_with_intruder_vote", "mixed alert cluster with an intruder vote met avg4 threshold")
        if alert_hits4 >= alert_hits_threshold and ml == 1 and recent_avg4 >= alert_ml_avg4_threshold and elapsed >= secondary_elapsed:
            return _confirm("alert_cluster_ml_threshold", "mixed alert cluster met supervised avg4 threshold")
        if avg_risk >= avg_risk_intruder_threshold and ml == 1 and intruder_hits4 >= 1 and elapsed >= secondary_elapsed:
            return _confirm("avg_risk_intruder_threshold", "overall average risk crossed intruder threshold with supervised support")

    return diagnostic


def _intruder_confirmed(
    model_decision: Optional[str],
    recent_decisions: deque[str],
    recent_risks: deque[float],
    risk: int,
    avg_risk: float,
    ml: int,
    elapsed: float,
    config: Dict[str, Any],
    warnings: int = 0,
    *,
    recent_timestamps: Optional[deque[float]] = None,
    event_time: Optional[float] = None,
    locking_allowed: bool = True,
    locking_reason: Optional[str] = None,
    quality_lock_ok_windows: Optional[int] = None,
    observed_risk: float = 0.0,
    observed_lock_quality_risks: Optional[list[Any]] = None,
    confirmed_intruder_feedback: bool = False,
    lock_safety_reason_codes: Optional[list[Any]] = None,
    explain: bool = False,
) -> bool | Dict[str, Any]:
    diagnostic = _intruder_confirmation_diagnostics(
        model_decision,
        recent_decisions,
        recent_risks,
        risk,
        avg_risk,
        ml,
        elapsed,
        config,
        warnings=warnings,
        recent_timestamps=recent_timestamps,
        event_time=event_time,
        locking_allowed=locking_allowed,
        locking_reason=locking_reason,
        quality_lock_ok_windows=quality_lock_ok_windows,
        observed_risk=observed_risk,
        observed_lock_quality_risks=observed_lock_quality_risks,
        confirmed_intruder_feedback=confirmed_intruder_feedback,
        lock_safety_reason_codes=lock_safety_reason_codes,
    )
    if explain:
        return diagnostic
    return bool(diagnostic["confirmed"])


def _resolve_runtime_escalation(
    *,
    model_decision: str,
    recent_decisions: deque[str],
    recent_risks: deque[float],
    risk: int,
    avg_risk: float,
    ml: int,
    elapsed: float,
    warnings: int,
    config: Dict[str, Any],
    recent_timestamps: Optional[deque[float]] = None,
    event_time: Optional[float] = None,
    locking_allowed: bool = True,
    locking_reason: Optional[str] = None,
    quality_lock_ok_windows: Optional[int] = None,
    observed_risk: float = 0.0,
    observed_lock_quality_risks: Optional[list[Any]] = None,
    confirmed_intruder_feedback: bool = False,
    lock_safety_reason_codes: Optional[list[Any]] = None,
) -> Dict[str, Any]:
    facade = _facade()
    confirmation_diagnostics = facade._intruder_confirmed(
        model_decision,
        recent_decisions,
        recent_risks,
        risk,
        avg_risk,
        ml,
        elapsed,
        config,
        warnings=warnings,
        recent_timestamps=recent_timestamps,
        event_time=event_time,
        locking_allowed=locking_allowed,
        locking_reason=locking_reason,
        quality_lock_ok_windows=quality_lock_ok_windows,
        observed_risk=observed_risk,
        observed_lock_quality_risks=observed_lock_quality_risks,
        confirmed_intruder_feedback=confirmed_intruder_feedback,
        lock_safety_reason_codes=lock_safety_reason_codes,
        explain=True,
    )
    confirmed_intruder = bool(confirmation_diagnostics["confirmed"])
    effective_decision = model_decision
    alert_title_key = None
    alert_message_key = None
    alert_code = None
    recent4 = list(recent_decisions)[-3:] + [model_decision]
    if recent_timestamps is not None and event_time is not None:
        recent_times = list(recent_timestamps)[-3:] + [float(event_time)]
        confirmation_window = facade._runtime_float(config, "runtime_confirmation_window_seconds", 10.0)
        filtered_decisions = [
            dec for dec, ts in zip(recent4, recent_times)
            if float(event_time) - float(ts) <= confirmation_window
        ]
        if filtered_decisions:
            recent4 = filtered_decisions
    recent_alert_hits = sum(dec in {"intruder", "suspicious"} for dec in recent4)

    decision_reason_code = "decision_unchanged"
    decision_reason = "runtime decision left unchanged"
    if confirmed_intruder:
        effective_decision = "intruder"
        warnings = 0
        decision_reason_code = "lock_confirmed"
        decision_reason = str(confirmation_diagnostics.get("matched_summary") or "lock rule matched")
    elif model_decision == "intruder":
        effective_decision = "suspicious"
        warnings = min(facade.WARNING_LIMIT + 2, warnings + 1)
        alert_code = "high_risk_snapshot"
        alert_title_key = "alert_high_risk_title"
        alert_message_key = "alert_high_risk_msg"
        decision_reason_code = "downgraded_intruder_snapshot"
        decision_reason = str(confirmation_diagnostics.get("matched_summary") or "intruder snapshot did not satisfy confirmation rules, so it was downgraded to suspicious")
    elif model_decision == "suspicious":
        effective_decision = "suspicious"
        warnings = min(facade.WARNING_LIMIT + 2, warnings + 1)
        if recent_alert_hits <= 1:
            alert_code = "suspicious_behavior"
            alert_title_key = "alert_warn_title"
            alert_message_key = "alert_warn_msg"
        decision_reason_code = "soft_suspicious_warning"
        decision_reason = "suspicious evidence raised warning state but did not confirm a lock"
    else:
        if avg_risk < facade._runtime_float(config, "runtime_warning_reset_avg_risk", 35.0) and recent_alert_hits == 0:
            warnings = 0
            decision_reason_code = "warning_reset"
            decision_reason = "legitimate evidence reset warnings because average risk is low and no recent alerts remain"
        else:
            warnings = max(0, warnings - 1)
            decision_reason_code = "warning_decay"
            decision_reason = "legitimate evidence reduced warning pressure but kept some recent alert memory"

    return {
        "confirmed_intruder": confirmed_intruder,
        "effective_decision": effective_decision,
        "warnings": warnings,
        "alert_title_key": alert_title_key,
        "alert_message_key": alert_message_key,
        "alert_code": alert_code,
        "recent_alert_hits": recent_alert_hits,
        "decision_reason_code": decision_reason_code,
        "decision_reason": decision_reason,
        "confirmation_diagnostics": confirmation_diagnostics,
        "demo_classic_lock_override": bool(confirmation_diagnostics.get("demo_classic_lock_override")),
        "demo_classic_lock_override_reason": str(confirmation_diagnostics.get("demo_classic_lock_override_reason") or ""),
        "calibration_immature_lock_bypassed_for_demo": bool(confirmation_diagnostics.get("calibration_immature_lock_bypassed_for_demo")),
        "runtime_confirmation_rule_before_demo_override": str(confirmation_diagnostics.get("runtime_confirmation_rule_before_demo_override") or ""),
        "runtime_confirmation_rule_after_demo_override": str(confirmation_diagnostics.get("runtime_confirmation_rule_after_demo_override") or ""),
        "runtime_locking_allowed_before_demo_override": bool(confirmation_diagnostics.get("runtime_locking_allowed_before_demo_override", locking_allowed)),
        "runtime_locking_allowed_after_demo_override": bool(confirmation_diagnostics.get("runtime_locking_allowed_after_demo_override", locking_allowed)),
        "protected_action_requested": bool(confirmation_diagnostics.get("protected_action_requested") or confirmed_intruder),
        "protected_action_phase": str(confirmation_diagnostics.get("protected_action_phase") or ("pre_lock_face_confirmation_required" if confirmed_intruder else "")),
        "face_confirmation_required_before_lock": bool(confirmation_diagnostics.get("face_confirmation_required_before_lock") or confirmed_intruder),
        "lock_reason": str(confirmation_diagnostics.get("lock_reason") or ""),
        "final_action": str(confirmation_diagnostics.get("final_action") or ("pre_lock_face_confirmation_required" if confirmed_intruder else "")),
    }
