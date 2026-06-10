"""Backend-owned production approval diagnostics for Protected Sessions."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, Mapping, Optional

from evaluation_core.production_evidence import (
    ProductionEvidenceGateResult,
    ProductionEvidencePromotionEffect,
    ProductionEvidenceReport,
    ProductionEvidenceStatus,
)


_CLOSED_BETA_ADVISORY_SAFETY_KEYS = {"safety_metrics_present", "warning_per_hour", "data_coverage"}


def _demo_classic_protected_enabled() -> bool:
    try:
        from app_settings import demo_classic_protected_enabled as _enabled

        return bool(_enabled())
    except Exception:
        return False


def _demo_classic_candidate_status(status: str) -> bool:
    return str(status or "").strip().lower() in {
        "approved_for_shadow",
        "shadow_validation",
        "approved_for_production",
        "production_ready",
        "demo_ready",
        "rejected",
        "offline_approval_rejected",
    }


def _demo_classic_rejected_candidate_status(status: str) -> bool:
    return str(status or "").strip().lower() in {"rejected", "offline_approval_rejected"}


def _demo_classic_ready_overlay(*, artifact_digest: str = "", rejected_override: bool = False) -> Dict[str, Any]:
    reason_code = "demo_classic_rejected_candidate_override" if rejected_override else "demo_classic_protected"
    runtime_source = "demo_classic_rejected_candidate_override" if rejected_override else "demo_classic_protected"
    reason_text = "Protected runtime is available for this build."
    ready_message = "Protected Sessions are available."
    ready_detail = "Protection can be started from this device."
    payload = {
        "demo_classic_protected": True,
        "production_approval_bypassed_for_demo": True,
        "demo_classic_protected_bypassed_production_gate": True,
        "runtime_publish_source": runtime_source,
        "runtime_requires_production_approval": False,
        "runtime_publish_demo_only": True,
        "productionReady": True,
        "production_ready": True,
        "protectedSessionsAvailable": True,
        "protected_sessions_available": True,
        "status": "demo_ready",
        "phase": "demo_classic_protected",
        "reason_code": reason_code,
        "reasonCode": reason_code,
        "reason_text": reason_text,
        "reasonText": reason_text,
        "next_action": "none",
        "nextAction": "none",
        "ready_notification_state": "ready",
        "readyNotificationState": "ready",
        "ready_notification_reason": reason_code,
        "readyNotificationReason": reason_code,
        "ready_notification_blockers": [],
        "readyNotificationBlockers": [],
        "protected_sessions_ready_notification_pending": False,
        "protectedSessionsReadyNotificationPending": False,
        "protected_sessions_ready_message": ready_message,
        "protectedSessionsReadyMessage": ready_message,
        "protected_sessions_ready_detail": ready_detail,
        "protectedSessionsReadyDetail": ready_detail,
        "protected_sessions_ready_artifact_digest": str(artifact_digest or ""),
        "protectedSessionsReadyArtifactDigest": str(artifact_digest or ""),
    }
    if rejected_override:
        payload.update({
            "demo_rejected_candidate_override": True,
            "candidate_status": "demo_ready",
            "candidateStatus": "demo_ready",
            "runtime_publish_source": "demo_classic_rejected_candidate_override",
        })
    return payload


def _closed_beta_required_from_env() -> bool:
    mode = str(os.environ.get("BIOAUTH_CLOSED_BETA_GATE_MODE") or "").strip().lower()
    if mode in {"required", "require", "blocking", "enforced"}:
        return True
    if mode in {"advisory", "optional", "off", "0", "false", "no"}:
        return False
    require = str(os.environ.get("BIOAUTH_REQUIRE_CLOSED_BETA_GATE") or "").strip().lower()
    return require in {"1", "true", "yes", "required", "require", "blocking", "enforced"}


def _closed_beta_policy_details(meta: Mapping[str, Any]) -> Dict[str, Any]:
    details = _as_dict(meta.get("policy_details")) if isinstance(meta, Mapping) else {}
    gate = _as_dict(details.get("closed_beta_gate"))
    required = bool(gate.get("required")) if "required" in gate else bool(details.get("closed_beta_gate_required", _closed_beta_required_from_env()))
    status = str(gate.get("status") or details.get("closed_beta_gate_status") or "").strip()
    blocking = bool(gate.get("blocking")) if "blocking" in gate else bool(details.get("closed_beta_gate_blocking", False))
    reasons = _safe_list(gate.get("advisory_reasons") or details.get("closed_beta_advisory_reasons"))
    coverage = _as_dict(details.get("closed_beta_coverage"))
    for item in _safe_list(coverage.get("missing")):
        if item not in reasons:
            reasons.append(item)
    if not status:
        if required and blocking:
            status = "required_failed"
        elif reasons:
            status = "optional_missing" if not required else "required_partial"
        else:
            status = "available"
    return {
        "mode": "required" if required else "advisory",
        "required": bool(required),
        "blocking": bool(blocking and required),
        "status": status,
        "advisory_reasons": reasons,
    }


def _closed_beta_is_required(metadata: Mapping[str, Any]) -> bool:
    return bool(_closed_beta_policy_details(metadata).get("required"))


def _closed_beta_observability_payload(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    policy = _closed_beta_policy_details(metadata)
    return {
        "closedBetaGateRequired": bool(policy.get("required")),
        "closed_beta_gate_required": bool(policy.get("required")),
        "closedBetaGateBlocking": bool(policy.get("blocking")),
        "closed_beta_gate_blocking": bool(policy.get("blocking")),
        "closedBetaGateStatus": str(policy.get("status") or "available"),
        "closed_beta_gate_status": str(policy.get("status") or "available"),
        "closedBetaAdvisoryReasons": list(policy.get("advisory_reasons") or []),
        "closed_beta_advisory_reasons": list(policy.get("advisory_reasons") or []),
    }


def _is_closed_beta_only_reason(reason: str) -> bool:
    lowered = str(reason or "").lower()
    return "closed-beta safety gate" in lowered or "closed beta safety gate" in lowered


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "pass", "passed", "ready", "available", "ok"}
    return False


def _ready_notification_artifact_digest(source: Mapping[str, Any], evidence_summary: Mapping[str, Any]) -> str:
    for key in ("protected_sessions_ready_artifact_digest", "ready_notification_artifact_digest", "productionEvidenceCandidateDigest", "production_evidence_candidate_digest"):
        value = source.get(key) if isinstance(source, Mapping) else None
        if value not in (None, ""):
            return str(value)
    for key in ("candidate_artifact_digest", "candidateArtifactDigest"):
        value = evidence_summary.get(key) if isinstance(evidence_summary, Mapping) else None
        if value not in (None, ""):
            return str(value)
    runtime_base = str(source.get("runtimeBundleBase") or source.get("runtime_bundle_base") or "").strip() if isinstance(source, Mapping) else ""
    return "runtime:" + runtime_base if runtime_base else ""


def build_protected_sessions_ready_notification_state(
    state: Mapping[str, Any] | None,
    *,
    notified_artifact_digest: str = "",
    notified_at: str = "",
) -> Dict[str, Any]:
    """Return artifact-aware, backend-owned Protected Sessions readiness notification state."""
    source = _as_dict(state)
    if _boolish(source.get("demo_classic_protected")):
        return _demo_classic_ready_overlay(
            artifact_digest=_ready_notification_artifact_digest(source, _as_dict(source.get("production_evidence_summary") or source.get("productionEvidenceSummary"))),
            rejected_override=_boolish(source.get("demo_rejected_candidate_override"))
            or str(source.get("reason_code") or source.get("reasonCode") or "").strip().lower() == "demo_classic_rejected_candidate_override",
        )
    evidence_summary = _as_dict(source.get("production_evidence_summary") or source.get("productionEvidenceSummary"))
    reason_codes = _safe_list(evidence_summary.get("reason_codes") or source.get("productionEvidenceReasonCodes") or source.get("production_evidence_reason_codes"))
    reason_code_set = {str(code).strip().lower() for code in reason_codes if str(code).strip()}
    evidence_status = str(evidence_summary.get("status") or source.get("productionEvidenceStatus") or source.get("production_evidence_status") or "").strip().lower()
    promotion_effect = str(evidence_summary.get("promotion_effect") or source.get("productionEvidencePromotionEffect") or source.get("production_evidence_promotion_effect") or "").strip().lower()
    runtime_reason = str(source.get("runtimeValidationReason") or source.get("runtime_validation_reason") or "").strip().lower()
    model_status = str(source.get("modelStatus") or source.get("candidate_status") or source.get("candidateStatus") or "").strip().lower()
    artifact_digest = _ready_notification_artifact_digest(source, evidence_summary)
    protected_available = _boolish(source.get("protected_sessions_available")) or _boolish(source.get("protectedSessionsAvailable"))
    production_ready = _boolish(source.get("productionReady")) or str(source.get("reason_code") or source.get("reasonCode") or "").strip().lower() == "production_ready"
    approval_passed = _boolish(source.get("productionApprovalPassed")) or str(source.get("status") or "").strip().lower() == "approved"
    evidence_passed = _boolish(source.get("productionEvidencePassed")) or evidence_status == "pass"
    runtime_ok = runtime_reason in {"", "ok", "valid", "runtime_ok"}
    blockers: list[str] = []
    if not protected_available:
        blockers.append("protected_sessions_unavailable")
    if not production_ready:
        blockers.append("production_ready_false")
    if not approval_passed:
        blockers.append("production_approval_not_passed")
    if not evidence_passed or evidence_status not in {"pass", "passed"}:
        blockers.append("production_evidence_not_passed")
    if promotion_effect in {"shadow_only", "partial", "none", "blocked"}:
        blockers.append("production_evidence_shadow_only")
    if not runtime_ok:
        blockers.append("runtime_validation_not_ok")
    if model_status in {"approved_for_shadow", "shadow_validation", "rejected", "untrained", "missing", "none", "pending_evaluation"}:
        blockers.append("candidate_not_production_ready")
    if not artifact_digest:
        blockers.append("artifact_digest_missing")
    blocking_reason_codes = {"baseline_decision_missing", "insufficient_model_agreement", "insufficient_model_agreement_data", "insufficient_post_unlock_evidence", "runtime_schema_mismatch", "candidate_digest_mismatch", "confirmed_intruder_low_risk", "production_evidence_partial", "production_evidence_failed"}
    for code in sorted(reason_code_set & blocking_reason_codes):
        blockers.append(code)
    eligible = not blockers
    already_notified = bool(eligible and artifact_digest and str(notified_artifact_digest or "") == artifact_digest)
    pending = bool(eligible and not already_notified)
    state_name = "pending" if pending else ("already_notified" if already_notified else "not_ready")
    reason = "all_backend_gates_passed" if pending else ("already_notified_for_artifact" if already_notified else (blockers[0] if blockers else "not_ready"))
    message = "Protected Sessions are ready." if eligible else ""
    detail = "Your BioAuth profile passed backend approval. You can start Protected Sessions." if eligible else ""
    return {
        "protected_sessions_ready_notification_pending": pending,
        "protectedSessionsReadyNotificationPending": pending,
        "protected_sessions_ready_notified_at": str(notified_at or "") if already_notified else "",
        "protectedSessionsReadyNotifiedAt": str(notified_at or "") if already_notified else "",
        "protected_sessions_ready_message": message,
        "protectedSessionsReadyMessage": message,
        "protected_sessions_ready_detail": detail,
        "protectedSessionsReadyDetail": detail,
        "protected_sessions_ready_artifact_digest": artifact_digest,
        "protectedSessionsReadyArtifactDigest": artifact_digest,
        "ready_notification_state": state_name,
        "readyNotificationState": state_name,
        "ready_notification_artifact_digest": artifact_digest,
        "readyNotificationArtifactDigest": artifact_digest,
        "ready_notification_reason": reason,
        "readyNotificationReason": reason,
        "ready_notification_blockers": blockers,
        "readyNotificationBlockers": list(blockers),
    }


def with_protected_sessions_ready_notification_state(state: Mapping[str, Any] | None, *, notified_artifact_digest: str = "", notified_at: str = "") -> Dict[str, Any]:
    payload = dict(state or {}) if isinstance(state, Mapping) else {}
    payload.update(build_protected_sessions_ready_notification_state(payload, notified_artifact_digest=notified_artifact_digest, notified_at=notified_at))
    return payload



def _merge_reason_codes(existing: Iterable[Any], extra: Iterable[Any]) -> tuple[str, ...]:
    merged: list[str] = []
    for item in list(existing or []) + list(extra or []):
        text = str(item or "").strip().lower()
        if text and text not in merged:
            merged.append(text)
    return tuple(merged)


def _report_with_reason_codes(report: ProductionEvidenceReport, reason_codes: Iterable[Any]) -> ProductionEvidenceReport:
    if not isinstance(report, ProductionEvidenceReport):
        report = ProductionEvidenceReport.missing_evidence()
    merged = _merge_reason_codes(report.gate.reason_codes, reason_codes)
    if not merged:
        return report
    status = report.gate.status
    effect = report.gate.promotion_effect
    # Additional ledger/pipeline reasons are evidence-only and must never turn a
    # partial/shadow-only state into production eligibility. If a reason was
    # appended to a passing report, downgrade to partial/shadow-only.
    if set(merged) != set(report.gate.reason_codes) and status is ProductionEvidenceStatus.PASS:
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
        gate=ProductionEvidenceGateResult(status=status, promotion_effect=effect, reason_codes=merged),
    )


def _nested_production_evidence(source: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = source.get("production_evidence") if isinstance(source, Mapping) else None
    return payload if isinstance(payload, Mapping) else {}


def _evidence_field_from_sources(field: str, *sources: Mapping[str, Any]) -> str:
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        value = source.get(field)
        if value not in (None, ""):
            return str(value)
        evidence = _nested_production_evidence(source)
        value = evidence.get(field)
        if value not in (None, ""):
            return str(value)
    return ""


def _candidate_digest_from_sources(candidate_paths: Mapping[str, str], *sources: Mapping[str, Any]) -> str:
    digest = _evidence_field_from_sources("candidate_artifact_digest", *sources)
    if digest:
        return digest
    for key in ("candidate_artifact_digest", "artifact_digest", "model_digest", "bundle_digest"):
        for source in sources:
            if isinstance(source, Mapping) and source.get(key) not in (None, ""):
                return str(source.get(key))
    model_path = str(candidate_paths.get("model") or candidate_paths.get("classifier") or "") if isinstance(candidate_paths, Mapping) else ""
    if model_path and os.path.exists(model_path) and os.path.isfile(model_path):
        import hashlib
        digest = hashlib.sha256()
        with open(model_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    return ""


def _runtime_schema_from_sources(*sources: Mapping[str, Any]) -> str:
    for key in ("runtime_schema_version", "feature_schema_version", "schema_version"):
        value = _evidence_field_from_sources(key, *sources)
        if value:
            return value
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            nested = source.get("feature_schema")
            if isinstance(nested, Mapping) and nested.get("version") not in (None, ""):
                return str(nested.get("version"))
    return ""


def _evidence_report_digest_from_sources(report: Mapping[str, Any]) -> str:
    return _evidence_field_from_sources("evaluation_report_digest", report)


def _ledger_evidence_for_user(
    user_id: str,
    *,
    candidate_artifact_digest: str = "",
    baseline_artifact_digest: str = "",
    evaluation_report_digest: str = "",
    runtime_schema_version: str = "",
) -> Dict[str, Any]:
    if not str(user_id or "").strip():
        return {}
    try:
        from metadata_core.production_evidence_pipeline import load_shadow_evidence_summary_for_candidate

        summary = load_shadow_evidence_summary_for_candidate(
            user_id,
            candidate_artifact_digest=candidate_artifact_digest,
            baseline_artifact_digest=baseline_artifact_digest,
            evaluation_report_digest=evaluation_report_digest,
            runtime_schema_version=runtime_schema_version,
        )
    except (OSError, TypeError, ValueError):
        return {}
    return summary if isinstance(summary, dict) and int(summary.get("records_total") or 0) > 0 else {}


_METRIC_KEYS = (
    "auc",
    "f1",
    "precision",
    "recall",
    "far",
    "frr",
    "frr_user",
    "far_intruder",
    "warning_per_hour",
    "lock_per_hour",
    "false_lock_count",
    "low_quality_decision_rate",
    "session_count",
    "legitimate_session_count",
    "intruder_session_count",
)

_CONTEXT_NAMES = {"keyboard_heavy", "mouse_heavy", "mixed", "short_session"}


_MISSING_REPORT_REASON = "Evaluation report is not available yet. BioAuth will only unlock Protected Sessions after a production-approved runtime bundle is verified."
_SHADOW_REASON = "The candidate model is safe for shadow validation, but it has not passed production approval yet. Protected Sessions remain locked."
_PRODUCTION_READY_REASON = "The model passed production approval and the active runtime bundle is valid. Protected Sessions are available."
_PRODUCTION_INVALID_REASON = "The model is production-approved, but the active production runtime bundle is not valid yet. Protected Sessions remain locked until runtime validation passes."
_REJECTED_REASON = "The candidate model did not pass the offline policy gates yet. Protected Sessions remain locked."
_NOT_TRAINED_REASON = "No trained candidate model is available yet. Collect enough trusted enrollment sessions, then train and evaluate the model."


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _production_evidence_from_sources(*sources: Mapping[str, Any]) -> ProductionEvidenceReport:
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        payload = source.get("production_evidence")
        if not isinstance(payload, Mapping):
            continue
        try:
            return ProductionEvidenceReport.from_dict(payload, allow_unknown_reason_codes=True)
        except (TypeError, ValueError):
            return ProductionEvidenceReport.missing_evidence()
    return ProductionEvidenceReport.missing_evidence()


def _production_evidence_allows_production(*sources: Mapping[str, Any]) -> bool:
    return bool(_production_evidence_from_sources(*sources).gate.allows_production_eligibility)


def _top_level_text(source: Mapping[str, Any], *keys: str) -> str:
    if not isinstance(source, Mapping):
        return ""
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _independent_candidate_digest(candidate_paths: Mapping[str, str], *sources: Mapping[str, Any]) -> tuple[str, str]:
    """Return candidate identity outside nested production_evidence when present."""

    for source_name, source in zip(("candidate_metadata", "evaluation_report", "runtime_metadata"), sources):
        digest = _top_level_text(source, "candidate_artifact_digest", "artifact_digest", "model_digest", "bundle_digest")
        if digest:
            return digest, source_name
    model_path = str(candidate_paths.get("model") or candidate_paths.get("classifier") or "") if isinstance(candidate_paths, Mapping) else ""
    if model_path and os.path.exists(model_path) and os.path.isfile(model_path):
        import hashlib

        digest = hashlib.sha256()
        with open(model_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest(), "candidate_artifact_hash"
    return "", ""


def _explicit_runtime_schema(*sources: Mapping[str, Any]) -> tuple[str, str]:
    for source_name, source in zip(("candidate_metadata", "evaluation_report", "runtime_metadata"), sources):
        if not isinstance(source, Mapping):
            continue
        for key in ("runtime_schema_version", "runtimeSchemaVersion"):
            value = source.get(key)
            if value not in (None, ""):
                return str(value).strip(), source_name
    return "", ""


def _rollback_ready_from_sources(*sources: Mapping[str, Any], explicit: Any = None) -> tuple[bool, str]:
    if explicit is not None:
        return _boolish(explicit), "explicit"
    for source_name, source in zip(("candidate_metadata", "evaluation_report", "runtime_metadata"), sources):
        if not isinstance(source, Mapping):
            continue
        for key in ("rollback_available", "rollback_ready", "rollbackReady", "rollbackAvailable"):
            if key in source:
                return _boolish(source.get(key)), source_name
        rollout = _as_dict(source.get("rollout_details"))
        for key in ("rollback_available", "rollback_ready", "rollback_to_classic_on_failure"):
            if key in rollout:
                return _boolish(rollout.get(key)), source_name + ".rollout_details"
        deep_runtime = _as_dict(source.get("deep_runtime"))
        for key in ("runtime_rollback_to_classic_on_failure", "rollback_available", "rollback_ready"):
            if key in deep_runtime:
                return _boolish(deep_runtime.get(key)), source_name + ".deep_runtime"
    return False, "missing"


def build_production_eligibility_state(
    *,
    candidate_paths: Mapping[str, str] | None = None,
    candidate_metadata: Mapping[str, Any] | None = None,
    evaluation_report: Mapping[str, Any] | None = None,
    runtime_validation: Mapping[str, Any] | None = None,
    runtime_paths: Mapping[str, str] | None = None,
    rollback_available: Any = None,
) -> Dict[str, Any]:
    """Return a deterministic, backend-owned production eligibility decision.

    This evidence-layer helper never activates production, writes the runtime
    pointer, unlocks Protected Sessions, or changes policy thresholds. Missing
    or ambiguous evidence fails closed with privacy-safe blockers.
    """

    candidate_paths = _as_dict(candidate_paths)
    metadata = _as_dict(candidate_metadata)
    report = _as_dict(evaluation_report)
    runtime_payload = _as_dict(runtime_validation)
    runtime_metadata = _as_dict(runtime_payload.get("metadata"))
    runtime_paths_payload = _as_dict(runtime_paths)
    evidence = _production_evidence_from_sources(metadata, report, runtime_metadata)
    model_status = _model_status_from_sources(metadata, runtime_metadata, bool(metadata))
    blockers: list[str] = []

    if model_status != "approved_for_production":
        blockers.append("model_not_approved_for_production")

    evidence_digest = str(evidence.candidate_artifact_digest or "").strip()
    independent_digest, independent_source = _independent_candidate_digest(candidate_paths, metadata, report, runtime_metadata)
    effective_candidate_digest = independent_digest or evidence_digest
    if not evidence_digest:
        blockers.append("production_evidence_candidate_digest_missing")
    if not effective_candidate_digest:
        blockers.append("candidate_artifact_digest_missing")
    if independent_digest and evidence_digest and independent_digest != evidence_digest:
        # Commercial-Core-22F: evidence for an older candidate must not keep the
        # current candidate blocked forever as a hard digest mismatch. Treat it as
        # stale/missing evidence so fresh current-candidate ledger records can
        # unblock the gate deterministically.
        blockers.append("production_evidence_stale_for_previous_candidate")

    if not evidence.evaluation_report_digest:
        blockers.append("evaluation_report_digest_missing")
    report_digest = _top_level_text(report, "evaluation_report_digest", "report_digest")
    if report_digest and evidence.evaluation_report_digest and report_digest != evidence.evaluation_report_digest:
        blockers.append("evaluation_report_digest_mismatch")

    evidence_runtime_schema = str(evidence.runtime_schema_version or "").strip()
    explicit_runtime_schema, explicit_schema_source = _explicit_runtime_schema(metadata, report, runtime_metadata)
    if not evidence_runtime_schema:
        blockers.append("runtime_schema_version_missing")
    if explicit_runtime_schema and evidence_runtime_schema and explicit_runtime_schema != evidence_runtime_schema:
        blockers.append("runtime_schema_mismatch")

    if not evidence.gate.allows_production_eligibility:
        status = str(evidence.gate.status.value)
        blockers.append(f"production_evidence_{status}")
        for code in evidence.gate.reason_codes:
            code_text = str(code or "").strip()
            if code_text:
                blockers.append(f"production_evidence_{code_text}")

    selection_gate = getattr(evidence, "selection_promotion_gate", None)
    if selection_gate is not None and getattr(selection_gate, "evaluated", False) and not getattr(selection_gate, "allows_selection_promotion", False):
        blockers.append("selection_promotion_gate_blocked")
        for code in getattr(selection_gate, "reason_codes", ()):
            code_text = str(code or "").strip()
            if code_text:
                blockers.append(code_text)

    runtime_ok = bool(runtime_payload.get("ok"))
    runtime_reason = str(runtime_payload.get("reason") or ("ok" if runtime_ok else "runtime_validation_missing")).strip()
    if not runtime_ok:
        blockers.append("runtime_validation_missing" if not runtime_payload else f"runtime_validation_{runtime_reason or 'failed'}")

    rollback_ready, rollback_source = _rollback_ready_from_sources(metadata, report, runtime_metadata, explicit=rollback_available)
    if not rollback_ready:
        blockers.append("rollback_readiness_missing")

    deduped_blockers: list[str] = []
    for item in blockers:
        text = str(item or "").strip()
        if text and text not in deduped_blockers:
            deduped_blockers.append(text)
    eligible = not deduped_blockers
    reason = "production_eligible_backend_gates_passed" if eligible else deduped_blockers[0]
    return {
        "eligible": bool(eligible),
        "production_eligible": bool(eligible),
        "productionEligibilityPassed": bool(eligible),
        "production_eligibility_passed": bool(eligible),
        "status": "pass" if eligible else "blocked",
        "reason_code": reason,
        "reasonCode": reason,
        "blockers": list(deduped_blockers),
        "productionEligibilityBlockers": list(deduped_blockers),
        "candidate_artifact_digest": effective_candidate_digest,
        "candidateArtifactDigest": effective_candidate_digest,
        "evidence_candidate_artifact_digest": evidence_digest,
        "evidenceCandidateArtifactDigest": evidence_digest,
        "candidate_digest_source": independent_source or "production_evidence",
        "candidateDigestSource": independent_source or "production_evidence",
        "candidate_digest_matched": bool(effective_candidate_digest and evidence_digest and effective_candidate_digest == evidence_digest),
        "candidateDigestMatched": bool(effective_candidate_digest and evidence_digest and effective_candidate_digest == evidence_digest),
        "evaluation_report_digest": str(evidence.evaluation_report_digest or ""),
        "evaluationReportDigest": str(evidence.evaluation_report_digest or ""),
        "runtime_schema_version": evidence_runtime_schema,
        "runtimeSchemaVersion": evidence_runtime_schema,
        "runtime_schema_source": explicit_schema_source or "production_evidence",
        "runtimeSchemaSource": explicit_schema_source or "production_evidence",
        "runtime_validation_required": True,
        "runtimeValidationRequired": True,
        "runtime_validation_ok": bool(runtime_ok),
        "runtimeValidationOk": bool(runtime_ok),
        "runtime_validation_reason": runtime_reason,
        "runtimeValidationReason": runtime_reason,
        "rollback_ready": bool(rollback_ready),
        "rollbackReady": bool(rollback_ready),
        "rollback_source": rollback_source,
        "rollbackSource": rollback_source,
        "promotion_effect": str(evidence.gate.promotion_effect.value),
        "promotionEffect": str(evidence.gate.promotion_effect.value),
        "evidence_status": str(evidence.gate.status.value),
        "evidenceStatus": str(evidence.gate.status.value),
        "evidence_reason_codes": list(evidence.gate.reason_codes),
        "evidenceReasonCodes": list(evidence.gate.reason_codes),
        "selection_promotion_gate": getattr(evidence, "selection_promotion_gate", None).to_dict() if getattr(evidence, "selection_promotion_gate", None) is not None else {},
        "selectionPromotionGate": getattr(evidence, "selection_promotion_gate", None).to_dict() if getattr(evidence, "selection_promotion_gate", None) is not None else {},
        "selection_promotion_passed": bool(getattr(getattr(evidence, "selection_promotion_gate", None), "allows_selection_promotion", False)),
        "selectionPromotionPassed": bool(getattr(getattr(evidence, "selection_promotion_gate", None), "allows_selection_promotion", False)),
        "runtime_bundle_base": os.path.basename(str(runtime_paths_payload.get("base") or "")),
        "runtimeBundleBase": os.path.basename(str(runtime_paths_payload.get("base") or "")),
        "protected_sessions_available": False,
        "protectedSessionsAvailable": False,
        "active_runtime_pointer_written": False,
        "activeRuntimePointerWritten": False,
    }


def _production_evidence_summary_from_report(evidence: ProductionEvidenceReport) -> Dict[str, Any]:
    """Return a compact, privacy-safe evidence summary for backend state.

    The summary intentionally contains only aggregate counters, rates, reason
    codes, and artifact/schema identifiers. It never includes raw keyboard,
    mouse, biometric feature vectors, or per-event behavioral samples.
    """

    report = evidence if isinstance(evidence, ProductionEvidenceReport) else ProductionEvidenceReport.missing_evidence()
    model_agreement = report.model_agreement.to_dict()
    post_unlock = report.post_unlock_evidence.to_dict()
    intruder = report.confirmed_intruder_evidence.to_dict()
    runtime = report.runtime_safety.to_dict()
    selection_gate = getattr(report, "selection_promotion_gate", None)
    selection_summary = selection_gate.to_dict() if selection_gate is not None else {}
    summary = {
        "schema_version": int(report.schema_version),
        "status": report.gate.status.value,
        "promotion_effect": report.gate.promotion_effect.value,
        "reason_codes": list(report.gate.reason_codes),
        "allows_production_eligibility": bool(report.gate.allows_production_eligibility),
        "candidate_artifact_digest": str(report.candidate_artifact_digest or ""),
        "baseline_artifact_digest": str(report.baseline_artifact_digest or ""),
        "evaluation_report_digest": str(report.evaluation_report_digest or ""),
        "runtime_schema_version": str(report.runtime_schema_version or ""),
        "model_agreement": {
            "overall_agreement_rate": _safe_float_or_none(model_agreement.get("overall_agreement_rate")),
            "trusted_window_agreement_rate": _safe_float_or_none(model_agreement.get("trusted_window_agreement_rate")),
            "critical_disagreement_count": _safe_int_or_none(model_agreement.get("critical_disagreement_count")),
            "high_risk_disagreement_count": _safe_int_or_none(model_agreement.get("high_risk_disagreement_count")),
        },
        "post_unlock_evidence": {
            "trusted_window_count": _safe_int_or_none(post_unlock.get("trusted_window_count")),
            "warning_rate": _safe_float_or_none(post_unlock.get("warning_rate")),
            "simulated_false_locks": _safe_int_or_none(post_unlock.get("simulated_false_locks")),
            "feature_quality_rate": _safe_float_or_none(post_unlock.get("feature_quality_rate")),
        },
        "confirmed_intruder_evidence": {
            "available": bool(intruder.get("available")),
            "confirmed_intruder_count": _safe_int_or_none(intruder.get("confirmed_intruder_count")),
            "confirmed_intruder_low_risk_count": _safe_int_or_none(intruder.get("confirmed_intruder_low_risk_count")),
        },
        "runtime_safety": {
            "simulated_false_lock_count": _safe_int_or_none(runtime.get("simulated_false_lock_count")),
            "unknown_rate": _safe_float_or_none(runtime.get("unknown_rate")),
            "low_quality_decision_rate": _safe_float_or_none(runtime.get("low_quality_decision_rate")),
        },
        "selection_promotion_gate": selection_summary,
        "selectionPromotionGate": selection_summary,
        "selection_promotion_status": str(selection_summary.get("status") or "not_evaluated"),
        "selectionPromotionStatus": str(selection_summary.get("status") or "not_evaluated"),
        "selection_promotion_effect": str(selection_summary.get("promotion_effect") or "manual_review_required"),
        "selectionPromotionEffect": str(selection_summary.get("promotion_effect") or "manual_review_required"),
        "selection_promotion_weighted_score": _safe_float_or_none(selection_summary.get("weighted_score")),
        "selectionPromotionWeightedScore": _safe_float_or_none(selection_summary.get("weighted_score")),
        "selection_promotion_reason_codes": list(selection_summary.get("reason_codes") or []),
        "selectionPromotionReasonCodes": list(selection_summary.get("reason_codes") or []),
    }
    return summary


def _production_evidence_summary_from_sources(*sources: Mapping[str, Any]) -> Dict[str, Any]:
    return _production_evidence_summary_from_report(_production_evidence_from_sources(*sources))


def _safe_float_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_int_or_none(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _bounded_percent(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError, OverflowError):
        return None


def _threshold_value(metadata: Mapping[str, Any], report: Mapping[str, Any], metric: str) -> float | None:
    """Return only thresholds already persisted with candidate/report metadata."""
    metric = str(metric or "").strip().lower()
    if not metric:
        return None
    policy_details = _as_dict(metadata.get("policy_details"))
    report_policy = _as_dict(report.get("policy_details"))
    sources = (
        _as_dict(metadata.get("policy_thresholds")),
        _as_dict(metadata.get("thresholds")),
        _as_dict(policy_details.get("policy_thresholds")),
        _as_dict(policy_details.get("thresholds")),
        _as_dict(report.get("policy_thresholds")),
        _as_dict(report.get("thresholds")),
        _as_dict(report_policy.get("policy_thresholds")),
        _as_dict(report_policy.get("thresholds")),
    )
    for source in sources:
        for key in (f"{metric}_threshold", f"max_{metric}", f"production_{metric}_threshold", f"shadow_{metric}_threshold", metric):
            value = _safe_float_or_none(source.get(key))
            if value is not None:
                return value
    return None


def _shadow_windows_collected(shadow_status: Mapping[str, Any]) -> int | None:
    for key in ("windows_collected", "shadow_windows_collected", "quality_ok_windows", "total_eval_count", "evaluated_windows", "window_count"):
        value = _safe_int_or_none(shadow_status.get(key))
        if value is not None:
            return value
    return None


def _shadow_windows_required(shadow_status: Mapping[str, Any]) -> int | None:
    for key in ("windows_required", "shadow_windows_required", "required_windows", "required_eval_count", "min_windows"):
        value = _safe_int_or_none(shadow_status.get(key))
        if value is not None:
            return value
    return None


def _shadow_progress_percent(collected: int | None, required: int | None, shadow_status: Mapping[str, Any]) -> int | None:
    explicit = _bounded_percent(shadow_status.get("progress_percent") or shadow_status.get("progressPercent"))
    if explicit is not None:
        return explicit
    if collected is None or required is None or required <= 0:
        return None
    return max(0, min(100, int(round((float(collected) / float(required)) * 100.0))))


def _ledger_shadow_evidence_summary(source: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Return the backend-owned, privacy-safe shadow-evidence summary, if present."""
    data = _as_dict(source)
    summary = _as_dict(data.get("production_evidence_summary") or data.get("productionEvidenceSummary"))
    if not summary:
        return {}
    source_name = str(summary.get("source") or "").strip().lower()
    records_total = _safe_int_or_none(summary.get("records_total") if summary.get("records_total") is not None else summary.get("recordsTotal"))
    records_accepted = _safe_int_or_none(summary.get("records_accepted") if summary.get("records_accepted") is not None else summary.get("recordsAccepted"))
    windows = _ledger_windows_collected_from_evidence_summary(summary)
    if source_name == "shadow_evidence_monitor" or (records_total is not None and records_total > 0) or (records_accepted is not None and records_accepted > 0) or (windows is not None and windows > 0):
        return summary
    return {}


