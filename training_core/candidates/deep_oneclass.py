from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .common import _artifact_metadata, _dependency_available, _finite_quantile
from .constants import (
    AtomicBytesWriter,
    AtomicTextWriter,
    CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    DEFAULT_DEEP_BATCH_SIZE,
    DEFAULT_DEEP_LEARNING_RATE,
    DEFAULT_DEEP_MAX_EPOCHS,
    DEEP_ONECLASS_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    DEEP_ONECLASS_CANDIDATE_ARTIFACT_FILENAMES,
    DEEP_ONECLASS_CANDIDATE_IDS,
    MANIFEST_FILENAME,
    MIN_DEEP_SEQUENCE_LENGTH,
    MIN_DEEP_SEQUENCE_WINDOWS,
    NEAR_CONSTANT_STD_EPSILON,
)
from .io import _atomic_write_bytes, _atomic_write_text, _write_torch_artifact
from .manifest import _candidate_artifact_manifest_payload, _manifest_entry

def _torch_version() -> str | None:
    try:
        import torch

        return str(getattr(torch, "__version__", "") or "")
    except Exception:
        return None


def _deep_candidate_architecture(candidate_id: str) -> str:
    mapping = {
        "oneclass_lstm_autoencoder": "lstm_autoencoder",
        "oneclass_conv_autoencoder": "conv_autoencoder",
        "oneclass_deep_svdd": "deep_svdd",
        "mouse_autoencoder": "mouse_autoencoder",
        "mouse_deep_svdd": "mouse_deep_svdd",
    }
    return mapping.get(str(candidate_id), str(candidate_id))


def _is_deep_svdd_candidate(candidate_id: str) -> bool:
    return str(candidate_id) in {"oneclass_deep_svdd", "mouse_deep_svdd"}


def _is_mouse_deep_candidate(candidate_id: str) -> bool:
    return str(candidate_id).startswith("mouse_")


