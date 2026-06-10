from __future__ import annotations

import builtins
import importlib
import json
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def install_secret_storage_stub() -> None:
    module = types.ModuleType("bio_platform.secrets")
    module.get_secret_backend_name = lambda: "test-stub"
    module.load_or_create_secret = lambda **kwargs: kwargs.get("generate_secret", lambda: b"0" * 32)()
    sys.modules.setdefault("bio_platform.secrets", module)


def install_identity_stub() -> None:
    package = types.ModuleType("utils")
    identity = types.ModuleType("utils.identity")

    def slugify_username(value):
        text = str(value or "").strip().lower().replace(" ", "_")
        return "".join(ch for ch in text if ch.isalnum() or ch in {"_", "-"}).strip("_-")

    identity.slugify_username = slugify_username
    package.identity = identity
    sys.modules.setdefault("utils", package)
    sys.modules.setdefault("utils.identity", identity)


def install_features_stub() -> None:
    features = types.ModuleType("features")
    features.DEFAULT_MIN_WINDOW_EVENTS = 24
    features.DEFAULT_WINDOW_SECONDS = 12.0
    features.DEFAULT_WINDOW_STEP_SECONDS = 6.0

    features.TRANSITION_SESSION_START_SECONDS = 2.0
    features.TRANSITION_POST_IDLE_GAP_SECONDS = 30.0
    features.TRANSITION_ACTIVITY_SHIFT_THRESHOLD = 0.35
    features.SEQUENCE_FEATURES_VERSION = "test-sequence-v1"
    features.SEQUENCE_TREND_LOOKBACK = 3
    features.annotate_transition_windows = lambda samples, *args, **kwargs: list(samples or [])
    features.annotate_sequence_trend_windows = lambda samples, *args, **kwargs: list(samples or [])
    features.classify_behavior_context = lambda sample, *args, **kwargs: {"context": "mixed", "confidence": 0.0}
    features.extract_context_router_features = lambda sample, *args, **kwargs: {"context": "mixed", "confidence": 0.0}
    features.extract_keyboard_features = lambda *args, **kwargs: {}
    features.extract_mouse_features = lambda *args, **kwargs: {}
    features.extract_combined_features = lambda *args, **kwargs: {}
    features.extract_window_feature_samples = lambda *args, **kwargs: []
    features.extract_multi_scale_window_feature_samples = lambda *args, **kwargs: []
    features.extract_session_quality_indicators = lambda *args, **kwargs: {"quality_score": 1.0, "accepted": True}
    sys.modules.setdefault("features", features)


class CaptureLogs:
    def __init__(self, level=logging.WARNING):
        self.records = []
        self.handler = logging.Handler()
        self.handler.emit = self.records.append
        self.level = level
        self.root = logging.getLogger()
        self.old_level = self.root.level

    def __enter__(self):
        self.root.addHandler(self.handler)
        self.root.setLevel(self.level)
        return self.records

    def __exit__(self, exc_type, exc, tb):
        self.root.removeHandler(self.handler)
        self.root.setLevel(self.old_level)


def check_settings_load_failure() -> None:
    install_secret_storage_stub()
    install_identity_stub()
    import app_settings

    app_settings._SETTINGS_CACHE = None
    with tempfile.TemporaryDirectory() as td:
        settings_file = Path(td) / "settings.json"
        settings_file.write_text("{}", encoding="utf-8")
        original_file = app_settings.SETTINGS_FILE
        original_loader = app_settings.load_enveloped_json
        app_settings.SETTINGS_FILE = str(settings_file)
        app_settings.load_enveloped_json = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("storage unavailable"))
        try:
            with CaptureLogs() as records:
                settings = app_settings.load_settings()
        finally:
            app_settings.SETTINGS_FILE = original_file
            app_settings.load_enveloped_json = original_loader
            app_settings._SETTINGS_CACHE = None
    assert settings == app_settings.DEFAULT_SETTINGS
    assert app_settings.get_last_settings_storage_state() == "load_error"
    assert any("settings storage error" in record.getMessage().lower() for record in records)


def check_users_load_failure() -> None:
    install_secret_storage_stub()
    install_identity_stub()
    import auth

    original_loader = auth.load_enveloped_json
    auth.load_enveloped_json = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("users unavailable"))
    try:
        with CaptureLogs() as records:
            users = auth._load_users()
    finally:
        auth.load_enveloped_json = original_loader
    assert users == {}
    assert auth.get_last_users_storage_state() == "load_error"
    assert any("Users file could not be loaded" in record.getMessage() for record in records)


def check_license_malformed_and_import_failure() -> None:
    import license_manager

    for bad_code in ("BIOAUTH-LIC-v1.not-valid", "BIOAUTH-LIC-v1.invalid.invalid"):
        payload, signature, error = license_manager.parse_license_code(bad_code)
        assert payload == {}
        assert signature == ""
        assert error == "malformed_license_code"
    with tempfile.TemporaryDirectory() as td:
        bad_json = Path(td) / "bad_license.json"
        bad_json.write_text('{"license_code":', encoding="utf-8")
        with CaptureLogs() as records:
            result = license_manager.import_license_file(bad_json)
    assert result["ok"] is False
    assert result["state"] == "invalid_basic"
    assert result["licenseStatus"]["last_error"] == license_manager.ERROR_MESSAGES["license_import_failed"]
    assert any("License import failed" in record.getMessage() for record in records)


