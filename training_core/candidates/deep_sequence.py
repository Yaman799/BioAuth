from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .common import _artifact_metadata, _dependency_available, _finite_quantile, _utc_now_iso
from .constants import (
    AtomicBytesWriter,
    AtomicTextWriter,
    CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    DEFAULT_DEEP_BATCH_SIZE,
    DEFAULT_DEEP_LEARNING_RATE,
    DEFAULT_DEEP_MAX_EPOCHS,
    DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    DEEP_SEQUENCE_CANDIDATE_ARTIFACT_FILENAMES,
    DEEP_SEQUENCE_CANDIDATE_IDS,
    MANIFEST_FILENAME,
    MIN_COMBINED_SEQUENCE_WINDOWS,
    MIN_DEEP_SEQUENCE_LENGTH,
    MIN_DEEP_SEQUENCE_NATIVE_WINDOWS,
    NEAR_CONSTANT_STD_EPSILON,
)
from .deep_oneclass import _deep_selected_feature_names, _torch_version
from .io import _atomic_write_bytes, _atomic_write_text, _write_torch_artifact
from .manifest import _candidate_artifact_manifest_payload, _manifest_entry, _trained_entry

def _deep_sequence_native_architecture(candidate_id: str) -> str:
    mapping = {
        "mouse_resnet_gru": "mouse_resnet_gru",
        "combined_cnn_lstm": "cnn_lstm",
    }
    return mapping.get(str(candidate_id), str(candidate_id))


