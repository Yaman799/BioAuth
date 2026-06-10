from __future__ import annotations

import importlib
import os
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_ui_sounds_module_exports_startup_import_contract() -> None:
    module = importlib.import_module("ui_sounds")
    assert hasattr(module, "play_button_sound")
    assert "play_button_sound" in getattr(module, "__all__", [])


def test_button_sound_non_windows_is_non_blocking() -> None:
    module = importlib.import_module("ui_sounds")
    result = module.play_button_sound("neutral")
    assert result in (True, False)
    if module.os.name != "nt":
        assert result is False


def test_button_sound_can_be_disabled_without_import_side_effects() -> None:
    module = importlib.import_module("ui_sounds")
    old_value = os.environ.get("BIOAUTH_DISABLE_UI_SOUNDS")
    os.environ["BIOAUTH_DISABLE_UI_SOUNDS"] = "1"
    try:
        assert module.play_button_sound("success") is False
    finally:
        if old_value is None:
            os.environ.pop("BIOAUTH_DISABLE_UI_SOUNDS", None)
        else:
            os.environ["BIOAUTH_DISABLE_UI_SOUNDS"] = old_value


def test_button_sound_windows_backend_is_silent_by_default() -> None:
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
        if old_enable is None:
            os.environ.pop("BIOAUTH_ENABLE_UI_SOUNDS", None)
        else:
            os.environ["BIOAUTH_ENABLE_UI_SOUNDS"] = old_enable
        if old_disable is None:
            os.environ.pop("BIOAUTH_DISABLE_UI_SOUNDS", None)
        else:
            os.environ["BIOAUTH_DISABLE_UI_SOUNDS"] = old_disable


def test_button_sound_windows_backend_is_developer_opt_in() -> None:
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
        if old_enable is None:
            os.environ.pop("BIOAUTH_ENABLE_UI_SOUNDS", None)
        else:
            os.environ["BIOAUTH_ENABLE_UI_SOUNDS"] = old_enable
        if old_disable is None:
            os.environ.pop("BIOAUTH_DISABLE_UI_SOUNDS", None)
        else:
            os.environ["BIOAUTH_DISABLE_UI_SOUNDS"] = old_disable


def test_sound_module_does_not_reference_raw_behavioral_payload_fields() -> None:
    source = (ROOT / "ui_sounds.py").read_text(encoding="utf-8").lower()
    for forbidden in ["keystroke", "mouse_events", "keyboard_events", "raw_key", "raw_mouse"]:
        assert forbidden not in source


if __name__ == "__main__":
    test_ui_sounds_module_exports_startup_import_contract()
    test_button_sound_non_windows_is_non_blocking()
    test_button_sound_can_be_disabled_without_import_side_effects()
    test_button_sound_windows_backend_is_silent_by_default()
    test_button_sound_windows_backend_is_developer_opt_in()
    test_sound_module_does_not_reference_raw_behavioral_payload_fields()
    print("6 focused UI sound import contract tests passed", flush=True)
    os._exit(0)
