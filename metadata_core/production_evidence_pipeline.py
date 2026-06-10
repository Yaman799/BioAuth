from __future__ import annotations

"""Privacy-safe Production Evidence data pipeline.

This module bridges real runtime/shadow monitor summaries into the existing
Production Evidence Gate v2 computation. It stores only decision summaries,
artifact/schema identifiers, counters, booleans, and reason codes. It must not
store raw keyboard, mouse, biometric samples, or feature vectors.
"""

from dataclasses import dataclass, field
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import paths
from evaluation_core.production_evidence import (
    ConfirmedIntruderEvidenceMetrics,
    ModelAgreementMetrics,
    PostUnlockEvidenceMetrics,
    ProductionEvidenceGateResult,
    ProductionEvidencePromotionEffect,
    ProductionEvidenceReasonCode,
    ProductionEvidenceReport,
    ProductionEvidenceStatus,
    RuntimeSafetyMetrics,
    assert_privacy_safe_payload,
    build_production_evidence_report,
    build_production_evidence_report_from_summaries,
    normalize_reason_codes,
)
from metadata_core.feature_schema_contract import (
    CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION,
    FEATURE_SCHEMA_CONTRACT_VERSION,
    WINDOW_SCHEMA_VERSION,
    build_feature_schema_contract,
)
from shadow_core.background_contracts import (
    SHADOW_EVIDENCE_LEDGER_FILENAME,
    shadow_evidence_ledger_path,
    shadow_eval_report_path,
)
from utils.identity import slugify_username

PRODUCTION_EVIDENCE_LEDGER_SCHEMA_VERSION = 1
PRODUCTION_EVIDENCE_LEDGER_FILENAME = "production_evidence_records.jsonl"
PRODUCTION_EVIDENCE_MAX_RECORDS = 500
SHADOW_EVIDENCE_LEDGER_SCHEMA_VERSION = "shadow-evidence-ledger-v1"
SHADOW_EVIDENCE_LEDGER_POLICY_VERSION = "commercial-core-03-shadow-evidence-ledger-v1"
SHADOW_EVIDENCE_LEDGER_DEFAULT_MAX_BYTES = 5 * 1024 * 1024
PRE_LOCK_FACE_CONFIRMATION_EVIDENCE_SOURCE = "pre_lock_face_confirmation"
POST_LOCK_FEEDBACK_EVIDENCE_SOURCE = "post_lock_confirmation_feedback"
FACE_FEEDBACK_SHADOW_POLICY_VERSION = "phase14-face-feedback-shadow-evidence-v1"
POST_LOCK_FEEDBACK_SHADOW_POLICY_VERSION = "commercial-core-04-post-lock-feedback-evidence-v1"

_LOW_RISK_BUCKETS = {"low", "trusted", "safe", "owner"}
_WARNING_BUCKETS = {"medium", "warning", "high", "critical", "lock"}
_LOCK_DECISIONS = {"lock", "locked", "intruder_lock", "device_locked"}
_WARNING_DECISIONS = {"warning", "warn", "suspicious", "intruder", "lock", "locked", "reject", "rejected"}
_TRUSTED_DECISIONS = {"trusted", "legit", "legitimate", "accepted", "owner", "allow", "allowed", "ok", "pass"}
_UNKNOWN_DECISIONS = {"", "unknown", "pending", "abstain", "none", "no_decision"}


def _now_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)


def _normalize_decision(value: Any) -> str:
    text = _as_str(value).strip().lower()
    if text in _TRUSTED_DECISIONS:
        return "trusted"
    if text in {"suspicious", "warning", "warn", "intruder", "reject", "rejected", "deny", "denied"}:
        return "warning"
    if text in _LOCK_DECISIONS:
        return "lock"
    if text in _UNKNOWN_DECISIONS:
        return "unknown"
    return text or "unknown"


def _risk_bucket_from_value(value: Any) -> str:
    text = _as_str(value).strip().lower()
    if text in _LOW_RISK_BUCKETS:
        return "low"
    if text in {"medium", "warning"}:
        return "warning"
    if text in {"high", "critical", "lock", "intruder"}:
        return "high"
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "unknown"
    # Runtime risk values in BioAuth are usually 0-100, while evidence fixtures
    # may use probabilities. Treat both conservatively.
    if number <= 1.0:
        if number <= 0.35:
            return "low"
        if number < 0.70:
            return "warning"
        return "high"
    if number <= 35.0:
        return "low"
    if number < 70.0:
        return "warning"
    return "high"


def _bucket_to_evidence_decision(bucket: str, fallback: str = "unknown") -> str:
    bucket = str(bucket or "").strip().lower()
    if bucket == "low":
        return "trusted"
    if bucket in {"warning", "medium"}:
        return "warning"
    if bucket in {"high", "critical", "lock"}:
        return "lock"
    return _normalize_decision(fallback)


