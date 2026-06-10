from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from bioauth_model.classical_baselines import (
    CLASSICAL_BASELINE_SCHEMA_VERSION,
    NNMahalanobisVerifier,
    OneClassSVMBaseline,
    ScaledManhattanVerifier,
)

from .artifacts import SklearnOneClassRiskArtifact
from .common import _artifact_metadata, _dependency_available, _feature_dimension_reason, _finite_quantile, _matrix
from .constants import (
    AtomicBytesWriter,
    AtomicTextWriter,
    CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    CLASSICAL_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    CLASSICAL_CANDIDATE_IDS,
    MANIFEST_FILENAME,
    MAX_DENSITY_MODEL_FEATURES,
    _MIN_CLASSICAL_SAMPLES,
)
from .io import _atomic_write_bytes, _atomic_write_text, _write_pickle_artifact
from .manifest import _manifest_entry, _skipped, _trained_entry

def _build_scaled_manhattan(X: np.ndarray, feature_names: Sequence[str], feature_schema_version: str | None, model_dir: Path, writer: AtomicBytesWriter) -> dict[str, Any]:
    cid = "classic_scaled_manhattan"
    if X.shape[0] < _MIN_CLASSICAL_SAMPLES[cid] or X.shape[1] < 1:
        return _skipped(cid, reason="insufficient_genuine_samples", X=X, feature_names=feature_names, model_family="scaled_manhattan")
    artifact = ScaledManhattanVerifier().fit(X)
    if not bool(getattr(artifact, "available_", False)):
        return _skipped(cid, reason=str(getattr(artifact, "reason_", "artifact_training_failed")), X=X, feature_names=feature_names, model_family="scaled_manhattan")
    artifact.candidate_artifact_metadata_ = _artifact_metadata(
        candidate_id=cid,
        model_family="scaled_manhattan",
        feature_names=feature_names,
        feature_schema_version=feature_schema_version,
        threshold=artifact.threshold_,
        threshold_source="owner_positive_p95",
        training_sample_count=X.shape[0],
        hyperparameters={"epsilon": artifact.epsilon, "scale_method": artifact.scale_method},
    )
    rel_path, digest = _write_pickle_artifact(model_dir=model_dir, candidate_id=cid, artifact=artifact, writer=writer)
    return _trained_entry(candidate_id=cid, artifact_path=rel_path, artifact_digest=digest, feature_names=feature_names, threshold=artifact.threshold_, training_sample_count=X.shape[0], model_family="scaled_manhattan")


def _build_nn_mahalanobis(X: np.ndarray, feature_names: Sequence[str], feature_schema_version: str | None, model_dir: Path, writer: AtomicBytesWriter) -> dict[str, Any]:
    cid = "classic_nn_mahalanobis"
    if X.shape[0] < _MIN_CLASSICAL_SAMPLES[cid] or X.shape[1] < 1:
        return _skipped(cid, reason="insufficient_genuine_samples", X=X, feature_names=feature_names, model_family="nn_mahalanobis")
    dimension_reason = _feature_dimension_reason(X)
    if dimension_reason:
        return _skipped(cid, reason=dimension_reason, X=X, feature_names=feature_names, model_family="nn_mahalanobis")
    artifact = NNMahalanobisVerifier().fit(X)
    if not bool(getattr(artifact, "available_", False)):
        return _skipped(cid, reason=str(getattr(artifact, "reason_", "artifact_training_failed")), X=X, feature_names=feature_names, model_family="nn_mahalanobis")
    artifact.candidate_artifact_metadata_ = _artifact_metadata(
        candidate_id=cid,
        model_family="nn_mahalanobis",
        feature_names=feature_names,
        feature_schema_version=feature_schema_version,
        threshold=artifact.threshold_,
        threshold_source="owner_positive_p95",
        training_sample_count=X.shape[0],
        hyperparameters={"regularization": artifact.regularization, "used_pinv": artifact.used_pinv_},
    )
    rel_path, digest = _write_pickle_artifact(model_dir=model_dir, candidate_id=cid, artifact=artifact, writer=writer)
    return _trained_entry(candidate_id=cid, artifact_path=rel_path, artifact_digest=digest, feature_names=feature_names, threshold=artifact.threshold_, training_sample_count=X.shape[0], model_family="nn_mahalanobis", extra={"used_pinv": artifact.used_pinv_})


