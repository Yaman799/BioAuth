"""Artifact integrity helpers for model bundles."""

from __future__ import annotations

import json
import io
import os
import pickle
from pathlib import Path
from typing import Any, Dict, Optional

from security import (
    CLASSIFIER_INTEGRITY_LABEL,
    METADATA_INTEGRITY_LABEL,
    MODEL_INTEGRITY_LABEL,
    _calculate_bytes_hmac,
    _encode_integrity_value,
    _read_saved_integrity,
    atomic_write_bytes,
    atomic_write_text,
    remove_classifier_hash,
    remove_user_classifier_hash,
    verify_classifier_hash,
    verify_metadata_hash,
    verify_model_hash,
    verify_user_classifier_hash,
)


class SecurityError(Exception):
    """Raised when saved model integrity validation fails."""



def _security_runtime():
    import security as active_security

    return active_security


DEEP_SEQUENCE_MODEL_INTEGRITY_LABEL = b"bioauth.deep_sequence.integrity.v1"

def _sequence_model_hash_path(artifact_path: str) -> str:
    return os.path.join(os.path.dirname(artifact_path), "sequence_model.hash")

def save_sequence_model_hash(artifact_path: str, raw_bytes: bytes) -> None:
    digest = _calculate_bytes_hmac(raw_bytes, DEEP_SEQUENCE_MODEL_INTEGRITY_LABEL)
    atomic_write_text(_sequence_model_hash_path(artifact_path), _encode_integrity_value(digest))

def verify_sequence_model_hash(artifact_path: str, raw_bytes: bytes) -> bool:
    sidecar = _sequence_model_hash_path(artifact_path)
    if not os.path.exists(sidecar):
        return False
    try:
        scheme, saved_digest = _read_saved_integrity(sidecar)
    except OSError:
        return False
    if scheme != 'hmac-sha256':
        return False
    current = _calculate_bytes_hmac(raw_bytes, DEEP_SEQUENCE_MODEL_INTEGRITY_LABEL)
    return current == saved_digest

def save_sequence_model_artifact(artifact_path: str, payload: Dict[str, Any]) -> None:
    try:
        import torch
    except Exception as exc:
        raise SecurityError('⚠️ sequence_model backend unavailable') from exc
    buffer = io.BytesIO()
    torch.save(payload, buffer)
    raw_bytes = buffer.getvalue()
    atomic_write_bytes(artifact_path, raw_bytes)
    save_sequence_model_hash(artifact_path, raw_bytes)

def load_sequence_model_artifact(artifact_path: str) -> Dict[str, Any]:
    if not os.path.exists(artifact_path):
        raise SecurityError('⚠️ sequence_model missing')
    try:
        import torch
    except Exception as exc:
        raise SecurityError('⚠️ sequence_model backend unavailable') from exc
    raw_bytes = Path(artifact_path).read_bytes()
    if not verify_sequence_model_hash(artifact_path, raw_bytes):
        raise SecurityError('⚠️ sequence_model tampered')
    try:
        return torch.load(io.BytesIO(raw_bytes), map_location='cpu')
    except Exception as exc:
        raise SecurityError('⚠️ sequence_model artifact invalid') from exc


def _current_model_file() -> str:
    from model_metadata import MODEL_FILE

    return MODEL_FILE


def _current_classifier_file() -> str:
    from model_metadata import CLASSIFIER_FILE

    return CLASSIFIER_FILE


def _current_metadata_file() -> str:
    from model_metadata import METADATA_FILE

    return METADATA_FILE


def _temp_integrity_sidecar_path(path: str) -> str:
    return f"{path}.integrity.tmp"


def _artifact_integrity_label(path: str, artifact_type: str) -> bytes:
    if artifact_type == "model":
        return MODEL_INTEGRITY_LABEL
    if artifact_type == "classifier":
        return CLASSIFIER_INTEGRITY_LABEL
    if artifact_type == "metadata":
        return METADATA_INTEGRITY_LABEL
    raise ValueError(f"Unsupported artifact type: {artifact_type}")


def _write_temp_integrity_sidecar(path: str, raw_bytes: bytes, artifact_type: str) -> str:
    sidecar = _temp_integrity_sidecar_path(path)
    digest = _calculate_bytes_hmac(raw_bytes, _artifact_integrity_label(path, artifact_type))
    atomic_write_text(sidecar, _encode_integrity_value(digest))
    return sidecar


def _verify_temp_copy_integrity(path: str, artifact_type: str) -> None:
    sidecar = _temp_integrity_sidecar_path(path)
    raw_bytes = Path(path).read_bytes()
    scheme, saved_digest = _read_saved_integrity(sidecar)
    if scheme != "hmac-sha256":
        raise SecurityError(f"⚠️ {artifact_type} temp integrity scheme invalid")
    current = _calculate_bytes_hmac(raw_bytes, _artifact_integrity_label(path, artifact_type))
    if current != saved_digest:
        raise SecurityError(f"⚠️ {artifact_type} temp copy integrity failed")



