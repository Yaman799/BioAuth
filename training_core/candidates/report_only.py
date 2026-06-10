from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from .artifacts import OptionalSupervisedDependencySpec
from .classical import _build_gmm, _build_lof, _build_nn_mahalanobis, _build_one_class_svm, _build_scaled_manhattan
from .common import _matrix
from .constants import (
    ALL_REPORT_ONLY_CANDIDATE_IDS,
    AtomicBytesWriter,
    AtomicTextWriter,
    CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
    CLASSICAL_CANDIDATE_IDS,
    COMBINED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    DEEP_ONECLASS_CANDIDATE_IDS,
    DEEP_SEQUENCE_CANDIDATE_IDS,
    DEFAULT_DEEP_BATCH_SIZE,
    DEFAULT_DEEP_LEARNING_RATE,
    DEFAULT_DEEP_MAX_EPOCHS,
    KEYBOARD_DEEP_CANDIDATE_IDS,
    MANIFEST_FILENAME,
    MIN_DEEP_SEQUENCE_LENGTH,
    MIN_KEYBOARD_SEQUENCE_LENGTH,
    OPTIONAL_SUPERVISED_CANDIDATE_IDS,
)
from .deep_oneclass import _build_deep_oneclass_candidate
from .deep_sequence import _build_deep_sequence_native_candidate
from .io import _atomic_write_bytes, _atomic_write_text
from .keyboard_deep import _build_keyboard_deep_candidate
from .manifest import _candidate_artifact_manifest_payload, _forced_candidate_artifact_entry
from .supervised import _build_optional_supervised_candidate

