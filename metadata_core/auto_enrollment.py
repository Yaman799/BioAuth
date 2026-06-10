"""Backend-owned Smart Auto Enrollment state and passive collection helpers.

Smart Auto Enrollment is a conservative passive evidence collector. It may
start/stop one background enrollment capture session and expose backend-owned
status, but it must never become a trust-decision shortcut. Passive collection
creates candidate behavioral evidence only; archive/session quality gates decide
whether a session can count, dashboard/training readiness decides whether
training may start, model evaluation and shadow validation decide candidate
safety, and production approval/auto-promotion gates decide runtime protection.

Allowed to collect is not allowed to train. Allowed to train is not allowed to
promote. Allowed to shadow is not allowed to protect.
"""

from __future__ import annotations

import datetime as _dt
import os
import time
from typing import Any, Dict, Iterable, Mapping

from metadata_core.remediation_loop import RemediationAction, RemediationFailureKind, RemediationPlan
from metadata_core.passive_quality import (
    PASSIVE_AUTO_ENROLLMENT_SOURCE,
    PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS,
    PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS,
    PASSIVE_TRUSTED_MIN_MOUSE_EVENTS,
    session_meets_passive_trusted_minimum_floor_if_needed,
)

# Keep this state helper import-light. These match metadata_core.constants
# in the current baseline and are also overridden by backend profile fields when
# a dashboard snapshot supplies project-owned threshold values.
MIN_REQUIRED_ENROLLMENT_SESSIONS = 8
MIN_WINDOW_EVENTS = 30
RECOMMENDED_ENROLLMENT_SESSIONS = 15

_TIME_OF_DAY_BUCKETS = ("morning", "afternoon", "evening", "night")
PASSIVE_COLLECTION_SOURCE = PASSIVE_AUTO_ENROLLMENT_SOURCE
REMEDIATION_EVIDENCE_SOURCE = "remediation_refill"
REMEDIATION_HARD_NEGATIVE_EVIDENCE_SOURCE = "hard_negative_remediation"
REMEDIATION_ENV_PLAN_ID = "BIOAUTH_REMEDIATION_PLAN_ID"
REMEDIATION_ENV_TARGETED_ACTION = "BIOAUTH_TARGETED_COLLECTION_ACTION"
REMEDIATION_ENV_EVIDENCE_SOURCE = "BIOAUTH_EVIDENCE_SOURCE"
REMEDIATION_ENV_TRUST_LEVEL = "BIOAUTH_TRUST_LEVEL"
REMEDIATION_ENV_EXCLUDED_FROM_POSITIVE = "BIOAUTH_EXCLUDED_FROM_POSITIVE_TRAINING"

_TARGETED_OWNER_COLLECTION_ACTIONS = frozenset(
    {
        RemediationAction.COLLECT_POST_UNLOCK_TRUSTED_WINDOWS.value,
        RemediationAction.COLLECT_MORE_SHADOW_COMPARISON_WINDOWS.value,
        RemediationAction.COLLECT_HIGHER_QUALITY_OWNER_SESSIONS.value,
        RemediationAction.COLLECT_DIVERSE_OWNER_SESSIONS.value,
        RemediationAction.COLLECT_TRUSTED_OWNER_REAUTH_OR_UNLOCK_WINDOWS.value,
    }
)
_HARD_NEGATIVE_COLLECTION_ACTIONS = frozenset({RemediationAction.HARD_NEGATIVE_REMEDIATION_REQUIRED.value})
_NO_COLLECTION_REMEDIATION_ACTIONS = frozenset(
    {
        RemediationAction.NO_COLLECTION_FIX_RUNTIME.value,
        RemediationAction.NO_COLLECTION_FIX_SCHEMA.value,
        RemediationAction.NO_RETRY_UNTIL_CODE_FIX.value,
        RemediationAction.WAIT_FOR_MANUAL_REVIEW.value,
        RemediationAction.INSPECT_OFFLINE_SUB_REASONS.value,
    }
)
AUTO_ENROLLMENT_MIN_DURATION_SECONDS = 60
AUTO_ENROLLMENT_TARGET_CAPTURE_EVENTS = 100000
AUTO_ENROLLMENT_TARGET_KEYBOARD_EVENTS = 2500
AUTO_ENROLLMENT_TARGET_MOUSE_EVENTS = 100000
AUTO_ENROLLMENT_INACTIVITY_SECONDS = 120
AUTO_ENROLLMENT_MAX_DURATION_SECONDS = 90 * 60
AUTO_ENROLLMENT_MIN_SPACING_SECONDS = 10 * 60

# Inactivity finalization only means the passive logger session may close after
# enough live evidence has been observed. These thresholds do not accept the
# session for training; existing archive/session quality gates remain
# authoritative after finalization.
AUTO_ENROLLMENT_MIN_INACTIVITY_KEYBOARD_EVENTS = PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS
AUTO_ENROLLMENT_MIN_INACTIVITY_MOUSE_EVENTS = PASSIVE_TRUSTED_MIN_MOUSE_EVENTS
AUTO_ENROLLMENT_MIN_INACTIVITY_CAPTURE_EVENTS = PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_bool(source: Mapping[str, Any], key: str, default: bool = False) -> bool:
    if not isinstance(source, Mapping) or key not in source:
        return bool(default)
    return bool(source.get(key))


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


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


