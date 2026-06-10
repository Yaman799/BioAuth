from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

from .common import _finite_array, _safe_ratio, _stats_template, _timing_deltas, _value_stats

CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION = "commercial-core-11-conservative-features-v2"

_LETTER_KEYS = set("abcdefghijklmnopqrstuvwxyz")
_DIGIT_KEYS = set("0123456789")
_BACKSPACE_NAMES = {"backspace", "bksp", "delete_backward", "key.backspace"}
_DELETE_NAMES = {"delete", "del", "key.delete"}
_MODIFIER_NAMES = {
    "shift",
    "left_shift",
    "right_shift",
    "ctrl",
    "control",
    "left_ctrl",
    "right_ctrl",
    "alt",
    "left_alt",
    "right_alt",
    "meta",
    "cmd",
    "command",
    "windows",
    "win",
    "caps_lock",
    "tab",
}
_SYMBOL_NAMES = {
    "space",
    "enter",
    "return",
    "escape",
    "esc",
    "period",
    "comma",
    "semicolon",
    "quote",
    "slash",
    "backslash",
    "minus",
    "equals",
    "bracket",
    "left_bracket",
    "right_bracket",
}


def _as_float_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame is None or frame.empty or column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").dropna().astype(float)


def _entropy_from_counts(counts: Sequence[float]) -> float:
    arr = np.asarray([float(v) for v in counts if float(v) > 0.0], dtype=float)
    total = float(arr.sum()) if arr.size else 0.0
    if total <= 0.0:
        return 0.0
    probs = arr / total
    return float(-(probs * np.log2(probs)).sum())


def _normalized_entropy_from_counts(counts: Sequence[float]) -> float:
    positive = [float(v) for v in counts if float(v) > 0.0]
    if len(positive) <= 1:
        return 0.0
    return float(_entropy_from_counts(positive) / max(1e-9, math.log2(len(positive))))


def _key_category(key: object) -> str:
    text = str(key or "").strip().lower()
    if not text:
        return "unknown"
    if text in _BACKSPACE_NAMES:
        return "backspace"
    if text in _DELETE_NAMES:
        return "delete"
    if text in _MODIFIER_NAMES or any(part in text for part in ("shift", "ctrl", "control", "alt")):
        return "modifier"
    if len(text) == 1 and text in _LETTER_KEYS:
        return "letter"
    if len(text) == 1 and text in _DIGIT_KEYS:
        return "digit"
    if text in _SYMBOL_NAMES or len(text) == 1:
        return "symbol"
    return "other"


def _burst_durations(timestamps: Iterable[float], *, gap_seconds: float = 0.75) -> List[float]:
    arr = _finite_array(timestamps)
    if arr.size < 2:
        return []
    arr = np.sort(arr)
    starts = [float(arr[0])]
    durations: List[float] = []
    prev = float(arr[0])
    for value in arr[1:]:
        current = float(value)
        if current - prev > gap_seconds:
            durations.append(max(0.0, prev - starts[-1]))
            starts.append(current)
        prev = current
    durations.append(max(0.0, prev - starts[-1]))
    return durations


