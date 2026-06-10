"""Privacy-safe warning feedback and shadow-learning queues.

Phase 4 guardrails:
- feedback is an audit signal, not production training data;
- confirmed intruder / suspicious feedback can never become a positive sample;
- verified-legit feedback may be used only by shadow/evaluation paths until promoted
  through the existing shadow governance gate.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import paths
from utils.identity import slugify_username

FEEDBACK_POLICY_VERSION = "phase4-feedback-v1"
FACE_FEEDBACK_SHADOW_POLICY_VERSION = "phase14-face-feedback-shadow-evidence-v1"
FEEDBACK_SOURCE_PRE_LOCK_FACE_CONFIRMATION = "pre_lock_face_confirmation"
FEEDBACK_LABEL_PRE_LOCK_FACE_FALSE_POSITIVE = "pre_lock_face_confirmation_false_positive_candidate"
FEEDBACK_LABEL_VERIFIED_LEGIT = "verified_legit_after_warning"
FEEDBACK_LABEL_CONFIRMED_INTRUDER = "confirmed_intruder"
FEEDBACK_LABEL_IGNORED = "user_ignored_feedback"
ALLOWED_FEEDBACK_LABELS = {
    FEEDBACK_LABEL_VERIFIED_LEGIT,
    FEEDBACK_LABEL_CONFIRMED_INTRUDER,
    FEEDBACK_LABEL_IGNORED,
}
PRODUCTION_POSITIVE_BLOCK_LABELS = {
    FEEDBACK_LABEL_VERIFIED_LEGIT,
    FEEDBACK_LABEL_CONFIRMED_INTRUDER,
    FEEDBACK_LABEL_IGNORED,
    FEEDBACK_LABEL_PRE_LOCK_FACE_FALSE_POSITIVE,
}
SHADOW_ALLOWED_LABELS = {FEEDBACK_LABEL_VERIFIED_LEGIT}
SENSITIVE_DECISION_LABELS = {"intruder", "suspicious", "rejected", "unauthorized", "interrupted"}


def _append_jsonl(path: str, entry: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass


def feedback_root_dir(user_id: str) -> str:
    safe = slugify_username(user_id)
    root = os.path.join(paths.data_dir(), "feedback", safe or "unknown")
    os.makedirs(root, exist_ok=True)
    return root


def feedback_log_path(user_id: str) -> str:
    return os.path.join(feedback_root_dir(user_id), "warning_feedback.jsonl")


def shadow_feedback_queue_path(user_id: str) -> str:
    return os.path.join(feedback_root_dir(user_id), "shadow_evaluation_queue.jsonl")


def _now_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _sanitize_text(value: Any, limit: int = 160) -> str:
    text = str(value or "").strip()
    text = text.replace("\r", " ").replace("\n", " ")
    return text[: max(1, int(limit))]


def _normalize_label(label: Any) -> str:
    normalized = str(label or "").strip().lower()
    aliases = {
        "yes": FEEDBACK_LABEL_VERIFIED_LEGIT,
        "it_was_me": FEEDBACK_LABEL_VERIFIED_LEGIT,
        "me": FEEDBACK_LABEL_VERIFIED_LEGIT,
        "no": FEEDBACK_LABEL_CONFIRMED_INTRUDER,
        "someone_else": FEEDBACK_LABEL_CONFIRMED_INTRUDER,
        "intruder": FEEDBACK_LABEL_CONFIRMED_INTRUDER,
        "ignore": FEEDBACK_LABEL_IGNORED,
        "later": FEEDBACK_LABEL_IGNORED,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in ALLOWED_FEEDBACK_LABELS:
        raise ValueError(f"Unsupported feedback label: {label}")
    return normalized


def _compact_runtime_context(runtime_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    state = runtime_state if isinstance(runtime_state, dict) else {}
    return {
        "decision": _sanitize_text(state.get("decision") or state.get("final_decision") or "", 48),
        "risk": int(state.get("risk") or 0),
        "avg_risk": float(state.get("avg_risk") or 0.0),
        "warning_count": int(state.get("warning_count") or state.get("warnings") or 0),
        "reason_code": _sanitize_text(state.get("runtime_diagnostic_code") or "", 96),
        "confirmation_rule": _sanitize_text(state.get("runtime_confirmation_rule") or "", 96),
        "quality_gate_applied": bool(state.get("runtime_quality_gate_applied")),
        "calibration_mature": bool(state.get("runtime_calibration_mature")),
        "lock_allowed": bool(state.get("runtime_locking_allowed")),
    }


def build_feedback_record(
    *,
    user_id: str,
    label: str,
    session_id: str,
    decision_reason_code: str = "",
    model_version: str = "",
    policy_version: str = "",
    archive_path: str = "",
    decision: str = "",
    risk: Any = 0,
    runtime_state: Optional[Dict[str, Any]] = None,
    prompt_token: str = "",
) -> Dict[str, Any]:
    safe = slugify_username(user_id)
    normalized_label = _normalize_label(label)
    resolved_archive = os.path.abspath(str(archive_path or "").strip()) if archive_path else ""
    return {
        "schema_version": 1,
        "feedback_policy_version": FEEDBACK_POLICY_VERSION,
        "timestamp": _now_timestamp(),
        "user_id": safe,
        "session_id": _sanitize_text(session_id, 96),
        "label": normalized_label,
        "decision_reason_code": _sanitize_text(decision_reason_code, 128),
        "model_version": _sanitize_text(model_version, 96),
        "policy_version": _sanitize_text(policy_version or FEEDBACK_POLICY_VERSION, 96),
        "archive_path": resolved_archive,
        "decision": _sanitize_text(decision, 48),
        "risk": int(risk or 0),
        "prompt_token": _sanitize_text(prompt_token, 160),
        "runtime_context": _compact_runtime_context(runtime_state),
        "privacy_note": "No raw keyboard/mouse events, typed text, screenshots, webcam frames, secrets, or feature vectors are stored in feedback.",
        "production_training_allowed": False,
        "shadow_only": normalized_label in SHADOW_ALLOWED_LABELS,
    }


def record_warning_feedback(
    *,
    user_id: str,
    label: str,
    session_id: str,
    decision_reason_code: str = "",
    model_version: str = "",
    policy_version: str = "",
    archive_path: str = "",
    decision: str = "",
    risk: Any = 0,
    runtime_state: Optional[Dict[str, Any]] = None,
    prompt_token: str = "",
) -> Dict[str, Any]:
    record = build_feedback_record(
        user_id=user_id,
        label=label,
        session_id=session_id,
        decision_reason_code=decision_reason_code,
        model_version=model_version,
        policy_version=policy_version,
        archive_path=archive_path,
        decision=decision,
        risk=risk,
        runtime_state=runtime_state,
        prompt_token=prompt_token,
    )
    _append_jsonl(feedback_log_path(user_id), record)
    if record["label"] in SHADOW_ALLOWED_LABELS:
        _append_jsonl(shadow_feedback_queue_path(user_id), record)
    return record


def _iter_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except Exception:
        return []
    return rows


def latest_feedback_for_session(user_id: str, session_id: str = "", archive_path: str = "") -> Optional[Dict[str, Any]]:
    safe_session = _sanitize_text(session_id, 96)
    resolved_archive = os.path.normcase(os.path.abspath(str(archive_path or "").strip())) if archive_path else ""
    latest: Optional[Dict[str, Any]] = None
    for item in _iter_jsonl(feedback_log_path(user_id)):
        item_session = _sanitize_text(item.get("session_id"), 96)
        item_archive = os.path.normcase(os.path.abspath(str(item.get("archive_path") or "").strip())) if item.get("archive_path") else ""
        if safe_session and item_session == safe_session:
            latest = item
        elif resolved_archive and item_archive == resolved_archive:
            latest = item
    return latest


def production_positive_training_allowed(meta: Optional[Dict[str, Any]], *, user_id: str = "", session_path: str = "") -> bool:
    data = meta if isinstance(meta, dict) else {}
    session_kind = str(data.get("session_kind") or "").strip().lower()
    decision = str(data.get("final_decision") or data.get("archive_label") or data.get("decision") or data.get("label") or "").strip().lower()
    if decision in SENSITIVE_DECISION_LABELS:
        return False
    if bool(data.get("feedback_shadow_only")):
        return False
    evidence_source = str(data.get("source") or data.get("evidence_source") or "").strip().lower()
    collection_source = str(data.get("collection_source") or data.get("runtime_mode") or "").strip().lower()
    if evidence_source in {"shadow_evidence_monitor", "shadow_evidence", "runtime_shadow_evidence", "hybrid_direct_test_monitor"}:
        return False
    if collection_source in {"shadow_evidence", "shadow_evidence_monitor", "hybrid_direct_test"}:
        return False
    if bool(data.get("confirmedIntruderAfterLock") or data.get("confirmed_intruder") or data.get("is_confirmed_intruder_window")):
        return False
    if bool(data.get("false_positive_candidate")) or bool(data.get("verified_owner_after_anomaly")) or evidence_source == FEEDBACK_SOURCE_PRE_LOCK_FACE_CONFIRMATION:
        return False
    explicit_label = str(data.get("feedback_label") or data.get("user_feedback_label") or "").strip().lower()
    if explicit_label in PRODUCTION_POSITIVE_BLOCK_LABELS:
        return False
    if user_id:
        latest = latest_feedback_for_session(user_id, str(data.get("session_id") or ""), session_path)
        latest_label = str((latest or {}).get("label") or "").strip().lower()
        if latest_label in PRODUCTION_POSITIVE_BLOCK_LABELS:
            return False
    return session_kind in {"enrollment", "protected"}


def shadow_feedback_allows_session(meta: Optional[Dict[str, Any]], *, user_id: str = "", session_path: str = "") -> bool:
    data = meta if isinstance(meta, dict) else {}
    evidence_source = str(data.get("source") or data.get("evidence_source") or "").strip().lower()
    collection_source = str(data.get("collection_source") or data.get("runtime_mode") or "").strip().lower()
    if evidence_source in {"shadow_evidence_monitor", "shadow_evidence", "runtime_shadow_evidence", "hybrid_direct_test_monitor"}:
        return False
    if collection_source in {"shadow_evidence", "shadow_evidence_monitor", "hybrid_direct_test"}:
        return False
    if bool(data.get("confirmedIntruderAfterLock") or data.get("confirmed_intruder") or data.get("is_confirmed_intruder_window")):
        return False
    if bool(data.get("false_positive_candidate")) or bool(data.get("verified_owner_after_anomaly")) or evidence_source == FEEDBACK_SOURCE_PRE_LOCK_FACE_CONFIRMATION:
        return False
    if not bool(data.get("metadata_trusted")):
        return False
    if not os.path.isdir(session_path):
        return False
    explicit_label = str(data.get("feedback_label") or data.get("user_feedback_label") or "").strip().lower()
    if explicit_label == FEEDBACK_LABEL_VERIFIED_LEGIT:
        return True
    if user_id:
        latest = latest_feedback_for_session(user_id, str(data.get("session_id") or ""), session_path)
        return str((latest or {}).get("label") or "").strip().lower() == FEEDBACK_LABEL_VERIFIED_LEGIT
    return False


def list_shadow_feedback_queue(user_id: str) -> list[Dict[str, Any]]:
    return list(_iter_jsonl(shadow_feedback_queue_path(user_id)))
