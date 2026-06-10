from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "qml"
USER_QML = [
    QML / "UserShell.qml",
    QML / "pages" / "user" / "UserHomePage.qml",
    QML / "pages" / "user" / "UserActivityPage.qml",
    QML / "pages" / "user" / "UserFaceConfirmationPage.qml",
    QML / "pages" / "user" / "UserModelUpdatePage.qml",
    QML / "pages" / "user" / "UserProtectionPage.qml",
    QML / "pages" / "user" / "UserSettingsPage.qml",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _install_fake_pyside6() -> None:
    if "PySide6" in sys.modules:
        return
    pyside6 = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")
    qtqml = types.ModuleType("PySide6.QtQml")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class _QObject:
        def __init__(self, *args, **kwargs):
            pass

    class _Signal:
        def __init__(self, *args, **kwargs):
            pass

        def emit(self, *args, **kwargs):
            return None

        def connect(self, *args, **kwargs):
            return None

    def _decorator(*args, **kwargs):
        def _wrap(func):
            return func
        return _wrap

    class _QTimer:
        @staticmethod
        def singleShot(*args, **kwargs):
            return None

    class _QUrl:
        def __init__(self, value=""):
            self.value = value

    class _QCoreApplication:
        @staticmethod
        def translate(_context, text):
            return text

    class _QLocale:
        @staticmethod
        def system():
            return _QLocale()

        def name(self):
            return "en_US"

    class _QDesktopServices:
        @staticmethod
        def openUrl(*args, **kwargs):
            return True

    class _QtObject:
        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    qtcore.QObject = _QObject
    qtcore.Property = lambda *args, **kwargs: property(args[-1]) if args and callable(args[-1]) else None
    qtcore.QTimer = _QTimer
    qtcore.QUrl = _QUrl
    qtcore.QCoreApplication = _QCoreApplication
    qtcore.QLocale = _QLocale
    qtcore.QRunnable = _QtObject
    qtcore.QThreadPool = _QtObject
    qtcore.Qt = _QtObject()
    qtcore.Signal = _Signal
    qtcore.Slot = _decorator
    qtgui.QDesktopServices = _QDesktopServices
    qtgui.QIcon = _QtObject
    qtqml.QQmlApplicationEngine = _QtObject
    qtwidgets.QApplication = _QtObject
    qtwidgets.QMenu = _QtObject
    qtwidgets.QSystemTrayIcon = _QtObject
    pyside6.QtCore = qtcore
    pyside6.QtGui = qtgui
    pyside6.QtQml = qtqml
    pyside6.QtWidgets = qtwidgets
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtQml"] = qtqml
    sys.modules["PySide6.QtWidgets"] = qtwidgets


def _session_mixin_module():
    _install_fake_pyside6()
    import bridge.session_mixin as session_mixin
    return importlib.reload(session_mixin)


class _BridgeForUserActionTests:
    authenticated = True
    startEnrollmentLoggerUnavailableReason = "Learning in progress"
    stopEnrollmentLoggerUnavailableReason = "Learning is not running"

    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self.statuses: list[tuple[str, str]] = []
        self.can_start_enrollment = False
        self.can_stop_enrollment = False
        self.can_start_protection = False
        self.can_stop_protection = False
        self.canTrain = False
        self.trainingBlockedReason = "Training not ready."
        self._training_in_progress = False

    def _t(self, key: str, **kwargs) -> str:
        messages = {
            "user_action_unavailable": "Action unavailable right now.",
            "user_action_start_enrollment_requested": "Learning start requested.",
            "user_action_stop_enrollment_requested": "Learning stop requested.",
            "user_action_start_protection_requested": "Protection start requested.",
            "user_action_stop_protection_requested": "Protection stop requested.",
            "user_action_train_profile_requested": "Protection model training requested.",
            "user_action_refresh_requested": "Status refresh requested.",
            "training_running": "Training is already running.",
            "user_action_open_settings_requested": "Settings can be opened now.",
            "user_protection_start_unavailable_tooltip": "Protection not ready yet.",
            "user_protection_stop_unavailable_tooltip": "No protection session is running.",
        }
        return messages.get(key, key).format(**kwargs)

    def _set_status(self, message: str, tone: str = "info") -> bool:
        self.statuses.append((message, tone))
        return True

    def _can_start_enrollment_logger(self) -> bool:
        return self.can_start_enrollment

    def _can_stop_enrollment_logger(self) -> bool:
        return self.can_stop_enrollment

    def _can_start_production_monitor(self) -> bool:
        return self.can_start_protection

    def requestRefresh(self, reason: str, force: bool) -> None:
        self.calls.append(("refresh", (reason, force)))


def _bridge_instance(session_mixin_module):
    class Bridge(session_mixin_module.SessionMixin, _BridgeForUserActionTests):
        pass
    return Bridge()


def test_user_home_qml_uses_safe_action_wrapper_only() -> None:
    qml = _read(QML / "pages" / "user" / "UserHomePage.qml")
    assert qml.count("backend.requestUserHomeAction(") == 5
    for action in ["start_enrollment", "stop_enrollment", "start_protection", "stop_protection", "train_profile"]:
        assert f'backend.requestUserHomeAction("{action}")' in qml
    for forbidden in [
        "backend.startEnrollment(",
        "backend.stopEnrollmentLogger(",
        "backend.startProtected(",
        "backend.stopProductionMonitor(",
        "backend.stopCurrentSession(",
        "backend.requestUserStartLearning(",
        "backend.requestUserStopLearning(",
        "backend.requestUserStartProtection(",
        "backend.requestUserStopProtection(",
    ]:
        assert forbidden not in qml


def test_user_facing_qml_has_no_direct_unsafe_runtime_slot_calls() -> None:
    combined = "\n".join(_read(path) for path in USER_QML)
    for forbidden in [
        "backend.startEnrollment(",
        "backend.stopEnrollmentLogger(",
        "backend.startProtected(",
        "backend.stopProductionMonitor(",
        "backend.stopCurrentSession(",
        "backend.trainProfile(",
        "backend.approveProductionModelSwitch(",
    ]:
        assert forbidden not in combined


def test_safe_wrapper_allows_known_action_after_state_validation(monkeypatch) -> None:
    session_mixin = _session_mixin_module()
    bridge = _bridge_instance(session_mixin)
    bridge.can_start_enrollment = True
    monkeypatch.setattr(session_mixin.session_runtime_helpers, "start_enrollment", lambda self: self.calls.append(("start_enrollment", None)))

    result = bridge.requestUserHomeAction("start_enrollment")

    assert result["ok"] is True
    assert result["action"] == "start_enrollment"
    assert result["message"] == "Learning start requested."
    assert bridge.calls == [("start_enrollment", None)]


def test_safe_wrapper_allows_user_train_profile_after_training_gate(monkeypatch) -> None:
    session_mixin = _session_mixin_module()
    bridge = _bridge_instance(session_mixin)
    bridge.canTrain = True
    monkeypatch.setattr(
        session_mixin.session_training_helpers,
        "train_profile",
        lambda self, auto_training=False: self.calls.append(("train_profile", {"auto_training": auto_training})) or True,
    )

    result = bridge.requestUserHomeAction("train_profile")

    assert result["ok"] is True
    assert result["action"] == "train_profile"
    assert result["message"] == "Protection model training requested."
    assert bridge.calls == [("train_profile", {"auto_training": False})]


def test_safe_wrapper_denies_user_train_profile_when_gate_is_closed(monkeypatch) -> None:
    session_mixin = _session_mixin_module()
    bridge = _bridge_instance(session_mixin)
    bridge.canTrain = False
    bridge.trainingBlockedReason = "Need more trusted sessions."
    monkeypatch.setattr(
        session_mixin.session_training_helpers,
        "train_profile",
        lambda self, auto_training=False: self.calls.append(("train_profile", {"auto_training": auto_training})) or True,
    )

    result = bridge.requestUserHomeAction("train_profile")

    assert result["ok"] is False
    assert result["action"] == "train_profile"
    assert result["message"] == "Need more trusted sessions."
    assert bridge.calls == []
    assert bridge.statuses[-1] == ("Need more trusted sessions.", "warn")


def test_safe_wrapper_denies_unknown_action_without_side_effect(monkeypatch) -> None:
    session_mixin = _session_mixin_module()
    bridge = _bridge_instance(session_mixin)
    monkeypatch.setattr(session_mixin.session_runtime_helpers, "start_enrollment", lambda self: self.calls.append(("start_enrollment", None)))

    result = bridge.requestUserHomeAction("start_shadow")

    assert result["ok"] is False
    assert result["action"] == "start_shadow"
    assert result["message"] == "Action unavailable right now."
    assert result["user_safe_reason"] == "Action unavailable right now."
    assert bridge.calls == []
    assert bridge.statuses[-1] == ("Action unavailable right now.", "warn")


def test_safe_wrapper_denies_action_when_state_is_unsafe(monkeypatch) -> None:
    session_mixin = _session_mixin_module()
    bridge = _bridge_instance(session_mixin)
    bridge.can_start_protection = False
    monkeypatch.setattr(session_mixin.session_runtime_helpers, "start_protected_session", lambda self, **kwargs: self.calls.append(("start_protected", kwargs)))

    result = bridge.requestUserHomeAction("start_protection")

    assert result["ok"] is False
    assert result["action"] == "start_protection"
    assert result["message"] == "Protection not ready yet."
    assert bridge.calls == []
    assert bridge.statuses[-1] == ("Protection not ready yet.", "warn")


def test_safe_wrapper_does_not_bypass_protection_readiness_gate(monkeypatch) -> None:
    session_mixin = _session_mixin_module()
    bridge = _bridge_instance(session_mixin)
    monkeypatch.setattr(session_mixin.session_runtime_helpers, "start_protected_session", lambda self, **kwargs: self.calls.append(("start_protected", kwargs)))

    denied = bridge.requestUserHomeAction("start_protection")
    assert denied["ok"] is False
    assert bridge.calls == []

    bridge.can_start_protection = True
    allowed = bridge.requestUserHomeAction("start_protection")
    assert allowed["ok"] is True
    assert bridge.calls == [("start_protected", {"auto_resume": False, "trigger_refresh": True})]


def test_safe_wrapper_supports_non_runtime_allowed_actions() -> None:
    session_mixin = _session_mixin_module()
    bridge = _bridge_instance(session_mixin)

    refresh_result = bridge.requestUserHomeAction("refresh_status")
    settings_result = bridge.requestUserHomeAction("open_settings")

    assert refresh_result["ok"] is True
    assert settings_result["ok"] is True
    assert bridge.calls == [("refresh", ("user_home_action", True))]
