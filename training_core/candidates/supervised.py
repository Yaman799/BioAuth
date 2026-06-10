from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from utils.dependency_probe import probe_dependency

from .artifacts import OptionalSupervisedDependencySpec, SupervisedRiskArtifact
from .common import _artifact_metadata, _dependency_version, _matrix
from .constants import (
    AtomicBytesWriter,
    AtomicTextWriter,
    CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
    MIN_SUPERVISED_INTRUDER_SAMPLES,
    MIN_SUPERVISED_OWNER_SAMPLES,
    OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_FILENAMES,
    OPTIONAL_SUPERVISED_CANDIDATE_IDS,
    OPTIONAL_SUPERVISED_DEPENDENCIES,
    OPTIONAL_SUPERVISED_MODEL_FAMILIES,
    RECOMMENDED_SUPERVISED_INTRUDER_SAMPLES,
    MANIFEST_FILENAME,
)
from .io import _atomic_write_bytes, _atomic_write_text, _write_supervised_pickle_artifact
from .manifest import _candidate_artifact_manifest_payload, _manifest_entry

def resolve_optional_supervised_dependency(candidate_id: str) -> OptionalSupervisedDependencySpec:
    cid = str(candidate_id or "").strip()
    dependency_name = OPTIONAL_SUPERVISED_DEPENDENCIES.get(cid, "")
    model_family = OPTIONAL_SUPERVISED_MODEL_FAMILIES.get(cid, cid)
    if not dependency_name:
        return OptionalSupervisedDependencySpec(cid, "", model_family, None, None, False, "dependency_missing", "")
    status = probe_dependency(dependency_name, require_import=True)
    if not status.available:
        return OptionalSupervisedDependencySpec(
            cid,
            dependency_name,
            model_family,
            None,
            status.version,
            False,
            status.reason,
            status.import_error,
        )
    try:
        if cid == "supervised_xgboost":
            module = importlib.import_module("xgboost")
            estimator_class = getattr(module, "XGBClassifier")
        elif cid == "supervised_lightgbm":
            module = importlib.import_module("lightgbm")
            estimator_class = getattr(module, "LGBMClassifier")
        elif cid == "supervised_catboost":
            module = importlib.import_module("catboost")
            estimator_class = getattr(module, "CatBoostClassifier")
        else:
            return OptionalSupervisedDependencySpec(cid, dependency_name, model_family, None, status.version, False, "dependency_missing", "")
    except Exception as exc:
        return OptionalSupervisedDependencySpec(
            cid,
            dependency_name,
            model_family,
            None,
            status.version,
            False,
            "dependency_import_failed",
            f"{type(exc).__name__}:{exc}",
        )
    return OptionalSupervisedDependencySpec(
        candidate_id=cid,
        dependency_name=dependency_name,
        model_family=model_family,
        estimator_class=estimator_class,
        dependency_version=status.version or _dependency_version(dependency_name),
        available=True,
        dependency_status="ok",
        import_error="",
    )


def _default_optional_supervised_params(candidate_id: str) -> dict[str, Any]:
    parallel_jobs = max(1, int(os.cpu_count() or 1) - 1)
    if candidate_id == "supervised_xgboost":
        return {
            "n_estimators": 80,
            "max_depth": 3,
            "learning_rate": 0.05,
            "subsample": 0.9,
            "colsample_bytree": 0.9,
            "eval_metric": "logloss",
            "random_state": 42,
            "n_jobs": parallel_jobs,
        }
    if candidate_id == "supervised_lightgbm":
        return {
            "n_estimators": 80,
            "learning_rate": 0.05,
            "num_leaves": 15,
            "min_child_samples": 1,
            "subsample": 0.9,
            "colsample_bytree": 0.9,
            "reg_lambda": 0.1,
            "random_state": 42,
            "n_jobs": parallel_jobs,
            "verbose": -1,
        }
    if candidate_id == "supervised_catboost":
        return {
            "iterations": 80,
            "depth": 4,
            "learning_rate": 0.05,
            "loss_function": "Logloss",
            "random_seed": 42,
            "verbose": False,
            "allow_writing_files": False,
            "thread_count": parallel_jobs,
        }
    return {}