def _file_digest(path: str) -> str:
    text = str(path or "").strip()
    if not text or not os.path.exists(text) or not os.path.isfile(text):
        return ""
    digest = hashlib.sha256()
    with open(text, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_reason_codes(reason_codes: Sequence[Any] | str | None) -> list[str]:
    try:
        return list(normalize_reason_codes(reason_codes, allow_unknown=True))
    except Exception:
        return [ProductionEvidenceReasonCode.UNKNOWN_REASON_CODE]


def evidence_ledger_dir(user_id: str) -> str:
    safe = slugify_username(user_id or "") or "unknown"
    directory = os.path.join(paths.evidence_dir(), "production_evidence", f"user_{safe}")
    os.makedirs(directory, exist_ok=True)
    return directory


def evidence_ledger_path(user_id: str) -> str:
    return os.path.join(evidence_ledger_dir(user_id), PRODUCTION_EVIDENCE_LEDGER_FILENAME)


@dataclass(frozen=True)
class ProductionEvidenceRecord:
    window_id: str
    timestamp: str = field(default_factory=_now_timestamp)
    user_id: str = ""
    candidate_artifact_digest: str = ""
    baseline_artifact_digest: str = ""
    runtime_schema_version: str = ""
    feature_schema_version: str = ""
    feature_schema_contract_version: str = FEATURE_SCHEMA_CONTRACT_VERSION
    window_schema_version: str = WINDOW_SCHEMA_VERSION
    feature_extension_profile: str = CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION
    feature_schema_digest: str = ""
    candidate_decision: str = "unknown"
    baseline_decision: str = ""
    candidate_risk_bucket: str = "unknown"
    baseline_risk_bucket: str = "unknown"
    candidate_would_lock_if_production: bool = False
    baseline_would_lock_if_production: bool = False
    is_trusted_window: bool = False
    trusted_anchor_type: str = ""
    is_post_unlock_window: bool = False
    is_confirmed_intruder_window: bool = False
    feature_quality_ok: bool = False
    unknown_or_abstain: bool = False
    schema_ok: bool = True
    source: str = "runtime"
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    false_positive_candidate: bool = False
    verified_owner_after_anomaly: bool = False
    eligible_for_shadow_evidence: bool = False
    eligible_for_direct_production_training: bool = False
    production_decision_changed: bool = False
    production_threshold_changed: bool = False
    production_model_pointer_changed: bool = False
    protected_sessions_unlocked: bool = False
    excluded_from_positive_training: bool = False
    production_training_allowed: bool = False
    face_confirmation_status: str = ""
    policy_version: str = ""
    production_model_version: str = ""
    classic_decision_summary: str = ""
    sequence_decision_summary: str = ""
    hybrid_decision_summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", slugify_username(self.user_id or ""))
        object.__setattr__(self, "candidate_decision", _normalize_decision(self.candidate_decision))
        object.__setattr__(self, "baseline_decision", _normalize_decision(self.baseline_decision) if self.baseline_decision else "")
        object.__setattr__(self, "candidate_risk_bucket", _risk_bucket_from_value(self.candidate_risk_bucket))
        object.__setattr__(self, "baseline_risk_bucket", _risk_bucket_from_value(self.baseline_risk_bucket))
        object.__setattr__(self, "reason_codes", tuple(_safe_reason_codes(self.reason_codes)))
        assert_privacy_safe_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": PRODUCTION_EVIDENCE_LEDGER_SCHEMA_VERSION,
            "window_id": str(self.window_id or ""),
            "timestamp": str(self.timestamp or ""),
            "user_id": str(self.user_id or ""),
            "candidate_artifact_digest": str(self.candidate_artifact_digest or ""),
            "baseline_artifact_digest": str(self.baseline_artifact_digest or ""),
            "runtime_schema_version": str(self.runtime_schema_version or ""),
            "feature_schema_version": str(self.feature_schema_version or ""),
            "feature_schema_contract_version": str(self.feature_schema_contract_version or FEATURE_SCHEMA_CONTRACT_VERSION),
            "window_schema_version": str(self.window_schema_version or WINDOW_SCHEMA_VERSION),
            "feature_extension_profile": str(self.feature_extension_profile or CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION),
            "feature_schema_digest": str(self.feature_schema_digest or ""),
            "candidate_decision": str(self.candidate_decision or "unknown"),
            "baseline_decision": str(self.baseline_decision or ""),
            "candidate_risk_bucket": str(self.candidate_risk_bucket or "unknown"),
            "baseline_risk_bucket": str(self.baseline_risk_bucket or "unknown"),
            "candidate_would_lock_if_production": bool(self.candidate_would_lock_if_production),
            "baseline_would_lock_if_production": bool(self.baseline_would_lock_if_production),
            "is_trusted_window": bool(self.is_trusted_window),
            "trusted_anchor_type": str(self.trusted_anchor_type or ""),
            "is_post_unlock_window": bool(self.is_post_unlock_window),
            "is_confirmed_intruder_window": bool(self.is_confirmed_intruder_window),
            "feature_quality_ok": bool(self.feature_quality_ok),
            "unknown_or_abstain": bool(self.unknown_or_abstain),
            "schema_ok": bool(self.schema_ok),
            "source": str(self.source or "runtime"),
            "reason_codes": list(self.reason_codes),
            "false_positive_candidate": bool(self.false_positive_candidate),
            "verified_owner_after_anomaly": bool(self.verified_owner_after_anomaly),
            "eligible_for_shadow_evidence": bool(self.eligible_for_shadow_evidence),
            "eligible_for_direct_production_training": bool(self.eligible_for_direct_production_training),
            "production_decision_changed": bool(self.production_decision_changed),
            "production_threshold_changed": bool(self.production_threshold_changed),
            "production_model_pointer_changed": bool(self.production_model_pointer_changed),
            "protected_sessions_unlocked": bool(self.protected_sessions_unlocked),
            "excluded_from_positive_training": bool(self.excluded_from_positive_training),
            "production_training_allowed": bool(self.production_training_allowed),
            "face_confirmation_status": str(self.face_confirmation_status or ""),
            "policy_version": str(self.policy_version or ""),
            "production_model_version": str(self.production_model_version or ""),
            "classic_decision_summary": str(self.classic_decision_summary or ""),
            "sequence_decision_summary": str(self.sequence_decision_summary or ""),
            "hybrid_decision_summary": str(self.hybrid_decision_summary or ""),
        }
        assert_privacy_safe_payload(payload)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ProductionEvidenceRecord":
        data = _as_mapping(payload)
        assert_privacy_safe_payload(data)
        return cls(
            window_id=_as_str(data.get("window_id") or data.get("decision_id") or data.get("event_id")),
            timestamp=_as_str(data.get("timestamp") or data.get("evaluated_at") or data.get("time") or _now_timestamp()),
            user_id=_as_str(data.get("user_id") or data.get("profile_id") or data.get("expected_user")),
            candidate_artifact_digest=_as_str(data.get("candidate_artifact_digest")),
            baseline_artifact_digest=_as_str(data.get("baseline_artifact_digest")),
            runtime_schema_version=_as_str(data.get("runtime_schema_version")),
            feature_schema_version=_as_str(data.get("feature_schema_version")),
            feature_schema_contract_version=_as_str(data.get("feature_schema_contract_version") or FEATURE_SCHEMA_CONTRACT_VERSION),
            window_schema_version=_as_str(data.get("window_schema_version") or WINDOW_SCHEMA_VERSION),
            feature_extension_profile=_as_str(data.get("feature_extension_profile") or CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION),
            feature_schema_digest=_as_str(data.get("feature_schema_digest")),
            candidate_decision=_as_str(data.get("candidate_decision")),
            baseline_decision=_as_str(data.get("baseline_decision")),
            candidate_risk_bucket=_as_str(data.get("candidate_risk_bucket") or data.get("candidate_risk") or data.get("risk")),
            baseline_risk_bucket=_as_str(data.get("baseline_risk_bucket") or data.get("baseline_risk")),
            candidate_would_lock_if_production=_as_bool(data.get("candidate_would_lock_if_production")),
            baseline_would_lock_if_production=_as_bool(data.get("baseline_would_lock_if_production")),
            is_trusted_window=_as_bool(data.get("is_trusted_window") or data.get("trusted_window")),
            trusted_anchor_type=_as_str(data.get("trusted_anchor_type")),
            is_post_unlock_window=_as_bool(data.get("is_post_unlock_window") or data.get("post_unlock_trusted")),
            is_confirmed_intruder_window=_as_bool(data.get("is_confirmed_intruder_window") or data.get("confirmed_intruder")),
            feature_quality_ok=_as_bool(data.get("feature_quality_ok") or data.get("quality_ok")),
            unknown_or_abstain=_as_bool(data.get("unknown_or_abstain") or data.get("unknown") or data.get("abstained")),
            schema_ok=_as_bool(data.get("schema_ok"), True),
            source=_as_str(data.get("source") or "runtime"),
            reason_codes=tuple(data.get("reason_codes") or ()),
            false_positive_candidate=_as_bool(data.get("false_positive_candidate")),
            verified_owner_after_anomaly=_as_bool(data.get("verified_owner_after_anomaly")),
            eligible_for_shadow_evidence=_as_bool(data.get("eligible_for_shadow_evidence")),
            eligible_for_direct_production_training=_as_bool(data.get("eligible_for_direct_production_training")),
            production_decision_changed=_as_bool(data.get("production_decision_changed")),
            production_threshold_changed=_as_bool(data.get("production_threshold_changed")),
            production_model_pointer_changed=_as_bool(data.get("production_model_pointer_changed")),
            protected_sessions_unlocked=_as_bool(data.get("protected_sessions_unlocked")),
            excluded_from_positive_training=_as_bool(data.get("excluded_from_positive_training")),
            production_training_allowed=_as_bool(data.get("production_training_allowed")),
            face_confirmation_status=_as_str(data.get("face_confirmation_status")),
            policy_version=_as_str(data.get("policy_version")),
            production_model_version=_as_str(data.get("production_model_version")),
            classic_decision_summary=_as_str(data.get("classic_decision_summary")),
            sequence_decision_summary=_as_str(data.get("sequence_decision_summary")),
            hybrid_decision_summary=_as_str(data.get("hybrid_decision_summary")),
        )


def _is_shadow_evidence_ledger_path(path: str | os.PathLike[str] | None) -> bool:
    return os.path.basename(str(path or "")) == SHADOW_EVIDENCE_LEDGER_FILENAME


def _shadow_ledger_max_bytes() -> int:
    raw = os.environ.get("BIOAUTH_SHADOW_EVIDENCE_LEDGER_MAX_BYTES")
    try:
        value = int(str(raw).strip()) if raw not in (None, "") else SHADOW_EVIDENCE_LEDGER_DEFAULT_MAX_BYTES
    except (TypeError, ValueError, OverflowError):
        value = SHADOW_EVIDENCE_LEDGER_DEFAULT_MAX_BYTES
    return max(1024, int(value))


def _rotate_shadow_ledger_if_needed(path: str) -> dict[str, Any]:
    """Rotate an oversized shadow ledger without deleting any evidence file.

    Rotation uses a timestamped sidecar path next to the active ledger. This keeps
    the commercial no-loss contract: the active file is moved away only when it is
    over the configured size and a fresh file is created by the next append.
    """

    if not _is_shadow_evidence_ledger_path(path) or not os.path.exists(path):
        return {"rotated": False}
    max_bytes = _shadow_ledger_max_bytes()
    try:
        size = os.path.getsize(path)
    except OSError:
        return {"rotated": False, "reason": "stat_failed"}
    if size < max_bytes:
        return {"rotated": False, "size_bytes": int(size), "max_bytes": int(max_bytes)}
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    archive_path = f"{path}.{stamp}.rotated"
    suffix = 0
    while os.path.exists(archive_path):
        suffix += 1
        archive_path = f"{path}.{stamp}.{suffix}.rotated"
    try:
        os.replace(path, archive_path)
    except OSError as exc:
        return {"rotated": False, "reason": f"rotate_failed:{exc}", "size_bytes": int(size), "max_bytes": int(max_bytes)}
    return {"rotated": True, "archive_path": archive_path, "size_bytes": int(size), "max_bytes": int(max_bytes)}


def _shadow_ledger_envelope(path: str, *, user_id: str, record: Mapping[str, Any], rotation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not _is_shadow_evidence_ledger_path(path):
        return {}
    return {
        "shadow_ledger_schema_version": SHADOW_EVIDENCE_LEDGER_SCHEMA_VERSION,
        "shadow_ledger_policy_version": SHADOW_EVIDENCE_LEDGER_POLICY_VERSION,
        "ledger_kind": "shadow_evidence",
        "ledger_user_id": slugify_username(user_id or "") or "unknown",
        "ledger_record_kind": str(record.get("source") or "shadow_evidence"),
        "written_at": _now_timestamp(),
        "rotated_before_append": bool((rotation or {}).get("rotated")),
    }


def _write_shadow_eval_report_if_needed(user_id: str, ledger_path: str, latest_record: Mapping[str, Any]) -> None:
    """Best-effort latest shadow ledger report. Never blocks runtime writes."""

    if not _is_shadow_evidence_ledger_path(ledger_path):
        return
    try:
        report = build_shadow_evidence_ledger_report(user_id, ledger_path=ledger_path, latest_record=latest_record)
        report_path = shadow_eval_report_path(user_id)
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        tmp = f"{report_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(report, handle, sort_keys=True, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, report_path)
    except Exception:
        # Ledger append is the authoritative action. Reporting is advisory and
        # must never break the protection/runtime path.
        return


def append_evidence_record(user_id: str, record: ProductionEvidenceRecord | Mapping[str, Any], *, ledger_path: str | None = None) -> dict[str, Any]:
    safe = slugify_username(user_id or "") or "unknown"
    rec = record if isinstance(record, ProductionEvidenceRecord) else ProductionEvidenceRecord.from_dict(record)
    path = ledger_path or evidence_ledger_path(safe)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rotation = _rotate_shadow_ledger_if_needed(path)
    payload = {**rec.to_dict(), "user_id": rec.user_id or safe}
    payload.update(_shadow_ledger_envelope(path, user_id=rec.user_id or safe, record=payload, rotation=rotation))
    assert_privacy_safe_payload(payload)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")
    _write_shadow_eval_report_if_needed(rec.user_id or safe, path, payload)
    return payload


def read_evidence_records(user_id: str, *, ledger_path: str | None = None, limit: int = PRODUCTION_EVIDENCE_MAX_RECORDS) -> list[dict[str, Any]]:
    path = ledger_path or evidence_ledger_path(user_id)
    if not os.path.exists(path):
        return []
    records: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-max(1, int(limit or PRODUCTION_EVIDENCE_MAX_RECORDS)) :]
    except OSError:
        return []
    for line in lines:
        try:
            data = json.loads(line)
            rec = ProductionEvidenceRecord.from_dict(data).to_dict()
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        records.append(rec)
    return records


