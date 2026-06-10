"""Training-time data extraction and model fitting."""

from __future__ import annotations

import inspect
import json
import logging
import os
import pickle
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from auth import mark_profile_state
from app_settings import demo_classic_protected_enabled
from deep_sequence.training import train_sequence_model_candidate
from artifact_integrity import load_metadata as load_artifact_metadata
from artifact_integrity import remove_classifier_sidecar, save_classifier_sidecar
from bioauth_model.scoring import DEFAULT_RISK_SENSITIVITY, classifier_training_summary
from features import (
    annotate_sequence_trend_windows,
    annotate_transition_windows,
    extract_session_quality_indicators,
)
from model_metadata import (
    KB_HEADER,
    MS_HEADER,
    CLASSIFIER_FILE,
    CONTEXT_ROUTER_MIN_CONFIDENCE,
    CONTEXT_ROUTING_VERSION,
    FEATURE_SCHEMA_VERSION,
    FEATURE_WINDOW_STRATEGY,
    MAX_ENROLLMENT_TRAINING_SESSIONS,
    MAX_PREDICT_WINDOWS,
    MAX_REFERENCE_NEGATIVE_SESSIONS,
    MAX_TRAIN_WINDOWS_PER_SESSION,
    METADATA_FILE,
    MIN_CONTEXT_POSITIVE_SESSION_SUPPORT,
    MIN_CONTEXT_POSITIVE_WINDOW_SAMPLES,
    MIN_NEGATIVE_WINDOW_SAMPLES,
    MIN_POSITIVE_WINDOW_SAMPLES,
    MIN_REQUIRED_ENROLLMENT_SESSIONS,
    MIN_WINDOW_EVENTS,
    MODEL_FILE,
    PREDICT_WINDOW_STEP_SECONDS,
    RECOMMENDED_ENROLLMENT_SESSIONS,
    ACTIVE_WINDOW_SCALES,
    WINDOW_SECONDS,
    WINDOW_STEP_SECONDS,
    ROUTER_CONTEXTS,
    _collect_negative_sessions_for_user,
    _is_accepted_session,
    _session_quality_ok,
    _user_model_paths,
    _user_production_paths,
    _user_session_paths,
    resolve_active_runtime_paths,
    write_active_runtime_pointer,
    user_model_lifecycle_lock,
    list_session_dirs,
    read_session_metadata,
)
from security import atomic_write_bytes, atomic_write_text, save_metadata_hash, save_model_hash
from training_core.calibration import (
    CALIBRATION_VERSION,
    MIN_CALIBRATION_CONTEXT_COVERAGE,
    MIN_CALIBRATION_POSITIVE_SESSIONS,
    MIN_CALIBRATION_POSITIVE_WINDOW_SAMPLES,
    _compute_user_calibration_profile,
    _score_percentiles_dict,
    _session_level_raw_percentiles,
)
from training_core.data import (
    EncryptedSessionReadError,
    _normalize_window_scales,
    _per_scale_sample_counts,
    _scale_metadata_label,
    build_matrix,
    extract_from_session,
    extract_window_samples_from_session,
    get_anomaly_scores,
    normalize_feature_dict,
    read_csv_encrypted,
)
from training_core.context_models import (
    CONTEXT_SELECTION_VERSION,
    _context_dir,
    train_context_submodels as _train_context_submodels_impl,
)
from training_core.selection import (
    HARD_NEGATIVE_MINING_VERSION,
    MIN_SELECTION_QUALITY_SCORE,
    QUALITY_SELECTION_VERSION,
    _clamp01,
    build_training_selection as build_training_selection,
)
from training_core.supervised import (
    CHALLENGER_MAX_FAR_DEGRADATION,
    CHALLENGER_MAX_FRR_DEGRADATION,
    CHALLENGER_MIN_AUC_IMPROVEMENT,
    CHALLENGER_MIN_F1_IMPROVEMENT,
    CHALLENGER_SELECTION_VERSION,
    SUPERVISED_SELECTION_HOLDOUT_FRACTION,
    _challenger_respects_error_rate_guards as _challenger_respects_error_rate_guards_impl,
    _classifier_probability_values as _classifier_probability_values_impl,
    _evaluate_supervised_candidate as _evaluate_supervised_candidate_impl,
    _false_accept_false_reject_rates as _false_accept_false_reject_rates_impl,
    _make_supervised_classifier as _make_supervised_classifier_impl,
    _ordered_unique_strings as _ordered_unique_strings_impl,
    _select_primary_supervised_family as _select_primary_supervised_family_impl,
    _select_supervised_validation_indices as _select_supervised_validation_indices_impl,
    train_supervised_classifier_candidates as _train_supervised_classifier_candidates_impl,
)
from hybrid_pro_metadata_normalization import normalize_hybrid_pro_artifact_metadata
from training_core.pipeline import (
    TRAINING_PROGRESS_HEARTBEAT_INTERVAL_SECONDS,
    _ProgressHeartbeat,
    _emit_local_progress,
    _merge_progress_message_params,
    _summarize_sequence_feature_family,
    _training_result,
    train_model as _train_model_impl,
    train_user_model as _train_user_model_impl,
)
from training_core.transitions import (
    SEQUENCE_FEATURES_VERSION,
    TRANSITION_ACTIVITY_SHIFT_THRESHOLD,
    TRANSITION_KEEP_RATIO,
    TRANSITION_MIN_KEEP_WINDOWS,
    TRANSITION_POLICY_VERSION,
    TRANSITION_POST_IDLE_GAP_SECONDS,
    TRANSITION_SESSION_START_SECONDS,
    _apply_transition_window_policy,
    _summarize_transition_training,
)

