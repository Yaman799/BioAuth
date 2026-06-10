from __future__ import annotations

import json
import os
import sys
import tempfile
import time as real_time
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).absolute().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridge import refresh_dashboard_helpers, session_runtime_helpers


class _Signal:
    def __init__(self) -> None:
        self.count = 0

    def emit(self, *args, **kwargs) -> None:
        self.count += 1


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = float(now)
        self.localtime = real_time.localtime
        self.strftime = real_time.strftime

    def time(self) -> float:
        return float(self.now)


class _Process:
    def __init__(self, alive: bool = True) -> None:
        self.alive = bool(alive)
        self.pid = 12345

    def poll(self):
        return None if self.alive else 0


class _Facade:
    def __init__(self, bridge, *, sessions_root: str, now: float = 1000.0) -> None:
        self.bridge = bridge
        self.os = os
        self.time = _Clock(now)
        self.stop_requests: list[str] = []
        self.clear_stops: list[str] = []
        self.invalidated = 0
        self._sessions_root = sessions_root

    def write_session_state(self, state):
        self.bridge.state = dict(state)
        self.bridge._runtime_state = dict(state)
        return True

    def read_session_state(self, default=None):
        return dict(getattr(self.bridge, "state", {}) or (default or {}))

    def request_stop(self, key: str):
        self.stop_requests.append(str(key))

    def clear_stop(self, key: str):
        self.clear_stops.append(str(key))

    def invalidate_session_discovery_cache(self):
        self.invalidated += 1

    def sessions_dir(self):
        return self._sessions_root


class _Bridge:
    def __init__(self, state: dict, *, now: float = 1000.0, sessions_root: str = "") -> None:
        self._current_user = {"user_id": "alice"}
        self.state = dict(state)
        self._runtime_state = dict(state)
        self._running_processes = {}
        self._pending_logger_start = False
        self._pending_monitor_start = False
        self._training_in_progress = False
        self._history_sync_pending = False
        self._history_sync_started_at = 0.0
        self._history_sync_hard_deadline = 0.0
        self._history_sync_status = "idle"
        self._history_sync_warning = ""
        self._passive_auto_enrollment_finalizing = False
        self._passive_finalization_observed_signature = ""
        self._passive_finalization_observed_since = 0.0
        self._last_passive_duplicate_finalization_log_key = ""
        self._last_passive_duplicate_finalization_log_at = 0.0
        self._last_passive_auto_enrollment_finalize_reason = ""
        self._last_passive_auto_enrollment_block_reason = ""
        self._active_live_session_dir = "live"
        self.statuses: list[tuple[str, str]] = []
        self.refreshes: list[tuple[str, bool]] = []
        self.debug_events: list[tuple[str, str, dict, str]] = []
        for name in (
            "autoEnrollmentChanged",
            "modelReadinessChanged",
            "runtimeStateChanged",
            "statusChanged",
            "controlsChanged",
            "sessionsChanged",
            "dashboardStateChanged",
        ):
            setattr(self, name, _Signal())
        self._facade = _Facade(self, sessions_root=sessions_root or tempfile.mkdtemp(), now=now)

    def _active_state_for_current_user(self):
        return dict(self.state)

    def _session_flow(self, state=None):
        data = state if isinstance(state, dict) else self.state
        if bool(data.get("active")) and str(data.get("session_kind") or "").lower() == "enrollment":
            return "enrollment_active"
        return "idle"

    def _logger_process_key(self):
        return "logger_user_alice"

    def _logger_key(self):
        return "logger_user_alice"

    def _clear_pending_logger_start(self):
        self._pending_logger_start = False

    def _clear_pending_monitor_start(self):
        self._pending_monitor_start = False

    def _clear_history_archive_watch(self):
        self._history_sync_pending = False
        self._history_sync_started_at = 0.0
        self._history_sync_hard_deadline = 0.0
        self._history_sync_status = "idle"
        self._history_sync_warning = ""

    def _begin_history_archive_watch(self, timeout_sec=15.0, *, hard_timeout_sec=30.0):
        self._history_sync_pending = True
        self._history_sync_started_at = self._facade.time.time()
        self._history_sync_hard_deadline = self._facade.time.time() + float(hard_timeout_sec)
        self._history_sync_status = "finalizing"

    def _runtime_state_is_orphaned(self, state):
        return False

    def _stop_stale_monitor(self, wait_timeout=0.5):
        return True

    def _force_clear_orphaned_runtime_state(self, state=None, *, reason=""):
        self.force_clear_reason = reason

    def _invalidate_dashboard_snapshot_cache(self):
        self.invalidated_dashboard = True

    def _update_refresh_timer(self, *, force=False):
        self.refresh_timer_forced = bool(force)

    def requestRefresh(self, reason, force=False):
        self.refreshes.append((str(reason), bool(force)))

    def _set_status(self, message, tone):
        self.statuses.append((str(message), str(tone)))

    def _t(self, key, **kwargs):
        if key == "passive_finalization_recovered":
            return "Previous session finalization was recovered. Continue using your device normally."
        return str(key)

    def _debug_trace(self, category, message, payload=None, level="info"):
        self.debug_events.append((str(category), str(message), dict(payload or {}), str(level)))