def _ledger_windows_collected_from_evidence_summary(summary: Mapping[str, Any] | None) -> int | None:
    data = _as_dict(summary)
    for key in ("windows_collected", "windowsCollected", "records_accepted", "recordsAccepted"):
        value = _safe_int_or_none(data.get(key))
        if value is not None:
            return value
    return None


def _ledger_reason_code_from_evidence_summary(summary: Mapping[str, Any], fallback: str) -> str:
    codes = _safe_list(summary.get("reason_codes") or summary.get("reasonCodes"))
    for preferred in (
        "production_evidence_partial",
        "insufficient_model_agreement_data",
        "baseline_decision_missing",
        "insufficient_model_agreement",
    ):
        if preferred in codes:
            return "production_evidence_partial" if preferred != "production_evidence_partial" else preferred
    status = str(summary.get("status") or "").strip().lower()
    if status == "partial":
        return "production_evidence_partial"
    if status == "fail":
        return "production_evidence_failed"
    return fallback


def _merge_ledger_shadow_evidence_top_level_fields(
    payload: Dict[str, Any],
    contract: Dict[str, Any],
    *,
    training_active: bool = False,
    evaluation_active: bool = False,
) -> Dict[str, Any]:
    """Preserve ledger-backed counters when volatile runtime overlay is stale.

    This helper reads only aggregate ProductionEvidenceSummary fields. It never
    reads or exposes raw keyboard, mouse, biometric samples, or feature vectors.
    Ledger evidence remains necessary-but-not-sufficient and never enables
    Protected Sessions by itself.
    """

    if training_active or evaluation_active:
        return contract
    candidate_status = str(
        payload.get("candidate_status")
        or payload.get("candidateStatus")
        or payload.get("modelStatus")
        or contract.get("candidate_status")
        or contract.get("candidateStatus")
        or ""
    ).strip().lower()
    if candidate_status != "approved_for_shadow":
        return contract
    summary = _ledger_shadow_evidence_summary(payload)
    if not summary:
        return contract
    ledger_windows = _ledger_windows_collected_from_evidence_summary(summary)
    if ledger_windows is None:
        return contract
    contract_windows = _safe_int_or_none(contract.get("windows_collected") if contract.get("windows_collected") is not None else contract.get("windowsCollected"))
    if contract_windows is None or ledger_windows > contract_windows:
        contract["windows_collected"] = ledger_windows
        contract["windowsCollected"] = ledger_windows
        contract["progress_percent"] = None
        contract["progressPercent"] = None
    reason_code = str(contract.get("reason_code") or contract.get("reasonCode") or "").strip()
    if ledger_windows > 0 and reason_code in {"", "shadow_validation_not_started", "approved_for_shadow_only"}:
        aligned = _ledger_reason_code_from_evidence_summary(summary, "production_evidence_partial")
        contract["reason_code"] = aligned
        contract["reasonCode"] = aligned
        contract["status"] = "pending"
        contract["phase"] = "shadow_validation"
        contract["reason_text"] = _contract_reason_text(
            reason_code=aligned,
            approval_reason="",
            runtime_reason=str(payload.get("runtimeValidationReason") or "production_evidence_required"),
            report_available=bool(payload.get("evaluationReportAvailable")),
            windows_collected=ledger_windows,
            windows_required=_safe_int_or_none(contract.get("windows_required") if contract.get("windows_required") is not None else contract.get("windowsRequired")),
        )
        contract["reasonText"] = contract["reason_text"]
        contract["next_action"] = _contract_next_action(reason_code=aligned, protected_available=False)
        contract["nextAction"] = contract["next_action"]
    contract["protected_sessions_available"] = False
    contract["protectedSessionsAvailable"] = False
    return contract


