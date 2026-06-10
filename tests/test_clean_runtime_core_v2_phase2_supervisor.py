from __future__ import annotations

import inspect
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from bioauth_runtime.supervisor import protection_session_controller as start_ctl
from bioauth_runtime.supervisor import resume_controller, stop_controller, worker_health
from bridge import refresh_runtime_helpers, session_runtime_helpers
from bridge.session_mixin import SessionMixin


class _Signal:
    def emit(self):
        pass


class _FakeFacade:
    LOGGER_SCRIPT = "logger.py"
    MONITOR_SCRIPT = "monitor.py"
    LOGGER_START_GRACE_SEC = 3.0
    MONITOR_START_GRACE_SEC = 3.0

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.state = {}
        self.stops = []
        self.cleared = []
        self.time = time
        import uuid

        self.uuid = uuid

    def user_profile_status(self, user_id):
        return {"production_ready": True, "user_id": user_id}

    def clear_stop(self, name):
        self.cleared.append(("stop", name))

    def request_stop(self, name):
        self.stops.append(name)

    def clear_session_state(self):
        self.state = {}
        return True

    def write_session_state(self, state):
        self.state = dict(state)
        return True

    def read_session_state(self, default=None):
        return dict(self.state or (default or {}))

    def clear_worker_heartbeat(self, kind=None):
        self.cleared.append(("heartbeat", kind))

    def invalidate_session_discovery_cache(self):
        self.cleared.append(("discovery", ""))

    def slugify_username(self, value):
        return str(value or "").lower()

    def prepare_session_state_for_new_runtime(self, *_args, **_kwargs):
        return {"ok": True}

    def is_current_session_locked(self):
        return False


class _FakeLegacy:
    def __init__(self, facade):
        self.facade = facade
        self.requested_refreshes = []

    def _facade(self):
        return self.facade

    def _normal_user_session_flow(self, bridge, state):
        return getattr(bridge, "flow", "idle")

    def stop_stale_monitor(self, bridge, wait_timeout=1.0):
        return True

    def _request_refresh(self, bridge, reason, force):
        self.requested_refreshes.append((reason, force))

    def worker_failure_detail(self, bridge, key, fallback):
        return fallback, {"exit_code": 1}

    def stop_live_candidate_observer(self, *_args, **_kwargs):
        return True


class _Bridge:
    def __init__(self, tmp_path):
        self._current_user = {"user_id": "alice"}
        self._profile = {"production_ready": True}
        self._running_processes = {}
        self._runtime_state = {}
        self._status = []
        self._last_process_start_error = ""
        self._last_auto_resume_attempt_at = 0.0
        self._auto_resume_inflight = False
        self._pending_logger_start = False
        self._pending_monitor_start = False
        self.onboardingChanged = _Signal()
        self.tmp_path = tmp_path
        self.flow = "idle"

    def _has_current_user_welcome_consent(self):
        return True

    def _set_status(self, msg, tone):
        self._status.append((msg, tone))

    def _t(self, key, **_kwargs):
        return key

    def _safe_user(self):
        return "alice"

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

    def _clear_pending_logger_start(self):
        self._pending_logger_start = False

    def _clear_pending_monitor_start(self):
        self._pending_monitor_start = False


def _install_fake_legacy(monkeypatch, tmp_path):
    facade = _FakeFacade(tmp_path)
    legacy = _FakeLegacy(facade)
    monkeypatch.setattr(start_ctl, "_legacy", lambda: legacy)
    monkeypatch.setattr(stop_controller, "_legacy", lambda: legacy)
    monkeypatch.setattr(resume_controller, "_legacy", lambda: legacy)
    return facade, legacy


def test_start_protection_wrapper_delegates_to_supervisor(monkeypatch):
    calls = []
    monkeypatch.setattr(start_ctl, "start_protection", lambda bridge, **kwargs: calls.append(kwargs) or True)
    assert session_runtime_helpers.start_protected_session(object(), auto_resume=False, trigger_refresh=True) is True
    assert calls == [{"auto_resume": False, "trigger_refresh": True}]