def validate_shadow_evidence_ledger(user_id: str, *, ledger_path: str | None = None, limit: int = PRODUCTION_EVIDENCE_MAX_RECORDS) -> dict[str, Any]:
    """Validate shadow ledger readability and privacy without changing files."""

    safe = slugify_username(user_id or "") or "unknown"
    path = ledger_path or shadow_evidence_ledger_path(safe)
    total_lines = 0
    valid_records = 0
    invalid_lines = 0
    raw_field_violations = 0
    missing_envelope = 0
    if not os.path.exists(path):
        return {
            "ok": True,
            "exists": False,
            "path": path,
            "records_total": 0,
            "records_valid": 0,
            "invalid_lines": 0,
            "raw_field_violations": 0,
            "missing_envelope": 0,
        }
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-max(1, int(limit or PRODUCTION_EVIDENCE_MAX_RECORDS)) :]
    except OSError as exc:
        return {"ok": False, "exists": True, "path": path, "reason": f"read_failed:{exc}"}
    for line in lines:
        total_lines += 1
        try:
            data = json.loads(line)
            assert_privacy_safe_payload(data)
            ProductionEvidenceRecord.from_dict(data)
        except ValueError as exc:
            invalid_lines += 1
            if "raw biometric" in str(exc).lower() or "behavioral" in str(exc).lower():
                raw_field_violations += 1
            continue
        except (TypeError, json.JSONDecodeError):
            invalid_lines += 1
            continue
        valid_records += 1
        if data.get("shadow_ledger_schema_version") != SHADOW_EVIDENCE_LEDGER_SCHEMA_VERSION:
            missing_envelope += 1
    ok = invalid_lines == 0 and raw_field_violations == 0
    return {
        "ok": ok,
        "exists": True,
        "path": path,
        "records_total": total_lines,
        "records_valid": valid_records,
        "invalid_lines": invalid_lines,
        "raw_field_violations": raw_field_violations,
        "missing_envelope": missing_envelope,
        "schema_version": SHADOW_EVIDENCE_LEDGER_SCHEMA_VERSION,
        "policy_version": SHADOW_EVIDENCE_LEDGER_POLICY_VERSION,
    }


def build_shadow_evidence_ledger_report(
    user_id: str,
    *,
    ledger_path: str | None = None,
    latest_record: Mapping[str, Any] | None = None,
    limit: int = PRODUCTION_EVIDENCE_MAX_RECORDS,
) -> dict[str, Any]:
    """Return a small privacy-safe operational report for the shadow ledger."""

    safe = slugify_username(user_id or "") or "unknown"
    path = ledger_path or shadow_evidence_ledger_path(safe)
    records = read_evidence_records(safe, ledger_path=path, limit=limit)
    by_source: dict[str, int] = {}
    candidate_locks = 0
    baseline_locks = 0
    quality_ok = 0
    false_positive = 0
    verified_owner = 0
    confirmed_intruder = 0
    post_unlock = 0
    post_lock_feedback = 0
    post_lock_false_positive = 0
    post_lock_confirmed_intruder = 0
    face_confirmation_events = 0
    digests: set[str] = set()
    schemas: set[str] = set()
    windows: set[str] = set()
    for rec in records:
        source = _as_str(rec.get("source") or "unknown") or "unknown"
        by_source[source] = by_source.get(source, 0) + 1
        if _as_bool(rec.get("candidate_would_lock_if_production")):
            candidate_locks += 1
        if _as_bool(rec.get("baseline_would_lock_if_production")):
            baseline_locks += 1
        if _as_bool(rec.get("feature_quality_ok")):
            quality_ok += 1
        if _as_bool(rec.get("false_positive_candidate")):
            false_positive += 1
        if _as_bool(rec.get("verified_owner_after_anomaly")):
            verified_owner += 1
        if _as_bool(rec.get("is_confirmed_intruder_window")):
            confirmed_intruder += 1
        if _as_bool(rec.get("is_post_unlock_window")):
            post_unlock += 1
        if source == POST_LOCK_FEEDBACK_EVIDENCE_SOURCE:
            post_lock_feedback += 1
            if _as_bool(rec.get("false_positive_candidate")):
                post_lock_false_positive += 1
            if _as_bool(rec.get("is_confirmed_intruder_window")):
                post_lock_confirmed_intruder += 1
        if source == PRE_LOCK_FACE_CONFIRMATION_EVIDENCE_SOURCE:
            face_confirmation_events += 1
        if _as_str(rec.get("candidate_artifact_digest")):
            digests.add(_as_str(rec.get("candidate_artifact_digest")))
        if _as_str(rec.get("runtime_schema_version")):
            schemas.add(_as_str(rec.get("runtime_schema_version")))
        if _as_str(rec.get("window_id")):
            windows.add(_as_str(rec.get("window_id")))
    validation = validate_shadow_evidence_ledger(safe, ledger_path=path, limit=limit)
    report = {
        "schema_version": SHADOW_EVIDENCE_LEDGER_SCHEMA_VERSION,
        "policy_version": SHADOW_EVIDENCE_LEDGER_POLICY_VERSION,
        "user_id": safe,
        "ledger_path": path,
        "records_total": len(records),
        "unique_window_count": len(windows),
        "sources": by_source,
        "candidate_lock_count": candidate_locks,
        "baseline_lock_count": baseline_locks,
        "quality_ok_windows": quality_ok,
        "false_positive_candidate_count": false_positive,
        "verified_owner_after_anomaly_count": verified_owner,
        "confirmed_intruder_count": confirmed_intruder,
        "post_unlock_window_count": post_unlock,
        "post_lock_feedback_count": post_lock_feedback,
        "post_lock_false_positive_feedback_count": post_lock_false_positive,
        "post_lock_confirmed_intruder_feedback_count": post_lock_confirmed_intruder,
        "face_confirmation_event_count": face_confirmation_events,
        "candidate_artifact_digests": sorted(digests)[:20],
        "runtime_schema_versions": sorted(schemas)[:20],
        "validation": validation,
        "latest_window_id": _as_str((latest_record or {}).get("window_id")),
        "latest_source": _as_str((latest_record or {}).get("source")),
        "updated_at": _now_timestamp(),
    }
    assert_privacy_safe_payload(report)
    return report


def _evidence_record_identity(record: Mapping[str, Any]) -> str:
    """Return a stable privacy-safe identity for de-duplicating ledger reads."""

    try:
        normalized = ProductionEvidenceRecord.from_dict(record).to_dict()
    except (TypeError, ValueError):
        normalized = dict(record or {})
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def read_all_evidence_records_for_user(user_id: str) -> list[dict[str, Any]]:
    """Read production and shadow evidence ledgers for a user without moving records.

    Runtime shadow monitors write privacy-safe evidence records to the shadow
    evidence ledger. Production evidence reporting needs read visibility into
    those records, but writes must remain isolated and missing ledgers must fail
    closed as empty reads.
    """

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ledger in (None, shadow_evidence_ledger_path(user_id)):
        for record in read_evidence_records(user_id, ledger_path=ledger):
            key = _evidence_record_identity(record)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    return records


def _record_matches_expected(record: Mapping[str, Any], *, expected_candidate_artifact_digest: str = "", expected_runtime_schema_version: str = "") -> tuple[bool, list[str]]:
    reasons: list[str] = []
    candidate_digest = _as_str(record.get("candidate_artifact_digest")).strip()
    runtime_schema = _as_str(record.get("runtime_schema_version")).strip()
    schema_ok = _as_bool(record.get("schema_ok"), True)
    expected_candidate = _as_str(expected_candidate_artifact_digest).strip()
    expected_schema = _as_str(expected_runtime_schema_version).strip()

    # Commercial-Core-22F: when a current candidate/schema identity is known,
    # ledger records without that exact identity are stale evidence and must be
    # ignored, not allowed to satisfy promotion / production evidence.
    if expected_candidate and candidate_digest != expected_candidate:
        reasons.append(ProductionEvidenceReasonCode.CANDIDATE_DIGEST_MISMATCH)
    if expected_schema and runtime_schema != expected_schema:
        reasons.append(ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH)
    if not schema_ok:
        reasons.append(ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH)
    return (not reasons), reasons


def _record_baseline_digest_reason(record: Mapping[str, Any], *, expected_baseline_artifact_digest: str = "") -> str:
    """Return a fail-closed reason when a comparable baseline window is not artifact-matched.

    Candidate/schema matching is handled separately. This check is intentionally
    scoped to model agreement windows so legacy records still contribute safe
    runtime/post-unlock diagnostics when no expected baseline digest is supplied,
    but cannot satisfy trusted model agreement for a different or missing
    production baseline artifact.
    """

    expected = _as_str(expected_baseline_artifact_digest).strip()
    if not expected:
        return ""
    actual = _as_str(record.get("baseline_artifact_digest")).strip()
    if not actual or actual != expected:
        return ProductionEvidenceReasonCode.BASELINE_ARTIFACT_DIGEST_MISMATCH
    return ""


