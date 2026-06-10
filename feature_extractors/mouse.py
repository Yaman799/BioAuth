from __future__ import annotations

import math
from typing import Dict

import numpy as np
import pandas as pd

from .conservative_v2 import extract_mouse_conservative_v2_features
from .common import (
    MS_DEFAULT_TAIL_ROWS,
    _activity_ratio,
    _finite_array,
    _safe_ratio,
    _sanitize_frame,
    _stats_template,
    _timing_deltas,
    _value_stats,
)


def extract_mouse_features(ms: pd.DataFrame, tail_rows: int = MS_DEFAULT_TAIL_ROWS) -> Dict[str, float]:
    ms = _sanitize_frame(ms, ["timestamp", "x", "y"], tail_rows=tail_rows)
    if ms.empty:
        base = {
            "ms_rows": 0.0,
            "ms_events_per_sec": 0.0,
            "ms_duration": 0.0,
            "ms_move_ratio": 0.0,
            "ms_drag_ratio": 0.0,
            "ms_click_ratio": 0.0,
            "ms_scroll_ratio": 0.0,
            "ms_longest_pause": 0.0,
            "ms_activity_ratio": 0.0,
            "ms_path_total": 0.0,
            "ms_path_efficiency": 0.0,
        }
        for prefix in (
            "ms_delta",
            "ms_step",
            "ms_velocity",
            "ms_accel",
            "ms_angle_change",
            "ms_click_interval",
            "ms_drag_step",
            "ms_scroll_interval",
        ):
            base.update(_stats_template(prefix))
        base.update(extract_mouse_conservative_v2_features(pd.DataFrame()))
        return base

    ms["event"] = ms.get("event", "").astype(str).str.strip().str.lower()
    duration = max(1e-6, float(ms["timestamp"].max() - ms["timestamp"].min()))
    deltas = _timing_deltas(ms["timestamp"])

    events = ms["event"]
    move_mask = events.eq("move")
    drag_mask = events.eq("drag") | events.str.contains("drag", na=False)
    click_mask = events.str.contains("click", na=False)
    click_press_mask = events.str.contains("click_press", na=False)
    scroll_mask = events.str.contains("scroll", na=False)

    motion = ms.loc[move_mask | drag_mask, ["timestamp", "x", "y", "event"]].copy()
    if len(motion) >= 2:
        dx = motion["x"].diff().fillna(0.0)
        dy = motion["y"].diff().fillna(0.0)
        step = np.sqrt(dx * dx + dy * dy).to_numpy(dtype=float)
        motion_dt = _timing_deltas(motion["timestamp"])
        velocity = np.asarray([], dtype=float)
        accel = np.asarray([], dtype=float)
        angle_change = np.asarray([], dtype=float)

        if motion_dt.size:
            usable_step = step[1 : 1 + motion_dt.size]
            velocity = np.divide(
                usable_step,
                motion_dt,
                out=np.zeros_like(usable_step, dtype=float),
                where=motion_dt > 1e-6,
            )
            valid_vel = velocity[np.isfinite(velocity)]
            velocity = valid_vel[valid_vel >= 0.0]
            if velocity.size >= 2 and motion_dt.size >= 2:
                accel_dt = motion_dt[1 : 1 + (velocity.size - 1)]
                vel_diff = np.diff(velocity)
                accel = np.divide(
                    np.abs(vel_diff),
                    accel_dt,
                    out=np.zeros_like(vel_diff, dtype=float),
                    where=accel_dt > 1e-6,
                )
            angles = np.unwrap(np.arctan2(dy.fillna(0.0), dx.fillna(0.0)).to_numpy(dtype=float))
            if angles.size >= 2:
                angle_change = np.abs(np.diff(angles))
        drag_motion = motion.loc[motion["event"].str.contains("drag", na=False)]
        drag_step = np.asarray([], dtype=float)
        if len(drag_motion) >= 2:
            ddx = drag_motion["x"].diff().fillna(0.0)
            ddy = drag_motion["y"].diff().fillna(0.0)
            drag_step = np.sqrt(ddx * ddx + ddy * ddy).to_numpy(dtype=float)
        total_path = float(np.nansum(step))
        displacement = float(
            math.hypot(
                float(motion["x"].iloc[-1] - motion["x"].iloc[0]),
                float(motion["y"].iloc[-1] - motion["y"].iloc[0]),
            )
        )
    else:
        step = np.asarray([], dtype=float)
        velocity = np.asarray([], dtype=float)
        accel = np.asarray([], dtype=float)
        angle_change = np.asarray([], dtype=float)
        drag_step = np.asarray([], dtype=float)
        total_path = 0.0
        displacement = 0.0

    click_times = ms.loc[click_press_mask, "timestamp"].astype(float).tolist()
    click_interval = np.diff(click_times) if len(click_times) >= 2 else np.asarray([], dtype=float)
    click_interval = _finite_array(click_interval)

    scroll_times = ms.loc[scroll_mask, "timestamp"].astype(float).tolist()
    scroll_interval = np.diff(scroll_times) if len(scroll_times) >= 2 else np.asarray([], dtype=float)
    scroll_interval = _finite_array(scroll_interval)

    features = {
        "ms_rows": float(len(ms)),
        "ms_events_per_sec": float(len(ms)) / max(duration, 1.0),
        "ms_duration": float(duration),
        "ms_move_ratio": _safe_ratio(move_mask.sum(), len(ms)),
        "ms_drag_ratio": _safe_ratio(drag_mask.sum(), len(ms)),
        "ms_click_ratio": _safe_ratio(click_mask.sum(), len(ms)),
        "ms_scroll_ratio": _safe_ratio(scroll_mask.sum(), len(ms)),
        "ms_longest_pause": float(deltas.max()) if deltas.size else 0.0,
        "ms_activity_ratio": _activity_ratio(ms["timestamp"], duration),
        "ms_path_total": total_path,
        "ms_path_efficiency": _safe_ratio(displacement, total_path),
    }
    features.update(_value_stats("ms_delta", deltas))
    features.update(_value_stats("ms_step", step))
    features.update(_value_stats("ms_velocity", velocity))
    features.update(_value_stats("ms_accel", accel))
    features.update(_value_stats("ms_angle_change", angle_change))
    features.update(_value_stats("ms_click_interval", click_interval))
    features.update(_value_stats("ms_drag_step", drag_step))
    features.update(_value_stats("ms_scroll_interval", scroll_interval))
    features.update(extract_mouse_conservative_v2_features(ms))
    return features
