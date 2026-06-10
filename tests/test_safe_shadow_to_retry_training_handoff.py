from __future__ import annotations

import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metadata_core.auto_training_scheduler import auto_training_should_start
from metadata_core.training_attempts import remediation_training_signature


def _settings():
    return {"auto_train_when_ready_enabled": True, "smart_auto_enrollment_enabled": True}


def _profile():
    return {"training_can_start": True, "production_ready": False, "session_count": 8, "minimum_session_count": 8}


def _sessions():
    return [
        {
            "session_kind": "enrollment",
            "metadata_trusted": True,
            "bucket": "accepted",
            "session_id": "s1",
            "training_counts_toward_minimum": True,
        }
    ]


def _plan(required: int = 5):
    return {
        "retry_eligibility": "requires_new_evidence",
        "action": "collect_more_shadow_comparison_windows",
        "required_new_evidence": {"shadow_comparison_windows": required},
        "current_new_evidence": {},
        "candidate_artifact_digest": "sha256:candidate",
        "evidence_report_digest": "sha256:report",
        "training_data_signature": "sha256:training-data",
        "source_gate": "production_evidence_gate_v2",
    }


def _runtime_shadow(*, logger: bool = True, monitor: bool = True, active: bool = True, handoff: str = ""):
    return {
        "active": active,
        "session_kind": "shadow_evidence",
        "evidence_source": "shadow_evidence_monitor",
        "logger_process_alive": logger,
        "monitor_process_alive": monitor,
        "retry_handoff_state": handoff,
    }


def _scheduler(**overrides):
    params = dict(
        settings=_settings(),
        profile=_profile(),
        runtime_state={},
        sessions=_sessions(),
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        evaluation_active=False,
        remediation_plan=_plan(),
        remediation_current_new_evidence={"shadow_comparison_windows": 5},
        production_evidence_summary={},
        now=1000.0,
    )
    params.update(overrides)
    return auto_training_should_start(**params)


class _Proc:
    def __init__(self, alive: bool = True):
        self.alive = alive
        self.terminated = False

    def poll(self):
        return None if self.alive else 0


class _Signal:
    def emit(self, *args, **kwargs):
        return None


class _FakeFacade:
    MONITOR_START_GRACE_SEC = 5.0
    LOGGER_SCRIPT = "logger.py"
    MONITOR_SCRIPT = "monitor.py"
    time = types.SimpleNamespace(time=lambda: 1000.0)

    def __init__(self, bridge=None, *, fail_stop: bool = False):
        self.bridge = bridge
        self.fail_stop = fail_stop
        self.stop_requests = []
        self.clear_requests = []
        self.written_states = []
        self.cache_invalidated = False

    def request_stop(self, name):
        if self.fail_stop:
            raise RuntimeError("stop unavailable")
        self.stop_requests.append(name)

    def clear_stop(self, name):
        self.clear_requests.append(name)

    def write_session_state(self, state):
        self.written_states.append(dict(state or {}))
        if self.bridge is not None:
            self.bridge.state = dict(state or {})
            self.bridge._runtime_state = dict(state or {})

    def invalidate_session_discovery_cache(self):
        self.cache_invalidated = True


