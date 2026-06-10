from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from bioauth_model.classical_baselines import BASELINE_SCORE_DIRECTION

from .constants import (
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
    CLASSICAL_CANDIDATE_IDS,
    COMBINED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    DEEP_ONECLASS_CANDIDATE_IDS,
    DEEP_SEQUENCE_CANDIDATE_IDS,
    KEYBOARD_DEEP_CANDIDATE_IDS,
    OPTIONAL_SUPERVISED_CANDIDATE_IDS,
    OPTIONAL_SUPERVISED_MODEL_FAMILIES,
)

def _manifest_entry(
    *,
    candidate_id: str,
    status: str,
    artifact_path: str | None,
    feature_names: Sequence[str],
    threshold: float | None,
    threshold_source: str,
    training_sample_count: int,
    reason: str,
    model_family: str,
    artifact_digest: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "candidate_id": str(candidate_id),
        "status": str(status),
        "artifact_path": artifact_path,
        "artifact_schema": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "feature_names": [str(name) for name in feature_names],
        "threshold": None if threshold is None else float(threshold),
        "decision_threshold": None if threshold is None else float(threshold),
        "threshold_source": str(threshold_source or "not_available"),
        "training_sample_count": int(training_sample_count),
        "reason": str(reason or ("ok" if status == "trained" else "unknown")),
        "model_family": str(model_family),
        "score_direction": BASELINE_SCORE_DIRECTION,
        "report_only": True,
        "can_lock": False,
        "can_lock_alone": False,
        "can_influence_device": False,
        "runtime_authoritative": False,
        "trigger_face_confirmation": False,
        "artifact_digest": str(artifact_digest or ""),
        "trained_on": "genuine_owner_windows_only",
    }
    if isinstance(extra, Mapping):
        payload.update(dict(extra))
    return payload


def _candidate_family_for_manifest(candidate_id: str) -> str:
    cid = str(candidate_id)
    if cid in CLASSICAL_CANDIDATE_IDS:
        return {
            "classic_lof": "local_outlier_factor",
            "classic_one_class_svm": "one_class_svm",
            "classic_gmm": "gaussian_mixture",
            "classic_scaled_manhattan": "scaled_manhattan",
            "classic_nn_mahalanobis": "nn_mahalanobis",
        }.get(cid, "classical")
    if cid in OPTIONAL_SUPERVISED_CANDIDATE_IDS:
        return OPTIONAL_SUPERVISED_MODEL_FAMILIES.get(cid, "optional_supervised")
    if cid in DEEP_ONECLASS_CANDIDATE_IDS:
        return {
            "oneclass_lstm_autoencoder": "lstm_autoencoder",
            "oneclass_conv_autoencoder": "conv_autoencoder",
            "oneclass_deep_svdd": "deep_svdd",
            "mouse_autoencoder": "mouse_autoencoder",
            "mouse_deep_svdd": "mouse_deep_svdd",
        }.get(cid, cid)
    if cid in KEYBOARD_DEEP_CANDIDATE_IDS:
        return {
            "keyboard_bigru_cnn_attention": "keyboard_bigru_cnn_attention",
            "keyboard_type2branch": "keyboard_type2branch",
            "keyboard_typeformer": "keyboard_typeformer",
            "keyboard_siamese_triplet": "keyboard_siamese_triplet",
        }.get(cid, cid)
    if cid in DEEP_SEQUENCE_CANDIDATE_IDS:
        return {
            "mouse_resnet_gru": "mouse_resnet_gru",
            "combined_cnn_lstm": "cnn_lstm",
        }.get(cid, cid)
    return cid


def _forced_candidate_artifact_entry(
    candidate_id: str,
    *,
    status: str,
    reason: str,
    feature_names: Sequence[str],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload_extra: dict[str, Any] = {
        "artifact_mode": str(status),
        "builder_version": COMBINED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    }
    if isinstance(extra, Mapping):
        payload_extra.update(dict(extra))
    return _manifest_entry(
        candidate_id=str(candidate_id),
        status=str(status),
        artifact_path=None,
        feature_names=[str(name) for name in feature_names],
        threshold=None,
        threshold_source="not_available",
        training_sample_count=0,
        reason=str(reason or "candidate_artifact_unavailable"),
        model_family=_candidate_family_for_manifest(str(candidate_id)),
        extra=payload_extra,
    )


def _skipped(candidate_id: str, *, reason: str, X: np.ndarray, feature_names: Sequence[str], model_family: str) -> dict[str, Any]:
    return _manifest_entry(
        candidate_id=candidate_id,
        status="skipped",
        artifact_path=None,
        feature_names=feature_names,
        threshold=None,
        threshold_source="not_available",
        training_sample_count=int(X.shape[0]) if X.ndim == 2 else 0,
        reason=reason,
        model_family=model_family,
    )


def _trained_entry(
    *,
    candidate_id: str,
    artifact_path: str,
    artifact_digest: str,
    feature_names: Sequence[str],
    threshold: float | None,
    training_sample_count: int,
    model_family: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _manifest_entry(
        candidate_id=candidate_id,
        status="trained",
        artifact_path=artifact_path,
        feature_names=feature_names,
        threshold=threshold,
        threshold_source="owner_positive_p95",
        training_sample_count=training_sample_count,
        reason="ok",
        model_family=model_family,
        artifact_digest=artifact_digest,
        extra=extra,
    )


def _candidate_artifact_manifest_payload(
    *,
    entries: Mapping[str, Mapping[str, Any]],
    candidate_ids: Sequence[str],
    builder_version: str,
    feature_names: Sequence[str],
    feature_schema_version: str | None,
    training_sample_count: int,
    trained_on: str,
) -> dict[str, Any]:
    clean_entries = {str(key): dict(value) for key, value in entries.items()}
    return {
        "schema_version": CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "builder_version": str(builder_version),
        "artifact_schema": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "candidate_ids": [str(item) for item in candidate_ids],
        "status_counts": {
            "trained": int(sum(1 for item in clean_entries.values() if item.get("status") == "trained")),
            "skipped": int(sum(1 for item in clean_entries.values() if item.get("status") == "skipped")),
            "failed": int(sum(1 for item in clean_entries.values() if item.get("status") == "failed")),
        },
        "feature_names": [str(name) for name in feature_names],
        "feature_schema_version": feature_schema_version,
        "training_sample_count": int(training_sample_count),
        "trained_on": str(trained_on),
        "report_only": True,
        "can_lock": False,
        "can_lock_alone": False,
        "can_influence_device": False,
        "runtime_authoritative": False,
        "trigger_face_confirmation": False,
        "artifact_serialization": "pickle",
        "artifact_trust_boundary": "trusted_local_candidate_bundle_only",
        "candidates": clean_entries,
    }