def _time_bucket(timestamp_value: Any) -> str:
    parsed = _parse_timestamp(timestamp_value)
    if parsed is None:
        return ""
    hour = int(parsed.hour)
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def time_of_day_bucket(timestamp_value: Any | None = None) -> str:
    """Return a safe, non-sensitive local time-of-day bucket."""

    if timestamp_value in (None, ""):
        try:
            timestamp_value = _dt.datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError):
            timestamp_value = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return _time_bucket(timestamp_value) or "night"


def input_coverage_summary(keyboard_rows: Any, mouse_rows: Any) -> str:
    """Summarize keyboard/mouse coverage without exposing raw events."""

    keyboard = max(0, _safe_int(keyboard_rows))
    mouse = max(0, _safe_int(mouse_rows))
    if keyboard <= 0 and mouse <= 0:
        return "none"
    if keyboard > 0 and mouse > 0:
        lower = min(keyboard, mouse)
        higher = max(keyboard, mouse)
        if lower >= max(1, MIN_WINDOW_EVENTS) and (not higher or lower / float(higher) >= 0.20):
            return "mixed"
        return "partial_mixed"
    if keyboard > 0:
        return "keyboard_only"
    return "mouse_only"


def passive_collection_env(
    remediation_plan: RemediationPlan | Mapping[str, Any] | None = None,
    *,
    remediation_plan_id: Any = "",
) -> Dict[str, str]:
    """Environment tags consumed by logger.py for passive auto-enrollment.

    Optional remediation values are backend-owned labels only. They do not start
    collection, do not decide training acceptance, and do not change production
    readiness.
    """

    env = {
        "BIOAUTH_AUTO_ENROLLMENT": "1",
        "BIOAUTH_COLLECTION_SOURCE": PASSIVE_COLLECTION_SOURCE,
        "BIOAUTH_TIME_OF_DAY_BUCKET": time_of_day_bucket(),
    }
    env.update(remediation_passive_collection_env(remediation_plan, remediation_plan_id=remediation_plan_id))
    return env


def metadata_tags_from_environment(env: Mapping[str, Any] | None = None, *, keyboard_rows: Any = 0, mouse_rows: Any = 0) -> Dict[str, Any]:
    """Return safe archive metadata tags for passive auto-enrollment sessions."""

    source = env if isinstance(env, Mapping) else os.environ
    enabled = str(source.get("BIOAUTH_AUTO_ENROLLMENT") or "").strip().lower() in {"1", "true", "yes"}
    collection_source = str(source.get("BIOAUTH_COLLECTION_SOURCE") or "").strip().lower()
    if not enabled and collection_source != PASSIVE_COLLECTION_SOURCE:
        return {}
    bucket = str(source.get("BIOAUTH_TIME_OF_DAY_BUCKET") or "").strip().lower()
    if bucket not in _TIME_OF_DAY_BUCKETS:
        bucket = time_of_day_bucket()
    tags: Dict[str, Any] = {
        "auto_enrollment": True,
        "collection_source": PASSIVE_COLLECTION_SOURCE,
        "time_of_day_bucket": bucket,
        "input_coverage": input_coverage_summary(keyboard_rows, mouse_rows),
    }
    action = _normal_action(source.get(REMEDIATION_ENV_TARGETED_ACTION))
    evidence_source = str(source.get(REMEDIATION_ENV_EVIDENCE_SOURCE) or "").strip().lower()
    trust_level = str(source.get(REMEDIATION_ENV_TRUST_LEVEL) or "").strip().lower()
    plan_id = str(source.get(REMEDIATION_ENV_PLAN_ID) or "").strip()
    excluded = str(source.get(REMEDIATION_ENV_EXCLUDED_FROM_POSITIVE) or "").strip().lower() in {"1", "true", "yes", "on"}
    if action in _TARGETED_OWNER_COLLECTION_ACTIONS or action in _HARD_NEGATIVE_COLLECTION_ACTIONS:
        tags["remediation_collection"] = True
        tags["targeted_collection_action"] = action
        tags["evidence_source"] = evidence_source or (REMEDIATION_HARD_NEGATIVE_EVIDENCE_SOURCE if action in _HARD_NEGATIVE_COLLECTION_ACTIONS else REMEDIATION_EVIDENCE_SOURCE)
        tags["trust_level"] = trust_level or ("hard_negative" if action in _HARD_NEGATIVE_COLLECTION_ACTIONS else "trusted_owner_candidate")
        if plan_id:
            tags["remediation_plan_id"] = plan_id
        if excluded or action in _HARD_NEGATIVE_COLLECTION_ACTIONS:
            tags["excluded_from_positive_training"] = True
            tags["training_counts_toward_minimum"] = False
    return tags