def _build_one_class_svm(X: np.ndarray, feature_names: Sequence[str], feature_schema_version: str | None, model_dir: Path, writer: AtomicBytesWriter) -> dict[str, Any]:
    cid = "classic_one_class_svm"
    if X.shape[0] < _MIN_CLASSICAL_SAMPLES[cid] or X.shape[1] < 1:
        return _skipped(cid, reason="insufficient_genuine_samples", X=X, feature_names=feature_names, model_family="one_class_svm")
    artifact = OneClassSVMBaseline(min_samples=_MIN_CLASSICAL_SAMPLES[cid]).fit(X)
    if not bool(getattr(artifact, "available_", False)):
        return _skipped(cid, reason=str(getattr(artifact, "reason_", "artifact_training_failed")), X=X, feature_names=feature_names, model_family="one_class_svm")
    artifact.candidate_artifact_metadata_ = _artifact_metadata(
        candidate_id=cid,
        model_family="one_class_svm",
        feature_names=feature_names,
        feature_schema_version=feature_schema_version,
        threshold=artifact.threshold_,
        threshold_source="owner_positive_p95",
        training_sample_count=X.shape[0],
        hyperparameters={"kernel": artifact.kernel, "nu": artifact.nu, "gamma": artifact.gamma, "min_samples": artifact.min_samples},
    )
    rel_path, digest = _write_pickle_artifact(model_dir=model_dir, candidate_id=cid, artifact=artifact, writer=writer)
    return _trained_entry(candidate_id=cid, artifact_path=rel_path, artifact_digest=digest, feature_names=feature_names, threshold=artifact.threshold_, training_sample_count=X.shape[0], model_family="one_class_svm")


def _build_lof(X: np.ndarray, feature_names: Sequence[str], feature_schema_version: str | None, model_dir: Path, writer: AtomicBytesWriter) -> dict[str, Any]:
    cid = "classic_lof"
    if X.shape[0] < _MIN_CLASSICAL_SAMPLES[cid] or X.shape[1] < 1:
        return _skipped(cid, reason="insufficient_genuine_samples", X=X, feature_names=feature_names, model_family="local_outlier_factor")
    dimension_reason = _feature_dimension_reason(X)
    if dimension_reason:
        return _skipped(cid, reason=dimension_reason, X=X, feature_names=feature_names, model_family="local_outlier_factor")
    if not _dependency_available("sklearn.neighbors"):
        return _skipped(cid, reason="dependency_missing:sklearn", X=X, feature_names=feature_names, model_family="local_outlier_factor")
    try:
        from sklearn.neighbors import LocalOutlierFactor

        n_neighbors = max(1, min(20, X.shape[0] - 1))
        estimator = LocalOutlierFactor(n_neighbors=n_neighbors, novelty=True)
        estimator.fit(X)
        train_scores = -np.asarray(estimator.decision_function(X), dtype=float).reshape(-1)
        threshold = _finite_quantile(train_scores)
        if threshold is None:
            return _skipped(cid, reason="threshold_unavailable", X=X, feature_names=feature_names, model_family="local_outlier_factor")
        metadata = _artifact_metadata(
            candidate_id=cid,
            model_family="local_outlier_factor",
            feature_names=feature_names,
            feature_schema_version=feature_schema_version,
            threshold=threshold,
            threshold_source="owner_positive_p95",
            training_sample_count=X.shape[0],
            hyperparameters={"n_neighbors": n_neighbors, "novelty": True},
        )
        artifact = SklearnOneClassRiskArtifact(
            estimator=estimator,
            candidate_id=cid,
            model_family="local_outlier_factor",
            feature_names=tuple(str(name) for name in feature_names),
            threshold_=threshold,
            threshold_source="owner_positive_p95",
            training_sample_count=int(X.shape[0]),
            score_method="negative_decision_function",
            artifact_metadata=metadata,
        )
        rel_path, digest = _write_pickle_artifact(model_dir=model_dir, candidate_id=cid, artifact=artifact, writer=writer)
        return _trained_entry(candidate_id=cid, artifact_path=rel_path, artifact_digest=digest, feature_names=feature_names, threshold=threshold, training_sample_count=X.shape[0], model_family="local_outlier_factor", extra={"n_neighbors": n_neighbors})
    except Exception as exc:
        return _manifest_entry(
            candidate_id=cid,
            status="failed",
            artifact_path=None,
            feature_names=feature_names,
            threshold=None,
            threshold_source="not_available",
            training_sample_count=int(X.shape[0]),
            reason=f"artifact_training_error:{type(exc).__name__}",
            model_family="local_outlier_factor",
        )


