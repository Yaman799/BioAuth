from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bridge.refresh_runtime_helpers as helpers


class _Signal:
    def __init__(self) -> None:
        self.count = 0

    def emit(self, *args, **kwargs) -> None:
        self.count += 1


class _Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def time(self) -> float:
        self.value += 0.01
        return self.value

    def monotonic(self) -> float:
        return self.time()


class _Logger:
    def warning(self, *args, **kwargs) -> None:
        return None


class _Facade:
    def __init__(self) -> None:
        self.time = _Clock()
        self.LOGGER = _Logger()

    def get_shadow_status(self, user_id: str) -> dict:
        return {"phase": "collecting", "ready": False, "suggestion_pending": False}


class _Bridge:
    def __init__(self, *, visible: bool) -> None:
        self._dashboard_visible = visible
        self._dashboard_visible_refresh_pending = False
        self._current_user = {"user_id": "alice"}
        self._runtime_state = {}
        self._profile = {}
        self._sessions = []
        self._refresh_inflight = False
        self._refresh_requested = False
        self._refresh_requested_force = False
        self._refresh_requested_reason = ""
        self._refresh_followup_scheduled = False
        self._pending_logger_start = False
        self._pending_monitor_start = False
        self._boot_autostart_pending = False
        self._training_in_progress = False
        self._shadow_worker_running = False
        self._dashboard_full_history_refresh_inflight = False
        self._dashboard_full_history_requested = False
        self._dashboard_snapshot_refresh_inflight = False
        self._history_sync_pending = False
        self._background = False
        self.dashboardStateChanged = _Signal()
        self.profileChanged = _Signal()
        self.sessionsChanged = _Signal()
        self.runtimeStateChanged = _Signal()
        self.controlsChanged = _Signal()
        self.autoEnrollmentChanged = _Signal()
        self.modelReadinessChanged = _Signal()
        self.statusChanged = _Signal()
        self.shadowChanged = _Signal()
        self.deepRuntimeChanged = _Signal()
        self.counts = {
            "cleanup": 0,
            "logger": 0,
            "monitor": 0,
            "dashboard": 0,
            "runtime_background": 0,
            "autostart": 0,
            "shadow_session": 0,
            "shadow_backlog": 0,
            "shadow_status": 0,
            "alerts": 0,
            "timer": 0,
        }

    def _cleanup_processes(self) -> None:
        self.counts["cleanup"] += 1

    def _maybe_finish_pending_logger_start(self) -> None:
        self.counts["logger"] += 1

    def _maybe_finish_pending_monitor_start(self) -> None:
        self.counts["monitor"] += 1

    def _update_dashboard(self) -> None:
        self.counts["dashboard"] += 1
        self._profile = {"ready": True}
        self.profileChanged.emit()

    def _active_state_for_current_user(self) -> dict:
        return {"active": True, "session_kind": "protected", "status": "active", "session_id": "s1"}

    def _build_runtime_state_view(self, state: dict) -> dict:
        self.counts["runtime_background"] += 1
        payload = dict(state)
        payload.setdefault("flow", "protected_active" if payload.get("active") else "idle")
        return payload

    def _refresh_deep_runtime_state(self) -> bool:
        return True

    def _maybe_auto_promote_production(self) -> bool:
        return False

    def _maybe_autostart_protection(self) -> bool:
        self.counts["autostart"] += 1
        return False

    def _maybe_finalize_passive_auto_enrollment(self) -> bool:
        return False

    def _maybe_start_auto_training(self) -> bool:
        return False

    def _maybe_process_shadow_session(self) -> None:
        self.counts["shadow_session"] += 1

    def _maybe_process_shadow_backlog(self) -> None:
        self.counts["shadow_backlog"] += 1

    def _consume_shadow_status_result(self):
        return None

    def _should_refresh_shadow_status(self) -> bool:
        return False

    def _queue_shadow_status_refresh(self, user_id: str) -> bool:
        return False

    def _check_shadow_suggestion(self, status: dict) -> None:
        return None

    def _refresh_shadow_status(self, status=None, force: bool = False) -> None:
        self.counts["shadow_status"] += 1

    def _handle_state_alerts(self) -> None:
        self.counts["alerts"] += 1

    def _maybe_resume_protection_after_unlock(self, state: dict) -> bool:
        return False

    def _update_refresh_timer(self, force: bool = False) -> None:
        self.counts["timer"] += 1

    def _session_flow(self, state=None) -> str:
        data = state if isinstance(state, dict) else self._runtime_state
        if data and data.get("active"):
            return "protected_active"
        return "idle"

    def _debug_trace(self, *args, **kwargs) -> None:
        return None


def _with_fake_facade(fn):
    old_facade = helpers._facade
    helpers._facade = lambda: _Facade()
    try:
        return fn()
    finally:
        helpers._facade = old_facade


