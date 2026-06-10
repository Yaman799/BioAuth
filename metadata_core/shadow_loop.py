"""Autonomous shadow-only recovery loop helpers for BioAuth.

These helpers are side-effect free. They do not train, evaluate, promote, lower
thresholds, or enable Protected Sessions. The bridge/scheduler uses the returned
state to decide whether the existing training path may run again after a
shadow-only result and after enough new trusted enrollment evidence appears.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import time
from typing import Any, Dict, Iterable, Mapping

from metadata_core.passive_quality import session_meets_passive_trusted_minimum_floor_if_needed

SHADOW_LOOP_RETRY_COOLDOWN_SECONDS = 6 * 60 * 60
SHADOW_LOOP_MIN_NEW_ACCEPTED_SESSIONS = 2
SHADOW_LOOP_REPEATED_FAILURE_LIMIT = 3

_TIME_OF_DAY_BUCKETS = ("morning", "afternoon", "evening", "night")


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def _safe_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _is_trusted_enrollment_session(session: Mapping[str, Any]) -> bool:
    if not isinstance(session, Mapping):
        return False
    if str(session.get("session_kind") or "").strip().lower() != "enrollment":
        return False
    if bool(session.get("training_counts_toward_minimum")):
        return session_meets_passive_trusted_minimum_floor_if_needed(session)
    bucket = str(session.get("bucket") or session.get("archive_group") or "").strip().lower()
    return bool(session.get("metadata_trusted")) and bucket in {"accepted", "authorized", "legit"} and session_meets_passive_trusted_minimum_floor_if_needed(session)


def _session_identity(session: Mapping[str, Any]) -> str:
    for key in ("session_id", "path", "archive_path"):
        text = str(session.get(key) or "").strip()
        if text:
            return f"{key}:{text}"
    return ""


def _dedupe_trusted_sessions(sessions: Iterable[Mapping[str, Any]] | None) -> list[Dict[str, Any]]:
    result: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for session in sessions or []:
        if not isinstance(session, Mapping) or not _is_trusted_enrollment_session(session):
            continue
        identity = _session_identity(session)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        result.append(dict(session))
    return result


def trusted_sessions_signature(sessions: Iterable[Mapping[str, Any]] | None) -> str:
    trusted = _dedupe_trusted_sessions(sessions)
    payload = {
        "trusted_session_ids": sorted(_session_identity(item) for item in trusted if _session_identity(item)),
        "trusted_session_count": len(trusted),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_timestamp(value: Any) -> _dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return _dt.datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return _dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _time_bucket(value: Any) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return ""
    hour = int(parsed.hour)
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _coverage_strength(count: int) -> str:
    count = max(0, _safe_int(count))
    if count <= 0:
        return "none"
    if count < 30:
        return "weak"
    if count < 90:
        return "partial"
    return "strong"


def _mixed_strength(keyboard_rows: int, mouse_rows: int) -> str:
    keyboard_rows = max(0, _safe_int(keyboard_rows))
    mouse_rows = max(0, _safe_int(mouse_rows))
    if keyboard_rows <= 0 or mouse_rows <= 0:
        return "none"
    lower = min(keyboard_rows, mouse_rows)
    higher = max(keyboard_rows, mouse_rows)
    if lower < 30:
        return "weak"
    if higher and (lower / float(higher)) < 0.20:
        return "partial"
    return "strong"


def _input_coverage(sessions: Iterable[Mapping[str, Any]]) -> Dict[str, str]:
    keyboard_rows = 0
    mouse_rows = 0
    for session in sessions:
        if not isinstance(session, Mapping):
            continue
        keyboard_rows += _safe_int(session.get("keyboard_rows"))
        mouse_rows += _safe_int(session.get("mouse_rows"))
    return {
        "keyboard": _coverage_strength(keyboard_rows),
        "mouse": _coverage_strength(mouse_rows),
        "mixed": _mixed_strength(keyboard_rows, mouse_rows),
    }


def _time_coverage(sessions: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    coverage = {bucket: 0 for bucket in _TIME_OF_DAY_BUCKETS}
    for session in sessions:
        if not isinstance(session, Mapping):
            continue
        bucket = str(session.get("time_of_day_bucket") or "").strip().lower()
        if bucket not in coverage:
            bucket = _time_bucket(session.get("created_at") or session.get("timestamp") or session.get("started_at") or session.get("started_at_text"))
        if bucket in coverage:
            coverage[bucket] += 1
    return coverage


def targeted_collection_action(production_approval: Mapping[str, Any] | None, model_readiness: Mapping[str, Any] | None = None) -> str:
    production = _as_dict(production_approval)
    readiness = _as_dict(model_readiness)
    active_contexts = _safe_list(production.get("activeRoutedContexts"))
    failed_gates = _safe_list(production.get("failedProductionGates"))
    readiness_action = str(readiness.get("nextBestAction") or "").strip()
    dominant_context = str(readiness.get("dominantInputContext") or "").strip()
    if "mouse_heavy" in active_contexts or dominant_context == "mouse_heavy":
        return "collect_keyboard_mixed_sessions"
    if "keyboard_heavy" in active_contexts or dominant_context == "keyboard_heavy":
        return "collect_mouse_mixed_sessions"
    if "insufficient_context_coverage" in failed_gates or any(item.endswith("context_coverage") for item in failed_gates):
        return "collect_context_diversity_sessions"
    if "insufficient_time_spread" in failed_gates:
        return "collect_time_distributed_sessions"
    if "benchmark_not_run" in failed_gates:
        return "run_device_check"
    if "production_margin_not_met" in failed_gates:
        return "collect_diverse_high_quality_sessions"
    if readiness_action:
        return readiness_action
    return "collect_targeted_trusted_sessions"


def _action_text(action: str) -> str:
    return {
        "collect_keyboard_mixed_sessions": "Collect more keyboard and mixed keyboard/mouse sessions before retraining.",
        "collect_mouse_mixed_sessions": "Collect more mouse and mixed keyboard/mouse sessions before retraining.",
        "collect_context_diversity_sessions": "Collect trusted sessions across more behavior contexts before retraining.",
        "collect_time_distributed_sessions": "Collect trusted sessions across different times of day before retraining.",
        "run_device_check": "Run the device check before relying on enhanced runtime production decisions.",
        "collect_diverse_high_quality_sessions": "Collect more diverse, high-quality trusted sessions before retraining.",
        "collect_targeted_trusted_sessions": "Collect targeted trusted sessions before retraining.",
    }.get(action, "Collect targeted trusted sessions before retraining.")


def _iso_from_epoch(value: Any) -> str:
    seconds = _safe_float(value, 0.0)
    if seconds <= 0.0:
        return ""
    try:
        return _dt.datetime.fromtimestamp(seconds, tz=_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return ""


def _latest_evaluation_time(production_approval: Mapping[str, Any], shadow_status: Mapping[str, Any]) -> str:
    for key in ("lastEvaluationTime", "evaluationReportModifiedAt", "evaluationSummaryModifiedAt"):
        text = str(production_approval.get(key) or "").strip()
        if text:
            return text
    for key in ("last_eval_at", "lastEvaluationTime"):
        text = str(shadow_status.get(key) or "").strip()
        if text:
            return text
    return ""


def build_shadow_loop_state(
    *,
    profile: Mapping[str, Any] | None,
    production_approval: Mapping[str, Any] | None,
    model_readiness: Mapping[str, Any] | None,
    sessions: Iterable[Mapping[str, Any]] | None,
    baseline_signature: str = "",
    baseline_accepted_count: int = 0,
    cooldown_until: float = 0.0,
    repeated_shadow_count: int = 0,
    shadow_status: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> Dict[str, Any]:
    profile_payload = _as_dict(profile)
    production_payload = _as_dict(production_approval)
    readiness_payload = _as_dict(model_readiness)
    shadow_payload = _as_dict(shadow_status)
    model_status = str(production_payload.get("modelStatus") or profile_payload.get("candidate_model_status") or "").strip().lower()
    paused = bool(shadow_payload.get("automation_paused") or shadow_payload.get("shadow_automation_paused"))
    shadow_candidate_waiting = model_status == "approved_for_shadow" and not bool(production_payload.get("protectedSessionsAvailable"))
    active = shadow_candidate_waiting and not paused
    trusted_sessions = _dedupe_trusted_sessions(sessions)
    current_signature = trusted_sessions_signature(trusted_sessions)
    accepted_count = _safe_int(profile_payload.get("session_count"), len(trusted_sessions))
    baseline_count = max(0, _safe_int(baseline_accepted_count, accepted_count if not baseline_signature else 0))
    if not baseline_signature:
        baseline_count = accepted_count
    new_accepted = max(0, accepted_count - baseline_count)
    repeated = max(0, _safe_int(repeated_shadow_count))
    min_new = SHADOW_LOOP_MIN_NEW_ACCEPTED_SESSIONS + (1 if repeated >= SHADOW_LOOP_REPEATED_FAILURE_LIMIT else 0)
    clock = time.time() if now is None else float(now)
    cooldown_active = bool(cooldown_until and float(cooldown_until) > clock)
    failed_gates = _safe_list(production_payload.get("failedProductionGates"))
    action = targeted_collection_action(production_payload, readiness_payload)
    diversity = {
        "inputCoverage": _input_coverage(trusted_sessions),
        "timeOfDayCoverage": _time_coverage(trusted_sessions),
    }
    has_new_signature = bool(baseline_signature and current_signature != str(baseline_signature or ""))
    enough_new_sessions = new_accepted >= min_new and has_new_signature
    requires_device_check = action == "run_device_check"
    retraining_eligible = bool(active and enough_new_sessions and not cooldown_active and not requires_device_check)
    if paused and shadow_candidate_waiting:
        phase = "developer_paused"
    elif not active:
        phase = "inactive"
    elif cooldown_active:
        phase = "cooldown"
    elif repeated >= SHADOW_LOOP_REPEATED_FAILURE_LIMIT and not enough_new_sessions:
        phase = "safe_failure_collecting"
    elif enough_new_sessions:
        phase = "retraining_ready"
    else:
        phase = "collecting_targeted_sessions"
    if phase == "developer_paused":
        background_action = "developer_shadow_paused"
    elif phase == "retraining_ready":
        background_action = "shadow_loop_ready_for_retraining"
    elif phase == "cooldown":
        background_action = "shadow_loop_cooldown"
    elif active:
        background_action = action
    else:
        background_action = ""
    status_text = (
        "Shadow automation is paused from Developer UI; monitor tests can run without shadow evidence auto-start."
        if paused and shadow_candidate_waiting
        else "BioAuth is validating your protection model safely in the background."
        if active
        else "Shadow validation loop is inactive."
    )
    advanced_parts = [
        f"phase={phase}",
        f"model_status={model_status or 'untrained'}",
        f"action={action}",
        "protected_sessions_available=false" if active else f"protected_sessions_available={bool(production_payload.get('protectedSessionsAvailable'))}",
        f"new_accepted_sessions={new_accepted}",
        f"min_new_sessions={min_new}",
    ]
    if failed_gates:
        advanced_parts.append("failed_gates=" + ",".join(failed_gates))
    latest_eval = _latest_evaluation_time(production_payload, shadow_payload)
    if latest_eval:
        advanced_parts.append("last_evaluation_time=" + latest_eval)
    if cooldown_active:
        advanced_parts.append("next_retry_eligible_at=" + _iso_from_epoch(cooldown_until))
    return {
        "enabled": bool(active),
        "active": bool(active),
        "automationPaused": bool(paused),
        "shadowAutomationPaused": bool(paused),
        "phase": phase,
        "modelStatus": model_status or "untrained",
        "protectedSessionsAvailable": False if active else bool(production_payload.get("protectedSessionsAvailable")),
        "failedProductionGates": failed_gates,
        "currentBlocker": str(readiness_payload.get("currentBlocker") or (failed_gates[0] if failed_gates else "approved_for_shadow" if active else "")),
        "targetedCollectionAction": action,
        "targetedCollectionText": _action_text(action),
        "backgroundAction": background_action,
        "safeUserMessage": status_text,
        "advancedDiagnosticText": " | ".join(advanced_parts),
        "lastEvaluationTime": latest_eval,
        "currentTrustedSignature": current_signature,
        "baselineTrustedSignature": str(baseline_signature or ""),
        "acceptedSessions": int(accepted_count),
        "baselineAcceptedSessions": int(baseline_count),
        "newAcceptedSessionsSinceShadow": int(new_accepted),
        "requiredNewAcceptedSessions": int(min_new),
        "retrainingEligible": bool(retraining_eligible),
        "cooldownActive": bool(cooldown_active),
        "nextRetryEligibleAt": _iso_from_epoch(cooldown_until),
        "repeatedShadowCount": int(repeated),
        "safeFailureState": bool(active and repeated >= SHADOW_LOOP_REPEATED_FAILURE_LIMIT and not enough_new_sessions),
        "evidence": {
            "evaluationReportFile": str(production_payload.get("evaluationReportFile") or ""),
            "evaluationSummaryFile": str(production_payload.get("evaluationSummaryFile") or ""),
            "evaluationReportAvailable": bool(production_payload.get("evaluationReportAvailable")),
            "evaluationSummaryAvailable": bool(production_payload.get("evaluationSummaryAvailable")),
            "activeRoutedContexts": _safe_list(production_payload.get("activeRoutedContexts")),
            "inputCoverage": diversity["inputCoverage"],
            "timeOfDayCoverage": diversity["timeOfDayCoverage"],
        },
    }


def shadow_retraining_gate(
    *,
    production_approval: Mapping[str, Any] | None,
    model_readiness: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    sessions: Iterable[Mapping[str, Any]] | None,
    baseline_signature: str = "",
    baseline_accepted_count: int = 0,
    cooldown_until: float = 0.0,
    repeated_shadow_count: int = 0,
    now: float | None = None,
) -> tuple[bool, str, Dict[str, Any]]:
    state = build_shadow_loop_state(
        profile=profile,
        production_approval=production_approval,
        model_readiness=model_readiness,
        sessions=sessions,
        baseline_signature=baseline_signature,
        baseline_accepted_count=baseline_accepted_count,
        cooldown_until=cooldown_until,
        repeated_shadow_count=repeated_shadow_count,
        now=now,
    )
    if not bool(state.get("active")):
        return True, "shadow_loop_inactive", state
    if bool(state.get("retrainingEligible")):
        return True, "shadow_loop_retraining_ready", state
    if bool(state.get("cooldownActive")):
        return False, "shadow_loop_cooldown", state
    if bool(state.get("safeFailureState")):
        return False, "shadow_loop_safe_failure_collecting", state
    return False, "shadow_loop_waiting_for_new_sessions", state


__all__ = [
    "SHADOW_LOOP_MIN_NEW_ACCEPTED_SESSIONS",
    "SHADOW_LOOP_REPEATED_FAILURE_LIMIT",
    "SHADOW_LOOP_RETRY_COOLDOWN_SECONDS",
    "build_shadow_loop_state",
    "shadow_retraining_gate",
    "targeted_collection_action",
    "trusted_sessions_signature",
]
