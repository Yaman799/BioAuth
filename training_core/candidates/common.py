from __future__ import annotations

import importlib
import math
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from bioauth_model.classical_baselines import BASELINE_SCORE_DIRECTION, CLASSICAL_BASELINE_SCHEMA_VERSION
from utils.dependency_probe import dependency_available, safe_dependency_version

from .constants import (
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    CLASSICAL_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    DEFAULT_THRESHOLD_QUANTILE,
    MAX_DENSITY_MODEL_FEATURES,
)

def _matrix(values: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.ndim != 2:
        raise ValueError("candidate artifact training input must be a 2D matrix")
    return np.where(np.isfinite(arr), arr, 0.0)


def _finite_quantile(values: Sequence[float] | np.ndarray, quantile: float = DEFAULT_THRESHOLD_QUANTILE) -> float | None:
    arr = np.asarray(values, dtype=float).reshape(-1)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    return float(np.quantile(finite, float(quantile)))


def _decision(score: float | None, threshold: float | None) -> str:
    if score is None or threshold is None:
        return "abstain"
    return "intruder" if float(score) >= float(threshold) else "genuine"


def _safe_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)
    return int(parsed)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dependency_available(module_name: str) -> bool:
    facade = sys.modules.get("training_core.candidate_artifact_builders")
    override = getattr(facade, "_dependency_available", None) if facade is not None else None
    if override is not None and override is not _dependency_available:
        return bool(override(module_name))
    return dependency_available(str(module_name or ""), require_import=True)


def _feature_dimension_reason(X: np.ndarray) -> str | None:
    if X.ndim != 2 or X.shape[1] < 1:
        return "window_feature_empty"
    if X.shape[1] > MAX_DENSITY_MODEL_FEATURES and X.shape[0] < (X.shape[1] * 2):
        return "insufficient_samples_for_feature_dimension"
    return None


def _artifact_metadata(
    *,
    candidate_id: str,
    model_family: str,
    feature_names: Sequence[str],
    feature_schema_version: str | None,
    threshold: float | None,
    threshold_source: str,
    training_sample_count: int,
    hyperparameters: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_schema": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "builder_version": CLASSICAL_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        "candidate_id": str(candidate_id),
        "model_family": str(model_family),
        "feature_names": [str(name) for name in feature_names],
        "feature_schema_version": feature_schema_version,
        "threshold": None if threshold is None else float(threshold),
        "decision_threshold": None if threshold is None else float(threshold),
        "threshold_source": str(threshold_source or "not_available"),
        "training_sample_count": int(training_sample_count),
        "score_direction": BASELINE_SCORE_DIRECTION,
        "trained_on": "genuine_owner_windows_only",
        "report_only": True,
        "can_lock": False,
        "can_lock_alone": False,
        "can_influence_device": False,
        "runtime_authoritative": False,
        "trigger_face_confirmation": False,
        "production_selection_performed": False,
        "promotion_performed": False,
        "artifact_serialization": "pickle",
        "artifact_trust_boundary": "trusted_local_candidate_bundle_only",
        "classical_baseline_schema_version": CLASSICAL_BASELINE_SCHEMA_VERSION,
        "hyperparameters": dict(hyperparameters or {}),
    }
    if isinstance(extra, Mapping):
        payload.update(dict(extra))
    return payload

def _dependency_version(module_name: str) -> str | None:
    return safe_dependency_version(str(module_name or ""))