def test_hidden_refresh_keeps_runtime_handlers_but_skips_dashboard_ui_signals() -> None:
    bridge = _Bridge(visible=False)

    def run() -> None:
        helpers._perform_refresh_now(bridge, reason="timer", force=True)

    _with_fake_facade(run)
    assert bridge.counts["cleanup"] == 1
    assert bridge.counts["logger"] == 1
    assert bridge.counts["monitor"] == 1
    assert bridge.counts["runtime_background"] == 1
    assert bridge.counts["autostart"] == 1
    assert bridge.counts["shadow_session"] == 1
    assert bridge.counts["shadow_backlog"] == 1
    assert bridge.counts["alerts"] == 1
    assert bridge.counts["dashboard"] == 0
    assert bridge.dashboardStateChanged.count == 0
    assert bridge.profileChanged.count == 0
    assert bridge.sessionsChanged.count == 0
    assert bridge._runtime_state.get("active") is True


def test_hidden_refresh_metadata_does_not_emit_dashboard_repaint_signal() -> None:
    bridge = _Bridge(visible=False)
    before = bridge.dashboardStateChanged.count
    helpers.set_dashboard_state(bridge, last_refresh_duration_ms=123, completed_at=1000.0, last_refresh_reason="timer")
    helpers.set_dashboard_state(bridge, last_refresh_duration_ms=124, completed_at=1001.0, last_refresh_reason="timer")
    assert bridge.dashboardStateChanged.count == before
    assert bridge._dashboard_last_refresh_duration_ms == 124


def test_visible_refresh_preserves_dashboard_behavior_and_emits_real_changes() -> None:
    bridge = _Bridge(visible=True)

    def run() -> None:
        helpers._perform_refresh_now(bridge, reason="timer", force=True)

    _with_fake_facade(run)
    assert bridge.counts["dashboard"] >= 1
    assert bridge.profileChanged.count >= 1
    assert bridge.dashboardStateChanged.count >= 1


def test_visibility_transition_requests_exactly_one_immediate_refresh() -> None:
    bridge = _Bridge(visible=True)
    calls: list[tuple[str, bool]] = []
    old_perform = helpers._perform_refresh_now

    def fake_perform(self, *, reason: str = "manual", force: bool = False, coalesced: bool = False) -> None:
        calls.append((reason, bool(force)))
        self._dashboard_visible_refresh_pending = False

    helpers._perform_refresh_now = fake_perform
    try:
        _with_fake_facade(lambda: helpers.set_dashboard_visible(bridge, False))
        _with_fake_facade(lambda: helpers.set_dashboard_visible(bridge, True))
        _with_fake_facade(lambda: helpers.set_dashboard_visible(bridge, True))
    finally:
        helpers._perform_refresh_now = old_perform
    assert calls == [("ui:dashboard_visible", True)]


def test_visibility_transition_coalesces_when_refresh_already_inflight() -> None:
    bridge = _Bridge(visible=False)
    bridge._refresh_inflight = True
    _with_fake_facade(lambda: helpers.set_dashboard_visible(bridge, True))
    assert bridge._refresh_requested is True
    assert bridge._refresh_requested_force is True
    assert "ui:dashboard_visible" in bridge._refresh_requested_reason
    assert bridge._refresh_followup_scheduled is True


def test_qml_notifies_backend_on_window_visibility_changes() -> None:
    main = (ROOT / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert "function dashboardWindowVisible()" in main
    assert "backend.setDashboardVisible(dashboardWindowVisible())" in main
    assert "onVisibleChanged: notifyDashboardVisibility()" in main
    assert "onVisibilityChanged: notifyDashboardVisibility()" in main
    assert "window.visibility !== Window.Minimized" in main
    assert "window.visibility !== Window.Hidden" in main


def test_bridge_exposes_dashboard_visibility_slot() -> None:
    mixin = (ROOT / "bridge" / "refresh_mixin.py").read_text(encoding="utf-8")
    runtime = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text(encoding="utf-8")
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    assert "@Slot(bool)" in mixin
    assert "def setDashboardVisible" in mixin
    assert "def set_dashboard_visible" in runtime
    assert "_dashboard_visible = True" in desktop
    assert "_dashboard_visible_refresh_pending" in desktop


def test_static_refresh_flow_gates_dashboard_not_runtime_logic() -> None:
    runtime = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text(encoding="utf-8")
    assert "if dashboard_visible:\n                self._update_dashboard()" in runtime
    assert "else:\n                update_runtime_background_state(self)" in runtime
    assert "self._maybe_finish_pending_logger_start()" in runtime
    assert "self._maybe_finish_pending_monitor_start()" in runtime
    assert "self._maybe_process_shadow_session()" in runtime
    assert "self._maybe_process_shadow_backlog()" in runtime
    assert "self._handle_state_alerts()" in runtime
    assert "and dashboard_visible" in runtime


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("8 focused dashboard visibility gated refresh tests passed", flush=True)
    os._exit(0)
