"""Pipeline orchestration seam extracted from the legacy training module.

Phase 6 moves the long-lived orchestration code behind ``training_core`` while
keeping ``model_training`` as the stable import surface. Public wrappers in
``model_training`` inject the legacy helpers and runtime dependencies so tests
that monkeypatch those names continue to work.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from deep_runtime import build_deep_runtime_metadata_contract
from runtime_policy import build_calibration_maturity
from feedback_loop import production_positive_training_allowed
from bioauth_model.classical_baselines import build_classical_baselines
from training_core.candidate_artifact_builders import (
    build_report_only_candidate_artifacts,
    build_report_only_candidate_artifacts_unavailable,
    summarize_candidate_artifact_build,
)
from training_core.hybrid_pro_artifacts import build_hybrid_pro_artifacts
from training_core.session_eligibility import TRAINING_SESSION_ELIGIBILITY_VERSION, assess_positive_training_session
from hybrid_pro_metadata_normalization import normalize_hybrid_pro_artifact_metadata
from metadata_core.feature_schema_contract import build_feature_schema_contract, validate_feature_names

LOGGER = logging.getLogger(__name__)

TRAINING_PROGRESS_HEARTBEAT_INTERVAL_SECONDS = 3.0


def _production_evidence_metadata_fields_from_report(evaluation_report: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Return privacy-safe production evidence fields for candidate metadata.

    The evaluation report is allowed to contain the canonical Production Evidence
    contract, but candidate metadata must only persist artifact-matched aggregate
    evidence. Invalid or raw behavioral payloads are not persisted, so the
    downstream production eligibility path continues to fail closed.
    """

    if not isinstance(evaluation_report, Mapping):
        return {}
    payload = evaluation_report.get("production_evidence")
    if not isinstance(payload, Mapping):
        return {}
    try:
        from evaluation_core.production_evidence import ProductionEvidenceReport

        evidence = ProductionEvidenceReport.from_dict(payload, allow_unknown_reason_codes=True)
        evidence_payload = evidence.to_dict()
    except (TypeError, ValueError):
        return {}

    fields: Dict[str, Any] = {"production_evidence": evidence_payload}
    identity_values = {
        "candidate_artifact_digest": evidence.candidate_artifact_digest,
        "baseline_artifact_digest": evidence.baseline_artifact_digest,
        "evaluation_report_digest": evidence.evaluation_report_digest,
        "runtime_schema_version": evidence.runtime_schema_version,
    }
    for key, value in identity_values.items():
        text = str(value or "").strip()
        if text:
            fields[key] = text
    return fields


def _merge_production_evidence_metadata_fields(metadata: Dict[str, Any], fields: Mapping[str, Any]) -> None:
    """Merge evidence metadata without hiding existing artifact mismatches."""

    if not isinstance(fields, Mapping):
        return
    for key, value in fields.items():
        if key == "production_evidence":
            metadata[key] = value
            continue
        text = str(value or "").strip()
        if not text:
            continue
        existing = str(metadata.get(key) or "").strip()
        if existing and existing != text:
            # Preserve the independent metadata identity so downstream promotion
            # gates can detect artifact/evidence mismatch and fail closed.
            continue
        metadata[key] = text


def _basic_clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _merge_progress_message_params(*parts: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        for name, value in dict(part).items():
            merged[str(name)] = value
    return merged


class _ProgressHeartbeat:
    def __init__(
        self,
        progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]],
        fraction: float,
        detail_key: str,
        message_params: Optional[Mapping[str, Any]] = None,
        *,
        interval_seconds: float = TRAINING_PROGRESS_HEARTBEAT_INTERVAL_SECONDS,
        clamp01_fn: Optional[Callable[[Any], float]] = None,
        emit_progress_fn: Optional[Callable[..., None]] = None,
    ) -> None:
        self._progress_callback = progress_callback
        self._clamp01_fn = clamp01_fn or _basic_clamp01
        self._emit_progress_fn = emit_progress_fn or _emit_local_progress
        self._fraction = self._clamp01_fn(fraction)
        self._detail_key = str(detail_key or "")
        self._message_params = dict(message_params or {})
        self._interval_seconds = max(0.01, float(interval_seconds or TRAINING_PROGRESS_HEARTBEAT_INTERVAL_SECONDS))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started_at = 0.0

    def __enter__(self) -> "_ProgressHeartbeat":
        if not callable(self._progress_callback):
            return self
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=0.2)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            elapsed = max(1, int(round(time.monotonic() - self._started_at)))
            self._emit_progress_fn(
                self._progress_callback,
                self._fraction,
                self._detail_key,
                _merge_progress_message_params(self._message_params, {"heartbeat_seconds": elapsed}),
                clamp01_fn=self._clamp01_fn,
            )


def _emit_local_progress(
    progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]],
    fraction: Any,
    detail_key: str = "",
    message_params: Optional[Mapping[str, Any]] = None,
    *,
    clamp01_fn: Optional[Callable[[Any], float]] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    if not callable(progress_callback):
        return
    clamp = clamp01_fn or _basic_clamp01
    active_logger = logger or LOGGER
    try:
        progress_callback(clamp(fraction), str(detail_key or ""), dict(message_params or {}))
    except Exception:
        active_logger.debug("Training progress callback failed", exc_info=True)


