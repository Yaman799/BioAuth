"""Offline evaluation helpers for trained BioAuth model bundles."""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from artifact_integrity import load_classifier, load_metadata, load_model
from evaluation_core.candidate import evaluate_candidate_model
from evaluation_core.metrics import _binary_metrics, _false_accept_false_reject_rates, _predicted_intruder, _session_truth_label, evaluate_model_bundle
from evaluation_core.safety_metrics import SAFETY_METRICS_SCHEMA_VERSION, calculate_user_facing_safety_metrics
from evaluation_core.planning import _aggregate_cross_validation_evaluations, _evaluate_current_production_bundle, plan_session_cross_validation_splits, plan_session_holdout_split
from evaluation_core.reporting import _build_summary_markdown, _write_evaluation_files, build_closed_beta_report
from model_inference import predict_from_session_details
from model_metadata import resolve_active_runtime_paths
from model_training import train_model
from security import atomic_write_text

EVALUATION_SCHEMA_VERSION = "1.0"
EVALUATION_REPORT_FILENAME = "evaluation_report.json"
EVALUATION_SUMMARY_FILENAME = "evaluation_summary.md"
BETA_EVALUATION_REPORT_FILENAME = "closed_beta_report.md"


def _emit_evaluation_progress(progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]], fraction: Any, detail_key: str = "", message_params: Optional[Mapping[str, Any]] = None) -> None:
    if not callable(progress_callback):
        return
    try:
        progress_callback(max(0.0, min(1.0, float(fraction))), str(detail_key or ""), dict(message_params or {}))
    except Exception:
        pass


def _now_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _unique_paths(paths: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for path in paths:
        normalized = os.path.normcase(os.path.abspath(str(path or "").strip()))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(os.path.abspath(path))
    return out


def _safe_session_name(path: str) -> str:
    return os.path.basename(os.path.abspath(path)) or str(path)


def _safe_score(value: Any) -> float:
    try:
        score = float(value)
    except Exception:
        score = 0.0
    try:
        import numpy as np
        if not np.isfinite(score):
            score = 0.0
    except Exception:
        if score != score:
            score = 0.0
    return score
