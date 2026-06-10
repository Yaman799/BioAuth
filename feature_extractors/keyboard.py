from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from .conservative_v2 import extract_keyboard_conservative_v2_features
from .common import (
    KB_DEFAULT_TAIL_ROWS,
    MAX_DWELL_SECONDS,
    MAX_FLIGHT_SECONDS,
    _activity_ratio,
    _safe_ratio,
    _sanitize_frame,
    _stats_template,
    _timing_deltas,
    _value_stats,
)


def extract_keyboard_features(kb: pd.DataFrame, tail_rows: int = KB_DEFAULT_TAIL_ROWS) -> Dict[str, float]:
    kb = _sanitize_frame(kb, ["timestamp"], tail_rows=tail_rows)
    if kb.empty:
        base = {
            "kb_rows": 0.0,
            "kb_events_per_sec": 0.0,
            "kb_duration": 0.0,
            "kb_press_ratio": 0.0,
            "kb_release_ratio": 0.0,
            "kb_unique_keys": 0.0,
            "kb_unique_keys_ratio": 0.0,
            "kb_press_release_balance": 0.0,
            "kb_burst_ratio": 0.0,
            "kb_longest_pause": 0.0,
            "kb_activity_ratio": 0.0,
            "kb_same_key_repeat_ratio": 0.0,
            "kb_matched_release_ratio": 0.0,
        }
        for prefix in (
            "kb_delta",
            "kb_dwell",
            "kb_flight_press",
            "kb_flight_release_press",
            "kb_digraph_diff",
            "kb_digraph_same",
            "kb_presses_per_second",
        ):
            base.update(_stats_template(prefix))
        base.update(extract_keyboard_conservative_v2_features(pd.DataFrame()))
        return base

    kb["event"] = kb.get("event", "").astype(str).str.strip().str.lower()
    kb["key"] = kb.get("key", "").astype(str)

    duration = max(1e-6, float(kb["timestamp"].max() - kb["timestamp"].min()))
    deltas = _timing_deltas(kb["timestamp"])

    press_mask = kb["event"].eq("press")
    release_mask = kb["event"].eq("release")
    press_rows = kb.loc[press_mask, ["timestamp", "key"]].reset_index(drop=True)
    release_rows = kb.loc[release_mask, ["timestamp", "key"]].reset_index(drop=True)
    presses = float(len(press_rows))
    releases = float(len(release_rows))

    if not press_rows.empty:
        press_rows = press_rows.assign(_idx=press_rows.groupby("key").cumcount())
    else:
        press_rows = press_rows.assign(_idx=pd.Series(dtype=int))

    if not release_rows.empty:
        dwell_stream = kb.loc[:, ["timestamp", "key", "event"]].copy()
        dwell_stream["_press_flag"] = dwell_stream["event"].eq("press").astype(int)
        dwell_stream["_release_flag"] = dwell_stream["event"].eq("release").astype(int)
        dwell_stream["_press_seen"] = dwell_stream.groupby("key")["_press_flag"].cumsum()
        dwell_stream["_release_seen"] = dwell_stream.groupby("key")["_release_flag"].cumsum()
        dwell_stream["_balance_after"] = dwell_stream["_press_seen"] - dwell_stream["_release_seen"]
        dwell_stream["_balance_before"] = dwell_stream.groupby("key")["_balance_after"].shift(fill_value=0)
        dwell_stream["_min_balance_before"] = dwell_stream.groupby("key")["_balance_before"].cummin()
        dwell_stream["_unmatched_before"] = (-dwell_stream["_min_balance_before"]).clip(lower=0).astype(int)

        matched_release_rows = dwell_stream.loc[
            dwell_stream["event"].eq("release"),
            ["timestamp", "key", "_press_seen", "_release_seen", "_unmatched_before"],
        ].copy()
        matched_release_rows["_release_rank"] = matched_release_rows["_release_seen"].astype(int) - 1
        matched_release_rows["_idx"] = matched_release_rows["_release_rank"] - matched_release_rows["_unmatched_before"]
        matched_release_rows = matched_release_rows.loc[
            (matched_release_rows["_idx"] >= 0)
            & (matched_release_rows["_idx"] < matched_release_rows["_press_seen"])
        ].copy()
        matched_release_rows["_idx"] = matched_release_rows["_idx"].astype(int)

        dwell_pairs = press_rows.merge(
            matched_release_rows[["timestamp", "key", "_idx"]].rename(columns={"timestamp": "release_timestamp"}),
            on=["key", "_idx"],
            how="inner",
        )
        dwell_series = pd.to_numeric(dwell_pairs["release_timestamp"], errors="coerce") - pd.to_numeric(dwell_pairs["timestamp"], errors="coerce")
        dwell_series = dwell_series[(dwell_series > 0.0) & (dwell_series <= MAX_DWELL_SECONDS)]
        dwell_times = dwell_series.astype(float).tolist()
    else:
        dwell_times = []

    if len(press_rows) >= 2:
        press_dt = pd.to_numeric(press_rows["timestamp"], errors="coerce").diff()
        press_dt = press_dt[(press_dt > 0.0) & (press_dt <= MAX_FLIGHT_SECONDS)]
        press_to_press = press_dt.astype(float).tolist()

        press_pairs = press_rows.copy()
        press_pairs["prev_key"] = press_pairs["key"].shift(1)
        press_pairs["prev_ts"] = pd.to_numeric(press_pairs["timestamp"], errors="coerce").shift(1)
        press_pairs["dt"] = pd.to_numeric(press_pairs["timestamp"], errors="coerce") - press_pairs["prev_ts"]
        valid_pairs = press_pairs.loc[(press_pairs["dt"] > 0.0) & (press_pairs["dt"] <= MAX_FLIGHT_SECONDS)].copy()
        digraph_same = valid_pairs.loc[valid_pairs["key"].eq(valid_pairs["prev_key"]), "dt"].astype(float).tolist()
        digraph_diff = valid_pairs.loc[~valid_pairs["key"].eq(valid_pairs["prev_key"]), "dt"].astype(float).tolist()
        repeated_presses = len(digraph_same)
        total_press_pairs = len(valid_pairs)
    else:
        press_to_press = []
        digraph_same = []
        digraph_diff = []
        repeated_presses = 0
        total_press_pairs = 0

    if not press_rows.empty and not release_rows.empty:
        release_prev = pd.merge_asof(
            press_rows[["timestamp"]].rename(columns={"timestamp": "press_timestamp"}).sort_values("press_timestamp"),
            release_rows[["timestamp"]].rename(columns={"timestamp": "release_timestamp"}).sort_values("release_timestamp"),
            left_on="press_timestamp",
            right_on="release_timestamp",
            direction="backward",
        )
        release_to_press_series = pd.to_numeric(release_prev["press_timestamp"], errors="coerce") - pd.to_numeric(release_prev["release_timestamp"], errors="coerce")
        release_to_press_series = release_to_press_series[(release_to_press_series > 0.0) & (release_to_press_series <= MAX_FLIGHT_SECONDS)]
        release_to_press = release_to_press_series.dropna().astype(float).tolist()
    else:
        release_to_press = []

    per_second_counts = []
    if not press_rows.empty:
        sec_counts = press_rows.assign(sec=press_rows["timestamp"].floordiv(1)).groupby("sec").size()
        per_second_counts = sec_counts.astype(float).tolist()

    unique_keys = float(press_rows["key"].nunique()) if not press_rows.empty else 0.0

    features = {
        "kb_rows": float(len(kb)),
        "kb_events_per_sec": float(len(kb)) / max(duration, 1.0),
        "kb_duration": float(duration),
        "kb_press_ratio": _safe_ratio(presses, len(kb)),
        "kb_release_ratio": _safe_ratio(releases, len(kb)),
        "kb_unique_keys": unique_keys,
        "kb_unique_keys_ratio": _safe_ratio(unique_keys, max(1.0, presses)),
        "kb_press_release_balance": abs(presses - releases) / max(1.0, presses + releases),
        "kb_burst_ratio": float(np.mean(deltas <= 0.18)) if deltas.size else 0.0,
        "kb_longest_pause": float(deltas.max()) if deltas.size else 0.0,
        "kb_activity_ratio": _activity_ratio(kb["timestamp"], duration),
        "kb_same_key_repeat_ratio": _safe_ratio(repeated_presses, total_press_pairs),
        "kb_matched_release_ratio": _safe_ratio(len(dwell_times), min(presses, releases) or 1.0),
    }
    features.update(_value_stats("kb_delta", deltas))
    features.update(_value_stats("kb_dwell", dwell_times))
    features.update(_value_stats("kb_flight_press", press_to_press))
    features.update(_value_stats("kb_flight_release_press", release_to_press))
    features.update(_value_stats("kb_digraph_diff", digraph_diff))
    features.update(_value_stats("kb_digraph_same", digraph_same))
    features.update(_value_stats("kb_presses_per_second", per_second_counts))
    features.update(
        extract_keyboard_conservative_v2_features(
            kb,
            dwell_times=dwell_times,
            press_to_press=press_to_press,
        )
    )
    return features