def _training_result(ok: bool, key: str, message: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ok": bool(ok), "message_key": key, "message": message}
    message_params = extra.pop("message_params", None)
    if isinstance(message_params, dict) and message_params:
        payload["message_params"] = dict(message_params)
    payload.update(extra)
    return payload


def _candidate_artifact_summary_from_metadata(metadata: Mapping[str, Any] | None) -> Dict[str, Any]:
    payload = metadata if isinstance(metadata, Mapping) else {}
    build_like = {
        "manifest_path": ((payload.get("candidate_artifact_builder") or {}) if isinstance(payload.get("candidate_artifact_builder"), Mapping) else {}).get("manifest_path")
        or ((payload.get("artifacts") or {}) if isinstance(payload.get("artifacts"), Mapping) else {}).get("candidate_artifacts_manifest")
        or "candidate_artifacts_manifest.json",
        "manifest": payload.get("candidate_artifact_manifest") if isinstance(payload.get("candidate_artifact_manifest"), Mapping) else {},
        "candidate_artifacts": payload.get("candidate_artifacts") if isinstance(payload.get("candidate_artifacts"), Mapping) else {},
        "status_counts": ((payload.get("candidate_artifact_builder") or {}) if isinstance(payload.get("candidate_artifact_builder"), Mapping) else {}).get("status_counts")
        or ((payload.get("candidate_artifact_training") or {}) if isinstance(payload.get("candidate_artifact_training"), Mapping) else {}).get("status_counts")
        or {},
    }
    return summarize_candidate_artifact_build(build_like)


def _build_training_candidate_artifacts(
    *,
    model_dir: str,
    X_pos: Any,
    X_neg: Any,
    feature_names: Sequence[str],
    feature_schema_version: str | None,
    atomic_write_bytes_fn: Callable[[str, bytes], None],
    atomic_write_text_fn: Callable[[str, str], None],
    samples: Sequence[Mapping[str, Any]],
    labels: Sequence[Any],
    sample_sources: Sequence[str],
    sequence_length: int,
    enable_candidate_artifacts: bool,
    enable_deep_candidate_artifacts: bool,
    strict_candidate_training: bool,
    logger: logging.Logger,
) -> Dict[str, Any]:
    if not bool(enable_candidate_artifacts):
        return build_report_only_candidate_artifacts_unavailable(
            model_dir=model_dir,
            reason="candidate_artifacts_disabled",
            status="skipped",
            feature_names=feature_names,
            feature_schema_version=feature_schema_version,
            atomic_write_text_fn=atomic_write_text_fn,
            extra={"enable_candidate_artifacts": False, "enable_deep_candidate_artifacts": bool(enable_deep_candidate_artifacts)},
        )
    try:
        return build_report_only_candidate_artifacts(
            model_dir=model_dir,
            X_pos=X_pos,
            X_neg=X_neg,
            feature_names=feature_names,
            feature_schema_version=feature_schema_version,
            atomic_write_bytes_fn=atomic_write_bytes_fn,
            atomic_write_text_fn=atomic_write_text_fn,
            samples=samples,
            labels=labels,
            sample_sources=sample_sources,
            sequence_length=sequence_length,
            include_deep_candidates=bool(enable_deep_candidate_artifacts),
        )
    except Exception as exc:
        if bool(strict_candidate_training):
            raise
        logger.warning("Report-only candidate artifact build failed safely: %s", exc, exc_info=True)
        return build_report_only_candidate_artifacts_unavailable(
            model_dir=model_dir,
            reason=f"candidate_artifact_build_failed:{type(exc).__name__}",
            status="failed",
            feature_names=feature_names,
            feature_schema_version=feature_schema_version,
            atomic_write_text_fn=atomic_write_text_fn,
            extra={
                "enable_candidate_artifacts": True,
                "enable_deep_candidate_artifacts": bool(enable_deep_candidate_artifacts),
                "strict_candidate_training": False,
                "failure_isolated": True,
            },
        )


def _attach_candidate_artifact_training_metadata(
    metadata: Dict[str, Any],
    candidate_artifact_build: Mapping[str, Any],
    *,
    enable_candidate_artifacts: bool,
    enable_deep_candidate_artifacts: bool,
    strict_candidate_training: bool,
) -> None:
    summary = summarize_candidate_artifact_build(candidate_artifact_build)
    metadata["candidate_artifact_manifest"] = dict(candidate_artifact_build.get("manifest") or {})
    metadata["candidate_artifacts"] = dict(candidate_artifact_build.get("candidate_artifacts") or {})
    metadata["candidate_artifact_builder"] = {
        "schema_version": candidate_artifact_build.get("schema_version"),
        "builder_version": candidate_artifact_build.get("builder_version"),
        "manifest_path": candidate_artifact_build.get("manifest_path"),
        "status_counts": dict(summary.get("status_counts") or {}),
        "report_only": True,
        "can_lock": False,
        "can_lock_alone": False,
        "can_influence_device": False,
        "runtime_authoritative": False,
        "trigger_face_confirmation": False,
    }
    metadata["candidate_artifact_training"] = {
        "enabled": bool(enable_candidate_artifacts),
        "deep_enabled": bool(enable_deep_candidate_artifacts),
        "strict_candidate_training": bool(strict_candidate_training),
        **summary,
    }


def _summarize_sequence_feature_family(feature_names: List[str], *, sequence_features_version: str) -> Dict[str, Any]:
    names = [str(name) for name in feature_names]
    adjacent = sorted(name for name in names if name.startswith("adjacent_"))
    trend = sorted(name for name in names if name.startswith("trend_"))
    return {
        "version": sequence_features_version,
        "enabled": bool(adjacent or trend),
        "lookback_windows": 2,
        "families_enabled": [family for family, enabled in (("adjacent_window_deltas", bool(adjacent)), ("tempo_trend", bool(trend))) if enabled],
        "feature_counts": {"adjacent_window_deltas": int(len(adjacent)), "tempo_trend": int(len(trend))},
        "total_feature_count": int(len(adjacent) + len(trend)),
        "feature_name_samples": {"adjacent_window_deltas": adjacent[:6], "tempo_trend": trend[:6]},
    }


def _collect_training_samples(
    *,
    sessions: List[str],
    negative_lookup: set[str],
    window_limits: Dict[str, int],
    active_window_scales: List[float],
    progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]],
    emit_progress_fn: Callable[..., None],
    clamp01_fn: Callable[[Any], float],
    extract_window_samples_from_session_fn: Callable[..., List[Dict[str, float]]],
    annotate_sequence_trend_windows_fn: Callable[[List[Dict[str, float]]], List[Dict[str, float]]],
    annotate_transition_windows_fn: Callable[[List[Dict[str, float]]], List[Dict[str, float]]],
    extract_from_session_fn: Callable[..., Dict[str, float]],
    get_label_fn: Callable[[str, str], int],
    apply_transition_window_policy_fn: Callable[..., Tuple[List[Dict[str, float]], Dict[str, Any]]],
    normalize_feature_dict_fn: Callable[[Mapping[str, Any]], Dict[str, float]],
    encrypted_session_read_error: type[Exception],
    logger: logging.Logger,
    max_train_windows_per_session: int,
    window_seconds: float,
    window_step_seconds: float,
    min_window_events: int,
) -> Dict[str, Any]:
    samples: List[Dict[str, float]] = []
    labels: List[int] = []
    sample_sources: List[str] = []
    transition_session_stats: List[Dict[str, Any]] = []
    total_sessions = max(1, len(sessions))
    emit_progress_fn(progress_callback, 0.02, "training_detail_extracting_session", {"current": 0, "total": total_sessions}, clamp01_fn=clamp01_fn, logger=logger)

    for index, session_path in enumerate(sessions, start=1):
        try:
            session_limit = window_limits.get(os.path.normcase(os.path.abspath(session_path)), max_train_windows_per_session)
            window_samples = extract_window_samples_from_session_fn(
                session_path,
                window_seconds=window_seconds,
                step_seconds=window_step_seconds,
                min_total_events=min_window_events,
                max_windows=max(1, int(session_limit)),
                window_scales=active_window_scales,
                strict=True,
            )
            if not window_samples:
                window_samples = annotate_sequence_trend_windows_fn(
                    annotate_transition_windows_fn([extract_from_session_fn(session_path, strict=True)])
                )
            label = 1 if os.path.normcase(os.path.abspath(session_path)) in negative_lookup else get_label_fn(session_path, os.path.basename(session_path))
            window_samples, transition_summary = apply_transition_window_policy_fn(window_samples, label=int(label))
            transition_summary["session_name"] = os.path.basename(session_path)
            transition_summary["session_path"] = session_path
            transition_session_stats.append(transition_summary)
            for sample in window_samples:
                samples.append(normalize_feature_dict_fn(sample))
                labels.append(int(label))
                sample_sources.append(os.path.basename(session_path))
        except encrypted_session_read_error as exc:
            logger.error("Unreadable training session %s: %s", session_path, exc)
            raise
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Skipping unreadable training session %s: %s", session_path, exc)
            continue
        finally:
            emit_progress_fn(
                progress_callback,
                0.08 + (0.38 * (index / total_sessions)),
                "training_detail_extracting_session",
                {"current": index, "total": total_sessions},
                clamp01_fn=clamp01_fn,
                logger=logger,
            )

    return {
        "samples": samples,
        "labels": labels,
        "sample_sources": sample_sources,
        "transition_session_stats": transition_session_stats,
    }


