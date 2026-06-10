from __future__ import annotations

import math
from typing import Dict

CONTEXT_LABELS = ("keyboard_heavy", "mouse_heavy", "mixed", "short_session")
CONTEXT_ROUTING_QUALITY_STATES = ("stable", "idle", "low_quality", "short_session")

KEYBOARD_HEAVY_SHARE_THRESHOLD = 0.70
MOUSE_HEAVY_SHARE_THRESHOLD = 0.70
HEAVY_DOMINANCE_MARGIN_THRESHOLD = 0.18
MIN_FULL_WINDOW_COVERAGE_RATIO = 0.82
MIN_ROUTABLE_WINDOW_EVENTS = 60.0
IDLE_EVENTS_PER_SECOND_THRESHOLD = 0.15
IDLE_EVENT_COUNT_THRESHOLD = 12.0
LOW_QUALITY_ACTIVITY_SUPPORT_THRESHOLD = 0.18



def _context_clamp01(value: float) -> float:
    try:
        number = float(value)
    except Exception:
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    return float(min(1.0, max(0.0, number)))


def _find_primary_context_prefix(feature_map: Dict[str, float]) -> str:
    candidates: list[tuple[float, str]] = []
    for key, value in feature_map.items():
        if not key.startswith("scale_") or not key.endswith("_requested_seconds"):
            continue
        prefix = key[: -len("_requested_seconds")]
        active_value = float(feature_map.get(f"{prefix}_active", 0.0) or 0.0)
        if active_value < 0.5:
            continue
        try:
            requested = float(value)
        except Exception:
            requested = 0.0
        candidates.append((requested, prefix))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[-1][1]


def _context_value(feature_map: Dict[str, float], prefix: str, base_key: str) -> float:
    if prefix:
        key = f"{prefix}_{base_key}"
        if key in feature_map:
            return float(feature_map.get(key, 0.0) or 0.0)
    return float(feature_map.get(base_key, 0.0) or 0.0)


def extract_context_router_features(sample: Dict[str, float]) -> Dict[str, float]:
    feature_map = {str(key): float(value or 0.0) for key, value in dict(sample or {}).items()}
    prefix = _find_primary_context_prefix(feature_map)
    requested_scales = [float(value or 0.0) for key, value in feature_map.items() if str(key).startswith("scale_") and str(key).endswith("_requested_seconds")]
    max_requested_seconds = max(requested_scales) if requested_scales else float(feature_map.get("window_seconds", 0.0) or 0.0)
    scale_coverage = float(feature_map.get("multiscale_scale_coverage", 1.0) or 1.0)
    active_scale_count = float(feature_map.get("multiscale_active_scale_count", 1.0) or 1.0)
    requested_scale_count = float(feature_map.get("multiscale_requested_scale_count", active_scale_count) or active_scale_count)
    return {
        "primary_scale_prefix": prefix,
        "window_seconds": _context_value(feature_map, prefix, "window_seconds"),
        "requested_seconds": _context_value(feature_map, prefix, "requested_seconds") or max_requested_seconds,
        "window_total_events": _context_value(feature_map, prefix, "window_total_events"),
        "session_events_per_sec": _context_value(feature_map, prefix, "session_events_per_sec"),
        "session_kb_share": _context_value(feature_map, prefix, "session_kb_share"),
        "session_ms_share": _context_value(feature_map, prefix, "session_ms_share"),
        "session_modality_switch_ratio": _context_value(feature_map, prefix, "session_modality_switch_ratio"),
        "scale_coverage": scale_coverage,
        "active_scale_count": active_scale_count,
        "requested_scale_count": requested_scale_count,
        "max_requested_seconds": float(max_requested_seconds),
    }


def _context_reason_codes(
    *,
    context: str,
    routing_quality: str,
    kb_share: float,
    ms_share: float,
    dominance_margin: float,
    events_per_sec: float,
    total_events: float,
    window_seconds: float,
    requested_seconds: float,
    scale_coverage: float,
) -> list[str]:
    reasons: list[str] = [f"context_{context}", f"routing_quality_{routing_quality}"]
    if routing_quality == "idle":
        reasons.append("idle_or_near_empty_window")
    elif routing_quality == "low_quality":
        reasons.append("insufficient_routing_evidence")
    elif routing_quality == "short_session":
        reasons.append("short_or_partial_window")
    if kb_share >= KEYBOARD_HEAVY_SHARE_THRESHOLD:
        reasons.append("keyboard_share_high")
    if ms_share >= MOUSE_HEAVY_SHARE_THRESHOLD:
        reasons.append("mouse_share_high")
    if dominance_margin >= HEAVY_DOMINANCE_MARGIN_THRESHOLD:
        reasons.append("dominant_modality_margin_met")
    else:
        reasons.append("dominant_modality_margin_not_met")
    if events_per_sec <= IDLE_EVENTS_PER_SECOND_THRESHOLD:
        reasons.append("very_low_activity_rate")
    if total_events < MIN_ROUTABLE_WINDOW_EVENTS:
        reasons.append("below_min_routable_events")
    if requested_seconds > 0.0 and window_seconds < (MIN_FULL_WINDOW_COVERAGE_RATIO * requested_seconds):
        reasons.append("window_coverage_short")
    if scale_coverage < 0.999:
        reasons.append("partial_scale_coverage")
    return list(dict.fromkeys(reasons))


