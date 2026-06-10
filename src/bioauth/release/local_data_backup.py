"""Encrypted local backup/restore helpers for BioAuth user data.

The helpers in this module never serialize decrypted behavioral rows, passwords,
face templates, or model payloads into plaintext backup files.  They package the
selected on-disk files as bytes inside a compressed archive, then store that
archive inside the existing secure JSON envelope v2 (Fernet + HMAC).  The outer
backup file therefore exposes only envelope metadata and an encrypted payload.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Tuple

import paths
from security import atomic_write_bytes
from secure_storage import (
    ALGORITHM as SECURE_ENVELOPE_ALGORITHM,
    STORAGE_FORMAT_VERSION,
    SecureEnvelopeIntegrityError,
    load_enveloped_json,
    write_enveloped_json,
)

BACKUP_FORMAT = "bioauth-local-backup-v1"
BACKUP_SCHEMA_VERSION = 1
DELETE_ALL_CONFIRMATION = "DELETE LOCAL BIOAUTH DATA"
RESET_PROFILE_CONFIRMATION = "RESET PROFILE"


class LocalDataBackupSafetyError(Exception):
    """Raised when backup/restore is blocked before touching local data."""


def _safe_error_result(reason: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "reason": reason, "message": message, "user_safe_reason": message}


_EXCLUDED_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "dev_monitor_logs",
    "logs",
    "tmp",
    "temp",
}
_EXCLUDED_FILE_SUFFIXES = {
    ".log",
    ".tmp",
    ".bak",
    ".old",
    ".pyc",
    ".pyo",
}
_EXCLUDED_FILE_NAMES = {
    "secret.key",
    "secret.key.dpapi",
    "model.hash.tmp",
    "classifier.hash.tmp",
    "metadata.hash.tmp",
}
_EXCLUDED_TOP_LEVEL_UNDER_DATA = {
    "live_session",  # runtime-only capture scratch/state; sessions are backed up separately.
    "control",       # stop/control files are process/runtime state, not durable profile data.
}


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relpath(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_relative_safe(rel_path: str) -> bool:
    rel_path = str(rel_path or "")
    if not rel_path or rel_path.startswith("/") or rel_path.startswith("\\") or "\\" in rel_path:
        return False
    parts = PurePosixPath(rel_path).parts
    if not parts or PurePosixPath(rel_path).is_absolute():
        return False
    return all(part not in {"", ".", ".."} and ":" not in part for part in parts)


def _excluded_file(path: Path, rel: str, *, root_label: str) -> bool:
    name = path.name
    if name in _EXCLUDED_FILE_NAMES:
        return True
    if path.suffix.lower() in _EXCLUDED_FILE_SUFFIXES:
        return True
    parts = Path(rel).parts
    if any(part in _EXCLUDED_DIR_NAMES for part in parts):
        return True
    if root_label == "data" and parts and parts[0] in _EXCLUDED_TOP_LEVEL_UNDER_DATA:
        return True
    return False


def _assert_no_symlink_component(path: Path, root: Path, *, action: str) -> None:
    """Reject symbolic links without exposing local paths in user-facing errors."""

    try:
        root_abs = root.absolute()
        current = root_abs
        if current.is_symlink():
            raise LocalDataBackupSafetyError(f"{action} refused because local data contains a symbolic link.")
        relative_parts = path.absolute().relative_to(root_abs).parts
    except ValueError as exc:
        raise LocalDataBackupSafetyError(f"{action} refused because a local data path is outside the allowed data roots.") from exc

    for part in relative_parts:
        current = current / part
        if current.is_symlink():
            raise LocalDataBackupSafetyError(f"{action} refused because local data contains a symbolic link.")


def _iter_root_files(root: Path, root_label: str) -> Iterable[Tuple[str, Path]]:
    if not root.exists():
        return []
    root = root.absolute()
    if root.is_symlink():
        raise LocalDataBackupSafetyError("Backup refused because local data contains a symbolic link.")
    root_resolved = root.resolve(strict=True)
    result: List[Tuple[str, Path]] = []
    for file_path in sorted(root.rglob("*")):
        _assert_no_symlink_component(file_path, root, action="Backup")
        if not file_path.is_file():
            continue
        file_resolved = file_path.resolve(strict=True)
        try:
            if os.path.commonpath([str(file_resolved), str(root_resolved)]) != str(root_resolved):
                raise LocalDataBackupSafetyError("Backup refused because a local data path is outside the allowed data roots.")
        except ValueError as exc:
            raise LocalDataBackupSafetyError("Backup refused because a local data path is outside the allowed data roots.") from exc
        rel_under_root = file_path.relative_to(root).as_posix()
        if _excluded_file(file_path, rel_under_root, root_label=root_label):
            continue
        backup_rel = f"{root_label}/{rel_under_root}"
        if _is_relative_safe(backup_rel):
            result.append((backup_rel, file_path))
    return result


def _collect_backup_files() -> List[Tuple[str, Path]]:
    files: List[Tuple[str, Path]] = []
    files.extend(_iter_root_files(Path(paths.data_dir()), "data"))
    files.extend(_iter_root_files(Path(paths.models_dir()), "models"))
    return sorted(files, key=lambda item: item[0])


def _build_archive(files: List[Tuple[str, Path]]) -> Tuple[bytes, List[Dict[str, Any]]]:
    manifest: List[Dict[str, Any]] = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel, file_path in files:
            data = file_path.read_bytes()
            manifest.append({"path": rel, "size": len(data), "sha256": _sha256_bytes(data)})
            info = zipfile.ZipInfo(rel)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue(), manifest


def export_encrypted_backup(destination_path: str) -> Dict[str, Any]:
    """Export selected BioAuth local data to an encrypted envelope backup file."""
    dest = Path(str(destination_path or "")).expanduser()
    if not str(dest).strip():
        return _safe_error_result("backup_path_required", "Choose where to save the encrypted backup.")
    try:
        files = _collect_backup_files()
        archive_bytes, manifest = _build_archive(files)
    except LocalDataBackupSafetyError as exc:
        return _safe_error_result("backup_symlink_refused", str(exc))
    except Exception:
        return _safe_error_result("backup_export_failed", "Encrypted backup could not be prepared safely.")
    payload = {
        "backup_format": BACKUP_FORMAT,
        "backup_schema_version": BACKUP_SCHEMA_VERSION,
        "created_at_utc": _utc_timestamp(),
        "source_app": "BioAuth",
        "secure_storage_format_version": STORAGE_FORMAT_VERSION,
        "secure_storage_algorithm": SECURE_ENVELOPE_ALGORITHM,
        "archive_encoding": "base64",
        "archive_compression": "zip-deflated",
        "archive_sha256": _sha256_bytes(archive_bytes),
        "file_count": len(manifest),
        "files": manifest,
        "archive_b64": base64.b64encode(archive_bytes).decode("ascii"),
    }
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_enveloped_json(str(dest), payload)
    except Exception:
        return _safe_error_result("backup_export_failed", "Encrypted backup could not be written.")
    return {
        "ok": True,
        "path": str(dest),
        "file_count": len(manifest),
        "archive_sha256": payload["archive_sha256"],
        "backup_format": BACKUP_FORMAT,
        "encrypted": True,
        "integrity_protected": True,
    }


def _load_backup_payload(source_path: str) -> Dict[str, Any]:
    src = Path(str(source_path or "")).expanduser()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError("backup file not found")
    payload, state = load_enveloped_json(str(src), default={}, rewrite_migrated=False)
    if state != "envelope_v2":
        raise SecureEnvelopeIntegrityError("backup is not an encrypted envelope v2 file")
    if payload.get("backup_format") != BACKUP_FORMAT:
        raise SecureEnvelopeIntegrityError("unsupported backup format")
    if int(payload.get("backup_schema_version") or 0) != BACKUP_SCHEMA_VERSION:
        raise SecureEnvelopeIntegrityError("unsupported backup schema version")
    if payload.get("archive_encoding") != "base64":
        raise SecureEnvelopeIntegrityError("unsupported backup archive encoding")
    return payload


def inspect_encrypted_backup(source_path: str) -> Dict[str, Any]:
    """Return safe metadata about a backup without restoring it."""
    try:
        payload = _load_backup_payload(source_path)
        return {
            "ok": True,
            "backup_format": payload.get("backup_format"),
            "backup_schema_version": payload.get("backup_schema_version"),
            "created_at_utc": payload.get("created_at_utc", ""),
            "file_count": int(payload.get("file_count") or 0),
            "archive_sha256": str(payload.get("archive_sha256") or ""),
            "encrypted": True,
            "integrity_protected": True,
        }
    except Exception:
        return _safe_error_result("backup_validation_failed", "This backup could not be verified.")


def _zipinfo_is_symlink(info: zipfile.ZipInfo) -> bool:
    file_type = (int(info.external_attr or 0) >> 16) & 0o170000
    return file_type == 0o120000


def _restore_root_for_label(root_label: str) -> Path:
    if root_label == "data":
        return Path(paths.data_dir()).absolute()
    if root_label == "models":
        return Path(paths.models_dir()).absolute()
    raise SecureEnvelopeIntegrityError("backup entry target is unsupported")


def _restore_target_for_relative(root_label: str, rel_under_root: str) -> Path:
    if not _is_relative_safe(rel_under_root):
        raise SecureEnvelopeIntegrityError("backup entry target is unsafe")
    root = _restore_root_for_label(root_label)
    parts = PurePosixPath(rel_under_root).parts
    return root.joinpath(*parts)


def _assert_restore_target_safe(target: Path, root_label: str) -> None:
    root = _restore_root_for_label(root_label)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise LocalDataBackupSafetyError("Restore refused because the local data root is a symbolic link.")
    _assert_no_symlink_component(target, root, action="Restore")
    root_resolved = root.resolve(strict=True)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    _assert_no_symlink_component(parent, root, action="Restore")
    try:
        parent_resolved = parent.resolve(strict=True)
        if os.path.commonpath([str(parent_resolved), str(root_resolved)]) != str(root_resolved):
            raise LocalDataBackupSafetyError("Restore refused because a target path is outside the allowed data roots.")
    except ValueError as exc:
        raise LocalDataBackupSafetyError("Restore refused because a target path is outside the allowed data roots.") from exc
    if target.is_symlink():
        raise LocalDataBackupSafetyError("Restore refused because a target file is a symbolic link.")


def _validated_archive_entries(payload: Mapping[str, Any]) -> List[Tuple[str, bytes, Dict[str, Any]]]:
    try:
        archive_bytes = base64.b64decode(str(payload.get("archive_b64") or ""), validate=True)
    except Exception as exc:
        raise SecureEnvelopeIntegrityError("backup archive is not valid base64") from exc
    expected_archive_hash = str(payload.get("archive_sha256") or "")
    if not expected_archive_hash or _sha256_bytes(archive_bytes) != expected_archive_hash:
        raise SecureEnvelopeIntegrityError("backup archive digest mismatch")
    manifest = payload.get("files")
    if not isinstance(manifest, list):
        raise SecureEnvelopeIntegrityError("backup manifest is missing")
    manifest_by_path: Dict[str, Dict[str, Any]] = {}
    for item in manifest:
        if not isinstance(item, dict):
            raise SecureEnvelopeIntegrityError("backup manifest entry is invalid")
        rel = str(item.get("path") or "")
        if not _is_relative_safe(rel) or not (rel.startswith("data/") or rel.startswith("models/")):
            raise SecureEnvelopeIntegrityError("backup manifest contains unsafe path")
        root_label, rel_under_root = rel.split("/", 1)
        if _excluded_file(Path(rel_under_root), rel_under_root, root_label=root_label):
            raise SecureEnvelopeIntegrityError("backup manifest contains excluded runtime or secret path")
        if rel in manifest_by_path:
            raise SecureEnvelopeIntegrityError("backup manifest contains duplicate path")
        manifest_by_path[rel] = item

    entries: List[Tuple[str, bytes, Dict[str, Any]]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if sorted(names) != sorted(manifest_by_path):
                raise SecureEnvelopeIntegrityError("backup archive entries do not match manifest")
            for info in infos:
                rel = info.filename
                if _zipinfo_is_symlink(info):
                    raise SecureEnvelopeIntegrityError("backup archive contains unsupported link entry")
                if info.is_dir() or not _is_relative_safe(rel) or rel not in manifest_by_path:
                    raise SecureEnvelopeIntegrityError("backup archive contains unsafe path")
                data = archive.read(info)
                meta = manifest_by_path[rel]
                if int(meta.get("size") or -1) != len(data):
                    raise SecureEnvelopeIntegrityError("backup entry size mismatch")
                if str(meta.get("sha256") or "") != _sha256_bytes(data):
                    raise SecureEnvelopeIntegrityError("backup entry digest mismatch")
                entries.append((rel, data, meta))
    except SecureEnvelopeIntegrityError:
        raise
    except Exception as exc:
        raise SecureEnvelopeIntegrityError("backup archive could not be read") from exc
    return entries


def _destination_for_backup_rel(rel: str) -> Path:
    if not _is_relative_safe(rel):
        raise SecureEnvelopeIntegrityError("backup entry target is unsafe")
    if rel.startswith("data/"):
        return _restore_target_for_relative("data", rel[len("data/"):])
    if rel.startswith("models/"):
        return _restore_target_for_relative("models", rel[len("models/"):])
    raise SecureEnvelopeIntegrityError("backup entry target is unsupported")


def _root_label_for_backup_rel(rel: str) -> str:
    if rel.startswith("data/"):
        return "data"
    if rel.startswith("models/"):
        return "models"
    raise SecureEnvelopeIntegrityError("backup entry target is unsupported")


def restore_encrypted_backup(source_path: str) -> Dict[str, Any]:
    """Validate and restore an encrypted BioAuth local backup using atomic file writes."""
    try:
        payload = _load_backup_payload(source_path)
        entries = _validated_archive_entries(payload)
    except Exception:
        return _safe_error_result("backup_validation_failed", "This backup could not be verified.")

    backups: List[Tuple[Path, bytes | None]] = []
    written: List[Path] = []
    try:
        for rel, data, _meta in entries:
            target = _destination_for_backup_rel(rel)
            root_label = _root_label_for_backup_rel(rel)
            _assert_restore_target_safe(target, root_label)
            target.parent.mkdir(parents=True, exist_ok=True)
            backups.append((target, target.read_bytes() if target.exists() else None))
            atomic_write_bytes(str(target), data)
            written.append(target)
    except LocalDataBackupSafetyError as exc:
        for target, previous in reversed(backups):
            try:
                if previous is None:
                    if target.exists() and not target.is_symlink():
                        target.unlink()
                else:
                    atomic_write_bytes(str(target), previous)
            except Exception:
                pass
        return _safe_error_result("restore_target_unsafe", str(exc))
    except Exception:
        for target, previous in reversed(backups):
            try:
                if previous is None:
                    if target.exists() and not target.is_symlink():
                        target.unlink()
                else:
                    atomic_write_bytes(str(target), previous)
            except Exception:
                pass
        return _safe_error_result("restore_failed_rolled_back", "Restore failed and the previous local data was restored.")

    return {
        "ok": True,
        "restored_file_count": len(written),
        "backup_format": BACKUP_FORMAT,
        "archive_sha256": str(payload.get("archive_sha256") or ""),
        "message": "Encrypted backup restored.",
    }


def reset_current_profile(user_id: str, *, confirmation: str = RESET_PROFILE_CONFIRMATION, delete_sessions: bool = False) -> Dict[str, Any]:
    """Backend-confirmed wrapper around the existing profile reset implementation."""
    if str(confirmation or "").strip() != RESET_PROFILE_CONFIRMATION:
        return {"ok": False, "reason": "confirmation_required", "message": "Profile reset confirmation is required."}
    if not str(user_id or "").strip():
        return {"ok": False, "reason": "user_required", "message": "Current user is required."}
    from model_metadata import reset_user_profile

    return dict(reset_user_profile(str(user_id), delete_sessions=bool(delete_sessions)))


def delete_all_local_data(*, confirmation: str = "") -> Dict[str, Any]:
    """Delete local BioAuth data directories after explicit backend confirmation."""
    if str(confirmation or "").strip() != DELETE_ALL_CONFIRMATION:
        return {"ok": False, "reason": "confirmation_required", "message": f"Type {DELETE_ALL_CONFIRMATION!r} to delete local BioAuth data."}

    deleted: List[str] = []
    for root in (Path(paths.data_dir()), Path(paths.models_dir())):
        if not root.exists():
            continue
        for child in sorted(root.iterdir(), key=lambda p: p.name):
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                deleted.append(str(child))
            except FileNotFoundError:
                continue
    try:
        import security

        security.reset_security_caches()
    except Exception:
        pass
    return {"ok": True, "deleted_path_count": len(deleted), "message": "Local BioAuth data deleted."}


def backup_format_summary() -> Dict[str, Any]:
    return {
        "backup_format": BACKUP_FORMAT,
        "backup_schema_version": BACKUP_SCHEMA_VERSION,
        "outer_storage_format_version": STORAGE_FORMAT_VERSION,
        "outer_algorithm": SECURE_ENVELOPE_ALGORITHM,
        "archive_encoding": "base64",
        "archive_compression": "zip-deflated",
        "included_metadata_database": "data/metadata_index.sqlite3 when present; rebuildable from encrypted file metadata if absent",
        "excluded_runtime_dirs": sorted(_EXCLUDED_TOP_LEVEL_UNDER_DATA),
        "excluded_secret_files": sorted(_EXCLUDED_FILE_NAMES),
        "delete_all_confirmation": DELETE_ALL_CONFIRMATION,
    }