def is_passive_auto_enrollment_state(state: Mapping[str, Any] | None) -> bool:
    if not isinstance(state, Mapping):
        return False
    return bool(state.get("auto_enrollment")) and str(state.get("collection_source") or "").strip().lower() == PASSIVE_COLLECTION_SOURCE


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def _epoch_seconds(value: Any) -> float:
    numeric = _safe_float(value, -1.0)
    if numeric >= 0.0:
        return numeric
    parsed = _parse_timestamp(value)
    if parsed is None:
        return 0.0
    try:
        return float(parsed.timestamp())
    except (OSError, OverflowError, ValueError):
        return 0.0


def _normal_action(action: Any) -> str:
    return str(action or "").strip().lower()


def _remediation_plan_payload(remediation_plan: RemediationPlan | Mapping[str, Any] | None) -> Dict[str, Any]:
    if isinstance(remediation_plan, RemediationPlan):
        return remediation_plan.to_dict()
    return _as_dict(remediation_plan)


def _remediation_plan_id(remediation_plan: RemediationPlan | Mapping[str, Any] | None, explicit_plan_id: Any = "") -> str:
    explicit = str(explicit_plan_id or "").strip()
    if explicit:
        return explicit
    payload = _remediation_plan_payload(remediation_plan)
    for key in ("remediation_plan_id", "plan_id", "id"):
        text = str(payload.get(key) or "").strip()
        if text:
            return text
    digest = str(payload.get("evidence_report_digest") or payload.get("candidate_artifact_digest") or "").strip()
    if digest:
        return digest
    return ""


def _remediation_action(remediation_plan: RemediationPlan | Mapping[str, Any] | None) -> str:
    payload = _remediation_plan_payload(remediation_plan)
    return _normal_action(payload.get("action") or payload.get("targeted_collection_action") or payload.get("next_action"))


def _remediation_failure_kind(remediation_plan: RemediationPlan | Mapping[str, Any] | None) -> str:
    payload = _remediation_plan_payload(remediation_plan)
    return str(payload.get("failure_kind") or "").strip().lower()


def remediation_collection_block_reason(remediation_plan: RemediationPlan | Mapping[str, Any] | None) -> str:
    """Return why a remediation plan must not request passive collection.

    Empty string means the plan may request a passive evidence refill, subject to
    the normal authentication, consent, runtime, training/evaluation, protected
    session, and cooldown gates. This helper never starts collection.
    """

    payload = _remediation_plan_payload(remediation_plan)
    if not payload:
        return "remediation_plan_missing"
    action = _remediation_action(payload)
    kind = _remediation_failure_kind(payload)
    if not action:
        return "remediation_action_missing"
    if action in _NO_COLLECTION_REMEDIATION_ACTIONS:
        if action == RemediationAction.NO_COLLECTION_FIX_RUNTIME.value:
            return "remediation_runtime_fix_required"
        if action == RemediationAction.NO_COLLECTION_FIX_SCHEMA.value:
            return "remediation_schema_fix_required"
        if action == RemediationAction.NO_RETRY_UNTIL_CODE_FIX.value:
            return "remediation_code_fix_required"
        return "remediation_manual_review_required"
    if action in _TARGETED_OWNER_COLLECTION_ACTIONS and kind in {
        RemediationFailureKind.DATA_REMEDIABLE.value,
        "evidence_remediable",
    }:
        return ""
    if action in _HARD_NEGATIVE_COLLECTION_ACTIONS and kind == RemediationFailureKind.NEGATIVE_REMEDIABLE.value:
        return ""
    return "remediation_collection_not_allowed"


def remediation_plan_allows_targeted_collection(remediation_plan: RemediationPlan | Mapping[str, Any] | None) -> bool:
    return remediation_collection_block_reason(remediation_plan) == ""


def _remediation_is_hard_negative(remediation_plan: RemediationPlan | Mapping[str, Any] | None) -> bool:
    return _remediation_action(remediation_plan) in _HARD_NEGATIVE_COLLECTION_ACTIONS


def remediation_metadata_from_plan(
    remediation_plan: RemediationPlan | Mapping[str, Any] | None,
    *,
    remediation_plan_id: Any = "",
) -> Dict[str, Any]:
    """Return safe archive metadata tags for a targeted remediation refill.

    The metadata is aggregate/label-only. It intentionally does not include raw
    keyboard, mouse, biometric, or feature-vector payloads and it never marks a
    hard-negative remediation as owner-positive training evidence.
    """

    if remediation_collection_block_reason(remediation_plan):
        return {}
    action = _remediation_action(remediation_plan)
    plan_id = _remediation_plan_id(remediation_plan, remediation_plan_id)
    hard_negative = _remediation_is_hard_negative(remediation_plan)
    evidence_source = REMEDIATION_HARD_NEGATIVE_EVIDENCE_SOURCE if hard_negative else REMEDIATION_EVIDENCE_SOURCE
    tags: Dict[str, Any] = {
        "remediation_collection": True,
        "targeted_collection_action": action,
        "evidence_source": evidence_source,
        "trust_level": "hard_negative" if hard_negative else "trusted_owner_candidate",
    }
    if plan_id:
        tags["remediation_plan_id"] = plan_id
    if hard_negative:
        tags["excluded_from_positive_training"] = True
        tags["training_counts_toward_minimum"] = False
    return tags