def _candidate_status_for_contract(model_status: str, production_ready: bool) -> str:
    status = str(model_status or "").strip().lower()
    if production_ready or status == "approved_for_production":
        return "production_ready"
    if status == "approved_for_shadow":
        return "approved_for_shadow"
    if status == "rejected":
        return "rejected"
    return "none"


def _metric_block_reason(policy_gate_results: Mapping[str, Any], failed_gates: list[str]) -> str:
    failed_text = {str(item or "").lower() for item in failed_gates}
    if policy_gate_results.get("far") is False or "policy_far" in failed_text or "far_too_high" in failed_text:
        return "far_too_high"
    if policy_gate_results.get("frr") is False or "policy_frr" in failed_text or "frr_too_high" in failed_text:
        return "frr_too_high"
    return ""


def _contract_reason_text(*, reason_code: str, approval_reason: str, runtime_reason: str, report_available: bool, windows_collected: int | None, windows_required: int | None) -> str:
    approval_reason = str(approval_reason or "").strip()
    if approval_reason:
        return approval_reason
    if reason_code == "no_candidate_model":
        return _NOT_TRAINED_REASON
    if reason_code == "training_in_progress":
        return "BioAuth is still building the behavioral model. Production approval is not evaluated until training finishes."
    if reason_code == "evaluation_in_progress":
        return "BioAuth is evaluating the candidate model before any production approval decision."
    if reason_code == "offline_approval_rejected":
        return _REJECTED_REASON
    if reason_code == "approved_for_shadow_only":
        return _SHADOW_REASON
    if reason_code == "shadow_validation_not_started":
        return "The candidate is approved for shadow validation, but no shadow evidence has been collected yet."
    if reason_code == "shadow_validation_in_progress":
        return "Shadow validation is collecting evidence. Protected Sessions remain locked until production approval passes."
    if reason_code == "insufficient_shadow_windows":
        if windows_collected is not None and windows_required is not None:
            return f"Shadow validation needs more evidence windows ({windows_collected}/{windows_required}). Protected Sessions remain locked."
        return "Shadow validation needs more evidence before production approval can pass."
    if reason_code == "runtime_bundle_invalid":
        return f"Production approval passed, but runtime bundle validation is blocked by {runtime_reason or 'runtime validation'}."
    if reason_code == "auto_promotion_disabled":
        return "Production approval passed, but automatic promotion is disabled. Manual production approval or runtime publication is required."
    if reason_code == "manual_approval_required":
        return "Production approval requires manual review before Protected Sessions can be enabled."
    if reason_code == "production_ready":
        return _PRODUCTION_READY_REASON
    if reason_code in {"production_evidence_missing", "production_evidence_partial"}:
        return "Production Evidence Gate v2 needs more privacy-safe shadow/runtime evidence. Protected Sessions remain locked."
    if reason_code == "production_evidence_failed":
        return "Production Evidence Gate v2 blocked production because safety evidence failed. Protected Sessions remain locked."
    if reason_code == "production_approval_blocked":
        return "Production approval is blocked by backend policy gates. Protected Sessions remain locked."
    if reason_code == "far_too_high":
        return "Production approval is blocked because the false accept rate is above the allowed gate."
    if reason_code == "frr_too_high":
        return "Production approval is blocked because the false reject rate is above the allowed gate."
    if reason_code == "candidate_unstable":
        return "Production approval is blocked because the candidate is not stable enough for Protected Sessions."
    if not report_available:
        return _MISSING_REPORT_REASON
    return "Production approval is pending. Protected Sessions remain locked until all backend gates pass."


