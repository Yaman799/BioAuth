from __future__ import annotations

import inspect
import time
from pathlib import Path

from bioauth_runtime.supervisor import heartbeat_store
from bioauth_runtime.supervisor import protection_session_controller as start_ctl
from bridge import refresh_runtime_helpers, session_runtime_helpers


class _Facade:
    def __init__(self, tmp_path: Path):
        import uuid

        self.uuid = uuid
        self.time = time
        self.state = {}
        self.cleared = []
        self.tmp_path = tmp_path

    def clear_stop(self, name):
        self.cleared.append(("stop", name))

    def prepare_session_state_for_new_runtime(self, *_args, **_kwargs):
        return {"ok": True}

    def clear_session_state(self):
        self.state = {}
        return True

    def write_session_state(self, state):
        self.state = dict(state or {})
        return True

    def invalidate_session_discovery_cache(self):
        self.cleared.append(("discovery", ""))


class _LegacyWithPublicStopOnly:
    def __init__(self, facade: _Facade):
        self.facade = facade
        self.stop_calls = []

    def _facade(self):
        return self.facade

    def stop_stale_monitor(self, bridge, wait_timeout=0.5):
        self.stop_calls.append((bridge, wait_timeout))
        return True


class _Bridge:
    def __init__(self, tmp_path: Path):
        self._current_user = {"user_id": "alice"}
        self._pending_logger_session_id = ""
        self._pending_logger_run_id = ""
        self._active_live_session_dir = None
        self._last_alert_signature = None
        self._runtime_state = {}
        self._debug_events = []
        self.tmp_path = tmp_path

    def _logger_key(self):
        return "logger_user_alice"

    def _clear_history_archive_watch(self):
        self.history_cleared = True

    def _invalidate_dashboard_snapshot_cache(self):
        self.cache_invalidated = True

    def _new_live_session_dir(self):
        path = self.tmp_path / "live-session"
        path.mkdir(exist_ok=True)
        return str(path)

    def _debug_trace(self, category, message, payload=None, level="info"):
        self._debug_events.append((category, message, dict(payload or {}), level))


def test_supervisor_no_longer_references_private_stop_stale_monitor_helper():
    source = inspect.getsource(start_ctl)
    assert "legacy._stop_stale_monitor" not in source
    assert "_stop_stale_monitor(bridge" not in source
    assert "legacy.stop_stale_monitor(bridge)" in source


def test_prepare_new_session_uses_public_stop_stale_monitor_without_attribute_error(monkeypatch, tmp_path):
    facade = _Facade(tmp_path)
    legacy = _LegacyWithPublicStopOnly(facade)
    bridge = _Bridge(tmp_path)
    monkeypatch.setattr(start_ctl, "_legacy", lambda: legacy)
    monkeypatch.setattr(start_ctl.heartbeat_store, "clear_current_session", lambda: None)

    assert not hasattr(legacy, "_stop_stale_monitor")
    assert start_ctl._prepare_new_session(bridge, auto_resume=False) is True

    assert len(legacy.stop_calls) == 1
    assert facade.state["session_kind"] == "protected"
    assert facade.state["flow"] == "protected_starting"
    assert facade.state["pending_monitor_start"] is True
    assert facade.state["session_id"]
    assert facade.state["run_id"]
    assert facade.state["live_session_dir"]


def test_hotfix_7c_readiness_transition_is_present_in_current_working_copy():
    merge_source = inspect.getsource(session_runtime_helpers.merge_worker_heartbeats_into_state)
    normalizer_source = inspect.getsource(heartbeat_store.normalize_protected_startup_ready_state)
    assert "normalize_protected_startup_ready_state" in merge_source
    assert "pending_monitor_start" in normalizer_source
    assert "worker_heartbeat_waiting_for" in normalizer_source
    assert "collecting_evidence" in normalizer_source
    assert "awaiting evidence" in normalizer_source


def test_hotfix_7c_normalizer_clears_startup_fields_when_both_workers_ready():
    state = {
        "session_kind": "protected",
        "active": True,
        "logger_ready": True,
        "monitor_ready": True,
        "pending_monitor_start": True,
        "worker_heartbeat_waiting_for": "logger",
        "flow": "protected_starting",
        "status": "starting",
        "runtime_status": "starting",
        "runtime_decision": "pending",
        "runtime_diag_code": "protected_starting",
        "runtime_diag_reason": "Waiting for logger readiness.",
    }

    normalized, changed = heartbeat_store.normalize_protected_startup_ready_state(state)

    assert changed is True
    assert normalized["pending_monitor_start"] is False
    assert normalized["worker_heartbeat_waiting_for"] == ""
    assert normalized["flow"] == "protected_active"
    assert normalized["runtime_status"] == "collecting"
    assert normalized["runtime_diag_code"] == "collecting_evidence"
    assert normalized["runtime_diag_reason"] == "awaiting evidence"


def test_refresh_still_has_no_worker_lifecycle_ownership_after_hotfix_7d():
    source = inspect.getsource(refresh_runtime_helpers._perform_refresh_now)
    for token in (
        "_maybe_finish_pending_logger_start(",
        "_maybe_finish_pending_monitor_start(",
        "check_worker_pair_liveness(",
        "_start_process(",
        "request_stop(",
        "recover_stale_protected_flow_without_workers(",
        "stop_current_session(",
    ):
        assert token not in source