def _supervised_probability_values(classifier: Any, X: np.ndarray) -> np.ndarray | None:
    if hasattr(classifier, "predict_proba"):
        probs = np.asarray(classifier.predict_proba(X), dtype=float)
        if probs.ndim == 2 and probs.shape[1] >= 2:
            return probs[:, 1].reshape(-1)
        if probs.ndim == 2 and probs.shape[1] == 1:
            return probs[:, 0].reshape(-1)
    if hasattr(classifier, "decision_function"):
        raw = np.asarray(classifier.decision_function(X), dtype=float).reshape(-1)
        return np.asarray([1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, float(value))))) for value in raw], dtype=float)
    return None


def _supervised_class_balance(owner_count: int, intruder_count: int) -> dict[str, Any]:
    total = int(owner_count) + int(intruder_count)
    return {
        "label_convention": {"genuine_owner": 0, "intruder": 1, "higher_score": "more_intruder_like"},
        "owner_samples": int(owner_count),
        "intruder_samples": int(intruder_count),
        "total_samples": int(total),
        "owner_fraction": float(owner_count / total) if total else 0.0,
        "intruder_fraction": float(intruder_count / total) if total else 0.0,
    }


def _supervised_skipped(
    candidate_id: str,
    *,
    reason: str,
    X_pos: np.ndarray,
    X_neg: np.ndarray,
    feature_names: Sequence[str],
    model_family: str,
    dependency_name: str,
    dependency_version: str | None = None,
    dependency_status: str | None = None,
    import_error: str = "",
) -> dict[str, Any]:
    owner_count = int(X_pos.shape[0]) if X_pos.ndim == 2 else 0
    intruder_count = int(X_neg.shape[0]) if X_neg.ndim == 2 else 0
    return _manifest_entry(
        candidate_id=candidate_id,
        status="skipped",
        artifact_path=None,
        feature_names=feature_names,
        threshold=None,
        threshold_source="not_available",
        training_sample_count=owner_count + intruder_count,
        reason=reason,
        model_family=model_family,
        extra={
            "builder_version": OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
            "dependency_name": dependency_name,
            "dependency_version": dependency_version,
            "dependency_available": False if str(reason).startswith("dependency_") else None,
            "dependency_status": str(dependency_status or ("dependency_missing" if str(reason).startswith("dependency_") else "not_checked")),
            "dependency_import_error": str(import_error or ""),
            "owner_sample_count": owner_count,
            "intruder_sample_count": intruder_count,
            "class_balance": _supervised_class_balance(owner_count, intruder_count),
            "trained_on": "owner_positive_and_trusted_intruder_windows",
            "artifact_mode": "skipped",
            "low_intruder_sample_warning": bool(0 < intruder_count < RECOMMENDED_SUPERVISED_INTRUDER_SAMPLES),
        },
    )


