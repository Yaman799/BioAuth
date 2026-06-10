"""Compatibility facade for the stable training API.

Phase 1 keeps the legacy public API stable while allowing selected helpers to
move behind ``training_core`` without forcing eager imports of the full
``model_training`` pipeline.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "CALIBRATION_VERSION",
    "CHALLENGER_MAX_FAR_DEGRADATION",
    "CHALLENGER_MAX_FRR_DEGRADATION",
    "CHALLENGER_MIN_AUC_IMPROVEMENT",
    "CHALLENGER_MIN_F1_IMPROVEMENT",
    "CHALLENGER_SELECTION_VERSION",
    "CONTEXT_SELECTION_VERSION",
    "CPU_PARALLELISM_RESERVED_CORES",
    "HARD_NEGATIVE_MINING_VERSION",
    "LIGHTWEIGHT_OFFLINE_EVAL_MIN_NEGATIVE_SESSIONS",
    "LIGHTWEIGHT_OFFLINE_EVAL_MIN_POSITIVE_SESSIONS",
    "MIN_CALIBRATION_CONTEXT_COVERAGE",
    "MIN_CALIBRATION_POSITIVE_SESSIONS",
    "MIN_CALIBRATION_POSITIVE_WINDOW_SAMPLES",
    "MIN_SELECTION_QUALITY_SCORE",
    "QUALITY_SELECTION_VERSION",
    "SEQUENCE_FEATURES_VERSION",
    "SUPERVISED_SELECTION_HOLDOUT_FRACTION",
    "TRAINING_PROGRESS_HEARTBEAT_INTERVAL_SECONDS",
    "TRANSITION_ACTIVITY_SHIFT_THRESHOLD",
    "TRANSITION_KEEP_RATIO",
    "TRANSITION_MIN_KEEP_WINDOWS",
    "TRANSITION_POLICY_VERSION",
    "TRANSITION_POST_IDLE_GAP_SECONDS",
    "TRANSITION_SESSION_START_SECONDS",
    "USING_PYOD",
    "EncryptedSessionReadError",
    "build_matrix",
    "build_training_selection",
    "build_classical_candidate_artifacts",
    "build_optional_supervised_candidate_artifacts",
    "build_deep_oneclass_candidate_artifacts",
    "build_keyboard_deep_candidate_artifacts",
    "build_deep_sequence_candidate_artifacts",
    "build_report_only_candidate_artifacts",
    "build_report_only_candidate_artifacts_unavailable",
    "summarize_candidate_artifact_build",
    "extract_from_session",
    "extract_window_samples_from_session",
    "get_anomaly_scores",
    "normalize_feature_dict",
    "read_csv_encrypted",
    "train_model",
    "train_supervised_classifier_candidates",
    "train_user_model",
]

_SELECTION_EXPORTS = {
    "HARD_NEGATIVE_MINING_VERSION",
    "MIN_SELECTION_QUALITY_SCORE",
    "QUALITY_SELECTION_VERSION",
    "build_training_selection",
}

_TRANSITION_EXPORTS = {
    "SEQUENCE_FEATURES_VERSION",
    "TRANSITION_ACTIVITY_SHIFT_THRESHOLD",
    "TRANSITION_KEEP_RATIO",
    "TRANSITION_MIN_KEEP_WINDOWS",
    "TRANSITION_POLICY_VERSION",
    "TRANSITION_POST_IDLE_GAP_SECONDS",
    "TRANSITION_SESSION_START_SECONDS",
}

_CALIBRATION_EXPORTS = {
    "CALIBRATION_VERSION",
    "MIN_CALIBRATION_CONTEXT_COVERAGE",
    "MIN_CALIBRATION_POSITIVE_SESSIONS",
    "MIN_CALIBRATION_POSITIVE_WINDOW_SAMPLES",
}

_DATA_EXPORTS = {
    "EncryptedSessionReadError",
    "build_matrix",
    "extract_from_session",
    "extract_window_samples_from_session",
    "get_anomaly_scores",
    "normalize_feature_dict",
    "read_csv_encrypted",
}

_CONTEXT_EXPORTS = {
    "CONTEXT_SELECTION_VERSION",
}

_CANDIDATE_ARTIFACT_BUILDER_EXPORTS = {
    "build_classical_candidate_artifacts",
    "build_optional_supervised_candidate_artifacts",
    "build_deep_oneclass_candidate_artifacts",
    "build_keyboard_deep_candidate_artifacts",
    "build_deep_sequence_candidate_artifacts",
    "build_report_only_candidate_artifacts",
    "build_report_only_candidate_artifacts_unavailable",
    "summarize_candidate_artifact_build",
}

_PIPELINE_EXPORTS = {
    "TRAINING_PROGRESS_HEARTBEAT_INTERVAL_SECONDS",
}

_SUPERVISED_EXPORTS = {
    "CHALLENGER_MAX_FAR_DEGRADATION",
    "CHALLENGER_MAX_FRR_DEGRADATION",
    "CHALLENGER_MIN_AUC_IMPROVEMENT",
    "CHALLENGER_MIN_F1_IMPROVEMENT",
    "CHALLENGER_SELECTION_VERSION",
    "SUPERVISED_SELECTION_HOLDOUT_FRACTION",
}


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    if name in _SELECTION_EXPORTS:
        module_name = "training_core.selection"
    elif name in _TRANSITION_EXPORTS:
        module_name = "training_core.transitions"
    elif name in _CALIBRATION_EXPORTS:
        module_name = "training_core.calibration"
    elif name in _DATA_EXPORTS:
        module_name = "training_core.data"
    elif name in _CONTEXT_EXPORTS:
        module_name = "training_core.context_models"
    elif name in _SUPERVISED_EXPORTS:
        module_name = "training_core.supervised"
    elif name in _CANDIDATE_ARTIFACT_BUILDER_EXPORTS:
        module_name = "training_core.candidate_artifact_builders"
    elif name in _PIPELINE_EXPORTS:
        module_name = "training_core.pipeline"
    else:
        module_name = "model_training"
    module = importlib.import_module(module_name)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