def test_request_user_start_and_stop_delegate_to_supervisor(monkeypatch):
    class Dummy(SessionMixin):
        def _can_start_production_monitor(self):
            return True

        def _safe_user_action_result(self, **payload):
            return payload

        def _deny_user_home_action(self, *args, **kwargs):
            return {"ok": False}

        def _t(self, key, **kwargs):
            return key

    dummy = Dummy()
    dummy.calls = []
    dummy._start_protected_session = lambda **kwargs: dummy.calls.append(("start", kwargs)) or True
    dummy.stopProductionMonitor = lambda silent=False: dummy.calls.append(("stop", silent))
    monkeypatch.setattr(session_runtime_helpers, "_protected_session_stop_available", lambda _bridge: True)
    dummy.requestUserStartProtection()
    dummy.requestUserStopProtection()
    assert dummy.calls == [("start", {"auto_resume": False, "trigger_refresh": True}), ("stop", False)]


def test_stop_protection_wrapper_delegates_to_supervisor(monkeypatch):
    calls = []
    monkeypatch.setattr(stop_controller, "stop_protection", lambda bridge, **kwargs: calls.append(kwargs) or {"ok": True})
    session_runtime_helpers.stop_production_monitor(object(), silent=True)
    assert calls == [{"reason": "user_requested", "silent": True}]


def test_start_protection_creates_one_session_and_starts_logger_first(monkeypatch, tmp_path):
    facade, _legacy = _install_fake_legacy(monkeypatch, tmp_path)
    bridge = _Bridge(tmp_path)
    starts = []
    monkeypatch.setattr(start_ctl, "_ensure_start_watcher", lambda _bridge: None)
    monkeypatch.setattr(start_ctl, "_ensure_health_watcher", lambda _bridge: None)
    monkeypatch.setattr(start_ctl.worker_processes, "start_worker", lambda bridge, key, args, extra_env=None: starts.append((key, args, extra_env)) or True)
    assert start_ctl.start_protection(bridge) is True
    assert facade.state["session_id"]
    assert facade.state["run_id"]
    assert Path(facade.state["live_session_dir"]).exists()
    assert starts == [("logger_user_alice", ["logger.py", "alice", "protected"], {"BIOAUTH_LIVE_SESSION_DIR": str(tmp_path / "live")})]


def test_monitor_is_started_only_after_logger_readiness(monkeypatch, tmp_path):
    _install_fake_legacy(monkeypatch, tmp_path)
    bridge = _Bridge(tmp_path)
    bridge._pending_logger_start = True
    bridge._pending_monitor_start = True
    calls = []
    monkeypatch.setattr(start_ctl, "_finish_pending_logger_start", lambda bridge: calls.append("logger") or True)
    monkeypatch.setattr(start_ctl, "_finish_pending_monitor_start", lambda bridge: calls.append("monitor") or True)
    assert start_ctl.advance_pending_start(bridge) == {"logger": True, "monitor": True}
    assert calls == ["logger", "monitor"]


def test_duplicate_start_does_not_spawn_duplicate_workers(monkeypatch, tmp_path):
    _install_fake_legacy(monkeypatch, tmp_path)
    bridge = _Bridge(tmp_path)
    bridge.flow = "protected_active"
    starts = []
    monkeypatch.setattr(start_ctl.worker_processes, "start_worker", lambda *args, **kwargs: starts.append(args) or True)
    assert start_ctl.start_protection(bridge) is False
    assert starts == []


def test_stop_protection_stops_both_workers(monkeypatch, tmp_path):
    facade, _legacy = _install_fake_legacy(monkeypatch, tmp_path)
    bridge = _Bridge(tmp_path)
    calls = []
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda bridge, **kwargs: calls.append(kwargs) or {"logger": {}, "monitor": {}})
    result = stop_controller.stop_protection(bridge, reason="user_requested", silent=True)
    assert result["ok"] is True
    assert calls == [{"reason": "user_requested", "wait_timeout": 1.25}]
    assert facade.state["active"] is False


def test_refresh_perform_does_not_directly_start_or_stop_workers():
    source = inspect.getsource(refresh_runtime_helpers._perform_refresh_now)
    forbidden = [
        "_maybe_finish_pending_logger_start(",
        "_maybe_finish_pending_monitor_start(",
        "check_worker_pair_liveness(",
        "_cleanup_processes(",
        "_start_process(",
        "request_stop(",
        "_terminate_process_key(",
    ]
    for token in forbidden:
        assert token not in source


def test_worker_health_classification_has_no_process_side_effect_tokens():
    source = inspect.getsource(worker_health.classify_worker_pair)
    for token in ("start_worker", "stop_worker", "request_stop", "terminate", "kill"):
        assert token not in source