def extract_keyboard_conservative_v2_features(kb: pd.DataFrame, *, dwell_times: Iterable[float] | None = None, press_to_press: Iterable[float] | None = None) -> Dict[str, float]:
    """Return conservative keyboard v2 features.

    These features use timing/category aggregates only.  They never persist raw
    typed text and they are safe to ignore by older runtime metadata because
    inference selects only model-declared feature names.
    """

    if kb is None or kb.empty:
        base: Dict[str, float] = {
            "kb_v2_backspace_rate": 0.0,
            "kb_v2_delete_rate": 0.0,
            "kb_v2_correction_key_rate": 0.0,
            "kb_v2_modifier_rate": 0.0,
            "kb_v2_letter_rate": 0.0,
            "kb_v2_digit_rate": 0.0,
            "kb_v2_symbol_rate": 0.0,
            "kb_v2_other_key_rate": 0.0,
            "kb_v2_key_category_entropy": 0.0,
            "kb_v2_hold_to_flight_ratio": 0.0,
            "kb_v2_pause_entropy": 0.0,
            "kb_v2_burst_count": 0.0,
            "kb_v2_burst_key_count_mean": 0.0,
        }
        for prefix in ("kb_v2_trigraph_latency", "kb_v2_burst_duration"):
            base.update(_stats_template(prefix))
        return base

    frame = kb.copy()
    frame["event"] = frame.get("event", "").astype(str).str.strip().str.lower()
    frame["key"] = frame.get("key", "").astype(str)
    press_rows = frame.loc[frame["event"].eq("press"), ["timestamp", "key"]].copy()
    press_count = float(len(press_rows))
    categories = press_rows["key"].map(_key_category) if not press_rows.empty else pd.Series(dtype=str)
    category_counts = categories.value_counts().to_dict() if len(categories) else {}

    press_ts = _as_float_series(press_rows, "timestamp")
    deltas = _timing_deltas(press_ts)
    trigraph_latency = deltas[:-1] + deltas[1:] if deltas.size >= 2 else np.asarray([], dtype=float)

    pause_bins = [0, 0, 0, 0]
    for value in deltas:
        if value <= 0.18:
            pause_bins[0] += 1
        elif value <= 0.75:
            pause_bins[1] += 1
        elif value <= 1.5:
            pause_bins[2] += 1
        else:
            pause_bins[3] += 1

    burst_durs = _burst_durations(press_ts.tolist())
    burst_key_counts: List[float] = []
    if press_ts.size:
        sorted_ts = np.sort(press_ts.to_numpy(dtype=float))
        count = 1
        prev = float(sorted_ts[0])
        for value in sorted_ts[1:]:
            current = float(value)
            if current - prev > 0.75:
                burst_key_counts.append(float(count))
                count = 1
            else:
                count += 1
            prev = current
        burst_key_counts.append(float(count))

    dwell_arr = _finite_array([] if dwell_times is None else dwell_times)
    flight_arr = _finite_array([] if press_to_press is None else press_to_press)
    hold_to_flight_ratio = _safe_ratio(float(np.mean(dwell_arr)) if dwell_arr.size else 0.0, float(np.mean(flight_arr)) if flight_arr.size else 0.0)

    features: Dict[str, float] = {
        "kb_v2_backspace_rate": _safe_ratio(category_counts.get("backspace", 0.0), press_count),
        "kb_v2_delete_rate": _safe_ratio(category_counts.get("delete", 0.0), press_count),
        "kb_v2_correction_key_rate": _safe_ratio(category_counts.get("backspace", 0.0) + category_counts.get("delete", 0.0), press_count),
        "kb_v2_modifier_rate": _safe_ratio(category_counts.get("modifier", 0.0), press_count),
        "kb_v2_letter_rate": _safe_ratio(category_counts.get("letter", 0.0), press_count),
        "kb_v2_digit_rate": _safe_ratio(category_counts.get("digit", 0.0), press_count),
        "kb_v2_symbol_rate": _safe_ratio(category_counts.get("symbol", 0.0), press_count),
        "kb_v2_other_key_rate": _safe_ratio(category_counts.get("other", 0.0) + category_counts.get("unknown", 0.0), press_count),
        "kb_v2_key_category_entropy": _normalized_entropy_from_counts(list(category_counts.values())),
        "kb_v2_hold_to_flight_ratio": float(hold_to_flight_ratio),
        "kb_v2_pause_entropy": _normalized_entropy_from_counts(pause_bins),
        "kb_v2_burst_count": float(len(burst_key_counts)),
        "kb_v2_burst_key_count_mean": float(np.mean(burst_key_counts)) if burst_key_counts else 0.0,
    }
    features.update(_value_stats("kb_v2_trigraph_latency", trigraph_latency))
    features.update(_value_stats("kb_v2_burst_duration", burst_durs))
    return features


