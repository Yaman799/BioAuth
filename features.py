"""Legacy compatibility facade for BioAuth feature extraction.

Phase 10 moves the implementation into the ``feature_extractors`` package while
keeping this module as the stable import surface for the rest of the project and
existing tests.
"""

from __future__ import annotations

from feature_extractors import (
    CONTEXT_LABELS,
    CONTEXT_ROUTING_QUALITY_STATES,
    DEFAULT_MIN_WINDOW_EVENTS,
    DEFAULT_WINDOW_SECONDS,
    DEFAULT_WINDOW_STEP_SECONDS,
    KB_DEFAULT_TAIL_ROWS,
    MAX_DWELL_SECONDS,
    MAX_FLIGHT_SECONDS,
    MAX_MOUSE_GAP_SECONDS,
    MS_DEFAULT_TAIL_ROWS,
    SEQUENCE_FEATURES_VERSION,
    SEQUENCE_TREND_LOOKBACK,
    TRANSITION_ACTIVITY_SHIFT_THRESHOLD,
    TRANSITION_POST_IDLE_GAP_SECONDS,
    TRANSITION_SESSION_START_SECONDS,
    annotate_sequence_trend_windows,
    annotate_transition_windows,
    classify_behavior_context,
    extract_combined_features,
    extract_context_router_features,
    extract_keyboard_features,
    extract_mouse_features,
    extract_multi_scale_window_feature_samples,
    extract_session_quality_indicators,
    extract_window_feature_samples,
)
from feature_extractors.common import (
    _activity_ratio,
    _combined_per_second_event_counts,
    _duration_from_timestamps,
    _finite_array,
    _safe_ratio,
    _sanitize_frame,
    _stats_template,
    _timing_deltas,
    _value_stats,
)
from feature_extractors.context import _context_clamp01, _context_value, _find_primary_context_prefix
from feature_extractors.sequence import _sequence_primary_prefix, _sequence_value, _transition_primary_prefix, _transition_value
from feature_extractors.windows import _combined_sorted_timestamps, _pre_window_idle_gap_seconds, _prefix_feature_values, _scale_label, _slice_frame

__all__ = [
    "CONTEXT_LABELS",
    "CONTEXT_ROUTING_QUALITY_STATES",
    "DEFAULT_MIN_WINDOW_EVENTS",
    "DEFAULT_WINDOW_SECONDS",
    "DEFAULT_WINDOW_STEP_SECONDS",
    "KB_DEFAULT_TAIL_ROWS",
    "MAX_DWELL_SECONDS",
    "MAX_FLIGHT_SECONDS",
    "MAX_MOUSE_GAP_SECONDS",
    "MS_DEFAULT_TAIL_ROWS",
    "SEQUENCE_FEATURES_VERSION",
    "SEQUENCE_TREND_LOOKBACK",
    "TRANSITION_ACTIVITY_SHIFT_THRESHOLD",
    "TRANSITION_POST_IDLE_GAP_SECONDS",
    "TRANSITION_SESSION_START_SECONDS",
    "annotate_sequence_trend_windows",
    "annotate_transition_windows",
    "classify_behavior_context",
    "extract_combined_features",
    "extract_context_router_features",
    "extract_keyboard_features",
    "extract_mouse_features",
    "extract_multi_scale_window_feature_samples",
    "extract_session_quality_indicators",
    "extract_window_feature_samples",
]
