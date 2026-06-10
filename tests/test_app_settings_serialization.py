from __future__ import annotations

import importlib
import json
import threading
from pathlib import Path

import app_settings
import bio_platform.secrets as secret_backend
import paths
import security


def _configure_settings_storage(tmp_path: Path, monkeypatch) -> Path:
    settings_path = tmp_path / "settings.json"
    model_dir = tmp_path / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(secret_backend, "keyring", None)
    monkeypatch.setattr(security, "MODELS_DIR", str(model_dir))
    monkeypatch.setattr(security, "KEY_FILE", str(model_dir / "secret.key"))
    monkeypatch.setattr(security, "KEY_FILE_DPAPI", str(model_dir / "secret.key.dpapi"))
    security.reset_security_caches()
    monkeypatch.setattr(app_settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_settings, "SETTINGS_FILE", str(settings_path))
    with app_settings._SETTINGS_LOCK:
        app_settings._SETTINGS_CACHE = None
    return settings_path


def test_save_settings_async_rapid_toggles_are_serialized(monkeypatch, tmp_path) -> None:
    settings_path = _configure_settings_storage(tmp_path, monkeypatch)

    for index in range(25):
        app_settings.save_settings_async({"remember_login_enabled": bool(index % 2)})

    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert set(saved) == {"storage_format_version", "encrypted", "algorithm", "key_id", "payload", "hmac"}
    assert saved["encrypted"] is True
    assert "remember_login_enabled" not in settings_path.read_text(encoding="utf-8")
    assert app_settings.load_settings()["remember_login_enabled"] is False


def test_save_settings_async_merges_concurrent_updates_without_lost_writes(monkeypatch, tmp_path) -> None:
    _configure_settings_storage(tmp_path, monkeypatch)
    barrier = threading.Barrier(3)

    def writer(payload):
        barrier.wait()
        app_settings.save_settings_async(payload)

    first = threading.Thread(target=writer, args=({"theme": "light"},))
    second = threading.Thread(target=writer, args=({
        "incident_evidence_enabled": True,
        "incident_evidence_consent_granted": True,
        "incident_evidence_consent_policy_version": app_settings.PRIVACY_POLICY_VERSION,
        "incident_evidence_consent_timestamp": "2026-04-24T00:00:00+00:00",
    },))
    first.start()
    second.start()
    barrier.wait()
    first.join()
    second.join()

    saved = app_settings.load_settings()
    assert saved["theme"] == "light"
    assert saved["incident_evidence_enabled"] is True


def test_save_settings_async_last_write_wins_for_same_key(monkeypatch, tmp_path) -> None:
    _configure_settings_storage(tmp_path, monkeypatch)

    app_settings.save_settings_async({"theme": "light"})
    app_settings.save_settings_async({"theme": "dark"})

    assert app_settings.load_settings()["theme"] == "dark"


def test_save_settings_async_persists_across_restart_simulation(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"

    with monkeypatch.context() as scoped:
        model_dir = tmp_path / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        scoped.setattr(secret_backend, "keyring", None)
        scoped.setattr(security, "MODELS_DIR", str(model_dir))
        scoped.setattr(security, "KEY_FILE", str(model_dir / "secret.key"))
        scoped.setattr(security, "KEY_FILE_DPAPI", str(model_dir / "secret.key.dpapi"))
        security.reset_security_caches()
        scoped.setattr(paths, "data_dir", lambda: str(tmp_path))
        scoped.setattr(paths, "settings_file", lambda: str(settings_path))
        module = importlib.reload(app_settings)
        module.save_settings_async({
            "theme": "light",
            "remember_login_enabled": True,
            "incident_evidence_enabled": True,
            "incident_evidence_consent_granted": True,
            "incident_evidence_consent_policy_version": module.PRIVACY_POLICY_VERSION,
            "incident_evidence_consent_timestamp": "2026-04-24T00:00:00+00:00",
        })
        module = importlib.reload(app_settings)
        loaded = module.load_settings()
        assert loaded["theme"] == "light"
        assert loaded["remember_login_enabled"] is True
        assert loaded["incident_evidence_enabled"] is True

    importlib.reload(app_settings)


def test_incident_evidence_without_current_consent_is_forced_off(monkeypatch, tmp_path) -> None:
    _configure_settings_storage(tmp_path, monkeypatch)

    saved = app_settings.save_settings_async({"incident_evidence_enabled": True})

    assert saved["incident_evidence_enabled"] is False
    assert saved["incident_evidence_capture_screenshot"] is False
    assert saved["incident_evidence_capture_webcam"] is False


def test_privacy_consent_helpers_stamp_current_policy(monkeypatch, tmp_path) -> None:
    _configure_settings_storage(tmp_path, monkeypatch)

    saved = app_settings.save_settings_async(app_settings.build_privacy_consent_fields())

    assert saved["privacy_policy_version"] == app_settings.PRIVACY_POLICY_VERSION
    assert saved["privacy_consent_policy_version"] == app_settings.PRIVACY_POLICY_VERSION
    assert app_settings.has_current_privacy_consent(saved) is True
