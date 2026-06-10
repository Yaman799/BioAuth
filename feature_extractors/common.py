from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

KB_DEFAULT_TAIL_ROWS = 1400
MS_DEFAULT_TAIL_ROWS = 1800
DEFAULT_WINDOW_SECONDS = 12.0
DEFAULT_WINDOW_STEP_SECONDS = 6.0
DEFAULT_MIN_WINDOW_EVENTS = 60
MAX_DWELL_SECONDS = 3.0
MAX_FLIGHT_SECONDS = 3.0
MAX_MOUSE_GAP_SECONDS = 3.0


def _finite_array(values: Iterable[float]) -> np.ndarray:
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        return np.asarray([], dtype=float)
    return arr[np.isfinite(arr)]


def _stats_template(prefix: str) -> Dict[str, float]:
    return {
        f"{prefix}_count": 0.0,
        f"{prefix}_mean": 0.0,
        f"{prefix}_std": 0.0,
        f"{prefix}_median": 0.0,
        f"{prefix}_p10": 0.0,
        f"{prefix}_p90": 0.0,
        f"{prefix}_iqr": 0.0,
        f"{prefix}_min": 0.0,
        f"{prefix}_max": 0.0,
    }


def _value_stats(prefix: str, values: Iterable[float]) -> Dict[str, float]:
    arr = _finite_array(values)
    if arr.size == 0:
        return _stats_template(prefix)
    q10, q25, q50, q75, q90 = np.percentile(arr, [10, 25, 50, 75, 90])
    return {
        f"{prefix}_count": float(arr.size),
        f"{prefix}_mean": float(arr.mean()),
        f"{prefix}_std": float(arr.std(ddof=0)),
        f"{prefix}_median": float(q50),
        f"{prefix}_p10": float(q10),
        f"{prefix}_p90": float(q90),
        f"{prefix}_iqr": float(q75 - q25),
        f"{prefix}_min": float(arr.min()),
        f"{prefix}_max": float(arr.max()),
    }


def _safe_ratio(num: float, den: float) -> float:
    den = float(den)
    if den <= 0:
        return 0.0
    return float(num) / den


def _duration_from_timestamps(*frames: pd.DataFrame) -> float:
    mins: List[float] = []
    maxs: List[float] = []
    for frame in frames:
        if frame is None or frame.empty or "timestamp" not in frame.columns:
            continue
        mins.append(float(frame["timestamp"].min()))
        maxs.append(float(frame["timestamp"].max()))
    if not mins or not maxs:
        return 0.0
    return max(0.0, max(maxs) - min(mins))


def _sanitize_frame(frame: Optional[pd.DataFrame], numeric_columns: List[str], tail_rows: Optional[int] = None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=numeric_columns)
    out = frame.copy()
    if tail_rows is not None and tail_rows > 0:
        out = out.tail(int(tail_rows)).copy()
    for col in numeric_columns:
        out[col] = pd.to_numeric(out.get(col), errors="coerce")
    out = out.dropna(subset=[c for c in numeric_columns if c in out.columns])
    out = out.sort_values("timestamp").reset_index(drop=True)
    return out


def _timing_deltas(series: pd.Series) -> np.ndarray:
    if series is None or len(series) < 2:
        return np.asarray([], dtype=float)
    deltas = pd.to_numeric(series, errors="coerce").diff().dropna().astype(float).to_numpy()
    deltas = deltas[np.isfinite(deltas)]
    return deltas[deltas >= 0.0]


def _activity_ratio(series: pd.Series, duration: float) -> float:
    if series is None or series.empty or duration <= 0:
        return 0.0
    active_seconds = pd.to_numeric(series, errors="coerce").dropna().floordiv(1).nunique()
    return _safe_ratio(active_seconds, max(1.0, math.ceil(duration)))


def _combined_per_second_event_counts(kb: pd.DataFrame, ms: pd.DataFrame) -> np.ndarray:
    frames = []
    if kb is not None and not kb.empty and "timestamp" in kb.columns:
        frames.append(pd.DataFrame({"sec": pd.to_numeric(kb["timestamp"], errors="coerce").dropna().floordiv(1)}))
    if ms is not None and not ms.empty and "timestamp" in ms.columns:
        frames.append(pd.DataFrame({"sec": pd.to_numeric(ms["timestamp"], errors="coerce").dropna().floordiv(1)}))
    if not frames:
        return np.asarray([], dtype=float)
    merged = pd.concat(frames, ignore_index=True).dropna(subset=["sec"])
    if merged.empty:
        return np.asarray([], dtype=float)
    counts = merged.groupby("sec").size().astype(float)
    return counts.to_numpy(dtype=float)
