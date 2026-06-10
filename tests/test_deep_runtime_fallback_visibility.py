from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deep_runtime import (
    deep_runtime_fallback_reason_text,
    deep_runtime_is_fallback,
    normalize_benchmark_record,
    normalize_deep_runtime_fallback_reason,
    resolve_deep_runtime_state,
)



def _install_pyside6_stub() -> None:
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
            self.count = 0

        def connect(self, *_args, **_kwargs):
            return None

        def emit(self, *_args, **_kwargs):
            self.count += 1

    def _slot(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def _property(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    class _QTimer:
        timeout = _Signal()

        def setInterval(self, *_args, **_kwargs):
            return None

        def start(self):
            return None

        @staticmethod
        def singleShot(*_args, **_kwargs):
            return None

    class _QUrl(str):
        @staticmethod
        def fromLocalFile(path: str) -> str:
            return path

    class _QLocale:
        def name(self):
            return "en_US"

    class _QDesktopServices:
        @staticmethod
        def openUrl(*_args, **_kwargs):
            return True

    class _QIcon:
        def __init__(self, *_args, **_kwargs):
            pass

    class _QQmlApplicationEngine:
        pass

    class _QApplication:
        def __init__(self, *_args, **_kwargs):
            pass

    class _QSystemTrayIcon:
        def __init__(self, *_args, **_kwargs):
            pass

        @staticmethod
        def isSystemTrayAvailable():
            return False

    class _QMenu:
        def addAction(self, *_args, **_kwargs):
            return types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda *_a, **_k: None))

    qtcore.QObject = _QObject
    qtcore.Property = _property
    qtcore.QTimer = _QTimer
    qtcore.QUrl = _QUrl
    qtcore.Signal = _Signal
    qtcore.Slot = _slot
    qtcore.QLocale = _QLocale
    qtgui.QDesktopServices = _QDesktopServices
    qtgui.QIcon = _QIcon
    qtqml.QQmlApplicationEngine = _QQmlApplicationEngine
    qtwidgets.QApplication = _QApplication
    qtwidgets.QSystemTrayIcon = _QSystemTrayIcon
    qtwidgets.QMenu = _QMenu
    pyside6.QtCore = qtcore
    pyside6.QtGui = qtgui
    pyside6.QtQml = qtqml
    pyside6.QtWidgets = qtwidgets
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtQml"] = qtqml
    sys.modules["PySide6.QtWidgets"] = qtwidgets


class DummySignal:
    def __init__(self) -> None:
        self.count = 0

    def emit(self, *_args, **_kwargs) -> None:
        self.count += 1


def _install_settings_mixin_import_stubs() -> dict[str, object | None]:
    _install_pyside6_stub()
    names = [
        "app_settings",
        "app_passcode",
        "license_manager",
        "release_profile",
        "bridge.shared",
        "bridge.settings_mixin",
    ]
    previous = {name: sys.modules.get(name) for name in names}

    app_settings = types.ModuleType("app_settings")
    app_settings.PRIVACY_POLICY_VERSION = "test-policy"
    app_settings.feature_flag_enabled = lambda settings, key: bool((settings or {}).get(key, False))
    app_settings.has_current_face_template_consent = lambda settings: bool((settings or {}).get("face_template_consent_granted", False))
    app_settings.normalize_interface_mode = lambda value: "user" if str(value).lower() == "user" else "developer"
    app_settings.build_evidence_consent_fields = lambda granted=True: {"incident_evidence_consent_granted": bool(granted)}
    app_settings.build_face_template_consent_fields = lambda granted=True: {"face_template_consent_granted": bool(granted)}
    app_settings.build_privacy_consent_fields = lambda: {"privacy_consent_policy_version": "test-policy"}
    sys.modules["app_settings"] = app_settings

    app_passcode = types.ModuleType("app_passcode")
    app_passcode.build_passcode_record = lambda *_args, **_kwargs: {}
    app_passcode.is_passcode_configured = lambda record: bool(record)
    app_passcode.validate_passcode_value = lambda value: (bool(value), "")
    app_passcode.verify_passcode_record = lambda *_args, **_kwargs: False
    sys.modules["app_passcode"] = app_passcode

    license_manager = types.ModuleType("license_manager")
    license_manager.activate_license_code = lambda *_args, **_kwargs: {}
    license_manager.import_license_file = lambda *_args, **_kwargs: {}
    sys.modules["license_manager"] = license_manager

    release_profile = types.ModuleType("release_profile")
    release_profile.current_build_profile = lambda: "test"
    release_profile.current_package_profile = lambda: "source"
    sys.modules["release_profile"] = release_profile

    shared = types.ModuleType("bridge.shared")
    shared.THEMES = {}
    shared.STRINGS = {}
    shared.WELCOME_POLICY_VERSION = "test-welcome"
    shared.ABOUT_US_PATH = "ABOUT_US.md"
    shared.QDesktopServices = object
    shared.QUrl = object
    shared.QTimer = object
    shared.Slot = lambda *args, **kwargs: (lambda func: func)
    shared.complete_user_onboarding = lambda *_args, **_kwargs: None
    shared.is_startup_enabled = lambda: False
    shared.play_button_sound = lambda *_args, **_kwargs: None
    shared.normalize_sensitivity_preset = lambda value: str(value or "balanced").lower()
    shared.save_settings_async = lambda payload: dict(payload)
    shared.set_startup_enabled = lambda *_args, **_kwargs: False
    shared.translate_string = lambda _language, key, **_kwargs: key
    sys.modules["bridge.shared"] = shared
    sys.modules.pop("bridge.settings_mixin", None)
    return previous


