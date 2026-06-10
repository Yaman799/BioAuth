from __future__ import annotations

import base64
import io
import stat
import sys
import types
import zipfile
from pathlib import Path

import pytest


def _install_fake_pyside6() -> None:
    if "PySide6" in sys.modules:
        return
    pyside6 = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")
    qtqml = types.ModuleType("PySide6.QtQml")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class _QObject:
        pass

    class _Signal:
        def __init__(self, *args, **kwargs):
            self._callbacks = []

        def connect(self, callback):
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs):
            for callback in list(self._callbacks):
                callback(*args, **kwargs)

    def _slot(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def _property(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    class _QTimer:
        def __init__(self, *args, **kwargs):
            self.timeout = _Signal()

        def setInterval(self, *args, **kwargs):
            pass

        def start(self):
            pass

        @staticmethod
        def singleShot(*args, **kwargs):
            pass

    class _QUrl(str):
        @staticmethod
        def fromLocalFile(path: str) -> str:
            return path

    class _QLocale:
        def name(self):
            return "en_US"

    qtcore.QObject = _QObject
    qtcore.Property = _property
    qtcore.QTimer = _QTimer
    qtcore.QUrl = _QUrl
    qtcore.Signal = _Signal
    qtcore.Slot = _slot
    qtcore.QLocale = _QLocale

    class _QDesktopServices:
        @staticmethod
        def openUrl(*args, **kwargs):
            return True

    class _QIcon:
        def __init__(self, *args, **kwargs):
            pass

    qtgui.QDesktopServices = _QDesktopServices
    qtgui.QIcon = _QIcon
    qtqml.QQmlApplicationEngine = type("_QQmlApplicationEngine", (), {})
    qtwidgets.QApplication = type("_QApplication", (), {"__init__": lambda self, *args, **kwargs: None})
    qtwidgets.QSystemTrayIcon = type("_QSystemTrayIcon", (), {"isSystemTrayAvailable": staticmethod(lambda: False)})
    qtwidgets.QMenu = type("_QMenu", (), {"addAction": lambda self, *args, **kwargs: types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda *a, **k: None))})

    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtQml"] = qtqml
    sys.modules["PySide6.QtWidgets"] = qtwidgets


_install_fake_pyside6()

import local_data_backup
import paths
import bio_platform.secrets as secret_backend
import security
import secure_storage
from bridge import settings_mixin


def _configure_local_store(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data"
    models_root = tmp_path / "models"
    data_root.mkdir()
    models_root.mkdir()
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


def _seed_data(data_root: Path, models_root: Path, *, suffix: str = "backup") -> None:
    secure_storage.write_enveloped_json(str(data_root / "settings.json"), {"version": suffix, "owner_email": f"alice-{suffix}@example.com"})
    secure_storage.write_enveloped_json(str(data_root / "users.json"), {"alice": {"email": f"alice-{suffix}@example.com"}})
    user_model = models_root / "alice"
    user_model.mkdir(parents=True, exist_ok=True)
    (user_model / "model.pkl").write_bytes(f"model-{suffix}".encode("utf-8"))
    (models_root / "secret.key").write_bytes(security.get_or_create_key())


def _encrypted_payload_path(tmp_path: Path, payload: dict) -> Path:
    backup_path = tmp_path / "crafted.bioauthbackup"
    secure_storage.write_enveloped_json(str(backup_path), payload)
    return backup_path


def _crafted_archive_payload(entries: dict[str, bytes], *, symlink_names: set[str] | None = None, manifest_paths: list[str] | None = None) -> dict:
    symlink_names = symlink_names or set()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel, data in entries.items():
            info = zipfile.ZipInfo(rel)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            if rel in symlink_names:
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, data)
    archive_bytes = buffer.getvalue()
    manifest = []
    for rel in manifest_paths or list(entries):
        data = entries.get(rel, b"")
        manifest.append({"path": rel, "size": len(data), "sha256": local_data_backup._sha256_bytes(data)})
    return {
        "backup_format": local_data_backup.BACKUP_FORMAT,
        "backup_schema_version": local_data_backup.BACKUP_SCHEMA_VERSION,
        "archive_encoding": "base64",
        "archive_sha256": local_data_backup._sha256_bytes(archive_bytes),
        "files": manifest,
        "archive_b64": base64.b64encode(archive_bytes).decode("ascii"),
    }


def test_export_refuses_symlinked_local_files(tmp_path, monkeypatch) -> None:
    data_root, models_root = _configure_local_store(tmp_path, monkeypatch)
    _seed_data(data_root, models_root)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link_path = data_root / "sessions-link.json"
    try:
        link_path.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    backup_path = tmp_path / "bioauth.backup"
    result = local_data_backup.export_encrypted_backup(str(backup_path))

    assert result["ok"] is False
    assert result["reason"] == "backup_symlink_refused"
    assert "symbolic link" in result["message"]
    assert not backup_path.exists()