def _prepare_training_matrix(
    *,
    samples: List[Dict[str, float]],
    labels: List[int],
    active_window_scales: List[float],
    progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]],
    emit_progress_fn: Callable[..., None],
    clamp01_fn: Callable[[Any], float],
    progress_heartbeat_factory: Callable[..., _ProgressHeartbeat],
    per_scale_sample_counts_fn: Callable[[List[Dict[str, float]], List[float]], Dict[str, int]],
    sequence_feature_summary_fn: Callable[[List[str]], Dict[str, Any]],
    build_matrix_fn: Callable[[List[Dict[str, float]], List[str]], np.ndarray],
    logger: logging.Logger,
) -> Dict[str, Any]:
    emit_progress_fn(progress_callback, 0.50, "training_detail_preparing_feature_matrix", clamp01_fn=clamp01_fn, logger=logger)
    with progress_heartbeat_factory(progress_callback, 0.50, "training_detail_preparing_feature_matrix"):
        per_scale_sample_counts = per_scale_sample_counts_fn(samples, active_window_scales)
        feature_names = sorted({feature for sample in samples for feature in sample.keys()})
        sequence_features = sequence_feature_summary_fn(feature_names)
        X = build_matrix_fn(samples, feature_names)
        y = np.asarray(labels, dtype=int)
        pos_mask = y == 0
        neg_mask = y == 1
        X_pos = X[pos_mask]
        X_neg = X[neg_mask]
    return {
        "per_scale_sample_counts": per_scale_sample_counts,
        "feature_names": feature_names,
        "sequence_features": sequence_features,
        "X": X,
        "y": y,
        "pos_mask": pos_mask,
        "neg_mask": neg_mask,
        "X_pos": X_pos,
        "X_neg": X_neg,
    }