def _build_optional_supervised_candidate(
    candidate_id: str,
    *,
    X_pos: np.ndarray,
    X_neg: np.ndarray,
    feature_names: Sequence[str],
    feature_schema_version: str | None,
    model_dir: Path,
    writer: AtomicBytesWriter,
    dependency_resolver: Callable[[str], OptionalSupervisedDependencySpec] | None = None,
    estimator_params: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    cid = str(candidate_id or "").strip()
    spec = (dependency_resolver or resolve_optional_supervised_dependency)(cid)
    dependency_name = str(spec.dependency_name or OPTIONAL_SUPERVISED_DEPENDENCIES.get(cid, ""))
    dependency_version = spec.dependency_version
    model_family = str(spec.model_family or OPTIONAL_SUPERVISED_MODEL_FAMILIES.get(cid, cid))
    owner_count = int(X_pos.shape[0]) if X_pos.ndim == 2 else 0
    intruder_count = int(X_neg.shape[0]) if X_neg.ndim == 2 else 0

    if owner_count < MIN_SUPERVISED_OWNER_SAMPLES or X_pos.shape[1] < 1:
        return _supervised_skipped(
            cid,
            reason="insufficient_owner_samples",
            X_pos=X_pos,
            X_neg=X_neg,
            feature_names=feature_names,
            model_family=model_family,
            dependency_name=dependency_name,
            dependency_version=dependency_version,
        )
    if intruder_count < MIN_SUPERVISED_INTRUDER_SAMPLES or X_neg.shape[1] < 1:
        return _supervised_skipped(
            cid,
            reason="insufficient_intruder_samples",
            X_pos=X_pos,
            X_neg=X_neg,
            feature_names=feature_names,
            model_family=model_family,
            dependency_name=dependency_name,
            dependency_version=dependency_version,
        )
    if X_neg.shape[1] != X_pos.shape[1]:
        return _supervised_skipped(
            cid,
            reason="calibration_unavailable",
            X_pos=X_pos,
            X_neg=X_neg,
            feature_names=feature_names,
            model_family=model_family,
            dependency_name=dependency_name,
            dependency_version=dependency_version,
        )
    if not bool(spec.available) or spec.estimator_class is None:
        return _supervised_skipped(
            cid,
            reason="dependency_missing",
            X_pos=X_pos,
            X_neg=X_neg,
            feature_names=feature_names,
            model_family=model_family,
            dependency_name=dependency_name,
            dependency_version=dependency_version,
            dependency_status=getattr(spec, "dependency_status", "dependency_missing"),
            import_error=getattr(spec, "import_error", ""),
        )

    X = np.vstack([X_pos, X_neg]).astype(float)
    y = np.concatenate([np.zeros(owner_count, dtype=int), np.ones(intruder_count, dtype=int)])
    params = dict((estimator_params or {}).get(cid) or _default_optional_supervised_params(cid))
    low_intruder_warning = bool(intruder_count < RECOMMENDED_SUPERVISED_INTRUDER_SAMPLES)
    artifact_mode = "diagnostic_shadow" if low_intruder_warning else "offline_candidate"
    try:
        estimator = spec.estimator_class(**params)
        estimator.fit(X, y)
        train_probs = _supervised_probability_values(estimator, X)
        if train_probs is None or not np.isfinite(train_probs).any():
            return _supervised_skipped(
                cid,
                reason="calibration_unavailable",
                X_pos=X_pos,
                X_neg=X_neg,
                feature_names=feature_names,
                model_family=model_family,
                dependency_name=dependency_name,
                dependency_version=dependency_version,
            )
        threshold = 0.5
        train_probs = np.where(np.isfinite(train_probs), train_probs, 0.0).reshape(-1)
        metadata = _artifact_metadata(
            candidate_id=cid,
            model_family=model_family,
            feature_names=feature_names,
            feature_schema_version=feature_schema_version,
            threshold=threshold,
            threshold_source="classifier_probability_default_0_5",
            training_sample_count=int(X.shape[0]),
            hyperparameters=params,
            extra={
                "builder_version": OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
                "dependency_name": dependency_name,
                "dependency_version": dependency_version,
                "dependency_available": True,
                "dependency_status": "ok",
                "owner_sample_count": owner_count,
                "intruder_sample_count": intruder_count,
                "class_balance": _supervised_class_balance(owner_count, intruder_count),
                "trained_on": "owner_positive_and_trusted_intruder_windows",
                "artifact_mode": artifact_mode,
                "diagnostic_shadow_artifact": bool(low_intruder_warning),
                "low_intruder_sample_warning": bool(low_intruder_warning),
                "minimum_recommended_intruder_samples": int(RECOMMENDED_SUPERVISED_INTRUDER_SAMPLES),
                "training_score_summary": {
                    "mean_intruder_probability": float(np.mean(train_probs)),
                    "min_intruder_probability": float(np.min(train_probs)),
                    "max_intruder_probability": float(np.max(train_probs)),
                },
            },
        )
        artifact = SupervisedRiskArtifact(
            estimator=estimator,
            candidate_id=cid,
            model_family=model_family,
            feature_names=tuple(str(name) for name in feature_names),
            threshold_=threshold,
            threshold_source="classifier_probability_default_0_5",
            training_sample_count=int(X.shape[0]),
            owner_sample_count=owner_count,
            intruder_sample_count=intruder_count,
            dependency_name=dependency_name,
            dependency_version=dependency_version,
            artifact_metadata=metadata,
        )
        rel_path, digest = _write_supervised_pickle_artifact(model_dir=model_dir, candidate_id=cid, artifact=artifact, writer=writer)
        return _manifest_entry(
            candidate_id=cid,
            status="trained",
            artifact_path=rel_path,
            feature_names=feature_names,
            threshold=threshold,
            threshold_source="classifier_probability_default_0_5",
            training_sample_count=int(X.shape[0]),
            reason="ok",
            model_family=model_family,
            artifact_digest=digest,
            extra={
                "builder_version": OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
                "dependency_name": dependency_name,
                "dependency_version": dependency_version,
                "dependency_available": True,
                "dependency_status": "ok",
                "owner_sample_count": owner_count,
                "intruder_sample_count": intruder_count,
                "class_balance": _supervised_class_balance(owner_count, intruder_count),
                "trained_on": "owner_positive_and_trusted_intruder_windows",
                "artifact_mode": artifact_mode,
                "diagnostic_shadow_artifact": bool(low_intruder_warning),
                "low_intruder_sample_warning": bool(low_intruder_warning),
                "minimum_recommended_intruder_samples": int(RECOMMENDED_SUPERVISED_INTRUDER_SAMPLES),
            },
        )
    except Exception as exc:
        return _manifest_entry(
            candidate_id=cid,
            status="failed",
            artifact_path=None,
            feature_names=feature_names,
            threshold=None,
            threshold_source="not_available",
            training_sample_count=owner_count + intruder_count,
            reason=f"training_failed:{type(exc).__name__}",
            model_family=model_family,
            extra={
                "builder_version": OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
                "dependency_name": dependency_name,
                "dependency_version": dependency_version,
                "dependency_available": True,
                "dependency_status": "ok",
                "owner_sample_count": owner_count,
                "intruder_sample_count": intruder_count,
                "class_balance": _supervised_class_balance(owner_count, intruder_count),
                "trained_on": "owner_positive_and_trusted_intruder_windows",
                "artifact_mode": "failed",
                "low_intruder_sample_warning": bool(low_intruder_warning),
            },
        )


def build_optional_supervised_candidate_artifacts(
    *,
    model_dir: str | os.PathLike[str],
    X_pos: Sequence[Sequence[float]] | np.ndarray,
    X_neg: Sequence[Sequence[float]] | np.ndarray,
    feature_names: Sequence[str],
    feature_schema_version: str | None = None,
    atomic_write_bytes_fn: AtomicBytesWriter | None = None,
    atomic_write_text_fn: AtomicTextWriter | None = None,
    dependency_resolver: Callable[[str], OptionalSupervisedDependencySpec] | None = None,
    estimator_params: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build optional supervised artifacts or precise skipped rows.

    ``X_pos`` is owner-positive only and ``X_neg`` is trusted intruder/negative
    evidence. Confirmed intruder samples are never added to owner-positive data.
    Missing optional dependencies or insufficient negative evidence produce
    manifest rows instead of fake artifacts.
    """

    output_dir = Path(model_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    X_owner = _matrix(X_pos)
    X_intruder = _matrix(X_neg)
    names = [str(name) for name in feature_names]
    byte_writer = atomic_write_bytes_fn or _atomic_write_bytes
    text_writer = atomic_write_text_fn or _atomic_write_text

    entries: dict[str, dict[str, Any]] = {}
    for candidate_id in OPTIONAL_SUPERVISED_CANDIDATE_IDS:
        entry = _build_optional_supervised_candidate(
            candidate_id,
            X_pos=X_owner,
            X_neg=X_intruder,
            feature_names=names,
            feature_schema_version=feature_schema_version,
            model_dir=output_dir,
            writer=byte_writer,
            dependency_resolver=dependency_resolver,
            estimator_params=estimator_params,
        )
        entries[str(entry["candidate_id"])] = entry

    manifest = _candidate_artifact_manifest_payload(
        entries=entries,
        candidate_ids=OPTIONAL_SUPERVISED_CANDIDATE_IDS,
        builder_version=OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        feature_names=names,
        feature_schema_version=feature_schema_version,
        training_sample_count=int(X_owner.shape[0] + X_intruder.shape[0]),
        trained_on="owner_positive_and_trusted_intruder_windows",
    )
    manifest_path = output_dir / MANIFEST_FILENAME
    text_writer(str(manifest_path), json.dumps(manifest, indent=2, ensure_ascii=False))
    return {
        "schema_version": CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "builder_version": OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
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
