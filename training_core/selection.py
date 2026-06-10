"""Training-session selection seam extracted in Phase 1.

This module owns the quality/diversity session selection pipeline so metadata
views can consume selection summaries without importing the full legacy
training pipeline module.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from features import extract_session_quality_indicators
from model_metadata import (
    KB_HEADER,
    MAX_REFERENCE_NEGATIVE_SESSIONS,
    MAX_TRAIN_WINDOWS_PER_SESSION,
    MS_HEADER,
    WINDOW_SECONDS,
    read_session_metadata,
)
from training_core.data import EncryptedSessionReadError, read_csv_encrypted
from feedback_loop import production_positive_training_allowed
from training_core.session_eligibility import TRAINING_SESSION_ELIGIBILITY_VERSION, assess_positive_training_session

LOGGER = logging.getLogger(__name__)

QUALITY_SELECTION_VERSION = "phase3-v1"
HARD_NEGATIVE_MINING_VERSION = "hard-negative-v1"
MIN_SELECTION_QUALITY_SCORE = 0.28


def _clamp01(value: Any) -> float:
    try:
        numeric = float(value)
    except Exception:
        return 0.0
    if not np.isfinite(numeric):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _quality_band(value: float, *, low: float, high: float) -> str:
    try:
        val = float(value)
    except Exception:
        val = 0.0
    if val < low:
        return "low"
    if val >= high:
        return "high"
    return "mid"


def _triangular_score(value: float, *, low: float, ideal_low: float, ideal_high: float, high: float) -> float:
    try:
        val = float(value)
    except Exception:
        val = 0.0
    if val <= low or val >= high:
        return 0.0
    if ideal_low <= val <= ideal_high:
        return 1.0
    if val < ideal_low:
        return _clamp01((val - low) / max(1e-6, ideal_low - low))
    return _clamp01((high - val) / max(1e-6, high - ideal_high))


def _window_budget_for_quality(score: float) -> int:
    if score >= 0.72:
        return MAX_TRAIN_WINDOWS_PER_SESSION
    if score >= 0.54:
        return max(10, int(round(MAX_TRAIN_WINDOWS_PER_SESSION * 0.7)))
    return max(6, int(round(MAX_TRAIN_WINDOWS_PER_SESSION * 0.45)))


def _compute_session_quality_record(
    session_path: str,
    meta: Optional[Dict[str, Any]],
    *,
    role: str,
    strict: bool,
) -> Dict[str, Any]:
    metadata = dict(meta or {})
    kb = read_csv_encrypted(os.path.join(session_path, "keyboard_log.csv"), KB_HEADER, strict=strict)
    ms = read_csv_encrypted(os.path.join(session_path, "mouse_log.csv"), MS_HEADER, strict=strict)
    indicators = extract_session_quality_indicators(kb, ms, kb_tail_rows=None, ms_tail_rows=None)

    density_score = _triangular_score(indicators["event_density"], low=0.6, ideal_low=2.5, ideal_high=18.0, high=40.0)
    activity_score = _clamp01(indicators["active_second_ratio"])
    modality_score = _clamp01(0.35 + 0.65 * indicators["modality_balance"])
    inactivity_score = _clamp01(1.0 - indicators["inactivity_burst_ratio"])
    stability_score = _clamp01(indicators["density_stability"])
    quality_score = float(
        0.30 * density_score
        + 0.25 * activity_score
        + 0.15 * modality_score
        + 0.15 * inactivity_score
        + 0.15 * stability_score
    )
    activity_band = _quality_band(indicators["event_density"], low=3.0, high=10.0)
    duration_band = _quality_band(indicators["duration_seconds"], low=max(10.0, WINDOW_SECONDS), high=90.0)
    kb_share = indicators["keyboard_share"]
    if kb_share >= 0.7:
        modality_band = "keyboard_heavy"
    elif kb_share <= 0.3:
        modality_band = "mouse_heavy"
    else:
        modality_band = "mixed"
    quality_tier = "high" if quality_score >= 0.72 else "medium" if quality_score >= 0.54 else "borderline" if quality_score >= MIN_SELECTION_QUALITY_SCORE else "reject"
    return {
        "session_path": os.path.abspath(session_path),
        "session_name": os.path.basename(session_path),
        "session_kind": str(metadata.get("session_kind") or "unknown"),
        "role": role,
        "quality_score": round(quality_score, 6),
        "quality_tier": quality_tier,
        "quality_components": {
            "density_score": round(density_score, 6),
            "activity_score": round(activity_score, 6),
            "modality_score": round(modality_score, 6),
            "inactivity_score": round(inactivity_score, 6),
            "stability_score": round(stability_score, 6),
        },
        "quality_indicators": {key: round(float(value), 6) for key, value in indicators.items()},
        "activity_band": activity_band,
        "duration_band": duration_band,
        "modality_band": modality_band,
        "training_eligible": bool(metadata.get("training_eligible")),
        "metadata_trusted": bool(metadata.get("metadata_trusted")),
        "window_budget": _window_budget_for_quality(quality_score),
        "selection_score": 0.0,
        "selection_reason": "",
        "excluded": False,
        "exclusion_reason": None,
    }


def _recency_scores(records: List[Dict[str, Any]]) -> Dict[str, float]:
    if not records:
        return {}
    mtimes = []
    for record in records:
        try:
            mtimes.append(float(os.path.getmtime(record["session_path"])))
        except OSError:
            mtimes.append(0.0)
    lo = min(mtimes)
    hi = max(mtimes)
    if hi <= lo:
        return {record["session_path"]: 1.0 for record in records}
    return {
        record["session_path"]: _clamp01((mtime - lo) / max(1e-6, hi - lo))
        for record, mtime in zip(records, mtimes)
    }


def _candidate_novelty(record: Dict[str, Any], selected: List[Dict[str, Any]]) -> float:
    if not selected:
        return 1.0
    novelty = 0.2
    for field in ("activity_band", "modality_band", "duration_band"):
        seen = {item.get(field) for item in selected}
        if record.get(field) not in seen:
            novelty += 0.25
    signature = (record.get("activity_band"), record.get("modality_band"), record.get("duration_band"))
    seen_signatures = {
        (item.get("activity_band"), item.get("modality_band"), item.get("duration_band"))
        for item in selected
    }
    if signature not in seen_signatures:
        novelty += 0.2
    return _clamp01(novelty)


def _negative_mining_vector(record: Dict[str, Any]) -> np.ndarray:
    indicators = dict(record.get("quality_indicators") or {})
    density = min(1.0, np.log1p(max(0.0, float(indicators.get("event_density") or 0.0))) / np.log1p(40.0))
    duration = _clamp01(float(indicators.get("duration_seconds") or 0.0) / 120.0)
    active = _clamp01(indicators.get("active_second_ratio"))
    modality_balance = _clamp01(indicators.get("modality_balance"))
    inactivity_resilience = _clamp01(1.0 - float(indicators.get("inactivity_burst_ratio") or 0.0))
    density_stability = _clamp01(indicators.get("density_stability"))
    keyboard_share = _clamp01(indicators.get("keyboard_share"))
    modality_switch = _clamp01(indicators.get("modality_switch_ratio"))
    quality_score = _clamp01(record.get("quality_score"))
    return np.asarray(
        [
            density,
            duration,
            active,
            modality_balance,
            inactivity_resilience,
            density_stability,
            keyboard_share,
            modality_switch,
            quality_score,
        ],
        dtype=float,
    )


def _resolve_selected_records(summary: Dict[str, Any], source_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected_names = {str(item.get("session_name") or "") for item in list(summary.get("included_records") or [])}
    return [record for record in source_records if str(record.get("session_name") or "") in selected_names]


def _assign_negative_hardness(records: List[Dict[str, Any]], positive_reference_records: List[Dict[str, Any]]) -> None:
    if not records:
        return
    if positive_reference_records:
        positive_vectors = np.vstack([_negative_mining_vector(record) for record in positive_reference_records])
        centroid = np.mean(positive_vectors, axis=0)
    else:
        centroid = np.zeros_like(_negative_mining_vector(records[0]))

    distances: List[float] = []
    for record in records:
        vector = _negative_mining_vector(record)
        distance = float(np.linalg.norm(vector - centroid))
        record["hardness_distance"] = round(distance, 6)
        distances.append(distance)

    if not distances:
        return
    min_distance = min(distances)
    max_distance = max(distances)
    for record, distance in zip(records, distances):
        if max_distance <= min_distance + 1e-9:
            hardness_score = 1.0
        else:
            hardness_score = 1.0 - ((distance - min_distance) / max(1e-6, max_distance - min_distance))
        record["hardness_score"] = round(_clamp01(hardness_score), 6)

    ranked = sorted(
        records,
        key=lambda item: (
            float(item.get("hardness_score") or 0.0),
            float(item.get("quality_score") or 0.0),
            float(item.get("recency_score") or 0.0),
            item.get("session_name", ""),
        ),
        reverse=True,
    )
    total = len(ranked)
    if total == 1:
        hard_count, medium_count = 1, 0
    elif total == 2:
        hard_count, medium_count = 1, 0
    else:
        hard_count = max(1, int(np.ceil(total / 3.0)))
        easy_count = max(1, int(np.ceil(total / 3.0)))
        medium_count = max(0, total - hard_count - easy_count)

    for idx, record in enumerate(ranked):
        if total == 1:
            band = "hard"
        elif total == 2:
            band = "hard" if idx == 0 else "easy"
        elif idx < hard_count:
            band = "hard"
        elif idx < hard_count + medium_count:
            band = "medium"
        else:
            band = "easy"
        record["hardness_band"] = band


def _summarize_negative_mix(selected: List[Dict[str, Any]]) -> Dict[str, int]:
    mix = {"hard": 0, "medium": 0, "easy": 0}
    for record in selected:
        band = str(record.get("hardness_band") or "")
        if band in mix:
            mix[band] += 1
    return mix


def _summarize_selection_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summarized: List[Dict[str, Any]] = []
    for record in records:
        summarized.append(
            {
                "session_path": record["session_path"],
                "session_name": record["session_name"],
                "session_kind": record.get("session_kind"),
                "role": record.get("role"),
                "quality_score": record.get("quality_score"),
                "quality_tier": record.get("quality_tier"),
                "selection_score": round(float(record.get("selection_score") or 0.0), 6),
                "recency_score": round(float(record.get("recency_score") or 0.0), 6),
                "diversity_score": round(float(record.get("diversity_score") or 0.0), 6),
                "window_budget": int(record.get("window_budget") or 0),
                "activity_band": record.get("activity_band"),
                "duration_band": record.get("duration_band"),
                "modality_band": record.get("modality_band"),
                "selection_reason": record.get("selection_reason"),
                "exclusion_reason": record.get("exclusion_reason"),
                "quality_indicators": dict(record.get("quality_indicators") or {}),
                "hardness_score": round(float(record.get("hardness_score") or 0.0), 6) if record.get("hardness_score") is not None else 0.0,
                "hardness_distance": round(float(record.get("hardness_distance") or 0.0), 6) if record.get("hardness_distance") is not None else 0.0,
                "hardness_band": record.get("hardness_band"),
            }
        )
    return summarized


def _build_negative_selection_summary(
    candidate_records: List[Dict[str, Any]],
    *,
    max_sessions: int,
    positive_reference_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    records = [dict(item) for item in candidate_records]
    recency_lookup = _recency_scores(records)
    eligible: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for record in records:
        record["recency_score"] = round(float(recency_lookup.get(record["session_path"], 0.0)), 6)
        if float(record.get("quality_score") or 0.0) < MIN_SELECTION_QUALITY_SCORE:
            record["excluded"] = True
            record["exclusion_reason"] = "quality_score_below_floor"
            record["selection_reason"] = "Excluded because the reference negative quality score fell below the minimum mining floor."
            excluded.append(record)
        else:
            eligible.append(record)

    max_keep = max(0, int(max_sessions or 0))
    if max_keep <= 0:
        for record in eligible:
            record["excluded"] = True
            record["exclusion_reason"] = "selection_capacity_zero"
            record["selection_reason"] = "Excluded because the reference negative capacity for this pool is zero."
            excluded.append(record)
        return {
            "selection_version": QUALITY_SELECTION_VERSION,
            "negative_strategy": "quality_gated_hard_negative_mining",
            "negative_strategy_version": HARD_NEGATIVE_MINING_VERSION,
            "included_records": [],
            "excluded_records": _summarize_selection_records(excluded),
            "candidate_count": len(records),
            "included_count": 0,
            "excluded_count": len(excluded),
            "hardness_band_counts": {},
            "hardness_mix": {"hard": 0, "medium": 0, "easy": 0},
        }

    _assign_negative_hardness(eligible, positive_reference_records)
    for record in eligible:
        selection_score = (
            0.45 * float(record.get("quality_score") or 0.0)
            + 0.20 * float(record.get("recency_score") or 0.0)
            + 0.35 * float(record.get("hardness_score") or 0.0)
        )
        record["selection_score"] = round(selection_score, 6)

    selected: List[Dict[str, Any]] = []
    available_bands = [band for band in ("hard", "medium", "easy") if any(item.get("hardness_band") == band for item in eligible)]
    if max_keep >= 3:
        for band in available_bands:
            if len(selected) >= max_keep:
                break
            candidates = [record for record in eligible if record not in selected and record.get("hardness_band") == band]
            if not candidates:
                continue
            candidates.sort(key=lambda item: (float(item.get("selection_score") or 0.0), float(item.get("quality_score") or 0.0), item.get("session_name", "")), reverse=True)
            chosen = candidates[0]
            chosen["selection_reason"] = f"Selected to preserve the {band} hard-negative band in the mining mix."
            selected.append(chosen)

    rotation = [band for band in ("hard", "medium", "easy") if band in available_bands] or ["hard"]
    cursor = 0
    while len(selected) < max_keep:
        remaining = [record for record in eligible if record not in selected]
        if not remaining:
            break
        target_band = rotation[cursor % len(rotation)]
        cursor += 1
        band_candidates = [record for record in remaining if record.get("hardness_band") == target_band]
        if not band_candidates:
            band_candidates = remaining
        band_candidates.sort(key=lambda item: (float(item.get("selection_score") or 0.0), float(item.get("quality_score") or 0.0), item.get("session_name", "")), reverse=True)
        chosen = band_candidates[0]
        if not chosen.get("selection_reason"):
            chosen["selection_reason"] = "Selected by the hard-negative mining pipeline using a quality/recency/hardness mix."
        selected.append(chosen)

    for record in eligible:
        if record in selected:
            if not record.get("selection_reason"):
                record["selection_reason"] = "Selected by the hard-negative mining pipeline using a quality/recency/hardness mix."
            continue
        record["excluded"] = True
        record["exclusion_reason"] = "ranked_below_negative_cutoff"
        record["selection_reason"] = "Excluded because the selected hard-negative mix already covered the available reference negative budget."
        excluded.append(record)

    selected.sort(key=lambda item: (float(item.get("selection_score") or 0.0), float(item.get("hardness_score") or 0.0), item.get("session_name", "")), reverse=True)
    hardness_band_counts: Dict[str, int] = {}
    for record in eligible:
        band = str(record.get("hardness_band") or "unknown")
        hardness_band_counts[band] = hardness_band_counts.get(band, 0) + 1

    return {
        "selection_version": QUALITY_SELECTION_VERSION,
        "negative_strategy": "quality_gated_hard_negative_mining",
        "negative_strategy_version": HARD_NEGATIVE_MINING_VERSION,
        "included_records": _summarize_selection_records(selected),
        "excluded_records": _summarize_selection_records(excluded),
        "candidate_count": len(records),
        "included_count": len(selected),
        "excluded_count": len(excluded),
        "hardness_band_counts": hardness_band_counts,
        "hardness_mix": _summarize_negative_mix(selected),
    }


def _build_selection_summary(
    candidate_records: List[Dict[str, Any]],
    *,
    max_sessions: int,
    required_activity_bands: Optional[List[str]] = None,
) -> Dict[str, Any]:
    records = [dict(item) for item in candidate_records]
    recency_lookup = _recency_scores(records)
    eligible: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for record in records:
        record["recency_score"] = round(float(recency_lookup.get(record["session_path"], 0.0)), 6)
        if float(record.get("quality_score") or 0.0) < MIN_SELECTION_QUALITY_SCORE:
            record["excluded"] = True
            record["exclusion_reason"] = "quality_score_below_floor"
            record["selection_reason"] = "Excluded because the session quality score fell below the minimum training floor."
            excluded.append(record)
        else:
            eligible.append(record)

    selected: List[Dict[str, Any]] = []
    max_keep = max(0, int(max_sessions or 0))
    if max_keep <= 0:
        for record in eligible:
            record["excluded"] = True
            record["exclusion_reason"] = "selection_capacity_zero"
            record["selection_reason"] = "Excluded because the selection capacity for this pool is zero."
            excluded.append(record)
        return {
            "selection_version": QUALITY_SELECTION_VERSION,
            "included_records": [],
            "excluded_records": _summarize_selection_records(excluded),
            "candidate_count": len(records),
            "included_count": 0,
            "excluded_count": len(excluded),
            "activity_band_counts": {},
        }

    floors = list(required_activity_bands or [])
    for band in floors:
        if len(selected) >= max_keep:
            break
        band_candidates = [record for record in eligible if record not in selected and record.get("activity_band") == band]
        if not band_candidates:
            continue
        band_candidates.sort(key=lambda item: (float(item.get("quality_score") or 0.0), float(item.get("recency_score") or 0.0), item.get("session_name", "")), reverse=True)
        chosen = band_candidates[0]
        chosen["diversity_score"] = 1.0
        chosen["selection_score"] = round(0.70 * float(chosen.get("quality_score") or 0.0) + 0.30 * float(chosen.get("recency_score") or 0.0), 6)
        chosen["selection_reason"] = f"Selected to satisfy the {band} activity diversity floor."
        selected.append(chosen)

    while len(selected) < max_keep:
        remaining = [record for record in eligible if record not in selected]
        if not remaining:
            break
        for record in remaining:
            diversity_score = _candidate_novelty(record, selected)
            selection_score = (
                0.55 * float(record.get("quality_score") or 0.0)
                + 0.20 * float(record.get("recency_score") or 0.0)
                + 0.25 * diversity_score
            )
            record["diversity_score"] = round(diversity_score, 6)
            record["selection_score"] = round(selection_score, 6)
        remaining.sort(key=lambda item: (float(item.get("selection_score") or 0.0), float(item.get("quality_score") or 0.0), item.get("session_name", "")), reverse=True)
        chosen = remaining[0]
        if not chosen.get("selection_reason"):
            chosen["selection_reason"] = "Selected by the quality/diversity/recency ranking pipeline."
        selected.append(chosen)

    for record in eligible:
        if record in selected:
            if not record.get("selection_reason"):
                record["selection_reason"] = "Selected by the quality/diversity/recency ranking pipeline."
            continue
        record["excluded"] = True
        record["exclusion_reason"] = "ranked_below_selection_cutoff"
        record["selection_reason"] = "Excluded because higher-ranked sessions covered the available training budget."
        excluded.append(record)

    selected.sort(key=lambda item: (float(item.get("selection_score") or 0.0), float(item.get("quality_score") or 0.0), item.get("session_name", "")), reverse=True)
    activity_band_counts: Dict[str, int] = {}
    for record in selected:
        band = str(record.get("activity_band") or "unknown")
        activity_band_counts[band] = activity_band_counts.get(band, 0) + 1
    return {
        "selection_version": QUALITY_SELECTION_VERSION,
        "included_records": _summarize_selection_records(selected),
        "excluded_records": _summarize_selection_records(excluded),
        "candidate_count": len(records),
        "included_count": len(selected),
        "excluded_count": len(excluded),
        "activity_band_counts": activity_band_counts,
    }


def _emit_local_progress(
    progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]],
    local_fraction: float,
    detail_key: str,
    message_params: Optional[Mapping[str, Any]] = None,
) -> None:
    if not callable(progress_callback):
        return
    try:
        progress_callback(float(max(0.0, min(1.0, local_fraction))), detail_key, dict(message_params or {}))
    except Exception:
        LOGGER.debug("Training progress callback failed during selection seam", exc_info=True)


def build_training_selection(
    positive_candidates: List[Tuple[str, Dict[str, Any]]],
    negative_candidates: List[str],
    *,
    max_enrollment_sessions: int,
    max_protected_sessions: int = 8,
    max_negative_sessions: int = MAX_REFERENCE_NEGATIVE_SESSIONS,
    progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]] = None,
) -> Dict[str, Any]:
    enrollment_records: List[Dict[str, Any]] = []
    protected_records: List[Dict[str, Any]] = []
    total_candidates = max(1, len(positive_candidates) + len(negative_candidates))
    processed_candidates = 0
    _emit_local_progress(progress_callback, 0.02, "training_detail_quality_selection")
    for session_path, meta in positive_candidates:
        eligibility = assess_positive_training_session(
            meta,
            session_path=session_path,
            user_id=str((meta or {}).get("user_id") or ""),
            session_quality_ok_fn=lambda item: True,
            production_allowed_fn=production_positive_training_allowed,
        )
        if not bool(eligibility.get("allowed")):
            continue
        record = _compute_session_quality_record(session_path, meta, role="positive", strict=True)
        if str(meta.get("session_kind") or "").strip().lower() == "enrollment":
            enrollment_records.append(record)
        else:
            protected_records.append(record)
        processed_candidates += 1
        _emit_local_progress(progress_callback, 0.10 + (0.45 * (processed_candidates / total_candidates)), "training_detail_scanning_sessions", {"current": processed_candidates, "total": total_candidates})

    negative_records: List[Dict[str, Any]] = []
    negative_excluded: List[Dict[str, Any]] = []
    for session_path in negative_candidates:
        meta = read_session_metadata(session_path) or {}
        try:
            negative_records.append(_compute_session_quality_record(session_path, meta, role="negative", strict=True))
        except EncryptedSessionReadError:
            negative_excluded.append(
                {
                    "session_name": os.path.basename(session_path),
                    "session_kind": str(meta.get("session_kind") or "unknown"),
                    "role": "negative",
                    "quality_score": 0.0,
                    "quality_tier": "reject",
                    "selection_score": 0.0,
                    "recency_score": 0.0,
                    "diversity_score": 0.0,
                    "window_budget": 0,
                    "activity_band": None,
                    "duration_band": None,
                    "modality_band": None,
                    "selection_reason": "Excluded because the reference negative session could not be read safely.",
                    "exclusion_reason": "unreadable_or_corrupted",
                    "quality_indicators": {},
                }
            )
        finally:
            processed_candidates += 1
            _emit_local_progress(progress_callback, 0.10 + (0.45 * (processed_candidates / total_candidates)), "training_detail_scanning_sessions", {"current": processed_candidates, "total": total_candidates})

    positive_activity_bands = {record.get("activity_band") for record in enrollment_records if record.get("activity_band") in {"low", "high"}}
    required_bands = []
    for band in ("low", "high"):
        if band in positive_activity_bands:
            required_bands.append(band)

    _emit_local_progress(progress_callback, 0.72, "training_detail_quality_selection")
    enrollment_summary = _build_selection_summary(enrollment_records, max_sessions=max_enrollment_sessions, required_activity_bands=required_bands)
    protected_summary = _build_selection_summary(protected_records, max_sessions=max_protected_sessions)
    selected_positive_records = _resolve_selected_records(enrollment_summary, enrollment_records) + _resolve_selected_records(protected_summary, protected_records)
    negative_summary = _build_negative_selection_summary(
        negative_records,
        max_sessions=max_negative_sessions,
        positive_reference_records=selected_positive_records,
    )
    if negative_excluded:
        negative_summary["excluded_records"].extend(negative_excluded)
        negative_summary["excluded_count"] = len(negative_summary["excluded_records"])
        negative_summary["candidate_count"] += len(negative_excluded)

    selection_window_limits: Dict[str, int] = {}
    positives: List[str] = []
    for summary, source_records in ((enrollment_summary, enrollment_records), (protected_summary, protected_records), (negative_summary, negative_records)):
        lookup = {record["session_name"]: record for record in source_records}
        for item in summary["included_records"]:
            record = lookup.get(item["session_name"])
            if not record:
                continue
            selection_window_limits[record["session_path"]] = int(record.get("window_budget") or MAX_TRAIN_WINDOWS_PER_SESSION)
            if record.get("role") == "positive":
                positives.append(record["session_path"])
    negatives = []
    negative_lookup = {record["session_name"]: record for record in negative_records}
    for item in negative_summary["included_records"]:
        record = negative_lookup.get(item["session_name"])
        if not record:
            continue
        negatives.append(record["session_path"])

    _emit_local_progress(progress_callback, 1.0, "training_detail_quality_selection")
    return {
        "selection_version": QUALITY_SELECTION_VERSION,
        "training_session_eligibility_version": TRAINING_SESSION_ELIGIBILITY_VERSION,
        "negative_mining_version": HARD_NEGATIVE_MINING_VERSION,
        "negative_strategy": negative_summary.get("negative_strategy"),
        "positive_sessions": positives,
        "negative_sessions": negatives,
        "session_window_limits": selection_window_limits,
        "included_sessions": enrollment_summary["included_records"] + protected_summary["included_records"] + negative_summary["included_records"],
        "excluded_sessions": enrollment_summary["excluded_records"] + protected_summary["excluded_records"] + negative_summary["excluded_records"],
        "positive_pool": {
            "enrollment": enrollment_summary,
            "protected": protected_summary,
        },
        "negative_pool": negative_summary,
    }


__all__ = [
    "HARD_NEGATIVE_MINING_VERSION",
    "MIN_SELECTION_QUALITY_SCORE",
    "QUALITY_SELECTION_VERSION",
    "build_training_selection",
]