def _segment_efficiencies(motion: pd.DataFrame, *, gap_seconds: float = 0.75) -> List[float]:
    if motion is None or len(motion) < 2:
        return []
    rows = motion[["timestamp", "x", "y"]].dropna().sort_values("timestamp").to_dict("records")
    if len(rows) < 2:
        return []
    segments: List[List[dict]] = [[rows[0]]]
    prev_ts = float(rows[0]["timestamp"])
    for row in rows[1:]:
        ts = float(row["timestamp"])
        if ts - prev_ts > gap_seconds:
            segments.append([row])
        else:
            segments[-1].append(row)
        prev_ts = ts
    efficiencies: List[float] = []
    for segment in segments:
        if len(segment) < 2:
            continue
        path = 0.0
        for a, b in zip(segment, segment[1:]):
            path += math.hypot(float(b["x"] - a["x"]), float(b["y"] - a["y"]))
        disp = math.hypot(float(segment[-1]["x"] - segment[0]["x"]), float(segment[-1]["y"] - segment[0]["y"]))
        efficiencies.append(_safe_ratio(disp, path))
    return efficiencies


def extract_mouse_conservative_v2_features(ms: pd.DataFrame) -> Dict[str, float]:
    if ms is None or ms.empty:
        base: Dict[str, float] = {
            "ms_v2_direction_entropy": 0.0,
            "ms_v2_micro_move_rate": 0.0,
            "ms_v2_turning_point_count": 0.0,
            "ms_v2_pre_click_slowdown": 0.0,
            "ms_v2_pre_click_direction_changes": 0.0,
            "ms_v2_scroll_burst_count": 0.0,
            "ms_v2_scroll_direction_change_rate": 0.0,
        }
        for prefix in ("ms_v2_jerk", "ms_v2_curvature", "ms_v2_segment_efficiency"):
            base.update(_stats_template(prefix))
        return base

    frame = ms.copy()
    frame["event"] = frame.get("event", "").astype(str).str.strip().str.lower()
    motion = frame.loc[frame["event"].eq("move") | frame["event"].str.contains("drag", na=False), ["timestamp", "x", "y", "event"]].copy()
    motion["timestamp"] = pd.to_numeric(motion.get("timestamp"), errors="coerce")
    motion["x"] = pd.to_numeric(motion.get("x"), errors="coerce")
    motion["y"] = pd.to_numeric(motion.get("y"), errors="coerce")
    motion = motion.dropna(subset=["timestamp", "x", "y"]).sort_values("timestamp").reset_index(drop=True)

    jerk = np.asarray([], dtype=float)
    curvature = np.asarray([], dtype=float)
    direction_entropy = 0.0
    micro_move_rate = 0.0
    turning_point_count = 0.0
    pre_click_slowdown = 0.0
    pre_click_direction_changes = 0.0
    segment_efficiency = _segment_efficiencies(motion)

    if len(motion) >= 3:
        dx = motion["x"].diff().fillna(0.0).to_numpy(dtype=float)
        dy = motion["y"].diff().fillna(0.0).to_numpy(dtype=float)
        step = np.sqrt(dx * dx + dy * dy)
        dt = _timing_deltas(motion["timestamp"])
        usable_step = step[1 : 1 + dt.size] if dt.size else np.asarray([], dtype=float)
        velocity = np.divide(usable_step, dt, out=np.zeros_like(usable_step), where=dt > 1e-6) if dt.size else np.asarray([], dtype=float)
        if velocity.size >= 3 and dt.size >= 3:
            accel = np.diff(velocity) / np.maximum(dt[1 : 1 + (velocity.size - 1)], 1e-6)
            if accel.size >= 2:
                jerk = np.abs(np.diff(accel) / np.maximum(dt[2 : 2 + (accel.size - 1)], 1e-6))
        angles = np.arctan2(dy[1:], dx[1:])
        valid_angles = angles[np.isfinite(angles)]
        if valid_angles.size:
            bins = np.histogram(valid_angles, bins=8, range=(-math.pi, math.pi))[0]
            direction_entropy = _normalized_entropy_from_counts(bins)
        angle_change = np.abs(np.diff(np.unwrap(angles))) if angles.size >= 2 else np.asarray([], dtype=float)
        usable_step2 = step[2 : 2 + angle_change.size]
        curvature = np.divide(angle_change, usable_step2, out=np.zeros_like(angle_change), where=usable_step2 > 1e-6) if angle_change.size else np.asarray([], dtype=float)
        micro_move_rate = _safe_ratio(float(np.sum((step > 0.0) & (step <= 2.0))), float(max(1, step.size)))
        turning_point_count = float(np.sum(angle_change >= (math.pi / 4.0))) if angle_change.size else 0.0

        click_mask = frame["event"].str.contains("click_press", na=False) | frame["event"].str.contains("click", na=False)
        click_times = pd.to_numeric(frame.loc[click_mask, "timestamp"], errors="coerce").dropna().astype(float).tolist()
        if click_times and velocity.size:
            slowdowns: List[float] = []
            direction_changes: List[float] = []
            motion_ts = motion["timestamp"].to_numpy(dtype=float)[1 : 1 + velocity.size]
            for click_ts in click_times[:5]:
                before_idx = np.where((motion_ts >= click_ts - 1.0) & (motion_ts <= click_ts))[0]
                if before_idx.size >= 4:
                    early = velocity[before_idx[: max(1, before_idx.size // 2)]]
                    late = velocity[before_idx[max(1, before_idx.size // 2) :]]
                    slowdowns.append(max(0.0, float(np.mean(early) - np.mean(late))))
                    local_angles = valid_angles[max(0, int(before_idx[0]) - 1) : int(before_idx[-1]) + 1]
                    if local_angles.size >= 2:
                        local_changes = np.abs(np.diff(np.unwrap(local_angles)))
                        direction_changes.append(float(np.sum(local_changes >= math.pi / 6.0)))
            pre_click_slowdown = float(np.mean(slowdowns)) if slowdowns else 0.0
            pre_click_direction_changes = float(np.mean(direction_changes)) if direction_changes else 0.0

    scroll_mask = frame["event"].str.contains("scroll", na=False)
    scroll_rows = frame.loc[scroll_mask].copy()
    scroll_bursts = 0
    scroll_direction_changes = 0
    if not scroll_rows.empty:
        scroll_ts = pd.to_numeric(scroll_rows["timestamp"], errors="coerce").dropna().sort_values().to_numpy(dtype=float)
        if scroll_ts.size:
            scroll_bursts = 1
            for gap in np.diff(scroll_ts):
                if gap > 0.75:
                    scroll_bursts += 1
        direction_values = None
        for col in ("dy", "delta_y", "wheel_delta", "scroll_delta"):
            if col in scroll_rows.columns:
                direction_values = pd.to_numeric(scroll_rows[col], errors="coerce").dropna().to_numpy(dtype=float)
                break
        if direction_values is not None and direction_values.size >= 2:
            signs = np.sign(direction_values)
            scroll_direction_changes = int(np.sum(signs[1:] * signs[:-1] < 0))
    return {
        **_value_stats("ms_v2_jerk", jerk),
        **_value_stats("ms_v2_curvature", curvature),
        **_value_stats("ms_v2_segment_efficiency", segment_efficiency),
        "ms_v2_direction_entropy": float(direction_entropy),
        "ms_v2_micro_move_rate": float(micro_move_rate),
        "ms_v2_turning_point_count": float(turning_point_count),
        "ms_v2_pre_click_slowdown": float(pre_click_slowdown),
        "ms_v2_pre_click_direction_changes": float(pre_click_direction_changes),
        "ms_v2_scroll_burst_count": float(scroll_bursts),
        "ms_v2_scroll_direction_change_rate": _safe_ratio(float(scroll_direction_changes), float(max(1, len(scroll_rows)))) if not scroll_rows.empty else 0.0,
    }


def extract_combined_conservative_v2_features(kb: pd.DataFrame, ms: pd.DataFrame) -> Dict[str, float]:
    kb_ts = _as_float_series(kb, "timestamp") if kb is not None else pd.Series(dtype=float)
    ms_ts = _as_float_series(ms, "timestamp") if ms is not None else pd.Series(dtype=float)
    kb_to_mouse_delays: List[float] = []
    mouse_to_kb_delays: List[float] = []
    modality_sequence: List[str] = []
    if not kb_ts.empty:
        modality_sequence.extend(["kb"] * len(kb_ts))
    if not ms_ts.empty:
        modality_sequence.extend(["ms"] * len(ms_ts))
    if not kb_ts.empty and not ms_ts.empty:
        kb_df = pd.DataFrame({"timestamp": kb_ts, "src": "kb"})
        ms_df = pd.DataFrame({"timestamp": ms_ts, "src": "ms"})
        merged = pd.concat([kb_df, ms_df], ignore_index=True).sort_values("timestamp").reset_index(drop=True)
        src = merged["src"].tolist()
        ts = merged["timestamp"].astype(float).tolist()
        for idx in range(1, len(src)):
            delay = max(0.0, float(ts[idx] - ts[idx - 1]))
            if src[idx - 1] == "kb" and src[idx] == "ms":
                kb_to_mouse_delays.append(delay)
            elif src[idx - 1] == "ms" and src[idx] == "kb":
                mouse_to_kb_delays.append(delay)
        modality_sequence = src
    switch_entropy = _normalized_entropy_from_counts([
        sum(1 for v in modality_sequence if v == "kb"),
        sum(1 for v in modality_sequence if v == "ms"),
    ])
    total_events = float((len(kb_ts) if kb_ts is not None else 0) + (len(ms_ts) if ms_ts is not None else 0))
    duration = 0.0
    all_ts = []
    if not kb_ts.empty:
        all_ts.extend(kb_ts.tolist())
    if not ms_ts.empty:
        all_ts.extend(ms_ts.tolist())
    if all_ts:
        duration = max(0.0, float(max(all_ts) - min(all_ts)))
    kb_quality = min(1.0, _safe_ratio(float(len(kb_ts)), 40.0)) if len(kb_ts) else 0.0
    ms_quality = min(1.0, _safe_ratio(float(len(ms_ts)), 80.0)) if len(ms_ts) else 0.0
    density = _safe_ratio(total_events, max(1.0, duration))
    density_score = min(1.0, density / 12.0)
    combined_quality = float((0.35 * kb_quality) + (0.35 * ms_quality) + (0.30 * density_score))
    return {
        "session_v2_kb_to_mouse_delay_mean": float(np.mean(kb_to_mouse_delays)) if kb_to_mouse_delays else 0.0,
        "session_v2_mouse_to_kb_delay_mean": float(np.mean(mouse_to_kb_delays)) if mouse_to_kb_delays else 0.0,
        "session_v2_modality_switch_entropy": float(switch_entropy),
        "session_v2_evidence_density": float(density),
        "session_v2_keyboard_quality_score": float(kb_quality),
        "session_v2_mouse_quality_score": float(ms_quality),
        "session_v2_combined_quality_score": float(min(1.0, max(0.0, combined_quality))),
    }


__all__ = [
    "CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION",
    "extract_keyboard_conservative_v2_features",
    "extract_mouse_conservative_v2_features",
    "extract_combined_conservative_v2_features",
]
