from __future__ import annotations

import importlib
from pathlib import Path


def test_root_wrappers_and_desktop_bridge_exports_remain_available() -> None:
    for name in ("desktop_app", "logger", "monitor", "model_training", "model_inference", "paths", "security", "app_settings"):
        importlib.import_module(name)

    desktop = importlib.import_module("bioauth.app.desktop_app_impl")
    assert hasattr(desktop, "AppBridge")
    assert callable(desktop.main)


def test_desktop_self_relaunch_guards_stay_before_qt_import() -> None:
    source = Path("desktop_app.py").read_text(encoding="utf-8")
    assert source.index("guard_desktop_system_python_child") < source.index("import_module(\"bioauth.app.desktop_app_impl\")")
    assert source.index("enter_root_wrapper") < source.index("import_module(\"bioauth.app.desktop_app_impl\")")


def test_desktop_shell_keeps_qml_backend_markers() -> None:
    source = Path("src/bioauth/app/desktop_app_impl.py").read_text(encoding="utf-8")
    assert "class AppBridge(AuthMixin, SessionMixin, SettingsMixin, RefreshMixin" in source
    assert "QQmlApplicationEngine" in source
    assert "backend" in source