class _FakeBridge:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self.state = {
            "active": True,
            "user_id": "alice",
            "session_kind": "shadow_evidence",
            "mode": "shadow_evidence",
            "runtime_mode": "shadow_evidence",
            "evidence_source": "shadow_evidence_monitor",
            "logger_ready": True,
            "monitor_ready": True,
            "status": "shadow_evidence",
            "excluded_from_positive_training": True,
            "training_counts_toward_minimum": False,
            "owner_positive_training_allowed": False,
        }
        self._runtime_state = dict(self.state)
        self._running_processes = {"shadow_logger_user_alice": _Proc(True), "shadow_monitor_user_alice": _Proc(True)}
        self._training_in_progress = False
        self._training_progress = {}
        self._evaluation_in_progress = False
        self._candidate_evaluation_active = False
        self._model_evaluation_active = False
        self._passive_auto_enrollment_finalizing = False
        self._history_sync_pending = False
        self._pending_passive_auto_enrollment = False
        self._pending_monitor_start = False
        self._pending_shadow_evidence_monitor_start = False
        self._retry_handoff_state = "idle"
        self._retry_handoff_blockers = []
        self._retry_handoff_last_error = ""
        self._shadow_evidence_stopped_for_retry = False
        self.statuses = []
        self.refreshes = []
        self.history_watch_started = False
        self.controlsChanged = _Signal()

    def _safe_user(self):
        return "alice"

    def _logger_key(self):
        return "logger_user_alice"

    def _logger_process_key(self):
        return "logger_user_alice"

    def _active_state_for_current_user(self):
        return dict(self.state)

    def _clear_pending_monitor_start(self):
        self._pending_monitor_start = False

    def _clear_pending_shadow_evidence_monitor_start(self):
        self._pending_shadow_evidence_monitor_start = False

    def _begin_history_archive_watch(self, *args, **kwargs):
        self.history_watch_started = True

    def _invalidate_dashboard_snapshot_cache(self):
        return None

    def _set_status(self, message, tone="info"):
        self.statuses.append((message, tone))

    def _update_refresh_timer(self, force=False):
        self.refreshes.append(("timer", force))

    def requestRefresh(self, reason, force=False):
        self.refreshes.append((reason, force))

    def _debug_trace(self, *args, **kwargs):
        return None


def _patch_facade(monkeypatch, bridge, *, fail_stop: bool = False):
    import bridge.session_runtime_helpers as helpers

    facade = _FakeFacade(bridge, fail_stop=fail_stop)
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    return helpers, facade


def test_retry_training_not_allowed_while_shadow_monitor_running():
    allowed, reason, _signature = _scheduler(runtime_state=_runtime_shadow())
    assert allowed is False
    assert reason == "shadow_evidence_handoff_required"


def test_retry_training_not_allowed_while_logger_running():
    allowed, reason, _signature = _scheduler(runtime_state=_runtime_shadow(monitor=False, logger=True))
    assert allowed is False
    assert reason == "shadow_evidence_handoff_required"


def test_shadow_evidence_stops_before_retry_training_allowed(monkeypatch):
    bridge = _FakeBridge()
    helpers, facade = _patch_facade(monkeypatch, bridge)
    assert helpers.request_shadow_evidence_stop_for_retry(bridge) is True
    assert "shadow_monitor_user_alice" in facade.stop_requests
    assert "shadow_logger_user_alice" in facade.stop_requests
    assert "monitor" not in facade.stop_requests
    assert "logger_user_alice" not in facade.stop_requests
    assert bridge._retry_handoff_state == "shadow_evidence_settling_for_retry"
    assert bridge.state["retry_handoff_state"] == "shadow_evidence_settling_for_retry"
    assert bridge.state["excluded_from_positive_training"] is True
    assert bridge.state["training_counts_toward_minimum"] is False


def test_shadow_evidence_stop_for_retry_preserves_evidence_ledger(monkeypatch, tmp_path):
    ledger = tmp_path / "production_evidence_records.jsonl"
    ledger.write_text('{"safe":"record"}\n', encoding="utf-8")
    bridge = _FakeBridge()
    helpers, _facade = _patch_facade(monkeypatch, bridge)
    assert helpers.request_shadow_evidence_stop_for_retry(bridge) is True
    assert ledger.exists()
    assert ledger.read_text(encoding="utf-8") == '{"safe":"record"}\n'


def test_shadow_evidence_session_excluded_from_positive_training_after_stop(monkeypatch):
    bridge = _FakeBridge()
    helpers, _facade = _patch_facade(monkeypatch, bridge)
    assert helpers.request_shadow_evidence_stop_for_retry(bridge) is True
    state = bridge.state
    assert state["excluded_from_positive_training"] is True
    assert state["training_counts_toward_minimum"] is False
    assert state["owner_positive_training_allowed"] is False