def train_model(
    *,
    sessions: Optional[List[str]] = None,
    negative_sessions: Optional[List[str]] = None,
    model_file: str,
    classifier_file: str,
    metadata_file: str,
    session_window_limits: Optional[Dict[str, int]] = None,
    training_selection: Optional[Mapping[str, Any]] = None,
    progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]] = None,
    list_session_dirs_fn: Callable[[], List[str]],
    normalize_window_scales_fn: Callable[[], List[float]],
    emit_progress_fn: Callable[..., None],
    clamp01_fn: Callable[[Any], float],
    progress_heartbeat_factory: Callable[..., _ProgressHeartbeat],
    get_label_fn: Callable[[str, str], int],
    extract_window_samples_from_session_fn: Callable[..., List[Dict[str, float]]],
    annotate_sequence_trend_windows_fn: Callable[[List[Dict[str, float]]], List[Dict[str, float]]],
    annotate_transition_windows_fn: Callable[[List[Dict[str, float]]], List[Dict[str, float]]],
    extract_from_session_fn: Callable[..., Dict[str, float]],
    apply_transition_window_policy_fn: Callable[..., Tuple[List[Dict[str, float]], Dict[str, Any]]],
    normalize_feature_dict_fn: Callable[[Mapping[str, Any]], Dict[str, float]],
    encrypted_session_read_error: type[Exception],
    logger: logging.Logger,
    max_train_windows_per_session: int,
    window_seconds: float,
    window_step_seconds: float,
    min_window_events: int,
    per_scale_sample_counts_fn: Callable[[List[Dict[str, float]], List[float]], Dict[str, int]],
    sequence_feature_summary_fn: Callable[[List[str]], Dict[str, Any]],
    build_matrix_fn: Callable[[List[Dict[str, float]], List[str]], np.ndarray],
    min_positive_window_samples: int,
    iforest_factory: Any,
    iforest_fit_kwargs_fn: Callable[[float], Dict[str, Any]],
    get_anomaly_scores_fn: Callable[[Any, np.ndarray], np.ndarray],
    score_percentiles_dict_fn: Callable[[np.ndarray], Dict[str, float]],
    train_supervised_classifier_candidates_fn: Callable[..., Tuple[Any | None, Dict[str, Any]]],
    min_negative_window_samples: int,
    remove_classifier_sidecar_fn: Callable[[str], None],
    atomic_write_bytes_fn: Callable[[str, bytes], None],
    save_model_hash_fn: Callable[[str], None],
    save_classifier_sidecar_fn: Callable[[str], None],
    atomic_write_text_fn: Callable[[str, str], None],
    save_metadata_hash_fn: Callable[[str], None],
    feature_schema_version: str,
    feature_window_strategy: str,
    predict_window_step_seconds: float,
    max_predict_windows: int,
    recommended_enrollment_sessions: int,
    default_risk_sensitivity: str,
    classifier_selection_version: str,
    train_context_submodels_fn: Callable[..., Dict[str, Any]],
    context_selection_version: str,
    summarize_transition_training_fn: Callable[[List[Mapping[str, Any]]], Dict[str, Any]],
    transition_policy_version: str,
    transition_session_start_seconds: float,
    transition_post_idle_gap_seconds: float,
    transition_activity_shift_threshold: float,
    transition_keep_ratio: float,
    transition_min_keep_windows: int,
    compute_user_calibration_profile_fn: Callable[..., Dict[str, Any]],
    enable_candidate_artifacts: bool = True,
    enable_deep_candidate_artifacts: bool = True,
    strict_candidate_training: bool = False,
) -> Tuple[Optional[Any], str]:
    resolved_sessions = list(dict.fromkeys(sessions if sessions is not None else list_session_dirs_fn()))
    negative_lookup = {os.path.normcase(os.path.abspath(path)) for path in (negative_sessions or [])}
    window_limits = {os.path.normcase(os.path.abspath(path)): int(limit) for path, limit in (session_window_limits or {}).items()}
    active_window_scales = normalize_window_scales_fn()

    if not resolved_sessions:
        return None, "fail"

    collected = _collect_training_samples(
        sessions=resolved_sessions,
        negative_lookup=negative_lookup,
        window_limits=window_limits,
        active_window_scales=active_window_scales,
        progress_callback=progress_callback,
        emit_progress_fn=emit_progress_fn,
        clamp01_fn=clamp01_fn,
        extract_window_samples_from_session_fn=extract_window_samples_from_session_fn,
        annotate_sequence_trend_windows_fn=annotate_sequence_trend_windows_fn,
        annotate_transition_windows_fn=annotate_transition_windows_fn,
        extract_from_session_fn=extract_from_session_fn,
        get_label_fn=get_label_fn,
        apply_transition_window_policy_fn=apply_transition_window_policy_fn,
        normalize_feature_dict_fn=normalize_feature_dict_fn,
        encrypted_session_read_error=encrypted_session_read_error,
        logger=logger,
        max_train_windows_per_session=max_train_windows_per_session,
        window_seconds=window_seconds,
        window_step_seconds=window_step_seconds,
        min_window_events=min_window_events,
    )
    samples = list(collected["samples"])
    labels = list(collected["labels"])
    sample_sources = list(collected["sample_sources"])
    transition_session_stats = list(collected["transition_session_stats"])

    if len(samples) < 2:
        return None, "fail"

    prepared = _prepare_training_matrix(
        samples=samples,
        labels=labels,
        active_window_scales=active_window_scales,
        progress_callback=progress_callback,
        emit_progress_fn=emit_progress_fn,
        clamp01_fn=clamp01_fn,
        progress_heartbeat_factory=progress_heartbeat_factory,
        per_scale_sample_counts_fn=per_scale_sample_counts_fn,
        sequence_feature_summary_fn=sequence_feature_summary_fn,
        build_matrix_fn=build_matrix_fn,
        logger=logger,
    )
    per_scale_sample_counts = dict(prepared["per_scale_sample_counts"])
    feature_names = list(prepared["feature_names"])
    feature_schema_validation = validate_feature_names(feature_names, require_multiscale=True)
    feature_schema_contract = build_feature_schema_contract(feature_names)
    sequence_features = dict(prepared["sequence_features"])
    X = prepared["X"]
    y = prepared["y"]
    pos_mask = prepared["pos_mask"]
    neg_mask = prepared["neg_mask"]
    X_pos = prepared["X_pos"]
    X_neg = prepared["X_neg"]

    if len(X_pos) < min_positive_window_samples:
        return None, "fail"

    emit_progress_fn(progress_callback, 0.58, "training_detail_fitting_anomaly_detector", clamp01_fn=clamp01_fn, logger=logger)
    contamination = 0.06 if len(X_pos) >= 40 else 0.08 if len(X_pos) >= 20 else 0.1
    model = iforest_factory(**iforest_fit_kwargs_fn(contamination))
    with progress_heartbeat_factory(progress_callback, 0.58, "training_detail_fitting_anomaly_detector"):
        model.fit(X_pos)

    pos_scores = get_anomaly_scores_fn(model, X_pos)
    score_percentiles = score_percentiles_dict_fn(pos_scores)
    classical_baselines = build_classical_baselines(
        X_pos,
        feature_names=feature_names,
        feature_schema_version=feature_schema_version,
    )
    clf, classifier_info = train_supervised_classifier_candidates_fn(
        X_pos,
        X_neg,
        pos_sample_sources=[sample_sources[idx] for idx, is_positive in enumerate(pos_mask) if bool(is_positive)],
        neg_sample_sources=[sample_sources[idx] for idx, is_negative in enumerate(neg_mask) if bool(is_negative)],
        minimum_negative_samples=min_negative_window_samples,
        progress_callback=progress_callback,
    )
    if clf is None and os.path.exists(classifier_file):
        try:
            os.remove(classifier_file)
        except OSError:
            pass
        remove_classifier_sidecar_fn(classifier_file)

    model_dir = os.path.dirname(model_file)
    os.makedirs(model_dir, exist_ok=True)

    atomic_write_bytes_fn(model_file, pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL))
    save_model_hash_fn(model_file)

    if clf is not None:
        atomic_write_bytes_fn(classifier_file, pickle.dumps(clf, protocol=pickle.HIGHEST_PROTOCOL))
        save_classifier_sidecar_fn(classifier_file)

    metadata: Dict[str, Any] = {
        "feature_names": feature_names,
        "feature_name_count": int(len(feature_names)),
        "feature_schema_version": feature_schema_version,
        "feature_schema_contract_version": feature_schema_contract.get("contract_version"),
        "feature_schema_digest": feature_schema_contract.get("schema_digest"),
        "window_schema_version": feature_schema_contract.get("window_schema_version"),
        "feature_extension_profile": feature_schema_contract.get("feature_extension_profile"),
        "feature_window_strategy": feature_window_strategy,
        "feature_schema_contract": feature_schema_contract,
        "feature_schema_validation": feature_schema_validation,
        "active_window_scales": [float(scale) for scale in active_window_scales],
        "per_scale_sample_counts": per_scale_sample_counts,
        "window_seconds": max(active_window_scales) if active_window_scales else window_seconds,
        "window_step_seconds": window_step_seconds,
        "predict_window_step_seconds": predict_window_step_seconds,
        "min_window_events": min_window_events,
        "max_predict_windows": max_predict_windows,
        "recommended_enrollment_sessions": recommended_enrollment_sessions,
        "sequence_features": sequence_features,
        "positive_window_samples": int(len(X_pos)),
        "negative_window_samples": int(len(X_neg)),
        "sessions": sample_sources,
        "labels": labels,
        "score_percentiles": score_percentiles,
        "risk_sensitivity_default": default_risk_sensitivity,
        "anomaly_detector": "IsolationForest",
        "anomaly_detector_strategy": "one-class profile trained only on accepted positive windows",
        "training_session_eligibility_version": TRAINING_SESSION_ELIGIBILITY_VERSION,
        "classical_baselines": classical_baselines,
        "model_family": "classic_iforest_with_optional_supervised",
        "p10": float(score_percentiles.get("p10", score_percentiles["p50"])),
        "p90": float(score_percentiles["p95"]),
        "deep_runtime": build_deep_runtime_metadata_contract(sequence_length=max_predict_windows),
    }
    candidate_artifact_build = _build_training_candidate_artifacts(
        model_dir=model_dir,
        X_pos=X_pos,
        X_neg=X_neg,
        feature_names=feature_names,
        feature_schema_version=feature_schema_version,
        atomic_write_bytes_fn=atomic_write_bytes_fn,
        atomic_write_text_fn=atomic_write_text_fn,
        samples=samples,
        labels=labels,
        sample_sources=sample_sources,
        sequence_length=max_predict_windows,
        enable_candidate_artifacts=enable_candidate_artifacts,
        enable_deep_candidate_artifacts=enable_deep_candidate_artifacts,
        strict_candidate_training=strict_candidate_training,
        logger=logger,
    )
    _attach_candidate_artifact_training_metadata(
        metadata,
        candidate_artifact_build,
        enable_candidate_artifacts=enable_candidate_artifacts,
        enable_deep_candidate_artifacts=enable_deep_candidate_artifacts,
        strict_candidate_training=strict_candidate_training,
    )

    metadata.update(classifier_info)
    metadata["supervised_classifier_selection_version"] = classifier_selection_version
    metadata["classifier_family"] = classifier_info.get("classifier_family")
    metadata["supervised_candidates"] = dict((classifier_info.get("supervised_classifier") or {}).get("head_to_head") or {})
    metadata["artifact_integrity_scheme"] = "sidecar-hmac-sha256"
    metadata["bundle_role"] = "candidate"
    metadata["model_status"] = "pending_evaluation"
    metadata["policy_version"] = None
    metadata["approval_reason"] = "Awaiting offline evaluation."
    metadata["runtime_requires_production_approval"] = True
    metadata["artifacts"] = {
        "model": os.path.basename(model_file),
        "classifier": os.path.basename(classifier_file) if clf is not None else None,
        "metadata": os.path.basename(metadata_file),
        "candidate_artifacts_manifest": str((metadata.get("candidate_artifact_builder") or {}).get("manifest_path") or "candidate_artifacts_manifest.json"),
    }
    for candidate_id, entry in dict(metadata.get("candidate_artifacts") or {}).items():
        artifact_name = str((entry or {}).get("artifact_path") or "").strip() if isinstance(entry, Mapping) else ""
        if artifact_name:
            metadata["artifacts"][f"{candidate_id}_artifact"] = artifact_name
    emit_progress_fn(progress_callback, 0.90, "training_detail_building_contexts", clamp01_fn=clamp01_fn, logger=logger)
    with progress_heartbeat_factory(progress_callback, 0.90, "training_detail_building_contexts"):
        context_router = train_context_submodels_fn(
            model_dir=model_dir,
            feature_names=feature_names,
            X=X,
            y=y,
            samples=samples,
            sample_sources=sample_sources,
            active_window_scales=active_window_scales,
            metadata_template=metadata,
        )
    metadata["context_router"] = context_router
    metadata["context_models"] = {
        "version": context_selection_version,
        "active_contexts": list(context_router.get("active_contexts") or []),
        "bundles": dict(context_router.get("bundles") or {}),
        "context_sample_counts": dict(context_router.get("context_sample_counts") or {}),
        "global_fallback_enabled": True,
    }
    hybrid_pro_training = build_hybrid_pro_artifacts(
        model_dir=model_dir,
        X=X,
        y=y,
        X_pos=X_pos,
        X_neg=X_neg,
        samples=samples,
        feature_names=feature_names,
        iforest_factory=iforest_factory,
        iforest_fit_kwargs_fn=iforest_fit_kwargs_fn,
        atomic_write_bytes_fn=atomic_write_bytes_fn,
        classifier_family=str(metadata.get("classifier_family") or ""),
    )
    metadata["training_strategy"] = str(hybrid_pro_training.get("training_strategy") or "context_aware")
    if metadata["training_strategy"].startswith("hybrid_pro"):
        metadata["model_family"] = str(hybrid_pro_training.get("model_family") or metadata.get("model_family") or "hybrid_pro")
    metadata["hybrid_pro_enabled"] = bool(hybrid_pro_training.get("hybrid_pro_enabled"))
    metadata["layer_artifacts"] = dict(hybrid_pro_training.get("layer_artifacts") or {})
    metadata["hybrid_pro_artifacts"] = dict(hybrid_pro_training.get("layer_artifacts") or {})
    metadata["skipped_layers"] = dict(hybrid_pro_training.get("skipped_layers") or {})
    metadata["skip_reason_codes"] = list(hybrid_pro_training.get("skip_reason_codes") or [])
    metadata["dependency_versions"] = dict(hybrid_pro_training.get("dependency_versions") or {})
    metadata["hybrid_pro_training"] = hybrid_pro_training
    metadata["hybrid_pro_layer_readiness"] = dict(hybrid_pro_training.get("layer_readiness") or {})
    metadata["hybrid_pro_modality_mapping"] = dict(hybrid_pro_training.get("modality_mapping") or {})
    artifacts = dict(metadata.get("artifacts") or {})
    for layer, info in dict(hybrid_pro_training.get("layer_artifacts") or {}).items():
        artifact_name = str(info.get("artifact") or info.get("path") or "").strip()
        if artifact_name:
            artifacts[f"{layer}_artifact"] = artifact_name
    metadata["artifacts"] = artifacts
    positive_sample_sources = [sample_sources[idx] for idx, is_positive in enumerate(pos_mask) if bool(is_positive)]
    positive_samples = [samples[idx] for idx, is_positive in enumerate(pos_mask) if bool(is_positive)]
    emit_progress_fn(progress_callback, 0.97, "training_detail_finalizing_training_artifacts", clamp01_fn=clamp01_fn, logger=logger)
    metadata["transition_policy"] = {
        "version": transition_policy_version,
        "enabled": True,
        "session_start_seconds": float(transition_session_start_seconds),
        "post_idle_gap_seconds": float(transition_post_idle_gap_seconds),
        "activity_shift_threshold": float(transition_activity_shift_threshold),
        "keep_ratio": float(transition_keep_ratio),
        "minimum_kept_transition_windows_per_session": int(transition_min_keep_windows),
        "runtime_transition_status": "transitioning",
        "runtime_min_settled_windows": 2,
        "runtime_high_risk_bypass": 92.0,
        "runtime_high_severe_window_count": 2,
    }
    metadata["transition_training"] = summarize_transition_training_fn(transition_session_stats)
    metadata["user_calibration"] = compute_user_calibration_profile_fn(
        pos_scores=pos_scores,
        neg_scores=get_anomaly_scores_fn(model, X_neg) if len(X_neg) else np.asarray([], dtype=float),
        pos_sample_sources=positive_sample_sources,
        pos_samples=positive_samples,
    )
    metadata["calibration_maturity"] = build_calibration_maturity(
        selection_summary=training_selection,
        positive_samples=positive_samples,
        positive_sample_sources=positive_sample_sources,
        user_calibration=metadata.get("user_calibration") or {},
    )
    metadata = normalize_hybrid_pro_artifact_metadata(
        metadata,
        bundle_paths={"base": model_dir, "model": model_file, "classifier": classifier_file, "metadata": metadata_file},
        metadata_path=metadata_file,
        base_dir=model_dir,
    )
    atomic_write_text_fn(metadata_file, json.dumps(metadata, indent=2, ensure_ascii=False))
    save_metadata_hash_fn(metadata_file)
    emit_progress_fn(progress_callback, 1.0, "training_detail_done", clamp01_fn=clamp01_fn, logger=logger)
    return model, "ok"


