"""Backward-compatible public model API.

This module now acts as a compatibility facade over focused units:
- ``model_metadata.py`` for model/session metadata and path helpers
- ``model_training.py`` for training-time feature extraction and fitting
- ``model_inference.py`` for runtime prediction and risk scoring
- ``shadow_model.py`` for shadow lifecycle + promotion
- ``artifact_integrity.py`` for artifact verification / loading

Keeping this facade preserves older imports and tests while making the ML flow easier to
reason about and maintain.
"""

from __future__ import annotations

import importlib

import artifact_integrity as _artifact_integrity_module
import model_inference as _model_inference_module
import model_evaluation as _model_evaluation_module
import model_policy as _model_policy_module
import model_metadata as _model_metadata_module
import model_training as _model_training_module
import shadow_model as _shadow_model_module

# Reload focused modules whenever this compatibility facade is reloaded. Tests patch
# ``paths`` and then reload ``model`` to point storage into a temporary directory.
_model_metadata_module = importlib.reload(_model_metadata_module)
_artifact_integrity_module = importlib.reload(_artifact_integrity_module)
_model_training_module = importlib.reload(_model_training_module)
_model_inference_module = importlib.reload(_model_inference_module)
_model_evaluation_module = importlib.reload(_model_evaluation_module)
_model_policy_module = importlib.reload(_model_policy_module)
_shadow_model_module = importlib.reload(_shadow_model_module)

from artifact_integrity import (  # noqa: E402
    SecurityError,
    copy_verified_temp as _copy_verified_temp,
    load_classifier,
    load_metadata,
    load_model,
    remove_classifier_sidecar as _remove_classifier_sidecar,
    save_classifier_sidecar as _save_classifier_sidecar,
    verify_tmp_copy as _verify_tmp_copy,
)
from bioauth_model.scoring import (  # noqa: E402
    DEFAULT_RISK_SENSITIVITY,
    RISK_SENSITIVITY_PRESETS,
    compute_risk,
    normalize_sensitivity_preset,
    resolve_sensitivity_config,
    weighted_average as _weighted_average,
)
from model_evaluation import (  # noqa: E402
    EVALUATION_REPORT_FILENAME,
    EVALUATION_SCHEMA_VERSION,
    EVALUATION_SUMMARY_FILENAME,
    evaluate_candidate_model,
    plan_session_holdout_split,
)
from model_inference import (  # noqa: E402
    load_user_model,
    predict_from_session,
    predict_live_session,
    predict_live_session_for_user,
)
from model_policy import POLICY_VERSION, evaluate_model_policy  # noqa: E402
from model_metadata import (  # noqa: E402
    CLASSIFIER_FILE,
    KB_HEADER,
    LIVE_SESSION_DIR,
    MAX_ENROLLMENT_TRAINING_SESSIONS,
    MAX_PREDICT_WINDOWS,
    MAX_REFERENCE_NEGATIVE_SESSIONS,
    MAX_TRAIN_WINDOWS_PER_SESSION,
    METADATA_FILE,
    MIN_NEGATIVE_WINDOW_SAMPLES,
    MIN_POSITIVE_WINDOW_SAMPLES,
    MIN_REQUIRED_ENROLLMENT_SESSIONS,
    MIN_WINDOW_EVENTS,
    MODEL_FILE,
    MODELS_DIR,
    FEATURE_SCHEMA_VERSION,
    FEATURE_WINDOW_STRATEGY,
    ACTIVE_WINDOW_SCALES,
    MS_HEADER,
    PREDICT_WINDOW_STEP_SECONDS,
    RECOMMENDED_ENROLLMENT_SESSIONS,
    SESSIONS_DIR,
    SHADOW_BACKUP_DAYS,
    SHADOW_DISCARD_THRESHOLD,
    SHADOW_EVAL_SESSIONS,
    SHADOW_LOCK_STALE_SECONDS,
    SHADOW_MAX_SESSIONS,
    SHADOW_MIN_SESSIONS,
    SHADOW_PROMOTE_THRESHOLD,
    WINDOW_SECONDS,
    WINDOW_STEP_SECONDS,
    _backup_model_dir,
    _collect_negative_sessions_for_user,
    _format_timestamp,
    _is_accepted_session,
    _now_timestamp,
    _parse_timestamp_value,
    _read_text_file,
    _session_bucket,
    _session_quality_ok,
    _shadow_lock_path,
    _shadow_model_dir,
    _shadow_model_paths,
    _shadow_state_defaults,
    _shadow_state_path,
    _unique_existing_paths,
    _user_model_dir,
    _user_model_paths,
    _user_production_paths,
    _user_session_paths,
    resolve_active_runtime_paths,
    runtime_feature_schema_mismatch_reason,
    write_active_runtime_pointer,
    delete_user_data,
    list_session_dirs,
    read_session_metadata,
    reset_user_profile,
    summarize_user_sessions,
    user_profile_status,
)
from model_training import (  # noqa: E402
    USING_PYOD,
    IForest,
    build_matrix as _build_matrix,
    extract_from_session,
    extract_window_samples_from_session,
    get_anomaly_scores as _get_anomaly_scores,
    normalize_feature_dict as _normalize_feature_dict,
    read_csv_encrypted,
    train_model,
    train_user_model,
)
from security import atomic_write_bytes, atomic_write_text, save_metadata_hash, save_model_hash  # noqa: E402
from shadow_model import (  # noqa: E402
    _read_shadow_state,
    _remove_shadow_artifacts,
    _reset_shadow_state,
    _shadow_eval_log,
    _shadow_lock,
    _shadow_lock_is_stale,
    _shadow_session_ok,
    _write_shadow_eval_log,
    _write_shadow_state,
    cleanup_old_backups,
    dismiss_shadow_suggestion,
    evaluate_shadow_vs_main,
    get_shadow_status,
    list_shadow_backlog_sessions,
    log_shadow_event,
    promote_shadow_model,
    register_legit_session_for_shadow,
    train_shadow_model,
)


__all__ = [name for name in globals() if not name.startswith("__")]


if __name__ == "__main__":
    train_model()