def build_report_only_candidate_artifacts(
    *,
    model_dir: str | os.PathLike[str],
    X_pos: Sequence[Sequence[float]] | np.ndarray,
    X_neg: Sequence[Sequence[float]] | np.ndarray,
    feature_names: Sequence[str],
    feature_schema_version: str | None = None,
    atomic_write_bytes_fn: AtomicBytesWriter | None = None,
    atomic_write_text_fn: AtomicTextWriter | None = None,
    dependency_resolver: Callable[[str], OptionalSupervisedDependencySpec] | None = None,
    supervised_estimator_params: Mapping[str, Mapping[str, Any]] | None = None,
    samples: Sequence[Mapping[str, Any]] | None = None,
    labels: Sequence[Any] | None = None,
    sample_sources: Sequence[Any] | None = None,
    sequence_length: int = MIN_DEEP_SEQUENCE_LENGTH,
    deep_max_epochs: int = DEFAULT_DEEP_MAX_EPOCHS,
    include_deep_candidates: bool = True,
) -> dict[str, Any]:
    """Build the combined report-only candidate artifact manifest.

    This is the training-pipeline entry point used by P2B3. It preserves the
    P2B1 classical artifacts, P2B2 optional supervised rows, and adds deep
    one-class/mouse artifact rows without
    changing runtime authority, lock behavior, Face Confirmation, production
    approval, or promotion state.
    """

    output_dir = Path(model_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    X_owner = _matrix(X_pos)
    X_intruder = _matrix(X_neg)
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
        entry = builder(X_owner, names, feature_schema_version, output_dir, byte_writer)
        entries[str(entry["candidate_id"])] = entry

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
            estimator_params=supervised_estimator_params,
        )
        entries[str(entry["candidate_id"])] = entry

    if bool(include_deep_candidates):
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
                max_epochs=int(deep_max_epochs),
                batch_size=DEFAULT_DEEP_BATCH_SIZE,
                learning_rate=DEFAULT_DEEP_LEARNING_RATE,
                seed=20260512,
            )
            entries[str(entry["candidate_id"])] = entry

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
                max_epochs=int(deep_max_epochs),
                batch_size=DEFAULT_DEEP_BATCH_SIZE,
                learning_rate=DEFAULT_DEEP_LEARNING_RATE,
                seed=20260514,
            )
            entries[str(entry["candidate_id"])] = entry

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
                max_epochs=int(deep_max_epochs),
                batch_size=DEFAULT_DEEP_BATCH_SIZE,
                learning_rate=DEFAULT_DEEP_LEARNING_RATE,
                seed=20260518,
            )
            entries[str(entry["candidate_id"])] = entry
    else:
        for candidate_id in (*DEEP_ONECLASS_CANDIDATE_IDS, *KEYBOARD_DEEP_CANDIDATE_IDS, *DEEP_SEQUENCE_CANDIDATE_IDS):
            entry = _forced_candidate_artifact_entry(
                candidate_id,
                status="skipped",
                reason="deep_candidate_artifacts_disabled",
                feature_names=[],
                extra={"deep_candidate_artifacts_enabled": False},
            )
            entries[str(entry["candidate_id"])] = entry

    candidate_ids = list(ALL_REPORT_ONLY_CANDIDATE_IDS)
    manifest = _candidate_artifact_manifest_payload(
        entries=entries,
        candidate_ids=candidate_ids,
        builder_version=COMBINED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        feature_names=names,
        feature_schema_version=feature_schema_version,
        training_sample_count=int(X_owner.shape[0] + X_intruder.shape[0]),
        trained_on="classical_owner_positive_only_supervised_owner_plus_trusted_intruder_deep_owner_sequence_keyboard_timing_and_phase3_native_sequence_windows",
    )
    manifest_path = output_dir / MANIFEST_FILENAME
    text_writer(str(manifest_path), json.dumps(manifest, indent=2, ensure_ascii=False))
    return {
        "schema_version": CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "builder_version": COMBINED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
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


def build_report_only_candidate_artifacts_unavailable(
    *,
    model_dir: str | os.PathLike[str],
    reason: str,
    status: str = "skipped",
    feature_names: Sequence[str] | None = None,
    feature_schema_version: str | None = None,
    atomic_write_text_fn: AtomicTextWriter | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a complete report-only manifest when integration cannot run builders.

    This keeps Train Profile safe: a candidate integration outage never fabricates
    artifacts and never grants runtime authority.  In strict mode callers may still
    raise before using this helper.
    """

    output_dir = Path(model_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    names = [str(name) for name in list(feature_names or []) if str(name or "").strip()]
    text_writer = atomic_write_text_fn or _atomic_write_text
    safe_status = str(status or "skipped").strip().lower()
    if safe_status not in {"skipped", "failed"}:
        safe_status = "skipped"
    entries = {
        candidate_id: _forced_candidate_artifact_entry(
            candidate_id,
            status=safe_status,
            reason=str(reason or "candidate_artifact_unavailable"),
            feature_names=names if candidate_id in CLASSICAL_CANDIDATE_IDS or candidate_id in OPTIONAL_SUPERVISED_CANDIDATE_IDS else [],
            extra=extra,
        )
        for candidate_id in ALL_REPORT_ONLY_CANDIDATE_IDS
    }
    manifest = _candidate_artifact_manifest_payload(
        entries=entries,
        candidate_ids=ALL_REPORT_ONLY_CANDIDATE_IDS,
        builder_version=COMBINED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
        feature_names=names,
        feature_schema_version=feature_schema_version,
        training_sample_count=0,
        trained_on="not_trained",
    )
    manifest["integration_status"] = safe_status
    manifest["integration_reason"] = str(reason or "candidate_artifact_unavailable")
    manifest_path = output_dir / MANIFEST_FILENAME
    text_writer(str(manifest_path), json.dumps(manifest, indent=2, ensure_ascii=False))
    return {
        "schema_version": CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "builder_version": COMBINED_CANDIDATE_ARTIFACT_BUILDER_VERSION,
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


def summarize_candidate_artifact_build(build: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return UI/API-friendly candidate artifact counts and artifact mapping."""

    payload = build if isinstance(build, Mapping) else {}
    entries = payload.get("candidate_artifacts") or (payload.get("manifest") or {}).get("candidates") or {}
    clean_entries = {str(key): dict(value) for key, value in dict(entries or {}).items() if isinstance(value, Mapping)}
    built = {cid: str(entry.get("artifact_path") or "") for cid, entry in clean_entries.items() if str(entry.get("status") or "") == "trained" and str(entry.get("artifact_path") or "").strip()}
    skipped = {cid: str(entry.get("reason") or "skipped") for cid, entry in clean_entries.items() if str(entry.get("status") or "") == "skipped"}
    failed = {cid: str(entry.get("reason") or "failed") for cid, entry in clean_entries.items() if str(entry.get("status") or "") == "failed"}
    status_counts = dict(payload.get("status_counts") or (payload.get("manifest") or {}).get("status_counts") or {})
    for key, value in {"trained": len(built), "skipped": len(skipped), "failed": len(failed)}.items():
        try:
            status_counts[key] = int(status_counts.get(key, value))
        except (TypeError, ValueError):
            status_counts[key] = int(value)
    return {
        "candidate_artifacts_built": sorted(built),
        "candidate_artifact_paths": built,
        "candidate_artifacts_skipped": skipped,
        "candidate_artifacts_failed": failed,
        "status_counts": status_counts,
        "artifact_manifest": str(payload.get("manifest_path") or MANIFEST_FILENAME),
        "report_only": True,
        "can_lock": False,
        "can_lock_alone": False,
        "can_influence_device": False,
        "runtime_authoritative": False,
        "trigger_face_confirmation": False,
    }