def test_restore_rejects_path_traversal_manifest_entries(tmp_path, monkeypatch) -> None:
    data_root, models_root = _configure_local_store(tmp_path, monkeypatch)
    _seed_data(data_root, models_root)
    payload = _crafted_archive_payload({"data/../outside.txt": b"bad"})
    backup_path = _encrypted_payload_path(tmp_path, payload)

    result = local_data_backup.restore_encrypted_backup(str(backup_path))

    assert result["ok"] is False
    assert result["reason"] == "backup_validation_failed"
    assert not (tmp_path / "outside.txt").exists()


def test_restore_rejects_zip_symlink_entries(tmp_path, monkeypatch) -> None:
    data_root, models_root = _configure_local_store(tmp_path, monkeypatch)
    _seed_data(data_root, models_root)
    payload = _crafted_archive_payload({"data/settings.json": b"target"}, symlink_names={"data/settings.json"})
    backup_path = _encrypted_payload_path(tmp_path, payload)

    result = local_data_backup.restore_encrypted_backup(str(backup_path))

    assert result["ok"] is False
    assert result["reason"] == "backup_validation_failed"


def test_restore_refuses_existing_symlink_targets_without_overwriting_outside_file(tmp_path, monkeypatch) -> None:
    data_root, models_root = _configure_local_store(tmp_path, monkeypatch)
    _seed_data(data_root, models_root, suffix="backup")
    backup_path = tmp_path / "safe.backup"
    assert local_data_backup.export_encrypted_backup(str(backup_path))["ok"] is True
    outside = tmp_path / "outside-settings.json"
    outside.write_text("outside-current", encoding="utf-8")
    (data_root / "settings.json").unlink()
    try:
        (data_root / "settings.json").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    result = local_data_backup.restore_encrypted_backup(str(backup_path))

    assert result["ok"] is False
    assert result["reason"] == "restore_target_unsafe"
    assert outside.read_text(encoding="utf-8") == "outside-current"


def test_restore_rolls_back_previous_files_when_partial_write_fails(tmp_path, monkeypatch) -> None:
    data_root, models_root = _configure_local_store(tmp_path, monkeypatch)
    _seed_data(data_root, models_root, suffix="backup")
    backup_path = tmp_path / "safe.backup"
    assert local_data_backup.export_encrypted_backup(str(backup_path))["ok"] is True

    _seed_data(data_root, models_root, suffix="current")
    original_settings = (data_root / "settings.json").read_bytes()
    original_users = (data_root / "users.json").read_bytes()
    real_atomic_write = local_data_backup.atomic_write_bytes
    calls: list[str] = []

    def flaky_atomic_write(path: str, data: bytes) -> None:
        calls.append(Path(path).name)
        if len(calls) == 2:
            raise OSError("simulated write failure with private path /tmp/secret")
        real_atomic_write(path, data)

    monkeypatch.setattr(local_data_backup, "atomic_write_bytes", flaky_atomic_write)

    result = local_data_backup.restore_encrypted_backup(str(backup_path))

    assert result["ok"] is False
    assert result["reason"] == "restore_failed_rolled_back"
    assert "/tmp/secret" not in result["message"]
    assert (data_root / "settings.json").read_bytes() == original_settings
    assert (data_root / "users.json").read_bytes() == original_users


class _RunningServer:
    running = True


class _DummySettingsBridge:
    def __init__(self) -> None:
        self._training_in_progress = False
        self._pending_monitor_start = False
        self._pending_logger_start = False
        self._pending_shadow_evidence_monitor_start = False
        self._companion_api_server = None
        self.canStop = False
        self.enrollment_flow = "idle"
        self.user_flow = "idle"
        self.monitor_running = False

    def _destructive_action_block_reason(self, *, for_delete: bool = False) -> str:
        return ""

    def _normal_enrollment_logger_flow(self) -> str:
        return self.enrollment_flow

    def _normal_user_session_flow(self) -> str:
        return self.user_flow

    def _production_monitor_process_running(self) -> bool:
        return self.monitor_running


def _guard_reason(dummy: _DummySettingsBridge) -> str:
    return settings_mixin.SettingsMixin._local_data_action_block_reason(dummy)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("_training_in_progress", True, "training"),
        ("_pending_monitor_start", True, "starting"),
        ("_pending_logger_start", True, "starting"),
        ("_pending_shadow_evidence_monitor_start", True, "starting"),
        ("canStop", True, "current session"),
        ("enrollment_flow", "enrollment_active", "learning"),
        ("user_flow", "protected_active", "protection"),
        ("monitor_running", True, "protection"),
        ("_companion_api_server", _RunningServer(), "Companion"),
    ],
)
def test_backend_local_data_guard_blocks_unsafe_runtime_states(field, value, expected) -> None:
    dummy = _DummySettingsBridge()
    setattr(dummy, field, value)

    reason = _guard_reason(dummy)

    assert expected in reason


def test_backend_local_data_guard_allows_idle_state() -> None:
    assert _guard_reason(_DummySettingsBridge()) == ""