LOGGER = logging.getLogger(__name__)

LIGHTWEIGHT_OFFLINE_EVAL_MIN_POSITIVE_SESSIONS = 10
LIGHTWEIGHT_OFFLINE_EVAL_MIN_NEGATIVE_SESSIONS = 3
CPU_PARALLELISM_RESERVED_CORES = 1


def _coerce_candidate_training_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value)
        return bool(default)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled", ""}:
            return False
    return bool(default)


def _running_under_pytest() -> bool:
    """Return True only for active pytest test execution.

    Candidate artifact builders can legitimately train optional PyTorch, XGBoost,
    LightGBM, or CatBoost artifacts.  That is desired in the real Train Profile
    flow, but legacy unit tests call ``train_user_model()`` many times to verify
    unrelated security and metadata behavior.  Keep production defaults intact
    while making those tests deterministic and fast unless a test explicitly opts
    in through a function argument or environment override.
    """

    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _candidate_artifact_test_default_enabled() -> bool:
    override = os.environ.get("BIOAUTH_ENABLE_CANDIDATE_ARTIFACTS_IN_TESTS")
    if override is not None:
        return _coerce_candidate_training_bool(override, default=False)
    return not _running_under_pytest()


def _candidate_training_settings() -> Dict[str, bool]:
    settings: Dict[str, Any] = {}
    try:
        from app_settings import load_settings

        settings = load_settings()
    except Exception:
        settings = {}
    default_candidate_enabled = _candidate_artifact_test_default_enabled()
    if _running_under_pytest() and os.environ.get("BIOAUTH_ENABLE_CANDIDATE_ARTIFACTS_IN_TESTS") is None:
        # Unit tests that need candidate artifacts can still pass explicit
        # train_model()/train_user_model() switches.  This branch only changes
        # implicit defaults for legacy tests exercising unrelated training paths.
        return {
            "enable_candidate_artifacts": False,
            "enable_deep_candidate_artifacts": False,
            "strict_candidate_training": False,
        }
    return {
        "enable_candidate_artifacts": _coerce_candidate_training_bool(settings.get("enable_candidate_artifacts", default_candidate_enabled), default=default_candidate_enabled),
        "enable_deep_candidate_artifacts": _coerce_candidate_training_bool(settings.get("enable_deep_candidate_artifacts", default_candidate_enabled), default=default_candidate_enabled),
        "strict_candidate_training": _coerce_candidate_training_bool(settings.get("strict_candidate_training", False), default=False),
    }


def _cpu_parallel_jobs(*, reserve_cores: int = CPU_PARALLELISM_RESERVED_CORES) -> int:
    """Return a safe parallelism budget that keeps the desktop UI responsive.

    Using every logical core can starve the GUI and background maintenance threads on
    smaller systems. Reserving one core still unlocks multi-core fitting while keeping
    the app usable during long training runs.
    """

    cpu_total = int(os.cpu_count() or 1)
    reserved = max(0, int(reserve_cores))
    return max(1, cpu_total - reserved)


def _supports_n_jobs_parameter(factory: Any) -> bool:
    try:
        return "n_jobs" in inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return False


def _iforest_fit_kwargs(contamination: float) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"contamination": float(contamination), "random_state": 42}
    if _supports_n_jobs_parameter(IForest):
        kwargs["n_jobs"] = _cpu_parallel_jobs()
    return kwargs