def _restore_import_stubs(previous: dict[str, object | None]) -> None:
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _load_settings_mixin_class():
    previous = _install_settings_mixin_import_stubs()
    try:
        module = importlib.import_module("bridge.settings_mixin")
        return module.SettingsMixin
    finally:
        _restore_import_stubs(previous)


def test_backend_fallback_reason_mapping_is_safe_and_complete() -> None:
    expected_reasons = {
        "benchmark_not_run",
        "classic_requested",
        "deep_runtime_not_available_yet",
        "accelerated_backend_unavailable",
        "backend_import_failed",
        "model_unavailable",
        "ok",
    }
    for reason in expected_reasons:
        assert normalize_deep_runtime_fallback_reason(reason) == reason
        text = deep_runtime_fallback_reason_text(reason)
        assert text
        assert "Traceback" not in text
        assert "File \"" not in text
    assert deep_runtime_is_fallback("ok") is False
    assert deep_runtime_is_fallback("classic_requested") is False
    for reason in expected_reasons - {"ok", "classic_requested"}:
        assert deep_runtime_is_fallback(reason) is True


def test_resolved_state_exposes_qml_safe_fallback_fields() -> None:
    state = resolve_deep_runtime_state({"deep_runtime_mode": "auto", "deep_runtime_manual_override": False})
    assert state["fallback_reason"] == "benchmark_not_run"
    assert state["fallbackReason"] == "benchmark_not_run"
    assert state["is_fallback"] is True
    assert state["isFallback"] is True
    assert "Core protection remains active" in state["fallback_reason_text"]
    assert state["fallbackReasonText"] == state["fallback_reason_text"]

    classic = resolve_deep_runtime_state({"deep_runtime_mode": "classic", "deep_runtime_manual_override": True})
    assert classic["fallback_reason"] == "classic_requested"
    assert classic["isFallback"] is False

    benchmark = normalize_benchmark_record({"fallback_reason": "backend_import_failed"})
    assert benchmark["fallbackReason"] == "backend_import_failed"
    assert benchmark["isFallback"] is True
    assert "Core protection remains active" in benchmark["fallbackReasonText"]


def test_qml_uses_backend_owned_fallback_properties() -> None:
    settings_qml = (ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml").read_text(encoding="utf-8")
    telemetry_qml = (ROOT / "qml" / "components" / "LiveTelemetryPanel.qml").read_text(encoding="utf-8")

    for source in (settings_qml, telemetry_qml):
        assert "backend.deepRuntimeFallbackReasonText" in source
        assert "backend.deepRuntimeIsFallback" in source
        assert "fallback_reason" not in source
        assert "Traceback" not in source

    assert "Protection remains active through the core engine" in settings_qml
    assert "Active protection" in telemetry_qml
    assert "Fallback reason" in telemetry_qml


def test_bridge_deep_runtime_properties_update_when_runtime_metadata_changes() -> None:
    SettingsMixin = _load_settings_mixin_class()

    class Bridge(SettingsMixin):
        def __init__(self) -> None:
            self._settings_payload_value = {
                "deep_runtime_mode": "hybrid",
                "deep_runtime_manual_override": True,
                "deep_runtime_benchmark": {
                    "status": "ok",
                    "recommended_mode": "hybrid",
                    "recommended_backend": "classic",
                    "fallback_reason": "ok",
                },
            }
            self._runtime_state = {
                "runtime_metadata": {
                    "deep_runtime": {
                        "deep_sequence_runtime_enabled": False,
                        "sequence_model": {"enabled": False, "artifact": None},
                    }
                }
            }
            self._deep_runtime_state = {}
            self._deep_runtime_mode = "hybrid"
            self._deep_runtime_manual_override = True
            self._deep_runtime_benchmark = {}
            self.deepRuntimeChanged = DummySignal()

        def _settings_payload(self, **changes):
            payload = dict(self._settings_payload_value)
            payload.update(changes)
            return payload

    bridge = Bridge()

    changed = bridge._refresh_deep_runtime_state()
    assert changed is True
    assert bridge._deep_runtime_state["effective_mode"] == "classic"
    assert bridge._deep_runtime_state["fallbackReason"] == "deep_runtime_not_available_yet"
    assert bridge._deep_runtime_state["isFallback"] is True

    bridge._runtime_state = {
        "runtime_metadata": {
            "deep_runtime": {
                "deep_sequence_runtime_enabled": True,
                "sequence_model": {"enabled": True, "artifact": "sequence.onnx"},
            }
        }
    }
    changed = bridge._refresh_deep_runtime_state()
    assert changed is True
    assert bridge._deep_runtime_state["effective_mode"] == "hybrid"
    assert bridge._deep_runtime_state["fallbackReason"] == "ok"
    assert bridge._deep_runtime_state["isFallback"] is False


def run_all() -> None:
    test_backend_fallback_reason_mapping_is_safe_and_complete()
    test_resolved_state_exposes_qml_safe_fallback_fields()
    test_qml_uses_backend_owned_fallback_properties()
    test_bridge_deep_runtime_properties_update_when_runtime_metadata_changes()


if __name__ == "__main__":
    run_all()
    print("ALL_DEEP_RUNTIME_FALLBACK_VISIBILITY_CHECKS_PASSED=4")