def _state(*, finalizing_at: float = 900.0, passive: bool = True) -> dict:
    state = {
        "active": True,
        "session_id": "sess-1",
        "session_kind": "enrollment",
        "user_id": "alice",
        "source": "logger",
        "status": "ok",
        "logger_ready": True,
        "auto_enrollment_finalizing": True,
        "auto_enrollment_stop_requested": True,
        "auto_enrollment_finalizing_started_at": finalizing_at,
        "auto_enrollment_stop_requested_at": finalizing_at,
        "started_at": 800.0,
    }
    if passive:
        state.update({"auto_enrollment": True, "collection_source": "passive_auto_enrollment"})
    return state


def _with_facade(bridge: _Bridge):
    original = session_runtime_helpers._facade
    session_runtime_helpers._facade = lambda: bridge._facade
    return original


def test_stale_finalizing_no_logger_is_recovery_eligible() -> None:
    bridge = _Bridge(_state(finalizing_at=900.0), now=1000.0)
    original = _with_facade(bridge)
    try:
        result = session_runtime_helpers.detect_stale_passive_finalization(bridge, bridge.state)
    finally:
        session_runtime_helpers._facade = original
    assert result["stale"] is True
    assert result["reason"] == "stale_finalization_recovered"


def test_recent_finalizing_state_waits_for_grace_period() -> None:
    bridge = _Bridge(_state(finalizing_at=990.0), now=1000.0)
    original = _with_facade(bridge)
    try:
        result = session_runtime_helpers.detect_stale_passive_finalization(bridge, bridge.state)
    finally:
        session_runtime_helpers._facade = original
    assert result["stale"] is False
    assert result["reason"] == "finalization_grace"


def test_live_logger_prevents_recovery() -> None:
    bridge = _Bridge(_state(finalizing_at=900.0), now=1000.0)
    bridge._running_processes["logger_user_alice"] = _Process(alive=True)
    original = _with_facade(bridge)
    try:
        result = session_runtime_helpers.detect_stale_passive_finalization(bridge, bridge.state)
    finally:
        session_runtime_helpers._facade = original
    assert result["stale"] is False
    assert result["reason"] == "logger_process_alive"


def test_training_active_prevents_idle_recovery() -> None:
    bridge = _Bridge(_state(finalizing_at=900.0), now=1000.0)
    bridge._training_in_progress = True
    original = _with_facade(bridge)
    try:
        result = session_runtime_helpers.detect_stale_passive_finalization(bridge, bridge.state)
    finally:
        session_runtime_helpers._facade = original
    assert result["stale"] is False
    assert result["reason"] == "training_active"


def test_manual_enrollment_is_not_recovered_by_passive_recovery() -> None:
    bridge = _Bridge(_state(finalizing_at=900.0, passive=False), now=1000.0)
    original = _with_facade(bridge)
    try:
        result = session_runtime_helpers.detect_stale_passive_finalization(bridge, bridge.state)
    finally:
        session_runtime_helpers._facade = original
    assert result["stale"] is False
    assert result["reason"] == "not_passive_auto_enrollment"


def test_recovery_clears_finalizing_marks_idle_and_preserves_files() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        archive = Path(tmpdir) / "accepted" / "alice_enrollment_interrupted_sess-1"
        archive.mkdir(parents=True)
        metadata = archive / "metadata.json"
        metadata.write_text(json.dumps({"session_id": "sess-1", "training_eligible": True}), encoding="utf-8")
        state = _state(finalizing_at=900.0)
        state["archive_path"] = str(archive)
        bridge = _Bridge(state, now=1000.0, sessions_root=tmpdir)
        original = _with_facade(bridge)
        original_security = sys.modules.get("security")
        fake_security = ModuleType("security")
        fake_security.atomic_write_text = lambda path, text: Path(path).write_text(text, encoding="utf-8")
        fake_security.save_metadata_hash = lambda path: Path(path).with_name("metadata.hash").write_text("test-hash", encoding="utf-8")
        sys.modules["security"] = fake_security
        try:
            assert session_runtime_helpers.recover_stale_passive_auto_enrollment_finalization(bridge, bridge.state, source="refresh") is True
        finally:
            session_runtime_helpers._facade = original
            if original_security is None:
                sys.modules.pop("security", None)
            else:
                sys.modules["security"] = original_security
        assert bridge.state["active"] is False
        assert bridge._session_flow(bridge.state) == "idle"
        assert bridge.state["auto_enrollment_finalizing"] is False
        assert bridge.state["auto_enrollment_stop_requested"] is False
        assert bridge.state["stop_requested"] is False
        assert bridge.state["archive_pending"] is False
        assert bridge.state["auto_enrollment_recovery_reason"] == "stale_finalization_recovered"
        assert bridge.state["auto_enrollment_recovered_after_restart"] is True
        assert metadata.exists()
        marked = json.loads(metadata.read_text(encoding="utf-8"))
        assert marked["auto_enrollment_recovery_reason"] == "stale_finalization_recovered"
        assert marked["training_eligible"] is False
        message, tone = refresh_dashboard_helpers.status_for_dashboard(bridge, {}, bridge.state)
        assert "Session archive is being finalized" not in message
        assert tone in {"info", "neutral"}
        assert bridge.autoEnrollmentChanged.count >= 1