def _deep_sequence_native_feature_names(candidate_id: str, samples: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> list[str]:
    cid = str(candidate_id)
    if cid == "mouse_resnet_gru":
        return _deep_selected_feature_names("mouse_resnet_gru", samples, feature_names)
    disallowed_exact = {"text", "raw_text", "typed_text", "plaintext", "characters", "char", "key", "key_name", "key_value", "password"}
    disallowed_substrings = ("raw_text", "typed_text", "plaintext", "transcript", "password")
    selected: list[str] = []
    seen: set[str] = set()
    for raw_name in feature_names:
        name = str(raw_name or "").strip()
        lower = name.lower()
        if not name or lower in disallowed_exact or any(token in lower for token in disallowed_substrings):
            continue
        if name not in seen:
            seen.add(name)
            selected.append(name)
    return selected


def _group_sequence_samples_by_label(
    *,
    samples: Sequence[Mapping[str, Any]],
    labels: Sequence[Any] | None,
    sample_sources: Sequence[Any] | None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    labels_by_group: dict[str, int] = {}
    label_values = list(labels or [])
    source_values = list(sample_sources or [])
    for idx, sample in enumerate(list(samples or [])):
        if not isinstance(sample, Mapping):
            continue
        try:
            label = int(label_values[idx]) if idx < len(label_values) else 0
        except Exception:
            label = 0
        label = 1 if label else 0
        source = str(source_values[idx] if idx < len(source_values) else f"session-{idx}") or f"session-{idx}"
        key = f"{'intruder' if label else 'owner'}:{source}"
        grouped.setdefault(key, []).append(dict(sample))
        labels_by_group[key] = label
    return grouped, labels_by_group


def _deep_sequence_native_skipped(
    candidate_id: str,
    *,
    reason: str,
    feature_names: Sequence[str],
    training_sample_count: int = 0,
    sequence_count: int = 0,
    owner_sequence_count: int = 0,
    intruder_sequence_count: int = 0,
    model_family: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload_extra = {
        "builder_version": DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        "dependency_name": "torch",
        "dependency_version": _torch_version(),
        "dependency_available": _dependency_available("torch"),
        "model_config": {"architecture": _deep_sequence_native_architecture(candidate_id)},
        "sequence_count": int(sequence_count),
        "owner_sequence_count": int(owner_sequence_count),
        "intruder_sequence_count": int(intruder_sequence_count),
        "artifact_mode": "skipped",
        "trained_on": "owner_sequence_windows" if str(candidate_id) == "mouse_resnet_gru" else "owner_and_trusted_intruder_sequence_windows",
        "artifact_serialization": "torch_state_dict",
        "privacy": {"stores_raw_text": False, "raw_text_fields_stored": [], "raw_text_stored": False},
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
        model_family=model_family or _deep_sequence_native_architecture(candidate_id),
        extra=payload_extra,
    )


def _deep_sequence_native_model_for_candidate(candidate_id: str, *, feature_dim: int, model_config: Mapping[str, Any] | None = None) -> Any:
    from deep_sequence.models import MouseResNetGruVerifier, SequenceCnnLstm

    config = dict(model_config or {})
    if str(candidate_id) == "mouse_resnet_gru":
        return MouseResNetGruVerifier(
            feature_dim=int(feature_dim),
            channels=int(config.get("channels") or 8),
            residual_blocks=int(config.get("residual_blocks") or 1),
            gru_hidden_size=int(config.get("gru_hidden_size") or 8),
            dropout=float(config.get("dropout") if config.get("dropout") is not None else 0.0),
        )
    if str(candidate_id) == "combined_cnn_lstm":
        return SequenceCnnLstm(
            feature_dim=int(feature_dim),
            conv_channels=int(config.get("conv_channels") or 8),
            hidden_size=int(config.get("hidden_size") or 8),
            dropout=float(config.get("dropout") if config.get("dropout") is not None else 0.0),
        )
    raise ValueError(f"unsupported_deep_sequence_candidate:{candidate_id}")


def _default_deep_sequence_native_model_config(candidate_id: str, *, feature_dim: int, sequence_length: int) -> dict[str, Any]:
    cid = str(candidate_id)
    config: dict[str, Any] = {
        "architecture": _deep_sequence_native_architecture(cid),
        "candidate_id": cid,
        "feature_dim": int(feature_dim),
        "sequence_length": int(sequence_length),
        "dropout": 0.0,
    }
    if cid == "mouse_resnet_gru":
        config.update({"channels": 8, "residual_blocks": 1, "gru_hidden_size": 8})
    else:
        config.update({"conv_channels": 8, "hidden_size": 8})
    return config


def _binary_metrics(y_true: np.ndarray, probabilities: np.ndarray, threshold: float = 0.5) -> dict[str, Any]:
    y = np.asarray(y_true, dtype=int).reshape(-1)
    p = np.asarray(probabilities, dtype=float).reshape(-1)
    if y.size == 0 or p.size == 0 or y.size != p.size:
        return {"sample_count": int(y.size), "threshold": float(threshold)}
    pred = (p >= float(threshold)).astype(int)
    owner = int(np.sum(y == 0))
    intruder = int(np.sum(y == 1))
    tn = int(np.sum((y == 0) & (pred == 0)))
    fp = int(np.sum((y == 0) & (pred == 1)))
    fn = int(np.sum((y == 1) & (pred == 0)))
    tp = int(np.sum((y == 1) & (pred == 1)))
    return {
        "sample_count": int(y.size),
        "owner_sequence_count": owner,
        "intruder_sequence_count": intruder,
        "threshold": float(threshold),
        "accuracy": float((tp + tn) / max(1, y.size)),
        "far": float(fp / max(1, owner)) if owner else 0.0,
        "frr": float(fn / max(1, intruder)) if intruder else 0.0,
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
    }


from .deep_sequence_training import _train_deep_sequence_native_candidate


def _build_deep_sequence_native_candidate(
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
    grouped_all, labels_by_group = _group_sequence_samples_by_label(samples=samples, labels=labels, sample_sources=sample_sources)
    all_samples_flat = [sample for group in grouped_all.values() for sample in group]
    selected_features = _deep_sequence_native_feature_names(cid, all_samples_flat, feature_names)
    if cid == "mouse_resnet_gru":
        owner_groups = {key: value for key, value in grouped_all.items() if int(labels_by_group.get(key, 0)) == 0}
        if not owner_groups:
            return _deep_sequence_native_skipped(cid, reason="insufficient_mouse_windows", feature_names=selected_features or feature_names)
        if not selected_features:
            return _deep_sequence_native_skipped(cid, reason="insufficient_mouse_windows", feature_names=[])
        build_groups = owner_groups
        build_labels = {session_id: 0 for session_id in owner_groups}
    elif cid == "combined_cnn_lstm":
        if not grouped_all:
            return _deep_sequence_native_skipped(cid, reason="insufficient_combined_windows", feature_names=selected_features or feature_names)
        if not selected_features:
            return _deep_sequence_native_skipped(cid, reason="insufficient_combined_windows", feature_names=[])
        if 0 not in set(labels_by_group.values()):
            return _deep_sequence_native_skipped(cid, reason="insufficient_owner_samples", feature_names=selected_features)
        if 1 not in set(labels_by_group.values()):
            return _deep_sequence_native_skipped(cid, reason="insufficient_combined_windows", feature_names=selected_features, extra={"requires_trusted_intruder_sequences": True})
        build_groups = grouped_all
        build_labels = labels_by_group
    else:
        return _deep_sequence_native_skipped(cid, reason="trainer_not_available", feature_names=selected_features or feature_names)
    try:
        from deep_sequence.tensorization import build_sequence_dataset_from_session_samples

        payload = build_sequence_dataset_from_session_samples(
            build_groups,
            selected_features,
            build_labels,
            sequence_length=max(MIN_DEEP_SEQUENCE_LENGTH, int(sequence_length or MIN_DEEP_SEQUENCE_LENGTH)),
            stride=1,
        )
        X = payload.get("X")
        y = payload.get("y")
        sequence_count = int(payload.get("sequence_count") or (X.shape[0] if isinstance(X, np.ndarray) and X.ndim == 3 else 0))
        if not isinstance(X, np.ndarray) or X.ndim != 3 or sequence_count < MIN_DEEP_SEQUENCE_NATIVE_WINDOWS:
            reason = "insufficient_mouse_windows" if cid == "mouse_resnet_gru" else "insufficient_combined_windows"
            return _deep_sequence_native_skipped(
                cid,
                reason=reason,
                feature_names=selected_features,
                training_sample_count=sequence_count,
                sequence_count=sequence_count,
                extra={"sequence_dataset": {"sequence_count": sequence_count, "skipped_sessions": list(payload.get("skipped_sessions") or [])}},
            )
        return _train_deep_sequence_native_candidate(
            cid,
            sequence_tensor=X,
            sequence_labels=y if cid == "combined_cnn_lstm" else np.zeros((int(X.shape[0]),), dtype=int),
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
            model_family=_deep_sequence_native_architecture(cid),
            extra={"builder_version": DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION, "artifact_mode": "failed", "privacy": {"stores_raw_text": False, "raw_text_fields_stored": [], "raw_text_stored": False}},
        )


def build_deep_sequence_candidate_artifacts(
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
    seed: int = 20260518,
) -> dict[str, Any]:
    """Build Phase 3 native report-only deep sequence artifacts.

    This completes the previously partial ``mouse_resnet_gru`` and
    ``combined_cnn_lstm`` candidates.  PyTorch is still optional, all outputs are
    non-authoritative, and raw typed text/key values are filtered from feature
    schemas before artifact serialization.
    """

    output_dir = Path(model_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    names = [str(name) for name in feature_names]
    byte_writer = atomic_write_bytes_fn or _atomic_write_bytes
    text_writer = atomic_write_text_fn or _atomic_write_text
    entries: dict[str, dict[str, Any]] = {}
    for candidate_id in DEEP_SEQUENCE_CANDIDATE_IDS:
        entry = _build_deep_sequence_native_candidate(
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
    manifest_feature_names = sorted({str(name) for entry in entries.values() for name in list(entry.get("feature_names") or []) if str(name or "").strip()})
    manifest = _candidate_artifact_manifest_payload(
        entries=entries,
        candidate_ids=DEEP_SEQUENCE_CANDIDATE_IDS,
        builder_version=DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        feature_names=manifest_feature_names,
        feature_schema_version=feature_schema_version,
        training_sample_count=int(sum(int(entry.get("training_sample_count") or 0) for entry in entries.values())),
        trained_on="mouse_owner_only_and_combined_owner_plus_trusted_intruder_sequence_windows",
    )
    manifest["artifact_serialization"] = "torch_state_dict"
    manifest["privacy"] = {"stores_raw_text": False, "raw_text_fields_stored": [], "raw_text_stored": False, "feature_source": "numeric_window_sequence_features"}
    manifest_path = output_dir / MANIFEST_FILENAME
    text_writer(str(manifest_path), json.dumps(manifest, indent=2, ensure_ascii=False))
    return {
        "schema_version": CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "builder_version": DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION,
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
