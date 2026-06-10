from __future__ import annotations

import sys
import types
from unittest.mock import patch


def _install_fake_pyside6() -> None:
    if "PySide6" in sys.modules:
        return

    pyside6 = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")
    qtqml = types.ModuleType("PySide6.QtQml")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

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
            self._interval = 0

        def setInterval(self, value):
            self._interval = int(value)

        def interval(self):
            return self._interval

        def start(self):
            pass

    class _QLocale:
        def name(self):
            return "en_US"

    qtcore.QObject = object
    qtcore.QLocale = _QLocale
    qtcore.Property = _property
    qtcore.QTimer = _QTimer
    qtcore.QUrl = str
    qtcore.Signal = _Signal
    qtcore.Slot = _slot

    qtgui.QDesktopServices = type("QDesktopServices", (), {"openUrl": staticmethod(lambda *args, **kwargs: True)})
    qtgui.QIcon = type("QIcon", (), {})
    qtqml.QQmlApplicationEngine = type("QQmlApplicationEngine", (), {})
    qtwidgets.QApplication = type("QApplication", (), {})
    qtwidgets.QSystemTrayIcon = type("QSystemTrayIcon", (), {"isSystemTrayAvailable": staticmethod(lambda: False)})
    qtwidgets.QMenu = type("QMenu", (), {"addAction": lambda self, *args, **kwargs: types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda *a, **k: None))})

    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtQml"] = qtqml
    sys.modules["PySide6.QtWidgets"] = qtwidgets


_install_fake_pyside6()

from bridge.refresh_mixin import RefreshMixin
from bridge.shared import STRINGS, translate_backend_result
import monitor


class DummySignal:
    def __init__(self):
        self.calls = []

    def emit(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class ArabicRefreshBridge(RefreshMixin):
    def __init__(self):
        self._language = "ar"
        self._current_user = {"user_id": "alice"}
        self._runtime_state = {
            "active": True,
            "session_id": "sess-1",
            "decision": "suspicious",
            "session_kind": "protected",
            "mode": "monitored",
            "alert_code": "high_risk_snapshot",
            "alert_title_key": "alert_high_risk_title",
            "alert_message_key": "alert_high_risk_msg",
            "alert_token": "high-risk-1",
        }
        self._last_alert_signature = None
        self.dialogMessage = DummySignal()

    def _t(self, key: str, **kwargs):
        text = STRINGS["ar"].get(key, STRINGS["en"].get(key, key))
        try:
            return text.format(**kwargs)
        except Exception:
            return text

    def _session_flow(self, state=None):
        return "protected_warning"


def test_translate_backend_result_prefers_message_key_for_arabic():
    result = {
        "ok": False,
        "message_key": "auth_invalid_credentials",
        "message": "Invalid username or password.",
    }
    assert translate_backend_result("ar", result) == "اسم المستخدم أو كلمة المرور غير صحيحين."


def test_runtime_state_view_exposes_translated_decision_label():
    bridge = ArabicRefreshBridge()
    view = bridge._build_runtime_state_view({"active": True, "decision": "intruder", "risk": 91, "avg_risk": 84, "session_kind": "protected", "mode": "monitored"})
    assert view["decisionText"] == "intruder"
    assert view["decisionLabel"] == "متطفل"


def test_handle_state_alerts_uses_alert_keys_not_raw_english():
    bridge = ArabicRefreshBridge()
    with patch("bridge.refresh_mixin.show_taskbar_notification", return_value=False):
        bridge._handle_state_alerts()
    assert bridge.dialogMessage.calls
    args, _kwargs = bridge.dialogMessage.calls[-1]
    assert args[0] == "شذوذ عالي الخطورة"
    assert args[1] == "رصد BioAuth شذوذًا أقوى وينتظر تأكيدًا إضافيًا واحدًا قبل قفل الجهاز."
    assert args[2] == "warning"


def test_monitor_escalation_returns_translation_keys():
    result = monitor._resolve_runtime_escalation(
        model_decision="intruder",
        recent_decisions=monitor.deque(["legit", "intruder"]),
        recent_risks=monitor.deque([20.0, 91.0]),
        risk=91,
        avg_risk=55.0,
        ml=1,
        elapsed=10.0,
        warnings=0,
        config={
            "runtime_high_risk_override": 95.0,
            "runtime_high_risk_min_elapsed_seconds": 20.0,
            "runtime_intruder_confirmations": 3,
            "runtime_intruder_avg3_threshold": 70.0,
            "runtime_intruder_avg4_ml_threshold": 70.0,
            "runtime_intruder_avg4_severe_threshold": 70.0,
            "runtime_alert_hits_threshold": 3,
            "runtime_alert_avg4_threshold": 70.0,
            "runtime_alert_ml_avg4_threshold": 70.0,
            "runtime_avg_risk_intruder_threshold": 80.0,
            "runtime_severe_hit_threshold": 90.0,
            "runtime_severe_hit_count": 2,
            "runtime_min_samples_for_action": 3,
            "runtime_min_lock_elapsed_seconds": 30.0,
            "runtime_secondary_lock_elapsed_seconds": 20.0,
            "runtime_warning_reset_avg_risk": 35.0,
            "runtime_warning_escalation_alert_hits": 2,
        },
    )
    assert result["alert_title_key"] == "alert_high_risk_title"
    assert result["alert_message_key"] == "alert_high_risk_msg"