def _build_gmm(X: np.ndarray, feature_names: Sequence[str], feature_schema_version: str | None, model_dir: Path, writer: AtomicBytesWriter) -> dict[str, Any]:
    cid = "classic_gmm"
    if X.shape[0] < _MIN_CLASSICAL_SAMPLES[cid] or X.shape[1] < 1:
        return _skipped(cid, reason="insufficient_genuine_samples", X=X, feature_names=feature_names, model_family="gaussian_mixture")
    dimension_reason = _feature_dimension_reason(X)
    if dimension_reason:
        return _skipped(cid, reason=dimension_reason, X=X, feature_names=feature_names, model_family="gaussian_mixture")
    if not _dependency_available("sklearn.mixture"):
        return _skipped(cid, reason="dependency_missing:sklearn", X=X, feature_names=feature_names, model_family="gaussian_mixture")
    try:
        from sklearn.mixture import GaussianMixture

        n_components = max(1, min(2, X.shape[0] // 2))
        estimator = GaussianMixture(n_components=n_components, covariance_type="diag", reg_covar=1e-6, random_state=42)
        estimator.fit(X)
        train_scores = -np.asarray(estimator.score_samples(X), dtype=float).reshape(-1)
        threshold = _finite_quantile(train_scores)
        if threshold is None:
            return _skipped(cid, reason="threshold_unavailable", X=X, feature_names=feature_names, model_family="gaussian_mixture")
        metadata = _artifact_metadata(
            candidate_id=cid,
            model_family="gaussian_mixture",
            feature_names=feature_names,
            feature_schema_version=feature_schema_version,
            threshold=threshold,
            threshold_source="owner_positive_p95",
            training_sample_count=X.shape[0],
            hyperparameters={"n_components": n_components, "covariance_type": "diag", "reg_covar": 1e-6, "random_state": 42},
            extra={"n_components": n_components, "min_training_samples": _MIN_CLASSICAL_SAMPLES[cid]},
        )
        artifact = SklearnOneClassRiskArtifact(
            estimator=estimator,
            candidate_id=cid,
            model_family="gaussian_mixture",
            feature_names=tuple(str(name) for name in feature_names),
            threshold_=threshold,
            threshold_source="owner_positive_p95",
            training_sample_count=int(X.shape[0]),
            score_method="negative_score_samples",
            artifact_metadata=metadata,
        )
        rel_path, digest = _write_pickle_artifact(model_dir=model_dir, candidate_id=cid, artifact=artifact, writer=writer)
        return _trained_entry(candidate_id=cid, artifact_path=rel_path, artifact_digest=digest, feature_names=feature_names, threshold=threshold, training_sample_count=X.shape[0], model_family="gaussian_mixture", extra={"n_components": n_components, "min_training_samples": _MIN_CLASSICAL_SAMPLES[cid]})
    except Exception as exc:
        return _manifest_entry(
            candidate_id=cid,
            status="failed",
            artifact_path=None,
            feature_names=feature_names,
            threshold=None,
            threshold_source="not_available",
            training_sample_count=int(X.shape[0]),
            reason=f"artifact_training_error:{type(exc).__name__}",
            model_family="gaussian_mixture",
        )


def build_classical_candidate_artifacts(
    *,
    model_dir: str | os.PathLike[str],
    X_pos: Sequence[Sequence[float]] | np.ndarray,
    feature_names: Sequence[str],
    feature_schema_version: str | None = None,
    atomic_write_bytes_fn: AtomicBytesWriter | None = None,
    atomic_write_text_fn: AtomicTextWriter | None = None,
) -> dict[str, Any]:
    """Build report-only classical candidate artifacts into a candidate bundle.

    ``X_pos`` must contain owner-positive windows only.  The training pipeline
    supplies this matrix from labels where ``0`` is genuine/owner, so confirmed
    intruder/negative windows are excluded before this builder is called.
    """

    output_dir = Path(model_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    X = _matrix(X_pos)
    names = [str(name) for name in feature_names]
    byte_writer = atomic_write_bytes_fn or _atomic_write_bytes
    text_writer = atomic_write_text_fn or _atomic_write_text

    entries: dict[str, dict[str, Any]] = {}
    for builder in (
        _build_lof,
        _build_one_class_svm,
        _build_gmm,
        _build_scaled_manhattan,
        _build_nn_mahalanobis,
    ):
        entry = builder(X, names, feature_schema_version, output_dir, byte_writer)
        entries[str(entry["candidate_id"])] = entry

    manifest = {
        "schema_version": CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "builder_version": CLASSICAL_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        "artifact_schema": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "candidate_ids": list(CLASSICAL_CANDIDATE_IDS),
        "status_counts": {
            "trained": int(sum(1 for item in entries.values() if item.get("status") == "trained")),
            "skipped": int(sum(1 for item in entries.values() if item.get("status") == "skipped")),
            "failed": int(sum(1 for item in entries.values() if item.get("status") == "failed")),
        },
        "feature_names": names,
        "feature_schema_version": feature_schema_version,
        "training_sample_count": int(X.shape[0]) if X.ndim == 2 else 0,
        "trained_on": "genuine_owner_windows_only",
        "report_only": True,
        "can_lock": False,
        "can_lock_alone": False,
        "can_influence_device": False,
        "runtime_authoritative": False,
        "trigger_face_confirmation": False,
        "artifact_serialization": "pickle",
        "artifact_trust_boundary": "trusted_local_candidate_bundle_only",
        "candidates": entries,
    }
    manifest_path = output_dir / MANIFEST_FILENAME
    text_writer(str(manifest_path), json.dumps(manifest, indent=2, ensure_ascii=False))
    return {
        "schema_version": CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "builder_version": CLASSICAL_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        "manifest_path": MANIFEST_FILENAME,
        "manifest": manifest,
        "candidate_artifacts": entries,
        "status_counts": dict(manifest["status_counts"]),
        "report_only": True,
        "can_lock": False,
        "can_lock_alone": False,
        "can_influence_device": False,
        "runtime_authoritative": False,
        "trigger_face_confirmation": False,
    }