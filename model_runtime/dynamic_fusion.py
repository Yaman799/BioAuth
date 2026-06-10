"""Quality-aware Dynamic Fusion v1 helpers.

Commercial-Core-10 contract:
- production runtime remains the only owner of final enforcement;
- Dynamic Fusion v1 is transparent and conservative;
- it can reduce over-confident risk/probability when modality evidence is weak;
- it must never increase risk, change thresholds, trigger locks, or touch session state.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

import numpy as np

from features import extract_context_router_features
from model_metadata import MIN_WINDOW_EVENTS

DYNAMIC_FUSION_POLICY_VERSION = "commercial-core-10-dynamic-fusion-v1"
DYNAMIC_FUSION_DEFAULT_ENABLED = True


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    if not np.isfinite(number):
        return float(default)
    return float(number)


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    number = _safe_float(value, low)
    return float(min(float(high), max(float(low), number)))


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    return bool(default)


def _config_enabled(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "n", "off", "disabled"}:
            return False
    return bool(default)


def dynamic_fusion_v1_enabled(*, metadata: Mapping[str, Any] | None = None, settings: Mapping[str, Any] | None = None) -> bool:
    """Return whether Dynamic Fusion v1 is enabled for runtime scoring.

    Commercial default is enabled. It can be disabled by emergency env flag,
    app settings, or runtime metadata. The function is intentionally tiny and
    side-effect free so tests and release gates can reason about it.
    """

    if _env_flag("BIOAUTH_DISABLE_DYNAMIC_FUSION_V1"):
        return False
    enabled = DYNAMIC_FUSION_DEFAULT_ENABLED
    for source in (_as_mapping(settings), _as_mapping(metadata)):
        config = source.get("dynamic_fusion_v1")
        if isinstance(config, Mapping) and "enabled" in config:
            enabled = _config_enabled(config.get("enabled"), default=enabled)
        elif "dynamic_fusion_v1_enabled" in source:
            enabled = _config_enabled(source.get("dynamic_fusion_v1_enabled"), default=enabled)
    return bool(enabled)


def _modality_weights(keyboard_share: float, mouse_share: float, context_name: str, route_confidence: float) -> tuple[float, float]:
    kb = max(0.0, float(keyboard_share))
    ms = max(0.0, float(mouse_share))
    total = kb + ms
    if total <= 1e-9:
        return 0.5, 0.5
    kb_weight = kb / total
    mouse_weight = ms / total
    # Keep weights interpretable, but acknowledge a confident context route.
    context = str(context_name or "").strip().lower()
    boost = 0.10 * _clamp(route_confidence)
    if context == "keyboard_heavy":
        kb_weight = min(1.0, kb_weight + boost)
        mouse_weight = max(0.0, 1.0 - kb_weight)
    elif context == "mouse_heavy":
        mouse_weight = min(1.0, mouse_weight + boost)
        kb_weight = max(0.0, 1.0 - mouse_weight)
    return round(float(kb_weight), 6), round(float(mouse_weight), 6)


def _context_fit(*, context_name: str, keyboard_share: float, mouse_share: float, modality_switch_ratio: float) -> float:
    context = str(context_name or "").strip().lower()
    if context == "keyboard_heavy":
        return _clamp((keyboard_share - 0.45) / 0.45)
    if context == "mouse_heavy":
        return _clamp((mouse_share - 0.45) / 0.45)
    if context in {"mixed", "balanced", "hybrid"}:
        balance = 1.0 - abs(float(keyboard_share) - float(mouse_share))
        return _clamp(0.60 * balance + 0.40 * _clamp(modality_switch_ratio / 0.25))
    # Unknown contexts get neutral support. The route confidence still matters.
    return 0.60


def _record_for_window(
    *,
    sample: Mapping[str, Any],
    route: Mapping[str, Any],
    used_context: str,
    risk_value: float,
    classifier_prob: float | None,
    enabled: bool,
) -> dict[str, Any]:
    router_features = extract_context_router_features(dict(sample or {}))
    context_name = str((route or {}).get("context") or "")
    route_confidence = _clamp((route or {}).get("confidence"))
    keyboard_share = _clamp(router_features.get("session_kb_share"))
    mouse_share = _clamp(router_features.get("session_ms_share"))
    modality_switch_ratio = _clamp(router_features.get("session_modality_switch_ratio"))
    event_count = _safe_float(router_features.get("window_total_events"))
    scale_coverage = _clamp(router_features.get("scale_coverage"), 0.0, 1.0)
    transition_flag = bool(_safe_float(sample.get("transition_flag")) >= 0.5)
    session_start_flag = bool(_safe_float(sample.get("transition_session_start_flag")) >= 0.5)
    post_idle_flag = bool(_safe_float(sample.get("transition_post_idle_flag")) >= 0.5)

    event_support = _clamp(event_count / max(24.0, float(MIN_WINDOW_EVENTS) * 1.5))
    context_fit = _context_fit(
        context_name=context_name,
        keyboard_share=keyboard_share,
        mouse_share=mouse_share,
        modality_switch_ratio=modality_switch_ratio,
    )
    routed_context = str(used_context or "").strip().lower()
    route_support = route_confidence if routed_context and routed_context != "global_fallback" else route_confidence * 0.85
    transition_support = 0.0 if (transition_flag or session_start_flag or post_idle_flag) else 1.0
    evidence_confidence = _clamp(
        0.32 * event_support
        + 0.20 * scale_coverage
        + 0.18 * route_support
        + 0.20 * context_fit
        + 0.10 * transition_support
    )

    reason_codes: list[str] = []
    if not enabled:
        reason_codes.append("dynamic_fusion_disabled")
    if event_count <= max(12.0, float(MIN_WINDOW_EVENTS)):
        reason_codes.append("low_event_count")
        evidence_confidence = min(evidence_confidence, 0.42)
    if scale_coverage < 0.98:
        reason_codes.append("partial_scale_coverage")
        evidence_confidence = min(evidence_confidence, 0.70)
    if transition_flag:
        reason_codes.append("transition_window")
        evidence_confidence = min(evidence_confidence, 0.48)
    if session_start_flag:
        reason_codes.append("startup_window")
        evidence_confidence = min(evidence_confidence, 0.48)
    if post_idle_flag:
        reason_codes.append("post_idle_window")
        evidence_confidence = min(evidence_confidence, 0.48)

    extreme_keyboard = keyboard_share >= 0.95 and mouse_share <= 0.05
    extreme_mouse = mouse_share >= 0.95 and keyboard_share <= 0.05
    if (extreme_keyboard or extreme_mouse) and routed_context == "global_fallback" and route_confidence >= 0.80:
        reason_codes.append("single_modality_global_fallback")
        evidence_confidence = min(evidence_confidence, 0.62)

    risk_before = _safe_float(risk_value)
    prob_before = None if classifier_prob is None else _clamp(classifier_prob)
    risk_after = risk_before
    prob_after = prob_before
    applied = False
    if enabled:
        # Conservative cap: never amplifies risk; only limits over-confident risk
        # when the evidence supporting the current modality mix is weak.
        cap = 42.0 + 58.0 * evidence_confidence
        if risk_before > 45.0 and risk_before > cap:
            risk_after = float(cap)
            applied = True
            reason_codes.append("dynamic_fusion_quality_cap")
        if prob_before is not None:
            prob_cap = 0.25 + 0.75 * evidence_confidence
            if prob_before > prob_cap:
                prob_after = float(prob_cap)
                applied = True
                reason_codes.append("dynamic_fusion_probability_cap")

    keyboard_weight, mouse_weight = _modality_weights(keyboard_share, mouse_share, context_name, route_confidence)
    return {
        "policy_version": DYNAMIC_FUSION_POLICY_VERSION,
        "enabled": bool(enabled),
        "applied": bool(applied),
        "reason_codes": list(dict.fromkeys(reason_codes or ["evidence_confidence_ok"])),
        "context": context_name,
        "used_context": str(used_context or ""),
        "route_confidence": round(float(route_confidence), 6),
        "keyboard_share": round(float(keyboard_share), 6),
        "mouse_share": round(float(mouse_share), 6),
        "keyboard_weight": float(keyboard_weight),
        "mouse_weight": float(mouse_weight),
        "modality_switch_ratio": round(float(modality_switch_ratio), 6),
        "event_count": int(round(event_count)),
        "scale_coverage": round(float(scale_coverage), 6),
        "evidence_confidence": round(float(evidence_confidence), 6),
        "risk_before": round(float(risk_before), 6),
        "risk_after": round(float(risk_after), 6),
        "classifier_prob_before": round(float(prob_before), 6) if prob_before is not None else None,
        "classifier_prob_after": round(float(prob_after), 6) if prob_after is not None else None,
    }


def apply_dynamic_fusion_v1(
    *,
    window_samples: Sequence[Mapping[str, Any]],
    route_records: Sequence[Mapping[str, Any]] | None,
    used_contexts: Sequence[str] | None,
    risk_values: Sequence[Any],
    classifier_probs: Sequence[Any | None] | None,
    metadata: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply transparent quality-aware fusion to runtime window scores.

    The returned ``risk_values`` and ``classifier_probs`` are safe replacements
    for the incoming traces. Values are never increased. A per-window record is
    returned for diagnostics and support bundles.
    """

    enabled = dynamic_fusion_v1_enabled(metadata=metadata, settings=settings)
    samples = [dict(item or {}) for item in list(window_samples or [])]
    risks = [_safe_float(value) for value in list(risk_values or [])]
    probs_raw = list(classifier_probs or [])
    records: list[dict[str, Any]] = []
    out_risks: list[float] = []
    out_probs: list[float | None] = []
    route_items = list(route_records or [])
    used_items = list(used_contexts or [])
    for index, sample in enumerate(samples):
        risk_value = risks[index] if index < len(risks) else 0.0
        prob_value = probs_raw[index] if index < len(probs_raw) else None
        route = route_items[index] if index < len(route_items) and isinstance(route_items[index], Mapping) else {}
        used_context = str(used_items[index]) if index < len(used_items) else ""
        record = _record_for_window(
            sample=sample,
            route=route,
            used_context=used_context,
            risk_value=risk_value,
            classifier_prob=prob_value,
            enabled=enabled,
        )
        records.append(record)
        out_risks.append(float(record.get("risk_after") if enabled else record.get("risk_before") or 0.0))
        after_prob = record.get("classifier_prob_after") if enabled else record.get("classifier_prob_before")
        out_probs.append(float(after_prob) if after_prob is not None else None)

    applied_count = sum(1 for record in records if bool(record.get("applied")))
    avg_confidence = 0.0
    if records:
        avg_confidence = float(sum(_safe_float(record.get("evidence_confidence")) for record in records) / len(records))
    capped_count = sum(1 for record in records if "dynamic_fusion_quality_cap" in set(record.get("reason_codes") or []))
    prob_capped_count = sum(1 for record in records if "dynamic_fusion_probability_cap" in set(record.get("reason_codes") or []))
    return {
        "enabled": bool(enabled),
        "policy_version": DYNAMIC_FUSION_POLICY_VERSION,
        "risk_values": out_risks,
        "classifier_probs": out_probs,
        "records": records,
        "summary": {
            "enabled": bool(enabled),
            "policy_version": DYNAMIC_FUSION_POLICY_VERSION,
            "window_count": int(len(records)),
            "applied_window_count": int(applied_count),
            "risk_capped_window_count": int(capped_count),
            "probability_capped_window_count": int(prob_capped_count),
            "average_evidence_confidence": round(float(avg_confidence), 6),
            "non_increasing_risk_guarantee": True,
            "can_lock": False,
            "can_change_threshold": False,
            "can_change_model_pointer": False,
        },
    }
