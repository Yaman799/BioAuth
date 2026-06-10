from __future__ import annotations

import os
import io
import pickle
from pathlib import Path
from typing import Any

from .constants import (
    AtomicBytesWriter,
    CLASSICAL_CANDIDATE_ARTIFACT_FILENAMES,
    DEEP_ONECLASS_CANDIDATE_ARTIFACT_FILENAMES,
    DEEP_SEQUENCE_CANDIDATE_ARTIFACT_FILENAMES,
    KEYBOARD_DEEP_CANDIDATE_ARTIFACT_FILENAMES,
    OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_FILENAMES,
)

def _atomic_write_bytes(path: str, data: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)


def _atomic_write_text(path: str, data: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, target)


def _artifact_digest(path: Path) -> str:
    import hashlib

    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return ""


def _artifact_filename(candidate_id: str) -> str:
    return (
        CLASSICAL_CANDIDATE_ARTIFACT_FILENAMES.get(candidate_id)
        or OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_FILENAMES.get(candidate_id)
        or DEEP_ONECLASS_CANDIDATE_ARTIFACT_FILENAMES.get(candidate_id)
        or KEYBOARD_DEEP_CANDIDATE_ARTIFACT_FILENAMES.get(candidate_id)
        or DEEP_SEQUENCE_CANDIDATE_ARTIFACT_FILENAMES.get(candidate_id)
        or f"{candidate_id}.pkl"
    )


def _write_pickle_artifact(
    *,
    model_dir: Path,
    candidate_id: str,
    artifact: Any,
    writer: AtomicBytesWriter,
) -> tuple[str, str]:
    filename = _artifact_filename(candidate_id)
    path = model_dir / filename
    writer(str(path), pickle.dumps(artifact, protocol=pickle.HIGHEST_PROTOCOL))
    return filename, _artifact_digest(path)


def _write_supervised_pickle_artifact(
    *,
    model_dir: Path,
    candidate_id: str,
    artifact: Any,
    writer: AtomicBytesWriter,
) -> tuple[str, str]:
    filename = OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]
    path = model_dir / filename
    writer(str(path), pickle.dumps(artifact, protocol=pickle.HIGHEST_PROTOCOL))
    return filename, _artifact_digest(path)


def _write_torch_artifact(
    *,
    model_dir: Path,
    candidate_id: str,
    artifact: Mapping[str, Any],
    writer: AtomicBytesWriter,
) -> tuple[str, str]:
    import torch

    filename = _artifact_filename(candidate_id)
    buffer = io.BytesIO()
    torch.save(dict(artifact), buffer)
    path = model_dir / filename
    writer(str(path), buffer.getvalue())
    return filename, _artifact_digest(path)
