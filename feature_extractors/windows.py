from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from .combined import extract_combined_features
from .common import (
    DEFAULT_MIN_WINDOW_EVENTS,
    DEFAULT_WINDOW_SECONDS,
    DEFAULT_WINDOW_STEP_SECONDS,
    _safe_ratio,
    _sanitize_frame,
)
from .sequence import annotate_sequence_trend_windows, annotate_transition_windows


def _slice_frame(frame: pd.DataFrame, start_ts: float, end_ts: float) -> pd.DataFrame:
    if frame is None or frame.empty:
        return frame.iloc[0:0].copy()
    return frame.loc[(frame["timestamp"] >= start_ts) & (frame["timestamp"] < end_ts)].copy()


def _combined_sorted_timestamps(kb: pd.DataFrame, ms: pd.DataFrame) -> np.ndarray:
    arrays: list[np.ndarray] = []
    if kb is not None and not kb.empty and "timestamp" in kb.columns:
        arrays.append(pd.to_numeric(kb["timestamp"], errors="coerce").dropna().astype(float).to_numpy())
    if ms is not None and not ms.empty and "timestamp" in ms.columns:
        arrays.append(pd.to_numeric(ms["timestamp"], errors="coerce").dropna().astype(float).to_numpy())
    if not arrays:
        return np.asarray([], dtype=float)
    merged = np.concatenate(arrays).astype(float, copy=False)
    merged = merged[np.isfinite(merged)]
    if merged.size == 0:
        return np.asarray([], dtype=float)
    return np.sort(merged)


def _pre_window_idle_gap_seconds(all_timestamps: np.ndarray, start_ts: float, session_start: float) -> float:
    arr = np.asarray(all_timestamps, dtype=float)
    if arr.size == 0:
        return 0.0
    idx = int(np.searchsorted(arr, float(start_ts), side="left")) - 1
    if idx < 0:
        return float(max(0.0, float(start_ts) - float(session_start)))
    previous_ts = float(arr[idx])
    return float(max(0.0, float(start_ts) - previous_ts))


def extract_window_feature_samples(
    kb: pd.DataFrame,
    ms: pd.DataFrame,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    step_seconds: float = DEFAULT_WINDOW_STEP_SECONDS,
    min_total_events: int = DEFAULT_MIN_WINDOW_EVENTS,
    max_windows: Optional[int] = None,
) -> List[Dict[str, float]]:
    kb_clean = _sanitize_frame(kb, ["timestamp"], tail_rows=None)
    ms_clean = _sanitize_frame(ms, ["timestamp", "x", "y"], tail_rows=None)

    total_events = len(kb_clean) + len(ms_clean)
    if total_events <= 0:
        return []

    min_ts_candidates = []
    max_ts_candidates = []
    if not kb_clean.empty:
        min_ts_candidates.append(float(kb_clean["timestamp"].min()))
        max_ts_candidates.append(float(kb_clean["timestamp"].max()))
    if not ms_clean.empty:
        min_ts_candidates.append(float(ms_clean["timestamp"].min()))
        max_ts_candidates.append(float(ms_clean["timestamp"].max()))

    session_start = min(min_ts_candidates)
    session_end = max(max_ts_candidates)
    total_duration = max(0.0, session_end - session_start)
    all_timestamps = _combined_sorted_timestamps(kb_clean, ms_clean)

    if total_duration <= 0.0 or total_duration <= float(window_seconds):
        if total_events < int(min_total_events):
            return []
        feat = extract_combined_features(kb_clean, ms_clean)
        feat["window_total_events"] = float(total_events)
        feat["window_seconds"] = float(max(total_duration, 1.0))
        feat["window_start_offset"] = 0.0
        feat["window_end_offset"] = float(max(total_duration, 1.0))
        feat["pre_window_idle_gap_seconds"] = 0.0
        return annotate_sequence_trend_windows(annotate_transition_windows([feat]))

    starts = list(np.arange(session_start, max(session_start, session_end - float(window_seconds)) + 1e-6, max(1.0, float(step_seconds))))
    if not starts:
        starts = [max(session_start, session_end - float(window_seconds))]
    if max_windows is not None and max_windows > 0 and len(starts) > int(max_windows):
        starts = starts[-int(max_windows):]

    samples: List[Dict[str, float]] = []
    for start_ts in starts:
        end_ts = min(session_end + 1e-6, start_ts + float(window_seconds))
        kb_win = _slice_frame(kb_clean, start_ts, end_ts)
        ms_win = _slice_frame(ms_clean, start_ts, end_ts)
        event_count = len(kb_win) + len(ms_win)
        if event_count < int(min_total_events):
            continue
        feat = extract_combined_features(kb_win, ms_win)
        feat["window_total_events"] = float(event_count)
        feat["window_seconds"] = float(max(0.0, end_ts - start_ts))
        feat["window_start_offset"] = float(max(0.0, start_ts - session_start))
        feat["window_end_offset"] = float(max(0.0, end_ts - session_start))
        feat["pre_window_idle_gap_seconds"] = _pre_window_idle_gap_seconds(all_timestamps, start_ts, session_start)
        samples.append(feat)

    if not samples and total_events >= int(min_total_events):
        feat = extract_combined_features(kb_clean, ms_clean)
        feat["window_total_events"] = float(total_events)
        feat["window_seconds"] = float(max(total_duration, 1.0))
        feat["window_start_offset"] = 0.0
        feat["window_end_offset"] = float(max(total_duration, 1.0))
        feat["pre_window_idle_gap_seconds"] = 0.0
        samples.append(feat)
    return annotate_sequence_trend_windows(annotate_transition_windows(samples))