def test_stop_failure_blocks_retry_training(monkeypatch):
    bridge = _FakeBridge()
    helpers, _facade = _patch_facade(monkeypatch, bridge, fail_stop=True)
    assert helpers.request_shadow_evidence_stop_for_retry(bridge) is False
    assert bridge._retry_handoff_state == "blocked"
    assert bridge._retry_handoff_blockers == ["stop_request_failed"]


def test_training_active_blocks_shadow_evidence_stop_restart_loop(monkeypatch):
    bridge = _FakeBridge()
    bridge._training_in_progress = True
    helpers, _facade = _patch_facade(monkeypatch, bridge)
    assert helpers.request_shadow_evidence_stop_for_retry(bridge) is False
    assert bridge._retry_handoff_blockers == ["training_active"]


def test_evaluation_active_blocks_retry_handoff(monkeypatch):
    bridge = _FakeBridge()
    bridge._training_progress = {"stage_key": "candidate_evaluation_running"}
    helpers, _facade = _patch_facade(monkeypatch, bridge)
    assert helpers.request_shadow_evidence_stop_for_retry(bridge) is False
    assert bridge._retry_handoff_blockers == ["evaluation_active"]


def test_passive_enrollment_active_blocks_retry_handoff(monkeypatch):
    bridge = _FakeBridge()
    bridge._runtime_state = {"active": True, "session_kind": "enrollment", "auto_enrollment": True, "collection_source": "passive_auto_enrollment"}
    helpers, _facade = _patch_facade(monkeypatch, bridge)
    assert helpers.request_shadow_evidence_stop_for_retry(bridge) is False
    assert bridge._retry_handoff_blockers == ["passive_auto_enrollment_active"]


def test_protected_session_active_blocks_retry_handoff(monkeypatch):
    bridge = _FakeBridge()
    bridge.state = {"active": True, "session_kind": "protected", "user_id": "alice"}
    bridge._runtime_state = dict(bridge.state)
    helpers, _facade = _patch_facade(monkeypatch, bridge)
    assert helpers.request_shadow_evidence_stop_for_retry(bridge) is False
    assert bridge._retry_handoff_blockers == ["protected_session_active"]


def test_new_evidence_signature_required_for_retry_after_handoff():
    allowed, reason, signature = _scheduler(runtime_state={}, remediation_current_new_evidence={"shadow_comparison_windows": 5})
    assert allowed is True
    assert reason == "ready"
    allowed_same, reason_same, _ = _scheduler(
        runtime_state={},
        remediation_current_new_evidence={"shadow_comparison_windows": 5},
        last_attempted_signature=signature,
        last_attempted_training_result="failed",
        last_attempted_training_status="rejected",
    )
    assert allowed_same is False
    assert reason_same == "already_attempted_current_training_data"
    allowed_new, reason_new, signature_new = _scheduler(
        runtime_state={},
        remediation_current_new_evidence={"shadow_comparison_windows": 6},
        last_attempted_signature=signature,
        last_attempted_training_result="failed",
        last_attempted_training_status="rejected",
    )
    assert allowed_new is True
    assert reason_new == "ready"
    assert signature_new != signature


def test_existing_protected_session_lifecycle_unchanged():
    source = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    start_protected = source[source.index("def start_protected_session"):source.index("def stop_current_session")]
    assert 'profile.get("production_ready")' in start_protected
    assert '"protected"' in start_protected
    stop_for_retry = source[source.index("def request_shadow_evidence_stop_for_retry"):source.index("def maybe_mark_shadow_evidence_stopped_for_retry")]
    assert "start_protected_session" not in stop_for_retry


def test_qml_does_not_control_retry_handoff():
    qml = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "qml").rglob("*.qml"))
    forbidden = [
        "requestShadowEvidenceStopForRetry",
        "stopShadowEvidenceForRetry",
        "retryHandoffState =",
        "function retryHandoff",
        "function retryEligibility",
        "function productionReady",
        "function protectedSessionsAvailable",
    ]
    assert not any(item in qml for item in forbidden)
    assert re.search(r"\bproductionReady\s*=(?!=)", qml) is None
    assert re.search(r"\bprotectedSessionsAvailable\s*=(?!=)", qml) is None