def _make_training_progress_callbacks(
    *,
    progress_callback: Optional[Callable[[Mapping[str, Any]], None]],
    progress_context: Dict[str, Any],
    clamp01_fn: Callable[[Any], float],
    logger: logging.Logger,
) -> Tuple[
    Callable[[Any, str, str, Optional[Mapping[str, Any]]], None],
    Callable[[int, int, str], Callable[[Any, str, Optional[Mapping[str, Any]]], None]],
]:
    def report_progress(percent: Any, stage_key: str, detail_key: str = "", message_params: Optional[Mapping[str, Any]] = None) -> None:
        if not callable(progress_callback):
            return
        payload_params = dict(progress_context)
        payload_params.update(dict(message_params or {}))
        try:
            progress_callback(
                {
                    "percent": max(0, min(100, int(round(float(percent))))),
                    "stage_key": str(stage_key or ""),
                    "detail_key": str(detail_key or ""),
                    "message_params": payload_params,
                    "active": True,
                }
            )
        except Exception:
            logger.debug("Training progress payload callback failed", exc_info=True)

    def stage_progress(start_percent: int, end_percent: int, stage_key: str):
        span = max(0.0, float(end_percent) - float(start_percent))

        def _emit(local_fraction: Any = 0.0, detail_key: str = "", message_params: Optional[Mapping[str, Any]] = None) -> None:
            report_progress(start_percent + (span * clamp01_fn(local_fraction)), stage_key, detail_key, message_params)

        return _emit

    return report_progress, stage_progress


