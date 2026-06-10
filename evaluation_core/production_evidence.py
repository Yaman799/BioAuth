from __future__ import annotations

"""Privacy-safe Production Evidence Gate v2 contracts.

This module is intentionally contract-only. It defines serializable evidence
schemas for later evaluation/policy wiring, but it does not change production
readiness, Protected Sessions availability, runtime validation, shadow
validation, auto-promotion, or QML behavior.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Mapping, Sequence

PRODUCTION_EVIDENCE_SCHEMA_VERSION = 1


class ProductionEvidenceStatus(str, Enum):
    """Gate status values for evidence-only production eligibility."""

    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"


class ProductionEvidencePromotionEffect(str, Enum):
    """Policy effect suggestions emitted by the evidence contract only.

    ``production_eligible`` is not production readiness. Existing BioAuth policy,
    production approval, shadow validation, runtime validation, and auto-promotion
    gates remain authoritative in later integration phases.
    """

    PRODUCTION_ELIGIBLE = "production_eligible"
    SHADOW_ONLY = "shadow_only"
    BLOCKED = "blocked"


class ProductionEvidenceReasonCode:
    """Stable string reason-code constants for Production Evidence Gate v2."""

    INSUFFICIENT_MODEL_AGREEMENT: ClassVar[str] = "insufficient_model_agreement"
    CRITICAL_MODEL_DISAGREEMENT: ClassVar[str] = "critical_model_disagreement"
    HIGH_RISK_MODEL_DISAGREEMENT: ClassVar[str] = "high_risk_model_disagreement"
    INSUFFICIENT_POST_UNLOCK_EVIDENCE: ClassVar[str] = "insufficient_post_unlock_evidence"
    POST_UNLOCK_FALSE_LOCK_DETECTED: ClassVar[str] = "post_unlock_false_lock_detected"
    CONFIRMED_INTRUDER_LOW_RISK: ClassVar[str] = "confirmed_intruder_low_risk"
    SIMULATED_FALSE_LOCK_DETECTED: ClassVar[str] = "simulated_false_lock_detected"
    FEATURE_QUALITY_TOO_LOW: ClassVar[str] = "feature_quality_too_low"
    UNKNOWN_RATE_TOO_HIGH: ClassVar[str] = "unknown_rate_too_high"
    PRODUCTION_EVIDENCE_MISSING: ClassVar[str] = "production_evidence_missing"
    PRODUCTION_EVIDENCE_PARTIAL: ClassVar[str] = "production_evidence_partial"
    PRODUCTION_EVIDENCE_FAILED: ClassVar[str] = "production_evidence_failed"
    PRODUCTION_EVIDENCE_PASSED: ClassVar[str] = "production_evidence_passed"
    BASELINE_DECISION_MISSING: ClassVar[str] = "baseline_decision_missing"
    BASELINE_ARTIFACT_DIGEST_MISMATCH: ClassVar[str] = "baseline_artifact_digest_mismatch"
    INSUFFICIENT_MODEL_AGREEMENT_DATA: ClassVar[str] = "insufficient_model_agreement_data"
    CANDIDATE_DIGEST_MISMATCH: ClassVar[str] = "candidate_digest_mismatch"
    RUNTIME_SCHEMA_MISMATCH: ClassVar[str] = "runtime_schema_mismatch"
    SHADOW_EVIDENCE_LOCK_SUPPRESSED: ClassVar[str] = "shadow_evidence_lock_suppressed"
    UNKNOWN_REASON_CODE: ClassVar[str] = "unknown_reason_code"

    ALL: ClassVar[frozenset[str]] = frozenset(
        {
            INSUFFICIENT_MODEL_AGREEMENT,
            CRITICAL_MODEL_DISAGREEMENT,
            HIGH_RISK_MODEL_DISAGREEMENT,
            INSUFFICIENT_POST_UNLOCK_EVIDENCE,
            POST_UNLOCK_FALSE_LOCK_DETECTED,
            CONFIRMED_INTRUDER_LOW_RISK,
            SIMULATED_FALSE_LOCK_DETECTED,
            FEATURE_QUALITY_TOO_LOW,
            UNKNOWN_RATE_TOO_HIGH,
            PRODUCTION_EVIDENCE_MISSING,
            PRODUCTION_EVIDENCE_PARTIAL,
            PRODUCTION_EVIDENCE_FAILED,
            PRODUCTION_EVIDENCE_PASSED,
            BASELINE_DECISION_MISSING,
            BASELINE_ARTIFACT_DIGEST_MISMATCH,
            INSUFFICIENT_MODEL_AGREEMENT_DATA,
            CANDIDATE_DIGEST_MISMATCH,
            RUNTIME_SCHEMA_MISMATCH,
            SHADOW_EVIDENCE_LOCK_SUPPRESSED,
            UNKNOWN_REASON_CODE,
        }
    )


class SelectionPromotionReasonCode:
    """Stable reason codes for the Commercial-Core-06 selection promotion gate.

    These codes are intentionally separate from ProductionEvidenceReasonCode: the
    selection gate is a challenger-vs-champion promotion guard, not a raw runtime
    evidence classifier.
    """

    NOT_EVALUATED: ClassVar[str] = "selection_gate_not_evaluated"
    PASSED: ClassVar[str] = "selection_gate_passed"
    WEIGHTED_SCORE_BELOW_THRESHOLD: ClassVar[str] = "selection_weighted_score_below_threshold"
    CANDIDATE_DIGEST_MISMATCH: ClassVar[str] = "selection_candidate_digest_mismatch"
    RUNTIME_SCHEMA_MISMATCH: ClassVar[str] = "selection_runtime_schema_mismatch"
    SIGNED_ARTIFACTS_MISSING: ClassVar[str] = "selection_signed_artifacts_missing"
    ROLLBACK_NOT_READY: ClassVar[str] = "selection_rollback_not_ready"
    STARTUP_SUCCESS_RATE_TOO_LOW: ClassVar[str] = "selection_startup_success_rate_too_low"
    FALSE_LOCK_REGRESSION: ClassVar[str] = "selection_false_lock_regression"
    FAR_REGRESSION: ClassVar[str] = "selection_far_regression"
    SHADOW_PIPELINE_REGRESSION: ClassVar[str] = "selection_shadow_pipeline_regression"
    INSUFFICIENT_EVIDENCE_VOLUME: ClassVar[str] = "selection_insufficient_evidence_volume"
    PRODUCTION_EVIDENCE_NOT_PASSED: ClassVar[str] = "selection_production_evidence_not_passed"
    PRIVACY_UNSAFE_PAYLOAD: ClassVar[str] = "selection_privacy_unsafe_payload"

    ALL: ClassVar[frozenset[str]] = frozenset(
        {
            NOT_EVALUATED,
            PASSED,
            WEIGHTED_SCORE_BELOW_THRESHOLD,
            CANDIDATE_DIGEST_MISMATCH,
            RUNTIME_SCHEMA_MISMATCH,
            SIGNED_ARTIFACTS_MISSING,
            ROLLBACK_NOT_READY,
            STARTUP_SUCCESS_RATE_TOO_LOW,
            FALSE_LOCK_REGRESSION,
            FAR_REGRESSION,
            SHADOW_PIPELINE_REGRESSION,
            INSUFFICIENT_EVIDENCE_VOLUME,
            PRODUCTION_EVIDENCE_NOT_PASSED,
            PRIVACY_UNSAFE_PAYLOAD,
        }
    )




_DISALLOWED_RAW_BIOMETRIC_FIELDS = frozenset(
    {
        "raw_keyboard",
        "raw_keyboard_events",
        "keyboard_events",
        "keyboard_samples",
        "keystrokes",
        "key_timings",
        "raw_mouse",
        "raw_mouse_events",
        "mouse_events",
        "mouse_samples",
        "mouse_movements",
        "raw_biometric_events",
        "biometric_samples",
        "biometric_features",
        "feature_vector",
        "feature_vectors",
        "feature_values",
        "raw_feature_values",
    }
)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_string(value: Any) -> str:
    return "" if value is None else str(value)


def contains_raw_biometric_fields(payload: Mapping[str, Any] | Sequence[Any] | Any) -> bool:
    """Return True when a payload contains disallowed raw behavioral-data keys."""

    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key).strip().lower() in _DISALLOWED_RAW_BIOMETRIC_FIELDS:
                return True
            if contains_raw_biometric_fields(value):
                return True
        return False
    if isinstance(payload, (list, tuple)):
        return any(contains_raw_biometric_fields(item) for item in payload)
    return False


def assert_privacy_safe_payload(payload: Mapping[str, Any]) -> None:
    """Reject payloads that attempt to carry raw biometric/behavioral data."""

    if contains_raw_biometric_fields(payload):
        raise ValueError("production evidence contracts must not include raw biometric or behavioral event fields")


def normalize_reason_codes(reason_codes: Sequence[Any] | str | None, *, allow_unknown: bool = False) -> tuple[str, ...]:
    """Normalize reason codes while rejecting unknown values by default."""

    if reason_codes is None:
        return tuple()
    raw_codes: Sequence[Any]
    if isinstance(reason_codes, str):
        raw_codes = [reason_codes]
    elif isinstance(reason_codes, Sequence):
        raw_codes = reason_codes
    else:
        raw_codes = [reason_codes]

    normalized: list[str] = []
    unknown: list[str] = []
    for item in raw_codes:
        code = str(item).strip().lower()
        if not code:
            continue
        if code not in ProductionEvidenceReasonCode.ALL:
            unknown.append(code)
            if allow_unknown:
                code = ProductionEvidenceReasonCode.UNKNOWN_REASON_CODE
            else:
                continue
        if code not in normalized:
            normalized.append(code)

    if unknown and not allow_unknown:
        raise ValueError(f"unknown production evidence reason code(s): {', '.join(unknown)}")
    return tuple(normalized)


@dataclass(frozen=True)
class ModelAgreementMetrics:
    overall_agreement_rate: float = 0.0
    trusted_window_agreement_rate: float = 0.0
    critical_disagreement_count: int = 0
    high_risk_disagreement_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_agreement_rate": float(self.overall_agreement_rate),
            "trusted_window_agreement_rate": float(self.trusted_window_agreement_rate),
            "critical_disagreement_count": int(self.critical_disagreement_count),
            "high_risk_disagreement_count": int(self.high_risk_disagreement_count),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ModelAgreementMetrics":
        data = _as_mapping(payload)
        return cls(
            overall_agreement_rate=_as_float(data.get("overall_agreement_rate")),
            trusted_window_agreement_rate=_as_float(data.get("trusted_window_agreement_rate")),
            critical_disagreement_count=_as_int(data.get("critical_disagreement_count")),
            high_risk_disagreement_count=_as_int(data.get("high_risk_disagreement_count")),
        )


@dataclass(frozen=True)
class PostUnlockEvidenceMetrics:
    trusted_window_count: int = 0
    warning_rate: float = 0.0
    simulated_false_locks: int = 0
    feature_quality_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trusted_window_count": int(self.trusted_window_count),
            "warning_rate": float(self.warning_rate),
            "simulated_false_locks": int(self.simulated_false_locks),
            "feature_quality_rate": float(self.feature_quality_rate),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "PostUnlockEvidenceMetrics":
        data = _as_mapping(payload)
        return cls(
            trusted_window_count=_as_int(data.get("trusted_window_count")),
            warning_rate=_as_float(data.get("warning_rate")),
            simulated_false_locks=_as_int(data.get("simulated_false_locks")),
            feature_quality_rate=_as_float(data.get("feature_quality_rate")),
        )


@dataclass(frozen=True)
class ConfirmedIntruderEvidenceMetrics:
    available: bool = False
    confirmed_intruder_count: int = 0
    confirmed_intruder_low_risk_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": bool(self.available),
            "confirmed_intruder_count": int(self.confirmed_intruder_count),
            "confirmed_intruder_low_risk_count": int(self.confirmed_intruder_low_risk_count),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ConfirmedIntruderEvidenceMetrics":
        data = _as_mapping(payload)
        return cls(
            available=_as_bool(data.get("available")),
            confirmed_intruder_count=_as_int(data.get("confirmed_intruder_count")),
            confirmed_intruder_low_risk_count=_as_int(data.get("confirmed_intruder_low_risk_count")),
        )


@dataclass(frozen=True)
class RuntimeSafetyMetrics:
    simulated_false_lock_count: int = 0
    unknown_rate: float = 0.0
    low_quality_decision_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulated_false_lock_count": int(self.simulated_false_lock_count),
            "unknown_rate": float(self.unknown_rate),
            "low_quality_decision_rate": float(self.low_quality_decision_rate),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "RuntimeSafetyMetrics":
        data = _as_mapping(payload)
        return cls(
            simulated_false_lock_count=_as_int(data.get("simulated_false_lock_count")),
            unknown_rate=_as_float(data.get("unknown_rate")),
            low_quality_decision_rate=_as_float(data.get("low_quality_decision_rate")),
        )


@dataclass(frozen=True)
class ProductionEvidenceGateResult:
    status: ProductionEvidenceStatus = ProductionEvidenceStatus.PARTIAL
    promotion_effect: ProductionEvidencePromotionEffect = ProductionEvidencePromotionEffect.SHADOW_ONLY
    reason_codes: tuple[str, ...] = field(default_factory=lambda: (ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_MISSING,))

    def __post_init__(self) -> None:
        normalized = normalize_reason_codes(self.reason_codes)
        object.__setattr__(self, "reason_codes", normalized)
        status = self.status if isinstance(self.status, ProductionEvidenceStatus) else ProductionEvidenceStatus(str(self.status))
        effect = self.promotion_effect if isinstance(self.promotion_effect, ProductionEvidencePromotionEffect) else ProductionEvidencePromotionEffect(str(self.promotion_effect))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "promotion_effect", effect)

    @property
    def allows_production_eligibility(self) -> bool:
        """Evidence-only eligibility hint; never unlocks Protected Sessions."""

        return self.status is ProductionEvidenceStatus.PASS and self.promotion_effect is ProductionEvidencePromotionEffect.PRODUCTION_ELIGIBLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "promotion_effect": self.promotion_effect.value,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def missing(cls) -> "ProductionEvidenceGateResult":
        return cls(
            status=ProductionEvidenceStatus.PARTIAL,
            promotion_effect=ProductionEvidencePromotionEffect.SHADOW_ONLY,
            reason_codes=(ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_MISSING,),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None, *, allow_unknown_reason_codes: bool = False) -> "ProductionEvidenceGateResult":
        data = _as_mapping(payload)
        assert_privacy_safe_payload(data)
        status = ProductionEvidenceStatus(str(data.get("status") or ProductionEvidenceStatus.PARTIAL.value))
        effect = ProductionEvidencePromotionEffect(str(data.get("promotion_effect") or ProductionEvidencePromotionEffect.SHADOW_ONLY.value))
        raw_codes = data.get("reason_codes")
        reason_codes = normalize_reason_codes(raw_codes, allow_unknown=allow_unknown_reason_codes)
        if not reason_codes:
            reason_codes = (ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_MISSING,)
        if ProductionEvidenceReasonCode.UNKNOWN_REASON_CODE in reason_codes and allow_unknown_reason_codes:
            if status is ProductionEvidenceStatus.PASS or effect is ProductionEvidencePromotionEffect.PRODUCTION_ELIGIBLE:
                status = ProductionEvidenceStatus.PARTIAL
                effect = ProductionEvidencePromotionEffect.SHADOW_ONLY
        return cls(status=status, promotion_effect=effect, reason_codes=reason_codes)



@dataclass(frozen=True)
class SelectionPromotionThresholds:
    """Guardrails and weights for selection-based candidate promotion.

    This gate implements the Commercial-Core-06 principle: feedback and shadow
    evidence select whether a candidate is safe enough for review/promotion; they
    do not update model weights, thresholds, or runtime pointers by themselves.
    """

    min_weighted_score: float = 0.03
    max_far_relative_worsening: float = 0.05
    max_false_lock_rate_absolute_worsening: float = 0.001
    min_startup_success_rate: float = 0.995
    max_shadow_pipeline_failure_rate: float = 0.02
    min_total_evidence_windows: int = 0
    min_adjudicated_high_risk_events: int = 0
    weight_eer: float = 0.30
    weight_false_lock_rate: float = 0.25
    weight_frr_at_target_far: float = 0.15
    weight_time_to_detect: float = 0.10
    weight_adjudicated_disagreement: float = 0.10
    weight_shadow_pipeline_failure_rate: float = 0.10


@dataclass(frozen=True)
class SelectionBasedPromotionGateResult:
    """Selection-based promotion report for challenger-vs-champion evaluation.

    The result is intentionally evidence-only. A PASS makes a candidate eligible
    for later user/admin approval; it does not switch production, alter
    thresholds, lock Windows, or unlock Protected Sessions.
    """

    status: str = "not_evaluated"
    promotion_effect: str = "manual_review_required"
    weighted_score: float = 0.0
    min_weighted_score: float = 0.03
    reason_codes: tuple[str, ...] = field(default_factory=lambda: (SelectionPromotionReasonCode.NOT_EVALUATED,))
    metric_improvements: Mapping[str, float] = field(default_factory=dict)
    guardrails: Mapping[str, bool] = field(default_factory=dict)
    candidate_metrics: Mapping[str, float] = field(default_factory=dict)
    champion_metrics: Mapping[str, float] = field(default_factory=dict)
    evidence_volume: Mapping[str, int] = field(default_factory=dict)
    candidate_artifact_digest: str = ""
    baseline_artifact_digest: str = ""
    runtime_schema_version: str = ""
    policy_version: str = "commercial-core-06-selection-promotion-gate-v1"

    def __post_init__(self) -> None:
        status = str(self.status or "not_evaluated").strip().lower()
        effect = str(self.promotion_effect or "manual_review_required").strip().lower()
        codes: list[str] = []
        for item in self.reason_codes or ():
            code = str(item or "").strip().lower()
            if not code:
                continue
            if code not in SelectionPromotionReasonCode.ALL:
                code = SelectionPromotionReasonCode.PRIVACY_UNSAFE_PAYLOAD if "privacy" in code else SelectionPromotionReasonCode.NOT_EVALUATED
            if code not in codes:
                codes.append(code)
        if not codes:
            codes = [SelectionPromotionReasonCode.PASSED if status == "pass" else SelectionPromotionReasonCode.NOT_EVALUATED]
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "promotion_effect", effect)
        object.__setattr__(self, "reason_codes", tuple(codes))
        object.__setattr__(self, "metric_improvements", {str(k): float(v) for k, v in dict(self.metric_improvements or {}).items()})
        object.__setattr__(self, "guardrails", {str(k): bool(v) for k, v in dict(self.guardrails or {}).items()})
        object.__setattr__(self, "candidate_metrics", {str(k): float(v) for k, v in dict(self.candidate_metrics or {}).items()})
        object.__setattr__(self, "champion_metrics", {str(k): float(v) for k, v in dict(self.champion_metrics or {}).items()})
        object.__setattr__(self, "evidence_volume", {str(k): int(v) for k, v in dict(self.evidence_volume or {}).items()})
        assert_privacy_safe_payload(self.to_dict())

    @property
    def evaluated(self) -> bool:
        return self.status != "not_evaluated"

    @property
    def allows_selection_promotion(self) -> bool:
        return self.status == "pass" and self.promotion_effect == "production_eligible_after_approval"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "promotion_effect": self.promotion_effect,
            "weighted_score": float(self.weighted_score),
            "min_weighted_score": float(self.min_weighted_score),
            "reason_codes": list(self.reason_codes),
            "metric_improvements": dict(self.metric_improvements),
            "guardrails": dict(self.guardrails),
            "candidate_metrics": dict(self.candidate_metrics),
            "champion_metrics": dict(self.champion_metrics),
            "evidence_volume": dict(self.evidence_volume),
            "candidate_artifact_digest": str(self.candidate_artifact_digest or ""),
            "baseline_artifact_digest": str(self.baseline_artifact_digest or ""),
            "runtime_schema_version": str(self.runtime_schema_version or ""),
            "policy_version": str(self.policy_version or "commercial-core-06-selection-promotion-gate-v1"),
        }
        assert_privacy_safe_payload(payload)
        return payload

    @classmethod
    def not_evaluated(cls) -> "SelectionBasedPromotionGateResult":
        return cls()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "SelectionBasedPromotionGateResult":
        data = _as_mapping(payload)
        if not data:
            return cls.not_evaluated()
        assert_privacy_safe_payload(data)
        return cls(
            status=str(data.get("status") or "not_evaluated"),
            promotion_effect=str(data.get("promotion_effect") or "manual_review_required"),
            weighted_score=_as_float(data.get("weighted_score")),
            min_weighted_score=_as_float(data.get("min_weighted_score"), 0.03),
            reason_codes=tuple(data.get("reason_codes") or ()),
            metric_improvements=_as_mapping(data.get("metric_improvements")),
            guardrails=_as_mapping(data.get("guardrails")),
            candidate_metrics=_as_mapping(data.get("candidate_metrics")),
            champion_metrics=_as_mapping(data.get("champion_metrics")),
            evidence_volume=_as_mapping(data.get("evidence_volume")),
            candidate_artifact_digest=_as_string(data.get("candidate_artifact_digest")),
            baseline_artifact_digest=_as_string(data.get("baseline_artifact_digest")),
            runtime_schema_version=_as_string(data.get("runtime_schema_version")),
            policy_version=_as_string(data.get("policy_version")) or "commercial-core-06-selection-promotion-gate-v1",
        )


def _metric_value(metrics: Mapping[str, Any] | None, *keys: str, default: float = 0.0) -> float:
    source = _as_mapping(metrics)
    for key in keys:
        if key in source:
            return _as_float(source.get(key), default)
    return default


def _relative_improvement(champion_value: float, candidate_value: float, *, eps: float = 1e-9) -> float:
    return (float(champion_value) - float(candidate_value)) / max(abs(float(champion_value)), eps)


def build_selection_based_promotion_gate(
    *,
    candidate_metrics: Mapping[str, Any] | None = None,
    champion_metrics: Mapping[str, Any] | None = None,
    evidence_volume: Mapping[str, Any] | None = None,
    candidate_artifact_digest: str = "",
    baseline_artifact_digest: str = "",
    runtime_schema_version: str = "",
    expected_candidate_artifact_digest: str = "",
    expected_runtime_schema_version: str = "",
    production_evidence_passed: bool = True,
    signed_artifacts_ok: bool = True,
    rollback_ready: bool = True,
    startup_success_rate: float = 1.0,
    thresholds: SelectionPromotionThresholds | None = None,
) -> SelectionBasedPromotionGateResult:
    """Build the Commercial-Core-06 challenger selection promotion gate.

    The function consumes aggregate metrics only. It refuses raw biometric/event
    fields and returns an evidence-only gate result. Passing this gate means
    "eligible for manual/user/admin approval", not automatic production switch.
    """

    candidate = dict(_as_mapping(candidate_metrics))
    champion = dict(_as_mapping(champion_metrics))
    volume = dict(_as_mapping(evidence_volume))
    payload = {"candidate_metrics": candidate, "champion_metrics": champion, "evidence_volume": volume}
    assert_privacy_safe_payload(payload)
    limits = thresholds or SelectionPromotionThresholds()

    eer_improvement = _relative_improvement(
        _metric_value(champion, "eer", "EER"),
        _metric_value(candidate, "eer", "EER"),
    )
    false_lock_improvement = _relative_improvement(
        _metric_value(champion, "false_lock_rate", "falseLockRate"),
        _metric_value(candidate, "false_lock_rate", "falseLockRate"),
    )
    frr_improvement = _relative_improvement(
        _metric_value(champion, "frr_at_target_far", "FRRAtTargetFAR", "frr"),
        _metric_value(candidate, "frr_at_target_far", "FRRAtTargetFAR", "frr"),
    )
    ttd_improvement = _relative_improvement(
        _metric_value(champion, "time_to_detect", "timeToDetect"),
        _metric_value(candidate, "time_to_detect", "timeToDetect"),
    )
    disagreement_improvement = _relative_improvement(
        _metric_value(champion, "adjudicated_disagreement_rate", "disagreement_on_adjudicated_events"),
        _metric_value(candidate, "adjudicated_disagreement_rate", "disagreement_on_adjudicated_events"),
    )
    pipeline_failure_improvement = _relative_improvement(
        _metric_value(champion, "shadow_pipeline_failure_rate", "pipeline_failure_rate"),
        _metric_value(candidate, "shadow_pipeline_failure_rate", "pipeline_failure_rate"),
    )
    improvements = {
        "eer": eer_improvement,
        "false_lock_rate": false_lock_improvement,
        "frr_at_target_far": frr_improvement,
        "time_to_detect": ttd_improvement,
        "adjudicated_disagreement_rate": disagreement_improvement,
        "shadow_pipeline_failure_rate": pipeline_failure_improvement,
    }
    weighted_score = (
        limits.weight_eer * eer_improvement
        + limits.weight_false_lock_rate * false_lock_improvement
        + limits.weight_frr_at_target_far * frr_improvement
        + limits.weight_time_to_detect * ttd_improvement
        + limits.weight_adjudicated_disagreement * disagreement_improvement
        + limits.weight_shadow_pipeline_failure_rate * pipeline_failure_improvement
    )

    champion_far = _metric_value(champion, "far", "FAR")
    candidate_far = _metric_value(candidate, "far", "FAR")
    champion_false_lock = _metric_value(champion, "false_lock_rate", "falseLockRate")
    candidate_false_lock = _metric_value(candidate, "false_lock_rate", "falseLockRate")
    candidate_pipeline_failure = _metric_value(candidate, "shadow_pipeline_failure_rate", "pipeline_failure_rate")
    total_windows = int(_metric_value(volume, "total_windows", "evidence_windows", default=0.0))
    adjudicated_events = int(_metric_value(volume, "adjudicated_high_risk_events", "adjudicated_events", default=0.0))

    far_relative_worsening = (candidate_far - champion_far) / max(abs(champion_far), 1e-9)
    false_lock_absolute_worsening = candidate_false_lock - champion_false_lock
    guardrails = {
        "production_evidence_passed": bool(production_evidence_passed),
        "candidate_digest_match": not expected_candidate_artifact_digest or not candidate_artifact_digest or candidate_artifact_digest == expected_candidate_artifact_digest,
        "runtime_schema_match": not expected_runtime_schema_version or not runtime_schema_version or runtime_schema_version == expected_runtime_schema_version,
        "signed_artifacts_ok": bool(signed_artifacts_ok),
        "rollback_ready": bool(rollback_ready),
        "startup_success_rate_ok": float(startup_success_rate) >= float(limits.min_startup_success_rate),
        "far_regression_ok": far_relative_worsening <= float(limits.max_far_relative_worsening),
        "false_lock_regression_ok": false_lock_absolute_worsening <= float(limits.max_false_lock_rate_absolute_worsening),
        "shadow_pipeline_failure_rate_ok": candidate_pipeline_failure <= float(limits.max_shadow_pipeline_failure_rate),
        "evidence_volume_ok": total_windows >= int(limits.min_total_evidence_windows) and adjudicated_events >= int(limits.min_adjudicated_high_risk_events),
        "weighted_score_ok": weighted_score >= float(limits.min_weighted_score),
    }

    reason_codes: list[str] = []
    if not guardrails["production_evidence_passed"]:
        reason_codes.append(SelectionPromotionReasonCode.PRODUCTION_EVIDENCE_NOT_PASSED)
    if not guardrails["candidate_digest_match"]:
        reason_codes.append(SelectionPromotionReasonCode.CANDIDATE_DIGEST_MISMATCH)
    if not guardrails["runtime_schema_match"]:
        reason_codes.append(SelectionPromotionReasonCode.RUNTIME_SCHEMA_MISMATCH)
    if not guardrails["signed_artifacts_ok"]:
        reason_codes.append(SelectionPromotionReasonCode.SIGNED_ARTIFACTS_MISSING)
    if not guardrails["rollback_ready"]:
        reason_codes.append(SelectionPromotionReasonCode.ROLLBACK_NOT_READY)
    if not guardrails["startup_success_rate_ok"]:
        reason_codes.append(SelectionPromotionReasonCode.STARTUP_SUCCESS_RATE_TOO_LOW)
    if not guardrails["far_regression_ok"]:
        reason_codes.append(SelectionPromotionReasonCode.FAR_REGRESSION)
    if not guardrails["false_lock_regression_ok"]:
        reason_codes.append(SelectionPromotionReasonCode.FALSE_LOCK_REGRESSION)
    if not guardrails["shadow_pipeline_failure_rate_ok"]:
        reason_codes.append(SelectionPromotionReasonCode.SHADOW_PIPELINE_REGRESSION)
    if not guardrails["evidence_volume_ok"]:
        reason_codes.append(SelectionPromotionReasonCode.INSUFFICIENT_EVIDENCE_VOLUME)
    if not guardrails["weighted_score_ok"]:
        reason_codes.append(SelectionPromotionReasonCode.WEIGHTED_SCORE_BELOW_THRESHOLD)

    passed = not reason_codes
    if passed:
        status = "pass"
        effect = "production_eligible_after_approval"
        reason_codes = [SelectionPromotionReasonCode.PASSED]
    else:
        status = "blocked"
        effect = "shadow_only"

    return SelectionBasedPromotionGateResult(
        status=status,
        promotion_effect=effect,
        weighted_score=weighted_score,
        min_weighted_score=limits.min_weighted_score,
        reason_codes=tuple(reason_codes),
        metric_improvements=improvements,
        guardrails=guardrails,
        candidate_metrics={str(k): _as_float(v) for k, v in candidate.items() if isinstance(v, (int, float, str)) and str(v).strip() != ""},
        champion_metrics={str(k): _as_float(v) for k, v in champion.items() if isinstance(v, (int, float, str)) and str(v).strip() != ""},
        evidence_volume={str(k): _as_int(v) for k, v in volume.items() if isinstance(v, (int, float, str)) and str(v).strip() != ""},
        candidate_artifact_digest=candidate_artifact_digest,
        baseline_artifact_digest=baseline_artifact_digest,
        runtime_schema_version=runtime_schema_version,
    )


@dataclass(frozen=True)
class ProductionEvidenceReport:
    schema_version: int = PRODUCTION_EVIDENCE_SCHEMA_VERSION
    candidate_artifact_digest: str = ""
    baseline_artifact_digest: str = ""
    evaluation_report_digest: str = ""
    runtime_schema_version: str = ""
    model_agreement: ModelAgreementMetrics = field(default_factory=ModelAgreementMetrics)
    post_unlock_evidence: PostUnlockEvidenceMetrics = field(default_factory=PostUnlockEvidenceMetrics)
    confirmed_intruder_evidence: ConfirmedIntruderEvidenceMetrics = field(default_factory=ConfirmedIntruderEvidenceMetrics)
    runtime_safety: RuntimeSafetyMetrics = field(default_factory=RuntimeSafetyMetrics)
    gate: ProductionEvidenceGateResult = field(default_factory=ProductionEvidenceGateResult.missing)
    selection_promotion_gate: SelectionBasedPromotionGateResult = field(default_factory=SelectionBasedPromotionGateResult.not_evaluated)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": int(self.schema_version),
            "candidate_artifact_digest": self.candidate_artifact_digest,
            "baseline_artifact_digest": self.baseline_artifact_digest,
            "evaluation_report_digest": self.evaluation_report_digest,
            "runtime_schema_version": self.runtime_schema_version,
            "model_agreement": self.model_agreement.to_dict(),
            "post_unlock_evidence": self.post_unlock_evidence.to_dict(),
            "confirmed_intruder_evidence": self.confirmed_intruder_evidence.to_dict(),
            "runtime_safety": self.runtime_safety.to_dict(),
            "gate": self.gate.to_dict(),
            "selection_promotion_gate": self.selection_promotion_gate.to_dict(),
        }
        assert_privacy_safe_payload(payload)
        return payload

    @classmethod
    def missing_evidence(
        cls,
        *,
        candidate_artifact_digest: str = "",
        baseline_artifact_digest: str = "",
        evaluation_report_digest: str = "",
        runtime_schema_version: str = "",
    ) -> "ProductionEvidenceReport":
        """Return fail-safe missing evidence: partial + shadow-only."""

        return cls(
            candidate_artifact_digest=candidate_artifact_digest,
            baseline_artifact_digest=baseline_artifact_digest,
            evaluation_report_digest=evaluation_report_digest,
            runtime_schema_version=runtime_schema_version,
            gate=ProductionEvidenceGateResult.missing(),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None, *, allow_unknown_reason_codes: bool = False) -> "ProductionEvidenceReport":
        data = _as_mapping(payload)
        assert_privacy_safe_payload(data)
        return cls(
            schema_version=_as_int(data.get("schema_version"), PRODUCTION_EVIDENCE_SCHEMA_VERSION),
            candidate_artifact_digest=_as_string(data.get("candidate_artifact_digest")),
            baseline_artifact_digest=_as_string(data.get("baseline_artifact_digest")),
            evaluation_report_digest=_as_string(data.get("evaluation_report_digest")),
            runtime_schema_version=_as_string(data.get("runtime_schema_version")),
            model_agreement=ModelAgreementMetrics.from_dict(data.get("model_agreement")),
            post_unlock_evidence=PostUnlockEvidenceMetrics.from_dict(data.get("post_unlock_evidence")),
            confirmed_intruder_evidence=ConfirmedIntruderEvidenceMetrics.from_dict(data.get("confirmed_intruder_evidence")),
            runtime_safety=RuntimeSafetyMetrics.from_dict(data.get("runtime_safety")),
            gate=ProductionEvidenceGateResult.from_dict(data.get("gate"), allow_unknown_reason_codes=allow_unknown_reason_codes),
            selection_promotion_gate=SelectionBasedPromotionGateResult.from_dict(data.get("selection_promotion_gate") or data.get("selectionPromotionGate")),
        )


@dataclass(frozen=True)
class ProductionEvidenceThresholds:
    """Thresholds used by the side-effect-free Production Evidence Gate MVP.

    These thresholds classify privacy-safe evidence only. They do not promote a
    model, unlock Protected Sessions, or replace existing BioAuth policy gates.
    """

    min_model_agreement_samples: int = 1
    min_overall_agreement_rate: float = 0.85
    min_trusted_window_agreement_rate: float = 0.90
    min_post_unlock_trusted_windows: int = 3
    max_unknown_rate: float = 0.30
    min_feature_quality_rate: float = 0.80
    low_risk_threshold: float = 0.35


def _coerce_records(records: Sequence[Mapping[str, Any]] | None) -> tuple[Mapping[str, Any], ...]:
    return tuple(item for item in (records or ()) if isinstance(item, Mapping))


def _first_present(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record:
            return record.get(key)
    return None


def _nested_mapping(record: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = record.get(key)
    return value if isinstance(value, Mapping) else {}


def _summary_value(record: Mapping[str, Any], prefix: str, *keys: str) -> Any:
    """Read a summary value from flat or nested candidate/baseline fields."""

    prefixed = tuple(f"{prefix}_{key}" for key in keys)
    value = _first_present(record, *prefixed)
    if value is not None:
        return value
    nested = _nested_mapping(record, prefix)
    return _first_present(nested, *keys)


def _normalized_decision(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "accepted": "trusted",
        "accept": "trusted",
        "allow": "trusted",
        "allowed": "trusted",
        "legitimate": "trusted",
        "owner": "trusted",
        "ok": "trusted",
        "pass": "trusted",
        "trusted_owner": "trusted",
        "deny": "warning",
        "denied": "warning",
        "reject": "warning",
        "rejected": "warning",
        "unauthorized": "warning",
        "suspicious": "warning",
        "intruder": "warning",
        "warn": "warning",
        "locked": "lock",
        "device_locked": "lock",
        "intruder_lock": "lock",
        "abstain": "unknown",
        "none": "unknown",
        "no_decision": "unknown",
    }
    return aliases.get(text, text or "unknown")


def _record_truth_is_intruder(record: Mapping[str, Any]) -> bool:
    for key in ("confirmed_intruder", "is_confirmed_intruder", "truth_intruder", "intruder"):
        if key in record:
            return _as_bool(record.get(key))
    for key in ("true_label", "truth_label", "label"):
        value = record.get(key)
        try:
            return int(value) == 1
        except (TypeError, ValueError):
            pass
    text = str(_first_present(record, "truth", "actor", "session_type", "event_type") or "").strip().lower()
    return text in {"intruder", "attacker", "negative", "unauthorized", "confirmed_intruder"}


def _record_truth_is_owner(record: Mapping[str, Any]) -> bool:
    if _record_truth_is_intruder(record):
        return False
    for key in ("trusted_owner", "owner", "legitimate", "is_owner"):
        if key in record:
            return _as_bool(record.get(key))
    for key in ("true_label", "truth_label", "label"):
        value = record.get(key)
        try:
            return int(value) == 0
        except (TypeError, ValueError):
            pass
    text = str(_first_present(record, "truth", "actor", "session_type", "event_type") or "").strip().lower()
    return text in {"owner", "legitimate", "positive", "authorized", "trusted"}


def _decision_is_low_risk(record: Mapping[str, Any], *, prefix: str = "candidate", threshold: float = 0.35) -> bool:
    explicit = _summary_value(record, prefix, "low_risk", "is_low_risk")
    if explicit is not None:
        return _as_bool(explicit)
    level = str(_summary_value(record, prefix, "risk_level", "risk_bucket", "risk_band") or "").strip().lower()
    if level in {"low", "trusted", "safe", "owner"}:
        return True
    if level in {"medium", "warning", "high", "critical", "lock", "unknown"}:
        return False
    risk = _summary_value(record, prefix, "risk", "risk_score", "score")
    try:
        return float(risk) <= float(threshold)
    except (TypeError, ValueError):
        pass
    decision = _normalized_decision(_summary_value(record, prefix, "decision", "final", "status", "label"))
    return decision == "trusted"


def _decision_is_warning_or_lock(record: Mapping[str, Any], *, prefix: str) -> bool:
    decision = _normalized_decision(_summary_value(record, prefix, "decision", "final", "status", "label"))
    if decision in {"warning", "lock"}:
        return True
    level = str(_summary_value(record, prefix, "risk_level", "risk_bucket", "risk_band") or "").strip().lower()
    return level in {"high", "critical", "warning", "lock"}


def _decision_is_lock(record: Mapping[str, Any], *, prefix: str = "candidate") -> bool:
    if _as_bool(_summary_value(record, prefix, "lock", "locked", "lock_triggered")):
        return True
    decision = _normalized_decision(_summary_value(record, prefix, "decision", "final", "status", "label"))
    return decision == "lock"


def _is_trusted_window(record: Mapping[str, Any]) -> bool:
    for key in ("trusted_window", "post_unlock_trusted", "trusted_owner", "owner_trusted", "trusted"):
        if key in record:
            return _as_bool(record.get(key))
    return _record_truth_is_owner(record)


def _has_warning(record: Mapping[str, Any]) -> bool:
    for key in ("warning", "warning_shown", "warning_triggered", "would_warn"):
        if key in record:
            return _as_bool(record.get(key))
    decision = _normalized_decision(_first_present(record, "decision", "final", "status"))
    return decision in {"warning", "lock"}


def _has_simulated_false_lock(record: Mapping[str, Any]) -> bool:
    for key in ("simulated_false_lock", "would_false_lock", "false_lock", "candidate_false_lock"):
        if key in record:
            return _as_bool(record.get(key))
    return _record_truth_is_owner(record) and _decision_is_lock(record, prefix="candidate")


def _is_unknown_decision(record: Mapping[str, Any]) -> bool:
    for key in ("unknown", "abstained", "candidate_unknown"):
        if key in record:
            return _as_bool(record.get(key))
    decision = _normalized_decision(_first_present(record, "decision", "final", "status", "candidate_decision", "candidate_final", "candidate_status"))
    return decision == "unknown"


def _quality_known(record: Mapping[str, Any]) -> bool:
    return any(key in record for key in ("feature_quality_ok", "quality_ok", "feature_quality_score", "quality_score", "low_quality"))


def _quality_good(record: Mapping[str, Any]) -> bool:
    if "low_quality" in record:
        return not _as_bool(record.get("low_quality"))
    for key in ("feature_quality_ok", "quality_ok"):
        if key in record:
            return _as_bool(record.get(key))
    score = _first_present(record, "feature_quality_score", "quality_score")
    try:
        return float(score) >= 0.50
    except (TypeError, ValueError):
        return False


def _safe_rate(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator > 0 else 0.0


def compute_model_agreement_metrics(
    model_comparison_windows: Sequence[Mapping[str, Any]] | None,
) -> tuple[ModelAgreementMetrics, int]:
    """Compute aggregate candidate/baseline agreement from summary windows."""

    comparable = 0
    matches = 0
    trusted_total = 0
    trusted_matches = 0
    critical_disagreements = 0
    high_risk_disagreements = 0
    for record in _coerce_records(model_comparison_windows):
        assert_privacy_safe_payload(record)
        candidate = _normalized_decision(_summary_value(record, "candidate", "decision", "final", "status", "label"))
        baseline = _normalized_decision(_summary_value(record, "baseline", "decision", "final", "status", "label"))
        if candidate == "unknown" and baseline == "unknown":
            continue
        comparable += 1
        matched = candidate == baseline
        if matched:
            matches += 1
        trusted = _is_trusted_window(record)
        if trusted:
            trusted_total += 1
            if matched:
                trusted_matches += 1
        if not matched:
            critical = _as_bool(record.get("critical")) or _as_bool(record.get("critical_disagreement"))
            critical = critical or (trusted and (_decision_is_lock(record, prefix="candidate") != _decision_is_lock(record, prefix="baseline")))
            if critical:
                critical_disagreements += 1
            high_risk = _as_bool(record.get("high_risk")) or _as_bool(record.get("high_risk_disagreement"))
            high_risk = high_risk or (_decision_is_warning_or_lock(record, prefix="candidate") != _decision_is_warning_or_lock(record, prefix="baseline"))
            if high_risk:
                high_risk_disagreements += 1
    return (
        ModelAgreementMetrics(
            overall_agreement_rate=_safe_rate(matches, comparable),
            trusted_window_agreement_rate=_safe_rate(trusted_matches, trusted_total),
            critical_disagreement_count=critical_disagreements,
            high_risk_disagreement_count=high_risk_disagreements,
        ),
        comparable,
    )


def compute_post_unlock_evidence_metrics(
    post_unlock_windows: Sequence[Mapping[str, Any]] | None,
) -> PostUnlockEvidenceMetrics:
    """Compute trusted post-unlock aggregate metrics from summary windows."""

    trusted = 0
    warnings = 0
    false_locks = 0
    quality_known = 0
    quality_good = 0
    for record in _coerce_records(post_unlock_windows):
        assert_privacy_safe_payload(record)
        if not _is_trusted_window(record):
            continue
        trusted += 1
        if _has_warning(record):
            warnings += 1
        if _has_simulated_false_lock(record):
            false_locks += 1
        if _quality_known(record):
            quality_known += 1
            if _quality_good(record):
                quality_good += 1
    return PostUnlockEvidenceMetrics(
        trusted_window_count=trusted,
        warning_rate=_safe_rate(warnings, trusted),
        simulated_false_locks=false_locks,
        feature_quality_rate=_safe_rate(quality_good, quality_known) if quality_known else 0.0,
    )


def compute_confirmed_intruder_evidence_metrics(
    confirmed_intruder_events: Sequence[Mapping[str, Any]] | None,
    *,
    low_risk_threshold: float = 0.35,
) -> ConfirmedIntruderEvidenceMetrics:
    """Count confirmed intruders and candidate-low-risk intruder failures."""

    if confirmed_intruder_events is None:
        return ConfirmedIntruderEvidenceMetrics(available=False)
    total = 0
    low_risk = 0
    for record in _coerce_records(confirmed_intruder_events):
        assert_privacy_safe_payload(record)
        if not _record_truth_is_intruder(record):
            continue
        total += 1
        if _decision_is_low_risk(record, prefix="candidate", threshold=low_risk_threshold):
            low_risk += 1
    return ConfirmedIntruderEvidenceMetrics(
        available=True,
        confirmed_intruder_count=total,
        confirmed_intruder_low_risk_count=low_risk,
    )


def compute_runtime_safety_metrics(
    runtime_decision_summaries: Sequence[Mapping[str, Any]] | None,
) -> tuple[RuntimeSafetyMetrics, int, int]:
    """Compute aggregate runtime safety from decision summaries.

    Returns metrics, decision_count, and feature_quality_known_count so missing
    source data can remain partial instead of being fabricated as passing.
    """

    decisions = 0
    unknown = 0
    false_locks = 0
    quality_known = 0
    quality_good = 0
    for record in _coerce_records(runtime_decision_summaries):
        assert_privacy_safe_payload(record)
        decisions += 1
        if _is_unknown_decision(record):
            unknown += 1
        if _has_simulated_false_lock(record):
            false_locks += 1
        if _quality_known(record):
            quality_known += 1
            if _quality_good(record):
                quality_good += 1
    low_quality_rate = 1.0 - _safe_rate(quality_good, quality_known) if quality_known else 0.0
    return (
        RuntimeSafetyMetrics(
            simulated_false_lock_count=false_locks,
            unknown_rate=_safe_rate(unknown, decisions),
            low_quality_decision_rate=low_quality_rate,
        ),
        decisions,
        quality_known,
    )


def build_production_evidence_report(
    *,
    candidate_artifact_digest: str = "",
    baseline_artifact_digest: str = "",
    evaluation_report_digest: str = "",
    runtime_schema_version: str = "",
    model_comparison_windows: Sequence[Mapping[str, Any]] | None = None,
    post_unlock_windows: Sequence[Mapping[str, Any]] | None = None,
    confirmed_intruder_events: Sequence[Mapping[str, Any]] | None = None,
    runtime_decision_summaries: Sequence[Mapping[str, Any]] | None = None,
    thresholds: ProductionEvidenceThresholds | None = None,
) -> ProductionEvidenceReport:
    """Build a privacy-safe Production Evidence Gate v2 report from summaries.

    The builder is deterministic and side-effect free. It consumes aggregate
    decision/window summaries only, refuses raw behavioral fields, and produces
    an evidence-only result. It does not call model policy, mutate production
    approval, alter runtime validation, or unlock Protected Sessions.
    """

    limits = thresholds or ProductionEvidenceThresholds()
    model_agreement, model_samples = compute_model_agreement_metrics(model_comparison_windows)
    post_unlock = compute_post_unlock_evidence_metrics(post_unlock_windows)
    intruder = compute_confirmed_intruder_evidence_metrics(
        confirmed_intruder_events,
        low_risk_threshold=limits.low_risk_threshold,
    )
    runtime_safety, runtime_decision_count, runtime_quality_known_count = compute_runtime_safety_metrics(runtime_decision_summaries)

    feature_quality_rate = 1.0 - runtime_safety.low_quality_decision_rate if runtime_quality_known_count else post_unlock.feature_quality_rate
    post_unlock = PostUnlockEvidenceMetrics(
        trusted_window_count=post_unlock.trusted_window_count,
        warning_rate=post_unlock.warning_rate,
        simulated_false_locks=post_unlock.simulated_false_locks,
        feature_quality_rate=feature_quality_rate,
    )

    reason_codes: list[str] = []
    hard_block = False
    partial = False

    if model_samples < limits.min_model_agreement_samples:
        partial = True
        reason_codes.append(ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT)
    elif model_agreement.overall_agreement_rate < limits.min_overall_agreement_rate:
        partial = True
        reason_codes.append(ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT)
    if model_samples >= limits.min_model_agreement_samples and model_agreement.trusted_window_agreement_rate < limits.min_trusted_window_agreement_rate:
        partial = True
        reason_codes.append(ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT)
    if model_agreement.critical_disagreement_count > 0:
        hard_block = True
        reason_codes.append(ProductionEvidenceReasonCode.CRITICAL_MODEL_DISAGREEMENT)
    if model_agreement.high_risk_disagreement_count > 0:
        hard_block = True
        reason_codes.append(ProductionEvidenceReasonCode.HIGH_RISK_MODEL_DISAGREEMENT)

    if post_unlock.trusted_window_count < limits.min_post_unlock_trusted_windows:
        partial = True
        reason_codes.append(ProductionEvidenceReasonCode.INSUFFICIENT_POST_UNLOCK_EVIDENCE)
    if post_unlock.simulated_false_locks > 0:
        hard_block = True
        reason_codes.append(ProductionEvidenceReasonCode.POST_UNLOCK_FALSE_LOCK_DETECTED)

    if not intruder.available:
        partial = True
        reason_codes.append(ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PARTIAL)
    if intruder.confirmed_intruder_low_risk_count > 0:
        hard_block = True
        reason_codes.append(ProductionEvidenceReasonCode.CONFIRMED_INTRUDER_LOW_RISK)

    if runtime_decision_count <= 0:
        partial = True
        reason_codes.append(ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PARTIAL)
    if runtime_safety.simulated_false_lock_count > 0:
        hard_block = True
        reason_codes.append(ProductionEvidenceReasonCode.SIMULATED_FALSE_LOCK_DETECTED)
    if runtime_safety.unknown_rate > limits.max_unknown_rate:
        partial = True
        reason_codes.append(ProductionEvidenceReasonCode.UNKNOWN_RATE_TOO_HIGH)
    if runtime_quality_known_count <= 0 or feature_quality_rate < limits.min_feature_quality_rate:
        partial = True
        reason_codes.append(ProductionEvidenceReasonCode.FEATURE_QUALITY_TOO_LOW)

    if hard_block:
        status = ProductionEvidenceStatus.FAIL
        effect = ProductionEvidencePromotionEffect.BLOCKED
        reason_codes.append(ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_FAILED)
    elif partial:
        status = ProductionEvidenceStatus.PARTIAL
        effect = ProductionEvidencePromotionEffect.SHADOW_ONLY
        reason_codes.append(ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PARTIAL)
    else:
        status = ProductionEvidenceStatus.PASS
        effect = ProductionEvidencePromotionEffect.PRODUCTION_ELIGIBLE
        reason_codes.append(ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PASSED)

    normalized_reason_codes = normalize_reason_codes(reason_codes)
    return ProductionEvidenceReport(
        candidate_artifact_digest=candidate_artifact_digest,
        baseline_artifact_digest=baseline_artifact_digest,
        evaluation_report_digest=evaluation_report_digest,
        runtime_schema_version=runtime_schema_version,
        model_agreement=model_agreement,
        post_unlock_evidence=post_unlock,
        confirmed_intruder_evidence=intruder,
        runtime_safety=runtime_safety,
        gate=ProductionEvidenceGateResult(
            status=status,
            promotion_effect=effect,
            reason_codes=normalized_reason_codes,
        ),
    )


def build_production_evidence_report_from_summaries(
    summaries: Mapping[str, Any] | None,
    *,
    thresholds: ProductionEvidenceThresholds | None = None,
) -> ProductionEvidenceReport:
    """Build evidence from a combined summaries mapping when callers have one.

    Missing keys remain missing evidence. This helper intentionally accepts only
    summary lists and digest strings; raw behavioral fields are rejected by the
    same privacy guard as the direct builder.
    """

    data = _as_mapping(summaries)
    assert_privacy_safe_payload(data)
    model_windows = data["model_comparison_windows"] if "model_comparison_windows" in data else data.get("shadow_comparison_windows") if "shadow_comparison_windows" in data else data.get("shadow_windows")
    post_unlock = data["post_unlock_windows"] if "post_unlock_windows" in data else data.get("post_unlock_evidence")
    intruders = data["confirmed_intruder_events"] if "confirmed_intruder_events" in data else data.get("confirmed_intruder_evidence")
    runtime_decisions = data["runtime_decision_summaries"] if "runtime_decision_summaries" in data else data.get("runtime_safety_decisions") if "runtime_safety_decisions" in data else data.get("runtime_decisions")
    return build_production_evidence_report(
        candidate_artifact_digest=_as_string(data.get("candidate_artifact_digest")),
        baseline_artifact_digest=_as_string(data.get("baseline_artifact_digest")),
        evaluation_report_digest=_as_string(data.get("evaluation_report_digest")),
        runtime_schema_version=_as_string(data.get("runtime_schema_version")),
        model_comparison_windows=model_windows,
        post_unlock_windows=post_unlock,
        confirmed_intruder_events=intruders,
        runtime_decision_summaries=runtime_decisions,
        thresholds=thresholds,
    )
