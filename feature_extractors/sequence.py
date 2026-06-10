from __future__ import annotations

from typing import Dict, List

import numpy as np

from .common import _safe_ratio
from .context import _context_clamp01, _find_primary_context_prefix

TRANSITION_SESSION_START_SECONDS = 10.0
TRANSITION_POST_IDLE_GAP_SECONDS = 8.0
TRANSITION_ACTIVITY_SHIFT_THRESHOLD = 0.42
SEQUENCE_FEATURES_VERSION = "phase8-sequence-v1"
SEQUENCE_TREND_LOOKBACK = 2


def _transition_primary_prefix(sample: Dict[str, float]) -> str:
    if "multiscale_requested_scale_count" in sample or any(str(key).startswith("scale_") for key in sample.keys()):
        return _find_primary_context_prefix(sample)
    return ""


def _transition_value(sample: Dict[str, float], prefix: str, base_key: str) -> float:
    if prefix:
        prefixed = f"{prefix}_{base_key}"
        if prefixed in sample:
            return float(sample.get(prefixed, 0.0) or 0.0)
    return float(sample.get(base_key, 0.0) or 0.0)


def annotate_transition_windows(samples: List[Dict[str, float]]) -> List[Dict[str, float]]:
    if not samples:
        return []
    annotated: List[Dict[str, float]] = []
    previous_event_rate: float | None = None
    previous_kb_share: float | None = None
    previous_ms_share: float | None = None
    for index, original in enumerate(samples):
        sample = dict(original or {})
        prefix = _transition_primary_prefix(sample)
        start_offset = max(0.0, _transition_value(sample, prefix, "start_offset") or sample.get("window_start_offset", 0.0))
        end_offset = max(start_offset, _transition_value(sample, prefix, "end_offset") or sample.get("window_end_offset", start_offset))
        window_seconds = max(1e-6, _transition_value(sample, prefix, "window_seconds") or max(1e-6, end_offset - start_offset))
        requested_seconds = max(window_seconds, _transition_value(sample, prefix, "requested_seconds") or window_seconds)
        total_events = max(0.0, _transition_value(sample, prefix, "window_total_events"))
        event_rate = _transition_value(sample, prefix, "session_events_per_sec")
        if event_rate <= 0.0:
            event_rate = _safe_ratio(total_events, window_seconds)
        kb_share = _context_clamp01(_transition_value(sample, prefix, "session_kb_share"))
        ms_share = _context_clamp01(_transition_value(sample, prefix, "session_ms_share"))
        idle_gap = max(
            0.0,
            _transition_value(sample, prefix, "pre_window_idle_gap_seconds") or sample.get("pre_window_idle_gap_seconds", 0.0),
        )

        session_start_flag = 1.0 if start_offset <= TRANSITION_SESSION_START_SECONDS else 0.0
        post_idle_flag = 1.0 if idle_gap >= TRANSITION_POST_IDLE_GAP_SECONDS else 0.0
        short_support = 1.0 if window_seconds < (requested_seconds * 0.75) else 0.0

        if previous_event_rate is None:
            activity_shift_score = 0.0
        else:
            rate_delta = abs(event_rate - previous_event_rate) / max(1.0, previous_event_rate)
            modality_delta = abs(kb_share - (previous_kb_share or 0.0)) + abs(ms_share - (previous_ms_share or 0.0))
            activity_shift_score = _context_clamp01(0.72 * rate_delta + 0.28 * modality_delta)

        transition_strength = _context_clamp01(
            0.38 * session_start_flag
            + 0.46 * post_idle_flag
            + 0.36 * max(0.0, activity_shift_score - TRANSITION_ACTIVITY_SHIFT_THRESHOLD)
            + 0.16 * short_support
        )
        transition_flag = 1.0 if (
            session_start_flag >= 0.5
            or post_idle_flag >= 0.5
            or activity_shift_score >= TRANSITION_ACTIVITY_SHIFT_THRESHOLD
            or transition_strength >= 0.5
        ) else 0.0

        sample["transition_window_index"] = float(index)
        sample["transition_session_start_flag"] = session_start_flag
        sample["transition_post_idle_flag"] = post_idle_flag
        sample["transition_activity_shift_score"] = round(float(activity_shift_score), 6)
        sample["transition_short_support_flag"] = short_support
        sample["transition_strength"] = round(float(transition_strength), 6)
        sample["transition_flag"] = transition_flag
        sample["transition_settled_flag"] = 0.0 if transition_flag >= 0.5 else 1.0
        sample["transition_start_offset"] = round(float(start_offset), 6)
        sample["transition_end_offset"] = round(float(end_offset), 6)
        sample["transition_pre_window_idle_gap_seconds"] = round(float(idle_gap), 6)
        sample["transition_event_rate"] = round(float(event_rate), 6)
        annotated.append(sample)

        previous_event_rate = event_rate
        previous_kb_share = kb_share
        previous_ms_share = ms_share
    return annotated


def _sequence_primary_prefix(sample: Dict[str, float]) -> str:
    return _transition_primary_prefix(sample)


def _sequence_value(sample: Dict[str, float], prefix: str, base_key: str) -> float:
    return _transition_value(sample, prefix, base_key)