def remediation_passive_collection_env(
    remediation_plan: RemediationPlan | Mapping[str, Any] | None,
    *,
    remediation_plan_id: Any = "",
) -> Dict[str, str]:
    """Environment tags for a future passive logger start.

    Returning environment values is not a side effect; callers still must pass
    the normal start gates before launching logger.py.
    """

    tags = remediation_metadata_from_plan(remediation_plan, remediation_plan_id=remediation_plan_id)
    if not tags:
        return {}
    result = {
        REMEDIATION_ENV_TARGETED_ACTION: str(tags.get("targeted_collection_action") or ""),
        REMEDIATION_ENV_EVIDENCE_SOURCE: str(tags.get("evidence_source") or ""),
        REMEDIATION_ENV_TRUST_LEVEL: str(tags.get("trust_level") or ""),
    }
    if tags.get("remediation_plan_id"):
        result[REMEDIATION_ENV_PLAN_ID] = str(tags.get("remediation_plan_id") or "")
    if bool(tags.get("excluded_from_positive_training")):
        result[REMEDIATION_ENV_EXCLUDED_FROM_POSITIVE] = "1"
    return result


def remediation_session_counts_as_success(
    session: Mapping[str, Any] | None,
    remediation_plan: RemediationPlan | Mapping[str, Any] | None = None,
) -> bool:
    """Return whether a finalized remediation session may satisfy owner evidence.

    This helper does not accept a session for training or readiness. It only
    verifies that a targeted refill session is not excluded from positive
    training and still passes the existing passive quality floor.
    """

    if not isinstance(session, Mapping):
        return False
    if bool(session.get("excluded_from_positive_training")):
        return False
    action = str(session.get("targeted_collection_action") or "").strip().lower()
    if remediation_plan is not None:
        expected_action = _remediation_action(remediation_plan)
        if expected_action and action and action != expected_action:
            return False
    if action in _HARD_NEGATIVE_COLLECTION_ACTIONS:
        return False
    if action and action not in _TARGETED_OWNER_COLLECTION_ACTIONS:
        return False
    return session_meets_passive_trusted_minimum_floor_if_needed(session)


def _has_mixed_evidence(keyboard_events: int, mouse_events: int) -> bool:
    return keyboard_events >= AUTO_ENROLLMENT_TARGET_KEYBOARD_EVENTS and mouse_events >= AUTO_ENROLLMENT_TARGET_MOUSE_EVENTS


def _has_minimum_inactivity_evidence(capture_events: int, keyboard_events: int, mouse_events: int) -> bool:
    """Return whether an idle passive session has enough evidence to close safely.

    This is a passive logger lifetime rule only. It deliberately uses stronger
    minimum evidence than the old 20-keyboard/20-mouse heuristic and does not
    imply the archived session is accepted for training.
    """

    return bool(
        keyboard_events >= AUTO_ENROLLMENT_MIN_INACTIVITY_KEYBOARD_EVENTS
        or mouse_events >= AUTO_ENROLLMENT_MIN_INACTIVITY_MOUSE_EVENTS
        or capture_events >= AUTO_ENROLLMENT_MIN_INACTIVITY_CAPTURE_EVENTS
    )