def _record_matches_remediation_expected(record: Mapping[str, Any], *, expected_candidate_artifact_digest: str = "", expected_runtime_schema_version: str = "") -> tuple[bool, list[str]]:
    """Strict artifact/schema match for remediation progress counters only.

    Production Evidence aggregation can preserve older partial ledger evidence for
    gate diagnostics. Remediation progress is stricter: a shadow comparison window
    must be tied to the exact candidate digest and runtime schema when those
    expectations are known, otherwise it must not satisfy new-evidence progress.
    """

    reasons: list[str] = []
    candidate_digest = _as_str(record.get("candidate_artifact_digest"))
    runtime_schema = _as_str(record.get("runtime_schema_version"))
    schema_ok = _as_bool(record.get("schema_ok"), True)
    if expected_candidate_artifact_digest and candidate_digest != expected_candidate_artifact_digest:
        reasons.append(ProductionEvidenceReasonCode.CANDIDATE_DIGEST_MISMATCH)
    if expected_runtime_schema_version and runtime_schema != expected_runtime_schema_version:
        reasons.append(ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH)
    if not schema_ok:
        reasons.append(ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH)
    return (not reasons), reasons


def _record_to_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    candidate_bucket = _as_str(record.get("candidate_risk_bucket"))
    baseline_bucket = _as_str(record.get("baseline_risk_bucket"))
    candidate_decision = _normalize_decision(record.get("candidate_decision") or _bucket_to_evidence_decision(candidate_bucket))
    baseline_decision = _normalize_decision(record.get("baseline_decision") or _bucket_to_evidence_decision(baseline_bucket, "")) if record.get("baseline_decision") else ""
    return {
        "window_id": _as_str(record.get("window_id")),
        "candidate_decision": candidate_decision,
        "baseline_decision": baseline_decision,
        "candidate_risk_bucket": candidate_bucket,
        "baseline_risk_bucket": baseline_bucket,
        "candidate_low_risk": candidate_bucket == "low" or candidate_decision == "trusted",
        "candidate_lock": _as_bool(record.get("candidate_would_lock_if_production")) or candidate_decision == "lock",
        "baseline_lock": _as_bool(record.get("baseline_would_lock_if_production")) or baseline_decision == "lock",
        "trusted_window": _as_bool(record.get("is_trusted_window")),
        "post_unlock_trusted": _as_bool(record.get("is_post_unlock_window")) and _as_bool(record.get("is_trusted_window")),
        "confirmed_intruder": _as_bool(record.get("is_confirmed_intruder_window")),
        "feature_quality_ok": _as_bool(record.get("feature_quality_ok")),
        "unknown": _as_bool(record.get("unknown_or_abstain")) or candidate_decision == "unknown",
        "simulated_false_lock": _as_bool(record.get("is_trusted_window")) and (_as_bool(record.get("candidate_would_lock_if_production")) or candidate_decision == "lock"),
        "warning_triggered": candidate_decision in {"warning", "lock"},
        "source": _as_str(record.get("source")),
        "false_positive_candidate": _as_bool(record.get("false_positive_candidate")),
        "verified_owner_after_anomaly": _as_bool(record.get("verified_owner_after_anomaly")),
        "eligible_for_shadow_evidence": _as_bool(record.get("eligible_for_shadow_evidence")),
        "eligible_for_direct_production_training": _as_bool(record.get("eligible_for_direct_production_training")),
        "production_decision_changed": _as_bool(record.get("production_decision_changed")),
        "production_threshold_changed": _as_bool(record.get("production_threshold_changed")),
        "production_model_pointer_changed": _as_bool(record.get("production_model_pointer_changed")),
        "protected_sessions_unlocked": _as_bool(record.get("protected_sessions_unlocked")),
        "excluded_from_positive_training": _as_bool(record.get("excluded_from_positive_training")),
        "face_confirmation_status": _as_str(record.get("face_confirmation_status")),
        "policy_version": _as_str(record.get("policy_version")),
        "production_model_version": _as_str(record.get("production_model_version")),
        "classic_decision_summary": _as_str(record.get("classic_decision_summary")),
        "sequence_decision_summary": _as_str(record.get("sequence_decision_summary")),
        "hybrid_decision_summary": _as_str(record.get("hybrid_decision_summary")),
    }



# These fragments describe weak *window-quality* evidence only.
# Model-agreement gaps such as ``baseline_decision_missing`` and
# ``insufficient_model_agreement_data`` must not make an otherwise valid
# shadow_evidence runtime window weak for remediation collection progress;
# those reasons still block model agreement and production eligibility in the
# ProductionEvidenceReport / production approval gates.
_REMEDIATION_WEAK_REASON_FRAGMENTS = (
    "startup",
    "transition",
    "insufficient_evidence",
    "insufficient_window",
    "short_window",
    "short-window",
    "short window",
    "low_quality",
    "low-quality",
    "low quality",
    "feature_quality_too_low",
    "unknown",
    "invalid",
)


def _record_reason_codes(record: Mapping[str, Any]) -> list[str]:
    codes = record.get("reason_codes") if isinstance(record, Mapping) else []
    if isinstance(codes, str):
        values: Iterable[Any] = [codes]
    elif isinstance(codes, Iterable):
        values = codes
    else:
        values = []
    result: list[str] = []
    for code in values:
        text = _as_str(code).strip().lower()
        if text and text not in result:
            result.append(text)
    return result


def _is_shadow_evidence_source(record: Mapping[str, Any]) -> bool:
    source = _as_str(record.get("source") or record.get("evidence_source")).strip().lower()
    return source in {"shadow_evidence_monitor", "shadow_evidence", "runtime_shadow_evidence", PRE_LOCK_FACE_CONFIRMATION_EVIDENCE_SOURCE, POST_LOCK_FEEDBACK_EVIDENCE_SOURCE}


def _has_weak_remediation_reason(record: Mapping[str, Any]) -> bool:
    for code in _record_reason_codes(record):
        if code == ProductionEvidenceReasonCode.UNKNOWN_REASON_CODE:
            return True
        if any(fragment in code for fragment in _REMEDIATION_WEAK_REASON_FRAGMENTS):
            return True
    return False


def _record_is_strong_remediation_window(record: Mapping[str, Any]) -> bool:
    decision = _normalize_decision(record.get("candidate_decision"))
    if not _is_shadow_evidence_source(record):
        return False
    if not _as_bool(record.get("feature_quality_ok")):
        return False
    if _as_bool(record.get("unknown_or_abstain")) or decision == "unknown":
        return False
    if _as_bool(record.get("is_confirmed_intruder_window")):
        return False
    if _as_bool(record.get("false_positive_candidate")):
        # Face-confirmed false-positive candidates are valuable for false-positive
        # analysis, but they are not trusted-owner collection windows and must not
        # satisfy remediation evidence quotas by themselves.
        return False
    if _has_weak_remediation_reason(record):
        return False
    return True


def remediation_progress_from_evidence_records(
    records: Sequence[Mapping[str, Any]] | None,
    *,
    candidate_artifact_digest: str = "",
    runtime_schema_version: str = "",
) -> dict[str, Any]:
    """Return privacy-safe remediation counts derived from shadow evidence ledger records.

    Counts are aggregate-only. They never include raw keyboard, mouse, biometric
    samples, feature vectors, or raw event streams. Shadow comparison progress
    uses only digest/schema-matched shadow-evidence records with acceptable
    feature quality and a non-unknown candidate decision. Missing baseline
    decisions may still count as collected shadow evidence, but model agreement
    remains incomplete in the ProductionEvidenceReport path.
    """

    counts = {
        "shadow_comparison_windows": 0,
        "post_unlock_windows": 0,
        "hard_negative_events": 0,
    }
    reason_codes: list[str] = []
    total = 0
    accepted = 0
    weak = 0
    for raw in records or []:
        try:
            rec = ProductionEvidenceRecord.from_dict(raw).to_dict()
        except (TypeError, ValueError):
            continue
        total += 1
        matches, reasons = _record_matches_remediation_expected(
            rec,
            expected_candidate_artifact_digest=candidate_artifact_digest,
            expected_runtime_schema_version=runtime_schema_version,
        )
        if not matches:
            if ProductionEvidenceReasonCode.CANDIDATE_DIGEST_MISMATCH in reasons:
                reason_codes.append("remediation_shadow_evidence_digest_mismatch")
            if ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH in reasons:
                reason_codes.append("remediation_shadow_evidence_runtime_schema_mismatch")
            continue
        if not _is_shadow_evidence_source(rec):
            continue
        accepted += 1
        if _as_bool(rec.get("is_confirmed_intruder_window")):
            # Safe hard-negative progress only. This must never become owner-positive training evidence.
            counts["hard_negative_events"] += 1
            reason_codes.append("remediation_confirmed_intruder_evidence_observed")
            continue
        if not _record_is_strong_remediation_window(rec):
            weak += 1
            reason_codes.append("remediation_shadow_evidence_insufficient_quality")
            continue
        counts["shadow_comparison_windows"] += 1
        if _as_bool(rec.get("is_post_unlock_window")) and _as_bool(rec.get("is_trusted_window")):
            counts["post_unlock_windows"] += 1
    if counts["shadow_comparison_windows"] > 0:
        reason_codes.append("remediation_shadow_evidence_progress")
    if total and not counts["shadow_comparison_windows"] and weak:
        reason_codes.append("remediation_shadow_evidence_insufficient_quality")
    payload = {
        "source": "shadow_evidence_monitor",
        "records_total": total,
        "records_accepted": accepted,
        "counts": counts,
        "reason_codes": sorted(set(reason_codes)),
    }
    assert_privacy_safe_payload(payload)
    return payload


