from __future__ import annotations

import types
import time as _time


class _Signal:
    def emit(self, *args, **kwargs):
        return None


class _Facade:
    LOGGER_SCRIPT = "logger.py"
    MONITOR_SCRIPT = "monitor.py"
    MONITOR_START_GRACE_SEC = 5.0
    time = _time

    class uuid:
        @staticmethod
        def uuid4():
            return types.SimpleNamespace(hex="phase1-session-id")

    def __init__(self):
        self.session_cleared = False
        self.cache_invalidated = False
        self.stop_requests = []

    def clear_session_state(self):
        self.session_cleared = True

    def invalidate_session_discovery_cache(self):
        self.cache_invalidated = True

    def clear_stop(self, name):
        self.stop_requests.append(("clear", name))

    def request_stop(self, name):
        self.stop_requests.append(("stop", name))

    def slugify_username(self, value):
        return str(value or "").strip().lower()

    def write_session_state(self, state):
        self.last_written_state = dict(state or {})


class _App:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._profile = {
            "production_ready": False,
            "candidate_model_status": "approved_for_shadow",
            "production_approval_state": {
                "modelStatus": "approved_for_shadow",
                "protectedSessionsAvailable": False,
                "runtimeValidationReason": "production_evidence_missing",
            },
        }
        self._runtime_state = {}
        self._training_in_progress = False
        self._training_progress = {}
        self._passive_auto_enrollment_finalizing = False
        self._history_sync_pending = False
        self._pending_passive_auto_enrollment = False
        self._pending_logger_start = False
        self._pending_logger_session_kind = ""
        self._pending_monitor_start = False
        self._pending_shadow_evidence_monitor_start = False
        self._shadow_evidence_monitor_launch_attempted = False
        self._shadow_evidence_monitor_start_deadline = 0.0
        self._shadow_evidence_monitor_failed = False
        self._last_shadow_evidence_monitor_block_reason = ""
        self._last_shadow_evidence_monitor_skipped_reason = ""
        self._shadow_automation_paused = False
        self._running_processes = {}
        self._active_live_session_dir = None
        self._last_alert_signature = None
        self.started = []
        self.refreshed = []
        self.statuses = []
        self.onboardingChanged = _Signal()

    def _has_current_user_welcome_consent(self):
        return True

    def _active_state_for_current_user(self):
        return dict(self._runtime_state)

    def _session_flow(self, state=None):
        data = state if isinstance(state, dict) else self._runtime_state
        return "shadow_evidence_active" if data.get("session_kind") == "shadow_evidence" and data.get("active") else "idle"

    def _stop_stale_monitor(self):
        return True

    def _logger_key(self):
        return "logger_user_alice"

    def _logger_process_key(self):
        return "logger_user_alice"

    def _shadow_logger_process_key(self):
        return "shadow_logger_user_alice"

    def _shadow_monitor_process_key(self):
        return "shadow_monitor_user_alice"

    def _shadow_logger_stop_control_name(self):
        return "shadow_logger_user_alice"

    def _shadow_monitor_stop_control_name(self):
        return "shadow_monitor_user_alice"

    def _new_live_session_dir(self):
        return "/tmp/bioauth-phase1-shadow"

    def _session_process_env(self):
        return {"BIOAUTH_BASE": "test"}

    def _start_process(self, key, args, extra_env=None):
        self.started.append((key, list(args), dict(extra_env or {})))
        return True

    def _clear_pending_shadow_evidence_monitor_start(self):
        self._pending_shadow_evidence_monitor_start = False
        self._shadow_evidence_monitor_start_deadline = 0.0
        self._shadow_evidence_monitor_launch_attempted = False

    def _clear_history_archive_watch(self):
        return None

    def _invalidate_dashboard_snapshot_cache(self):
        return None

    def _set_status(self, msg, tone):
        self.statuses.append((msg, tone))

    def _update_refresh_timer(self, force=False):
        self.refreshed.append(("timer", force))

    def requestRefresh(self, reason, force=False):
        self.refreshed.append((reason, force))


def _helpers(monkeypatch):
    import bridge.session_runtime_helpers as helpers

    facade = _Facade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    return helpers, facade


def test_independent_shadow_monitor_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("BIOAUTH_ENABLE_SHADOW_EVIDENCE_MONITOR", raising=False)
    helpers, facade = _helpers(monkeypatch)
    app = _App()

    assert helpers.start_shadow_evidence_monitor(app, trigger_refresh=False) is False
    assert app.started == []
    assert app._pending_shadow_evidence_monitor_start is False
    assert app._last_shadow_evidence_monitor_block_reason == ""
    assert app._last_shadow_evidence_monitor_skipped_reason == "independent_shadow_evidence_monitor_disabled"
    assert facade.session_cleared is False


def test_independent_shadow_monitor_requires_explicit_developer_flag(monkeypatch):
    monkeypatch.setenv("BIOAUTH_ENABLE_SHADOW_EVIDENCE_MONITOR", "1")
    helpers, facade = _helpers(monkeypatch)
    app = _App()

    assert helpers.start_shadow_evidence_monitor(app, trigger_refresh=False) is True
    key, args, env = app.started[-1]
    assert key == "shadow_logger_user_alice"
    assert args == [facade.LOGGER_SCRIPT, "alice", "shadow_evidence"]
    assert env["BIOAUTH_RUNTIME_MODE"] == "shadow_evidence"
    assert env["BIOAUTH_SHADOW_EVIDENCE_ONLY"] == "1"
    assert env["BIOAUTH_EVIDENCE_SOURCE"] == "shadow_evidence_monitor"


def test_autonomous_loop_does_not_auto_start_shadow_by_default():
    from metadata_core.autonomous_readiness_loop import build_autonomous_readiness_loop_state

    state = build_autonomous_readiness_loop_state(
        settings={"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": True},
        profile={"candidate_model_status": "approved_for_shadow"},
        runtime_state={},
        consent_satisfied=True,
        authenticated=True,
        production_approval={"modelStatus": "approved_for_shadow", "protectedSessionsAvailable": False},
    )
    assert state["autonomous_loop_state"] == "approved_for_shadow"
    assert state["autonomous_loop_next_action"] == "none"
    assert "independent_shadow_evidence_monitor_disabled" in state["autonomous_loop_blockers"]


def test_autonomous_loop_can_still_suggest_developer_shadow_when_enabled():
    from metadata_core.autonomous_readiness_loop import build_autonomous_readiness_loop_state

    state = build_autonomous_readiness_loop_state(
        settings={
            "smart_auto_enrollment_enabled": True,
            "auto_train_when_ready_enabled": True,
            "enable_independent_shadow_evidence_monitor": True,
        },
        profile={"candidate_model_status": "approved_for_shadow"},
        runtime_state={},
        consent_satisfied=True,
        authenticated=True,
        production_approval={"modelStatus": "approved_for_shadow", "protectedSessionsAvailable": False},
    )
    assert state["autonomous_loop_next_action"] == "start_shadow_evidence_monitor"


def test_stale_shadow_state_without_process_does_not_block_auto_training():
    from metadata_core.auto_training_scheduler import runtime_has_active_shadow_evidence_process

    assert runtime_has_active_shadow_evidence_process({"active": True, "session_kind": "shadow_evidence"}) is False
    assert runtime_has_active_shadow_evidence_process({"session_kind": "shadow_evidence", "logger_process_alive": True}) is True
