from __future__ import annotations

import importlib
from pathlib import Path


class _Bridge:
    REFRESH_REQUEST_DEBOUNCE_MS = 35

    def __init__(self) -> None:
        self._refresh_inflight = False
        self._timer_called = False
        self._current_user = None

    def _desired_refresh_interval_ms(self) -> int:
        return 1000


def test_background_refresh_request_is_queued_to_qt_thread(monkeypatch):
    runtime = importlib.import_module("bridge.refresh_runtime_helpers")
    bridge = _Bridge()
    queued = []

    monkeypatch.setattr(runtime, "is_qt_main_thread", lambda _owner: False)
    monkeypatch.setattr(
        runtime,
        "dispatch_to_qt_thread",
        lambda owner, callback, target_action="": queued.append((target_action, callback)) or True,
    )

    runtime.request_refresh(bridge, reason="supervisor:start", force=True)

    assert queued
    assert queued[0][0] == "request_refresh"


def test_refresh_timer_update_is_queued_to_qt_thread(monkeypatch):
    runtime = importlib.import_module("bridge.refresh_runtime_helpers")
    bridge = _Bridge()
    queued = []

    monkeypatch.setattr(runtime, "is_qt_main_thread", lambda _owner: False)
    monkeypatch.setattr(
        runtime,
        "dispatch_to_qt_thread",
        lambda owner, callback, target_action="": queued.append(target_action) or True,
    )

    runtime.update_refresh_timer(bridge, force=True)

    assert queued == ["update_refresh_timer"]


def test_supervisor_refresh_callback_does_not_call_timer_directly(monkeypatch):
    controller = importlib.import_module("bioauth_runtime.supervisor.protection_session_controller")
    calls = []

    class Bridge:
        def _update_refresh_timer(self, *, force=False):
            raise AssertionError("timer should be queued, not called directly")

    monkeypatch.setattr(
        controller,
        "dispatch_to_qt_thread",
        lambda owner, callback, target_action="": calls.append(target_action) or True,
    )

    controller._request_refresh(Bridge(), True, "supervisor:test")

    assert calls == ["supervisor_refresh:supervisor:test"]


def test_stop_supervisor_refresh_callback_is_queued(monkeypatch):
    stop_controller = importlib.import_module("bioauth_runtime.supervisor.stop_controller")
    calls = []

    class Bridge:
        def _update_refresh_timer(self, *, force=False):
            raise AssertionError("timer should be queued, not called directly")

    monkeypatch.setattr(
        stop_controller,
        "dispatch_to_qt_thread",
        lambda owner, callback, target_action="": calls.append(target_action) or True,
    )

    stop_controller._request_refresh(Bridge(), "supervisor:stop")

    assert calls == ["supervisor_stop_refresh:supervisor:stop"]


def test_dashboard_worker_refresh_no_direct_qtimer_singleshot():
    source = Path("bridge/refresh_dashboard_helpers.py").read_text(encoding="utf-8")
    assert "QTimer.singleShot" not in source
    assert "single_shot(" not in source
    assert "dispatch_to_qt_thread" in source


def test_refresh_runtime_uses_dispatch_before_qtimer_singleshot():
    source = Path("bridge/refresh_runtime_helpers.py").read_text(encoding="utf-8")
    request_index = source.index("def request_refresh")
    dispatch_index = source.index("dispatch_to_qt_thread", request_index)
    single_index = source.index("single_shot(", request_index)
    assert dispatch_index < single_index


def test_desktop_app_import_startup_smoke():
    importlib.import_module("desktop_app")


def test_app_bridge_installs_qt_thread_dispatcher_marker():
    source = Path("src/bioauth/app/desktop_app_impl.py").read_text(encoding="utf-8")
    assert "install_qt_thread_dispatcher(self)" in source