def _is_global_classifier_path(classifier_path: str) -> bool:
    return os.path.normcase(os.path.abspath(classifier_path)) == os.path.normcase(os.path.abspath(_current_classifier_file()))


def save_classifier_sidecar(classifier_path: str) -> None:
    from security import save_classifier_hash, save_user_classifier_hash

    if _is_global_classifier_path(classifier_path):
        save_classifier_hash(classifier_path)
    else:
        save_user_classifier_hash(classifier_path)


def remove_classifier_sidecar(classifier_path: str) -> None:
    if _is_global_classifier_path(classifier_path):
        remove_classifier_hash()
    else:
        remove_user_classifier_hash(classifier_path)


def load_model(model_file: Optional[str] = None) -> Optional[Any]:
    model_file = model_file or _current_model_file()
    if not os.path.exists(model_file):
        return None
    raw_bytes = Path(model_file).read_bytes()
    # Tests and dev tooling reload ``security`` after monkeypatching runtime paths.
    # Resolve the verifier at call time so integrity checks use the same current
    # HMAC key/path configuration that wrote the sidecar, not a stale imported
    # function captured during module collection.
    if not _security_runtime().verify_model_hash(model_file, raw_bytes=raw_bytes):
        raise SecurityError("⚠️ Model tampered")
    return pickle.loads(raw_bytes)


def load_classifier(classifier_file: Optional[str] = None):
    classifier_file = classifier_file or _current_classifier_file()
    if not os.path.exists(classifier_file):
        return None
    raw_bytes = Path(classifier_file).read_bytes()
    security_runtime = _security_runtime()
    if _is_global_classifier_path(classifier_file):
        if not security_runtime.verify_classifier_hash(classifier_file, raw_bytes=raw_bytes):
            raise SecurityError("⚠️ Classifier tampered")
    else:
        if not security_runtime.verify_user_classifier_hash(classifier_file, raw_bytes=raw_bytes):
            raise SecurityError("⚠️ Classifier tampered")
    return pickle.loads(raw_bytes)


def load_metadata(metadata_file: Optional[str] = None) -> Optional[Dict[str, Any]]:
    metadata_file = metadata_file or _current_metadata_file()
    if not os.path.exists(metadata_file):
        return None
    raw_bytes = Path(metadata_file).read_bytes()
    if not _security_runtime().verify_metadata_hash(metadata_file, raw_bytes=raw_bytes):
        raise SecurityError("⚠️ Metadata tampered")
    return json.loads(raw_bytes.decode("utf-8"))


def _validate_artifact_payload(raw_bytes: bytes, artifact_type: str) -> None:
    try:
        if artifact_type in {"model", "classifier"}:
            pickle.loads(raw_bytes)
        elif artifact_type == "metadata":
            payload = json.loads(raw_bytes.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Metadata payload must decode to an object")
        else:
            raise ValueError(f"Unsupported artifact type: {artifact_type}")
    except Exception as exc:
        raise SecurityError(f"⚠️ {artifact_type} artifact invalid") from exc


def verify_tmp_copy(path: str, artifact_type: str) -> None:
    path_obj = Path(path)
    raw_bytes = path_obj.read_bytes()
    security_runtime = _security_runtime()
    if artifact_type == "model":
        ok = security_runtime.verify_model_hash(path, raw_bytes=raw_bytes)
    elif artifact_type == "classifier":
        if _is_global_classifier_path(path):
            ok = security_runtime.verify_classifier_hash(path, raw_bytes=raw_bytes)
        else:
            ok = security_runtime.verify_user_classifier_hash(path, raw_bytes=raw_bytes)
    elif artifact_type == "metadata":
        ok = security_runtime.verify_metadata_hash(path, raw_bytes=raw_bytes)
    else:
        raise ValueError(f"Unsupported artifact type: {artifact_type}")
    if not ok:
        raise SecurityError(f"⚠️ {artifact_type} artifact tampered")


def copy_verified_temp(src: str, dst_tmp: str, artifact_type: str) -> str:
    raw_bytes = Path(src).read_bytes()
    verify_tmp_copy(src, artifact_type)
    _validate_artifact_payload(raw_bytes, artifact_type)

    sidecar = _temp_integrity_sidecar_path(dst_tmp)
    try:
        atomic_write_bytes(dst_tmp, raw_bytes)
        copied_bytes = Path(dst_tmp).read_bytes()
        if copied_bytes != raw_bytes:
            raise SecurityError(f"⚠️ {artifact_type} temp copy mismatch")
        _validate_artifact_payload(copied_bytes, artifact_type)
        _write_temp_integrity_sidecar(dst_tmp, copied_bytes, artifact_type)
        _verify_temp_copy_integrity(dst_tmp, artifact_type)
        return dst_tmp
    finally:
        try:
            if os.path.exists(sidecar):
                os.remove(sidecar)
        except OSError:
            pass