def _allow_expensive_offline_evaluation(positive_sessions: List[str], negative_sessions: List[str]) -> bool:
    """Only run temporary retraining-based evaluation when the session pool is large enough.

    Small enrollment sets already pay a noticeable cost for the main training pass. Re-running
    multiple temporary split models immediately afterward makes the UI feel frozen without adding
    much signal. Candidate-bundle evaluation still runs for every training job.
    """

    positive_count = len({os.path.normcase(os.path.abspath(path)) for path in list(positive_sessions or []) if path})
    negative_count = len({os.path.normcase(os.path.abspath(path)) for path in list(negative_sessions or []) if path})
    if positive_count < LIGHTWEIGHT_OFFLINE_EVAL_MIN_POSITIVE_SESSIONS:
        return False
    if negative_sessions and negative_count < LIGHTWEIGHT_OFFLINE_EVAL_MIN_NEGATIVE_SESSIONS:
        return False
    return True


def _publish_initial_production_bundle_if_approved(user_id: str, candidate_paths: Mapping[str, str], policy_decision: Mapping[str, Any]) -> bool:
    """Publish the freshly trained candidate as the first runtime bundle when policy allows it.

    Runtime loading in phase 10 requires an active production-approved bundle. Without this
    initial publication step, the UI can report training success while protected sessions fail
    immediately because the runtime has nothing production-ready to load.
    """

    model_status = str((policy_decision or {}).get("model_status") or "").strip().lower()
    demo_publish = bool(
        demo_classic_protected_enabled()
        and model_status in {"approved_for_shadow", "shadow_validation"}
    )
    if model_status != "approved_for_production" and not demo_publish:
        return False

    from artifact_integrity import load_classifier, load_metadata, load_model
    from utils.identity import slugify_username

    safe = slugify_username(user_id)
    runtime_paths = resolve_active_runtime_paths(safe)
    if runtime_paths and os.path.exists(runtime_paths.get("model", "")) and os.path.exists(runtime_paths.get("metadata", "")):
        try:
            runtime_meta = load_metadata(runtime_paths["metadata"]) or {}
        except Exception:
            runtime_meta = {}
        if str(runtime_meta.get("bundle_role") or "").strip().lower() == "production" and str(runtime_meta.get("model_status") or "").strip().lower() == "approved_for_production":
            return False

    production_paths = _user_production_paths(safe)
    os.makedirs(production_paths["base"], exist_ok=True)

    candidate_meta = load_metadata(str(candidate_paths["metadata"])) or {}
    rollout_details = dict((policy_decision or {}).get("rollout_details") or {})
    published_meta = dict(candidate_meta)
    deep_runtime = dict(published_meta.get("deep_runtime") or {})
    deep_runtime.update({
        "runtime_rollout_stage": (policy_decision or {}).get("rollout_status") or rollout_details.get("rollout_status") or deep_runtime.get("runtime_rollout_stage") or "classic_only_ready",
        "runtime_shadow_only": not bool(rollout_details.get("production_decision_enabled")),
        "runtime_decision_influence_enabled": bool(rollout_details.get("production_decision_enabled")),
        "runtime_shadow_diagnostics_enabled": bool(rollout_details.get("shadow_diagnostics_enabled", True)),
        "runtime_rollback_to_classic_on_failure": bool(rollout_details.get("rollback_to_classic_on_failure", True)),
        "runtime_activation_blocked_reason": rollout_details.get("blocked_reason"),
        "allowed_modes": list(rollout_details.get("allowed_modes") or deep_runtime.get("allowed_modes") or []),
    })
    if demo_publish:
        allowed_modes = list(deep_runtime.get("allowed_modes") or [])
        for mode in ("classic_only_ready", "demo_classic_protected"):
            if mode not in allowed_modes:
                allowed_modes.append(mode)
        deep_runtime.update({
            "runtime_rollout_stage": "demo_classic_protected",
            "runtime_shadow_only": False,
            "runtime_decision_influence_enabled": True,
            "runtime_shadow_diagnostics_enabled": bool(deep_runtime.get("runtime_shadow_diagnostics_enabled", True)),
            "runtime_activation_blocked_reason": None,
            "allowed_modes": allowed_modes,
            "demo_classic_protected": True,
            "classic_runtime_demo_direct": True,
        })
    runtime_publish_source = "demo_classic_protected" if demo_publish else "initial_training"
    published_meta.update(
        {
            "bundle_role": "production",
            "model_status": "approved_for_production",
            "rollout_status": (policy_decision or {}).get("rollout_status"),
            "rollout_details": rollout_details,
            "deep_runtime": deep_runtime,
            "runtime_requires_production_approval": False if demo_publish else True,
            "published_to_runtime_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "runtime_publish_source": runtime_publish_source,
        }
    )
    if demo_publish:
        published_meta.update({
            "demo_classic_protected": True,
            "production_approval_bypassed_for_demo": True,
            "runtime_requires_production_approval": False,
            "runtime_publish_source": "demo_classic_protected",
            "runtime_publish_demo_only": True,
            "runtime_publish_demo_flag": "BIOAUTH_DEMO_CLASSIC_PROTECTED",
            "runtime_publish_source_candidate_status": model_status,
            "original_model_status_before_demo_publish": model_status,
            "production_ready": True,
            "protected_sessions_available": True,
        })

    with open(str(candidate_paths["model"]), "rb") as handle:
        atomic_write_bytes(production_paths["model"], handle.read())
    save_model_hash(production_paths["model"])

    atomic_write_text(production_paths["metadata"], json.dumps(published_meta, indent=2, ensure_ascii=False))
    save_metadata_hash(production_paths["metadata"])

    classifier_src = str(candidate_paths.get("classifier") or "")
    if classifier_src and os.path.exists(classifier_src):
        with open(classifier_src, "rb") as handle:
            atomic_write_bytes(production_paths["classifier"], handle.read())
        save_classifier_sidecar(production_paths["classifier"])
    else:
        try:
            os.remove(production_paths["classifier"])
        except OSError:
            pass
        remove_classifier_sidecar(production_paths["classifier"])

    for extra_name in ("evaluation_report", "evaluation_summary"):
        src = str(candidate_paths.get(extra_name) or "")
        dst = str(production_paths.get(extra_name) or "")
        if src and dst and os.path.exists(src):
            with open(src, "rb") as handle:
                atomic_write_bytes(dst, handle.read())

    load_model(production_paths["model"])
    load_metadata(production_paths["metadata"])
    if os.path.exists(production_paths["classifier"]):
        load_classifier(production_paths["classifier"])
    write_active_runtime_pointer(safe, production_paths, source=("demo_classic_protected" if demo_publish else "initial_training"))
    return True

