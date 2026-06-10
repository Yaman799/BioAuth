"""Runtime window diagnostics helpers.

Structure-only split from model_inference.py. These functions intentionally keep
the legacy private names because model_inference imports them as compatibility
wrappers. Do not put scoring or feature schema changes here.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

import numpy as np

from features import extract_context_router_features
from model_metadata import MIN_WINDOW_EVENTS


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    if not np.isfinite(number):
        return float(default)
    return float(number)

def _clamp01(value: Any) -> float:
    return float(min(1.0, max(0.0, _safe_float(value))))

def _sample_metric(sample: Mapping[str, Any], prefix: str, base_key: str, default: float = 0.0) -> float:
    if prefix:
        prefixed = f"{prefix}_{base_key}"
        if prefixed in sample:
            return _safe_float(sample.get(prefixed), default)
    return _safe_float(sample.get(base_key), default)

def _window_quality_profile(
    *,
    sample: Mapping[str, Any],
    router_features: Mapping[str, Any],
    route: Mapping[str, Any],
    event_count: float,
    window_seconds: float,
    requested_seconds: float,
    scale_coverage: float,
    transition_flag: bool,
    session_start_flag: bool,
    post_idle_flag: bool,
) -> Dict[str, Any]:
    prefix = str(router_features.get("primary_scale_prefix") or "")
    kb_share = _clamp01(router_features.get("session_kb_share"))
    mouse_share = _clamp01(router_features.get("session_ms_share"))
    route_confidence = _clamp01((route or {}).get("confidence"))
    longest_pause = max(
        _sample_metric(sample, prefix, "kb_longest_pause"),
        _sample_metric(sample, prefix, "ms_longest_pause"),
    )
    pre_idle_gap = max(
        _safe_float(sample.get("pre_window_idle_gap_seconds")),
        _sample_metric(sample, prefix, "pre_window_idle_gap_seconds"),
        _safe_float(sample.get("transition_pre_window_idle_gap_seconds")),
    )
    idle_ratio = _clamp01(max(longest_pause, pre_idle_gap) / max(1.0, window_seconds))
    event_support = _clamp01(event_count / max(24.0, float(MIN_WINDOW_EVENTS) * 1.5))
    duration_support = 1.0 if requested_seconds <= 0.0 else _clamp01(window_seconds / max(1.0, requested_seconds))
    scale_support = _clamp01(scale_coverage)
    modality_balance = _clamp01(1.0 - abs(kb_share - mouse_share))
    balance_support = max(0.45, modality_balance)
    transition_penalty = 0.0
    if transition_flag:
        transition_penalty += 0.10
    if session_start_flag:
        transition_penalty += 0.08
    if post_idle_flag:
        transition_penalty += 0.08

    quality_score = _clamp01(
        0.28 * event_support
        + 0.18 * duration_support
        + 0.16 * scale_support
        + 0.18 * (1.0 - idle_ratio)
        + 0.10 * balance_support
        + 0.10 * route_confidence
        - transition_penalty
    )

    quality_reasons: list[str] = []
    if event_count <= max(12.0, float(MIN_WINDOW_EVENTS)):
        quality_reasons.append("low_event_count")
    if idle_ratio >= 0.68:
        quality_reasons.append("high_idle_ratio")
    if session_start_flag:
        quality_reasons.append("startup_window")
    if post_idle_flag:
        quality_reasons.append("post_idle_window")
    if transition_flag:
        quality_reasons.append("transition_window")

    quality_ok = bool(quality_score >= 0.55 and "low_event_count" not in quality_reasons and "high_idle_ratio" not in quality_reasons)
    quality_lock_ok = bool(quality_ok and not any(code in quality_reasons for code in {"startup_window", "post_idle_window", "transition_window"}))
    if not quality_lock_ok:
        quality_reasons.append("insufficient_evidence")

    return {
        "quality_score": round(float(quality_score), 6),
        "quality_ok": bool(quality_ok),
        "quality_lock_ok": bool(quality_lock_ok),
        "idle_ratio": round(float(idle_ratio), 6),
        "keyboard_mouse_balance": round(float(modality_balance), 6),
        "context_confidence": round(float(route_confidence), 6),
        "quality_reason_codes": list(dict.fromkeys(quality_reasons)),
    }

def _window_quality_summary(diagnostics: list[Mapping[str, Any]]) -> Dict[str, Any]:
    items = [dict(item or {}) for item in diagnostics]
    count = len(items)
    quality_ok_count = sum(1 for item in items if bool(item.get("quality_ok")))
    lock_quality_ok_count = sum(1 for item in items if bool(item.get("quality_lock_ok")))
    low_quality_count = count - quality_ok_count
    blocked_reasons: list[str] = []
    for item in items:
        if bool(item.get("quality_lock_ok")):
            continue
        for code in list(item.get("quality_reason_codes") or item.get("reason_codes") or []):
            if code in {"insufficient_evidence", "low_event_count", "high_idle_ratio", "startup_window", "post_idle_window", "transition_window"}:
                blocked_reasons.append(str(code))
    avg_quality = 0.0
    if items:
        avg_quality = float(sum(_safe_float(item.get("quality_score")) for item in items) / len(items))
    return {
        "window_count": int(count),
        "quality_ok_window_count": int(quality_ok_count),
        "quality_lock_ok_window_count": int(lock_quality_ok_count),
        "low_quality_window_count": int(low_quality_count),
        "average_quality_score": round(float(avg_quality), 6),
        "lock_quality_allowed": bool(lock_quality_ok_count > 0),
        "blocked_reason_codes": list(dict.fromkeys(blocked_reasons)),
    }

def _quality_gate_status(summary: Mapping[str, Any] | None) -> Dict[str, Any]:
    quality = dict((summary or {}).get("quality") or {})
    if int(quality.get("window_count") or 0) <= 0:
        return {"applied": False, "status": "ok", "reason": "no_window_diagnostics"}
    if bool(quality.get("lock_quality_allowed")):
        return {"applied": False, "status": "ok", "reason": "quality_lock_window_available"}
    reasons = list(quality.get("blocked_reason_codes") or ["insufficient_evidence"])
    return {
        "applied": True,
        "status": "insufficient_evidence",
        "reason": "+".join(str(code) for code in reasons[:4]) or "insufficient_evidence",
    }

def _window_feature_counts(sample: Mapping[str, Any]) -> tuple[int, int]:
    numeric_values = []
    for value in dict(sample or {}).values():
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if not np.isfinite(number):
            continue
        numeric_values.append(number)
    nonzero_count = sum(1 for number in numeric_values if abs(number) > 1e-9)
    return int(len(numeric_values)), int(nonzero_count)

def _window_reason_codes(*, risk_value: float, classifier_prob: float | None, event_count: float, window_seconds: float, requested_seconds: float, scale_coverage: float, transition_flag: bool, session_start_flag: bool, post_idle_flag: bool) -> list[str]:
    reasons: list[str] = []
    if risk_value >= 80.0:
        reasons.append('severe_risk')
    elif risk_value >= 60.0:
        reasons.append('high_risk')
    elif risk_value >= 40.0:
        reasons.append('elevated_risk')
    if classifier_prob is not None and float(classifier_prob) >= 0.70:
        reasons.append('high_classifier_prob')
    if event_count <= max(12.0, float(MIN_WINDOW_EVENTS)):
        reasons.append('low_event_count')
    if requested_seconds > 0.0 and window_seconds < requested_seconds * 0.82:
        reasons.append('short_window')
    if scale_coverage < 0.999:
        reasons.append('partial_scale_coverage')
    if transition_flag:
        reasons.append('transition_window')
    if session_start_flag:
        reasons.append('startup_window')
        reasons.append('session_start_window')
    if post_idle_flag:
        reasons.append('post_idle_window')
    return reasons

def _mouse_fallback_guard_profile(
    *,
    sample: Mapping[str, Any],
    route: Mapping[str, Any],
    used_context: str,
) -> dict[str, Any]:
    router_features = extract_context_router_features(dict(sample or {}))
    context_name = str((route or {}).get("context") or "")
    route_confidence = _safe_float((route or {}).get("confidence"), 0.0)
    keyboard_share = _safe_float(router_features.get("session_kb_share"))
    mouse_share = _safe_float(router_features.get("session_ms_share"))
    modality_switch_ratio = _safe_float(router_features.get("session_modality_switch_ratio"))
    scale_coverage = _safe_float(router_features.get("scale_coverage"), 1.0)
    event_count = _safe_float(router_features.get("window_total_events"))
    transition_flag = bool(_safe_float(sample.get("transition_flag")) >= 0.5)
    session_start_flag = bool(_safe_float(sample.get("transition_session_start_flag")) >= 0.5)
    post_idle_flag = bool(_safe_float(sample.get("transition_post_idle_flag")) >= 0.5)
    active = (
        context_name == "mouse_heavy"
        and str(used_context or "") == "global_fallback"
        and route_confidence >= 0.85
        and keyboard_share <= 0.03
        and mouse_share >= 0.95
        and modality_switch_ratio <= 0.05
        and scale_coverage >= 0.99
        and event_count >= max(60.0, float(MIN_WINDOW_EVENTS))
        and not transition_flag
        and not session_start_flag
        and not post_idle_flag
    )
    return {
        "active": bool(active),
        "context": context_name,
        "route_confidence": round(route_confidence, 6),
        "keyboard_share": round(keyboard_share, 3),
        "mouse_share": round(mouse_share, 3),
        "modality_switch_ratio": round(modality_switch_ratio, 3),
        "scale_coverage": round(scale_coverage, 3),
        "event_count": int(round(event_count)),
        "transition_flag": bool(transition_flag),
        "session_start_flag": bool(session_start_flag),
        "post_idle_flag": bool(post_idle_flag),
        "reason": "mouse_heavy_global_fallback_guard" if active else "not_applicable",
    }

def _apply_mouse_fallback_guard(
    *,
    risk_value: float,
    classifier_prob: float | None,
    guard_profile: Mapping[str, Any],
) -> tuple[float, float | None, dict[str, Any]]:
    risk_before = _safe_float(risk_value)
    prob_before = None if classifier_prob is None else _safe_float(classifier_prob)
    if not bool((guard_profile or {}).get("active")):
        return risk_before, prob_before, {
            "applied": False,
            "reason": str((guard_profile or {}).get("reason") or ""),
            "risk_before": round(risk_before, 2),
            "risk_after": round(risk_before, 2),
            "classifier_prob_before": round(prob_before, 6) if prob_before is not None else None,
            "classifier_prob_after": round(prob_before, 6) if prob_before is not None else None,
        }

    adjusted_risk = min(risk_before, 24.0 + max(0.0, risk_before - 24.0) * 0.35)
    adjusted_prob = prob_before
    if prob_before is not None:
        adjusted_prob = min(prob_before, 0.18 + max(0.0, prob_before - 0.18) * 0.45)
    return adjusted_risk, adjusted_prob, {
        "applied": True,
        "reason": "mouse_heavy_global_fallback_guard",
        "risk_before": round(risk_before, 2),
        "risk_after": round(adjusted_risk, 2),
        "classifier_prob_before": round(prob_before, 6) if prob_before is not None else None,
        "classifier_prob_after": round(adjusted_prob, 6) if adjusted_prob is not None else None,
    }

def _build_window_diagnostics(
    samples: list[Mapping[str, Any]],
    *,
    raw_values: list[float],
    risk_values: list[float],
    classifier_probs: list[float | None],
    route_records: list[Mapping[str, Any]],
    used_contexts: list[str],
    base_risk_values: list[float] | None = None,
    base_classifier_probs: list[float | None] | None = None,
    guard_records: list[Mapping[str, Any]] | None = None,
    dynamic_fusion_records: list[Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        router_features = extract_context_router_features(dict(sample or {}))
        numeric_feature_count, nonzero_feature_count = _window_feature_counts(sample)
        route = dict(route_records[index] or {}) if index < len(route_records) else {}
        classifier_prob = classifier_probs[index] if index < len(classifier_probs) else None
        risk_value = _safe_float(risk_values[index] if index < len(risk_values) else 0.0)
        raw_value = _safe_float(raw_values[index] if index < len(raw_values) else 0.0)
        base_risk_value = _safe_float((base_risk_values[index] if base_risk_values is not None and index < len(base_risk_values) else risk_value), risk_value)
        base_classifier_prob = (base_classifier_probs[index] if base_classifier_probs is not None and index < len(base_classifier_probs) else classifier_prob)
        guard_record = dict(guard_records[index] or {}) if guard_records is not None and index < len(guard_records) else {}
        dynamic_record = dict(dynamic_fusion_records[index] or {}) if dynamic_fusion_records is not None and index < len(dynamic_fusion_records) else {}
        window_seconds = _safe_float(router_features.get('window_seconds'))
        requested_seconds = _safe_float(router_features.get('requested_seconds'), window_seconds)
        event_count = _safe_float(router_features.get('window_total_events'))
        transition_flag = bool(_safe_float(sample.get('transition_flag')) >= 0.5)
        session_start_flag = bool(_safe_float(sample.get('transition_session_start_flag')) >= 0.5)
        post_idle_flag = bool(_safe_float(sample.get('transition_post_idle_flag')) >= 0.5)
        scale_coverage = _safe_float(router_features.get('scale_coverage'), 1.0)
        reason_codes = _window_reason_codes(
            risk_value=risk_value,
            classifier_prob=classifier_prob,
            event_count=event_count,
            window_seconds=window_seconds,
            requested_seconds=requested_seconds,
            scale_coverage=scale_coverage,
            transition_flag=transition_flag,
            session_start_flag=session_start_flag,
            post_idle_flag=post_idle_flag,
        )
        quality_profile = _window_quality_profile(
            sample=sample,
            router_features=router_features,
            route=route,
            event_count=event_count,
            window_seconds=window_seconds,
            requested_seconds=requested_seconds,
            scale_coverage=scale_coverage,
            transition_flag=transition_flag,
            session_start_flag=session_start_flag,
            post_idle_flag=post_idle_flag,
        )
        for code in list(quality_profile.get('quality_reason_codes') or []):
            if code not in reason_codes:
                reason_codes.append(str(code))
        if bool(guard_record.get('applied')) and 'mouse_fallback_guard' not in reason_codes:
            reason_codes.append('mouse_fallback_guard')
        if bool(dynamic_record.get('applied')) and 'dynamic_fusion_quality_cap' not in reason_codes:
            reason_codes.append('dynamic_fusion_quality_cap')
        diagnostics.append({
            'index': int(index),
            'risk': round(risk_value, 2),
            'base_risk': round(base_risk_value, 2),
            'raw_score': round(raw_value, 6),
            'classifier_prob': round(float(classifier_prob), 6) if classifier_prob is not None else None,
            'base_classifier_prob': round(float(base_classifier_prob), 6) if base_classifier_prob is not None else None,
            'guard_applied': bool(guard_record.get('applied')),
            'guard_reason': str(guard_record.get('reason') or ''),
            'context': str(route.get('context') or ''),
            'routing_quality': str(route.get('routing_quality') or ''),
            'routing_reason_codes': list(route.get('reason_codes') or []),
            'route_confidence': round(_safe_float(route.get('confidence')), 6),
            'used_context': str(used_contexts[index]) if index < len(used_contexts) else '',
            'window_seconds': round(window_seconds, 3),
            'requested_seconds': round(requested_seconds, 3),
            'event_count': int(round(event_count)),
            'events_per_second': round(_safe_float(router_features.get('session_events_per_sec')), 3),
            'keyboard_share': round(_safe_float(router_features.get('session_kb_share')), 3),
            'mouse_share': round(_safe_float(router_features.get('session_ms_share')), 3),
            'modality_switch_ratio': round(_safe_float(router_features.get('session_modality_switch_ratio')), 3),
            'scale_coverage': round(scale_coverage, 3),
            'transition_flag': transition_flag,
            'transition_strength': round(_safe_float(sample.get('transition_strength')), 3),
            'session_start_flag': session_start_flag,
            'post_idle_flag': post_idle_flag,
            'start_offset': round(_safe_float(sample.get('window_start_offset') or sample.get('multiscale_anchor_offset')), 3),
            'end_offset': round(_safe_float(sample.get('window_end_offset') or sample.get('multiscale_anchor_offset')), 3),
            'pre_window_idle_gap_seconds': round(_safe_float(sample.get('pre_window_idle_gap_seconds') or sample.get('scale_5s_pre_window_idle_gap_seconds')), 3),
            'numeric_feature_count': int(numeric_feature_count),
            'nonzero_feature_count': int(nonzero_feature_count),
            'reason_codes': list(reason_codes),
            'quality_score': float(quality_profile.get('quality_score', 0.0)),
            'quality_ok': bool(quality_profile.get('quality_ok')),
            'quality_lock_ok': bool(quality_profile.get('quality_lock_ok')),
            'quality_reason_codes': list(quality_profile.get('quality_reason_codes') or []),
            'idle_ratio': float(quality_profile.get('idle_ratio', 0.0)),
            'keyboard_mouse_balance': float(quality_profile.get('keyboard_mouse_balance', 0.0)),
            'context_confidence': float(quality_profile.get('context_confidence', 0.0)),
            'dynamic_fusion_enabled': bool(dynamic_record.get('enabled')),
            'dynamic_fusion_applied': bool(dynamic_record.get('applied')),
            'dynamic_fusion_policy_version': str(dynamic_record.get('policy_version') or ''),
            'dynamic_fusion_evidence_confidence': round(_safe_float(dynamic_record.get('evidence_confidence')), 6),
            'dynamic_fusion_risk_before': round(_safe_float(dynamic_record.get('risk_before'), risk_value), 2),
            'dynamic_fusion_risk_after': round(_safe_float(dynamic_record.get('risk_after'), risk_value), 2),
            'dynamic_fusion_classifier_prob_before': round(_safe_float(dynamic_record.get('classifier_prob_before')), 6) if dynamic_record.get('classifier_prob_before') is not None else None,
            'dynamic_fusion_classifier_prob_after': round(_safe_float(dynamic_record.get('classifier_prob_after')), 6) if dynamic_record.get('classifier_prob_after') is not None else None,
            'dynamic_keyboard_weight': round(_safe_float(dynamic_record.get('keyboard_weight')), 6),
            'dynamic_mouse_weight': round(_safe_float(dynamic_record.get('mouse_weight')), 6),
            'dynamic_fusion_reason_codes': list(dynamic_record.get('reason_codes') or []),
        })

    top_risky = sorted(diagnostics, key=lambda item: (float(item.get('risk') or 0.0), float(item.get('classifier_prob') or 0.0), -int(item.get('index') or 0)), reverse=True)[:3]
    recent = diagnostics[-3:]
    quality_summary = _window_quality_summary(diagnostics)
    summary = {
        'count': int(len(diagnostics)),
        'high_risk_count': int(sum(1 for item in diagnostics if float(item.get('risk') or 0.0) >= 60.0)),
        'severe_risk_count': int(sum(1 for item in diagnostics if float(item.get('risk') or 0.0) >= 80.0)),
        'transition_window_count': int(sum(1 for item in diagnostics if bool(item.get('transition_flag')))),
        'mouse_fallback_guard_count': int(sum(1 for item in diagnostics if bool(item.get('guard_applied')))),
        'dynamic_fusion_applied_count': int(sum(1 for item in diagnostics if bool(item.get('dynamic_fusion_applied')))),
        'quality': quality_summary,
        'quality_ok_window_count': int(quality_summary.get('quality_ok_window_count') or 0),
        'quality_lock_ok_window_count': int(quality_summary.get('quality_lock_ok_window_count') or 0),
        'low_quality_window_count': int(quality_summary.get('low_quality_window_count') or 0),
        'lock_quality_allowed': bool(quality_summary.get('lock_quality_allowed')),
        'top_risky_windows': [
            {
                'index': int(item.get('index') or 0),
                'risk': float(item.get('risk') or 0.0),
                'context': str(item.get('context') or ''),
                'used_context': str(item.get('used_context') or ''),
                'event_count': int(item.get('event_count') or 0),
                'quality_score': float(item.get('quality_score') or 0.0),
                'quality_ok': bool(item.get('quality_ok')),
                'quality_lock_ok': bool(item.get('quality_lock_ok')),
                'reason_codes': list(item.get('reason_codes') or []),
                'guard_applied': bool(item.get('guard_applied')),
                'dynamic_fusion_applied': bool(item.get('dynamic_fusion_applied')),
                'dynamic_fusion_evidence_confidence': float(item.get('dynamic_fusion_evidence_confidence') or 0.0),
                'base_risk': float(item.get('base_risk') or item.get('risk') or 0.0),
            }
            for item in top_risky
        ],
        'recent_windows': [
            {
                'index': int(item.get('index') or 0),
                'risk': float(item.get('risk') or 0.0),
                'context': str(item.get('context') or ''),
                'event_count': int(item.get('event_count') or 0),
                'quality_score': float(item.get('quality_score') or 0.0),
                'quality_ok': bool(item.get('quality_ok')),
                'quality_lock_ok': bool(item.get('quality_lock_ok')),
                'reason_codes': list(item.get('reason_codes') or []),
                'guard_applied': bool(item.get('guard_applied')),
                'dynamic_fusion_applied': bool(item.get('dynamic_fusion_applied')),
                'dynamic_fusion_evidence_confidence': float(item.get('dynamic_fusion_evidence_confidence') or 0.0),
                'base_risk': float(item.get('base_risk') or item.get('risk') or 0.0),
            }
            for item in recent
        ],
    }
    return diagnostics, summary

def _window_diag_brief(summary: Mapping[str, Any] | None) -> str:
    top_windows = list((summary or {}).get('top_risky_windows') or [])
    if not top_windows:
        return 'none'
    parts = []
    for item in top_windows[:3]:
        reasons = list(item.get('reason_codes') or [])
        reason_text = '+'.join(reasons[:2]) if reasons else '-'
        parts.append(f"#{int(item.get('index') or 0)}:r{int(round(float(item.get('risk') or 0.0)))}:{str(item.get('context') or '-') or '-'}:{reason_text}")
    return ' | '.join(parts)
