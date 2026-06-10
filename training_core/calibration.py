"""Training calibration and score percentile helpers extracted in Phase 3.

This module owns raw score percentile summaries and the user-calibration profile
builder so the legacy training module can reuse them without keeping the logic
inline.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from bioauth_model.scoring import weighted_average
from features import classify_behavior_context

CALIBRATION_VERSION = "phase6-calibration-v1"
MIN_CALIBRATION_POSITIVE_SESSIONS = 4
MIN_CALIBRATION_POSITIVE_WINDOW_SAMPLES = 24
MIN_CALIBRATION_CONTEXT_COVERAGE = 2


def _score_percentiles_dict(scores: np.ndarray) -> Dict[str, float]:
    arr = np.asarray(scores, dtype=float)
    if arr.size == 0:
        return {"p10": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0, "p95": 0.0, "p98": 0.0, "tail_high": 1.0}
    p10, p50, p75, p90, p95, p98 = np.percentile(arr, [10, 50, 75, 90, 95, 98])
    spread = max(1e-6, float(p90 - p50))
    return {
        "p10": float(p10),
        "p50": float(p50),
        "p75": float(p75),
        "p90": float(p90),
        "p95": float(p95),
        "p98": float(p98),
        "tail_high": float(max(p98 + spread * 1.5, p98 + 1e-6)),
    }


def _session_level_raw_percentiles(raw_scores: np.ndarray) -> Dict[str, float]:
    arr = np.asarray(raw_scores, dtype=float)
    if arr.size == 0:
        return {"p10": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0, "p95": 0.0, "p98": 0.0, "tail_high": 1.0}
    p10, p50, p75, p90, p95, p98 = np.percentile(arr, [10, 50, 75, 90, 95, 98])
    spread = max(1e-6, float(p90 - p50))
    return {
        "p10": float(p10),
        "p50": float(p50),
        "p75": float(p75),
        "p90": float(p90),
        "p95": float(p95),
        "p98": float(p98),
        "tail_high": float(max(p98 + spread * 1.25, p98 + 1e-6)),
    }


def _compute_user_calibration_profile(
    *,
    pos_scores: np.ndarray,
    neg_scores: np.ndarray,
    pos_sample_sources: List[str],
    pos_samples: List[Dict[str, float]],
) -> Dict[str, Any]:
    session_values: Dict[str, List[float]] = {}
    for session_name, score in zip(pos_sample_sources, np.asarray(pos_scores, dtype=float)):
        session_values.setdefault(str(session_name or "unknown"), []).append(float(score))

    session_aggregates = np.asarray([weighted_average(np.asarray(values, dtype=float)) for values in session_values.values() if values], dtype=float)
    session_percentiles = _session_level_raw_percentiles(session_aggregates)
    neg_arr = np.asarray(neg_scores, dtype=float)
    negative_percentiles = _session_level_raw_percentiles(neg_arr) if neg_arr.size else {}
    positive_contexts = {str((classify_behavior_context(sample) or {}).get("context") or "mixed") for sample in pos_samples if isinstance(sample, dict)}
    positive_contexts.discard("")

    session_count = int(len(session_values))
    window_count = int(len(pos_scores))
    context_coverage = int(len(positive_contexts))
    mature = session_count >= MIN_CALIBRATION_POSITIVE_SESSIONS and window_count >= MIN_CALIBRATION_POSITIVE_WINDOW_SAMPLES and context_coverage >= MIN_CALIBRATION_CONTEXT_COVERAGE
    if mature:
        reason = "enabled after sufficient positive session support, window support, and context coverage"
    else:
        parts = []
        if session_count < MIN_CALIBRATION_POSITIVE_SESSIONS:
            parts.append(f"needs >= {MIN_CALIBRATION_POSITIVE_SESSIONS} positive sessions")
        if window_count < MIN_CALIBRATION_POSITIVE_WINDOW_SAMPLES:
            parts.append(f"needs >= {MIN_CALIBRATION_POSITIVE_WINDOW_SAMPLES} positive windows")
        if context_coverage < MIN_CALIBRATION_CONTEXT_COVERAGE:
            parts.append(f"needs >= {MIN_CALIBRATION_CONTEXT_COVERAGE} routed contexts")
        reason = "; ".join(parts) if parts else "insufficient calibration evidence"

    safe_upper = float(session_percentiles.get("p75", session_percentiles.get("p50", 0.0)))
    warning_upper = float(session_percentiles.get("p95", safe_upper))
    tail_high = float(session_percentiles.get("tail_high", warning_upper + 1.0))
    if negative_percentiles:
        neg_p50 = float(negative_percentiles.get("p50", tail_high))
        if neg_p50 > warning_upper:
            tail_high = min(tail_high, max(warning_upper + 1e-6, neg_p50))

    return {
        "version": CALIBRATION_VERSION,
        "enabled": bool(mature),
        "maturity_flag": bool(mature),
        "maturity_reason": reason,
        "minimum_positive_session_support": int(MIN_CALIBRATION_POSITIVE_SESSIONS),
        "minimum_positive_window_support": int(MIN_CALIBRATION_POSITIVE_WINDOW_SAMPLES),
        "minimum_context_coverage": int(MIN_CALIBRATION_CONTEXT_COVERAGE),
        "positive_session_count": session_count,
        "positive_window_samples": window_count,
        "negative_window_samples": int(len(neg_scores)),
        "context_coverage": context_coverage,
        "positive_contexts": sorted(positive_contexts),
        "positive_session_raw_percentiles": {key: round(float(value), 6) for key, value in session_percentiles.items()},
        "negative_raw_reference": {key: round(float(value), 6) for key, value in negative_percentiles.items()} if negative_percentiles else {},
        "safe_band": {"raw_upper": round(safe_upper, 6)},
        "warning_band": {"raw_upper": round(warning_upper, 6), "tail_high": round(tail_high, 6)},
    }


__all__ = [
    "CALIBRATION_VERSION",
    "MIN_CALIBRATION_POSITIVE_SESSIONS",
    "MIN_CALIBRATION_POSITIVE_WINDOW_SAMPLES",
    "MIN_CALIBRATION_CONTEXT_COVERAGE",
    "_score_percentiles_dict",
    "_session_level_raw_percentiles",
    "_compute_user_calibration_profile",
]