def _scan_positive_training_candidates(
    *,
    safe: str,
    min_sessions: int,
    mark_profile_state_fn: Callable[[str, str], Any],
    training_result_fn: Callable[..., Dict[str, Any]],
    user_session_paths_fn: Callable[[str], List[str]],
    read_session_metadata_fn: Callable[[str], Mapping[str, Any] | None],
    is_accepted_session_fn: Callable[[str, Mapping[str, Any]], bool],
    session_quality_ok_fn: Callable[[Mapping[str, Any]], bool],
    report_progress_fn: Callable[[Any, str, str, Optional[Mapping[str, Any]]], None],
) -> Dict[str, Any]:
    enrollment_sessions: List[str] = []
    positive_candidates: List[Tuple[str, Dict[str, Any]]] = []
    session_paths = list(user_session_paths_fn(safe))
    total_saved_sessions = max(1, len(session_paths))
    report_progress_fn(2, "training_stage_preparing", "training_detail_scanning_sessions", {"current": 0, "total": len(session_paths)})
    for index, session_path in enumerate(session_paths, start=1):
        meta = dict(read_session_metadata_fn(session_path) or {})
        eligibility = assess_positive_training_session(
            meta,
            session_path=session_path,
            user_id=safe,
            is_accepted_session_fn=is_accepted_session_fn,
            session_quality_ok_fn=session_quality_ok_fn,
            production_allowed_fn=production_positive_training_allowed,
        )
        if not bool(eligibility.get("allowed")):
            logger_detail = str(eligibility.get("reason_code") or "blocked")
            LOGGER.info("Training session skipped by contamination guard: %s", logger_detail)
            continue
        session_kind = str(meta.get("session_kind", "")).strip().lower()
        if session_kind == "enrollment":
            enrollment_sessions.append(session_path)
        # Enrollment sessions remain the minimum gate, but accepted trusted
        # protected-session archives are valid supplemental owner-positive
        # training evidence.  Keep rejected/suspicious/intruder archives out via
        # the accepted-session, metadata-trust, and feedback-loop gates above.
        positive_candidates.append((session_path, meta))
        report_progress_fn(2 + (8 * (index / total_saved_sessions)), "training_stage_preparing", "training_detail_scanning_sessions", {"current": index, "total": len(session_paths)})

    enrollment_total = len(enrollment_sessions)
    if enrollment_total < int(min_sessions):
        mark_profile_state_fn(safe, "collecting")
        return {
            "ok": False,
            "result": training_result_fn(
                False,
                "training_need_more_sessions",
                f"Need at least {min_sessions} trusted enrollment sessions before training.",
                message_params={"minimum": int(min_sessions)},
                session_count=enrollment_total,
                diagnostic="Only archived sessions with verified metadata integrity count toward training.",
            ),
        }
    return {
        "ok": True,
        "enrollment_total": enrollment_total,
        "positive_candidates": positive_candidates,
    }