def aggregate_evidence_records(
    records: Sequence[Mapping[str, Any]] | None,
    *,
    candidate_artifact_digest: str = "",
    baseline_artifact_digest: str = "",
    evaluation_report_digest: str = "",
    runtime_schema_version: str = "",
) -> dict[str, Any]:
    """Convert privacy-safe ledger records into ProductionEvidenceReport inputs.

    Commercial-Core-22F contract:
    - evidence for an older candidate digest or runtime schema is ignored as stale;
    - stale evidence is reported in non-blocking counters;
    - stale evidence must not add ``candidate_digest_mismatch`` / schema mismatch
      gate reason codes that keep the current candidate pending forever;
    - only records matching the current candidate/schema can satisfy current
      production or selection evidence.
    """

    model_windows: list[dict[str, Any]] = []
    post_unlock_windows: list[dict[str, Any]] = []
    confirmed_intruder_events: list[dict[str, Any]] = []
    runtime_decisions: list[dict[str, Any]] = []
    reason_codes: list[str] = []
    total_records = 0
    accepted_records = 0
    baseline_missing = 0
    baseline_digest_mismatch = 0
    ignored_candidate_digest = 0
    ignored_runtime_schema = 0
    ignored_identity = 0
    malformed_records = 0
    for raw in records or []:
        try:
            rec = ProductionEvidenceRecord.from_dict(raw).to_dict()
        except (TypeError, ValueError):
            malformed_records += 1
            continue
        total_records += 1
        matches, reasons = _record_matches_expected(
            rec,
            expected_candidate_artifact_digest=candidate_artifact_digest,
            expected_runtime_schema_version=runtime_schema_version,
        )
        if not matches:
            ignored_identity += 1
            if ProductionEvidenceReasonCode.CANDIDATE_DIGEST_MISMATCH in reasons:
                ignored_candidate_digest += 1
            if ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH in reasons:
                ignored_runtime_schema += 1
            # Stale identity records are intentionally ignored. They remain visible
            # in counters but must not become gate-blocking reason codes for the
            # *current* candidate.
            continue
        accepted_records += 1
        summary = _record_to_summary(rec)
        runtime_decisions.append(summary)
        if summary["post_unlock_trusted"]:
            post_unlock_windows.append(summary)
        if summary["confirmed_intruder"]:
            confirmed_intruder_events.append(summary)
        if summary.get("baseline_decision"):
            baseline_reason = _record_baseline_digest_reason(
                rec,
                expected_baseline_artifact_digest=baseline_artifact_digest,
            )
            if baseline_reason:
                baseline_digest_mismatch += 1
                reason_codes.append(baseline_reason)
            else:
                model_windows.append(summary)
        else:
            baseline_missing += 1
    if accepted_records and not model_windows:
        reason_codes.append(ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA)
    if baseline_missing and accepted_records:
        reason_codes.append(ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING)
    if baseline_digest_mismatch:
        reason_codes.append(ProductionEvidenceReasonCode.BASELINE_ARTIFACT_DIGEST_MISMATCH)
    return {
        "candidate_artifact_digest": candidate_artifact_digest,
        "baseline_artifact_digest": baseline_artifact_digest,
        "evaluation_report_digest": evaluation_report_digest,
        "runtime_schema_version": runtime_schema_version,
        "model_comparison_windows": model_windows,
        "post_unlock_windows": post_unlock_windows,
        "confirmed_intruder_events": confirmed_intruder_events,
        "runtime_decision_summaries": runtime_decisions,
        "pipeline_reason_codes": sorted(set(reason_codes)),
        "pipeline_record_count": total_records,
        "pipeline_accepted_record_count": accepted_records,
        "pipeline_malformed_record_count": malformed_records,
        "pipeline_identity_filtered_record_count": ignored_identity,
        "pipeline_ignored_candidate_digest_record_count": ignored_candidate_digest,
        "pipeline_ignored_runtime_schema_record_count": ignored_runtime_schema,
        "pipeline_current_candidate_digest": candidate_artifact_digest,
        "pipeline_current_runtime_schema_version": runtime_schema_version,
    }


def _merge_reason_codes(existing: Sequence[Any], extra: Sequence[Any]) -> tuple[str, ...]:
    merged: list[str] = []
    for code in list(existing or ()) + list(extra or ()):  # type: ignore[arg-type]
        try:
            normalized = normalize_reason_codes([code], allow_unknown=True)
        except Exception:
            normalized = (ProductionEvidenceReasonCode.UNKNOWN_REASON_CODE,)
        for item in normalized:
            if item not in merged:
                merged.append(item)
    return tuple(merged)


def _with_pipeline_gate_reasons(report: ProductionEvidenceReport, reason_codes: Sequence[Any]) -> ProductionEvidenceReport:
    extra = tuple(code for code in _merge_reason_codes((), reason_codes) if code)
    if not extra:
        return report
    merged_codes = _merge_reason_codes(report.gate.reason_codes, extra + (ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PARTIAL,))
    status = report.gate.status
    effect = report.gate.promotion_effect
    if status is ProductionEvidenceStatus.PASS:
        status = ProductionEvidenceStatus.PARTIAL
        effect = ProductionEvidencePromotionEffect.SHADOW_ONLY
    return ProductionEvidenceReport(
        schema_version=report.schema_version,
        candidate_artifact_digest=report.candidate_artifact_digest,
        baseline_artifact_digest=report.baseline_artifact_digest,
        evaluation_report_digest=report.evaluation_report_digest,
        runtime_schema_version=report.runtime_schema_version,
        model_agreement=report.model_agreement,
        post_unlock_evidence=report.post_unlock_evidence,
        confirmed_intruder_evidence=report.confirmed_intruder_evidence,
        runtime_safety=report.runtime_safety,
        gate=ProductionEvidenceGateResult(status=status, promotion_effect=effect, reason_codes=merged_codes),
    )


def build_production_evidence_report_from_records(
    records: Sequence[Mapping[str, Any]] | None,
    *,
    candidate_artifact_digest: str = "",
    baseline_artifact_digest: str = "",
    evaluation_report_digest: str = "",
    runtime_schema_version: str = "",
) -> ProductionEvidenceReport:
    summaries = aggregate_evidence_records(
        records,
        candidate_artifact_digest=candidate_artifact_digest,
        baseline_artifact_digest=baseline_artifact_digest,
        evaluation_report_digest=evaluation_report_digest,
        runtime_schema_version=runtime_schema_version,
    )
    report = build_production_evidence_report_from_summaries(summaries)
    return _with_pipeline_gate_reasons(report, summaries.get("pipeline_reason_codes") or [])


def build_production_evidence_report_for_user(
    user_id: str,
    *,
    candidate_artifact_digest: str = "",
    baseline_artifact_digest: str = "",
    evaluation_report_digest: str = "",
    runtime_schema_version: str = "",
    explicit_summaries: Mapping[str, Any] | None = None,
) -> ProductionEvidenceReport:
    records = read_all_evidence_records_for_user(user_id)
    if records:
        return build_production_evidence_report_from_records(
            records,
            candidate_artifact_digest=candidate_artifact_digest,
            baseline_artifact_digest=baseline_artifact_digest,
            evaluation_report_digest=evaluation_report_digest,
            runtime_schema_version=runtime_schema_version,
        )
    return build_production_evidence_report_from_summaries(explicit_summaries or {})




def load_shadow_evidence_summary_for_candidate(
    user_id: str,
    *,
    candidate_artifact_digest: str = "",
    baseline_artifact_digest: str = "",
    evaluation_report_digest: str = "",
    runtime_schema_version: str = "",
) -> dict[str, Any]:
    """Load privacy-safe shadow/runtime ledger evidence for dashboard approval.

    The returned payload contains aggregate counts and a ProductionEvidenceReport
    only. It intentionally does not expose raw keyboard, mouse, biometric samples,
    or feature vectors. Missing baseline/model-agreement data remains partial and
    shadow-only through the report gate.
    """

    records = read_all_evidence_records_for_user(user_id)
    summaries = aggregate_evidence_records(
        records,
        candidate_artifact_digest=candidate_artifact_digest,
        baseline_artifact_digest=baseline_artifact_digest,
        evaluation_report_digest=evaluation_report_digest,
        runtime_schema_version=runtime_schema_version,
    )
    report = build_production_evidence_report_from_summaries(summaries)
    report = _with_pipeline_gate_reasons(report, summaries.get("pipeline_reason_codes") or [])
    accepted = _as_int(summaries.get("pipeline_accepted_record_count"), 0)
    total = _as_int(summaries.get("pipeline_record_count"), 0)
    quality_ok = 0
    unknown = 0
    simulated_false_locks = 0
    for summary in summaries.get("runtime_decision_summaries") or []:
        if not isinstance(summary, Mapping):
            continue
        if _as_bool(summary.get("feature_quality_ok")):
            quality_ok += 1
        if _as_bool(summary.get("unknown")):
            unknown += 1
        if _as_bool(summary.get("simulated_false_lock")):
            simulated_false_locks += 1
    remediation_progress = remediation_progress_from_evidence_records(
        records,
        candidate_artifact_digest=candidate_artifact_digest,
        runtime_schema_version=runtime_schema_version,
    )
    payload = {
        "source": "shadow_evidence_monitor",
        "windows_collected": accepted,
        "windowsCollected": accepted,
        "records_total": total,
        "records_accepted": accepted,
        "records_ignored_for_identity": _as_int(summaries.get("pipeline_identity_filtered_record_count"), 0),
        "records_ignored_for_candidate_digest": _as_int(summaries.get("pipeline_ignored_candidate_digest_record_count"), 0),
        "records_ignored_for_runtime_schema": _as_int(summaries.get("pipeline_ignored_runtime_schema_record_count"), 0),
        "identity_filter": {
            "current_candidate_artifact_digest": str(candidate_artifact_digest or ""),
            "current_runtime_schema_version": str(runtime_schema_version or ""),
            "accepted_record_count": accepted,
            "ignored_record_count": _as_int(summaries.get("pipeline_identity_filtered_record_count"), 0),
            "ignored_candidate_digest_record_count": _as_int(summaries.get("pipeline_ignored_candidate_digest_record_count"), 0),
            "ignored_runtime_schema_record_count": _as_int(summaries.get("pipeline_ignored_runtime_schema_record_count"), 0),
        },
        "quality_ok_windows": quality_ok,
        "unknown_windows": unknown,
        "simulated_false_lock_count": simulated_false_locks,
        "reason_codes": list(report.gate.reason_codes),
        "pipeline_reason_codes": list(summaries.get("pipeline_reason_codes") or []),
        "remediation_progress": dict(remediation_progress.get("counts") or {}),
        "remediationProgress": dict(remediation_progress.get("counts") or {}),
        "remediation_progress_reason_codes": list(remediation_progress.get("reason_codes") or []),
        "production_evidence": report.to_dict(),
    }
    assert_privacy_safe_payload(payload)
    return payload


