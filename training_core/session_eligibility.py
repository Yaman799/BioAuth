"""Fail-closed training-session eligibility checks.

This module is deliberately small and policy-only.  It does not read raw
keyboard/mouse rows, does not promote models, and does not decide production
readiness.  It only answers whether already-discovered session metadata may be
used as positive owner evidence for training.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, Mapping, Optional

from feedback_loop import production_positive_training_allowed
from utils.identity import slugify_username

LOGGER = logging.getLogger(__name__)

TRAINING_SESSION_ELIGIBILITY_VERSION = "phase8-contamination-guard-v1"

_ALLOWED_POSITIVE_SESSION_KINDS = {"enrollment", "protected"}
_ALLOWED_INTEGRITY_STATES = {"verified"}
_SENSITIVE_DECISIONS = {
    "intruder",
    "suspicious",
    "rejected",
    "unauthorized",
    "interrupted",
    "failed",
    "blocked",
}
_SHADOW_OR_TEST_SOURCES = {
    "shadow",
    "shadow_only",
    "shadow_evidence",
    "shadow_evidence_monitor",
    "runtime_shadow_evidence",
    "shadow_validation",
    "developer_shadow",
    "hybrid_direct_test",
    "hybrid_direct_test_monitor",
    "offline_replay_candidate",
    "candidate_replay",
    "candidate_runtime",
    "candidate_monitor",
    "pre_lock_face_confirmation",
}
_CANDIDATE_OR_INTERNAL_STATES = {
    "candidate",
    "candidate_only",
    "main_candidate",
    "approved_for_shadow",
    "shadow_validation",
    "pending_evaluation",
    "pending_approval",
    "rejected",
    "shadow_only",
}
_BLOCKED_TRUE_FLAGS = {
    "confirmedIntruderAfterLock",
    "confirmed_intruder",
    "is_confirmed_intruder_window",
    "intruder_confirmed",
    "false_positive_candidate",
    "verified_owner_after_anomaly",
    "feedback_shadow_only",
    "shadow_only",
    "candidate_only",
    "candidate_session",
    "failed_evidence",
    "evidence_failed",
    "failedEvidence",
    "incomplete_data",
    "corrupt_data",
    "corrupted",
    "low_quality_session",
    "raw_diagnostics_only",
}
_EXPLICIT_FALSE_QUALITY_FLAGS = {
    "quality_ok",
    "session_quality_ok",
    "feature_quality_ok",
    "input_coverage_ok",
    "evidence_passed",
    "productionEvidencePassed",
}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on", "passed", "pass"}


def _explicit_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    text = str(value or "").strip().lower()
    return text in {"0", "false", "no", "n", "off", "failed", "fail", "rejected", "blocked"}


def _text(data: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None:
            text = str(value).strip().lower()
            if text:
                return text
    return ""


def _result(allowed: bool, reason_code: str, *, detail: str = "") -> Dict[str, Any]:
    return {
        "allowed": bool(allowed),
        "reason_code": str(reason_code or ("allowed" if allowed else "blocked")),
        "user_safe_reason": "Session is trusted for training." if allowed else "This session cannot be used for training.",
        "eligibility_version": TRAINING_SESSION_ELIGIBILITY_VERSION,
        "detail": str(detail or ""),
    }


def assess_positive_training_session(
    meta: Optional[Mapping[str, Any]],
    *,
    session_path: str = "",
    user_id: str = "",
    is_accepted_session_fn: Optional[Callable[[str, Mapping[str, Any]], bool]] = None,
    session_quality_ok_fn: Optional[Callable[[Mapping[str, Any]], bool]] = None,
    production_allowed_fn: Callable[..., bool] = production_positive_training_allowed,
) -> Dict[str, Any]:
    """Return a fail-closed positive-training eligibility decision.

    Positive owner evidence must be independently trusted before any feature
    extraction happens.  The caller may pass project-specific accepted/quality
    functions; if those functions raise, the session is rejected.
    """

    data: Dict[str, Any] = dict(meta or {})
    if not data:
        return _result(False, "missing_metadata")

    if not _truthy(data.get("metadata_trusted")):
        return _result(False, "metadata_not_trusted")
    integrity = _text(data, "metadata_integrity")
    if integrity not in _ALLOWED_INTEGRITY_STATES:
        return _result(False, "metadata_integrity_not_verified", detail=integrity or "missing")
    if _truthy(data.get("metadata_inferred")):
        return _result(False, "metadata_inferred_only")

    if user_id:
        expected_user = slugify_username(user_id)
        meta_user = slugify_username(str(data.get("user_id") or ""))
        if not meta_user or meta_user != expected_user:
            return _result(False, "session_user_mismatch")

    session_kind = _text(data, "session_kind", "kind")
    if session_kind not in _ALLOWED_POSITIVE_SESSION_KINDS:
        return _result(False, "unsupported_session_kind", detail=session_kind or "missing")

    for key in ("final_decision", "archive_label", "decision", "label"):
        decision = _text(data, key)
        if decision in _SENSITIVE_DECISIONS:
            return _result(False, "sensitive_decision_label", detail=key)

    for key in ("source", "evidence_source", "collection_source", "runtime_mode"):
        source = _text(data, key)
        if source in _SHADOW_OR_TEST_SOURCES:
            return _result(False, "shadow_or_test_source", detail=key)

    for key in ("bundle_role", "model_status", "candidate_status", "rollout_status", "runtime_rollout_stage"):
        state = _text(data, key)
        if state in _CANDIDATE_OR_INTERNAL_STATES:
            return _result(False, "candidate_or_internal_state", detail=key)

    for key in _BLOCKED_TRUE_FLAGS:
        if _truthy(data.get(key)):
            return _result(False, "blocked_flag_present", detail=key)

    if data.get("training_eligible") is not None and _explicit_false(data.get("training_eligible")):
        return _result(False, "training_eligible_false")

    for key in _EXPLICIT_FALSE_QUALITY_FLAGS:
        if data.get(key) is not None and _explicit_false(data.get(key)):
            return _result(False, "failed_or_low_quality_evidence", detail=key)

    evidence_status = _text(data, "evidence_status", "production_evidence_status", "productionEvidenceStatus")
    if evidence_status in {"failed", "fail", "rejected", "blocked", "partial", "shadow_only"}:
        return _result(False, "failed_or_incomplete_evidence", detail=evidence_status)

    if is_accepted_session_fn is not None:
        try:
            if not bool(is_accepted_session_fn(session_path, data)):
                return _result(False, "not_accepted_archive")
        except Exception:
            LOGGER.debug("Accepted-session eligibility check failed", exc_info=True)
            return _result(False, "accepted_check_failed")

    if session_quality_ok_fn is not None:
        try:
            if not bool(session_quality_ok_fn(data)):
                return _result(False, "session_quality_gate_failed")
        except Exception:
            LOGGER.debug("Session-quality eligibility check failed", exc_info=True)
            return _result(False, "session_quality_check_failed")

    if session_path and not os.path.isdir(str(session_path)):
        return _result(False, "session_path_missing")

    try:
        if not bool(production_allowed_fn(data, user_id=user_id, session_path=session_path)):
            return _result(False, "production_positive_policy_denied")
    except Exception:
        LOGGER.debug("Production-positive eligibility policy failed", exc_info=True)
        return _result(False, "production_positive_policy_error")

    return _result(True, "allowed")


def positive_training_session_allowed(*args: Any, **kwargs: Any) -> bool:
    """Boolean convenience wrapper for call sites that do not need reasons."""

    return bool(assess_positive_training_session(*args, **kwargs).get("allowed"))


__all__ = [
    "TRAINING_SESSION_ELIGIBILITY_VERSION",
    "assess_positive_training_session",
    "positive_training_session_allowed",
]