def passive_collection_should_finalize(
    runtime_state: Mapping[str, Any] | None,
    auto_enrollment_state: Mapping[str, Any] | None = None,
    model_readiness_state: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
    now: Any = None,
) -> tuple[bool, str]:
    """Decide whether a passive auto-enrollment capture has enough live evidence to stop.

    This helper is intentionally side-effect free and never decides whether the
    session counts for training. It only decides when the existing passive
    logger session can be stopped and archived. Archived session quality gates,
    training readiness, model evaluation, shadow validation, production approval,
    and auto-promotion gates remain authoritative after finalization.
    """

    state = _as_dict(runtime_state)
    if not is_passive_auto_enrollment_state(state):
        return False, "not_passive_auto_enrollment"
    if not bool(state.get("active")):
        return False, "not_active"
    if str(state.get("session_kind") or "").strip().lower() != "enrollment":
        return False, "not_enrollment"

    auto_state = _as_dict(auto_enrollment_state)
    readiness = _as_dict(model_readiness_state)
    profile_payload = _as_dict(profile)

    if auto_state and not _safe_bool(auto_state, "enabled", True):
        return True, "setting_disabled"
    if auto_state and not _safe_bool(auto_state, "consentSatisfied", True):
        return True, "consent_revoked"

    now_value = _safe_float(now, 0.0)
    if now_value <= 0.0:
        now_value = time.time()
    started_at = _epoch_seconds(state.get("started_at") or state.get("started_at_text"))
    if started_at <= 0.0 or started_at > now_value:
        started_at = now_value
    duration = max(0.0, now_value - started_at)

    keyboard_events = max(0, _safe_int(state.get("keyboard_event_count")))
    mouse_events = max(0, _safe_int(state.get("mouse_event_count")))
    capture_events = max(0, _safe_int(state.get("capture_event_count"), keyboard_events + mouse_events))
    if capture_events < keyboard_events + mouse_events:
        capture_events = keyboard_events + mouse_events

    if duration < AUTO_ENROLLMENT_MIN_DURATION_SECONDS:
        return False, "minimum_duration_waiting"

    accepted_sessions = max(0, _safe_int(auto_state.get("acceptedSessions"), _safe_int(profile_payload.get("session_count"))))
    recommended_sessions = max(
        0,
        _safe_int(
            auto_state.get("recommendedSessions"),
            _safe_int(profile_payload.get("recommended_session_count"), RECOMMENDED_ENROLLMENT_SESSIONS),
        ),
    )
    if recommended_sessions > 0 and accepted_sessions >= recommended_sessions:
        return True, "recommended_sessions_reached"

    training_ready = bool(auto_state.get("trainingReady") or profile_payload.get("training_can_start"))
    auto_training_enabled = _safe_bool(auto_state, "autoTrainingEnabled", False)
    if training_ready and auto_training_enabled:
        return True, "training_ready_and_auto_training_waiting"

    next_action = _normal_action(readiness.get("nextBestAction") or readiness.get("backgroundAction"))
    mixed_evidence = _has_mixed_evidence(keyboard_events, mouse_events)

    if next_action == "collect_keyboard_mixed_sessions":
        if mixed_evidence:
            return True, "mixed_input_target_reached"
        if keyboard_events >= AUTO_ENROLLMENT_TARGET_KEYBOARD_EVENTS:
            return True, "keyboard_target_reached"
    elif next_action == "collect_mouse_mixed_sessions":
        if mixed_evidence:
            return True, "mixed_input_target_reached"
        if mouse_events >= AUTO_ENROLLMENT_TARGET_MOUSE_EVENTS:
            return True, "mouse_target_reached"
    elif next_action in {"collect_diverse_high_quality_sessions", "collect_context_diversity_sessions", "collect_time_distributed_sessions", "collect_targeted_trusted_sessions"}:
        if mixed_evidence:
            return True, "mixed_input_target_reached"
        if capture_events >= AUTO_ENROLLMENT_TARGET_CAPTURE_EVENTS:
            return True, "evidence_target_reached"
    else:
        if mixed_evidence:
            return True, "mixed_input_target_reached"
        if capture_events >= AUTO_ENROLLMENT_TARGET_CAPTURE_EVENTS:
            return True, "evidence_target_reached"

    last_capture_at = _epoch_seconds(state.get("last_capture_at") or state.get("logger_heartbeat_at"))
    if (
        last_capture_at > 0.0
        and (now_value - last_capture_at) >= AUTO_ENROLLMENT_INACTIVITY_SECONDS
        and _has_minimum_inactivity_evidence(capture_events, keyboard_events, mouse_events)
    ):
        return True, "inactivity_after_minimum_evidence"

    if duration >= AUTO_ENROLLMENT_MAX_DURATION_SECONDS:
        return True, "max_duration_reached"

    return False, "collecting_more_evidence"


def _session_identity(session: Mapping[str, Any]) -> str:
    for key in ("session_id", "path", "archive_path"):
        text = str(session.get(key) or "").strip()
        if text:
            return f"{key}:{text}"
    return ""


