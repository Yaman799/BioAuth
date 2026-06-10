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
    KEYBOARD_DEEP_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    KEYBOARD_DEEP_CANDIDATE_ARTIFACT_FILENAMES,
    KEYBOARD_DEEP_CANDIDATE_IDS,
    MANIFEST_FILENAME,
    MIN_KEYBOARD_SEQUENCE_LENGTH,
    MIN_KEYBOARD_SEQUENCE_WINDOWS,
    MIN_TYPEFORMER_FREE_TEXT_LENGTH,
    NEAR_CONSTANT_STD_EPSILON,
)
from .deep_oneclass import _group_owner_sequence_samples, _torch_version
from .io import _atomic_write_bytes, _atomic_write_text, _write_torch_artifact
from .manifest import _candidate_artifact_manifest_payload, _manifest_entry, _trained_entry

def _keyboard_candidate_architecture(candidate_id: str) -> str:
    mapping = {
        "keyboard_bigru_cnn_attention": "keyboard_bigru_cnn_attention",
        "keyboard_type2branch": "keyboard_type2branch",
        "keyboard_typeformer": "keyboard_typeformer",
        "keyboard_siamese_triplet": "keyboard_siamese_triplet",
    }
    return mapping.get(str(candidate_id), str(candidate_id))


def _is_keyboard_typeformer_candidate(candidate_id: str) -> bool:
    return str(candidate_id) == "keyboard_typeformer"


def _is_keyboard_siamese_candidate(candidate_id: str) -> bool:
    return str(candidate_id) == "keyboard_siamese_triplet"


