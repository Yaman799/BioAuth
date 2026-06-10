from __future__ import annotations

import time
from pathlib import Path

import bridge.refresh_dashboard_helpers as dashboard_helpers
import bridge.refresh_runtime_helpers as runtime_helpers
from tests.test_dashboard_async_idle_refresh import AsyncDashboardBridge, CapturingThread, _install_facade


def _state(bridge: AsyncDashboardBridge):
    return runtime_helpers.dashboard_state_payload(bridge)


def test_dashboard_loading_state_transitions_emit_signal(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")
    assert _state(bridge)["loading"] is False

    snapshot = dashboard_helpers.dashboard_snapshot(bridge, "alice")

    assert snapshot == {"profile": {}, "sessions": []}
    state = _state(bridge)
    assert state["loading"] is True
    assert state["updating"] is True
    assert bridge.dashboardStateChanged.count >= 1
    assert len(CapturingThread.targets) == 1


def test_dashboard_loading_state_clears_on_worker_success(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")
    result = {"profile": {"session_count": 1, "ready": True}, "sessions": [{"session_id": "s1"}]}
    monkeypatch.setattr(dashboard_helpers, "_compute_dashboard_snapshot", lambda self, user_id: result)

    dashboard_helpers.dashboard_snapshot(bridge, "alice")
    assert _state(bridge)["loading"] is True

    CapturingThread.targets.pop(0)()
    dashboard_helpers.dashboard_snapshot(bridge, "alice")

    state = _state(bridge)
    assert state["loading"] is False
    assert state["updating"] is False
    assert state["stale"] is False
    assert state["lastRefreshError"] == ""
    assert state["lastSnapshotDurationMs"] >= 0


def test_dashboard_loading_state_clears_on_worker_failure(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")

    def fail_compute(self, user_id):
        raise RuntimeError("boom from dashboard worker")

    monkeypatch.setattr(dashboard_helpers, "_compute_dashboard_snapshot", fail_compute)
    dashboard_helpers.dashboard_snapshot(bridge, "alice")
    assert _state(bridge)["loading"] is True

    CapturingThread.targets.pop(0)()
    dashboard_helpers.dashboard_snapshot(bridge, "alice")

    state = _state(bridge)
    assert state["loading"] is False
    assert state["updating"] is False
    assert "boom" in state["lastRefreshError"]
    assert CapturingThread.targets == []


def test_refresh_duration_updates_without_clearing_snapshot_error(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")
    runtime_helpers.set_dashboard_state(bridge, last_refresh_error="snapshot failed")
    bridge._update_dashboard = lambda: None

    runtime_helpers.request_refresh(bridge, reason="runtime:timer", force=True)

    state = _state(bridge)
    assert state["lastRefreshDurationMs"] >= 0
    assert state["lastRefreshReason"] == "runtime:timer"
    assert state["lastRefreshError"] == "snapshot failed"


def test_history_loading_state_is_visible_and_clears_on_success(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")
    result = {"profile": {"session_count": 2}, "sessions": [{"session_id": "s1"}, {"session_id": "s2"}]}
    monkeypatch.setattr(dashboard_helpers, "_compute_full_history_snapshot", lambda self, user_id: result)

    dashboard_helpers.load_full_history(bridge, force=True)
    assert _state(bridge)["historyLoading"] is True
    assert len(CapturingThread.targets) >= 1

    while CapturingThread.targets:
        CapturingThread.targets.pop(0)()
    assert bridge._dashboard_full_history_refresh_inflight is False
    dashboard_helpers.update_dashboard(bridge)

    state = _state(bridge)
    assert state["historyLoading"] is False
    assert state["historyLoaded"] is True
    assert bridge._sessions == result["sessions"]


def test_qml_backend_contract_mentions_dashboard_state_without_new_lifecycle_calls():
    app_shell = Path("qml/AppShell.qml").read_text(encoding="utf-8")
    overview = Path("qml/pages/OverviewPage.qml").read_text(encoding="utf-8")
    history = Path("qml/pages/HistoryPage.qml").read_text(encoding="utf-8")
    desktop = Path("desktop_app.py").read_text(encoding="utf-8")

    assert "dashboardStateChanged = Signal()" in desktop
    assert "def dashboardState" in desktop
    assert "backend.dashboardState" in app_shell
    assert "backend.dashboardState" in overview
    assert "backend.dashboardState" in history
    assert "backend.requestRefresh" not in app_shell
    assert "backend.refreshNow" not in app_shell
    assert "backend.requestRefresh" not in overview
    assert "backend.refreshNow" not in overview
