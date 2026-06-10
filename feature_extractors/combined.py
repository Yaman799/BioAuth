from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from .conservative_v2 import extract_combined_conservative_v2_features
from .common import (
    _combined_per_second_event_counts,
    _duration_from_timestamps,
    _safe_ratio,
    _sanitize_frame,
)
from .keyboard import KB_DEFAULT_TAIL_ROWS, extract_keyboard_features
from .mouse import MS_DEFAULT_TAIL_ROWS, extract_mouse_features


def extract_combined_features(
    kb: pd.DataFrame,
    ms: pd.DataFrame,
    kb_tail_rows: int = KB_DEFAULT_TAIL_ROWS,
    ms_tail_rows: int = MS_DEFAULT_TAIL_ROWS,
) -> Dict[str, float]:
    kb_clean = _sanitize_frame(kb, ["timestamp"], tail_rows=kb_tail_rows)
    ms_clean = _sanitize_frame(ms, ["timestamp", "x", "y"], tail_rows=ms_tail_rows)

    kb_features = extract_keyboard_features(kb_clean, tail_rows=kb_tail_rows)
    ms_features = extract_mouse_features(ms_clean, tail_rows=ms_tail_rows)

    total_events = float(len(kb_clean) + len(ms_clean))
    duration = max(1e-6, _duration_from_timestamps(kb_clean, ms_clean))

    modality_switch_ratio = 0.0
    if total_events >= 2:
        combined = []
        if not kb_clean.empty:
            combined.append(pd.DataFrame({"timestamp": kb_clean["timestamp"].astype(float), "src": "kb"}))
        if not ms_clean.empty:
            combined.append(pd.DataFrame({"timestamp": ms_clean["timestamp"].astype(float), "src": "ms"}))
        merged = pd.concat(combined, ignore_index=True).sort_values("timestamp")
        if len(merged) >= 2:
            switches = (merged["src"].shift() != merged["src"]).iloc[1:]
            modality_switch_ratio = float(switches.mean()) if len(switches) else 0.0

    combined_features = {
        "session_total_events": total_events,
        "session_duration": float(duration),
        "session_events_per_sec": total_events / max(duration, 1.0),
        "session_kb_share": _safe_ratio(len(kb_clean), total_events),
        "session_ms_share": _safe_ratio(len(ms_clean), total_events),
        "session_modality_switch_ratio": modality_switch_ratio,
    }
    combined_features.update(extract_combined_conservative_v2_features(kb_clean, ms_clean))
    combined_features.update(kb_features)
    combined_features.update(ms_features)
    return combined_features


def extract_session_quality_indicators(
    kb: pd.DataFrame,
    ms: pd.DataFrame,
    kb_tail_rows: Optional[int] = None,
    ms_tail_rows: Optional[int] = None,
) -> Dict[str, float]:
    kb_clean = _sanitize_frame(kb, ["timestamp"], tail_rows=kb_tail_rows)
    ms_clean = _sanitize_frame(ms, ["timestamp", "x", "y"], tail_rows=ms_tail_rows)
    kb_tail = len(kb_clean) if kb_tail_rows is None else kb_tail_rows
    ms_tail = len(ms_clean) if ms_tail_rows is None else ms_tail_rows
    combined = extract_combined_features(kb_clean, ms_clean, kb_tail_rows=kb_tail, ms_tail_rows=ms_tail)

    duration = max(0.0, _duration_from_timestamps(kb_clean, ms_clean))
    total_events = float(len(kb_clean) + len(ms_clean))
    counts = _combined_per_second_event_counts(kb_clean, ms_clean)
    density_cv = 0.0
    if counts.size >= 2 and float(np.mean(counts)) > 1e-6:
        density_cv = float(np.std(counts, ddof=0) / max(1e-6, float(np.mean(counts))))
    density_stability = float(max(0.0, 1.0 - min(1.0, density_cv / 1.5)))
    longest_pause = float(max(combined.get("kb_longest_pause", 0.0), combined.get("ms_longest_pause", 0.0)))
    inactivity_burst_ratio = _safe_ratio(longest_pause, max(1.0, duration))
    modality_balance = float(max(0.0, 1.0 - abs(float(combined.get("session_kb_share", 0.0)) - float(combined.get("session_ms_share", 0.0)))))
    active_second_ratio = float(max(float(combined.get("kb_activity_ratio", 0.0)), float(combined.get("ms_activity_ratio", 0.0)), float(combined.get("session_modality_switch_ratio", 0.0))))
    return {
        "total_events": total_events,
        "duration_seconds": float(duration),
        "event_density": _safe_ratio(total_events, max(1.0, duration)),
        "active_second_ratio": float(min(1.0, max(0.0, active_second_ratio))),
        "modality_balance": modality_balance,
        "inactivity_burst_ratio": float(min(1.0, max(0.0, inactivity_burst_ratio))),
        "density_stability": density_stability,
        "longest_pause_seconds": longest_pause,
        "modality_switch_ratio": float(combined.get("session_modality_switch_ratio", 0.0)),
        "keyboard_share": float(combined.get("session_kb_share", 0.0)),
        "mouse_share": float(combined.get("session_ms_share", 0.0)),
    }