def _keyboard_selected_feature_names(samples: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> list[str]:
    try:
        from deep_sequence.tensorization import infer_modality_feature_names

        inferred = infer_modality_feature_names(samples, modality="keyboard")
        if inferred:
            return inferred
    except Exception:
        pass
    disallowed_exact = {"text", "raw_text", "typed_text", "plaintext", "characters", "char", "key", "key_name", "key_value"}
    disallowed_substrings = ("raw_text", "typed_text", "plaintext", "transcript")
    keyboard_tokens = (
        "key_hold", "hold", "flight", "typing", "digraph", "trigraph", "latency",
        "backspace", "burst", "keys_per_second", "kb_", "keyboard_", "dwell",
        "press_interval", "release_interval", "event_count",
    )
    selected: list[str] = []
    for raw_name in feature_names:
        name = str(raw_name or "").strip()
        lower = name.lower()
        if not name or lower in disallowed_exact or any(token in lower for token in disallowed_substrings):
            continue
        if any(token in lower for token in keyboard_tokens):
            selected.append(name)
    return selected


def _keyboard_skipped(
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
        "builder_version": KEYBOARD_DEEP_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        "dependency_name": "torch",
        "dependency_version": _torch_version(),
        "dependency_available": _dependency_available("torch"),
        "model_config": {"architecture": _keyboard_candidate_architecture(candidate_id)},
        "sequence_count": int(sequence_count),
        "artifact_mode": "skipped",
        "trained_on": "genuine_owner_keyboard_timing_sequence_windows_only",
        "artifact_serialization": "torch_state_dict",
        "privacy": {"stores_raw_text": False, "raw_text_fields_stored": []},
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
        model_family=model_family or _keyboard_candidate_architecture(candidate_id),
        extra=payload_extra,
    )


def _keyboard_model_for_candidate(candidate_id: str, *, feature_dim: int, model_config: Mapping[str, Any] | None = None) -> Any:
    from deep_sequence.models import (
        KeyboardBiGruCnnAttention,
        KeyboardSiameseTripletVerifier,
        KeyboardType2BranchInspired,
        KeyboardTypeFormerInspired,
    )

    config = dict(model_config or {})
    common: dict[str, Any] = {"feature_dim": int(feature_dim)}
    if candidate_id == "keyboard_bigru_cnn_attention":
        return KeyboardBiGruCnnAttention(
            **common,
            cnn_channels=int(config.get("cnn_channels") or 8),
            gru_hidden_size=int(config.get("gru_hidden_size") or 8),
            attention_hidden_size=int(config.get("attention_hidden_size") or 8),
            dropout=float(config.get("dropout") if config.get("dropout") is not None else 0.0),
        )
    if candidate_id == "keyboard_type2branch":
        return KeyboardType2BranchInspired(
            **common,
            cnn_channels=int(config.get("cnn_channels") or 8),
            gru_hidden_size=int(config.get("gru_hidden_size") or 8),
            embedding_dim=int(config.get("embedding_dim") or 4),
            dropout=float(config.get("dropout") if config.get("dropout") is not None else 0.0),
        )
    if candidate_id == "keyboard_typeformer":
        return KeyboardTypeFormerInspired(
            **common,
            model_dim=int(config.get("model_dim") or 8),
            num_heads=int(config.get("num_heads") or 2),
            num_layers=int(config.get("num_layers") or 1),
            embedding_dim=int(config.get("embedding_dim") or 4),
            feedforward_dim=int(config.get("feedforward_dim") or 16),
            dropout=float(config.get("dropout") if config.get("dropout") is not None else 0.0),
            min_free_text_length=int(config.get("min_free_text_length") or MIN_TYPEFORMER_FREE_TEXT_LENGTH),
        )
    if candidate_id == "keyboard_siamese_triplet":
        return KeyboardSiameseTripletVerifier(
            **common,
            hidden_size=int(config.get("hidden_size") or 8),
            embedding_dim=int(config.get("embedding_dim") or 4),
            dropout=float(config.get("dropout") if config.get("dropout") is not None else 0.0),
        )
    raise ValueError(f"unsupported_keyboard_deep_candidate:{candidate_id}")


def _default_keyboard_model_config(candidate_id: str, *, feature_dim: int, sequence_length: int) -> dict[str, Any]:
    architecture = _keyboard_candidate_architecture(candidate_id)
    config: dict[str, Any] = {
        "architecture": architecture,
        "candidate_id": str(candidate_id),
        "feature_dim": int(feature_dim),
        "sequence_length": int(sequence_length),
        "dropout": 0.0,
    }
    if candidate_id == "keyboard_bigru_cnn_attention":
        config.update({"cnn_channels": 8, "gru_hidden_size": 8, "attention_hidden_size": 8})
    elif candidate_id == "keyboard_typeformer":
        config.update({"model_dim": 8, "num_heads": 2, "num_layers": 1, "embedding_dim": 4, "feedforward_dim": 16, "min_free_text_length": MIN_TYPEFORMER_FREE_TEXT_LENGTH})
    elif candidate_id == "keyboard_siamese_triplet":
        config.update({"hidden_size": 8, "embedding_dim": 4})
    else:
        config.update({"cnn_channels": 8, "gru_hidden_size": 8, "embedding_dim": 4})
    return config


from .keyboard_deep_training import _train_keyboard_deep_candidate


def _build_keyboard_deep_candidate(
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
    selected_features = _keyboard_selected_feature_names(owner_samples_flat, feature_names)
    if not owner_groups:
        return _keyboard_skipped(cid, reason="insufficient_keyboard_windows", feature_names=selected_features or feature_names)
    if not selected_features:
        return _keyboard_skipped(cid, reason="insufficient_window_features", feature_names=[])
    target_sequence_length = max(MIN_KEYBOARD_SEQUENCE_LENGTH, int(sequence_length or MIN_KEYBOARD_SEQUENCE_LENGTH))
    if _is_keyboard_typeformer_candidate(cid):
        target_sequence_length = max(target_sequence_length, MIN_TYPEFORMER_FREE_TEXT_LENGTH)
    try:
        from deep_sequence.tensorization import build_sequence_dataset_from_session_samples

        payload = build_sequence_dataset_from_session_samples(
            owner_groups,
            selected_features,
            {session_id: 0 for session_id in owner_groups},
            sequence_length=target_sequence_length,
            stride=1,
        )
        X = payload.get("X")
        sequence_count = int(payload.get("sequence_count") or (X.shape[0] if isinstance(X, np.ndarray) and X.ndim == 3 else 0))
        if not isinstance(X, np.ndarray) or X.ndim != 3 or sequence_count < MIN_KEYBOARD_SEQUENCE_WINDOWS:
            reason = "insufficient_free_text_data" if _is_keyboard_typeformer_candidate(cid) else "insufficient_keyboard_windows"
            return _keyboard_skipped(
                cid,
                reason=reason,
                feature_names=selected_features,
                training_sample_count=sequence_count,
                sequence_count=sequence_count,
                extra={"sequence_dataset": {"sequence_count": sequence_count, "skipped_sessions": list(payload.get("skipped_sessions") or [])}},
            )
        pair_count = max(0, int(sequence_count) - 1) if _is_keyboard_siamese_candidate(cid) else 0
        return _train_keyboard_deep_candidate(
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
            pair_count=pair_count,
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
            model_family=_keyboard_candidate_architecture(cid),
            extra={"builder_version": KEYBOARD_DEEP_CANDIDATE_ARTIFACT_BUILDER_VERSION, "artifact_mode": "failed", "privacy": {"stores_raw_text": False, "raw_text_fields_stored": []}},
        )


def build_keyboard_deep_candidate_artifacts(
    *,
    model_dir: str | os.PathLike[str],
    samples: Sequence[Mapping[str, Any]] | None = None,
    labels: Sequence[Any] | None = None,
    sample_sources: Sequence[Any] | None = None,
    feature_names: Sequence[str],
    feature_schema_version: str | None = None,
    sequence_length: int = MIN_KEYBOARD_SEQUENCE_LENGTH,
    atomic_write_bytes_fn: AtomicBytesWriter | None = None,
    atomic_write_text_fn: AtomicTextWriter | None = None,
    max_epochs: int = DEFAULT_DEEP_MAX_EPOCHS,
    batch_size: int = DEFAULT_DEEP_BATCH_SIZE,
    learning_rate: float = DEFAULT_DEEP_LEARNING_RATE,
    seed: int = 20260514,
) -> dict[str, Any]:
    """Build report-only keyboard deep artifacts from privacy-safe timing features.

    No raw typed text or key values are written to the artifact. Missing PyTorch,
    short keyboard sequences, incomplete reference templates, or near-constant
    inputs produce skipped manifest rows rather than random-weight artifacts.
    """

    output_dir = Path(model_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    names = [str(name) for name in feature_names]
    byte_writer = atomic_write_bytes_fn or _atomic_write_bytes
    text_writer = atomic_write_text_fn or _atomic_write_text
    entries: dict[str, dict[str, Any]] = {}
    for candidate_id in KEYBOARD_DEEP_CANDIDATE_IDS:
        entry = _build_keyboard_deep_candidate(
            candidate_id,
            samples=list(samples or []),
            labels=list(labels or []),
            sample_sources=list(sample_sources or []),
            feature_names=names,
            feature_schema_version=feature_schema_version,
            sequence_length=int(sequence_length or MIN_KEYBOARD_SEQUENCE_LENGTH),
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
        candidate_ids=KEYBOARD_DEEP_CANDIDATE_IDS,
        builder_version=KEYBOARD_DEEP_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        feature_names=manifest_feature_names,
        feature_schema_version=feature_schema_version,
        training_sample_count=int(sum(int(entry.get("training_sample_count") or 0) for entry in entries.values())),
        trained_on="genuine_owner_keyboard_timing_sequence_windows_only",
    )
    manifest["artifact_serialization"] = "torch_state_dict"
    manifest["privacy"] = {"stores_raw_text": False, "raw_text_fields_stored": [], "feature_source": "keyboard_timing_rhythm_windows"}
    manifest_path = output_dir / MANIFEST_FILENAME
    text_writer(str(manifest_path), json.dumps(manifest, indent=2, ensure_ascii=False))
    return {
        "schema_version": CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "builder_version": KEYBOARD_DEEP_CANDIDATE_ARTIFACT_BUILDER_VERSION,
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