def _scale_label(scale_seconds: float) -> str:
    value = float(scale_seconds)
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value))}s"
    return f"{str(value).replace('.', '_')}s"


def _prefix_feature_values(prefix: str, values: Dict[str, float]) -> Dict[str, float]:
    return {f"{prefix}_{key}": float(value) for key, value in values.items()}


def extract_multi_scale_window_feature_samples(
    kb: pd.DataFrame,
    ms: pd.DataFrame,
    window_scales: Optional[Iterable[float]] = None,
    step_seconds: float = DEFAULT_WINDOW_STEP_SECONDS,
    min_total_events: int = DEFAULT_MIN_WINDOW_EVENTS,
    max_windows: Optional[int] = None,
) -> List[Dict[str, float]]:
    kb_clean = _sanitize_frame(kb, ["timestamp"], tail_rows=None)
    ms_clean = _sanitize_frame(ms, ["timestamp", "x", "y"], tail_rows=None)

    total_events = len(kb_clean) + len(ms_clean)
    if total_events <= 0:
        return []

    scales = sorted({float(scale) for scale in (window_scales or [DEFAULT_WINDOW_SECONDS]) if float(scale) > 0.0})
    if not scales:
        scales = [float(DEFAULT_WINDOW_SECONDS)]

    min_ts_candidates = []
    max_ts_candidates = []
    if not kb_clean.empty:
        min_ts_candidates.append(float(kb_clean["timestamp"].min()))
        max_ts_candidates.append(float(kb_clean["timestamp"].max()))
    if not ms_clean.empty:
        min_ts_candidates.append(float(ms_clean["timestamp"].min()))
        max_ts_candidates.append(float(ms_clean["timestamp"].max()))

    session_start = min(min_ts_candidates)
    session_end = max(max_ts_candidates)
    total_duration = max(0.0, session_end - session_start)
    all_timestamps = _combined_sorted_timestamps(kb_clean, ms_clean)
    anchor_step = max(1.0, float(step_seconds))
    first_anchor = session_end if total_duration <= 0.0 else min(session_end, session_start + min(scales))
    anchors = list(np.arange(first_anchor, session_end + 1e-6, anchor_step))
    if not anchors:
        anchors = [session_end]
    elif anchors[-1] < session_end - 1e-6:
        anchors.append(session_end)

    deduped_anchors: List[float] = []
    for anchor in anchors:
        anchor_value = float(anchor)
        if deduped_anchors and abs(deduped_anchors[-1] - anchor_value) <= 1e-6:
            continue
        deduped_anchors.append(anchor_value)
    anchors = deduped_anchors

    if max_windows is not None and max_windows > 0 and len(anchors) > int(max_windows):
        anchors = anchors[-int(max_windows):]

    samples: List[Dict[str, float]] = []
    for anchor_end in anchors:
        sample: Dict[str, float] = {
            "multiscale_anchor_end": float(anchor_end),
            "multiscale_anchor_offset": float(max(0.0, anchor_end - session_start)),
            "multiscale_active_scale_count": 0.0,
            "multiscale_requested_scale_count": float(len(scales)),
        }
        active_scales = 0
        for scale in scales:
            label = _scale_label(scale)
            prefix = f"scale_{label}"
            start_ts = max(session_start, float(anchor_end) - float(scale))
            end_ts = min(session_end + 1e-6, float(anchor_end) + 1e-6)
            kb_win = _slice_frame(kb_clean, start_ts, end_ts)
            ms_win = _slice_frame(ms_clean, start_ts, end_ts)
            event_count = len(kb_win) + len(ms_win)
            actual_seconds = float(max(0.0, end_ts - start_ts))
            sample[f"{prefix}_requested_seconds"] = float(scale)
            sample[f"{prefix}_window_total_events"] = float(event_count)
            sample[f"{prefix}_window_seconds"] = actual_seconds
            sample[f"{prefix}_start_offset"] = float(max(0.0, start_ts - session_start))
            sample[f"{prefix}_end_offset"] = float(max(0.0, end_ts - session_start))
            sample[f"{prefix}_pre_window_idle_gap_seconds"] = _pre_window_idle_gap_seconds(all_timestamps, start_ts, session_start)
            is_active = event_count >= int(min_total_events)
            sample[f"{prefix}_active"] = 1.0 if is_active else 0.0
            if not is_active:
                continue
            active_scales += 1
            sample.update(_prefix_feature_values(prefix, extract_combined_features(kb_win, ms_win)))
        if active_scales <= 0:
            continue
        sample["multiscale_active_scale_count"] = float(active_scales)
        sample["multiscale_scale_coverage"] = _safe_ratio(active_scales, len(scales))
        samples.append(sample)

    if not samples and total_events >= int(min_total_events):
        fallback_anchor = float(session_end)
        fallback_sample: Dict[str, float] = {
            "multiscale_anchor_end": fallback_anchor,
            "multiscale_anchor_offset": float(max(0.0, fallback_anchor - session_start)),
            "multiscale_active_scale_count": 0.0,
            "multiscale_requested_scale_count": float(len(scales)),
        }
        active_scales = 0
        for scale in scales:
            label = _scale_label(scale)
            prefix = f"scale_{label}"
            start_ts = max(session_start, fallback_anchor - float(scale))
            end_ts = session_end + 1e-6
            kb_win = _slice_frame(kb_clean, start_ts, end_ts)
            ms_win = _slice_frame(ms_clean, start_ts, end_ts)
            event_count = len(kb_win) + len(ms_win)
            actual_seconds = float(max(0.0, end_ts - start_ts))
            fallback_sample[f"{prefix}_requested_seconds"] = float(scale)
            fallback_sample[f"{prefix}_window_total_events"] = float(event_count)
            fallback_sample[f"{prefix}_window_seconds"] = actual_seconds
            fallback_sample[f"{prefix}_start_offset"] = float(max(0.0, start_ts - session_start))
            fallback_sample[f"{prefix}_end_offset"] = float(max(0.0, end_ts - session_start))
            fallback_sample[f"{prefix}_pre_window_idle_gap_seconds"] = _pre_window_idle_gap_seconds(all_timestamps, start_ts, session_start)
            is_active = event_count >= int(min_total_events)
            fallback_sample[f"{prefix}_active"] = 1.0 if is_active else 0.0
            if not is_active:
                continue
            active_scales += 1
            fallback_sample.update(_prefix_feature_values(prefix, extract_combined_features(kb_win, ms_win)))
        if active_scales > 0:
            fallback_sample["multiscale_active_scale_count"] = float(active_scales)
            fallback_sample["multiscale_scale_coverage"] = _safe_ratio(active_scales, len(scales))
            samples.append(fallback_sample)
    return annotate_sequence_trend_windows(annotate_transition_windows(samples))