def _contract_next_action(*, reason_code: str, protected_available: bool) -> str:
    if protected_available or reason_code == "production_ready":
        return "none"
    if reason_code in {"no_candidate_model", "offline_approval_rejected", "frr_too_high", "far_too_high", "candidate_unstable"}:
        return "retrain_after_more_data"
    if reason_code in {"shadow_validation_not_started", "shadow_validation_in_progress", "insufficient_shadow_windows", "approved_for_shadow_only"}:
        return "continue_using_device_normally"
    if reason_code in {"production_evidence_missing", "production_evidence_partial", "production_evidence_failed"}:
        return "collect_more_evidence"
    if reason_code in {"production_approval_blocked", "runtime_bundle_invalid", "auto_promotion_disabled", "manual_approval_required"}:
        return "manual_review_required"
    if reason_code in {"training_in_progress", "evaluation_in_progress", "production_approval_pending"}:
        return "continue_using_device_normally"
    return "none"


_OBSERVABILITY_KEYS = (
    "status",
    "phase",
    "candidate_status",
    "reason_code",
    "protected_sessions_available",
    "windows_collected",
    "windows_required",
    "progress_percent",
    "far",
    "frr",
    "next_action",
)


def production_approval_observability_payload(state: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Return compact, non-biometric diagnostics for production approval refresh logs."""
    source = _as_dict(state)
    payload: Dict[str, Any] = {}
    aliases = {
        "candidate_status": "candidateStatus",
        "reason_code": "reasonCode",
        "next_action": "nextAction",
        "windows_collected": "windowsCollected",
        "windows_required": "windowsRequired",
        "progress_percent": "progressPercent",
    }
    for key in _OBSERVABILITY_KEYS:
        value = source.get(key)
        if value is None and key in aliases:
            value = source.get(aliases[key])
        if key == "protected_sessions_available":
            value = bool(value or source.get("protectedSessionsAvailable"))
        elif key in {"windows_collected", "windows_required", "progress_percent"}:
            value = _safe_int_or_none(value)
        elif key in {"far", "frr"}:
            value = _safe_float_or_none(value)
        elif key in {"status", "phase", "candidate_status", "reason_code", "next_action"}:
            value = str(value or "").strip()
        payload[key] = value
    for key, alias in (("ready_notification_state", "readyNotificationState"), ("ready_notification_reason", "readyNotificationReason")):
        value = str(source.get(key) or source.get(alias) or "").strip()
        if value:
            payload[key] = value

    evidence_source = (
        source.get("production_evidence_summary")
        or source.get("productionEvidenceSummary")
        or ({"production_evidence": source.get("production_evidence")} if isinstance(source.get("production_evidence"), Mapping) else None)
    )
    if isinstance(evidence_source, Mapping):
        if "production_evidence" in evidence_source:
            payload["production_evidence_summary"] = _production_evidence_summary_from_sources(evidence_source)
        else:
            payload["production_evidence_summary"] = _production_evidence_summary_from_report(
                ProductionEvidenceReport.from_dict(evidence_source, allow_unknown_reason_codes=True)
                if "gate" in evidence_source
                else _production_evidence_from_sources({"production_evidence": {"gate": {
                    "status": evidence_source.get("status"),
                    "promotion_effect": evidence_source.get("promotion_effect"),
                    "reason_codes": evidence_source.get("reason_codes"),
                },
                    "candidate_artifact_digest": evidence_source.get("candidate_artifact_digest"),
                    "baseline_artifact_digest": evidence_source.get("baseline_artifact_digest"),
                    "evaluation_report_digest": evidence_source.get("evaluation_report_digest"),
                    "runtime_schema_version": evidence_source.get("runtime_schema_version"),
                    "model_agreement": evidence_source.get("model_agreement"),
                    "post_unlock_evidence": evidence_source.get("post_unlock_evidence"),
                    "confirmed_intruder_evidence": evidence_source.get("confirmed_intruder_evidence"),
                    "runtime_safety": evidence_source.get("runtime_safety"),
                }})
            )
    return payload


def production_approval_observability_signature(payload: Mapping[str, Any] | None) -> str:
    """Stable signature used to rate-limit identical production approval logs."""
    safe = production_approval_observability_payload(payload)
    return json.dumps(safe, sort_keys=True, separators=(",", ":"))


def production_approval_status_for_user(state: Mapping[str, Any] | None) -> tuple[str, str]:
    """Build a concise user-facing status from backend-owned approval state only."""
    source = _as_dict(state)
    reason_code = str(source.get("reason_code") or source.get("reasonCode") or "").strip()
    reason_text = str(source.get("reason_text") or source.get("reasonText") or source.get("approvalReasonText") or "").strip()
    candidate_status = str(source.get("candidate_status") or source.get("candidateStatus") or source.get("modelStatus") or "").strip().lower()
    protected_available = bool(source.get("protected_sessions_available") or source.get("protectedSessionsAvailable"))
    production_ready = bool(source.get("productionReady")) or reason_code == "production_ready"
    windows_collected = _safe_int_or_none(source.get("windows_collected") if source.get("windows_collected") is not None else source.get("windowsCollected"))
    windows_required = _safe_int_or_none(source.get("windows_required") if source.get("windows_required") is not None else source.get("windowsRequired"))
    far = _safe_float_or_none(source.get("far"))
    frr = _safe_float_or_none(source.get("frr"))

    if bool(source.get("demo_classic_protected")) and protected_available:
        return "Protected Sessions are available.", "success"
    if production_ready and protected_available:
        return "Protected Sessions are available. The model passed production approval and the active runtime bundle is valid.", "success"
    if production_ready and not protected_available:
        return "Production approval is not yet exposing Protected Sessions. Runtime validation or backend publication is still pending.", "warn"

    if reason_code in {"training_in_progress", "evaluation_in_progress"}:
        return reason_text or "BioAuth is still evaluating the candidate model before production approval.", "info"

    if candidate_status == "rejected" or reason_code in {"offline_approval_rejected", "frr_too_high", "far_too_high", "candidate_unstable"}:
        metric_hint = ""
        if reason_code in {"frr_too_high", "far_too_high", "candidate_unstable"}:
            metric_hint = f" Reason: {reason_code}."
        elif far is not None or frr is not None:
            parts = []
            if far is not None:
                parts.append(f"FAR {far}")
            if frr is not None:
                parts.append(f"FRR {frr}")
            metric_hint = " Metrics: " + ", ".join(parts) + "."
        return (
            "Training finished, but the candidate model was rejected by offline approval checks."
            f"{metric_hint} Collect more high-quality sessions before retraining."
        ), "warn"

    if candidate_status == "approved_for_shadow" or reason_code in {"approved_for_shadow_only", "shadow_validation_not_started", "shadow_validation_in_progress", "insufficient_shadow_windows"}:
        if windows_collected is not None and windows_required is not None:
            evidence = f" Shadow evidence: {windows_collected}/{windows_required} windows collected."
        elif windows_collected is not None:
            evidence = f" Shadow evidence: {windows_collected} windows collected."
        else:
            evidence = " Shadow validation is pending."
        return (
            "Training finished; the candidate model is approved for shadow validation only."
            f"{evidence} Production approval is pending, and Protected Sessions remain unavailable until backend approval passes."
        ), "warn"

    if reason_code in {"production_evidence_missing", "production_evidence_partial", "production_evidence_failed", "production_approval_blocked", "runtime_bundle_invalid", "auto_promotion_disabled", "manual_approval_required"}:
        reason = f" {reason_text}" if reason_text else ""
        return f"Production approval is blocked.{reason} Protected Sessions remain unavailable.", "warn"

    if reason_code == "production_approval_pending":
        return reason_text or "Production approval is pending. Protected Sessions remain unavailable until backend gates pass.", "warn"

    return "", "info"


def _base_contract_fields(
    *,
    model_status: str,
    production_ready: bool,
    protected_available: bool,
    production_approval_passed: bool,
    runtime_reason: str,
    approval_reason: str,
    report_available: bool,
    failed_gates: list[str],
    metric_values: Mapping[str, Any],
    policy_gate_results: Mapping[str, Any],
    metadata: Mapping[str, Any],
    report: Mapping[str, Any],
    training_active: bool = False,
    evaluation_active: bool = False,
    shadow_status: Mapping[str, Any] | None = None,
    auto_promotion_enabled: bool | None = None,
) -> Dict[str, Any]:
    shadow_status = _as_dict(shadow_status)
    windows_collected = _shadow_windows_collected(shadow_status)
    windows_required = _shadow_windows_required(shadow_status)
    progress_percent = _shadow_progress_percent(windows_collected, windows_required, shadow_status)
    candidate_status = _candidate_status_for_contract(model_status, production_ready)
    metric_reason = _metric_block_reason(policy_gate_results, failed_gates)
    normalized_status = str(model_status or "").strip().lower()
    status = "pending"
    phase = "production_approval"
    reason_code = "production_approval_pending"

    if training_active:
        phase = "training"
        reason_code = "training_in_progress"
    elif evaluation_active or normalized_status == "pending_evaluation":
        phase = "offline_approval"
        reason_code = "evaluation_in_progress"
    elif production_ready and protected_available:
        status = "approved"
        phase = "production_ready"
        candidate_status = "production_ready"
        reason_code = "production_ready"
    elif normalized_status in {"", "missing", "untrained"}:
        status = "none"
        phase = "no_candidate"
        reason_code = "no_candidate_model"
        candidate_status = "none"
    elif normalized_status == "rejected":
        status = "blocked"
        phase = "offline_approval"
        candidate_status = "rejected"
        reason_code = metric_reason or "offline_approval_rejected"
    elif normalized_status == "approved_for_shadow":
        phase = "shadow_validation"
        candidate_status = "approved_for_shadow"
        if metric_reason:
            status = "blocked"
            reason_code = metric_reason
        elif windows_collected is None:
            reason_code = "approved_for_shadow_only" if report_available else "shadow_validation_not_started"
        elif windows_collected <= 0:
            reason_code = "shadow_validation_not_started"
        elif windows_required is not None and windows_collected < windows_required:
            reason_code = "insufficient_shadow_windows"
        else:
            reason_code = "shadow_validation_in_progress"
    elif normalized_status == "approved_for_production":
        candidate_status = "production_ready"
        if auto_promotion_enabled is False and not protected_available:
            status = "blocked"
            reason_code = "auto_promotion_disabled"
        elif not production_approval_passed:
            status = "blocked"
            if runtime_reason and runtime_reason != "ok" and not protected_available:
                reason_code = "runtime_bundle_invalid"
            else:
                reason_code = "production_approval_blocked"
        elif runtime_reason and runtime_reason != "ok" and not protected_available:
            status = "blocked"
            reason_code = "runtime_bundle_invalid"
        else:
            reason_code = "production_approval_pending"
    elif failed_gates:
        status = "blocked"
        reason_code = metric_reason or "production_approval_blocked"

    reason_text = _contract_reason_text(
        reason_code=reason_code,
        approval_reason=approval_reason,
        runtime_reason=runtime_reason,
        report_available=report_available,
        windows_collected=windows_collected,
        windows_required=windows_required,
    )
    next_action = _contract_next_action(reason_code=reason_code, protected_available=protected_available)
    far_threshold = _threshold_value(metadata, report, "far")
    frr_threshold = _threshold_value(metadata, report, "frr")
    return {
        "status": status,
        "phase": phase,
        "candidate_status": candidate_status,
        "reason_code": reason_code,
        "reason_text": reason_text,
        "protected_sessions_available": bool(protected_available),
        "windows_collected": windows_collected,
        "windows_required": windows_required,
        "progress_percent": progress_percent,
        "far": _safe_float_or_none(metric_values.get("far")),
        "far_threshold": far_threshold,
        "frr": _safe_float_or_none(metric_values.get("frr")),
        "frr_threshold": frr_threshold,
        "next_action": next_action,
        "reasonCode": reason_code,
        "reasonText": reason_text,
        "candidateStatus": candidate_status,
        "protectedSessionsAvailable": bool(protected_available),
        "windowsCollected": windows_collected,
        "windowsRequired": windows_required,
        "progressPercent": progress_percent,
        "farThreshold": far_threshold,
        "frrThreshold": frr_threshold,
        "nextAction": next_action,
    }


def apply_production_approval_runtime_context(
    state: Mapping[str, Any] | None,
    *,
    training_active: bool = False,
    evaluation_active: bool = False,
    shadow_status: Mapping[str, Any] | None = None,
    auto_promotion_enabled: bool | None = None,
) -> Dict[str, Any]:
    """Overlay volatile runtime context onto explainability fields only."""
    payload = dict(state or {}) if isinstance(state, Mapping) else {}
    model_status = str(payload.get("modelStatus") or "untrained").strip().lower()
    production_ready = bool(payload.get("productionReady"))
    protected_available = bool(payload.get("protectedSessionsAvailable")) and production_ready
    contract = _base_contract_fields(
        model_status=model_status,
        production_ready=production_ready,
        protected_available=protected_available,
        production_approval_passed=bool(payload.get("productionApprovalPassed")),
        runtime_reason=str(payload.get("runtimeValidationReason") or "runtime_pointer_missing").strip(),
        approval_reason=str(payload.get("approvalReasonText") or ""),
        report_available=bool(payload.get("evaluationReportAvailable")),
        failed_gates=_safe_list(payload.get("failedProductionGates")),
        metric_values=_as_dict(payload.get("metricValues")),
        policy_gate_results=_as_dict(payload.get("policyGateResults")),
        metadata={},
        report={},
        training_active=training_active,
        evaluation_active=evaluation_active,
        shadow_status=shadow_status,
        auto_promotion_enabled=auto_promotion_enabled,
    )
    contract["protected_sessions_available"] = protected_available
    contract["protectedSessionsAvailable"] = protected_available
    contract = _merge_ledger_shadow_evidence_top_level_fields(
        payload,
        contract,
        training_active=training_active,
        evaluation_active=evaluation_active,
    )
    payload.update(contract)
    payload.update(build_protected_sessions_ready_notification_state(payload))
    return payload


def _read_json_file(path: Any) -> Dict[str, Any]:
    text_path = str(path or "").strip()
    if not text_path or not os.path.exists(text_path):
        return {}
    try:
        with open(text_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return dict(payload) if isinstance(payload, Mapping) else {}
    except Exception:
        return {}


def _existing_file_label(path: Any) -> str:
    text_path = str(path or "").strip()
    if not text_path or not os.path.exists(text_path):
        return ""
    return os.path.basename(text_path)


def _file_modified_label(path: Any) -> str:
    text_path = str(path or "").strip()
    if not text_path or not os.path.exists(text_path):
        return ""
    try:
        import datetime as _dt
        return _dt.datetime.fromtimestamp(os.path.getmtime(text_path), tz=_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


def _primary_metrics_from_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    evaluations = report.get("evaluations") if isinstance(report, Mapping) else {}
    primary_key = str(report.get("primary_evaluation") or "candidate_bundle") if isinstance(report, Mapping) else "candidate_bundle"
    primary = evaluations.get(primary_key) if isinstance(evaluations, Mapping) else None
    metrics = primary.get("metrics") if isinstance(primary, Mapping) else {}
    return dict(metrics) if isinstance(metrics, Mapping) else {}


def _safe_metric_values(*sources: Mapping[str, Any]) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in _METRIC_KEYS:
            if key not in source or source.get(key) is None:
                continue
            raw = source.get(key)
            if isinstance(raw, bool):
                values[key] = bool(raw)
            elif isinstance(raw, int):
                values[key] = int(raw)
            elif isinstance(raw, float):
                values[key] = round(float(raw), 6)
            elif isinstance(raw, str):
                try:
                    values[key] = round(float(raw), 6)
                except (TypeError, ValueError, OverflowError):
                    continue
    return values


def _gate_results_from_metadata(meta: Mapping[str, Any]) -> Dict[str, Any]:
    details = _as_dict(meta.get("policy_details"))
    return _as_dict(details.get("gate_results"))


def _safety_gate_results_from_metadata(meta: Mapping[str, Any]) -> Dict[str, Any]:
    details = _as_dict(meta.get("policy_details"))
    return _as_dict(details.get("safety_gate_results"))


def _closed_beta_missing(meta: Mapping[str, Any]) -> list[str]:
    details = _as_dict(meta.get("policy_details"))
    coverage = _as_dict(details.get("closed_beta_coverage"))
    return _safe_list(coverage.get("missing"))


def _failed_boolean_gates(gates: Mapping[str, Any]) -> list[str]:
    failed: list[str] = []
    for key, value in gates.items():
        if value is False:
            failed.append(str(key))
    return failed


def _reason_contains(reason: str, needles: Iterable[str]) -> bool:
    lowered = str(reason or "").lower()
    return any(str(needle).lower() in lowered for needle in needles)


def _failed_production_gates(*, model_status: str, metadata: Mapping[str, Any], report: Mapping[str, Any], runtime_reason: str) -> list[str]:
    failed: list[str] = []
    reason = str(metadata.get("approval_reason") or "").strip()
    evidence = _production_evidence_from_sources(metadata, report)
    if not evidence.gate.allows_production_eligibility:
        status = str(evidence.gate.status.value)
        failed.append(f"production_evidence_{status}")
        for code in evidence.gate.reason_codes:
            failed.append(f"production_evidence_{code}")
    safety_gates = _safety_gate_results_from_metadata(metadata)
    failed_safety = _failed_boolean_gates(safety_gates)
    if failed_safety and not _closed_beta_is_required(metadata):
        failed_safety = [key for key in failed_safety if key not in _CLOSED_BETA_ADVISORY_SAFETY_KEYS]
    if failed_safety:
        failed.append("closed_beta_safety_gate" if _closed_beta_is_required(metadata) else "safety_gate_failed")
        for key in failed_safety:
            failed.append(f"safety_{key}")
    if _closed_beta_is_required(metadata):
        for missing in _closed_beta_missing(metadata):
            failed.append(f"coverage_{missing}")
    if _reason_contains(reason, ["production margins", "not for production", "production promotion blocked", "closed-beta safety gate"]):
        if _is_closed_beta_only_reason(reason) and not _closed_beta_is_required(metadata):
            pass
        elif "production_margin_not_met" not in failed and not failed_safety:
            failed.append("production_margin_not_met")
    if model_status == "approved_for_shadow" and not failed:
        failed.append("production_margin_not_met")
    if model_status == "rejected":
        for key in _failed_boolean_gates(_gate_results_from_metadata(metadata)):
            failed.append(f"policy_{key}")
    if model_status == "approved_for_production" and runtime_reason and runtime_reason != "ok":
        failed.append(f"runtime_{runtime_reason}")
    if not report and model_status not in {"", "missing", "untrained"}:
        failed.append("evaluation_report_missing")
    deduped: list[str] = []
    for item in failed:
        text = str(item or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _active_routed_contexts(*, metadata: Mapping[str, Any], report: Mapping[str, Any], runtime_metadata: Mapping[str, Any]) -> list[str]:
    sources = []
    report_router = _as_dict(report.get("context_router"))
    sources.extend(_safe_list(report_router.get("active_contexts")))
    for source_meta in (metadata, runtime_metadata):
        context_models = _as_dict(source_meta.get("context_models"))
        sources.extend(_safe_list(context_models.get("active_contexts")))
        router = _as_dict(source_meta.get("context_router"))
        sources.extend(_safe_list(router.get("active_contexts")))
    result: list[str] = []
    for item in sources:
        if item in _CONTEXT_NAMES and item not in result:
            result.append(item)
    return result


def _approval_reason_text(*, model_status: str, production_ready: bool, runtime_reason: str, metadata: Mapping[str, Any], report_available: bool) -> str:
    existing = str(metadata.get("approval_reason") or "").strip()
    if existing:
        if _is_closed_beta_only_reason(existing) and not _closed_beta_is_required(metadata):
            advisory = "Closed-beta coverage is optional/advisory in this build and is not blocking approval."
            if model_status == "approved_for_shadow":
                return f"Production approval is pending because evidence/core gates have not all passed. {advisory} Protected Sessions remain locked until production approval passes."
            if model_status == "approved_for_production" and not production_ready:
                return f"Production approval is pending because runtime validation is still blocked by {runtime_reason or 'runtime validation'}. {advisory}"
            return f"Production approval follows core backend gates. {advisory}"
        if model_status == "approved_for_shadow" and "Protected Sessions" not in existing:
            return f"{existing} Protected Sessions remain locked until production approval passes."
        if model_status == "approved_for_production" and not production_ready:
            return f"{existing} Runtime validation is still blocked by {runtime_reason or 'runtime validation'}."
        return existing
    if model_status == "approved_for_production":
        return _PRODUCTION_READY_REASON if production_ready else _PRODUCTION_INVALID_REASON
    if model_status == "approved_for_shadow":
        return _SHADOW_REASON if report_available else _MISSING_REPORT_REASON
    if model_status == "rejected":
        return _REJECTED_REASON
    return _NOT_TRAINED_REASON


def _safe_recommendation(*, model_status: str, production_ready: bool, failed_gates: list[str], active_contexts: list[str], report_available: bool) -> str:
    if production_ready:
        return "Protected Sessions are available. Keep monitoring runtime health and calibration maturity."
    if "mouse_heavy" in active_contexts:
        return "Collect more balanced keyboard and mixed keyboard/mouse behavior before retraining."
    if "production_margin_not_met" in failed_gates:
        return "Collect more diverse trusted sessions, then retrain and re-evaluate before production promotion."
    if any(item.startswith("coverage_") for item in failed_gates) or "closed_beta_safety_gate" in failed_gates:
        return "Complete the required closed-beta safety coverage before production promotion."
    if any(item.startswith("runtime_") for item in failed_gates):
        return "Verify the production runtime bundle and metadata before starting Protected Sessions."
    if any(item.startswith("production_evidence_") for item in failed_gates):
        return "Collect more privacy-safe shadow/runtime evidence before production promotion."
    if not report_available and model_status not in {"", "missing", "untrained"}:
        return "Run evaluation again or restore evaluation_report.json before relying on production diagnostics."
    if model_status == "approved_for_shadow":
        return "Continue shadow validation and collect stronger trusted behavior before retraining."
    if model_status == "approved_for_production":
        return "Publish or repair the active production runtime bundle before Protected Sessions can start."
    return "Collect trusted enrollment sessions, train the model, and evaluate it through the existing policy gates."


def _background_next_action(*, model_status: str, production_ready: bool, failed_gates: list[str], report_available: bool) -> str:
    if production_ready:
        return "none"
    if any(item.startswith("runtime_") for item in failed_gates):
        return "verify_runtime_bundle"
    if any(item.startswith("production_evidence_") for item in failed_gates):
        return "collect_more_evidence"
    if model_status == "approved_for_shadow":
        return "collect_targeted_sessions"
    if model_status == "approved_for_production":
        return "repair_or_publish_runtime_bundle"
    if model_status == "rejected":
        return "collect_more_sessions"
    if not report_available and model_status not in {"", "missing", "untrained"}:
        return "restore_or_rerun_evaluation"
    return "train_when_ready"


def _model_status_from_sources(candidate_metadata: Mapping[str, Any], runtime_metadata: Mapping[str, Any], candidate_metadata_exists: bool) -> str:
    for source in (candidate_metadata, runtime_metadata):
        status = str(source.get("model_status") or "").strip().lower()
        if status:
            return status
    return "pending_evaluation" if candidate_metadata_exists else "untrained"


def build_production_approval_state(
    *,
    candidate_paths: Mapping[str, str],
    candidate_metadata: Optional[Mapping[str, Any]],
    runtime_validation: Optional[Mapping[str, Any]],
    runtime_paths: Optional[Mapping[str, str]] = None,
    user_id: str = "",
    training_active: bool = False,
    evaluation_active: bool = False,
    shadow_status: Optional[Mapping[str, Any]] = None,
    auto_promotion_enabled: bool | None = None,
) -> Dict[str, Any]:
    """Build a QML-safe state object without changing model/runtime policy decisions."""

    candidate_metadata = _as_dict(candidate_metadata)
    runtime_validation = _as_dict(runtime_validation)
    runtime_paths = _as_dict(runtime_paths)
    runtime_metadata = _as_dict(runtime_validation.get("metadata"))
    candidate_paths = _as_dict(candidate_paths)

    candidate_metadata_file = str(candidate_paths.get("metadata") or "")
    candidate_metadata_exists = bool(candidate_metadata_file and os.path.exists(candidate_metadata_file))
    report_path = str(candidate_paths.get("evaluation_report") or "")
    summary_path = str(candidate_paths.get("evaluation_summary") or "")
    report = _read_json_file(report_path)
    report_available = bool(report)
    model_status = _model_status_from_sources(candidate_metadata, runtime_metadata, candidate_metadata_exists)
    runtime_reason = str(runtime_validation.get("reason") or "runtime_pointer_missing").strip()
    production_evidence = _production_evidence_from_sources(candidate_metadata, report, runtime_metadata)
    ledger_shadow_status: Dict[str, Any] = {}
    candidate_digest = _candidate_digest_from_sources(candidate_paths, candidate_metadata, report, runtime_metadata)
    baseline_digest = _evidence_field_from_sources("baseline_artifact_digest", candidate_metadata, report, runtime_metadata)
    runtime_schema = _runtime_schema_from_sources(candidate_metadata, report, runtime_metadata)
    evaluation_report_digest = _evidence_report_digest_from_sources(report)
    if model_status == "approved_for_shadow":
        ledger_shadow_status = _ledger_evidence_for_user(
            user_id,
            candidate_artifact_digest=candidate_digest,
            baseline_artifact_digest=baseline_digest,
            evaluation_report_digest=evaluation_report_digest,
            runtime_schema_version=runtime_schema,
        )
        ledger_payload = ledger_shadow_status.get("production_evidence") if isinstance(ledger_shadow_status, Mapping) else None
        if isinstance(ledger_payload, Mapping):
            try:
                ledger_report = ProductionEvidenceReport.from_dict(ledger_payload, allow_unknown_reason_codes=True)
                production_evidence = _report_with_reason_codes(production_evidence if isinstance(production_evidence, ProductionEvidenceReport) else ledger_report, ledger_report.gate.reason_codes)
                # Runtime ledger records are the live source of evidence while a candidate is
                # approved only for shadow. Use their metrics, but preserve any existing reason
                # codes from stored candidate/report evidence.
                production_evidence = _report_with_reason_codes(ledger_report, production_evidence.gate.reason_codes)
            except (TypeError, ValueError):
                pass
    production_evidence_summary = _production_evidence_summary_from_report(production_evidence)
    if ledger_shadow_status:
        production_evidence_summary["windows_collected"] = _safe_int_or_none(ledger_shadow_status.get("windows_collected"))
        production_evidence_summary["records_total"] = _safe_int_or_none(ledger_shadow_status.get("records_total"))
        production_evidence_summary["records_accepted"] = _safe_int_or_none(ledger_shadow_status.get("records_accepted"))
        production_evidence_summary["records_ignored_for_identity"] = _safe_int_or_none(ledger_shadow_status.get("records_ignored_for_identity"))
        production_evidence_summary["records_ignored_for_candidate_digest"] = _safe_int_or_none(ledger_shadow_status.get("records_ignored_for_candidate_digest"))
        production_evidence_summary["records_ignored_for_runtime_schema"] = _safe_int_or_none(ledger_shadow_status.get("records_ignored_for_runtime_schema"))
        if isinstance(ledger_shadow_status.get("identity_filter"), Mapping):
            production_evidence_summary["identity_filter"] = dict(ledger_shadow_status.get("identity_filter") or {})
            production_evidence_summary["identityFilter"] = dict(ledger_shadow_status.get("identity_filter") or {})
        production_evidence_summary["source"] = "shadow_evidence_monitor"
        remediation_progress = ledger_shadow_status.get("remediation_progress") or ledger_shadow_status.get("remediationProgress")
        if isinstance(remediation_progress, Mapping):
            production_evidence_summary["remediation_progress"] = {str(k): max(0, int(v or 0)) for k, v in remediation_progress.items()}
            production_evidence_summary["remediationProgress"] = dict(production_evidence_summary["remediation_progress"])
        remediation_reasons = ledger_shadow_status.get("remediation_progress_reason_codes") or ledger_shadow_status.get("remediationProgressReasonCodes")
        if isinstance(remediation_reasons, (list, tuple)):
            production_evidence_summary["remediation_progress_reason_codes"] = [str(item) for item in remediation_reasons if str(item).strip()]
    production_evidence_passed = bool(production_evidence.gate.allows_production_eligibility)
    last_good_runtime_ready = bool(runtime_validation.get("ok")) and str(runtime_metadata.get("bundle_role") or "").strip().lower() == "production" and str(runtime_metadata.get("model_status") or "").strip().lower() == "approved_for_production"
    production_eligibility = build_production_eligibility_state(
        candidate_paths=candidate_paths,
        candidate_metadata=candidate_metadata,
        evaluation_report=report,
        runtime_validation=runtime_validation,
        runtime_paths=runtime_paths,
    )
    production_eligibility_passed = bool(production_eligibility.get("eligible"))
    production_approval_passed = (model_status == "approved_for_production" and production_eligibility_passed) or bool(last_good_runtime_ready)
    production_ready = bool(runtime_validation.get("ok")) and bool(production_approval_passed)
    switch_candidate_digest = str(
        production_eligibility.get("candidate_artifact_digest")
        or production_eligibility.get("candidateArtifactDigest")
        or production_evidence_summary.get("candidate_artifact_digest")
        or ""
    ).strip()
    eligibility_blockers = [str(item or "").strip() for item in production_eligibility.get("blockers") or [] if str(item or "").strip()]
    non_runtime_eligibility_blockers = [item for item in eligibility_blockers if not item.startswith("runtime_validation_")]
    production_ready_pending_user_approval = (
        model_status == "approved_for_production"
        and bool(production_evidence_passed)
        and bool(switch_candidate_digest)
        and not bool(production_ready)
        and not non_runtime_eligibility_blockers
        and bool(production_eligibility.get("rollbackReady") or production_eligibility.get("rollback_ready"))
    )
    shadow_validation_passed = model_status in {"approved_for_shadow", "approved_for_production"}

    failed_gates = _failed_production_gates(
        model_status=model_status,
        metadata=candidate_metadata,
        report=report,
        runtime_reason=runtime_reason,
    )
    active_contexts = _active_routed_contexts(metadata=candidate_metadata, report=report, runtime_metadata=runtime_metadata)
    metric_values = _safe_metric_values(
        _as_dict(candidate_metadata.get("policy_metrics")),
        _primary_metrics_from_report(report),
    )
    policy_gate_results = _gate_results_from_metadata(candidate_metadata)
    safety_gate_results = _safety_gate_results_from_metadata(candidate_metadata)

    approval_reason_text = _approval_reason_text(
        model_status=model_status,
        production_ready=production_ready,
        runtime_reason=runtime_reason,
        metadata=candidate_metadata,
        report_available=report_available,
    )
    payload = {
        "modelStatus": model_status,
        "productionReady": bool(production_ready),
        "protectedSessionsAvailable": bool(production_ready),
        "shadowValidationPassed": bool(shadow_validation_passed),
        "productionApprovalPassed": bool(production_approval_passed),
        "productionEvidencePassed": bool(production_evidence_passed),
        "productionEvidenceStatus": production_evidence_summary["status"],
        "productionEvidencePromotionEffect": production_evidence_summary["promotion_effect"],
        "productionEvidenceReasonCodes": list(production_evidence_summary["reason_codes"]),
        "productionEvidenceCandidateDigest": production_evidence_summary["candidate_artifact_digest"],
        "productionEligibilityPassed": bool(production_eligibility_passed),
        "production_eligibility_passed": bool(production_eligibility_passed),
        "productionEligibilityState": production_eligibility,
        "production_eligibility_state": production_eligibility,
        "productionEligibilityReason": str(production_eligibility.get("reason_code") or ""),
        "production_eligibility_reason": str(production_eligibility.get("reason_code") or ""),
        "productionEligibilityBlockers": list(production_eligibility.get("blockers") or []),
        "production_eligibility_blockers": list(production_eligibility.get("blockers") or []),
        "productionReadyPendingUserApproval": bool(production_ready_pending_user_approval),
        "production_ready_pending_user_approval": bool(production_ready_pending_user_approval),
        "userApprovalRequired": bool(production_ready_pending_user_approval),
        "user_approval_required": bool(production_ready_pending_user_approval),
        "modelSwitchCandidateDigest": switch_candidate_digest,
        "model_switch_candidate_digest": switch_candidate_digest,
        "candidateDigest": switch_candidate_digest,
        "candidate_digest": switch_candidate_digest,
        "approvalAction": "approveProductionModelSwitch" if production_ready_pending_user_approval else "none",
        "approval_action": "approveProductionModelSwitch" if production_ready_pending_user_approval else "none",
        "productionEvidenceSummary": production_evidence_summary,
        "production_evidence_status": production_evidence_summary["status"],
        "production_evidence_promotion_effect": production_evidence_summary["promotion_effect"],
        "production_evidence_reason_codes": list(production_evidence_summary["reason_codes"]),
        "production_evidence_candidate_digest": production_evidence_summary["candidate_artifact_digest"],
        "production_evidence_summary": production_evidence_summary,
        "approvalReasonText": approval_reason_text,
        "failedProductionGates": failed_gates,
        "evaluationReportFile": _existing_file_label(report_path),
        "evaluationSummaryFile": _existing_file_label(summary_path),
        "evaluationReportAvailable": bool(report_available),
        "evaluationSummaryAvailable": bool(_existing_file_label(summary_path)),
        "evaluationReportModifiedAt": _file_modified_label(report_path),
        "evaluationSummaryModifiedAt": _file_modified_label(summary_path),
        "lastEvaluationTime": _file_modified_label(report_path) or _file_modified_label(summary_path),
        "activeRoutedContexts": active_contexts,
        "safeRecommendationText": _safe_recommendation(
            model_status=model_status,
            production_ready=production_ready,
            failed_gates=failed_gates,
            active_contexts=active_contexts,
            report_available=report_available,
        ),
        "backgroundNextAction": "user_approve_model_switch" if production_ready_pending_user_approval else _background_next_action(
            model_status=model_status,
            production_ready=production_ready,
            failed_gates=failed_gates,
            report_available=report_available,
        ),
        "metricValues": metric_values,
        "policyGateResults": policy_gate_results,
        "safetyGateResults": safety_gate_results,
        **_closed_beta_observability_payload(candidate_metadata),
        "runtimeValidationReason": runtime_reason,
        "runtimeBundleRole": str((runtime_metadata or candidate_metadata).get("bundle_role") or "").strip().lower(),
        "runtimeBundleBase": os.path.basename(str(runtime_paths.get("base") or "")) if runtime_paths else "",
        "last_good_production_available": bool(last_good_runtime_ready),
        "lastGoodProductionAvailable": bool(last_good_runtime_ready),
        "last_good_production_source": "commercial_core_22e_last_good_production_fallback" if last_good_runtime_ready else "",
        "lastGoodProductionSource": "commercial_core_22e_last_good_production_fallback" if last_good_runtime_ready else "",
        "pending_shadow_candidate_status": model_status if last_good_runtime_ready and model_status == "approved_for_shadow" else "",
        "pendingShadowCandidateStatus": model_status if last_good_runtime_ready and model_status == "approved_for_shadow" else "",
    }
    effective_shadow_status = dict(shadow_status or {}) if isinstance(shadow_status, Mapping) else {}
    if ledger_shadow_status:
        ledger_windows = _safe_int_or_none(ledger_shadow_status.get("windows_collected") if ledger_shadow_status.get("windows_collected") is not None else ledger_shadow_status.get("windowsCollected"))
        existing_windows = _safe_int_or_none(effective_shadow_status.get("windows_collected"))
        existing_shadow_windows = _safe_int_or_none(effective_shadow_status.get("shadow_windows_collected"))
        if ledger_windows is not None and (existing_windows is None or ledger_windows > existing_windows):
            effective_shadow_status["windows_collected"] = ledger_windows
        if ledger_windows is not None and (existing_shadow_windows is None or ledger_windows > existing_shadow_windows):
            effective_shadow_status["shadow_windows_collected"] = ledger_windows
        existing_codes = _safe_list(effective_shadow_status.get("reason_codes"))
        for code in _safe_list(ledger_shadow_status.get("reason_codes")):
            if code not in existing_codes:
                existing_codes.append(code)
        effective_shadow_status["reason_codes"] = existing_codes
    payload.update(_base_contract_fields(
        model_status=model_status,
        production_ready=production_ready,
        protected_available=bool(production_ready),
        production_approval_passed=production_approval_passed,
        runtime_reason=runtime_reason,
        approval_reason=approval_reason_text,
        report_available=report_available,
        failed_gates=failed_gates,
        metric_values=metric_values,
        policy_gate_results=policy_gate_results,
        metadata=candidate_metadata,
        report=report,
        training_active=training_active,
        evaluation_active=evaluation_active,
        shadow_status=effective_shadow_status,
        auto_promotion_enabled=auto_promotion_enabled,
    ))
    demo_classic_rejected_override = bool(_demo_classic_rejected_candidate_status(model_status))
    demo_classic_ready = bool(
        _demo_classic_protected_enabled()
        and _demo_classic_candidate_status(model_status)
        and candidate_metadata_exists
    )
    if demo_classic_ready:
        payload.update(_demo_classic_ready_overlay(artifact_digest=switch_candidate_digest or candidate_digest, rejected_override=demo_classic_rejected_override))
        production_evidence_summary = dict(payload.get("productionEvidenceSummary") or payload.get("production_evidence_summary") or {})
        reason_codes = [str(item) for item in list(production_evidence_summary.get("reason_codes") or []) if str(item).strip()]
        demo_reason = "demo_classic_rejected_candidate_override" if demo_classic_rejected_override else "demo_classic_protected"
        if demo_classic_rejected_override:
            original_rejection_reason = str(
                candidate_metadata.get("reason_code")
                or candidate_metadata.get("reasonCode")
                or "offline_approval_rejected"
            ).strip()
            if original_rejection_reason and original_rejection_reason not in reason_codes:
                reason_codes.append(original_rejection_reason)
        if demo_reason not in reason_codes:
            reason_codes.append(demo_reason)
        production_evidence_summary["reason_codes"] = reason_codes
        production_evidence_summary["status"] = production_evidence_summary.get("status") or "demo_bypassed"
        production_evidence_summary["promotion_effect"] = production_evidence_summary.get("promotion_effect") or "demo_direct"
        payload["productionEvidenceSummary"] = production_evidence_summary
        payload["production_evidence_summary"] = production_evidence_summary
        payload["productionEvidenceReasonCodes"] = reason_codes
        payload["production_evidence_reason_codes"] = reason_codes
    payload.update(build_protected_sessions_ready_notification_state(payload))
    if demo_classic_ready:
        payload.update(_demo_classic_ready_overlay(artifact_digest=switch_candidate_digest or candidate_digest, rejected_override=demo_classic_rejected_override))
    return payload


__all__ = [
    "apply_production_approval_runtime_context",
    "build_production_approval_state",
    "build_production_eligibility_state",
    "build_protected_sessions_ready_notification_state",
    "with_protected_sessions_ready_notification_state",
    "production_approval_observability_payload",
    "production_approval_observability_signature",
    "production_approval_status_for_user",
]