def _meta_truth_is_owner(meta: Mapping[str, Any]) -> bool:
    decision = str(meta.get("final_decision") or meta.get("archive_label") or meta.get("decision") or "").strip().lower()
    return decision in {"legit", "legitimate", "accepted", "verified_legit_after_warning"}


def _meta_truth_is_intruder(meta: Mapping[str, Any]) -> bool:
    decision = str(meta.get("final_decision") or meta.get("archive_label") or meta.get("decision") or "").strip().lower()
    return bool(meta.get("confirmedIntruderAfterLock") or meta.get("confirmed_intruder") or decision in {"intruder", "confirmed_intruder"})


def append_shadow_evaluation_record(
    *,
    user_id: str,
    session_metadata: Mapping[str, Any],
    session_path: str,
    candidate_artifact_digest: str,
    baseline_artifact_digest: str,
    runtime_schema_version: str = "",
    feature_schema_version: str = "",
    candidate_decision: Any,
    baseline_decision: Any,
    candidate_risk: Any = None,
    baseline_risk: Any = None,
) -> dict[str, Any]:
    meta = _as_mapping(session_metadata)
    candidate_bucket = _risk_bucket_from_value(candidate_risk)
    baseline_bucket = _risk_bucket_from_value(baseline_risk)
    rec = ProductionEvidenceRecord(
        window_id=str(meta.get("session_id") or os.path.basename(str(session_path or "")) or f"shadow-{int(time.time())}"),
        timestamp=_as_str(meta.get("evaluated_at") or _now_timestamp()),
        user_id=user_id,
        candidate_artifact_digest=candidate_artifact_digest,
        baseline_artifact_digest=baseline_artifact_digest,
        runtime_schema_version=runtime_schema_version,
        feature_schema_version=feature_schema_version,
        candidate_decision=_normalize_decision(candidate_decision or _bucket_to_evidence_decision(candidate_bucket)),
        baseline_decision=_normalize_decision(baseline_decision or _bucket_to_evidence_decision(baseline_bucket)),
        candidate_risk_bucket=candidate_bucket,
        baseline_risk_bucket=baseline_bucket,
        candidate_would_lock_if_production=_normalize_decision(candidate_decision) == "lock" or candidate_bucket == "high",
        baseline_would_lock_if_production=_normalize_decision(baseline_decision) == "lock" or baseline_bucket == "high",
        is_trusted_window=_meta_truth_is_owner(meta),
        trusted_anchor_type="shadow_verified_session" if _meta_truth_is_owner(meta) else "",
        is_post_unlock_window=_as_bool(meta.get("post_unlock_trusted_window") or meta.get("postUnlockTrustedWindow")),
        is_confirmed_intruder_window=_meta_truth_is_intruder(meta),
        feature_quality_ok=_as_bool(meta.get("quality_ok") or meta.get("session_quality_ok") or meta.get("metadata_trusted")),
        unknown_or_abstain=_normalize_decision(candidate_decision) == "unknown",
        schema_ok=True,
        source="shadow_evaluation",
    )
    return append_evidence_record(user_id, rec)


