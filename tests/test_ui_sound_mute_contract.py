from __future__ import annotations

import importlib
import os
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _restore_env(name: str, old_value: str | None) -> None:
    if old_value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = old_value


def test_ui_sounds_does_not_call_winsound_by_default() -> None:
    module = importlib.import_module("ui_sounds")
    old_os_name = module.os.name
    old_winsound = sys.modules.get("winsound")
    old_enable = os.environ.get("BIOAUTH_ENABLE_UI_SOUNDS")
    old_disable = os.environ.get("BIOAUTH_DISABLE_UI_SOUNDS")
    calls = []
    fake = types.SimpleNamespace(
        SND_ALIAS=1,
        SND_ASYNC=2,
        PlaySound=lambda alias, flags: calls.append((alias, flags)),
    )
    sys.modules["winsound"] = fake  # type: ignore[assignment]
    module.os.name = "nt"
    os.environ.pop("BIOAUTH_ENABLE_UI_SOUNDS", None)
    os.environ.pop("BIOAUTH_DISABLE_UI_SOUNDS", None)
    try:
        assert module.play_button_sound("warning") is False
        assert calls == []
    finally:
        module.os.name = old_os_name
        if old_winsound is None:
            sys.modules.pop("winsound", None)
        else:
            sys.modules["winsound"] = old_winsound
        _restore_env("BIOAUTH_ENABLE_UI_SOUNDS", old_enable)
        _restore_env("BIOAUTH_DISABLE_UI_SOUNDS", old_disable)


def test_ui_sounds_can_be_enabled_only_by_developer_env() -> None:
    module = importlib.import_module("ui_sounds")
    old_os_name = module.os.name
    old_winsound = sys.modules.get("winsound")
    old_enable = os.environ.get("BIOAUTH_ENABLE_UI_SOUNDS")
    old_disable = os.environ.get("BIOAUTH_DISABLE_UI_SOUNDS")
    calls = []
    fake = types.SimpleNamespace(
        SND_ALIAS=1,
        SND_ASYNC=2,
        PlaySound=lambda alias, flags: calls.append((alias, flags)),
    )
    sys.modules["winsound"] = fake  # type: ignore[assignment]
    module.os.name = "nt"
    os.environ["BIOAUTH_ENABLE_UI_SOUNDS"] = "1"
    os.environ.pop("BIOAUTH_DISABLE_UI_SOUNDS", None)
    try:
        assert module.play_button_sound("warning") is True
        assert calls == [("SystemExclamation", 3)]
    finally:
        module.os.name = old_os_name
        if old_winsound is None:
            sys.modules.pop("winsound", None)
        else:
            sys.modules["winsound"] = old_winsound
        _restore_env("BIOAUTH_ENABLE_UI_SOUNDS", old_enable)
        _restore_env("BIOAUTH_DISABLE_UI_SOUNDS", old_disable)


def test_disable_env_overrides_developer_enable_env() -> None:
    module = importlib.import_module("ui_sounds")
    old_os_name = module.os.name
    old_winsound = sys.modules.get("winsound")
    old_enable = os.environ.get("BIOAUTH_ENABLE_UI_SOUNDS")
    old_disable = os.environ.get("BIOAUTH_DISABLE_UI_SOUNDS")
    calls = []
    fake = types.SimpleNamespace(
        SND_ALIAS=1,
        SND_ASYNC=2,
        PlaySound=lambda alias, flags: calls.append((alias, flags)),
    )
    sys.modules["winsound"] = fake  # type: ignore[assignment]
    module.os.name = "nt"
    os.environ["BIOAUTH_ENABLE_UI_SOUNDS"] = "1"
    os.environ["BIOAUTH_DISABLE_UI_SOUNDS"] = "1"
    try:
        assert module.play_button_sound("warning") is False
        assert calls == []
    finally:
        module.os.name = old_os_name
        if old_winsound is None:
            sys.modules.pop("winsound", None)
        else:
            sys.modules["winsound"] = old_winsound
        _restore_env("BIOAUTH_ENABLE_UI_SOUNDS", old_enable)
        _restore_env("BIOAUTH_DISABLE_UI_SOUNDS", old_disable)


def test_backend_play_button_sound_respects_mute_setting() -> None:
    settings_mixin = importlib.import_module("bridge.settings_mixin")
    calls = []
    original = settings_mixin.play_button_sound
    settings_mixin.play_button_sound = lambda role="neutral": calls.append(role) or True
    try:
        bridge = settings_mixin.SettingsMixin()
        bridge._mute_button_sounds = True
        bridge.playButtonSound("neutral")
        assert calls == []
    finally:
        settings_mixin.play_button_sound = original


def test_backend_play_button_sound_calls_helper_only_when_unmuted() -> None:
    settings_mixin = importlib.import_module("bridge.settings_mixin")
    calls = []
    original = settings_mixin.play_button_sound
    settings_mixin.play_button_sound = lambda role="neutral": calls.append(role) or True
    try:
        bridge = settings_mixin.SettingsMixin()
        bridge._mute_button_sounds = False
        bridge.playButtonSound("neutral")
        assert calls == ["neutral"]
    finally:
        settings_mixin.play_button_sound = original


def test_qml_sound_calls_are_guarded_by_backend_muted_property() -> None:
    qml_files = [
        ROOT / "qml" / "components" / "AppButton.qml",
        ROOT / "qml" / "components" / "ChoiceChip.qml",
        ROOT / "qml" / "components" / "SelectableInfoCard.qml",
    ]
    for path in qml_files:
        source = path.read_text(encoding="utf-8")
        assert "backend.buttonSoundsMuted !== true" in source
        assert "backend.playButtonSound" in source


if __name__ == "__main__":
    test_ui_sounds_does_not_call_winsound_by_default()
    test_ui_sounds_can_be_enabled_only_by_developer_env()
    test_disable_env_overrides_developer_enable_env()
    test_backend_play_button_sound_respects_mute_setting()
    test_backend_play_button_sound_calls_helper_only_when_unmuted()
    test_qml_sound_calls_are_guarded_by_backend_muted_property()
    print("6 focused UI sound mute contract tests passed", flush=True)
    os._exit(0)
