from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import patch

from app_passcode import build_passcode_record, is_passcode_configured


class DummySignal:
    def __init__(self) -> None:
        self.count = 0

    def emit(self, *args, **kwargs) -> None:
        self.count += 1


def _install_settings_mixin_import_stubs() -> dict[str, object]:
    names = [
        "app_settings",
        "deep_runtime",
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

    deep_runtime = types.ModuleType("deep_runtime")
    deep_runtime.normalize_benchmark_record = lambda value: value if isinstance(value, dict) else {}
    deep_runtime.normalize_deep_runtime_mode = lambda value, default="auto": str(value or default)
    deep_runtime.normalize_deep_runtime_fallback_reason = lambda value: str(value or "")
    deep_runtime.deep_runtime_fallback_reason_text = lambda value, language="en": str(value or "")
    deep_runtime.deep_runtime_is_fallback = lambda state=None, **kwargs: False
    deep_runtime.resolve_deep_runtime_state = lambda *_args, **_kwargs: {}
    deep_runtime.resolve_runtime_rollout_state = lambda *_args, **_kwargs: {"production_decision_influence_enabled": False, "effective_mode": "classic"}
    deep_runtime.run_local_device_benchmark = lambda *_args, **_kwargs: {}
    sys.modules["deep_runtime"] = deep_runtime

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


def _restore_import_stubs(previous: dict[str, object]) -> None:
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _load_settings_mixin():
    previous = _install_settings_mixin_import_stubs()
    try:
        module = importlib.import_module("bridge.settings_mixin")
        return module.SettingsMixin, module
    finally:
        _restore_import_stubs(previous)


SettingsMixin, settings_mixin_module = _load_settings_mixin()


class DummySettings(SettingsMixin):
    def __init__(self) -> None:
        self._theme = "dark"
        self._language = "en"
        self._run_on_startup = False
        self._risk_sensitivity = "balanced"
        self._mute_button_sounds = False
        self._remember_login_enabled = False
        self._incident_evidence_enabled = False
        self._incident_evidence_consent_granted = False
        self._incident_evidence_consent_policy_version = ""
        self._incident_evidence_consent_timestamp = ""
        self._incident_evidence_capture_screenshot = False
        self._incident_evidence_capture_webcam = False
        self._incident_evidence_retention_days = 30
        self._app_passcode_enabled = True
        self._app_passcode_timeout_sec = 60
        self._app_passcode_record = build_passcode_record("1234", iterations=1_000)
        self._deep_runtime_mode = "auto"
        self._deep_runtime_manual_override = False
        self._deep_runtime_benchmark = {}
        self._app_settings = {}
        self._t = lambda key, **_kwargs: key
        self.appPasscodeChanged = DummySignal()
        self.statuses: list[tuple[str, str]] = []
        self.reset_count = 0

    def _set_status(self, message: str, tone: str = "info") -> None:
        self.statuses.append((message, tone))

    def _reset_app_passcode_runtime(self, *, unlock_only: bool = False) -> None:
        self.reset_count += 1


def test_disable_app_passcode_requires_current_code_and_preserves_state_on_failure() -> None:
    dummy = DummySettings()
    original_record = dict(dummy._app_passcode_record)

    with patch.object(settings_mixin_module, "save_settings", side_effect=lambda payload: dict(payload)) as save_settings:
        result = dummy.disableAppPasscode("9999")

    assert result is False
    assert dummy._app_passcode_enabled is True
    assert dummy._app_passcode_record == original_record
    assert dummy._app_settings == {}
    assert dummy.reset_count == 0
    assert dummy.appPasscodeChanged.count == 1
    assert dummy.statuses[-1] == ("app_passcode_invalid_current", "danger")
    save_settings.assert_not_called()


def test_disable_app_passcode_with_correct_code_disables_without_clearing_record() -> None:
    dummy = DummySettings()

    with patch.object(settings_mixin_module, "save_settings", side_effect=lambda payload: dict(payload)):
        result = dummy.disableAppPasscode("1234")

    assert result is True
    assert dummy._app_passcode_enabled is False
    assert is_passcode_configured(dummy._app_passcode_record) is True
    assert dummy._app_settings["app_passcode_enabled"] is False
    assert is_passcode_configured(dummy._app_settings["app_passcode_record"]) is True
    assert dummy.reset_count == 1
    assert dummy.appPasscodeChanged.count == 1
    assert dummy.statuses[-1] == ("app_passcode_disabled_msg", "info")


def test_set_app_passcode_enabled_false_is_blocked_without_current_code() -> None:
    dummy = DummySettings()

    with patch.object(settings_mixin_module, "save_settings", side_effect=lambda payload: dict(payload)) as save_settings:
        dummy.setAppPasscodeEnabled(False)

    assert dummy._app_passcode_enabled is True
    assert dummy._app_settings == {}
    assert dummy.appPasscodeChanged.count == 1
    assert dummy.statuses[-1] == ("app_passcode_disable_requires_current", "danger")
    save_settings.assert_not_called()


def test_clear_app_passcode_requires_current_code_and_preserves_state_on_failure() -> None:
    dummy = DummySettings()
    original_record = dict(dummy._app_passcode_record)

    with patch.object(settings_mixin_module, "save_settings", side_effect=lambda payload: dict(payload)) as save_settings:
        result = dummy.clearAppPasscode("9999")

    assert result is False
    assert dummy._app_passcode_enabled is True
    assert dummy._app_passcode_record == original_record
    assert dummy._app_settings == {}
    assert dummy.reset_count == 0
    assert dummy.appPasscodeChanged.count == 1
    assert dummy.statuses[-1] == ("app_passcode_invalid_current", "danger")
    save_settings.assert_not_called()


def test_clear_app_passcode_with_correct_code_removes_record_and_disables() -> None:
    dummy = DummySettings()

    with patch.object(settings_mixin_module, "save_settings", side_effect=lambda payload: dict(payload)):
        result = dummy.clearAppPasscode("1234")

    assert result is True
    assert dummy._app_passcode_enabled is False
    assert dummy._app_passcode_record == {}
    assert dummy._app_settings["app_passcode_enabled"] is False
    assert dummy._app_settings["app_passcode_record"] == {}
    assert dummy.reset_count == 1
    assert dummy.appPasscodeChanged.count == 1
    assert dummy.statuses[-1] == ("app_passcode_cleared", "success")


def test_settings_ui_reverts_draft_after_failed_disable_and_clear() -> None:
    page = open("qml/pages/SettingsPage.qml", encoding="utf-8").read()
    startup = open("qml/pages/settings/SettingsStartupTab.qml", encoding="utf-8").read()
    assert "backend.setAppPasscodeEnabled(draftAppPasscodeEnabled)" not in page
    assert "backend.disableAppPasscode(currentPasscodeField ? currentPasscodeField.text : \"\")" in page
    assert "Qt.callLater(syncDraftsFromBackend)" in page
    assert "if (backend.clearAppPasscode(currentPasscodeField.text))" in startup
    assert "Qt.callLater(controller.syncDraftsFromBackend)" in startup


def _run_direct() -> None:
    tests = [
        test_disable_app_passcode_requires_current_code_and_preserves_state_on_failure,
        test_disable_app_passcode_with_correct_code_disables_without_clearing_record,
        test_set_app_passcode_enabled_false_is_blocked_without_current_code,
        test_clear_app_passcode_requires_current_code_and_preserves_state_on_failure,
        test_clear_app_passcode_with_correct_code_removes_record_and_disables,
        test_settings_ui_reverts_draft_after_failed_disable_and_clear,
    ]
    for test in tests:
        test()
    print("PASSCODE_DISABLE_CLEAR_TESTS_PASS 6")


if __name__ == "__main__":
    _run_direct()