from sklearn.ensemble import IsolationForest as IForest

# Always use scikit-learn IsolationForest in the training path.
# The optional PyOD wrapper has compatibility problems with the sklearn
# version bundled in the desktop app and can crash before artifacts are
# published. Keeping the public alias name avoids wider refactors.
USING_PYOD = False

LGBMClassifier = getattr(_make_supervised_classifier_impl, "__globals__", {}).get("LGBMClassifier")
USING_LIGHTGBM = bool(getattr(_make_supervised_classifier_impl, "__globals__", {}).get("USING_LIGHTGBM", False))


def _get_label(session_path: str, session_name: str) -> int:
    meta = read_session_metadata(session_path) or {}
    label = str(meta.get("label") or meta.get("final_decision") or meta.get("archive_label") or meta.get("bucket") or "").strip().lower()
    if label in {"intruder", "suspicious", "rejected", "unauthorized"}:
        return 1
    if any(token in session_name.lower() for token in ("intruder", "suspicious", "rejected")):
        return 1
    return 0




def _run_deep_sequence_training(*, sessions: List[str], negative_sessions: List[str], model_file: str, metadata_file: str) -> Dict[str, Any]:
    resolved_sessions = list(sessions or [])
    negative_lookup = {os.path.normcase(os.path.abspath(path)) for path in list(negative_sessions or []) if path}
    labels_by_session: Dict[str, int] = {}
    session_samples: Dict[str, List[Dict[str, float]]] = {}
    feature_names: List[str] = []
    for session_path in resolved_sessions:
        session_key = str(session_path)
        labels_by_session[session_key] = 1 if os.path.normcase(os.path.abspath(session_path)) in negative_lookup else _get_label(session_path, os.path.basename(session_path))
        try:
            window_samples = extract_window_samples_from_session(session_path, window_seconds=WINDOW_SECONDS, step_seconds=WINDOW_STEP_SECONDS, min_total_events=MIN_WINDOW_EVENTS, max_windows=MAX_TRAIN_WINDOWS_PER_SESSION, window_scales=_normalize_window_scales(), strict=True)
        except Exception:
            window_samples = []
        normalized_samples = [normalize_feature_dict(sample) for sample in list(window_samples or [])]
        session_samples[session_key] = normalized_samples
        feature_names.extend(str(name) for sample in normalized_samples for name in sample.keys())
    artifact_path = os.path.join(os.path.dirname(model_file), 'sequence_model.pt')
    result = train_sequence_model_candidate(session_samples=session_samples, feature_names=sorted(set(feature_names)), labels_by_session=labels_by_session, artifact_path=artifact_path, sequence_length=MAX_PREDICT_WINDOWS, stride=1)
    try:
        metadata = load_artifact_metadata(metadata_file) or {}
    except Exception:
        metadata = {}
    deep_runtime = dict(metadata.get('deep_runtime') or {})
    sequence_contract = dict(deep_runtime.get('sequence_model') or {})
    sequence_contract.update({'enabled': bool(result.get('artifact_written')), 'artifact': result.get('artifact_file') if result.get('artifact_written') else None, 'framework': result.get('framework'), 'sequence_length': int(result.get('sequence_length') or MAX_PREDICT_WINDOWS), 'tensor_layout': str(result.get('tensor_layout') or 'NTF'), 'status': str(result.get('status') or 'disabled'), 'trained': bool(result.get('trained')), 'shadow_only': True})
    deep_runtime['deep_sequence_runtime_enabled'] = bool(result.get('artifact_written'))
    deep_runtime['runtime_activation_blocked_reason'] = None if result.get('artifact_written') else 'deep_training_unavailable'
    deep_runtime['runtime_shadow_only'] = True
    deep_runtime['runtime_decision_influence_enabled'] = False
    deep_runtime['runtime_shadow_diagnostics_enabled'] = True
    deep_runtime['sequence_model'] = sequence_contract
    metadata['deep_runtime'] = deep_runtime
    metadata['sequence_data'] = dict(result.get('sequence_data') or {})
    metadata['deep_sequence_training'] = dict(result)
    artifacts = dict(metadata.get('artifacts') or {})
    artifacts['sequence_model'] = result.get('artifact_file') if result.get('artifact_written') else None
    metadata['artifacts'] = artifacts
    layer_artifacts = dict(metadata.get('layer_artifacts') or {})
    hybrid_pro_artifacts = dict(metadata.get('hybrid_pro_artifacts') or {})
    skipped_layers = dict(metadata.get('skipped_layers') or {})
    skip_reason_codes = list(metadata.get('skip_reason_codes') or [])
    if result.get('artifact_written'):
        seq_path = os.path.join(os.path.dirname(model_file), str(result.get('artifact_file') or 'sequence_model.pt'))
        seq_digest = ''
        try:
            import hashlib
            h = hashlib.sha256()
            with open(seq_path, 'rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    h.update(chunk)
            seq_digest = 'sha256:' + h.hexdigest()
        except Exception:
            seq_digest = ''
        sequence_layer = {
            'available': True,
            'trained': True,
            'layer': 'cnn_lstm',
            'model_family': 'cnn_lstm',
            'artifact': result.get('artifact_file'),
            'path': result.get('artifact_file'),
            'digest': seq_digest,
            'reason_codes': [],
        }
        layer_artifacts['cnn_lstm'] = sequence_layer
        hybrid_pro_artifacts['cnn_lstm'] = sequence_layer
        if 'combined' not in layer_artifacts:
            layer_artifacts['combined'] = dict(sequence_layer, layer='combined', model_family='hybrid_pro_cnn_lstm')
            hybrid_pro_artifacts['combined'] = layer_artifacts['combined']
        skipped_layers.pop('cnn_lstm', None)
        skip_reason_codes = [code for code in skip_reason_codes if not str(code).startswith('cnn_lstm_') and code != 'torch_skipped_dependency_missing']
        if 'cnn_lstm_artifact_trained' not in skip_reason_codes:
            skip_reason_codes.append('cnn_lstm_artifact_trained')
        metadata['training_strategy'] = 'hybrid_pro_cnn_lstm' if {'keyboard', 'mouse', 'combined'}.issubset(set(layer_artifacts.keys())) else metadata.get('training_strategy', 'hybrid_pro_partial')
        metadata['model_family'] = 'hybrid_pro_cnn_lstm' if metadata.get('training_strategy') == 'hybrid_pro_cnn_lstm' else metadata.get('model_family', 'hybrid_pro_partial')
        metadata['hybrid_pro_enabled'] = True
    else:
        reason = str(result.get('reason') or 'cnn_lstm_skipped_insufficient_sequence_data')
        mapped_reason = 'cnn_lstm_skipped_insufficient_sequence_data' if reason in {'insufficient_sequence_windows', 'insufficient_label_diversity', 'labels_missing'} else reason
        skipped_layers['cnn_lstm'] = {'available': False, 'trained': False, 'layer': 'cnn_lstm', 'reason_codes': [mapped_reason]}
        if mapped_reason not in skip_reason_codes:
            skip_reason_codes.append(mapped_reason)
    metadata['layer_artifacts'] = layer_artifacts
    metadata['hybrid_pro_artifacts'] = hybrid_pro_artifacts
    metadata['skipped_layers'] = skipped_layers
    metadata['skip_reason_codes'] = skip_reason_codes
    metadata = normalize_hybrid_pro_artifact_metadata(
        metadata,
        bundle_paths={'base': os.path.dirname(model_file), 'model': model_file, 'metadata': metadata_file},
        metadata_path=metadata_file,
        base_dir=os.path.dirname(model_file),
    )
    atomic_write_text(metadata_file, json.dumps(metadata, indent=2, ensure_ascii=False))
    save_metadata_hash(metadata_file)
    return result


# Phase 7 seam: keep selection and transition constants/helper names available
# from this legacy module, while routing the actual implementations through
# ``training_core.selection`` and ``training_core.transitions``.

# Phase 4 seam: keep the legacy private helper surface available from this
# module while delegating routed context bundle training to
# ``training_core.context_models``.


def _train_context_submodels(
    *,
    model_dir: str,
    feature_names: List[str],
    X: np.ndarray,
    y: np.ndarray,
    samples: List[Dict[str, float]],
    sample_sources: List[str],
    active_window_scales: List[float],
    metadata_template: Dict[str, Any],
) -> Dict[str, Any]:
    return _train_context_submodels_impl(
        model_dir=model_dir,
        feature_names=feature_names,
        X=X,
        y=y,
        samples=samples,
        sample_sources=sample_sources,
        active_window_scales=active_window_scales,
        metadata_template=metadata_template,
        iforest_factory=IForest,
        iforest_fit_kwargs_builder=_iforest_fit_kwargs,
        classifier_trainer=train_supervised_classifier_candidates,
        minimum_negative_samples=MIN_NEGATIVE_WINDOW_SAMPLES,
        challenger_selection_version=CHALLENGER_SELECTION_VERSION,
    )


def _ordered_unique_strings(values: List[str]) -> List[str]:
    return _ordered_unique_strings_impl(values)


def _select_supervised_validation_indices(y_clf: np.ndarray, sample_sources: List[str]) -> tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    return _select_supervised_validation_indices_impl(
        y_clf,
        sample_sources,
        holdout_fraction=SUPERVISED_SELECTION_HOLDOUT_FRACTION,
    )


def _make_supervised_classifier(family: str):
    return _make_supervised_classifier_impl(
        family,
        cpu_parallel_jobs=_cpu_parallel_jobs,
        using_lightgbm=USING_LIGHTGBM,
        lgbm_classifier=LGBMClassifier,
        random_forest_classifier=RandomForestClassifier,
    )


def _classifier_probability_values(candidate: Any, X_val: np.ndarray) -> np.ndarray:
    return _classifier_probability_values_impl(candidate, X_val)


def _false_accept_false_reject_rates(*, tn: int, fp: int, fn: int, tp: int) -> tuple[float, float]:
    return _false_accept_false_reject_rates_impl(tn=tn, fp=fp, fn=fn, tp=tp)


def _evaluate_supervised_candidate(candidate: Any, X_val: np.ndarray, y_val: np.ndarray) -> Dict[str, Any]:
    return _evaluate_supervised_candidate_impl(candidate, X_val, y_val)


def _challenger_respects_error_rate_guards(
    baseline: Mapping[str, Any],
    challenger: Mapping[str, Any],
) -> bool:
    return _challenger_respects_error_rate_guards_impl(
        baseline,
        challenger,
        max_far_degradation=CHALLENGER_MAX_FAR_DEGRADATION,
        max_frr_degradation=CHALLENGER_MAX_FRR_DEGRADATION,
    )


def _select_primary_supervised_family(candidate_scores: Mapping[str, Mapping[str, Any]]) -> str:
    return _select_primary_supervised_family_impl(
        candidate_scores,
        challenger_respects_error_rate_guards_fn=_challenger_respects_error_rate_guards,
        min_auc_improvement=CHALLENGER_MIN_AUC_IMPROVEMENT,
        min_f1_improvement=CHALLENGER_MIN_F1_IMPROVEMENT,
    )



def train_supervised_classifier_candidates(
    X_pos: np.ndarray,
    X_neg: np.ndarray,
    *,
    pos_sample_sources: List[str],
    neg_sample_sources: List[str],
    minimum_negative_samples: int,
    progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]] = None,
) -> tuple[Any | None, Dict[str, Any]]:
    return _train_supervised_classifier_candidates_impl(
        X_pos,
        X_neg,
        pos_sample_sources=pos_sample_sources,
        neg_sample_sources=neg_sample_sources,
        minimum_negative_samples=minimum_negative_samples,
        progress_callback=progress_callback,
        emit_progress_fn=_emit_local_progress,
        heartbeat_factory=lambda callback, fraction, detail_key, params=None: _ProgressHeartbeat(
            callback,
            fraction,
            detail_key,
            params,
            clamp01_fn=_clamp01,
            emit_progress_fn=_emit_local_progress,
        ),
        classifier_training_summary_fn=classifier_training_summary,
        select_validation_indices_fn=_select_supervised_validation_indices,
        make_supervised_classifier_fn=_make_supervised_classifier,
        evaluate_candidate_fn=_evaluate_supervised_candidate,
        select_primary_family_fn=_select_primary_supervised_family,
        using_lightgbm=USING_LIGHTGBM,
        lgbm_classifier=LGBMClassifier,
        selection_version=CHALLENGER_SELECTION_VERSION,
        min_auc_improvement=CHALLENGER_MIN_AUC_IMPROVEMENT,
        min_f1_improvement=CHALLENGER_MIN_F1_IMPROVEMENT,
        max_far_degradation=CHALLENGER_MAX_FAR_DEGRADATION,
        max_frr_degradation=CHALLENGER_MAX_FRR_DEGRADATION,
    )


