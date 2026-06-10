"""Policy decisions for BioAuth model bundle promotion stages."""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping

from evaluation_core.production_evidence import (
    ProductionEvidenceGateResult,
    ProductionEvidencePromotionEffect,
    ProductionEvidenceReasonCode,
    ProductionEvidenceReport,
    ProductionEvidenceStatus,
)

POLICY_VERSION = "1.3"


SAFETY_POLICY_LIMITS = {
    "max_false_lock_count": 0,
    "max_warning_per_hour": 6.0,
    "max_low_quality_decision_rate": 0.35,
    # Closed-beta cohort coverage is advisory by default for local/single-user
    # builds. It may be made mandatory only by explicit policy configuration.
    "require_closed_beta_coverage": False,
}

_CLOSED_BETA_ADVISORY_SAFETY_KEYS = {"safety_metrics_present", "warning_per_hour", "data_coverage"}


def closed_beta_gate_mode() -> str:
    """Return the backend-owned closed-beta gate mode.

    Default is advisory so missing beta cohort coverage never becomes a hard
    production blocker by itself. Operators that require cohort coverage can set
    BIOAUTH_CLOSED_BETA_GATE_MODE=required or BIOAUTH_REQUIRE_CLOSED_BETA_GATE=1.
    """

    raw = str(os.environ.get("BIOAUTH_CLOSED_BETA_GATE_MODE") or "").strip().lower()
    if raw in {"required", "require", "blocking", "enforced"}:
        return "required"
    if raw in {"advisory", "optional", "off", "0", "false", "no"}:
        return "advisory"
    require = str(os.environ.get("BIOAUTH_REQUIRE_CLOSED_BETA_GATE") or "").strip().lower()
    if require in {"1", "true", "yes", "required", "require", "blocking", "enforced"}:
        return "required"
    return "advisory"


def closed_beta_gate_required() -> bool:
    return closed_beta_gate_mode() == "required"