def _evaluate_and_publish_candidate(
    *,
    safe: str,
    paths: Mapping[str, str],
    positives: List[str],
    negative_sessions: List[str],
    selection_summary: Mapping[str, Any],
    report_progress_fn: Callable[[Any, str, str, Optional[Mapping[str, Any]]], None],
    stage_progress_factory: Callable[[int, int, str], Callable[[Any, str, Optional[Mapping[str, Any]]], None]],
    allow_expensive_offline_evaluation_fn: Callable[[List[str], List[str]], bool],
    atomic_write_text_fn: Callable[[str, str], None],
    save_metadata_hash_fn: Callable[[str], None],
    publish_initial_production_bundle_if_approved_fn: Callable[[str, Mapping[str, str], Mapping[str, Any]], bool],
    context_routing_version: str,
    logger: logging.Logger,
) -> Dict[str, Any]:
    evaluation_report = None
    policy_decision: Dict[str, Any] = {
        "model_status": "pending_evaluation",
        "policy_version": None,
        "approval_reason": "Offline evaluation was not completed.",
    }
    try:
        from artifact_integrity import load_metadata
        from model_evaluation import evaluate_candidate_model
        from model_policy import evaluate_model_policy

        eval_progress = stage_progress_factory(78, 92, "training_stage_evaluating_model")
        eval_progress(0.0, "training_detail_prepare_evaluation")
        evaluation_report = evaluate_candidate_model(
            positive_sessions=positives,
            negative_sessions=negative_sessions,
            model_file=paths["model"],
            metadata_file=paths["metadata"],
            classifier_file=paths["classifier"],
            output_dir=paths["base"],
            bundle_role="main_candidate",
            user_id=safe,
            allow_temp_retraining=allow_expensive_offline_evaluation_fn(positives, negative_sessions),
            training_selection=selection_summary,
            progress_callback=eval_progress,
        )
        policy_decision = evaluate_model_policy(evaluation_report)

        report_progress_fn(94, "training_stage_publishing_profile", "training_detail_publish_bundle")
        metadata = load_metadata(paths["metadata"]) or {}
        rollout_details = dict(policy_decision.get("rollout_details") or {})
        deep_runtime = dict(metadata.get("deep_runtime") or {})
        deep_runtime.update({
            "runtime_rollout_stage": policy_decision.get("rollout_status") or rollout_details.get("rollout_status") or deep_runtime.get("runtime_rollout_stage") or "classic_only_ready",
            "runtime_shadow_only": not bool(rollout_details.get("production_decision_enabled")),
            "runtime_decision_influence_enabled": bool(rollout_details.get("production_decision_enabled")),
            "runtime_shadow_diagnostics_enabled": bool(rollout_details.get("shadow_diagnostics_enabled", True)),
            "runtime_rollback_to_classic_on_failure": bool(rollout_details.get("rollback_to_classic_on_failure", True)),
            "runtime_activation_blocked_reason": rollout_details.get("blocked_reason"),
            "allowed_modes": list(rollout_details.get("allowed_modes") or deep_runtime.get("allowed_modes") or []),
            "selected_backend": rollout_details.get("preferred_backend") or deep_runtime.get("selected_backend") or "classic",
            "recommended_backend": rollout_details.get("preferred_backend") or deep_runtime.get("recommended_backend") or "classic",
        })
        sequence_contract = dict(deep_runtime.get("sequence_model") or {})
        if sequence_contract:
            sequence_contract["shadow_only"] = not bool(rollout_details.get("production_decision_enabled"))
            sequence_contract["runtime_ready"] = bool(rollout_details.get("production_decision_enabled"))
            deep_runtime["sequence_model"] = sequence_contract
        production_evidence_metadata = _production_evidence_metadata_fields_from_report(evaluation_report)
        metadata.update(
            {
                "bundle_role": "main_candidate",
                "model_status": policy_decision["model_status"],
                "policy_version": policy_decision["policy_version"],
                "approval_reason": policy_decision["approval_reason"],
                "policy_metrics": policy_decision.get("policy_metrics") or {},
                "policy_gate": policy_decision.get("policy_gate"),
                "rollout_status": policy_decision.get("rollout_status"),
                "rollout_details": rollout_details,
                "evaluation_schema_version": evaluation_report.get("schema_version"),
                "evaluation_report_file": os.path.basename(paths["evaluation_report"]),
                "evaluation_summary_file": os.path.basename(paths["evaluation_summary"]),
                "latest_evaluation_primary": evaluation_report.get("primary_evaluation"),
                "runtime_requires_production_approval": True,
                "training_selection": selection_summary,
                "training_selection_version": selection_summary.get("selection_version"),
                "negative_mining_version": selection_summary.get("negative_mining_version"),
                "negative_strategy": selection_summary.get("negative_strategy"),
                "negative_hardness_mix": dict(selection_summary.get("negative_pool", {}).get("hardness_mix") or {}),
                "context_routing_version": context_routing_version,
                "user_calibration": metadata.get("user_calibration") or {},
                "calibration_version": ((metadata.get("user_calibration") or {}).get("version")),
                "calibration_maturity": metadata.get("calibration_maturity") or {},
                "calibration_maturity_version": ((metadata.get("calibration_maturity") or {}).get("version")),
                "sequence_features": metadata.get("sequence_features") or {},
                "sequence_features_version": ((metadata.get("sequence_features") or {}).get("version")),
                "deep_runtime": deep_runtime,
            }
        )
        _merge_production_evidence_metadata_fields(metadata, production_evidence_metadata)
        metadata = normalize_hybrid_pro_artifact_metadata(
            metadata,
            bundle_paths=paths,
            metadata_path=paths["metadata"],
            base_dir=paths.get("base"),
        )
        atomic_write_text_fn(paths["metadata"], json.dumps(metadata, indent=2, ensure_ascii=False))
        save_metadata_hash_fn(paths["metadata"])
        try:
            if evaluation_report is not None and os.path.exists(paths["evaluation_report"]):
                persisted_report = dict(evaluation_report)
                persisted_report["policy_decision"] = dict(policy_decision)
                persisted_report["rollout_status"] = policy_decision.get("rollout_status")
                persisted_report["rollout_details"] = rollout_details
                atomic_write_text_fn(paths["evaluation_report"], json.dumps(persisted_report, indent=2, ensure_ascii=False))
            if os.path.exists(paths["evaluation_summary"]):
                with open(paths["evaluation_summary"], "r", encoding="utf-8") as handle:
                    summary_text = handle.read().rstrip()
                summary_text += f"\n- Rollout status: {policy_decision.get('rollout_status')}\n- Production Hybrid enabled: {bool(rollout_details.get('production_decision_enabled'))}\n"
                atomic_write_text_fn(paths["evaluation_summary"], summary_text)
        except Exception:
            pass
        report_progress_fn(97, "training_stage_publishing_profile", "training_detail_publish_bundle")
        publish_initial_production_bundle_if_approved_fn(safe, paths, policy_decision)
    except Exception as exc:
        logger.warning("Offline evaluation/policy update failed for %s: %s", safe, exc, exc_info=True)
        policy_decision = {
            "model_status": "pending_evaluation",
            "policy_version": None,
            "approval_reason": f"Offline evaluation failed: {exc}",
        }
    return {
        "evaluation_report": evaluation_report,
        "policy_decision": policy_decision,
    }