def train_model(
    sessions: Optional[List[str]] = None,
    negative_sessions: Optional[List[str]] = None,
    model_file: str = MODEL_FILE,
    classifier_file: str = CLASSIFIER_FILE,
    metadata_file: str = METADATA_FILE,
    session_window_limits: Optional[Dict[str, int]] = None,
    training_selection: Optional[Mapping[str, Any]] = None,
    progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]] = None,
    enable_deep_sequence_training: bool = True,
    enable_candidate_artifacts: Optional[bool] = None,
    enable_deep_candidate_artifacts: Optional[bool] = None,
    strict_candidate_training: Optional[bool] = None,
) -> Tuple[Optional[Any], str]:
    candidate_settings = _candidate_training_settings()
    resolved_enable_candidate_artifacts = candidate_settings["enable_candidate_artifacts"] if enable_candidate_artifacts is None else bool(enable_candidate_artifacts)
    resolved_enable_deep_candidate_artifacts = candidate_settings["enable_deep_candidate_artifacts"] if enable_deep_candidate_artifacts is None else bool(enable_deep_candidate_artifacts)
    resolved_strict_candidate_training = candidate_settings["strict_candidate_training"] if strict_candidate_training is None else bool(strict_candidate_training)
    model, status = _train_model_impl(
        sessions=sessions,
        negative_sessions=negative_sessions,
        model_file=model_file,
        classifier_file=classifier_file,
        metadata_file=metadata_file,
        session_window_limits=session_window_limits,
        training_selection=training_selection,
        progress_callback=progress_callback,
        list_session_dirs_fn=list_session_dirs,
        normalize_window_scales_fn=_normalize_window_scales,
        emit_progress_fn=_emit_local_progress,
        clamp01_fn=_clamp01,
        progress_heartbeat_factory=lambda callback, fraction, detail_key, params=None: _ProgressHeartbeat(
            callback,
            fraction,
            detail_key,
            params,
            clamp01_fn=_clamp01,
            emit_progress_fn=_emit_local_progress,
        ),
        get_label_fn=_get_label,
        extract_window_samples_from_session_fn=extract_window_samples_from_session,
        annotate_sequence_trend_windows_fn=annotate_sequence_trend_windows,
        annotate_transition_windows_fn=annotate_transition_windows,
        extract_from_session_fn=extract_from_session,
        apply_transition_window_policy_fn=_apply_transition_window_policy,
        normalize_feature_dict_fn=normalize_feature_dict,
        encrypted_session_read_error=EncryptedSessionReadError,
        logger=LOGGER,
        max_train_windows_per_session=MAX_TRAIN_WINDOWS_PER_SESSION,
        window_seconds=WINDOW_SECONDS,
        window_step_seconds=WINDOW_STEP_SECONDS,
        min_window_events=MIN_WINDOW_EVENTS,
        per_scale_sample_counts_fn=_per_scale_sample_counts,
        sequence_feature_summary_fn=lambda feature_names: _summarize_sequence_feature_family(
            feature_names,
            sequence_features_version=SEQUENCE_FEATURES_VERSION,
        ),
        build_matrix_fn=build_matrix,
        min_positive_window_samples=MIN_POSITIVE_WINDOW_SAMPLES,
        iforest_factory=IForest,
        iforest_fit_kwargs_fn=_iforest_fit_kwargs,
        get_anomaly_scores_fn=get_anomaly_scores,
        score_percentiles_dict_fn=_score_percentiles_dict,
        train_supervised_classifier_candidates_fn=train_supervised_classifier_candidates,
        min_negative_window_samples=MIN_NEGATIVE_WINDOW_SAMPLES,
        remove_classifier_sidecar_fn=remove_classifier_sidecar,
        atomic_write_bytes_fn=atomic_write_bytes,
        save_model_hash_fn=save_model_hash,
        save_classifier_sidecar_fn=save_classifier_sidecar,
        atomic_write_text_fn=atomic_write_text,
        save_metadata_hash_fn=save_metadata_hash,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_window_strategy=FEATURE_WINDOW_STRATEGY,
        predict_window_step_seconds=PREDICT_WINDOW_STEP_SECONDS,
        max_predict_windows=MAX_PREDICT_WINDOWS,
        recommended_enrollment_sessions=RECOMMENDED_ENROLLMENT_SESSIONS,
        default_risk_sensitivity=DEFAULT_RISK_SENSITIVITY,
        classifier_selection_version=CHALLENGER_SELECTION_VERSION,
        train_context_submodels_fn=_train_context_submodels,
        context_selection_version=CONTEXT_SELECTION_VERSION,
        summarize_transition_training_fn=_summarize_transition_training,
        transition_policy_version=TRANSITION_POLICY_VERSION,
        transition_session_start_seconds=TRANSITION_SESSION_START_SECONDS,
        transition_post_idle_gap_seconds=TRANSITION_POST_IDLE_GAP_SECONDS,
        transition_activity_shift_threshold=TRANSITION_ACTIVITY_SHIFT_THRESHOLD,
        transition_keep_ratio=TRANSITION_KEEP_RATIO,
        transition_min_keep_windows=TRANSITION_MIN_KEEP_WINDOWS,
        compute_user_calibration_profile_fn=_compute_user_calibration_profile,
        enable_candidate_artifacts=resolved_enable_candidate_artifacts,
        enable_deep_candidate_artifacts=resolved_enable_deep_candidate_artifacts,
        strict_candidate_training=resolved_strict_candidate_training,
    )
    if model is not None and status == "ok" and enable_deep_sequence_training:
        try:
            _run_deep_sequence_training(sessions=list(sessions or []), negative_sessions=list(negative_sessions or []), model_file=model_file, metadata_file=metadata_file)
        except Exception as exc:
            LOGGER.warning("Deep sequence training skipped: %s", exc, exc_info=True)
    return model, status