def _closed_beta_advisory_reasons(safety: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    coverage = safety.get("data_coverage") if isinstance(safety, Mapping) else {}
    coverage = dict(coverage or {}) if isinstance(coverage, Mapping) else {}
    if not bool(safety):
        reasons.append("safety_metrics_missing")
    warning_per_hour = safety.get("warning_per_hour") if isinstance(safety, Mapping) else None
    if warning_per_hour is None:
        reasons.append("warning_per_hour_missing")
    if not bool(coverage.get("closed_beta_ready")):
        missing = coverage.get("missing") or []
        if missing:
            for item in missing:
                text = str(item or "").strip()
                if text and text not in reasons:
                    reasons.append(text)
        elif "closed_beta_coverage_missing" not in reasons:
            reasons.append("closed_beta_coverage_missing")
    return reasons


def _closed_beta_gate_payload(safety: Mapping[str, Any], gate: Mapping[str, bool]) -> Dict[str, Any]:
    required = closed_beta_gate_required()
    reasons = _closed_beta_advisory_reasons(safety)
    advisory_failed = bool(reasons)
    blocking = bool(required and (not bool(gate.get("warning_per_hour")) or not bool(gate.get("data_coverage")) or not bool(gate.get("safety_metrics_present"))))
    if blocking:
        status = "required_failed"
    elif required:
        status = "available" if not advisory_failed else "required_partial"
    elif advisory_failed:
        status = "optional_missing" if "safety_metrics_missing" in reasons or "closed_beta_coverage_missing" in reasons else "optional_partial"
    else:
        status = "available"
    return {
        "mode": "required" if required else "advisory",
        "required": bool(required),
        "blocking": bool(blocking),
        "status": status,
        "advisory_reasons": list(reasons),
        "missing": list(reasons),
    }


def _safety_metrics(report: Mapping[str, Any]) -> Dict[str, Any]:
    safety = report.get("safety_metrics") if isinstance(report, Mapping) else {}
    return dict(safety) if isinstance(safety, Mapping) else {}


def _production_evidence_report(report: Mapping[str, Any]) -> ProductionEvidenceReport:
    payload = report.get("production_evidence") if isinstance(report, Mapping) else None
    if isinstance(payload, Mapping):
        try:
            return ProductionEvidenceReport.from_dict(payload, allow_unknown_reason_codes=True)
        except (TypeError, ValueError):
            return ProductionEvidenceReport.missing_evidence()
    return ProductionEvidenceReport.missing_evidence()


def _production_evidence_policy_gate(evidence: ProductionEvidenceReport) -> Dict[str, Any]:
    gate = evidence.gate if isinstance(evidence.gate, ProductionEvidenceGateResult) else ProductionEvidenceGateResult.missing()
    return {
        "status": gate.status.value,
        "promotion_effect": gate.promotion_effect.value,
        "reason_codes": list(gate.reason_codes),
        "production_evidence_passed": gate.status is ProductionEvidenceStatus.PASS,
        "production_eligible_effect": gate.promotion_effect is ProductionEvidencePromotionEffect.PRODUCTION_ELIGIBLE,
        "allows_production_eligibility": bool(gate.allows_production_eligibility),
    }


def _production_evidence_reason_text(evidence: ProductionEvidenceReport) -> str:
    codes = list(evidence.gate.reason_codes)
    if not codes:
        return ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_MISSING
    return ", ".join(str(code) for code in codes)


def _safety_policy_gate(safety: Mapping[str, Any]) -> Dict[str, bool]:
    coverage = safety.get("data_coverage") if isinstance(safety, Mapping) else {}
    coverage = dict(coverage or {}) if isinstance(coverage, Mapping) else {}
    warning_per_hour = safety.get("warning_per_hour")
    low_quality = safety.get("low_quality_decision_rate")
    false_locks = int(safety.get("false_lock_count") or 0) if isinstance(safety, Mapping) else 0
    required = closed_beta_gate_required()
    warning_gate = (warning_per_hour is not None) and _metric_gate(warning_per_hour, maximum=float(SAFETY_POLICY_LIMITS["max_warning_per_hour"]))
    coverage_gate = bool(coverage.get("closed_beta_ready"))
    return {
        "safety_metrics_present": bool(safety) if required else True,
        "false_lock_count": false_locks <= int(SAFETY_POLICY_LIMITS["max_false_lock_count"]),
        "warning_per_hour": warning_gate if required else True,
        "low_quality_decision_rate": _metric_gate(low_quality, maximum=float(SAFETY_POLICY_LIMITS["max_low_quality_decision_rate"])) if low_quality is not None else True,
        "data_coverage": coverage_gate if required else True,
        "raw_data_absent": not bool(safety.get("raw_biometric_data_included")),
    }


def _failed_safety_messages(gate: Mapping[str, bool], safety: Mapping[str, Any]) -> list[str]:
    messages: list[str] = []
    if not bool(gate.get("safety_metrics_present")):
        messages.append("safety metrics missing")
    if not bool(gate.get("false_lock_count")):
        messages.append(f"false_lock_count ({int(safety.get('false_lock_count') or 0)})")
    if not bool(gate.get("warning_per_hour")):
        messages.append(f"warning_per_hour ({safety.get('warning_per_hour')})")
    if not bool(gate.get("low_quality_decision_rate")):
        messages.append(f"low_quality_decision_rate ({safety.get('low_quality_decision_rate')})")
    if not bool(gate.get("data_coverage")):
        coverage = dict(safety.get("data_coverage") or {}) if isinstance(safety, Mapping) else {}
        missing = coverage.get("missing") or []
        detail = ",".join(str(item) for item in missing) if missing else "closed_beta_coverage"
        messages.append(f"data_coverage ({detail})")
    if not bool(gate.get("raw_data_absent")):
        messages.append("raw biometric data present in report")
    return messages


def _failed_metric_messages(gate: Mapping[str, bool], *, auc: Any, f1: float, precision: float, recall: float, far: float, frr: float, intruder_sessions: int) -> list[str]:
    messages: list[str] = []
    if not bool(gate.get("minimum_support")):
        messages.append("minimum evaluation support")
    if intruder_sessions > 0 and not bool(gate.get("auc")):
        messages.append(f"AUC ({auc})")
    if not bool(gate.get("f1")):
        messages.append(f"F1 ({f1:.3f})")
    if intruder_sessions > 0 and not bool(gate.get("far")):
        messages.append(f"FAR ({far:.3f})")
    if not bool(gate.get("frr")):
        messages.append(f"FRR ({frr:.3f})")
    if intruder_sessions > 0 and not bool(gate.get("precision")):
        messages.append(f"precision ({precision:.3f})")
    if intruder_sessions > 0 and not bool(gate.get("recall")):
        messages.append(f"recall ({recall:.3f})")
    return messages


def _primary_metrics(report: Mapping[str, Any]) -> Dict[str, Any]:
    evaluations = report.get("evaluations") if isinstance(report, Mapping) else {}
    primary_key = str(report.get("primary_evaluation") or "candidate_bundle") if isinstance(report, Mapping) else "candidate_bundle"
    primary = evaluations.get(primary_key) if isinstance(evaluations, Mapping) else None
    metrics = primary.get("metrics") if isinstance(primary, Mapping) else {}
    return dict(metrics) if isinstance(metrics, Mapping) else {}


def _metric_gate(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> bool:
    try:
        number = float(value)
    except Exception:
        return False
    if minimum is not None and number < float(minimum):
        return False
    if maximum is not None and number > float(maximum):
        return False
    return True


def _hybrid_rollout_details(*, report: Mapping[str, Any], model_status: str) -> Dict[str, Any]:
    deep_sequence = dict(report.get("deep_sequence") or {}) if isinstance(report, Mapping) else {}
    deep_validation = dict(deep_sequence.get("validation_metrics") or {})
    hybrid_metrics = dict(report.get("hybrid_scoring") or {}) if isinstance(report, Mapping) else {}
    framework = str(deep_sequence.get("framework") or "")
    deep_available = bool(deep_sequence.get("available"))
    deep_runtime_enabled = bool(deep_sequence.get("runtime_enabled"))
    deep_sessions = int(hybrid_metrics.get("deep_available_session_count") or 0)

    reasons: list[str] = []
    if not deep_available:
        reasons.append("deep_artifact_missing")
    if not deep_runtime_enabled:
        reasons.append("deep_runtime_disabled")
    if deep_sessions <= 0:
        reasons.append("deep_shadow_coverage_low")

    hybrid_gate = {
        "f1": _metric_gate(hybrid_metrics.get("f1"), minimum=0.55),
        "far": _metric_gate(hybrid_metrics.get("far"), maximum=0.18),
        "frr": _metric_gate(hybrid_metrics.get("frr"), maximum=0.28),
        "auc": (hybrid_metrics.get("auc") is None) or _metric_gate(hybrid_metrics.get("auc"), minimum=0.70),
        "support": deep_sessions >= 1,
        "deep_validation": (deep_validation.get("auc") is None) or _metric_gate(deep_validation.get("auc"), minimum=0.65),
    }
    hybrid_ready = deep_available and deep_runtime_enabled and model_status == "approved_for_production" and all(hybrid_gate.values())
    accelerated_ready = hybrid_ready and framework in {"onnxruntime", "openvino"}

    if hybrid_ready:
        rollout_status = "accelerated_ready" if accelerated_ready else "hybrid_ready"
        allowed_modes = ["classic", "auto", "hybrid"] + (["hybrid_accelerated"] if accelerated_ready else [])
        blocked_reason = None
    elif deep_available and model_status in {"approved_for_shadow", "approved_for_production"}:
        rollout_status = "shadow_only_deep_ready"
        allowed_modes = ["classic", "auto"]
        blocked_reason = ",".join(reasons) if reasons else "shadow_only_policy"
    elif model_status == "approved_for_production":
        rollout_status = "classic_only_ready"
        allowed_modes = ["classic", "auto"]
        blocked_reason = ",".join(reasons) if reasons else "deep_not_ready"
    else:
        rollout_status = "classic_only_candidate"
        allowed_modes = ["classic"]
        blocked_reason = ",".join(reasons) if reasons else "awaiting_policy_approval"

    return {
        "rollout_status": rollout_status,
        "deep_available": deep_available,
        "deep_runtime_enabled": deep_runtime_enabled,
        "production_decision_enabled": bool(hybrid_ready),
        "shadow_diagnostics_enabled": bool(deep_available),
        "rollback_to_classic_on_failure": True,
        "allowed_modes": allowed_modes,
        "preferred_mode": "hybrid_accelerated" if accelerated_ready else ("hybrid" if hybrid_ready else "classic"),
        "preferred_backend": "accelerated" if accelerated_ready else ("pytorch_cpu" if hybrid_ready else "classic"),
        "blocked_reason": blocked_reason,
        "hybrid_gate": hybrid_gate,
        "deep_validation_metrics": deep_validation,
        "hybrid_metrics": hybrid_metrics,
    }


def evaluate_model_policy(report: Mapping[str, Any]) -> Dict[str, Any]:
    metrics = _primary_metrics(report)
    session_count = int(metrics.get("session_count") or 0)
    legitimate_sessions = int(metrics.get("legitimate_session_count") or 0)
    intruder_sessions = int(metrics.get("intruder_session_count") or 0)
    precision = float(metrics.get("precision") or 0.0)
    recall = float(metrics.get("recall") or 0.0)
    far = float(metrics.get("far") or 0.0)
    frr = float(metrics.get("frr") or 0.0)
    f1 = float(metrics.get("f1") or 0.0)
    auc = metrics.get("auc")
    safety = _safety_metrics(report)
    safety_gate = _safety_policy_gate(safety)
    production_evidence = _production_evidence_report(report)
    production_evidence_gate = _production_evidence_policy_gate(production_evidence)

    status = "rejected"
    approval_reason = "Candidate did not meet the minimum offline policy thresholds."

    if session_count < 4 or legitimate_sessions < 2:
        approval_reason = "Rejected because the evaluation set is too small for a trustworthy policy decision."
        gate_results = {
            "minimum_support": False,
            "auc": False,
            "f1": False,
            "far": False,
            "frr": False,
            "precision": False,
            "recall": False,
        }
    elif intruder_sessions <= 0:
        shadow_gate = {
            "minimum_support": legitimate_sessions >= 4,
            "auc": True,
            "f1": _metric_gate(f1, minimum=0.55),
            "far": True,
            "frr": _metric_gate(frr, maximum=0.30),
            "precision": True,
            "recall": True,
        }
        production_gate = {
            "minimum_support": legitimate_sessions >= 8,
            "auc": True,
            "f1": _metric_gate(f1, minimum=0.70),
            "far": True,
            "frr": _metric_gate(frr, maximum=0.15),
            "precision": True,
            "recall": True,
        }
        gate_results = production_gate if all(production_gate.values()) else shadow_gate
        if all(production_gate.values()):
            status = "approved_for_production"
            approval_reason = "Approved for production because the positive-only evaluation stayed stable with low false rejection and strong session consistency."
        elif all(shadow_gate.values()):
            status = "approved_for_shadow"
            approval_reason = "Approved for shadow because the positive-only evaluation looks stable enough for controlled validation, but not for production yet."
        else:
            failed = _failed_metric_messages(shadow_gate, auc=auc, f1=f1, precision=precision, recall=recall, far=far, frr=frr, intruder_sessions=intruder_sessions)
            detail = ", ".join(failed) if failed else "consistency"
            approval_reason = f"Rejected because the positive-only evaluation still shows too much false rejection or too little consistency ({detail})."
    else:
        shadow_gate = {
            "minimum_support": session_count >= 6,
            "auc": _metric_gate(auc, minimum=0.65),
            "f1": _metric_gate(f1, minimum=0.40),
            "far": _metric_gate(far, maximum=0.25),
            "frr": _metric_gate(frr, maximum=0.35),
            "precision": _metric_gate(precision, minimum=0.40),
            "recall": _metric_gate(recall, minimum=0.40),
        }
        production_gate = {
            "minimum_support": session_count >= 6,
            "auc": _metric_gate(auc, minimum=0.78),
            "f1": _metric_gate(f1, minimum=0.60),
            "far": _metric_gate(far, maximum=0.10),
            "frr": _metric_gate(frr, maximum=0.20),
            "precision": _metric_gate(precision, minimum=0.60),
            "recall": _metric_gate(recall, minimum=0.60),
        }
        gate_results = production_gate if all(production_gate.values()) else shadow_gate
        if all(production_gate.values()):
            status = "approved_for_production"
            approval_reason = "Approved for production because AUC, F1, FAR, FRR, precision, and recall all cleared the production policy thresholds."
        elif all(shadow_gate.values()):
            status = "approved_for_shadow"
            approval_reason = "Approved for shadow because AUC, F1, FAR, and FRR cleared the shadow policy thresholds, but production margins are not met yet."
        else:
            failed = _failed_metric_messages(shadow_gate, auc=auc, f1=f1, precision=precision, recall=recall, far=far, frr=frr, intruder_sessions=intruder_sessions)
            detail = ", ".join(failed) if failed else "offline policy thresholds"
            approval_reason = f"Rejected because the offline trade-off between discrimination quality and false accepts/rejects is still outside the allowed range ({detail})."

    closed_beta_gate = _closed_beta_gate_payload(safety, safety_gate)
    if status == "approved_for_production" and not all(safety_gate.values()):
        failed_safety = _failed_safety_messages(safety_gate, safety)
        detail = ", ".join(failed_safety) if failed_safety else "safety gate"
        status = "approved_for_shadow"
        if bool(closed_beta_gate.get("blocking")):
            approval_reason = f"Production promotion blocked by closed-beta safety gate: {detail}. Candidate remains eligible for shadow validation only."
        else:
            approval_reason = f"Production promotion blocked by required safety gate: {detail}. Candidate remains eligible for shadow validation only."

    if status == "approved_for_production":
        evidence_detail = _production_evidence_reason_text(production_evidence)
        if production_evidence.gate.status is ProductionEvidenceStatus.FAIL:
            status = "rejected"
            approval_reason = (
                "Rejected because Production Evidence Gate v2 blocked production "
                f"({evidence_detail}). Existing approval, runtime validation, shadow validation, "
                "and auto-promotion gates remain authoritative."
            )
        elif not production_evidence.gate.allows_production_eligibility:
            status = "approved_for_shadow"
            approval_reason = (
                "Production Evidence Gate v2 has not passed yet "
                f"({evidence_detail}). Candidate remains eligible for shadow validation only; "
                "evidence is necessary for production eligibility but never sufficient by itself."
            )

    rollout = _hybrid_rollout_details(report=report, model_status=status)
    return {
        "model_status": status,
        "policy_version": POLICY_VERSION,
        "approval_reason": approval_reason,
        "policy_metrics": {
            "auc": auc,
            "f1": f1,
            "precision": precision,
            "recall": recall,
            "far": far,
            "frr": frr,
            "frr_user": safety.get("frr_user"),
            "far_intruder": safety.get("far_intruder"),
            "warning_per_hour": safety.get("warning_per_hour"),
            "lock_per_hour": safety.get("lock_per_hour"),
            "false_lock_count": safety.get("false_lock_count"),
            "low_quality_decision_rate": safety.get("low_quality_decision_rate"),
            "session_count": session_count,
            "legitimate_session_count": legitimate_sessions,
            "intruder_session_count": intruder_sessions,
            "production_evidence_status": production_evidence.gate.status.value,
            "production_evidence_promotion_effect": production_evidence.gate.promotion_effect.value,
        },
        "production_evidence_reason_codes": list(production_evidence.gate.reason_codes),
        "policy_gate": str(report.get("primary_evaluation") or "candidate_bundle"),
        "rollout_status": rollout["rollout_status"],
        "rollout_details": rollout,
        "policy_details": {
            "uses_aggregate_metrics": True,
            "gate_results": gate_results,
            "safety_gate_results": safety_gate,
            "production_evidence_gate_results": production_evidence_gate,
            "production_evidence_reason_codes": list(production_evidence.gate.reason_codes),
            "safety_policy_limits": {**dict(SAFETY_POLICY_LIMITS), "require_closed_beta_coverage": bool(closed_beta_gate.get("required"))},
            "closed_beta_coverage": dict((safety.get("data_coverage") or {})),
            "closed_beta_gate": dict(closed_beta_gate),
            "closed_beta_gate_required": bool(closed_beta_gate.get("required")),
            "closed_beta_gate_status": closed_beta_gate.get("status"),
            "closed_beta_gate_blocking": bool(closed_beta_gate.get("blocking")),
            "closed_beta_advisory_reasons": list(closed_beta_gate.get("advisory_reasons") or []),
            "rollout": rollout,
        },
    }
