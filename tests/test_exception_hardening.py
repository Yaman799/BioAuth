from __future__ import annotations

import subprocess
import sys
import types


def _install_pyside6_stub() -> None:
    if "PySide6" in sys.modules:
        return
    core = types.ModuleType("PySide6.QtCore")
    core.QLocale = type("QLocale", (), {"name": lambda self: "en_US"})
    core.QObject = object
    core.Property = lambda *args, **kwargs: (lambda func: func)
    core.QTimer = object
    core.QUrl = type("QUrl", (), {"fromLocalFile": staticmethod(lambda path: path)})
    core.Signal = lambda *args, **kwargs: None
    core.Slot = lambda *args, **kwargs: (lambda func: func)
    gui = types.ModuleType("PySide6.QtGui")
    gui.QDesktopServices = type("QDesktopServices", (), {"openUrl": staticmethod(lambda *_args, **_kwargs: True)})
    gui.QIcon = object
    qml = types.ModuleType("PySide6.QtQml")
    qml.QQmlApplicationEngine = object
    widgets = types.ModuleType("PySide6.QtWidgets")
    widgets.QApplication = object
    widgets.QSystemTrayIcon = object
    widgets.QMenu = object
    pkg = types.ModuleType("PySide6")
    pkg.QtCore = core
    pkg.QtGui = gui
    pkg.QtQml = qml
    pkg.QtWidgets = widgets
    sys.modules["PySide6"] = pkg
    sys.modules["PySide6.QtCore"] = core
    sys.modules["PySide6.QtGui"] = gui
    sys.modules["PySide6.QtQml"] = qml
    sys.modules["PySide6.QtWidgets"] = widgets


_install_pyside6_stub()

from unittest.mock import patch

import monitor
from bridge.session_mixin import SessionMixin


class _DummyBridge(SessionMixin):
    def __init__(self):
        self._running_processes = {}
        self._pending_monitor_start = False
        self._pending_monitor_user_id = None
        self._monitor_start_deadline = 0.0
        self._monitor_launch_attempted = False
        self._monitor_start_failed = False


class _HangingProc:
    def __init__(self):
        self.killed = False
        self.terminated = False

    def poll(self):
        return None if not self.killed else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        if not self.killed:
            raise subprocess.TimeoutExpired(cmd="monitor", timeout=timeout)
        return 0

    def kill(self):
        self.killed = True


def test_stop_stale_monitor_forces_kill_after_timeout() -> None:
    bridge = _DummyBridge()
    proc = _HangingProc()
    bridge._running_processes["monitor"] = proc

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target
        def start(self):
            if callable(self._target):
                self._target()

    with patch("bridge.session_mixin.request_stop"), patch("bridge.session_mixin.threading.Thread", _ImmediateThread):
        stopped = bridge._stop_stale_monitor(wait_timeout=0.01)

    assert stopped is True
    assert proc.terminated is True
    assert proc.killed is True


def test_monitor_runtime_error_updates_shared_state_and_log(monkeypatch) -> None:
    state = {
        "session_id": "sess-1",
        "user_id": "alice",
        "session_kind": "protected",
        "decision": "pending",
        "active": True,
        "started_at": 10.0,
        "started_at_text": "2026-04-11 12:00:00",
    }
    writes = []
    logs = []
    sleep_calls = {"count": 0}

    def fake_read_session_state(default=None):
        return dict(state)

    def fake_write_session_state(data):
        state.clear()
        state.update(dict(data))
        writes.append(dict(data))

    def fake_sleep_with_stop(_total_seconds: float, step_seconds: float = 0.5) -> bool:
        sleep_calls["count"] += 1
        return sleep_calls["count"] == 1

    def fake_predict_runtime(_runtime):
        raise ValueError("bad window payload")

    monkeypatch.setattr(monitor, "clear_stop", lambda _name: None)
    monkeypatch.setattr(monitor, "read_session_state", fake_read_session_state)
    monkeypatch.setattr(monitor, "write_session_state", fake_write_session_state)
    monkeypatch.setattr(monitor, "_load_runtime_model", lambda: {"model": object(), "metadata": {"ready": True}})
    monkeypatch.setattr(monitor, "load_settings", lambda: {"monitor_interval_sec": 5})
    monkeypatch.setattr(monitor, "_sleep_with_stop", fake_sleep_with_stop)
    monkeypatch.setattr(monitor, "_predict_runtime", fake_predict_runtime)
    monkeypatch.setattr(monitor, "append_log", lambda entry: logs.append(dict(entry)))

    monitor.monitor()

    assert any(item.get("status") == "monitor_runtime_error" for item in writes)
    assert writes[-1]["active"] is False
    assert writes[-1]["monitor_error"].startswith("runtime_iteration_failed")
    assert any(entry.get("status") == "monitor_runtime_error" for entry in logs)
    assert logs[-1]["error"].startswith("runtime_iteration_failed")
