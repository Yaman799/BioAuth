"""Transition-window training helpers extracted in Phase 7.

This module owns the transition-focused window filtering policy and related
metadata constants so the legacy ``model_training`` facade can stay slim while
keeping the same helper names available.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np

from features import annotate_sequence_trend_windows, annotate_transition_windows

SEQUENCE_FEATURES_VERSION = "phase8-sequence-v1"
TRANSITION_POLICY_VERSION = "phase7-transition-v1"
TRANSITION_KEEP_RATIO = 0.75
TRANSITION_MIN_KEEP_WINDOWS = 1
TRANSITION_SESSION_START_SECONDS = 10.0
TRANSITION_POST_IDLE_GAP_SECONDS = 8.0
TRANSITION_ACTIVITY_SHIFT_THRESHOLD = 0.42


def _evenly_spaced_indices(total: int, keep_count: int) -> List[int]:
    total = max(0, int(total))
    keep_count = max(0, int(keep_count))
    if keep_count >= total:
        return list(range(total))
    if keep_count <= 0 or total <= 0:
        return []
    return sorted({int(round(value)) for value in np.linspace(0, total - 1, num=keep_count)})


def _apply_transition_window_policy(window_samples: List[Dict[str, float]], *, label: int) -> Tuple[List[Dict[str, float]], Dict[str, Any]]:
    annotated = annotate_transition_windows([dict(sample or {}) for sample in window_samples])
    total_windows = int(len(annotated))
    transition_indices = [idx for idx, sample in enumerate(annotated) if float(sample.get("transition_flag", 0.0) or 0.0) >= 0.5]
    transition_index_set = set(transition_indices)
    settled_indices = [idx for idx in range(total_windows) if idx not in transition_index_set]
    transition_count = int(len(transition_indices))
    prevalence = float(transition_count / total_windows) if total_windows > 0 else 0.0

    kept_transition_indices = list(transition_indices)
    if transition_count >= 3 and total_windows > 1:
        keep_count = max(TRANSITION_MIN_KEEP_WINDOWS, int(np.ceil(transition_count * TRANSITION_KEEP_RATIO)))
        keep_count = min(transition_count, keep_count)
        if keep_count < transition_count:
            positions = _evenly_spaced_indices(transition_count, keep_count)
            kept_transition_indices = [transition_indices[pos] for pos in positions]

    kept_indices = sorted(set(settled_indices + kept_transition_indices))
    filtered = annotate_sequence_trend_windows([annotated[idx] for idx in kept_indices])
    if not filtered and annotated:
        filtered = [annotated[-1]]

    kept_transition_windows = int(sum(1 for sample in filtered if float(sample.get("transition_flag", 0.0) or 0.0) >= 0.5))
    removed_transition_windows = int(max(0, transition_count - kept_transition_windows))
    summary = {
        "total_windows": total_windows,
        "transition_windows": transition_count,
        "settled_windows": int(total_windows - transition_count),
        "transition_prevalence": round(prevalence, 6),
        "kept_windows": int(len(filtered)),
        "kept_transition_windows": kept_transition_windows,
        "removed_transition_windows": removed_transition_windows,
        "session_start_transition_windows": int(sum(1 for sample in annotated if float(sample.get("transition_session_start_flag", 0.0) or 0.0) >= 0.5)),
        "post_idle_transition_windows": int(sum(1 for sample in annotated if float(sample.get("transition_post_idle_flag", 0.0) or 0.0) >= 0.5)),
        "max_transition_strength": round(float(max(((sample.get("transition_strength", 0.0) or 0.0) for sample in annotated), default=0.0)), 6),
        "label": int(label),
        "keep_ratio": float(TRANSITION_KEEP_RATIO),
    }
    return filtered, summary



def _summarize_transition_training(session_stats: List[Dict[str, Any]]) -> Dict[str, Any]:
    positive = [item for item in session_stats if int(item.get("label", 0) or 0) == 0]
    negative = [item for item in session_stats if int(item.get("label", 0) or 0) == 1]

    def _aggregate(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = int(sum(int(item.get("total_windows", 0) or 0) for item in items))
        transition = int(sum(int(item.get("transition_windows", 0) or 0) for item in items))
        kept = int(sum(int(item.get("kept_windows", 0) or 0) for item in items))
        kept_transition = int(sum(int(item.get("kept_transition_windows", 0) or 0) for item in items))
        removed_transition = int(sum(int(item.get("removed_transition_windows", 0) or 0) for item in items))
        return {
            "session_count": int(len(items)),
            "total_windows": total,
            "transition_windows": transition,
            "transition_prevalence": round(float(transition / total) if total > 0 else 0.0, 6),
            "kept_windows": kept,
            "kept_transition_windows": kept_transition,
            "removed_transition_windows": removed_transition,
        }

    return {
        "version": TRANSITION_POLICY_VERSION,
        "enabled": True,
        "keep_ratio": float(TRANSITION_KEEP_RATIO),
        "minimum_kept_transition_windows_per_session": int(TRANSITION_MIN_KEEP_WINDOWS),
        "session_start_seconds": float(TRANSITION_SESSION_START_SECONDS),
        "post_idle_gap_seconds": float(TRANSITION_POST_IDLE_GAP_SECONDS),
        "activity_shift_threshold": float(TRANSITION_ACTIVITY_SHIFT_THRESHOLD),
        "positive": _aggregate(positive),
        "negative": _aggregate(negative),
        "all_sessions": _aggregate(session_stats),
    }


__all__ = [
    "SEQUENCE_FEATURES_VERSION",
    "TRANSITION_ACTIVITY_SHIFT_THRESHOLD",
    "TRANSITION_KEEP_RATIO",
    "TRANSITION_MIN_KEEP_WINDOWS",
    "TRANSITION_POLICY_VERSION",
    "TRANSITION_POST_IDLE_GAP_SECONDS",
    "TRANSITION_SESSION_START_SECONDS",
    "_apply_transition_window_policy",
    "_evenly_spaced_indices",
    "_summarize_transition_training",
]
