from __future__ import annotations

import importlib
import sys
import types


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

    class _QQmlApplicationEngine:
        pass

    qtqml.QQmlApplicationEngine = _QQmlApplicationEngine

    class _QApplication:
        def __init__(self, *args, **kwargs):
            pass

    class _QSystemTrayIcon:
        def __init__(self, *args, **kwargs):
            pass

        @staticmethod
        def isSystemTrayAvailable():
            return False

    class _QMenu:
        def addAction(self, *args, **kwargs):
            return types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda *a, **k: None))

    qtwidgets.QApplication = _QApplication
    qtwidgets.QSystemTrayIcon = _QSystemTrayIcon
    qtwidgets.QMenu = _QMenu

    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtQml"] = qtqml
    sys.modules["PySide6.QtWidgets"] = qtwidgets


def test_shared_does_not_export_stdlib_or_typing_surface():
    _install_fake_pyside6()
    import bridge.shared as shared

    shared = importlib.reload(shared)
    banned = {"os", "sys", "subprocess", "threading", "time", "webbrowser", "Path", "Any", "Dict", "List", "Optional"}
    assert banned.isdisjoint(set(shared.__all__))


def test_mixins_import_without_shared_stdlib_reexports():
    _install_fake_pyside6()
    import bridge.auth_mixin as auth_mixin
    import bridge.refresh_mixin as refresh_mixin
    import bridge.session_mixin as session_mixin
    import bridge.settings_mixin as settings_mixin

    auth_mixin = importlib.reload(auth_mixin)
    refresh_mixin = importlib.reload(refresh_mixin)
    session_mixin = importlib.reload(session_mixin)
    settings_mixin = importlib.reload(settings_mixin)

    assert auth_mixin.AuthMixin.__name__ == "AuthMixin"
    assert refresh_mixin.RefreshMixin.__name__ == "RefreshMixin"
    assert session_mixin.SessionMixin.__name__ == "SessionMixin"
    assert settings_mixin.SettingsMixin.__name__ == "SettingsMixin"
