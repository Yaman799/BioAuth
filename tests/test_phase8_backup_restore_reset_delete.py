from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

import bio_platform.secrets as secret_backend
import paths
import security
import secure_storage
import local_data_backup


def _configure_local_store(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    data_root = tmp_path / "data"
    models_root = tmp_path / "models"
    data_root.mkdir(parents=True, exist_ok=True)
    models_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "data_dir", lambda: str(data_root))
    monkeypatch.setattr(paths, "models_dir", lambda: str(models_root))
    monkeypatch.setattr(paths, "settings_file", lambda: str(data_root / "settings.json"))
    monkeypatch.setattr(paths, "users_file", lambda: str(data_root / "users.json"))
    monkeypatch.setattr(secret_backend, "keyring", None)
    monkeypatch.setattr(security, "MODELS_DIR", str(models_root))
    monkeypatch.setattr(security, "KEY_FILE", str(models_root / "secret.key"))
    monkeypatch.setattr(security, "KEY_FILE_DPAPI", str(models_root / "secret.key.dpapi"))
    security.reset_security_caches()
    return data_root, models_root


def _seed_private_local_data(data_root: Path, models_root: Path) -> None:
    secure_storage.write_enveloped_json(str(data_root / "settings.json"), {"theme": "dark", "owner_email": "alice@example.com"})
    secure_storage.write_enveloped_json(str(data_root / "users.json"), {"alice": {"password_hash": "secret-password-hash", "email": "alice@example.com"}})
    session_dir = data_root / "sessions" / "alice_session_001"
    session_dir.mkdir(parents=True, exist_ok=True)
    secure_storage.write_enveloped_json(str(session_dir / "metadata.json"), {"session_id": "alice_session_001", "user_id": "alice"})
    (data_root / "live_session").mkdir(parents=True, exist_ok=True)
    (data_root / "live_session" / "runtime.tmp").write_text("runtime scratch should not be backed up", encoding="utf-8")
    (data_root / "control").mkdir(parents=True, exist_ok=True)
    (data_root / "control" / "stop").write_text("runtime stop control should not be backed up", encoding="utf-8")
    user_model = models_root / "alice"
    user_model.mkdir(parents=True, exist_ok=True)
    (user_model / "model.pkl").write_bytes(b"behavioral-model-bytes")
    (models_root / "secret.key").write_bytes(security.get_or_create_key())


def test_export_backup_is_encrypted_integrity_protected_and_excludes_runtime_junk(tmp_path, monkeypatch) -> None:
    data_root, models_root = _configure_local_store(tmp_path, monkeypatch)
    _seed_private_local_data(data_root, models_root)
    backup_path = tmp_path / "bioauth.backup"

    result = local_data_backup.export_encrypted_backup(str(backup_path))

    assert result["ok"] is True
    raw = backup_path.read_text(encoding="utf-8")
    envelope = json.loads(raw)
    assert set(envelope) == {"storage_format_version", "encrypted", "algorithm", "key_id", "payload", "hmac"}
    assert envelope["storage_format_version"] == secure_storage.STORAGE_FORMAT_VERSION
    assert envelope["encrypted"] is True
    assert "alice@example.com" not in raw
    assert "secret-password-hash" not in raw
    assert "behavioral-model-bytes" not in raw
    payload, state = secure_storage.load_enveloped_json(str(backup_path), rewrite_migrated=False)
    assert state == "envelope_v2"
    exported_paths = {entry["path"] for entry in payload["files"]}
    assert "data/settings.json" in exported_paths
    assert "data/users.json" in exported_paths
    assert "models/alice/model.pkl" in exported_paths
    assert "models/secret.key" not in exported_paths
    assert not any(path.startswith("data/live_session/") for path in exported_paths)
    assert not any(path.startswith("data/control/") for path in exported_paths)


def test_restore_backup_validates_archive_and_restores_expected_files(tmp_path, monkeypatch) -> None:
    data_root, models_root = _configure_local_store(tmp_path, monkeypatch)
    _seed_private_local_data(data_root, models_root)
    backup_path = tmp_path / "bioauth.backup"
    assert local_data_backup.export_encrypted_backup(str(backup_path))["ok"] is True

    (data_root / "settings.json").unlink()
    (data_root / "users.json").unlink()
    (models_root / "alice" / "model.pkl").unlink()

    restored = local_data_backup.restore_encrypted_backup(str(backup_path))

    assert restored["ok"] is True
    settings_payload, settings_state = secure_storage.load_enveloped_json(str(data_root / "settings.json"), rewrite_migrated=False)
    assert settings_state == "envelope_v2"
    assert settings_payload["owner_email"] == "alice@example.com"
    users_payload, users_state = secure_storage.load_enveloped_json(str(data_root / "users.json"), rewrite_migrated=False)
    assert users_state == "envelope_v2"
    assert users_payload["alice"]["email"] == "alice@example.com"
    assert (models_root / "alice" / "model.pkl").read_bytes() == b"behavioral-model-bytes"