def train_user_model(
    user_id: str,
    min_sessions: int = MIN_REQUIRED_ENROLLMENT_SESSIONS,
    max_enrollment_sessions: int = MAX_ENROLLMENT_TRAINING_SESSIONS,
    progress_callback: Optional[Callable[[Mapping[str, Any]], None]] = None,
    enable_candidate_artifacts: Optional[bool] = None,
    enable_deep_candidate_artifacts: Optional[bool] = None,
    strict_candidate_training: Optional[bool] = None,
) -> Dict[str, Any]:
    from utils.identity import slugify_username

    safe = slugify_username(user_id)

    def _train_model_with_candidate_switches(**kwargs: Any) -> Tuple[Optional[Any], str]:
        kwargs.setdefault("enable_candidate_artifacts", enable_candidate_artifacts)
        kwargs.setdefault("enable_deep_candidate_artifacts", enable_deep_candidate_artifacts)
        kwargs.setdefault("strict_candidate_training", strict_candidate_training)
        return train_model(**kwargs)

    return _train_user_model_impl(
        safe=safe,
        min_sessions=min_sessions,
        max_enrollment_sessions=max_enrollment_sessions,
        progress_callback=progress_callback,
        clamp01_fn=_clamp01,
        logger=LOGGER,
        user_model_lifecycle_lock_fn=user_model_lifecycle_lock,
        user_model_paths_fn=_user_model_paths,
        user_session_paths_fn=_user_session_paths,
        read_session_metadata_fn=read_session_metadata,
        is_accepted_session_fn=_is_accepted_session,
        session_quality_ok_fn=_session_quality_ok,
        mark_profile_state_fn=mark_profile_state,
        collect_negative_sessions_fn=_collect_negative_sessions_for_user,
        build_training_selection_fn=build_training_selection,
        train_model_fn=_train_model_with_candidate_switches,
        training_result_fn=_training_result,
        encrypted_session_read_error=EncryptedSessionReadError,
        allow_expensive_offline_evaluation_fn=_allow_expensive_offline_evaluation,
        atomic_write_text_fn=atomic_write_text,
        save_metadata_hash_fn=save_metadata_hash,
        publish_initial_production_bundle_if_approved_fn=_publish_initial_production_bundle_if_approved,
        context_routing_version=CONTEXT_ROUTING_VERSION,
        normalize_window_scales_fn=_normalize_window_scales,
        scale_metadata_label_fn=_scale_metadata_label,
    )

__all__ = [
    "CALIBRATION_VERSION",
    "CHALLENGER_MAX_FAR_DEGRADATION",
    "CHALLENGER_MAX_FRR_DEGRADATION",
    "CHALLENGER_MIN_AUC_IMPROVEMENT",
    "CHALLENGER_MIN_F1_IMPROVEMENT",
    "CHALLENGER_SELECTION_VERSION",
    "CONTEXT_SELECTION_VERSION",
    "CPU_PARALLELISM_RESERVED_CORES",
    "EncryptedSessionReadError",
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
    "build_matrix",
    "build_training_selection",
    "extract_from_session",
    "extract_window_samples_from_session",
    "get_anomaly_scores",
    "normalize_feature_dict",
    "read_csv_encrypted",
    "train_model",
    "train_supervised_classifier_candidates",
    "train_user_model",
]