def annotate_sequence_trend_windows(samples: List[Dict[str, float]], lookback: int = SEQUENCE_TREND_LOOKBACK) -> List[Dict[str, float]]:
    if not samples:
        return []
    lookback_count = max(1, int(lookback or 1))
    annotated: List[Dict[str, float]] = []
    previous_rates: List[float] = []
    previous_samples: List[Dict[str, float]] = []
    for index, original in enumerate(samples):
        sample = dict(original or {})
        prefix = _sequence_primary_prefix(sample)
        window_seconds = max(1e-6, _sequence_value(sample, prefix, "window_seconds"))
        total_events = max(0.0, _sequence_value(sample, prefix, "window_total_events"))
        event_rate = _sequence_value(sample, prefix, "session_events_per_sec")
        if event_rate <= 0.0:
            event_rate = _safe_ratio(total_events, window_seconds)
        kb_share = _context_clamp01(_sequence_value(sample, prefix, "session_kb_share"))
        ms_share = _context_clamp01(_sequence_value(sample, prefix, "session_ms_share"))
        modality_switch_ratio = _context_clamp01(_sequence_value(sample, prefix, "session_modality_switch_ratio"))
        start_offset = max(0.0, _sequence_value(sample, prefix, "start_offset") or sample.get("window_start_offset", 0.0) or sample.get("transition_start_offset", 0.0))
        prev_sample = previous_samples[-1] if previous_samples else None
        if prev_sample is None:
            prev_event_rate = 0.0
            prev_kb_share = 0.0
            prev_ms_share = 0.0
            prev_switch_ratio = 0.0
            prev_transition_flag = 0.0
            prev_end_offset = start_offset
        else:
            prev_prefix = _sequence_primary_prefix(prev_sample)
            prev_event_rate = _sequence_value(prev_sample, prev_prefix, "session_events_per_sec")
            if prev_event_rate <= 0.0:
                prev_window_seconds = max(1e-6, _sequence_value(prev_sample, prev_prefix, "window_seconds"))
                prev_event_rate = _safe_ratio(_sequence_value(prev_sample, prev_prefix, "window_total_events"), prev_window_seconds)
            prev_kb_share = _context_clamp01(_sequence_value(prev_sample, prev_prefix, "session_kb_share"))
            prev_ms_share = _context_clamp01(_sequence_value(prev_sample, prev_prefix, "session_ms_share"))
            prev_switch_ratio = _context_clamp01(_sequence_value(prev_sample, prev_prefix, "session_modality_switch_ratio"))
            prev_transition_flag = 1.0 if float(prev_sample.get("transition_flag", 0.0) or 0.0) >= 0.5 else 0.0
            prev_end_offset = max(start_offset, _sequence_value(prev_sample, prev_prefix, "end_offset") or prev_sample.get("window_end_offset", 0.0) or prev_sample.get("transition_end_offset", start_offset))
        recent_rates = previous_rates[-lookback_count:]
        mean_prev_rate = float(np.mean(recent_rates)) if recent_rates else prev_event_rate
        oldest_recent_rate = float(recent_rates[0]) if recent_rates else prev_event_rate
        prior_velocity = float(recent_rates[-1] - recent_rates[-2]) if len(recent_rates) >= 2 else 0.0
        current_velocity = float(event_rate - prev_event_rate) if previous_samples else 0.0
        trend_delta_vs_mean = float(event_rate - mean_prev_rate) if previous_samples else 0.0
        acceleration = float(current_velocity - prior_velocity) if len(recent_rates) >= 2 else 0.0
        consistency_score = _context_clamp01(1.0 - (abs(trend_delta_vs_mean) / max(1.0, abs(mean_prev_rate)))) if previous_samples else 1.0
        inter_window_gap = max(0.0, float(start_offset - prev_end_offset)) if previous_samples else 0.0
        sample["adjacent_has_history"] = 1.0 if previous_samples else 0.0
        sample["adjacent_lookback_count"] = float(min(len(previous_rates), lookback_count))
        sample["adjacent_prev_event_rate"] = round(float(prev_event_rate), 6)
        sample["adjacent_delta_event_rate"] = round(float(event_rate - prev_event_rate), 6) if previous_samples else 0.0
        sample["adjacent_delta_kb_share"] = round(float(kb_share - prev_kb_share), 6) if previous_samples else 0.0
        sample["adjacent_delta_ms_share"] = round(float(ms_share - prev_ms_share), 6) if previous_samples else 0.0
        sample["adjacent_delta_modality_switch_ratio"] = round(float(modality_switch_ratio - prev_switch_ratio), 6) if previous_samples else 0.0
        sample["adjacent_inter_window_gap_seconds"] = round(float(inter_window_gap), 6)
        sample["adjacent_prev_transition_flag"] = float(prev_transition_flag)
        sample["trend_mean_prev2_event_rate"] = round(float(mean_prev_rate), 6) if previous_samples else 0.0
        sample["trend_delta_vs_mean_prev2"] = round(float(trend_delta_vs_mean), 6)
        sample["trend_velocity_prev2"] = round(float(event_rate - oldest_recent_rate), 6) if previous_samples else 0.0
        sample["trend_current_velocity"] = round(float(current_velocity), 6)
        sample["trend_acceleration"] = round(float(acceleration), 6)
        sample["trend_consistency_score"] = round(float(consistency_score), 6)
        sample["sequence_window_index"] = float(index)
        annotated.append(sample)
        previous_rates.append(float(event_rate))
        previous_samples.append(sample)
    return annotated
