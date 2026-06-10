from __future__ import annotations

from pathlib import Path

import inspect

import pytest

from bioauth_runtime.supervisor import protection_session_controller as start_ctl
from bridge import refresh_runtime_helpers


class _Signal:
    def emit(self):
        pass


class _FakeFacade:
    LOGGER_SCRIPT = "logger.py"
    MONITOR_SCRIPT = "monitor.py"
    LOGGER_START_GRACE_SEC = 3.0
    MONITOR_START_GRACE_SEC = 3.0

    def __init__(self, tmp_path):
        import time
        import uuid

        self.tmp_path = tmp_path
        self.time = time
        self.uuid = uuid
        self.state = {}
        self.writes = []
        self.cleared = []
        self.profile = {"production_ready": True, "user_id": "alice"}
        self.raise_profile = False

    def user_profile_status(self, user_id):
        if self.raise_profile:
            raise RuntimeError("profile database locked")
        return dict(self.profile)

    def clear_stop(self, name):
        self.cleared.append(("stop", str(name)))

    def request_stop(self, name):
        self.cleared.append(("request_stop", str(name)))

    def clear_session_state(self):
        self.state = {}
        return True

    def write_session_state(self, state):
        self.state = dict(state or {})
        self.writes.append(dict(self.state))
        return True

    def read_session_state(self, default=None):
        return dict(self.state or (default or {}))

    def clear_worker_heartbeat(self, kind=None):
        self.cleared.append(("heartbeat", str(kind)))

    def invalidate_session_discovery_cache(self):
        self.cleared.append(("discovery", ""))

    def prepare_session_state_for_new_runtime(self, *_args, **_kwargs):
        return {"ok": True}


class _FakeLegacy:
    def __init__(self, facade):
        self.facade = facade
        self.refreshes = []

    def _facade(self):
        return self.facade

    def _normal_user_session_flow(self, bridge, state):
        return getattr(bridge, "flow", "idle")

    def stop_stale_monitor(self, bridge, wait_timeout=1.0):
        return True

    def _request_refresh(self, bridge, reason, force):
        self.refreshes.append((reason, force))


class _Bridge:
    def __init__(self, tmp_path):
        self._current_user = {"user_id": "alice"}
        self._profile = {"production_ready": True}
        self._runtime_state = {}
        self._running_processes = {}
        self._status = []
        self._debug_events = []
        self._last_process_start_error = ""
        self._pending_logger_start = False
        self._pending_monitor_start = False
        self._active_live_session_dir = None
        self._last_alert_signature = None
        self.flow = "idle"
        self.tmp_path = tmp_path
        self.onboardingChanged = _Signal()

    def _debug_trace(self, category, message, payload=None):
        self._debug_events.append((category, message, dict(payload or {})))

    def _has_current_user_welcome_consent(self):
        return True

    def _set_status(self, msg, tone):
        self._status.append((str(msg), str(tone)))

    def _t(self, key, **_kwargs):
        return key

    def _logger_key(self):
        return "logger_user_alice"

    def _logger_process_key(self):
        return "logger_user_alice"

    def _new_live_session_dir(self):
        path = self.tmp_path / "live"
        path.mkdir(exist_ok=True)
        return str(path)

    def _session_process_env(self):
        return {"BIOAUTH_LIVE_SESSION_DIR": str(self.tmp_path / "live")}

    def _clear_history_archive_watch(self):
        self.history_cleared = True

    def _invalidate_dashboard_snapshot_cache(self):
        self.cache_invalidated = True

    def _update_refresh_timer(self, force=False):
        self.refresh_force = bool(force)

    def _active_state_for_current_user(self):
        return dict(self._runtime_state)


@pytest.fixture()
def fake_runtime(monkeypatch, tmp_path):
    facade = _FakeFacade(tmp_path)
    legacy = _FakeLegacy(facade)
    monkeypatch.setattr(start_ctl, "_legacy", lambda: legacy)
    monkeypatch.setattr(start_ctl, "_ensure_start_watcher", lambda _bridge: None)
    monkeypatch.setattr(start_ctl, "_ensure_health_watcher", lambda _bridge: None)
    return facade, legacy, _Bridge(tmp_path)


def _checkpoint_names(bridge):
    return [message for _category, message, _payload in bridge._debug_events]


def test_profile_validation_exception_writes_failed_to_start_state(fake_runtime):
    facade, _legacy, bridge = fake_runtime
    bridge._profile = {}
    facade.raise_profile = True
    assert start_ctl.start_protection(bridge) is False
    assert facade.state["active"] is False
    assert facade.state["status"] == "failed_to_start"
    assert facade.state["runtime_status"] == "start_failed"
    assert facade.state["runtime_decision"] == "failed"
    assert facade.state["runtime_diag_code"] == "start_protection_exception"
    assert "profile database locked" in facade.state["runtime_diag_reason"]
    assert any("Protection could not start" in msg for msg, _tone in bridge._status)
    assert "start_failed_exception" in _checkpoint_names(bridge)