def _deep_selected_feature_names(candidate_id: str, samples: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> list[str]:
    names = [str(name) for name in feature_names if str(name or "").strip()]
    if _is_mouse_deep_candidate(candidate_id):
        try:
            from deep_sequence.tensorization import infer_modality_feature_names

            inferred = infer_modality_feature_names(samples, modality="mouse")
            if inferred:
                return inferred
        except Exception:
            pass
        # Conservative fallback for tests/training matrices that already carry
        # known mouse-derived numeric window features.  Never include raw text.
        mouse_tokens = ("mouse", "dx", "dy", "distance", "velocity", "acceleration", "angle", "click", "scroll", "drag")
        return [name for name in names if any(token in name.lower() for token in mouse_tokens)]
    return names


def _group_owner_sequence_samples(
    *,
    samples: Sequence[Mapping[str, Any]],
    labels: Sequence[Any] | None,
    sample_sources: Sequence[Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    label_values = list(labels or [])
    source_values = list(sample_sources or [])
    for idx, sample in enumerate(list(samples or [])):
        if not isinstance(sample, Mapping):
            continue
        label = 0
        if idx < len(label_values):
            try:
                label = int(label_values[idx])
            except Exception:
                label = 0
        # Only owner-positive windows feed one-class training. Intruder evidence
        # is intentionally excluded and never re-labeled as owner-positive.
        if label != 0:
            continue
        source = str(source_values[idx] if idx < len(source_values) else "owner_session") or "owner_session"
        grouped.setdefault(source, []).append(dict(sample))
    return grouped


def _deep_skipped(
    candidate_id: str,
    *,
    reason: str,
    feature_names: Sequence[str],
    training_sample_count: int = 0,
    sequence_count: int = 0,
    model_family: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload_extra = {
        "builder_version": DEEP_ONECLASS_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        "dependency_name": "torch",
        "dependency_version": _torch_version(),
        "dependency_available": _dependency_available("torch"),
        "model_config": {"architecture": _deep_candidate_architecture(candidate_id)},
        "sequence_count": int(sequence_count),
        "artifact_mode": "skipped",
        "trained_on": "genuine_owner_sequence_windows_only",
        "artifact_serialization": "torch_state_dict",
    }
    if isinstance(extra, Mapping):
        payload_extra.update(dict(extra))
    return _manifest_entry(
        candidate_id=candidate_id,
        status="skipped",
        artifact_path=None,
        feature_names=feature_names,
        threshold=None,
        threshold_source="not_available",
        training_sample_count=int(training_sample_count),
        reason=str(reason),
        model_family=model_family or _deep_candidate_architecture(candidate_id),
        extra=payload_extra,
    )


def _deep_model_for_candidate(candidate_id: str, *, feature_dim: int, model_config: Mapping[str, Any] | None = None) -> Any:
    from deep_sequence.models import (
        MouseAutoencoder,
        MouseDeepSvddNetwork,
        SequenceConvAutoencoder,
        SequenceDeepSvddNetwork,
        SequenceLstmAutoencoder,
    )

    config = dict(model_config or {})
    common: dict[str, Any] = {"feature_dim": int(feature_dim)}
    if candidate_id == "oneclass_lstm_autoencoder":
        return SequenceLstmAutoencoder(
            **common,
            hidden_size=int(config.get("hidden_size") or 8),
            latent_size=int(config.get("latent_size") or 4),
            dropout=float(config.get("dropout") if config.get("dropout") is not None else 0.0),
        )
    if candidate_id == "oneclass_conv_autoencoder":
        return SequenceConvAutoencoder(
            **common,
            channels=int(config.get("channels") or 8),
            latent_channels=int(config.get("latent_channels") or 4),
            dropout=float(config.get("dropout") if config.get("dropout") is not None else 0.0),
        )
    if candidate_id == "oneclass_deep_svdd":
        return SequenceDeepSvddNetwork(
            **common,
            hidden_size=int(config.get("hidden_size") or 8),
            embedding_dim=int(config.get("embedding_dim") or 4),
            dropout=float(config.get("dropout") if config.get("dropout") is not None else 0.0),
        )
    if candidate_id == "mouse_autoencoder":
        return MouseAutoencoder(
            **common,
            channels=int(config.get("channels") or 8),
            latent_channels=int(config.get("latent_channels") or 4),
            dropout=float(config.get("dropout") if config.get("dropout") is not None else 0.0),
        )
    if candidate_id == "mouse_deep_svdd":
        return MouseDeepSvddNetwork(
            **common,
            hidden_size=int(config.get("hidden_size") or 8),
            embedding_dim=int(config.get("embedding_dim") or 4),
            dropout=float(config.get("dropout") if config.get("dropout") is not None else 0.0),
        )
    raise ValueError(f"unsupported_deep_oneclass_candidate:{candidate_id}")


def _default_deep_model_config(candidate_id: str, *, feature_dim: int, sequence_length: int) -> dict[str, Any]:
    architecture = _deep_candidate_architecture(candidate_id)
    config: dict[str, Any] = {
        "architecture": architecture,
        "candidate_id": str(candidate_id),
        "feature_dim": int(feature_dim),
        "sequence_length": int(sequence_length),
        "dropout": 0.0,
    }
    if "lstm" in architecture:
        config.update({"hidden_size": 8, "latent_size": 4})
    elif "svdd" in architecture:
        config.update({"hidden_size": 8, "embedding_dim": 4})
    else:
        config.update({"channels": 8, "latent_channels": 4})
    return config


from .deep_oneclass_training import _train_deep_oneclass_candidate


def _build_deep_oneclass_candidate(
    candidate_id: str,
    *,
    samples: Sequence[Mapping[str, Any]],
    labels: Sequence[Any] | None,
    sample_sources: Sequence[Any] | None,
    feature_names: Sequence[str],
    feature_schema_version: str | None,
    sequence_length: int,
    model_dir: Path,
    writer: AtomicBytesWriter,
    max_epochs: int,
    batch_size: int,
    learning_rate: float,
    seed: int,
) -> dict[str, Any]:
    cid = str(candidate_id)
    owner_groups = _group_owner_sequence_samples(samples=samples, labels=labels, sample_sources=sample_sources)
    owner_samples_flat = [sample for group in owner_groups.values() for sample in group]
    selected_features = _deep_selected_feature_names(cid, owner_samples_flat, feature_names)
    if not owner_groups:
        reason = "insufficient_mouse_windows" if _is_mouse_deep_candidate(cid) else "insufficient_sequence_windows"
        return _deep_skipped(cid, reason=reason, feature_names=selected_features or feature_names)
    if not selected_features:
        reason = "insufficient_mouse_windows" if _is_mouse_deep_candidate(cid) else "insufficient_window_features"
        return _deep_skipped(cid, reason=reason, feature_names=[])
    try:
        from deep_sequence.tensorization import build_sequence_dataset_from_session_samples

        payload = build_sequence_dataset_from_session_samples(
            owner_groups,
            selected_features,
            {session_id: 0 for session_id in owner_groups},
            sequence_length=max(MIN_DEEP_SEQUENCE_LENGTH, int(sequence_length or MIN_DEEP_SEQUENCE_LENGTH)),
            stride=1,
        )
        X = payload.get("X")
        sequence_count = int(payload.get("sequence_count") or (X.shape[0] if isinstance(X, np.ndarray) and X.ndim == 3 else 0))
        if not isinstance(X, np.ndarray) or X.ndim != 3 or sequence_count < MIN_DEEP_SEQUENCE_WINDOWS:
            reason = "insufficient_mouse_windows" if _is_mouse_deep_candidate(cid) else "insufficient_sequence_windows"
            return _deep_skipped(
                cid,
                reason=reason,
                feature_names=selected_features,
                training_sample_count=sequence_count,
                sequence_count=sequence_count,
                extra={"sequence_dataset": {"sequence_count": sequence_count, "skipped_sessions": list(payload.get("skipped_sessions") or [])}},
            )
        return _train_deep_oneclass_candidate(
            cid,
            sequence_tensor=X,
            feature_names=selected_features,
            feature_schema_version=feature_schema_version,
            model_dir=model_dir,
            writer=writer,
            max_epochs=max_epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
            seed=seed,
        )
    except Exception as exc:
        return _manifest_entry(
            candidate_id=cid,
            status="failed",
            artifact_path=None,
            feature_names=selected_features,
            threshold=None,
            threshold_source="not_available",
            training_sample_count=0,
            reason=f"training_failed:{type(exc).__name__}",
            model_family=_deep_candidate_architecture(cid),
            extra={"builder_version": DEEP_ONECLASS_CANDIDATE_ARTIFACT_BUILDER_VERSION, "artifact_mode": "failed"},
        )


def build_deep_oneclass_candidate_artifacts(
    *,
    model_dir: str | os.PathLike[str],
    samples: Sequence[Mapping[str, Any]] | None = None,
    labels: Sequence[Any] | None = None,
    sample_sources: Sequence[Any] | None = None,
    feature_names: Sequence[str],
    feature_schema_version: str | None = None,
    sequence_length: int = MIN_DEEP_SEQUENCE_LENGTH,
    atomic_write_bytes_fn: AtomicBytesWriter | None = None,
    atomic_write_text_fn: AtomicTextWriter | None = None,
    max_epochs: int = DEFAULT_DEEP_MAX_EPOCHS,
    batch_size: int = DEFAULT_DEEP_BATCH_SIZE,
    learning_rate: float = DEFAULT_DEEP_LEARNING_RATE,
    seed: int = 20260512,
) -> dict[str, Any]:
    """Build report-only PyTorch one-class/mouse candidate artifacts.

    Artifacts are created only from owner-positive numeric window samples. Missing
    PyTorch, empty/short sequences, missing mouse features, or nearly constant
    inputs produce skipped manifest rows rather than fake/random artifacts.
    """

    output_dir = Path(model_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    names = [str(name) for name in feature_names]
    byte_writer = atomic_write_bytes_fn or _atomic_write_bytes
    text_writer = atomic_write_text_fn or _atomic_write_text
    entries: dict[str, dict[str, Any]] = {}
    for candidate_id in DEEP_ONECLASS_CANDIDATE_IDS:
        entry = _build_deep_oneclass_candidate(
            candidate_id,
            samples=list(samples or []),
            labels=list(labels or []),
            sample_sources=list(sample_sources or []),
            feature_names=names,
            feature_schema_version=feature_schema_version,
            sequence_length=int(sequence_length or MIN_DEEP_SEQUENCE_LENGTH),
            model_dir=output_dir,
            writer=byte_writer,
            max_epochs=int(max_epochs),
            batch_size=int(batch_size),
            learning_rate=float(learning_rate),
            seed=int(seed),
        )
        entries[str(entry["candidate_id"])] = entry
    manifest = _candidate_artifact_manifest_payload(
        entries=entries,
        candidate_ids=DEEP_ONECLASS_CANDIDATE_IDS,
        builder_version=DEEP_ONECLASS_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        feature_names=names,
        feature_schema_version=feature_schema_version,
        training_sample_count=int(sum(int(entry.get("training_sample_count") or 0) for entry in entries.values())),
        trained_on="genuine_owner_sequence_windows_only",
    )
    manifest["artifact_serialization"] = "torch_state_dict"
    manifest_path = output_dir / MANIFEST_FILENAME
    text_writer(str(manifest_path), json.dumps(manifest, indent=2, ensure_ascii=False))
    return {
        "schema_version": CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "builder_version": DEEP_ONECLASS_CANDIDATE_ARTIFACT_BUILDER_VERSION,
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