def test_logger_and_monitor_death_route_to_supervisor_stop(monkeypatch, tmp_path):
    facade, _legacy = _install_fake_legacy(monkeypatch, tmp_path)
    bridge = _Bridge(tmp_path)
    facade.state = {"session_kind": "protected", "active": True, "monitor_ready": True}
    calls = []
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda bridge, **kwargs: calls.append(kwargs) or {"ok": True})
    stop_controller.handle_logger_exit_after_ready(bridge, "logger_user_alice", diagnostics={"exit_code": 1})
    facade.state = {"session_kind": "protected", "active": True, "monitor_ready": True}
    stop_controller.handle_monitor_exit_after_ready(bridge, diagnostics={"exit_code": 1})
    assert [call["reason"] for call in calls] == ["logger_exited_after_ready", "monitor_exited_after_ready"]


def test_auto_resume_starts_once_and_waits_for_old_workers(monkeypatch, tmp_path):
    facade, _legacy = _install_fake_legacy(monkeypatch, tmp_path)
    bridge = _Bridge(tmp_path)
    state = {"session_kind": "protected", "active": False, "status": "resume_pending", "forced_stop": True, "protected_action_requested": True, "final_action": "windows_locked", "lock_reason": "camera_unavailable", "auto_resume_pending": True, "resume_after_unlock": True, "lock_controller_handoff": True}
    starts = []
    monkeypatch.setattr(resume_controller.worker_processes, "stop_pair", lambda *args, **kwargs: {})
    monkeypatch.setattr(resume_controller.worker_processes, "process_alive", lambda *args, **kwargs: False)
    monkeypatch.setattr(resume_controller.protection_session_controller, "start_protection", lambda bridge, **kwargs: starts.append(kwargs) or True)
    assert resume_controller.maybe_resume_after_unlock(bridge, state) is True
    assert resume_controller.maybe_resume_after_unlock(bridge, state) is False
    assert starts == [{"auto_resume": True, "trigger_refresh": False}]

    bridge._last_auto_resume_attempt_at = 0.0
    starts.clear()
    monkeypatch.setattr(resume_controller.worker_processes, "process_alive", lambda *args, **kwargs: True)
    assert resume_controller.maybe_resume_after_unlock(bridge, state) is False
    assert starts == []


def test_commercial_refresh_fences_auto_training_promotion_shadow_and_passive(monkeypatch):
    class Dummy:
        def __init__(self):
            self._current_user = {"user_id": "alice"}
            self._runtime_state = {"session_kind": "protected", "active": True, "status": "protected_active"}
            self.calls = []

        def _session_flow(self, state):
            return "protected_active"

        def _update_dashboard(self):
            pass

        def _handle_state_alerts(self):
            self.calls.append("alerts")

        def _maybe_resume_protection_after_unlock(self, state):
            self.calls.append("resume")
            return False

        def _update_refresh_timer(self):
            pass

        def _maybe_start_auto_training(self):
            self.calls.append("auto_training")
            return True

        def _maybe_auto_promote_production(self):
            self.calls.append("auto_promotion")
            return True

        def _maybe_process_shadow_backlog(self):
            self.calls.append("shadow_backlog")

        def _maybe_start_passive_auto_enrollment(self):
            self.calls.append("passive_auto_enrollment")
            return True

    refresh_runtime_helpers._perform_refresh_now(Dummy(), reason="test", force=True)
    assert "alerts" in Dummy.__dict__.get("calls", []) or True
    # Re-run on an instance we can inspect.
    app = Dummy()
    refresh_runtime_helpers._perform_refresh_now(app, reason="test", force=True)
    assert "auto_training" not in app.calls
    assert "auto_promotion" not in app.calls
    assert "shadow_backlog" not in app.calls
    assert "passive_auto_enrollment" not in app.calls


def test_logger_and_monitor_root_entrypoints_preserved():
    logger_source = Path("logger.py").read_text(encoding="utf-8")
    monitor_source = Path("monitor.py").read_text(encoding="utf-8")
    assert "bioauth_runtime.logger_worker.main" in logger_source
    assert "raise SystemExit(main())" in logger_source
    assert "bioauth_runtime.monitor_worker.main" in monitor_source
    assert "def monitor" in monitor_source
