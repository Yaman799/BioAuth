"""Persistent training-attempt bookkeeping for BioAuth auto-training.

This module records that a specific trusted training-data signature has already
been attempted. It does not decide training acceptance, model readiness,
shadow eligibility, production approval, or runtime promotion.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from typing import Any, Dict, Mapping

import re

import paths

TRAINING_ATTEMPT_STATE_FILENAME = "training_attempt_state.json"

TERMINAL_AUTO_TRAINING_ATTEMPT_RESULTS = {
    "rejected",
    "failed_offline_approval",
    "shadow_only",
    "approved_for_shadow",
    "already_evaluated",
    "failed",
    "training_failed",
    "evaluation_failed",
}


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _slugify_username(value: Any) -> str:
    text = _safe_text(value).lower()
    text = re.sub(r"[^a-z0-9_.-]+", "_", text).strip("._-")
    return text or "user"


def _user_model_dir(user_id: Any) -> str:
    return os.path.join(paths.models_dir(), f"user_{_slugify_username(user_id)}")


def training_attempt_state_path(user_id: Any) -> str:
    return os.path.join(_user_model_dir(user_id), TRAINING_ATTEMPT_STATE_FILENAME)


def _atomic_write_json(path: str, payload: Mapping[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def load_training_attempt_state(user_id: Any) -> Dict[str, Any]:
    path = training_attempt_state_path(user_id)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def normalize_training_attempt_result(*, ok: bool, model_status: Any = "", message_key: Any = "") -> str:
    status = _safe_text(model_status).lower()
    key = _safe_text(message_key).lower()
    if bool(ok):
        if status == "approved_for_production":
            return "approved_for_production"
        if status == "approved_for_shadow":
            return "shadow_only"
        if status == "rejected":
            return "rejected"
        if status in {"pending_evaluation", "missing", "untrained", ""}:
            return "pending_evaluation"
        return status
    if key in {"failed_offline_approval", "offline_approval_rejected", "candidate_rejected"}:
        return "failed_offline_approval"
    if key:
        return key
    return "failed"


def training_attempt_blocks_auto_retry(result: Any, status: Any = "") -> bool:
    result_text = _safe_text(result).lower()
    status_text = _safe_text(status).lower()
    return result_text in TERMINAL_AUTO_TRAINING_ATTEMPT_RESULTS or status_text in TERMINAL_AUTO_TRAINING_ATTEMPT_RESULTS



def remediation_training_signature(
    *,
    training_data_digest: Any = "",
    evidence_report_digest: Any = "",
    candidate_artifact_digest: Any = "",
    remediation_plan_id: Any = "",
    current_new_evidence: Mapping[str, Any] | None = None,
    source_gate: Any = "",
    action: Any = "",
) -> str:
    """Return a privacy-safe retry signature for remediation attempts.

    The signature includes aggregate/digest fields only. It deliberately avoids
    raw keyboard, mouse, biometric, or feature-vector values. Callers use it to
    prevent retry loops on the same failed training/evidence snapshot.
    """

    evidence = {}
    if isinstance(current_new_evidence, Mapping):
        for key, value in current_new_evidence.items():
            text_key = _safe_text(key)
            if not text_key:
                continue
            try:
                evidence[text_key] = max(0, int(value or 0))
            except (TypeError, ValueError, OverflowError):
                evidence[text_key] = 0
    payload = {
        "training_data_digest": _safe_text(training_data_digest),
        "evidence_report_digest": _safe_text(evidence_report_digest),
        "candidate_artifact_digest": _safe_text(candidate_artifact_digest),
        "remediation_plan_id": _safe_text(remediation_plan_id),
        "source_gate": _safe_text(source_gate),
        "action": _safe_text(action),
        "current_new_evidence": evidence,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def record_training_attempt(
    *,
    user_id: Any,
    signature: Any,
    result: Any,
    status: Any = "",
    rejection_reason: Any = "",
    source: Any = "",
    evidence_report_digest: Any = "",
    candidate_artifact_digest: Any = "",
    remediation_plan_id: Any = "",
    remediation_retry_signature: Any = "",
    attempted_at: float | None = None,
    previous_state: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    signature_text = _safe_text(signature)
    state = dict(previous_state) if isinstance(previous_state, Mapping) else load_training_attempt_state(user_id)
    clock = time.time() if attempted_at is None else float(attempted_at)
    state.update(
        {
            "last_attempted_training_signature": signature_text,
            "last_attempted_training_at": clock,
            "last_attempted_training_result": _safe_text(result),
            "last_attempted_training_status": _safe_text(status),
            "last_attempted_training_rejection_reason": _safe_text(rejection_reason),
            "last_attempted_training_source": _safe_text(source),
            "last_attempted_evidence_report_digest": _safe_text(evidence_report_digest),
            "last_attempted_candidate_artifact_digest": _safe_text(candidate_artifact_digest),
            "last_attempted_remediation_plan_id": _safe_text(remediation_plan_id),
            "last_attempted_remediation_retry_signature": _safe_text(remediation_retry_signature),
        }
    )
    if _safe_text(source).lower() == "auto":
        state["last_auto_training_signature"] = signature_text
    if _safe_text(result).lower() == "approved_for_production" or _safe_text(status).lower() == "approved_for_production":
        state["last_successful_training_signature"] = signature_text
    if signature_text:
        _atomic_write_json(training_attempt_state_path(user_id), state)
    return dict(state)


__all__ = [
    "TERMINAL_AUTO_TRAINING_ATTEMPT_RESULTS",
    "TRAINING_ATTEMPT_STATE_FILENAME",
    "load_training_attempt_state",
    "normalize_training_attempt_result",
    "record_training_attempt",
    "remediation_training_signature",
    "training_attempt_blocks_auto_retry",
    "training_attempt_state_path",
]