def classify_behavior_context(sample: Dict[str, float]) -> Dict[str, float | str | list[str]]:
    features = extract_context_router_features(sample)
    kb_share = _context_clamp01(features["session_kb_share"])
    ms_share = _context_clamp01(features["session_ms_share"])
    modality_switch_ratio = _context_clamp01(features["session_modality_switch_ratio"])
    events_per_sec = max(0.0, float(features["session_events_per_sec"]))
    window_seconds = max(0.0, float(features["window_seconds"]))
    total_events = max(0.0, float(features["window_total_events"]))
    scale_coverage = _context_clamp01(features["scale_coverage"])
    max_requested_seconds = max(0.0, float(features["max_requested_seconds"]))
    dominance_margin = abs(kb_share - ms_share)
    activity_support = _context_clamp01(events_per_sec / 12.0)

    idle_like = bool(
        total_events <= 0.0
        or (window_seconds >= 8.0 and total_events <= IDLE_EVENT_COUNT_THRESHOLD)
        or (window_seconds >= 8.0 and events_per_sec <= IDLE_EVENTS_PER_SECOND_THRESHOLD)
    )
    low_quality = bool(
        not idle_like
        and (
            total_events < MIN_ROUTABLE_WINDOW_EVENTS
            or (window_seconds >= 8.0 and activity_support < LOW_QUALITY_ACTIVITY_SUPPORT_THRESHOLD)
        )
    )

    is_short = False
    if max_requested_seconds > 0.0 and window_seconds < (MIN_FULL_WINDOW_COVERAGE_RATIO * max_requested_seconds):
        is_short = True
    if scale_coverage < 0.999 and window_seconds < max_requested_seconds:
        is_short = True
    if total_events <= 90.0 and window_seconds <= 8.0:
        is_short = True

    routing_quality = "stable"
    if idle_like:
        # Keep idle windows on the non-production short_session route so callers
        # cannot accidentally train or lock on near-empty behavioral evidence.
        confidence = _context_clamp01(0.64 + 0.18 * (1.0 - activity_support))
        context = "short_session"
        routing_quality = "idle"
    elif low_quality:
        # Low-quality windows remain deterministic and explainable, but route to
        # the safe fallback path instead of a context-specific production model.
        confidence = _context_clamp01(0.58 + 0.14 * (1.0 - activity_support))
        context = "short_session"
        routing_quality = "low_quality"
    elif is_short:
        confidence = _context_clamp01(0.58 + 0.24 * (1.0 - scale_coverage) + 0.10 * (1.0 - activity_support))
        context = "short_session"
        routing_quality = "short_session"
    elif kb_share >= KEYBOARD_HEAVY_SHARE_THRESHOLD and dominance_margin >= HEAVY_DOMINANCE_MARGIN_THRESHOLD:
        confidence = _context_clamp01(0.50 + 0.28 * dominance_margin + 0.18 * activity_support)
        context = "keyboard_heavy"
    elif ms_share >= MOUSE_HEAVY_SHARE_THRESHOLD and dominance_margin >= HEAVY_DOMINANCE_MARGIN_THRESHOLD:
        confidence = _context_clamp01(0.50 + 0.28 * dominance_margin + 0.18 * activity_support)
        context = "mouse_heavy"
    else:
        confidence = _context_clamp01(0.46 + 0.20 * (1.0 - dominance_margin) + 0.14 * modality_switch_ratio + 0.12 * activity_support)
        context = "mixed"

    reason_codes = _context_reason_codes(
        context=context,
        routing_quality=routing_quality,
        kb_share=kb_share,
        ms_share=ms_share,
        dominance_margin=dominance_margin,
        events_per_sec=events_per_sec,
        total_events=total_events,
        window_seconds=window_seconds,
        requested_seconds=max_requested_seconds,
        scale_coverage=scale_coverage,
    )

    return {
        "context": context,
        "confidence": round(float(confidence), 6),
        "keyboard_share": round(float(kb_share), 6),
        "mouse_share": round(float(ms_share), 6),
        "events_per_second": round(float(events_per_sec), 6),
        "modality_switch_ratio": round(float(modality_switch_ratio), 6),
        "window_seconds": round(float(window_seconds), 6),
        "window_total_events": round(float(total_events), 6),
        "scale_coverage": round(float(scale_coverage), 6),
        "routing_quality": routing_quality,
        "dominance_margin": round(float(dominance_margin), 6),
        "reason_codes": reason_codes,
    }