def test_logger_spawn_exception_keeps_initial_state_then_writes_failed_state(monkeypatch, fake_runtime):
    facade, _legacy, bridge = fake_runtime

    def boom(*_args, **_kwargs):
        raise OSError("cannot launch logger")

    monkeypatch.setattr(start_ctl.worker_processes, "start_worker", boom)
    monkeypatch.setattr(start_ctl.worker_processes, "stop_pair", lambda *_args, **_kwargs: {"ok": True})
    assert start_ctl.start_protection(bridge) is False
    first = facade.writes[0]
    final = facade.state
    assert first["active"] is True
    assert first["session_id"]
    assert first["run_id"]
    assert Path(first["live_session_dir"]).exists()
    assert first["flow"] == "protected_starting"
    assert final["active"] is False
    assert final["runtime_status"] == "start_failed"
    assert final["runtime_diag_code"] == "logger_spawn_failed"
    assert final["pending_monitor_start"] is False
    assert "logger_spawn_requested" in _checkpoint_names(bridge)
    assert "logger_spawn_failed" in _checkpoint_names(bridge)


def test_profile_not_ready_early_block_is_explicit(fake_runtime):
    facade, _legacy, bridge = fake_runtime
    bridge._profile = {"production_ready": False}
    assert start_ctl.start_protection(bridge) is False
    assert facade.state["status"] == "failed_to_start"
    assert facade.state["runtime_diag_code"] == "start_blocked_profile_not_ready"
    assert facade.state["runtime_diag_reason"] == "Production runtime profile is not ready."
    assert "production_profile_validation_result" in _checkpoint_names(bridge)


def test_initial_state_is_written_before_logger_spawn(monkeypatch, fake_runtime):
    facade, _legacy, bridge = fake_runtime
    observed_state_at_spawn = {}

    def start_worker(_bridge, _key, _args, extra_env=None):
        observed_state_at_spawn.update(facade.state)
        return True

    monkeypatch.setattr(start_ctl.worker_processes, "start_worker", start_worker)
    assert start_ctl.start_protection(bridge) is True
    assert observed_state_at_spawn["schema_version"] == 2
    assert observed_state_at_spawn["user"] == "alice"
    assert observed_state_at_spawn["session_id"]
    assert observed_state_at_spawn["run_id"]
    assert Path(observed_state_at_spawn["live_session_dir"]).exists()
    assert observed_state_at_spawn["active"] is True
    assert observed_state_at_spawn["session_kind"] == "protected"
    assert observed_state_at_spawn["status"] == "starting"
    assert observed_state_at_spawn["flow"] == "protected_starting"
    assert observed_state_at_spawn["pending_monitor_start"] is True
    assert observed_state_at_spawn["awaiting_evidence"] is True


def test_duplicate_start_while_starting_returns_explicit_block(monkeypatch, fake_runtime):
    facade, _legacy, bridge = fake_runtime
    bridge._pending_logger_start = True
    bridge._runtime_state = {"session_kind": "protected", "status": "starting", "flow": "protected_starting", "active": True}
    starts = []
    monkeypatch.setattr(start_ctl.worker_processes, "start_worker", lambda *args, **kwargs: starts.append(args) or True)
    assert start_ctl.start_protection(bridge) is False
    assert starts == []
    assert facade.state["runtime_diag_code"] == "start_blocked_start_already_in_progress"
    assert facade.state["active"] is True


def test_successful_start_still_spawns_logger_first(monkeypatch, fake_runtime):
    facade, _legacy, bridge = fake_runtime
    starts = []
    monkeypatch.setattr(start_ctl.worker_processes, "start_worker", lambda bridge, key, args, extra_env=None: starts.append((key, args, extra_env)) or True)
    assert start_ctl.start_protection(bridge) is True
    assert starts == [("logger_user_alice", ["logger.py", "alice", "protected"], {"BIOAUTH_LIVE_SESSION_DIR": str(bridge.tmp_path / "live")})]
    assert facade.state["active"] is True
    assert facade.state["runtime_diag_code"] == "protected_starting"
    assert "supervisor_start_completed" in _checkpoint_names(bridge)


def test_refresh_still_has_no_direct_worker_lifecycle_calls():
    source = inspect.getsource(refresh_runtime_helpers._perform_refresh_now)
    forbidden = (
        "_maybe_finish_pending_logger_start(",
        "_maybe_finish_pending_monitor_start(",
        "check_worker_pair_liveness(",
        "_start_process(",
        "request_stop(",
        "recover_stale_protected_flow_without_workers(",
        "stop_current_session(",
    )
    for token in forbidden:
        assert token not in source