def _first_text(source: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        text = _as_str(source.get(key)).strip()
        if text:
            return text[:160]
    return ""


_SAFE_DECISION_SUMMARY_KEYS = frozenset(
    {
        "used",
        "available",
        "probability",
        "risk",
        "score",
        "decision",
        "final",
        "status",
        "reason",
        "reason_code",
        "backend",
        "artifact_file",
        "sequence_length",
        "shadow_only",
        "used_for_decision",
        "confidence_bucket",
        "risk_bucket",
    }
)

_UNSAFE_DECISION_SUMMARY_KEYS = frozenset(
    {
        "raw",
        "raw_score",
        "raw_scores",
        "raw_sample",
        "raw_samples",
        "sample",
        "samples",
        "tensor",
        "tensors",
        "embedding",
        "embeddings",
        "feature",
        "features",
        "feature_vector",
        "feature_vectors",
        "feature_values",
        "raw_feature_values",
        "keyboard_event",
        "keyboard_events",
        "raw_keyboard",
        "raw_keyboard_events",
        "mouse_event",
        "mouse_events",
        "raw_mouse",
        "raw_mouse_events",
        "biometric_sample",
        "biometric_samples",
        "biometric_features",
        "window_samples",
    }
)


def _summary_key_is_safe(key: Any) -> bool:
    normalized = str(key).strip().lower()
    if not normalized or normalized in _UNSAFE_DECISION_SUMMARY_KEYS:
        return False
    if normalized.startswith("raw_") or normalized.endswith("_raw"):
        return False
    return normalized in _SAFE_DECISION_SUMMARY_KEYS


def _safe_summary_scalar(key: str, value: Any) -> Any:
    if value is None or isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            return None
        return round(value, 6)
    text = _as_str(value).strip()
    if not text:
        return None
    if key == "artifact_file":
        text = os.path.basename(text)
    return text[:120]


def _safe_decision_summary_mapping(source: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for raw_key, raw_value in source.items():
        key = str(raw_key).strip().lower()
        if not _summary_key_is_safe(key):
            continue
        value = _safe_summary_scalar(key, raw_value)
        if value is not None:
            clean[key] = value
    return clean


def _safe_decision_summary(source: Mapping[str, Any], *keys: str) -> str:
    values: dict[str, Any] = {}
    selected_keys = keys or tuple(sorted(_SAFE_DECISION_SUMMARY_KEYS))
    for key in selected_keys:
        if key not in source:
            continue
        raw = source.get(key)
        if isinstance(raw, Mapping):
            clean = _safe_decision_summary_mapping(raw)
            if clean:
                values[str(key)] = clean
        else:
            safe_value = _safe_summary_scalar(str(key).strip().lower(), raw)
            if safe_value is not None:
                values[str(key)] = safe_value
    if not values:
        return ""
    encoded = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return encoded[:640]


def _runtime_classic_decision_summary(payload: Mapping[str, Any], prediction_payload: Mapping[str, Any], *, decision: str, risk_bucket: str) -> str:
    summary_source = {
        "decision": decision or payload.get("model_decision") or payload.get("decision"),
        "final": prediction_payload.get("final") or payload.get("final_decision") or payload.get("effective_decision"),
        "status": prediction_payload.get("status") or payload.get("status"),
        "risk": prediction_payload.get("risk") if prediction_payload.get("risk") is not None else payload.get("risk"),
        "score": prediction_payload.get("score") if prediction_payload.get("score") is not None else payload.get("score"),
        "probability": prediction_payload.get("probability") if prediction_payload.get("probability") is not None else payload.get("probability"),
        "confidence_bucket": prediction_payload.get("confidence_bucket") or payload.get("confidence_bucket"),
        "risk_bucket": risk_bucket or prediction_payload.get("risk_bucket") or payload.get("risk_bucket"),
        "backend": prediction_payload.get("decision_source") or payload.get("decision_source") or prediction_payload.get("backend") or payload.get("backend"),
        "reason": prediction_payload.get("reason") or payload.get("runtime_diagnostic_code") or payload.get("reason"),
    }
    return _safe_decision_summary(summary_source)


def _runtime_nested_decision_summary(source: Mapping[str, Any], nested_key: str, *fallback_keys: str) -> str:
    summary = _safe_decision_summary(source, nested_key)
    if summary:
        return summary
    return _safe_decision_summary(source, *fallback_keys)


def append_pre_lock_face_confirmation_shadow_evidence_record(
    *,
    user_id: str,
    session_id: str,
    risk: Any = None,
    avg_risk: Any = None,
    state: Mapping[str, Any] | None = None,
    face_result: Mapping[str, Any] | None = None,
    timestamp: str = "",
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """Append a privacy-safe, shadow-only false-positive candidate event.

    Verified owner-after-risky-prediction events are useful for future
    false-positive analysis, but they are not enrollment data, not owner-positive
    production-training samples, and not a signal to change production models,
    thresholds, gates, active pointers, auto-promotion, or Protected Sessions.
    """

    payload = _as_mapping(state)
    face_payload = _as_mapping(face_result)
    safe_user = user_id or _as_str(payload.get("user_id") or payload.get("expected_user"))
    safe_session = session_id or _as_str(payload.get("session_id")) or f"pre-lock-face-{int(time.time() * 1000)}"
    candidate_digest = _first_text(payload, "production_model_digest", "candidate_artifact_digest", "active_model_digest", "model_digest", "artifact_digest")
    runtime_schema = _first_text(payload, "runtime_schema_version", "feature_schema_version")
    model_version = _first_text(payload, "production_model_version", "model_version", "runtime_model_version")
    reason_codes = [ProductionEvidenceReasonCode.SHADOW_EVIDENCE_LOCK_SUPPRESSED]
    if not _first_text(payload, "baseline_decision"):
        reason_codes.extend([ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING, ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA])
    rec = ProductionEvidenceRecord(
        window_id=str(safe_session),
        timestamp=_as_str(timestamp or payload.get("updated_at_text") or _now_timestamp()),
        user_id=safe_user,
        candidate_artifact_digest=candidate_digest,
        baseline_artifact_digest=_first_text(payload, "baseline_artifact_digest"),
        runtime_schema_version=runtime_schema,
        feature_schema_version=_first_text(payload, "feature_schema_version") or runtime_schema,
        candidate_decision="lock",
        baseline_decision=_first_text(payload, "baseline_decision"),
        candidate_risk_bucket=_risk_bucket_from_value(avg_risk if avg_risk is not None else risk),
        baseline_risk_bucket=_risk_bucket_from_value(payload.get("baseline_risk")),
        candidate_would_lock_if_production=True,
        baseline_would_lock_if_production=_as_bool(payload.get("baseline_would_lock_if_production")),
        is_trusted_window=True,
        trusted_anchor_type="pre_lock_face_confirmation_shadow_only",
        is_post_unlock_window=False,
        is_confirmed_intruder_window=False,
        feature_quality_ok=True,
        unknown_or_abstain=False,
        schema_ok=not _as_bool(payload.get("technical_failure")),
        source=PRE_LOCK_FACE_CONFIRMATION_EVIDENCE_SOURCE,
        reason_codes=tuple(reason_codes),
        false_positive_candidate=True,
        verified_owner_after_anomaly=True,
        eligible_for_shadow_evidence=True,
        eligible_for_direct_production_training=False,
        production_decision_changed=False,
        production_threshold_changed=False,
        production_model_pointer_changed=False,
        protected_sessions_unlocked=False,
        excluded_from_positive_training=True,
        production_training_allowed=False,
        face_confirmation_status=_as_str(face_payload.get("status") or "verified_owner")[:80],
        policy_version=FACE_FEEDBACK_SHADOW_POLICY_VERSION,
        production_model_version=model_version,
        classic_decision_summary=_safe_decision_summary(payload, "decision", "final_decision", "model_decision", "effective_decision", "runtime_diagnostic_code", "runtime_confirmation_rule"),
        sequence_decision_summary=_safe_decision_summary(payload, "sequence_decision", "sequence_decision_summary", "deep_sequence_decision"),
        hybrid_decision_summary=_safe_decision_summary(payload, "hybrid_decision", "hybrid_decision_summary", "runtime_hybrid_decision"),
    )
    target_ledger_path = ledger_path or shadow_evidence_ledger_path(safe_user)
    return append_evidence_record(safe_user, rec, ledger_path=target_ledger_path)


def _normalize_post_lock_feedback_label(label: Any, feedback_record: Mapping[str, Any] | None = None) -> tuple[str, str, bool]:
    raw = _as_str(label or (_as_mapping(feedback_record).get("label"))).strip().lower()
    aliases = {
        "yes": "verified_legit_after_warning",
        "it_was_me": "verified_legit_after_warning",
        "me": "verified_legit_after_warning",
        "legit": "verified_legit_after_warning",
        "owner": "verified_legit_after_warning",
        "no": "confirmed_intruder",
        "someone_else": "confirmed_intruder",
        "intruder": "confirmed_intruder",
    }
    normalized = aliases.get(raw, raw)
    if normalized == "confirmed_intruder":
        return normalized, "confirmed_intruder_after_lock", False
    if normalized == "verified_legit_after_warning":
        return normalized, "verified_legit_after_lock", True
    raise ValueError(f"unsupported post-lock feedback label: {label}")


def append_post_lock_feedback_shadow_evidence_record(
    *,
    user_id: str,
    state: Mapping[str, Any] | None,
    label: str,
    feedback_record: Mapping[str, Any] | None = None,
    timestamp: str = "",
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """Append a privacy-safe post-lock adjudication record to the shadow ledger.

    Post-lock Yes/No feedback is recorded as shadow evidence only. It may help
    selection-based promotion and future offline retraining, but it must never
    modify the live production model, threshold, active runtime pointer, or
    protected-session enforcement decision.
    """

    payload = _as_mapping(state)
    feedback = _as_mapping(feedback_record)
    normalized_label, classification, user_verified = _normalize_post_lock_feedback_label(label, feedback)
    prompt = _as_mapping(payload.get("feedback_prompt"))
    safe_user = user_id or _as_str(payload.get("user_id") or payload.get("expected_user"))
    event_id = _first_text(payload, "postLockConfirmationEventId", "blockedEventId", "lastIntruderEnforcementId") or _as_str(prompt.get("event_id"))
    session_id = _first_text(payload, "postLockConfirmationEventSessionId", "session_id") or _as_str(prompt.get("session_id"))
    safe_window = event_id or session_id or f"post-lock-feedback-{int(time.time() * 1000)}"
    candidate_digest = _first_text(
        payload,
        "postLockConfirmationCandidateDigest",
        "candidate_artifact_digest",
        "production_model_digest",
        "active_model_digest",
        "model_digest",
        "artifact_digest",
    )
    runtime_schema = _first_text(payload, "runtime_schema_version", "feature_schema_version")
    model_version = _as_str(feedback.get("model_version")) or _first_text(payload, "postLockConfirmationModelVersion", "production_model_version", "model_version", "runtime_model_version")
    risk = payload.get("postLockConfirmationRisk") if payload.get("postLockConfirmationRisk") is not None else payload.get("risk")
    avg_risk = payload.get("postLockConfirmationAvgRisk") if payload.get("postLockConfirmationAvgRisk") is not None else payload.get("avg_risk")
    reason_codes: list[str] = []
    if user_verified:
        reason_codes.append(ProductionEvidenceReasonCode.POST_UNLOCK_FALSE_LOCK_DETECTED)
    elif _risk_bucket_from_value(avg_risk if avg_risk is not None else risk) == "low":
        reason_codes.append(ProductionEvidenceReasonCode.CONFIRMED_INTRUDER_LOW_RISK)
    if not _first_text(payload, "baseline_decision"):
        reason_codes.extend([ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING, ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA])
    face_payload = _as_mapping(payload.get("face_confirmation"))
    face_status = _first_text(payload, "face_confirmation_status", "face_pre_lock_status") or _as_str(face_payload.get("status"))
    rec = ProductionEvidenceRecord(
        window_id=str(safe_window),
        timestamp=_as_str(timestamp or feedback.get("timestamp") or payload.get("postLockConfirmationAnsweredAt") or payload.get("updated_at_text") or _now_timestamp()),
        user_id=safe_user,
        candidate_artifact_digest=candidate_digest,
        baseline_artifact_digest=_first_text(payload, "baseline_artifact_digest"),
        runtime_schema_version=runtime_schema,
        feature_schema_version=_first_text(payload, "feature_schema_version") or runtime_schema,
        candidate_decision="lock",
        baseline_decision=_first_text(payload, "baseline_decision"),
        candidate_risk_bucket=_risk_bucket_from_value(avg_risk if avg_risk is not None else risk),
        baseline_risk_bucket=_risk_bucket_from_value(payload.get("baseline_risk")),
        candidate_would_lock_if_production=True,
        baseline_would_lock_if_production=_as_bool(payload.get("baseline_would_lock_if_production")),
        is_trusted_window=bool(user_verified),
        trusted_anchor_type="post_lock_user_confirmed_legit" if user_verified else "",
        is_post_unlock_window=True,
        is_confirmed_intruder_window=not bool(user_verified),
        feature_quality_ok=not _as_bool(payload.get("technical_failure")),
        unknown_or_abstain=False,
        schema_ok=not _as_bool(payload.get("technical_failure")),
        source=POST_LOCK_FEEDBACK_EVIDENCE_SOURCE,
        reason_codes=tuple(reason_codes),
        false_positive_candidate=bool(user_verified),
        verified_owner_after_anomaly=bool(user_verified),
        eligible_for_shadow_evidence=True,
        eligible_for_direct_production_training=False,
        production_decision_changed=False,
        production_threshold_changed=False,
        production_model_pointer_changed=False,
        protected_sessions_unlocked=False,
        excluded_from_positive_training=True,
        production_training_allowed=False,
        face_confirmation_status=face_status[:80],
        policy_version=POST_LOCK_FEEDBACK_SHADOW_POLICY_VERSION,
        production_model_version=model_version,
        classic_decision_summary=_safe_decision_summary(
            {
                "post_lock_label": normalized_label,
                "classification": classification,
                "decision": payload.get("decision") or payload.get("final_decision"),
                "runtime_diagnostic_code": payload.get("runtime_diagnostic_code") or payload.get("postLockConfirmationReason"),
                "risk": risk,
            }
        ),
        sequence_decision_summary=_safe_decision_summary(payload, "sequence_decision", "sequence_decision_summary", "deep_sequence_decision"),
        hybrid_decision_summary=_safe_decision_summary(payload, "hybrid_decision", "hybrid_decision_summary", "runtime_hybrid_decision"),
    )
    target_ledger_path = ledger_path or shadow_evidence_ledger_path(safe_user)
    return append_evidence_record(safe_user, rec, ledger_path=target_ledger_path)


def _metadata_candidate_digest(metadata: Mapping[str, Any]) -> str:
    for key in ("candidate_artifact_digest", "artifact_digest", "model_digest", "bundle_digest"):
        value = metadata.get(key) if isinstance(metadata, Mapping) else None
        text = _as_str(value).strip()
        if text:
            return text[:180]
    return ""


def append_runtime_monitor_evidence_record(
    *,
    user_id: str,
    state: Mapping[str, Any],
    runtime: Mapping[str, Any] | None = None,
    prediction: Mapping[str, Any] | None = None,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    payload = _as_mapping(state)
    runtime_payload = _as_mapping(runtime)
    prediction_payload = _as_mapping(prediction)
    metadata = _as_mapping(runtime_payload.get("metadata"))
    paths_payload = _as_mapping(runtime_payload.get("paths"))
    model_path = _as_str(paths_payload.get("model"))
    candidate_digest = _metadata_candidate_digest(metadata) or _file_digest(model_path)
    runtime_schema = _as_str(metadata.get("runtime_schema_version") or metadata.get("feature_schema_version") or payload.get("runtime_schema_version"))
    schema_contract = _as_mapping(metadata.get("feature_schema_contract") or payload.get("feature_schema_contract"))
    feature_schema_digest = _as_str(metadata.get("feature_schema_digest") or payload.get("feature_schema_digest") or schema_contract.get("schema_digest"))
    if not feature_schema_digest:
        try:
            feature_schema_digest = _as_str(build_feature_schema_contract().get("schema_digest"))
        except Exception:
            feature_schema_digest = ""
    quality_ok = _as_int(payload.get("runtime_quality_ok_windows"), 0) > 0 and _as_int(payload.get("runtime_low_quality_windows"), 0) == 0
    decision = _normalize_decision(payload.get("model_decision") or payload.get("decision") or prediction_payload.get("final"))
    risk_bucket = _risk_bucket_from_value(payload.get("avg_risk") if payload.get("avg_risk") is not None else payload.get("risk"))
    source = _as_str(payload.get("evidence_source") or payload.get("source") or "runtime_monitor")
    if _as_str(payload.get("runtime_mode")).strip().lower() == "shadow_evidence" or _as_str(payload.get("session_kind")).strip().lower() == "shadow_evidence":
        source = "shadow_evidence_monitor"
    reason_codes = list(payload.get("runtime_lock_safety_reasons") or ())
    if source == "shadow_evidence_monitor" and _as_bool(payload.get("candidate_would_lock_if_production")):
        reason_codes.append("shadow_evidence_lock_suppressed")
    baseline_decision = _as_str(payload.get("baseline_decision") or prediction_payload.get("baseline_decision"))
    baseline_digest = _as_str(payload.get("baseline_artifact_digest") or metadata.get("baseline_artifact_digest"))
    if source == "shadow_evidence_monitor" and not baseline_decision:
        reason_codes.append(ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING)
        reason_codes.append(ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA)
    explicit_would_lock = payload.get("candidate_would_lock_if_production")
    candidate_would_lock = _as_bool(explicit_would_lock) if explicit_would_lock is not None else (decision == "lock" or _as_bool(payload.get("app_locked") or payload.get("screen_locked")))
    rec = ProductionEvidenceRecord(
        window_id=str(payload.get("runtime_telemetry_seq") or payload.get("session_id") or f"runtime-{int(time.time() * 1000)}"),
        timestamp=_as_str(payload.get("updated_at_text") or _now_timestamp()),
        user_id=user_id or _as_str(payload.get("user_id") or payload.get("expected_user")),
        candidate_artifact_digest=candidate_digest,
        baseline_artifact_digest=baseline_digest,
        runtime_schema_version=runtime_schema,
        feature_schema_version=runtime_schema,
        feature_schema_contract_version=_as_str(metadata.get("feature_schema_contract_version") or payload.get("feature_schema_contract_version") or FEATURE_SCHEMA_CONTRACT_VERSION),
        window_schema_version=_as_str(metadata.get("window_schema_version") or payload.get("window_schema_version") or WINDOW_SCHEMA_VERSION),
        feature_extension_profile=_as_str(metadata.get("feature_extension_profile") or payload.get("feature_extension_profile") or schema_contract.get("feature_extension_profile") or CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION),
        feature_schema_digest=feature_schema_digest,
        candidate_decision=decision,
        baseline_decision=baseline_decision,
        candidate_risk_bucket=risk_bucket,
        baseline_risk_bucket=_risk_bucket_from_value(payload.get("baseline_risk") or prediction_payload.get("baseline_risk")),
        candidate_would_lock_if_production=candidate_would_lock,
        baseline_would_lock_if_production=_as_bool(payload.get("baseline_would_lock_if_production")),
        is_trusted_window=decision == "trusted" or risk_bucket == "low",
        trusted_anchor_type="post_unlock" if _as_bool(payload.get("postUnlockTrustedWindow") or payload.get("post_unlock_trusted_window")) else "runtime_monitor",
        is_post_unlock_window=_as_bool(payload.get("postLockConfirmationAnswered") or payload.get("postUnlockTrustedWindow") or payload.get("post_unlock_trusted_window")),
        is_confirmed_intruder_window=_as_bool(payload.get("confirmedIntruderAfterLock") or payload.get("confirmed_intruder")),
        feature_quality_ok=quality_ok,
        unknown_or_abstain=decision == "unknown" or str(payload.get("status") or "").strip().lower() in {"unknown", "pending"},
        schema_ok=not bool(payload.get("technical_failure")),
        source=source,
        reason_codes=tuple(reason_codes),
        classic_decision_summary=_runtime_classic_decision_summary(
            payload,
            prediction_payload,
            decision=decision,
            risk_bucket=risk_bucket,
        ),
        sequence_decision_summary=_runtime_nested_decision_summary(
            prediction_payload,
            "deep_sequence",
            "sequence_decision",
            "sequence_decision_summary",
            "deep_sequence_decision",
        ) or _runtime_nested_decision_summary(
            payload,
            "deep_sequence",
            "sequence_decision",
            "sequence_decision_summary",
            "deep_sequence_decision",
        ),
        hybrid_decision_summary=_runtime_nested_decision_summary(
            prediction_payload,
            "hybrid_shadow",
            "hybrid_decision",
            "hybrid_decision_summary",
            "runtime_hybrid_decision",
        ) or _runtime_nested_decision_summary(
            payload,
            "hybrid_shadow",
            "hybrid_decision",
            "hybrid_decision_summary",
            "runtime_hybrid_decision",
        ),
    )
    return append_evidence_record(user_id or rec.user_id, rec, ledger_path=ledger_path)


def delete_evidence_records_for_user(user_id: str) -> bool:
    safe = slugify_username(user_id or "") or "unknown"
    import shutil

    production_directory = Path(paths.evidence_dir()) / "production_evidence" / f"user_{safe}"
    try:
        from shadow_core.background_contracts import shadow_evidence_dir

        shadow_directory = Path(shadow_evidence_dir(safe))
    except Exception:
        shadow_directory = None

    removed_any = False
    if production_directory.exists():
        shutil.rmtree(production_directory, ignore_errors=True)
        removed_any = True
    if shadow_directory is not None and shadow_directory.exists():
        shutil.rmtree(shadow_directory, ignore_errors=True)
        removed_any = True

    production_gone = not production_directory.exists()
    shadow_gone = True if shadow_directory is None else not shadow_directory.exists()
    return bool(removed_any and production_gone and shadow_gone)


__all__ = [
    "PRODUCTION_EVIDENCE_LEDGER_SCHEMA_VERSION",
    "PRODUCTION_EVIDENCE_LEDGER_FILENAME",
    "SHADOW_EVIDENCE_LEDGER_SCHEMA_VERSION",
    "SHADOW_EVIDENCE_LEDGER_POLICY_VERSION",
    "PRE_LOCK_FACE_CONFIRMATION_EVIDENCE_SOURCE",
    "POST_LOCK_FEEDBACK_EVIDENCE_SOURCE",
    "FACE_FEEDBACK_SHADOW_POLICY_VERSION",
    "POST_LOCK_FEEDBACK_SHADOW_POLICY_VERSION",
    "ProductionEvidenceRecord",
    "append_evidence_record",
    "append_runtime_monitor_evidence_record",
    "build_shadow_evidence_ledger_report",
    "validate_shadow_evidence_ledger",
    "append_pre_lock_face_confirmation_shadow_evidence_record",
    "append_post_lock_feedback_shadow_evidence_record",
    "append_shadow_evaluation_record",
    "aggregate_evidence_records",
    "build_production_evidence_report_for_user",
    "remediation_progress_from_evidence_records",
    "build_production_evidence_report_from_records",
    "load_shadow_evidence_summary_for_candidate",
    "evidence_ledger_dir",
    "evidence_ledger_path",
    "delete_evidence_records_for_user",
    "read_evidence_records",
    "read_all_evidence_records_for_user",
]