def test_stop_button_recovers_stale_finalizing_without_requesting_stop_loop() -> None:
    bridge = _Bridge(_state(finalizing_at=900.0), now=1000.0)
    original = _with_facade(bridge)
    try:
        session_runtime_helpers.stop_current_session(bridge, silent=False)
        session_runtime_helpers.stop_current_session(bridge, silent=False)
    finally:
        session_runtime_helpers._facade = original
    assert bridge.state["active"] is False
    assert bridge.state["auto_enrollment_recovery_reason"] == "stale_finalization_recovered"
    assert bridge._facade.stop_requests == []
    assert any("manual stop" in message for _cat, message, _payload, _level in bridge.debug_events)


def test_stop_with_live_logger_uses_normal_stop_path() -> None:
    bridge = _Bridge(_state(finalizing_at=900.0), now=1000.0)
    bridge._running_processes["logger_user_alice"] = _Process(alive=True)
    original = _with_facade(bridge)
    try:
        session_runtime_helpers.stop_current_session(bridge, silent=True)
    finally:
        session_runtime_helpers._facade = original
    assert "logger_user_alice" in bridge._facade.stop_requests
    assert "monitor" in bridge._facade.stop_requests
    assert bridge._history_sync_pending is True


def test_already_finalizing_log_is_rate_limited_to_debug_after_first_info() -> None:
    bridge = _Bridge(_state(finalizing_at=900.0), now=1000.0)
    original = _with_facade(bridge)
    try:
        session_runtime_helpers._debug_skip_duplicate_passive_finalization(bridge, reason="already_finalizing", state=bridge.state)
        session_runtime_helpers._debug_skip_duplicate_passive_finalization(bridge, reason="already_finalizing", state=bridge.state)
    finally:
        session_runtime_helpers._facade = original
    levels = [level for category, _message, _payload, level in bridge.debug_events if category == "auto_enrollment"]
    assert levels == ["info", "debug"]
    assert bridge.debug_events[0][2]["elapsed_finalizing_seconds"] == 100.0


def test_normal_passive_finalization_still_calls_stop_once() -> None:
    bridge = _Bridge({**_state(finalizing_at=0.0), "auto_enrollment_finalizing": False, "auto_enrollment_stop_requested": False}, now=1000.0)
    bridge._profile = {"session_count": 15, "recommended_session_count": 15}
    bridge.autoEnrollmentState = {"enabled": True, "consentSatisfied": True, "acceptedSessions": 15, "recommendedSessions": 15}
    bridge.modelReadinessState = {}
    bridge.stop_count = 0

    def stop_current_session(silent=True):
        bridge.stop_count += 1

    bridge.stopCurrentSession = stop_current_session
    original = _with_facade(bridge)
    try:
        assert session_runtime_helpers.maybe_finalize_passive_auto_enrollment(bridge) is True
        assert session_runtime_helpers.maybe_finalize_passive_auto_enrollment(bridge) is False
    finally:
        session_runtime_helpers._facade = original
    assert bridge.stop_count == 1
    assert bridge.state["auto_enrollment_finalizing"] is True
    assert bridge.state["auto_enrollment_finalizing_started_at"] == 1000.0


def test_missing_timestamp_uses_in_memory_grace_before_recovery() -> None:
    state = _state(finalizing_at=0.0)
    state.pop("auto_enrollment_finalizing_started_at", None)
    state.pop("auto_enrollment_stop_requested_at", None)
    bridge = _Bridge(state, now=1000.0)
    original = _with_facade(bridge)
    try:
        first = session_runtime_helpers.detect_stale_passive_finalization(bridge, bridge.state)
        bridge._facade.time.now = 1016.0
        second = session_runtime_helpers.detect_stale_passive_finalization(bridge, bridge.state)
    finally:
        session_runtime_helpers._facade = original
    assert first["stale"] is False
    assert first["reason"] == "finalization_observed_grace"
    assert second["stale"] is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("11 focused passive finalization stuck-state recovery tests passed", flush=True)
    raise SystemExit(0)