def check_runtime_bundle_invalid_artifacts() -> None:
    install_secret_storage_stub()
    install_identity_stub()
    install_features_stub()
    from metadata_core import runtime

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        model = root / "model.pkl"
        metadata = root / "metadata.json"
        classifier = root / "classifier.pkl"
        model.write_bytes(b"model")
        metadata.write_text("{}", encoding="utf-8")
        classifier.write_bytes(b"classifier")
        paths = {"model": str(model), "metadata": str(metadata), "classifier": str(classifier)}

        def install_artifact_module(metadata_error=False, model_error=False, classifier_error=False):
            module = types.ModuleType("artifact_integrity")

            def load_metadata(_path):
                if metadata_error:
                    raise ValueError("bad metadata")
                return {
                    "feature_schema_version": runtime.FEATURE_SCHEMA_VERSION,
                    "feature_window_strategy": runtime.FEATURE_WINDOW_STRATEGY,
                    "active_window_scales": runtime.ACTIVE_WINDOW_SCALES,
                    "bundle_role": "production",
                    "model_status": "approved_for_production",
                    "classifier_family": "rf",
                }

            def load_model(_path):
                if model_error:
                    raise ValueError("bad model")
                return object()

            def load_classifier(_path):
                if classifier_error:
                    raise ValueError("bad classifier")
                return object()

            module.load_metadata = load_metadata
            module.load_model = load_model
            module.load_classifier = load_classifier
            sys.modules["artifact_integrity"] = module

        reasons = []
        for kwargs in ({"metadata_error": True}, {"model_error": True}, {"classifier_error": True}):
            runtime.clear_runtime_model_cache()
            install_artifact_module(**kwargs)
            reasons.append(runtime.validate_runtime_bundle_for_activation(paths)["reason"])
    assert reasons[0].startswith("metadata_invalid:")
    assert reasons[1].startswith("model_invalid:")
    assert reasons[2].startswith("classifier_invalid:")


def check_dashboard_bad_session_json() -> None:
    install_secret_storage_stub()
    install_identity_stub()
    from metadata_core import sessions

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        session_dir = root / "alice_protected_legit_sess001"
        session_dir.mkdir()
        (session_dir / "keyboard_log.csv").write_text("ts,key\n", encoding="utf-8")
        (session_dir / "metadata.json").write_text('{"session_id":', encoding="utf-8")
        sessions.invalidate_session_discovery_cache(str(root))
        with CaptureLogs() as records:
            meta = sessions.read_session_metadata(str(session_dir))
    assert meta is not None
    assert meta["metadata_trusted"] is False
    assert meta["metadata_integrity"] == "invalid"
    assert meta["metadata_inferred"] is True
    assert any("Session metadata could not be trusted" in record.getMessage() for record in records)


def check_evidence_capture_qt_unavailable() -> None:
    install_secret_storage_stub()
    install_identity_stub()
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("PySide6"):
            raise ImportError("PySide6 unavailable in focused test")
        return real_import(name, globals, locals, fromlist, level)

    builtins.__import__ = fake_import
    try:
        sys.modules.pop("evidence_capture", None)
        evidence_capture = importlib.import_module("evidence_capture")
        with tempfile.TemporaryDirectory() as td:
            screenshot = evidence_capture.try_capture_screenshot(str(Path(td) / "shot.png"), timeout_sec=0.01)
            webcam = evidence_capture.try_capture_webcam_burst(td, timeout_sec=0.01)
    finally:
        builtins.__import__ = real_import
    assert screenshot["status"] == "failed"
    assert screenshot["error_reason"].startswith("qt_unavailable:")
    assert webcam["status"] == "failed"
    assert webcam["error_reason"].startswith("qt_unavailable:")


def check_monitor_runtime_exception_source_path() -> None:
    source = (ROOT / "src" / "bioauth" / "runtime" / "monitor_impl.py").read_text(encoding="utf-8")
    handler = 'except Exception as exc:\n                LOGGER.exception("Monitor runtime failed unexpectedly")'
    assert handler in source
    block = source[source.index(handler): source.index(handler) + 500]
    assert "_signal_unhandled_monitor_failure(exc" in block
    assert 'print(f"Monitor runtime failure: {type(exc).__name__}"' in block
    assert "break" in block


CHECKS = [
    ("settings load failure", check_settings_load_failure),
    ("users load failure", check_users_load_failure),
    ("license malformed/import failure", check_license_malformed_and_import_failure),
    ("runtime bundle invalid metadata/model/classifier", check_runtime_bundle_invalid_artifacts),
    ("dashboard/session bad JSON", check_dashboard_bad_session_json),
    ("evidence capture unavailable Qt/camera/screenshot", check_evidence_capture_qt_unavailable),
    ("monitor runtime exception source path", check_monitor_runtime_exception_source_path),
]


def main() -> int:
    failures = []
    for name, check in CHECKS:
        try:
            check()
            print(f"PASS: {name}")
        except Exception as exc:
            failures.append((name, exc))
            print(f"FAIL: {name}: {type(exc).__name__}: {exc}")
    if failures:
        return 1
    print(f"ALL_FOCUSED_CHECKS_PASSED={len(CHECKS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
