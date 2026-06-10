from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bridge.refresh_dashboard_helpers as dashboard_helpers
import bridge.refresh_shadow_helpers as shadow_helpers


class _Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def time(self) -> float:
        return self.value

    def perf_counter(self) -> float:
        return self.value


class _Facade:
    def __init__(self) -> None:
        self.time = _Clock()
        self.calls = 0

    def get_shadow_status(self, user_id: str) -> dict:
        self.calls += 1
        return {"phase": "collecting", "ready": False, "suggestion_pending": False}

    @staticmethod
    def slugify_username(value: str) -> str:
        return str(value or "").strip().lower()


class _ShadowBridge:
    SHADOW_STATUS_REFRESH_SEC = 12.0
    SHADOW_BACKLOG_SCAN_IDLE_SEC = 30.0

    def __init__(self) -> None:
        self._shadow_automation_paused = False
        self._pending_shadow_suggestion = False
        self._shadow_worker_running = False
        self._last_shadow_status_refresh_at = 0.0
        self._last_shadow_backlog_scan_at = 0.0
        self._dashboard_visible = True
        self._runtime_state = {}
        self._shadow_status = {"phase": "collecting", "ready": False, "suggestion_pending": False}
        self._current_user = {"user_id": "alice"}


def test_legacy_shadow_polling_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("BIOAUTH_ENABLE_LEGACY_SHADOW_STATUS_POLLING", raising=False)
    monkeypatch.delenv("BIOAUTH_ENABLE_LEGACY_SHADOW_BACKLOG_SCAN", raising=False)
    bridge = _ShadowBridge()
    assert shadow_helpers.should_refresh_shadow_status(bridge) is False
    assert shadow_helpers.should_scan_shadow_backlog(bridge) is False


def test_legacy_shadow_polling_can_be_enabled_for_research(monkeypatch) -> None:
    monkeypatch.setenv("BIOAUTH_ENABLE_LEGACY_SHADOW_STATUS_POLLING", "1")
    monkeypatch.setenv("BIOAUTH_ENABLE_LEGACY_SHADOW_BACKLOG_SCAN", "1")
    old_facade = shadow_helpers._facade
    facade = _Facade()
    shadow_helpers._facade = lambda: facade
    try:
        bridge = _ShadowBridge()
        assert shadow_helpers.should_refresh_shadow_status(bridge) is True
        assert shadow_helpers.should_scan_shadow_backlog(bridge) is True
    finally:
        shadow_helpers._facade = old_facade


def test_dashboard_production_observation_uses_signature_and_cooldown() -> None:
    old_facade = dashboard_helpers._facade
    facade = _Facade()
    dashboard_helpers._facade = lambda: facade
    try:
        bridge = type("B", (), {})()
        bridge._training_in_progress = False
        bridge._pending_monitor_start = False
        bridge._pending_logger_start = False
        profile = {"production_approval_state": {"status": "pending", "candidate_status": "approved_for_shadow", "reason_code": "partial"}}
        assert dashboard_helpers._should_observe_production_approval_state(bridge, profile) is True
        assert dashboard_helpers._should_observe_production_approval_state(bridge, profile) is False
        facade.time.value += 16.0
        assert dashboard_helpers._should_observe_production_approval_state(bridge, profile) is True
    finally:
        dashboard_helpers._facade = old_facade


def test_dashboard_production_observation_runs_when_signature_changes() -> None:
    old_facade = dashboard_helpers._facade
    facade = _Facade()
    dashboard_helpers._facade = lambda: facade
    try:
        bridge = type("B", (), {})()
        bridge._training_in_progress = False
        bridge._pending_monitor_start = False
        bridge._pending_logger_start = False
        first = {"production_approval_state": {"status": "pending", "candidate_status": "approved_for_shadow", "reason_code": "partial"}}
        second = {"production_approval_state": {"status": "approved", "candidate_status": "approved_for_production", "reason_code": "ready"}}
        assert dashboard_helpers._should_observe_production_approval_state(bridge, first) is True
        assert dashboard_helpers._should_observe_production_approval_state(bridge, second) is True
    finally:
        dashboard_helpers._facade = old_facade