def test_corrupted_backup_fails_closed_without_overwriting_current_files(tmp_path, monkeypatch) -> None:
    data_root, models_root = _configure_local_store(tmp_path, monkeypatch)
    _seed_private_local_data(data_root, models_root)
    backup_path = tmp_path / "bioauth.backup"
    assert local_data_backup.export_encrypted_backup(str(backup_path))["ok"] is True
    original_settings = (data_root / "settings.json").read_bytes()

    envelope = json.loads(backup_path.read_text(encoding="utf-8"))
    envelope["hmac"] = "0" * 64
    backup_path.write_text(json.dumps(envelope), encoding="utf-8")

    restored = local_data_backup.restore_encrypted_backup(str(backup_path))

    assert restored["ok"] is False
    assert restored["reason"] == "backup_validation_failed"
    assert (data_root / "settings.json").read_bytes() == original_settings



def test_reset_current_profile_requires_confirmation_and_calls_existing_model_reset(monkeypatch) -> None:
    denied = local_data_backup.reset_current_profile("alice", confirmation="reset")
    assert denied["ok"] is False
    assert denied["reason"] == "confirmation_required"

    called = {}
    fake_model_metadata = types.ModuleType("model_metadata")

    def fake_reset_user_profile(user_id: str, delete_sessions: bool = False):
        called["user_id"] = user_id
        called["delete_sessions"] = delete_sessions
        return {"ok": True, "message": "Profile reset.", "deleted_sessions": delete_sessions}

    fake_model_metadata.reset_user_profile = fake_reset_user_profile
    monkeypatch.setitem(sys.modules, "model_metadata", fake_model_metadata)

    result = local_data_backup.reset_current_profile("alice", confirmation=local_data_backup.RESET_PROFILE_CONFIRMATION)

    assert result["ok"] is True
    assert called == {"user_id": "alice", "delete_sessions": False}

def test_delete_all_local_data_requires_confirmation_and_deletes_only_local_data_roots(tmp_path, monkeypatch) -> None:
    data_root, models_root = _configure_local_store(tmp_path, monkeypatch)
    _seed_private_local_data(data_root, models_root)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")

    denied = local_data_backup.delete_all_local_data(confirmation="delete")
    assert denied["ok"] is False
    assert (data_root / "settings.json").exists()
    assert (models_root / "alice" / "model.pkl").exists()

    deleted = local_data_backup.delete_all_local_data(confirmation=local_data_backup.DELETE_ALL_CONFIRMATION)
    assert deleted["ok"] is True
    assert not any(data_root.iterdir())
    assert not any(models_root.iterdir())
    assert outside.read_text(encoding="utf-8") == "keep"


def test_backup_restore_rejects_excluded_secret_paths(tmp_path, monkeypatch) -> None:
    data_root, models_root = _configure_local_store(tmp_path, monkeypatch)
    _seed_private_local_data(data_root, models_root)
    payload = {
        "backup_format": local_data_backup.BACKUP_FORMAT,
        "backup_schema_version": local_data_backup.BACKUP_SCHEMA_VERSION,
        "archive_encoding": "base64",
        "archive_sha256": "unused",
        "files": [{"path": "models/secret.key", "size": 3, "sha256": "bad"}],
        "archive_b64": "AAAA",
    }
    backup_path = tmp_path / "bad-secret-path.backup"
    secure_storage.write_enveloped_json(str(backup_path), payload)

    result = local_data_backup.restore_encrypted_backup(str(backup_path))

    assert result["ok"] is False
    assert result["reason"] == "backup_validation_failed"
    assert (models_root / "secret.key").exists()



def test_bridge_slots_route_through_backend_guard_before_local_data_mutation() -> None:
    source = Path("bridge/settings_mixin.py").read_text(encoding="utf-8")
    for slot_name in (
        "exportEncryptedBackup",
        "importEncryptedBackup",
        "resetCurrentProfileData",
        "deleteAllLocalBioAuthData",
    ):
        assert f"def {slot_name}" in source
    assert "def _local_data_action_block_reason" in source
    assert source.count("blocked = self._local_data_action_block_reason()") >= 4
    assert "from local_data_backup import export_encrypted_backup" in source
    assert "from local_data_backup import restore_encrypted_backup" in source
    assert "from local_data_backup import DELETE_ALL_CONFIRMATION, delete_all_local_data" in source
    assert 'if str(confirmation or "").strip() != DELETE_ALL_CONFIRMATION' in source
