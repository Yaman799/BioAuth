from __future__ import annotations

import importlib
import pathlib
import sys
import os

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_ui_notifications_module_exports_startup_import_contract() -> None:
    module = importlib.import_module("ui_notifications")
    assert hasattr(module, "show_taskbar_notification")
    assert "show_taskbar_notification" in getattr(module, "__all__", [])


def test_taskbar_notification_non_windows_is_non_blocking() -> None:
    module = importlib.import_module("ui_notifications")
    result = module.show_taskbar_notification("BioAuth", "Startup notification smoke")
    assert result in (True, False)
    if module.os.name != "nt":
        assert result is False


def test_balloon_script_does_not_include_raw_behavioral_payload_fields() -> None:
    module = importlib.import_module("ui_notifications")
    script = module._build_balloon_script("BioAuth", "Safe status", timeout_ms=1000, level="warning")
    lowered = script.lower()
    assert "keystroke" not in lowered
    assert "mouse_events" not in lowered
    assert "Safe status" in script


if __name__ == "__main__":
    test_ui_notifications_module_exports_startup_import_contract()
    test_taskbar_notification_non_windows_is_non_blocking()
    test_balloon_script_does_not_include_raw_behavioral_payload_fields()
    print("3 focused UI notification import contract tests passed", flush=True)
    os._exit(0)