def _created_sort_value(session: Mapping[str, Any]) -> float:
    for key in ("created_at", "started_at_text", "timestamp"):
        parsed = _parse_timestamp(session.get(key))
        if parsed is not None:
            try:
                return parsed.timestamp()
            except (OSError, OverflowError, ValueError):
                pass
    try:
        return float(session.get("started_at") or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _dedupe_training_sessions(sessions: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    result: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for session in sessions:
        if not isinstance(session, Mapping):
            continue
        if not _is_training_enrollment_session(session):
            continue
        identity = _session_identity(session)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        result.append(dict(session))
    return result


def passive_collection_block_reason(
    *,
    settings: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    runtime_state: Mapping[str, Any] | None,
    consent_satisfied: bool,
    authenticated: bool,
    training_active: bool = False,
    evaluation_active: bool = False,
    app_locked: bool = False,
    remediation_plan: RemediationPlan | Mapping[str, Any] | None = None,
) -> str:
    """Explain why passive collection may not start. Empty means allowed.

    ``app_locked`` is kept in the public helper signature for bridge/test
    compatibility, but BioAuth App passcode lock is only a UI anti-tamper
    lock. It blocks console access after inactivity; it does not stop
    protection, monitoring, active sessions, passive enrollment, or
    background auto-training. Authentication, consent, runtime/session state,
    Protected Session, production-readiness, and technical-failure checks below
    remain the authoritative collection safety gates.
    """

    settings_payload = _as_dict(settings)
    profile_payload = _as_dict(profile)
    runtime_payload = _as_dict(runtime_state)
    if not authenticated:
        return "not_authenticated"
    if not _safe_bool(settings_payload, "smart_auto_enrollment_enabled", False):
        return "setting_disabled"
    if not consent_satisfied:
        return "consent_required"
    if bool(training_active):
        return "training_active"
    if bool(evaluation_active):
        return "evaluation_active"
    if remediation_plan is not None:
        remediation_reason = remediation_collection_block_reason(remediation_plan)
        if remediation_reason:
            return remediation_reason
    # Intentionally ignore ``app_locked`` here: the BioAuth App passcode lock
    # protects only the local interface and must not pause safe background
    # Smart Auto Enrollment by itself.
    if bool(profile_payload.get("production_ready")):
        return "production_ready"
    if bool(runtime_payload.get("technical_failure")):
        return "runtime_technical_failure"
    if str(runtime_payload.get("session_kind") or "").strip().lower() == "protected":
        return "protected_session_active"
    if bool(runtime_payload.get("active")) and not is_passive_auto_enrollment_state(runtime_payload):
        return "manual_or_other_session_active"
    return ""


def passive_collection_should_start(
    *,
    settings: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    runtime_state: Mapping[str, Any] | None,
    sessions: Iterable[Mapping[str, Any]] | None,
    consent_satisfied: bool,
    authenticated: bool,
    training_active: bool = False,
    evaluation_active: bool = False,
    app_locked: bool = False,
    remediation_plan: RemediationPlan | Mapping[str, Any] | None = None,
) -> tuple[bool, str]:
    reason = passive_collection_block_reason(
        settings=settings,
        profile=profile,
        runtime_state=runtime_state,
        consent_satisfied=consent_satisfied,
        authenticated=authenticated,
        training_active=training_active,
        evaluation_active=evaluation_active,
        app_locked=app_locked,
        remediation_plan=remediation_plan,
    )
    if reason:
        return False, reason
    if is_passive_auto_enrollment_state(runtime_state) and bool((runtime_state or {}).get("active")):
        return False, "already_collecting"
    profile_payload = _as_dict(profile)
    session_list = list(sessions or [])
    accepted_sessions = _safe_int(profile_payload.get("session_count"), len(_dedupe_training_sessions(session_list)))
    required_sessions = max(1, _safe_int(profile_payload.get("minimum_session_count"), MIN_REQUIRED_ENROLLMENT_SESSIONS))
    recommended_sessions = max(required_sessions, _safe_int(profile_payload.get("recommended_session_count"), RECOMMENDED_ENROLLMENT_SESSIONS))
    targeted_remediation = bool(remediation_plan is not None and remediation_plan_allows_targeted_collection(remediation_plan))
    if accepted_sessions >= recommended_sessions and not targeted_remediation:
        return False, "recommended_sessions_reached"
    trusted_auto_sessions = [item for item in _dedupe_training_sessions(session_list) if str(item.get("collection_source") or "").strip().lower() == PASSIVE_COLLECTION_SOURCE or bool(item.get("auto_enrollment"))]
    latest_auto = max((_created_sort_value(item) for item in trusted_auto_sessions), default=0.0)
    now = time.time()
    if latest_auto > 0.0 and (now - latest_auto) < AUTO_ENROLLMENT_MIN_SPACING_SECONDS:
        return False, "collection_spacing_active"
    return True, "ready"


def _is_training_enrollment_session(session: Mapping[str, Any]) -> bool:
    if not isinstance(session, Mapping):
        return False
    if bool(session.get("excluded_from_positive_training")):
        return False
    if str(session.get("targeted_collection_action") or "").strip().lower() in _HARD_NEGATIVE_COLLECTION_ACTIONS:
        return False
    kind = str(session.get("session_kind") or "").strip().lower()
    if kind != "enrollment":
        return False
    if bool(session.get("training_counts_toward_minimum")):
        return session_meets_passive_trusted_minimum_floor_if_needed(session)
    bucket = str(session.get("bucket") or "").strip().lower()
    trusted = bool(session.get("metadata_trusted"))
    return bool(trusted and bucket in {"accepted", "authorized", "legit"} and session_meets_passive_trusted_minimum_floor_if_needed(session))


def _coverage_strength(count: int) -> str:
    count = max(0, _safe_int(count))
    if count <= 0:
        return "none"
    if count < max(1, int(MIN_WINDOW_EVENTS)):
        return "weak"
    if count < max(1, int(MIN_WINDOW_EVENTS) * 3):
        return "partial"
    return "strong"


def _mixed_strength(keyboard_rows: int, mouse_rows: int) -> str:
    keyboard_rows = max(0, _safe_int(keyboard_rows))
    mouse_rows = max(0, _safe_int(mouse_rows))
    if keyboard_rows <= 0 or mouse_rows <= 0:
        return "none"
    lower = min(keyboard_rows, mouse_rows)
    higher = max(keyboard_rows, mouse_rows)
    if lower < max(1, int(MIN_WINDOW_EVENTS)):
        return "weak"
    if higher and (lower / float(higher)) < 0.20:
        return "partial"
    return "strong"


def _session_rows(sessions: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    keyboard_rows = 0
    mouse_rows = 0
    for session in sessions:
        if not isinstance(session, Mapping):
            continue
        keyboard_rows += _safe_int(session.get("keyboard_rows"))
        mouse_rows += _safe_int(session.get("mouse_rows"))
    return keyboard_rows, mouse_rows


def _time_of_day_coverage(sessions: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
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


def _backend_state(*, enabled: bool, consent_satisfied: bool, collecting: bool, training_ready: bool, production_ready: bool, block_reason: str = "", background_action: str = "") -> str:
    """Derive a QML-safe backend state from trusted backend facts only."""

    reason = str(block_reason or "").strip().lower()
    action = str(background_action or "").strip().lower()
    if not enabled:
        return "off"
    if not consent_satisfied:
        return "waiting_for_consent"
    if bool(production_ready):
        return "production_ready"
    if reason == "finalizing_passive_session" or action == "finalizing_passive_session":
        return "finalizing_passive_session"
    if collecting:
        return "collecting_passive_session"
    if action == "training_in_background":
        return "auto_training_running"
    if action.startswith("shadow_") or "shadow_validation" in action:
        return "shadow_validation_running"
    if reason == "collection_spacing_active":
        return "cooldown_after_collection"
    if reason == "not_authenticated":
        return "waiting_for_authentication"
    if reason in {"training_active", "runtime_technical_failure", "protected_session_active", "manual_or_other_session_active", "already_collecting"}:
        return "waiting_for_safe_idle"
    if training_ready:
        return "training_ready"
    return "waiting_for_quality_gates"


def _status_text(*, enabled: bool, consent_satisfied: bool, collecting: bool, block_reason: str = "") -> str:
    if not enabled:
        return "Smart Auto Enrollment is off. No passive collection is active."
    if not consent_satisfied:
        return "Smart Auto Enrollment is waiting for privacy consent. No passive collection is active."
    if str(block_reason or "") == "finalizing_passive_session":
        return "BioAuth is saving a completed passive enrollment session so existing quality gates can evaluate it."
    if collecting:
        return "Smart Auto Enrollment collects natural behavior in the background after consent. Only sessions accepted by BioAuth quality gates can count toward training."
    if block_reason == "recommended_sessions_reached":
        return "Smart Auto Enrollment has enough recommended trusted sessions. Passive collection is paused."
    if block_reason == "production_ready":
        return "Protected Sessions are production-ready. Passive enrollment collection is paused."
    if block_reason in {"training_active", "runtime_technical_failure", "protected_session_active", "manual_or_other_session_active"}:
        return "Smart Auto Enrollment is enabled but paused until the current activity is safe to collect from."
    if block_reason == "app_locked":
        return "Protection, monitoring, and Smart Auto Enrollment may continue while the BioAuth interface is passcode-locked."
    return "Smart Auto Enrollment is enabled and will collect natural behavior when the app is idle and safe. BioAuth quality gates decide whether sessions can count."


def _next_action_text(*, enabled: bool, consent_satisfied: bool, training_ready: bool, accepted_sessions: int, required_sessions: int, auto_training_enabled: bool, collecting: bool, input_coverage: Mapping[str, Any] | None = None) -> str:
    if not enabled:
        return "Enable Smart Auto Enrollment only after reviewing privacy consent. Continue manual enrollment for now."
    if not consent_satisfied:
        return "Review and accept privacy consent before any behavioral collection can run."
    if collecting:
        return "No action needed. Keep using your device normally; only sessions accepted by existing quality gates will count."
    coverage = _as_dict(input_coverage)
    keyboard = str(coverage.get("keyboard") or "none")
    mouse = str(coverage.get("mouse") or "none")
    if training_ready:
        if auto_training_enabled:
            return "Auto-training is enabled for a later phase; this build still uses the existing manual training path."
        return "Training is available through the existing manual training path. Auto-training is not active yet."
    remaining = max(0, int(required_sessions) - int(accepted_sessions))
    if keyboard in {"none", "weak"} and mouse not in {"none", "weak"}:
        return "More typing activity will strengthen your profile while BioAuth learns in the background."
    if mouse in {"none", "weak"} and keyboard not in {"none", "weak"}:
        return "More natural mouse activity will strengthen your profile while BioAuth learns in the background."
    if remaining > 0:
        return f"BioAuth needs {remaining} more trusted enrollment session(s). Keep using your device normally."
    return "Improve session quality/diversity before training; low-quality sessions will not count."


def build_auto_enrollment_state(
    *,
    settings: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    sessions: Iterable[Mapping[str, Any]] | None,
    consent_satisfied: bool,
    collecting: bool = False,
    collection_block_reason: str = "",
    background_action: str = "",
) -> Dict[str, Any]:
    """Return a QML-safe Smart Auto Enrollment state without side effects."""

    settings_payload = _as_dict(settings)
    profile_payload = _as_dict(profile)
    session_list = [dict(item) for item in (sessions or []) if isinstance(item, Mapping)]
    trusted_enrollment_sessions = _dedupe_training_sessions(session_list)

    enabled = _safe_bool(settings_payload, "smart_auto_enrollment_enabled", False)
    auto_training_enabled = _safe_bool(settings_payload, "auto_train_when_ready_enabled", False)
    auto_promotion_enabled = _safe_bool(settings_payload, "auto_promote_when_production_safe_enabled", False)
    accepted_sessions = _safe_int(profile_payload.get("session_count"), len(trusted_enrollment_sessions))
    required_sessions = max(1, _safe_int(profile_payload.get("minimum_session_count"), MIN_REQUIRED_ENROLLMENT_SESSIONS))
    recommended_sessions = max(required_sessions, _safe_int(profile_payload.get("recommended_session_count"), RECOMMENDED_ENROLLMENT_SESSIONS))
    training_ready = bool(profile_payload.get("training_can_start"))
    production_ready = bool(profile_payload.get("production_ready"))
    keyboard_rows, mouse_rows = _session_rows(trusted_enrollment_sessions)
    input_coverage = {
        "keyboard": _coverage_strength(keyboard_rows),
        "mouse": _coverage_strength(mouse_rows),
        "mixed": _mixed_strength(keyboard_rows, mouse_rows),
    }
    collecting = bool(collecting and enabled and consent_satisfied)

    return {
        "enabled": bool(enabled),
        "consentSatisfied": bool(consent_satisfied),
        "collecting": bool(collecting),
        "acceptedSessions": int(accepted_sessions),
        "requiredSessions": int(required_sessions),
        "recommendedSessions": int(recommended_sessions),
        "state": _backend_state(
            enabled=bool(enabled),
            consent_satisfied=bool(consent_satisfied),
            collecting=bool(collecting),
            training_ready=bool(training_ready),
            production_ready=bool(production_ready),
            block_reason=str(collection_block_reason or ""),
            background_action=str(background_action or ""),
        ),
        "trainingReady": bool(training_ready),
        "timeOfDayCoverage": _time_of_day_coverage(trusted_enrollment_sessions),
        "inputCoverage": input_coverage,
        "collectionStatusText": _status_text(enabled=bool(enabled), consent_satisfied=bool(consent_satisfied), collecting=bool(collecting), block_reason=str(collection_block_reason or "")),
        "nextBestActionText": _next_action_text(
            enabled=bool(enabled),
            consent_satisfied=bool(consent_satisfied),
            training_ready=bool(training_ready),
            accepted_sessions=int(accepted_sessions),
            required_sessions=int(required_sessions),
            auto_training_enabled=bool(auto_training_enabled),
            collecting=bool(collecting),
            input_coverage=input_coverage,
        ),
        "autoTrainingEnabled": bool(auto_training_enabled),
        "autoPromotionEnabled": bool(auto_promotion_enabled),
        "backgroundAction": str(background_action or ""),
    }


__all__ = [
    "AUTO_ENROLLMENT_INACTIVITY_SECONDS",
    "AUTO_ENROLLMENT_MAX_DURATION_SECONDS",
    "AUTO_ENROLLMENT_MIN_DURATION_SECONDS",
    "AUTO_ENROLLMENT_MIN_INACTIVITY_CAPTURE_EVENTS",
    "AUTO_ENROLLMENT_MIN_INACTIVITY_KEYBOARD_EVENTS",
    "AUTO_ENROLLMENT_MIN_INACTIVITY_MOUSE_EVENTS",
    "AUTO_ENROLLMENT_MIN_SPACING_SECONDS",
    "AUTO_ENROLLMENT_TARGET_CAPTURE_EVENTS",
    "AUTO_ENROLLMENT_TARGET_KEYBOARD_EVENTS",
    "AUTO_ENROLLMENT_TARGET_MOUSE_EVENTS",
    "PASSIVE_COLLECTION_SOURCE",
    "REMEDIATION_EVIDENCE_SOURCE",
    "REMEDIATION_HARD_NEGATIVE_EVIDENCE_SOURCE",
    "build_auto_enrollment_state",
    "input_coverage_summary",
    "is_passive_auto_enrollment_state",
    "metadata_tags_from_environment",
    "passive_collection_block_reason",
    "passive_collection_env",
    "remediation_collection_block_reason",
    "remediation_metadata_from_plan",
    "remediation_passive_collection_env",
    "remediation_plan_allows_targeted_collection",
    "remediation_session_counts_as_success",
    "passive_collection_should_finalize",
    "passive_collection_should_start",
    "time_of_day_bucket",
]
