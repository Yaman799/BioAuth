"""Feature extraction package for BioAuth.

This package is the stable Phase 10 home for feature extraction internals while
`features.py` remains the legacy facade module.
"""

from .combined import extract_combined_features, extract_session_quality_indicators
from .conservative_v2 import CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION
from .common import (
    DEFAULT_MIN_WINDOW_EVENTS,
    DEFAULT_WINDOW_SECONDS,
    DEFAULT_WINDOW_STEP_SECONDS,
    KB_DEFAULT_TAIL_ROWS,
    MAX_DWELL_SECONDS,
    MAX_FLIGHT_SECONDS,
    MAX_MOUSE_GAP_SECONDS,
    MS_DEFAULT_TAIL_ROWS,
)
from .context import CONTEXT_LABELS, CONTEXT_ROUTING_QUALITY_STATES, classify_behavior_context, extract_context_router_features
from .keyboard import extract_keyboard_features
from .mouse import extract_mouse_features
from .sequence import (
    SEQUENCE_FEATURES_VERSION,
    SEQUENCE_TREND_LOOKBACK,
    TRANSITION_ACTIVITY_SHIFT_THRESHOLD,
    TRANSITION_POST_IDLE_GAP_SECONDS,
    TRANSITION_SESSION_START_SECONDS,
    annotate_sequence_trend_windows,
    annotate_transition_windows,
)
from .windows import extract_multi_scale_window_feature_samples, extract_window_feature_samples

__all__ = [
    "CONTEXT_LABELS",
    "CONTEXT_ROUTING_QUALITY_STATES",
    "CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION",
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