def train_user_model(
    *,
    safe: str,
    min_sessions: int,
    max_enrollment_sessions: int,
    progress_callback: Optional[Callable[[Mapping[str, Any]], None]] = None,
    clamp01_fn: Callable[[Any], float],
    logger: logging.Logger,
    user_model_lifecycle_lock_fn: Callable[[str], Any],
    user_model_paths_fn: Callable[[str], Mapping[str, str]],
    user_session_paths_fn: Callable[[str], List[str]],
    read_session_metadata_fn: Callable[[str], Mapping[str, Any] | None],
    is_accepted_session_fn: Callable[[str, Mapping[str, Any]], bool],
    session_quality_ok_fn: Callable[[Mapping[str, Any]], bool],
    mark_profile_state_fn: Callable[[str, str], Any],
    collect_negative_sessions_fn: Callable[[str], List[str]],
    build_training_selection_fn: Callable[..., Mapping[str, Any]],
    train_model_fn: Callable[..., Tuple[Optional[Any], str]],
    training_result_fn: Callable[..., Dict[str, Any]],
    encrypted_session_read_error: type[Exception],
    allow_expensive_offline_evaluation_fn: Callable[[List[str], List[str]], bool],
    atomic_write_text_fn: Callable[[str, str], None],
    save_metadata_hash_fn: Callable[[str], None],
    publish_initial_production_bundle_if_approved_fn: Callable[[str, Mapping[str, str], Mapping[str, Any]], bool],
    context_routing_version: str,
    normalize_window_scales_fn: Callable[[], List[float]],
    scale_metadata_label_fn: Callable[[float], str],
) -> Dict[str, Any]:
    progress_context: Dict[str, Any] = {}
    report_progress, stage_progress = _make_training_progress_callbacks(
        progress_callback=progress_callback,
        progress_context=progress_context,
        clamp01_fn=clamp01_fn,
        logger=logger,
    )

    with user_model_lifecycle_lock_fn(safe):
        paths = user_model_paths_fn(safe)
        scanned = _scan_positive_training_candidates(
            safe=safe,
            min_sessions=min_sessions,
            mark_profile_state_fn=mark_profile_state_fn,
            training_result_fn=training_result_fn,
            user_session_paths_fn=user_session_paths_fn,
            read_session_metadata_fn=read_session_metadata_fn,
            is_accepted_session_fn=is_accepted_session_fn,
            session_quality_ok_fn=session_quality_ok_fn,
            report_progress_fn=report_progress,
        )
        if not scanned["ok"]:
            return scanned["result"]

        enrollment_total = int(scanned["enrollment_total"])
        positive_candidates = list(scanned["positive_candidates"])

        try:
            raw_negative_sessions = collect_negative_sessions_fn(safe)
            selection_progress = stage_progress(10, 28, "training_stage_selecting_sessions")
            selection_progress(0.0, "training_detail_quality_selection")
            selection_summary = build_training_selection_fn(
                positive_candidates,
                raw_negative_sessions,
                max_enrollment_sessions=max_enrollment_sessions,
                progress_callback=selection_progress,
            )
            positives = list(selection_summary["positive_sessions"])
            negative_sessions = list(selection_summary["negative_sessions"])
            selected_enrollment_records = list(selection_summary["positive_pool"]["enrollment"]["included_records"])
            selected_protected_records = list(selection_summary["positive_pool"]["protected"]["included_records"])

            if not positives:
                mark_profile_state_fn(safe, "failed")
                return training_result_fn(
                    False,
                    "training_need_higher_quality_sessions",
                    "Training did not start because the trusted sessions available for this user were too low-quality or too repetitive after the new quality/diversity gate. Collect a few longer and more varied sessions, then try again.",
                    session_count=enrollment_total,
                    training_selection=selection_summary,
                )

            progress_context.update({
                "positive_sessions": int(len(positives)),
                "reference_negatives": int(len(negative_sessions)),
            })
            train_progress = stage_progress(28, 78, "training_stage_training_model")
            train_progress(0.0, "training_detail_extracting_session", {"current": 0, "total": max(1, len(positives) + len(negative_sessions))})
            model, status = train_model_fn(
                sessions=positives + negative_sessions,
                negative_sessions=negative_sessions,
                model_file=paths["model"],
                classifier_file=paths["classifier"],
                metadata_file=paths["metadata"],
                session_window_limits=selection_summary.get("session_window_limits"),
                progress_callback=train_progress,
                training_selection=selection_summary,
            )
        except encrypted_session_read_error as exc:
            mark_profile_state_fn(safe, "failed")
            return training_result_fn(
                False,
                "training_corrupt_sessions",
                "Training failed because one or more session logs are unreadable or corrupted. Remove the damaged session and try again.",
                error=str(exc),
            )
        except Exception as exc:
            logger.error("Training pipeline crashed for %s before model publish: %s", safe, exc, exc_info=True)
            mark_profile_state_fn(safe, "failed")
            return training_result_fn(
                False,
                "training_failed_before_publish",
                f"Training failed before the model could be published: {exc}",
                error=str(exc),
            )

    if model is None or status != "ok":
        mark_profile_state_fn(safe, "failed")
        return training_result_fn(
            False,
            "training_failed_general",
            "Training failed. Collect longer enrollment sessions or a few more sessions so the model has enough behavioral windows to learn from.",
        )

    publish_result = _evaluate_and_publish_candidate(
        safe=safe,
        paths=paths,
        positives=positives,
        negative_sessions=negative_sessions,
        selection_summary=selection_summary,
        report_progress_fn=report_progress,
        stage_progress_factory=stage_progress,
        allow_expensive_offline_evaluation_fn=allow_expensive_offline_evaluation_fn,
        atomic_write_text_fn=atomic_write_text_fn,
        save_metadata_hash_fn=save_metadata_hash_fn,
        publish_initial_production_bundle_if_approved_fn=publish_initial_production_bundle_if_approved_fn,
        context_routing_version=context_routing_version,
        logger=logger,
    )
    policy_decision = dict(publish_result["policy_decision"])

    runtime_metadata_for_result: Dict[str, Any] = {}
    try:
        from artifact_integrity import load_metadata as _load_runtime_metadata

        runtime_metadata_for_result = dict(_load_runtime_metadata(paths["metadata"]) or {})
        active_contexts = list((runtime_metadata_for_result.get("context_models") or {}).get("active_contexts") or ["global_only"])
    except Exception:
        active_contexts = ["global_only"]
        runtime_metadata_for_result = {}
    report_progress(99, "training_stage_publishing_profile", "training_detail_done")
    mark_profile_state_fn(safe, "ready")
    report_progress(100, "training_stage_complete", "training_detail_done")
    return training_result_fn(
        True,
        "training_finished_summary",
        f"Training finished with multi-scale behavioral profiling, quality/diversity-gated session selection, hard-negative mining, context-specific routing with global fallback, user-specific calibration, and transition-aware evidence handling, sequence/trend-aware feature families, and a stronger challenger supervised model selection path. Active scales: {', '.join(scale_metadata_label_fn(scale) for scale in normalize_window_scales_fn())}. Enrollment sessions used: {len(selected_enrollment_records)} out of {enrollment_total} saved; supplemental protected sessions used: {len(selected_protected_records)}; reference negatives used: {len(negative_sessions)}. Active routed contexts: {', '.join(active_contexts)}. Offline status: {policy_decision['model_status']}",
        message_params={
            "used_enrollment": len(selected_enrollment_records),
            "total_enrollment": enrollment_total,
            "used_protected": len(selected_protected_records),
            "used_negative": len(negative_sessions),
        },
        session_count=enrollment_total,
        used_enrollment_sessions=len(selected_enrollment_records),
        used_protected_sessions=len(selected_protected_records),
        used_negative_sessions=len(negative_sessions),
        training_selection=selection_summary,
        model_status=policy_decision["model_status"],
        policy_version=policy_decision.get("policy_version"),
        approval_reason=policy_decision.get("approval_reason"),
        evaluation_report_file=os.path.basename(paths["evaluation_report"]) if os.path.exists(paths["evaluation_report"]) else None,
        evaluation_summary_file=os.path.basename(paths["evaluation_summary"]) if os.path.exists(paths["evaluation_summary"]) else None,
        **_candidate_artifact_summary_from_metadata(runtime_metadata_for_result),
    )
