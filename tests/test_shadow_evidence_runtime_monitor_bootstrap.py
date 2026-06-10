from __future__ import annotations

import re
import sys
import time as _time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class _FakeSignal:
    def emit(self, *args, **kwargs):
        return None


class _FakeFacade:
    LOGGER_SCRIPT = "logger.py"
    MONITOR_SCRIPT = "monitor.py"
    MONITOR_START_GRACE_SEC = 5.0
    time = _time

    class uuid:
        @staticmethod
        def uuid4():
            return types.SimpleNamespace(hex="fixed-session-id")

    def __init__(self):
        self.stops_cleared = []
        self.session_cleared = False
        self.cache_invalidated = False

    def clear_stop(self, name):
        self.stops_cleared.append(name)

    def clear_session_state(self):
        self.session_cleared = True

    def invalidate_session_discovery_cache(self):
        self.cache_invalidated = True

    def slugify_username(self, value):
        return str(value or "").strip().lower()

    def write_session_state(self, state):
        self.last_written_state = dict(state or {})

    def request_stop(self, name):
        self.stops_cleared.append(f"stop:{name}")

    def runtime_status_is_technical_failure(self, status):
        return str(status or "") in {"monitor_runtime_error", "runtime_schema_mismatch"}


class _FakeApp:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._profile = {
            "production_ready": False,
            "candidate_model_status": "approved_for_shadow",
            "production_approval_state": {
                "modelStatus": "approved_for_shadow",
                "productionReady": False,
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
        self._shadow_evidence_monitor_user_id = ""
        self._shadow_evidence_monitor_failed = False
        self._last_shadow_evidence_monitor_attempt_at = 0.0
        self._last_shadow_evidence_monitor_block_reason = ""
        self._shadow_automation_paused = False
        self._running_processes = {}
        self._active_live_session_dir = None
        self._last_alert_signature = None
        self.started = []
        self.statuses = []
        self.refreshed = []
        self.onboardingChanged = _FakeSignal()

    def _clear_pending_shadow_evidence_monitor_start(self):
        self._pending_shadow_evidence_monitor_start = False
        self._shadow_evidence_monitor_user_id = None
        self._shadow_evidence_monitor_start_deadline = 0.0
        self._shadow_evidence_monitor_launch_attempted = False

    def _clear_pending_monitor_start(self):
        self._pending_monitor_start = False

    def _has_current_user_welcome_consent(self):
        return True

    def _active_state_for_current_user(self):
        return dict(self._runtime_state)

    def _session_flow(self, state=None):
        data = state if isinstance(state, dict) else self._runtime_state
        if data.get("active"):
            kind = data.get("session_kind")
            if kind == "protected":
                return "protected_active"
            if kind == "enrollment":
                return "enrollment_active"
            if kind == "shadow_evidence":
                return "shadow_evidence_active"
        return "idle"

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
        return "/tmp/bioauth-live-shadow-test"

    def _session_process_env(self):
        env = {"BIOAUTH_BASE": "test"}
        live_dir = str(getattr(self, "_active_live_session_dir", "") or "").strip()
        if live_dir:
            env["BIOAUTH_LIVE_SESSION_DIR"] = live_dir
        session_id = str(getattr(self, "_pending_logger_session_id", "") or "").strip()
        if session_id:
            env["BIOAUTH_SESSION_ID"] = session_id
        run_id = str(getattr(self, "_pending_logger_run_id", "") or "").strip()
        if run_id:
            env["BIOAUTH_RUN_ID"] = run_id
        return env

    def _start_process(self, key, args, extra_env=None):
        self.started.append((key, list(args), dict(extra_env or {})))
        return True

    def _clear_history_archive_watch(self):
        return None

    def _invalidate_dashboard_snapshot_cache(self):
        return None

    def _set_status(self, message, tone):
        self.statuses.append((message, tone))

    def _update_refresh_timer(self, force=False):
        self.refreshed.append(("timer", force))

    def requestRefresh(self, reason, force=False):
        self.refreshed.append((reason, force))


def _helpers(monkeypatch):
    import bridge.session_runtime_helpers as helpers

    fake_facade = _FakeFacade()
    monkeypatch.setattr(helpers, "_facade", lambda: fake_facade)
    return helpers, fake_facade


def _startable_app():
    return _FakeApp()



def test_developer_shadow_pause_blocks_auto_bootstrap(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._shadow_automation_paused = True
    assert helpers._shadow_evidence_block_reason(app) == "developer_shadow_paused"
    assert not helpers.start_shadow_evidence_monitor(app, trigger_refresh=False, auto_bootstrap=True)
    assert app.started == []
    assert app._last_shadow_evidence_monitor_block_reason == "developer_shadow_paused"


def test_developer_shadow_pause_ui_and_backend_wiring_present():
    qml = (ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml").read_text(encoding="utf-8")
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    settings = (ROOT / "bridge" / "settings_mixin.py").read_text(encoding="utf-8")
    assert 'visible: backend.uiMode !== "user"' in qml
    assert 'backend.setShadowAutomationPaused(!backend.shadowAutomationPaused)' in qml
    assert "def shadowAutomationPaused" in desktop
    assert "def setShadowAutomationPaused" in settings
    assert '"shadow_automation_paused"' in settings


def test_shadow_loop_state_reports_developer_pause():
    from metadata_core.shadow_loop import build_shadow_loop_state

    state = build_shadow_loop_state(
        profile={"candidate_model_status": "approved_for_shadow", "session_count": 3},
        production_approval={"modelStatus": "approved_for_shadow", "protectedSessionsAvailable": False},
        model_readiness={},
        sessions=[],
        shadow_status={"automation_paused": True},
        now=1000.0,
    )
    assert state["active"] is False
    assert state["automationPaused"] is True
    assert state["phase"] == "developer_paused"
    assert state["backgroundAction"] == "developer_shadow_paused"


def test_shadow_evidence_monitor_starts_for_approved_for_shadow(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _startable_app()
    assert helpers.start_shadow_evidence_monitor(app, trigger_refresh=False)
    key, args, env = app.started[-1]
    assert key == "shadow_logger_user_alice"
    assert args == [facade.LOGGER_SCRIPT, "alice", "shadow_evidence"]
    assert env["BIOAUTH_RUNTIME_MODE"] == "shadow_evidence"
    assert env["BIOAUTH_SHADOW_EVIDENCE_ONLY"] == "1"
    assert env["BIOAUTH_EVIDENCE_SOURCE"] == "shadow_evidence_monitor"


def test_shadow_evidence_monitor_does_not_require_production_ready(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._profile["production_ready"] = False
    assert helpers.start_shadow_evidence_monitor(app, trigger_refresh=False)


def test_shadow_evidence_monitor_does_not_enable_protected_sessions(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    assert helpers.start_shadow_evidence_monitor(app, trigger_refresh=False)
    assert app._profile["production_ready"] is False
    assert not any(args[2] == "protected" for _, args, _ in app.started)
    source = (ROOT / "bridge" / "session_runtime_helpers.py").read_text()
    start_shadow = source[source.index("def start_shadow_evidence_monitor"):source.index("def maybe_start_shadow_evidence_monitor")]
    assert "start_protected_session(" not in start_shadow


def test_shadow_evidence_monitor_blocks_when_training_active(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._training_in_progress = True
    assert helpers._shadow_evidence_block_reason(app) == "training_active"


def test_shadow_evidence_monitor_blocks_when_evaluation_active(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._training_progress = {"stage_key": "candidate_evaluation_running"}
    assert helpers._shadow_evidence_block_reason(app) == "evaluation_active"


def test_shadow_evidence_monitor_blocks_when_passive_enrollment_active(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._runtime_state = {"active": True, "session_kind": "enrollment", "auto_enrollment": True, "collection_source": "passive_auto_enrollment"}
    assert helpers._shadow_evidence_block_reason(app) == "passive_auto_enrollment_active"


def test_shadow_evidence_monitor_blocks_when_protected_session_active(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._runtime_state = {"active": True, "session_kind": "protected"}
    assert helpers._shadow_evidence_block_reason(app) == "protected_session_active"


def test_shadow_evidence_logger_uses_shadow_evidence_session_kind():
    source = (ROOT / "src" / "bioauth" / "input" / "logger_impl.py").read_text()
    assert 'SHADOW_EVIDENCE_SESSION_KIND = "shadow_evidence"' in source
    assert '"evidence_source": SHADOW_EVIDENCE_SOURCE' in source
    assert '"trust_level": "shadow_runtime"' in source
    assert 'shadow_logger_stop_control_name(safe_user) if session_kind == SHADOW_EVIDENCE_SESSION_KIND else f"logger_user_{safe_user}"' in source


def test_shadow_evidence_sessions_excluded_from_positive_training():
    source = (ROOT / "src" / "bioauth" / "input" / "logger_impl.py").read_text()
    assert '"excluded_from_positive_training": True' in source
    assert '"training_counts_toward_minimum": False' in source
    assert '"metadata_trusted": False' in source
    assert 'if ARGS["session_kind"] != "enrollment":' in source


def test_shadow_evidence_monitor_appends_privacy_safe_evidence_records(monkeypatch, tmp_path):
    from evaluation_core.production_evidence import assert_privacy_safe_payload
    from metadata_core import production_evidence_pipeline as pipe

    ledger = tmp_path / "records.jsonl"
    monkeypatch.setattr(pipe, "evidence_ledger_path", lambda user_id: str(ledger))
    record = pipe.append_runtime_monitor_evidence_record(
        user_id="alice",
        state={
            "session_id": "s1",
            "runtime_telemetry_seq": 7,
            "session_kind": "shadow_evidence",
            "runtime_mode": "shadow_evidence",
            "evidence_source": "shadow_evidence_monitor",
            "model_decision": "legit",
            "risk": 12,
            "runtime_quality_ok_windows": 2,
            "runtime_low_quality_windows": 0,
        },
        runtime={"metadata": {"runtime_schema_version": "v1", "artifact_digest": "sha256:candidate"}, "paths": {}},
        prediction={"final": "legit"},
    )
    assert_privacy_safe_payload(record)
    assert record["source"] == "shadow_evidence_monitor"
    assert record["candidate_decision"] == "trusted"
    forbidden = {"keyboard_events", "mouse_events", "feature_vector", "feature_values"}
    assert forbidden.isdisjoint(record.keys())


def test_shadow_evidence_would_lock_is_simulated_not_enforced(monkeypatch, tmp_path):
    from metadata_core import production_evidence_pipeline as pipe

    ledger = tmp_path / "records.jsonl"
    monkeypatch.setattr(pipe, "evidence_ledger_path", lambda user_id: str(ledger))
    record = pipe.append_runtime_monitor_evidence_record(
        user_id="alice",
        state={
            "session_id": "s-lock",
            "session_kind": "shadow_evidence",
            "runtime_mode": "shadow_evidence",
            "candidate_would_lock_if_production": True,
            "app_locked": False,
            "screen_locked": False,
            "model_decision": "intruder",
            "risk": 92,
        },
        runtime={"metadata": {"runtime_schema_version": "v1", "artifact_digest": "sha256:candidate"}},
        prediction={"final": "intruder"},
    )
    assert record["candidate_would_lock_if_production"] is True
    assert record["source"] == "shadow_evidence_monitor"
    assert "shadow_evidence_lock_suppressed" in record["reason_codes"]
    source = (ROOT / "src" / "bioauth" / "runtime" / "monitor_impl.py").read_text()
    assert "if confirmed_intruder and not _shadow_evidence_mode():" in source


def test_shadow_evidence_missing_baseline_keeps_evidence_partial(monkeypatch, tmp_path):
    from evaluation_core.production_evidence import ProductionEvidenceStatus
    from metadata_core import production_evidence_pipeline as pipe

    ledger = tmp_path / "records.jsonl"
    monkeypatch.setattr(pipe, "evidence_ledger_path", lambda user_id: str(ledger))
    pipe.append_runtime_monitor_evidence_record(
        user_id="alice",
        state={"session_id": "s-partial", "session_kind": "shadow_evidence", "runtime_mode": "shadow_evidence", "model_decision": "legit", "risk": 10, "runtime_quality_ok_windows": 1},
        runtime={"metadata": {"runtime_schema_version": "v1", "artifact_digest": "sha256:candidate"}},
        prediction={"final": "legit"},
    )
    report = pipe.build_production_evidence_report_from_records(pipe.read_evidence_records("alice", ledger_path=str(ledger)))
    assert report.gate.status is not ProductionEvidenceStatus.PASS
    assert "baseline_decision_missing" in report.gate.reason_codes


def test_shadow_evidence_pipeline_updates_windows_collected(monkeypatch, tmp_path):
    from metadata_core import production_evidence_pipeline as pipe

    ledger = tmp_path / "records.jsonl"
    monkeypatch.setattr(pipe, "evidence_ledger_path", lambda user_id: str(ledger))
    pipe.append_runtime_monitor_evidence_record(
        user_id="alice",
        state={"session_id": "s-window", "runtime_telemetry_seq": 1, "session_kind": "shadow_evidence", "runtime_mode": "shadow_evidence", "model_decision": "legit", "risk": 8, "runtime_quality_ok_windows": 1},
        runtime={"metadata": {"runtime_schema_version": "v1", "artifact_digest": "sha256:candidate"}},
        prediction={"final": "legit"},
    )
    summaries = pipe.aggregate_evidence_records(pipe.read_evidence_records("alice", ledger_path=str(ledger)))
    assert summaries["pipeline_record_count"] == 1
    assert len(summaries["runtime_decision_summaries"]) == 1


def test_shadow_evidence_runtime_schema_mismatch_fails_closed():
    from metadata_core import production_evidence_pipeline as pipe

    summaries = pipe.aggregate_evidence_records([
        {
            "window_id": "schema-bad",
            "user_id": "alice",
            "session_kind": "shadow_evidence",
            "candidate_decision": "trusted",
            "runtime_schema_version": "old",
            "schema_ok": False,
            "source": "shadow_evidence_monitor",
        }
    ], runtime_schema_version="v1")
    assert "runtime_schema_mismatch" in summaries["pipeline_reason_codes"]
    assert summaries["pipeline_accepted_record_count"] == 0


def test_qml_does_not_compute_runtime_or_production_readiness():
    qml = "\n".join(path.read_text(errors="ignore") for path in (ROOT / "qml").rglob("*.qml"))
    forbidden = r"(productionReady|protectedSessionsAvailable|modelReady|approvalPassed)\s*:|var\s+(productionReady|protectedSessionsAvailable|modelReady|approvalPassed)\b|function\s+(productionReady|protectedSessionsAvailable|modelReady|approvalPassed)\b"
    assert not re.search(forbidden, qml)


def test_existing_protected_session_start_still_requires_backend_owned_real_production_readiness():
    source = (ROOT / "bridge" / "session_runtime_helpers.py").read_text()
    protected = source[source.index("def start_protected_session"):source.index("def stop_current_session")]
    assert 'if not bool(profile.get("production_ready"))' in protected
    assert 'profile.get("production_ready")' in source
    assert 'session_kind": "protected"' in protected


def test_existing_protected_session_monitor_still_starts_for_production_ready():
    source = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text()
    assert 'expected_kind = "shadow_evidence" if pending_shadow else "protected"' in source
    assert 'if pending_shadow:' in source
    assert 'BIOAUTH_SHADOW_EVIDENCE_ONLY' in source
    assert 'monitor_key = _shadow_monitor_process_key(self) if pending_shadow else "monitor"' in source


def test_training_and_shadow_evidence_monitor_never_overlap(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._training_in_progress = True
    assert not helpers.start_shadow_evidence_monitor(app, trigger_refresh=False)
    assert not app.started


def test_passive_enrollment_and_shadow_evidence_monitor_never_overlap(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._pending_passive_auto_enrollment = True
    assert not helpers.start_shadow_evidence_monitor(app, trigger_refresh=False)
    assert not app.started


def test_evidence_pass_still_does_not_unlock_protected_sessions():
    helper_source = (ROOT / "bridge" / "session_runtime_helpers.py").read_text()
    pipeline_source = (ROOT / "metadata_core" / "production_evidence_pipeline.py").read_text()
    assert "protectedSessionsAvailable" not in pipeline_source
    assert "productionReady" not in pipeline_source
    shadow_start = helper_source[helper_source.index("def start_shadow_evidence_monitor"):helper_source.index("def maybe_start_shadow_evidence_monitor")]
    assert "production_ready" not in shadow_start or "production_ready_use_protected_sessions" in shadow_start


class _FakeProcess:
    def __init__(self, alive=True, exit_code=None):
        self.alive = alive
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return None if self.alive else self.exit_code

    def terminate(self):
        self.terminated = True
        self.alive = False
        self.exit_code = -15


def _refresh_helpers(monkeypatch):
    import bridge.refresh_runtime_helpers as helpers

    fake_facade = _FakeFacade()
    fake_facade.last_written_state = {}
    monkeypatch.setattr(helpers, "_facade", lambda: fake_facade)
    monkeypatch.setattr(helpers._process_helpers, "worker_diagnostics_snapshot", lambda *_args, **_kwargs: {"exit_code": None, "stderr_tail": [], "stdout_tail": []})
    monkeypatch.setattr(helpers._process_helpers, "worker_failure_detail", lambda *_args, fallback="monitor_failed", **_kwargs: (fallback, {"exit_code": None, "stderr_tail": [], "stdout_tail": []}))
    return helpers, fake_facade


def _pending_shadow_refresh_app():
    app = _startable_app()
    app._pending_shadow_evidence_monitor_start = True
    app._shadow_evidence_monitor_user_id = "alice"
    app._shadow_evidence_monitor_start_deadline = _time.time() + 30.0
    app._runtime_state = {
        "active": True,
        "session_kind": "shadow_evidence",
        "mode": "shadow_evidence",
        "logger_ready": True,
        "monitor_ready": False,
        "user_id": "alice",
    }
    app._running_processes[app._shadow_logger_process_key()] = _FakeProcess(alive=True)
    return app


def test_shadow_evidence_fail_helper_exists_on_app_bridge():
    desktop_source = (ROOT / "desktop_app.py").read_text()
    refresh_source = (ROOT / "bridge" / "refresh_mixin.py").read_text()
    assert "class AppBridge(AuthMixin, SessionMixin, SettingsMixin, RefreshMixin" in desktop_source
    assert "def _fail_pending_shadow_evidence_monitor_start" in refresh_source
    assert "fail_pending_shadow_evidence_monitor_start(self" in refresh_source


def test_shadow_evidence_monitor_start_no_attribute_error_on_refresh(monkeypatch):
    helpers, _ = _refresh_helpers(monkeypatch)
    app = _pending_shadow_refresh_app()
    app._fail_pending_shadow_evidence_monitor_start = lambda **kwargs: helpers.fail_pending_shadow_evidence_monitor_start(app, **kwargs)
    helpers.maybe_finish_pending_monitor_start(app)
    assert app.started
    assert app.started[-1][0] == "shadow_monitor_user_alice"
    assert app.started[-1][2]["BIOAUTH_RUNTIME_MODE"] == "shadow_evidence"


def test_shadow_evidence_monitor_failure_clears_pending_state(monkeypatch):
    helpers, _ = _refresh_helpers(monkeypatch)
    app = _pending_shadow_refresh_app()
    helpers.fail_pending_shadow_evidence_monitor_start(app, reason="monitor_start_timeout")
    assert app._pending_shadow_evidence_monitor_start is False
    assert app._shadow_evidence_monitor_start_deadline == 0.0
    assert app._shadow_evidence_monitor_launch_attempted is False
    assert app._shadow_evidence_monitor_failed is True


def test_shadow_evidence_monitor_failure_keeps_protected_sessions_unavailable(monkeypatch):
    helpers, facade = _refresh_helpers(monkeypatch)
    app = _pending_shadow_refresh_app()
    helpers.fail_pending_shadow_evidence_monitor_start(app, reason="monitor_start_timeout")
    assert app._profile["production_approval_state"]["protectedSessionsAvailable"] is False
    assert facade.last_written_state["session_kind"] == "shadow_evidence"
    assert facade.last_written_state["runtime_mode"] == "shadow_evidence"


def test_shadow_evidence_monitor_failure_does_not_set_production_ready(monkeypatch):
    helpers, _ = _refresh_helpers(monkeypatch)
    app = _pending_shadow_refresh_app()
    helpers.fail_pending_shadow_evidence_monitor_start(app, reason="monitor_start_timeout")
    assert app._profile["production_ready"] is False
    assert app._profile["production_approval_state"]["productionReady"] is False
    assert app._profile["candidate_model_status"] == "approved_for_shadow"


def test_shadow_evidence_monitor_failure_does_not_use_start_protected_session():
    source = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text()
    fail_block = source[source.index("def fail_pending_shadow_evidence_monitor_start"):source.index("def fail_pending_monitor_start")]
    assert "start_protected_session" not in fail_block
    maybe_block = source[source.index("def maybe_finish_pending_monitor_start"):source.index("_CRITICAL_REFRESH_REASON_TOKENS")]
    assert "start_protected_session" not in maybe_block


def test_shadow_evidence_monitor_success_path_still_starts_monitor(monkeypatch):
    helpers, _ = _refresh_helpers(monkeypatch)
    app = _pending_shadow_refresh_app()
    app._fail_pending_shadow_evidence_monitor_start = lambda **kwargs: helpers.fail_pending_shadow_evidence_monitor_start(app, **kwargs)
    helpers.maybe_finish_pending_monitor_start(app)
    key, args, env = app.started[-1]
    assert key == "shadow_monitor_user_alice"
    assert args == ["monitor.py", "alice"]
    assert env["BIOAUTH_RUNTIME_MODE"] == "shadow_evidence"
    assert env["BIOAUTH_SHADOW_EVIDENCE_ONLY"] == "1"
    assert app._shadow_evidence_monitor_launch_attempted is True
    assert app._pending_monitor_start is False


def test_existing_protected_monitor_start_path_unchanged():
    source = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text()
    assert "pending_shadow = bool(getattr(self, \"_pending_shadow_evidence_monitor_start\", False))" in source
    assert "fail = self._fail_pending_shadow_evidence_monitor_start if pending_shadow else self._fail_pending_monitor_start" in source
    assert "env.update({\"BIOAUTH_RUNTIME_MODE\": \"shadow_evidence\"" in source
    assert "else:\n            self._monitor_launch_attempted = True" in source


def test_shadow_evidence_logger_started_then_monitor_timeout_reports_safe_reason(monkeypatch):
    helpers, facade = _refresh_helpers(monkeypatch)
    app = _pending_shadow_refresh_app()
    app._fail_pending_shadow_evidence_monitor_start = lambda **kwargs: helpers.fail_pending_shadow_evidence_monitor_start(app, **kwargs)
    app._running_processes[app._shadow_monitor_process_key()] = _FakeProcess(alive=True)
    app._shadow_evidence_monitor_start_deadline = 0.0
    helpers.maybe_finish_pending_monitor_start(app)
    assert app._pending_shadow_evidence_monitor_start is False
    assert app._last_shadow_evidence_monitor_block_reason == "monitor_start_timeout"
    assert facade.last_written_state["shadow_evidence_blocked_reason"] == "monitor_start_timeout"
    assert facade.last_written_state["status"] == "shadow_evidence_failed"
    assert app.statuses[-1][1] == "warn"


def test_refresh_loop_recovers_after_shadow_evidence_monitor_failure(monkeypatch):
    helpers, _ = _refresh_helpers(monkeypatch)
    app = _pending_shadow_refresh_app()
    helpers.fail_pending_shadow_evidence_monitor_start(app, reason="monitor_start_timeout")
    start_count = len(app.started)
    helpers.maybe_finish_pending_monitor_start(app)
    assert len(app.started) == start_count
    assert app._pending_shadow_evidence_monitor_start is False
    assert app.refreshed[-1] == ("timer", True)


def test_shadow_evidence_logger_already_running_does_not_fail_bootstrap(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _startable_app()
    app._runtime_state = {
        "active": True,
        "session_kind": "shadow_evidence",
        "mode": "shadow_evidence",
        "logger_ready": False,
        "monitor_ready": False,
        "status": "shadow_evidence_failed",
        "technical_failure": True,
        "user_id": "alice",
        "live_session_dir": "/tmp/bioauth-live-shadow-test",
        "session_id": "session-existing",
        "run_id": "run-existing",
    }
    app._running_processes[app._shadow_logger_process_key()] = _FakeProcess(alive=True)
    assert helpers.start_shadow_evidence_monitor(app, trigger_refresh=False, auto_bootstrap=True)
    assert app._pending_shadow_evidence_monitor_start is True
    assert app._shadow_evidence_monitor_failed is False
    assert app._last_shadow_evidence_monitor_block_reason == ""
    assert facade.last_written_state["status"] == "starting"
    assert facade.last_written_state["technical_failure"] is False
    assert not any(call[1] == [facade.LOGGER_SCRIPT, "alice", "shadow_evidence"] for call in app.started)


def test_shadow_evidence_monitor_launches_after_logger_ready(monkeypatch):
    helpers, _ = _refresh_helpers(monkeypatch)
    app = _pending_shadow_refresh_app()
    app._fail_pending_shadow_evidence_monitor_start = lambda **kwargs: helpers.fail_pending_shadow_evidence_monitor_start(app, **kwargs)
    helpers.maybe_finish_pending_monitor_start(app)
    assert app.started[-1][0] == "shadow_monitor_user_alice"
    assert app.started[-1][1] == ["monitor.py", "alice"]
    assert app._shadow_evidence_monitor_launch_attempted is True


def test_shadow_evidence_duplicate_logger_launch_still_allows_monitor_start(monkeypatch):
    start_helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._runtime_state = {
        "active": True,
        "session_kind": "shadow_evidence",
        "mode": "shadow_evidence",
        "logger_ready": True,
        "monitor_ready": False,
        "status": "ok",
        "user_id": "alice",
        "live_session_dir": "/tmp/bioauth-live-shadow-test",
        "session_id": "session-existing",
        "run_id": "run-existing",
    }
    app._running_processes[app._shadow_logger_process_key()] = _FakeProcess(alive=True)
    assert start_helpers.start_shadow_evidence_monitor(app, trigger_refresh=False, auto_bootstrap=True)
    assert app._pending_shadow_evidence_monitor_start is True
    assert app.started == []
    refresh_helpers, _ = _refresh_helpers(monkeypatch)
    app._fail_pending_shadow_evidence_monitor_start = lambda **kwargs: refresh_helpers.fail_pending_shadow_evidence_monitor_start(app, **kwargs)
    refresh_helpers.maybe_finish_pending_monitor_start(app)
    assert app.started[-1][0] == "shadow_monitor_user_alice"


def test_shadow_evidence_monitor_already_running_marks_active_not_failed(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _startable_app()
    app._runtime_state = {
        "active": True,
        "session_kind": "shadow_evidence",
        "mode": "shadow_evidence",
        "logger_ready": True,
        "monitor_ready": True,
        "status": "ok",
        "user_id": "alice",
    }
    app._running_processes[app._shadow_logger_process_key()] = _FakeProcess(alive=True)
    app._running_processes[app._shadow_monitor_process_key()] = _FakeProcess(alive=True)
    assert helpers.start_shadow_evidence_monitor(app, trigger_refresh=False, auto_bootstrap=True)
    assert app._pending_shadow_evidence_monitor_start is False
    assert app._shadow_evidence_monitor_failed is False
    assert facade.last_written_state["status"] == "shadow_evidence"
    assert facade.last_written_state["technical_failure"] is False
    assert not app.started


def test_shadow_evidence_logger_ready_timeout_fails_safely(monkeypatch):
    helpers, facade = _refresh_helpers(monkeypatch)
    app = _pending_shadow_refresh_app()
    app._runtime_state["logger_ready"] = False
    app._shadow_evidence_monitor_start_deadline = 0.0
    app._fail_pending_shadow_evidence_monitor_start = lambda **kwargs: helpers.fail_pending_shadow_evidence_monitor_start(app, **kwargs)
    helpers.maybe_finish_pending_monitor_start(app)
    assert app._pending_shadow_evidence_monitor_start is False
    assert app._last_shadow_evidence_monitor_block_reason in {"monitor_start_timeout", "logger_ready_timeout"}
    assert facade.last_written_state["session_kind"] == "shadow_evidence"
    assert app._profile["production_approval_state"]["protectedSessionsAvailable"] is False


def test_shadow_evidence_monitor_launch_failure_fails_safely_without_crashing_refresh(monkeypatch):
    helpers, facade = _refresh_helpers(monkeypatch)
    app = _pending_shadow_refresh_app()
    app._fail_pending_shadow_evidence_monitor_start = lambda **kwargs: helpers.fail_pending_shadow_evidence_monitor_start(app, **kwargs)

    def fail_start(key, args, extra_env=None):
        app.started.append((key, list(args), dict(extra_env or {})))
        return False

    app._start_process = fail_start
    helpers.maybe_finish_pending_monitor_start(app)
    assert app._pending_shadow_evidence_monitor_start is False
    assert app._shadow_evidence_monitor_failed is True
    assert facade.last_written_state["status"] == "shadow_evidence_failed"
    assert app._profile["production_ready"] is False


def test_shadow_evidence_flow_not_stuck_failed_with_only_logger_running(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _startable_app()
    app._runtime_state = {
        "active": True,
        "session_kind": "shadow_evidence",
        "mode": "shadow_evidence",
        "logger_ready": True,
        "monitor_ready": False,
        "status": "shadow_evidence_failed",
        "technical_failure": True,
        "user_id": "alice",
        "live_session_dir": "/tmp/bioauth-live-shadow-test",
    }
    app._running_processes[app._shadow_logger_process_key()] = _FakeProcess(alive=True)
    assert helpers.start_shadow_evidence_monitor(app, trigger_refresh=False, auto_bootstrap=True)
    assert facade.last_written_state["status"] == "starting"
    assert facade.last_written_state["technical_failure"] is False
    assert app._shadow_evidence_monitor_failed is False


def test_shadow_evidence_monitor_uses_shadow_evidence_env(monkeypatch):
    helpers, _ = _refresh_helpers(monkeypatch)
    app = _pending_shadow_refresh_app()
    app._pending_logger_session_id = "session-existing"
    app._pending_logger_run_id = "run-existing"
    app._active_live_session_dir = "/tmp/bioauth-live-shadow-test"
    app._fail_pending_shadow_evidence_monitor_start = lambda **kwargs: helpers.fail_pending_shadow_evidence_monitor_start(app, **kwargs)
    helpers.maybe_finish_pending_monitor_start(app)
    env = app.started[-1][2]
    assert env["BIOAUTH_RUNTIME_MODE"] == "shadow_evidence"
    assert env["BIOAUTH_SHADOW_EVIDENCE_ONLY"] == "1"
    assert env["BIOAUTH_EVIDENCE_SOURCE"] == "shadow_evidence_monitor"
    assert env["BIOAUTH_LIVE_SESSION_DIR"] == "/tmp/bioauth-live-shadow-test"
    assert env["BIOAUTH_SESSION_ID"] == "session-existing"
    assert env["BIOAUTH_RUN_ID"] == "run-existing"


def test_shadow_evidence_monitor_does_not_use_start_protected_session():
    source = (ROOT / "bridge" / "session_runtime_helpers.py").read_text()
    shadow_block = source[source.index("def start_shadow_evidence_monitor"):source.index("def maybe_start_shadow_evidence_monitor")]
    assert "start_protected_session" not in shadow_block
    refresh_source = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text()
    maybe_block = refresh_source[refresh_source.index("def maybe_finish_pending_monitor_start"):refresh_source.index("_CRITICAL_REFRESH_REASON_TOKENS")]
    assert "start_protected_session" not in maybe_block


def test_shadow_evidence_monitor_does_not_lock_app_or_workstation():
    source = (ROOT / "src" / "bioauth" / "runtime" / "monitor_impl.py").read_text()
    assert "_shadow_evidence_mode" in source
    assert "if confirmed_intruder and not _shadow_evidence_mode():" in source
    assert "shadow_evidence_lock_suppressed" in source
    assert "CONTROL_NAME = shadow_monitor_stop_control_name" in source
    assert "else \"monitor\"" in source


def test_shadow_evidence_runtime_window_count_can_increment_from_monitor_status(monkeypatch, tmp_path):
    from metadata_core import production_evidence_pipeline as pipe

    ledger_path = tmp_path / "window_count.jsonl"
    monkeypatch.setattr(pipe, "evidence_ledger_path", lambda user_id: str(ledger_path))
    record = pipe.append_runtime_monitor_evidence_record(
        user_id="alice",
        state={
            "session_id": "win-count",
            "runtime_telemetry_seq": 2,
            "session_kind": "shadow_evidence",
            "runtime_mode": "shadow_evidence",
            "evidence_source": "shadow_evidence_monitor",
            "runtime_quality_ok_windows": 1,
            "runtime_low_quality_windows": 0,
            "model_decision": "legit",
            "risk": 9,
        },
        runtime={"metadata": {"runtime_schema_version": "v1", "artifact_digest": "sha256:candidate"}},
        prediction={"final": "legit"},
    )
    summary = pipe.aggregate_evidence_records([record])
    assert len(summary["runtime_decision_summaries"]) >= 1


def test_shadow_evidence_evidence_records_can_be_appended_after_monitor_start(monkeypatch, tmp_path):
    from metadata_core import production_evidence_pipeline as pipe

    ledger = tmp_path / "shadow_records.jsonl"
    monkeypatch.setattr(pipe, "evidence_ledger_path", lambda user_id: str(ledger))
    pipe.append_runtime_monitor_evidence_record(
        user_id="alice",
        state={
            "session_id": "after-monitor",
            "runtime_telemetry_seq": 3,
            "session_kind": "shadow_evidence",
            "runtime_mode": "shadow_evidence",
            "evidence_source": "shadow_evidence_monitor",
            "model_decision": "legit",
            "risk": 11,
        },
        runtime={"metadata": {"runtime_schema_version": "v1", "artifact_digest": "sha256:candidate"}},
        prediction={"final": "legit"},
    )
    records = pipe.read_evidence_records("alice", ledger_path=str(ledger))
    assert len(records) == 1
    assert records[0]["source"] == "shadow_evidence_monitor"


def test_shadow_evidence_runtime_monitor_ledger_can_be_forced_to_shadow_path(monkeypatch, tmp_path):
    from metadata_core import production_evidence_pipeline as pipe

    production_ledger = tmp_path / "production" / "records.jsonl"
    shadow_ledger = tmp_path / "shadow" / "shadow_evidence.jsonl"
    monkeypatch.setattr(pipe, "evidence_ledger_path", lambda user_id: str(production_ledger))
    pipe.append_runtime_monitor_evidence_record(
        user_id="alice",
        state={
            "session_id": "shadow-ledger-only",
            "runtime_telemetry_seq": 4,
            "session_kind": "shadow_evidence",
            "runtime_mode": "shadow_evidence",
            "evidence_source": "shadow_evidence_monitor",
            "model_decision": "legit",
            "risk": 7,
        },
        runtime={"metadata": {"runtime_schema_version": "v1", "artifact_digest": "sha256:candidate"}},
        prediction={"final": "legit"},
        ledger_path=str(shadow_ledger),
    )
    assert shadow_ledger.exists()
    assert not production_ledger.exists()
    records = pipe.read_evidence_records("alice", ledger_path=str(shadow_ledger))
    assert len(records) == 1
    assert records[0]["source"] == "shadow_evidence_monitor"


def test_training_active_blocks_shadow_evidence_monitor_launch(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._training_in_progress = True
    assert helpers._shadow_evidence_block_reason(app) == "training_active"
    assert not helpers.start_shadow_evidence_monitor(app, trigger_refresh=False, auto_bootstrap=True)


def test_evaluation_active_blocks_shadow_evidence_monitor_launch(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._training_progress = {"stage_key": "candidate_evaluation_running"}
    assert helpers._shadow_evidence_block_reason(app) == "evaluation_active"
    assert not helpers.start_shadow_evidence_monitor(app, trigger_refresh=False, auto_bootstrap=True)


def test_passive_enrollment_active_blocks_shadow_evidence_monitor_launch(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._pending_passive_auto_enrollment = True
    assert helpers._shadow_evidence_block_reason(app) == "passive_auto_enrollment_active"
    assert not helpers.start_shadow_evidence_monitor(app, trigger_refresh=False, auto_bootstrap=True)


def test_protected_session_active_blocks_shadow_evidence_monitor_launch(monkeypatch):
    helpers, _ = _helpers(monkeypatch)
    app = _startable_app()
    app._runtime_state = {"active": True, "session_kind": "protected", "monitor_ready": True, "user_id": "alice"}
    assert helpers._shadow_evidence_block_reason(app) == "protected_session_active"
    assert not helpers.start_shadow_evidence_monitor(app, trigger_refresh=False, auto_bootstrap=True)


def test_qml_remains_display_only_for_runtime_and_readiness():
    qml = "\n".join(path.read_text(errors="ignore") for path in (ROOT / "qml").rglob("*.qml"))
    forbidden = r"(productionReady|protectedSessionsAvailable|modelReady|approvalPassed)\s*:|var\s+(productionReady|protectedSessionsAvailable|modelReady|approvalPassed)\b|function\s+(productionReady|protectedSessionsAvailable|modelReady|approvalPassed)\b"
    assert not re.search(forbidden, qml)
