from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Signal:
    def __init__(self):
        self.count = 0

    def emit(self, *args, **kwargs):
        self.count += 1


class _Proc:
    def __init__(self, alive: bool = True):
        self.alive = alive
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminated = True
        self.alive = False

    def kill(self):
        self.killed = True
        self.alive = False

    def wait(self, timeout=None):
        self.alive = False
        return 0


class _Facade:
    LOGGER_SCRIPT = "logger.py"
    MONITOR_SCRIPT = "monitor.py"
    MONITOR_START_GRACE_SEC = 0.1
    MIN_ENROLLMENT_SESSIONS = 8
    os = __import__("os")
    time = time
    uuid = SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="abc123"))

    class subprocess:
        class TimeoutExpired(Exception):
            pass

    def __init__(self):
        self.stop_requests: list[str] = []
        self.clear_requests: list[str] = []
        self.cleared_session = False
        self.cache_invalidated = False

    def request_stop(self, name):
        self.stop_requests.append(str(name))

    def clear_stop(self, name):
        self.clear_requests.append(str(name))

    def clear_session_state(self):
        self.cleared_session = True

    def invalidate_session_discovery_cache(self):
        self.cache_invalidated = True

    def runtime_status_is_technical_failure(self, status):
        return str(status or "") == "technical_failure"

    def read_session_state(self, default=None):
        return default or {}

    def write_session_state(self, state):
        self.written_state = dict(state or {})

    def slugify_username(self, value):
        return str(value or "").lower().replace("@", "_").replace(".", "_")


class _App:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._profile = {"production_ready": True, "training_can_start": True}
        self._runtime_state = {}
        self._running_processes = {}
        self._training_in_progress = False
        self._pending_logger_start = False
        self._pending_logger_session_kind = ""
        self._pending_monitor_start = False
        self._pending_shadow_evidence_monitor_start = False
        self._passive_auto_enrollment_finalizing = False
        self._history_sync_pending = False
        self._monitor_start_failed = False
        self._logger_start_failed = False
        self._last_process_start_error = ""
        self._sessions = []
        self.controlsChanged = _Signal()
        self.onboardingChanged = _Signal()
        self.statuses: list[tuple[str, str]] = []
        self.refreshes: list[tuple[str, bool]] = []
        self.started: list[tuple[str, list[str]]] = []
        self.shadow_pending_cleared = False
        self.history_cleared = False

    def _safe_user(self):
        return "alice"

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

    def _active_state_for_current_user(self):
        return dict(self._runtime_state)

    def _runtime_state_is_orphaned(self, state):
        return False

    def _normal_user_session_flow(self, state=None):
        import bridge.session_runtime_helpers as helpers
        return helpers._normal_user_session_flow(self, state=state)

    def _is_shadow_runtime_process_running(self):
        import bridge.session_runtime_helpers as helpers
        return helpers._is_shadow_runtime_process_running(self)

    def _clear_stale_shadow_state_if_safe(self, state=None):
        import bridge.session_runtime_helpers as helpers
        return helpers._clear_stale_shadow_state_if_safe(self, state=state)

    def _session_flow(self, state=None):
        import bridge.session_runtime_helpers as helpers
        return helpers.session_flow(self, state=state)

    def _clear_pending_shadow_evidence_monitor_start(self):
        self.shadow_pending_cleared = True
        self._pending_shadow_evidence_monitor_start = False

    def _clear_pending_logger_start(self):
        self._pending_logger_start = False
        self._pending_logger_session_kind = ""

    def _clear_pending_monitor_start(self):
        self._pending_monitor_start = False

    def _has_current_user_welcome_consent(self):
        return True

    def _t(self, key, **kwargs):
        return key

    def _set_status(self, message, tone):
        self.statuses.append((message, tone))

    def _update_refresh_timer(self, force=False):
        self.refreshes.append(("timer", bool(force)))

    def requestRefresh(self, reason, force=False):
        self.refreshes.append((str(reason), bool(force)))

    def _clear_history_archive_watch(self):
        self.history_cleared = True

    def _new_live_session_dir(self):
        return "/tmp/live-session"

    def _session_process_env(self):
        return None

    def _start_process(self, key, args, extra_env=None):
        self.started.append((str(key), list(args)))
        self._running_processes[str(key)] = _Proc(alive=True)
        return True

    def _stop_stale_monitor(self, wait_timeout=0.5):
        return True

    def _debug_trace(self, *args, **kwargs):
        return None


def _write_hybrid_report(path: Path, *, passed: bool = True) -> None:
    payload = {
        "passed": passed,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user": "alice",
        "profile": "alice",
        "reason_codes": ["hybrid_direct_monitor_prediction_completed"],
        "monitor": {
            "runtime_mode": "hybrid_direct_test",
            "source": "hybrid_direct_test_monitor",
            "process_key": "hybrid_direct_test_monitor_user_alice",
            "uses_shadow_monitor": False,
            "uses_production_monitor_executable": True,
            "test_only": True,
        },
        "safety": {
            "lock_allowed": False,
            "device_lock_allowed": False,
            "protected_sessions_unlock_allowed": False,
            "production_pointer_write_allowed": False,
            "production_approval_allowed": False,
            "production_promotion_allowed": False,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_only_shadow_logger_does_not_set_normal_enrollment_running(monkeypatch):
    import bridge.session_runtime_helpers as helpers
    facade = _Facade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    app = _App()
    app._runtime_state = {"active": True, "session_kind": "shadow_evidence", "runtime_mode": "shadow_evidence"}
    app._running_processes = {"shadow_logger_user_alice": _Proc(alive=True)}
    assert helpers._normal_enrollment_logger_flow(app) == "idle"
    assert helpers._normal_logger_process_running(app) is False


def test_only_shadow_monitor_does_not_set_production_monitor_or_stop_state(monkeypatch):
    import bridge.session_runtime_helpers as helpers
    facade = _Facade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    app = _App()
    app._runtime_state = {"active": True, "session_kind": "shadow_evidence", "runtime_mode": "shadow_evidence"}
    app._running_processes = {"shadow_monitor_user_alice": _Proc(alive=True)}
    assert helpers._production_monitor_process_running(app) is False
    assert helpers._production_monitor_flow(app) == "idle"


def test_stale_shadow_state_does_not_block_normal_enrollment_or_training(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers
    facade = _Facade()
    monkeypatch.setattr(runtime_helpers, "_facade", lambda: facade)
    report = tmp_path / "hybrid.json"
    _write_hybrid_report(report, passed=True)
    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(report))
    app = _App()
    app._runtime_state = {"active": True, "session_kind": "shadow_evidence", "runtime_mode": "shadow_evidence"}
    app._pending_shadow_evidence_monitor_start = True
    assert runtime_helpers._has_stale_shadow_state(app, app._runtime_state) is True
    assert runtime_helpers._normal_user_session_flow(app, app._runtime_state) == "idle"
    assert runtime_helpers._normal_enrollment_logger_flow(app, app._runtime_state) == "idle"
    status = training_helpers.training_gate_status(app)
    assert status["can_train"] is True
    assert status["training_sample_source"] == "normal_enrollment_archives_only"


def test_start_enrollment_starts_only_normal_logger_key(monkeypatch):
    import bridge.session_runtime_helpers as helpers
    facade = _Facade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    app = _App()
    assert helpers.start_enrollment(app) is True
    assert app.started == [("logger_user_alice", ["logger.py", "alice", "enrollment"])]
    assert all("shadow_logger_user_alice" != key for key, _args in app.started)
    assert all("shadow_monitor_user_alice" != key for key, _args in app.started)


def test_pending_shadow_logger_start_does_not_block_normal_enrollment(monkeypatch):
    import bridge.session_runtime_helpers as helpers
    facade = _Facade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    app = _App()
    app._pending_logger_start = True
    app._pending_logger_session_kind = "shadow_evidence"

    assert helpers.start_enrollment(app) is True

    assert app.started == [("logger_user_alice", ["logger.py", "alice", "enrollment"])]
    assert "shadow_logger_user_alice" not in [key for key, _args in app.started]
    assert "shadow_monitor_user_alice" not in [key for key, _args in app.started]
    assert app.statuses[-1] == ("enrollment_started", "info")
    assert facade.cleared_session is True


def test_pending_normal_logger_start_still_blocks_duplicate_enrollment(monkeypatch):
    import bridge.session_runtime_helpers as helpers
    facade = _Facade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    app = _App()
    app._pending_logger_start = True
    app._pending_logger_session_kind = "enrollment"

    assert helpers.start_enrollment(app) is False

    assert app.started == []
    assert app.statuses[-1] == ("enrollment_started", "info")


def test_start_enrollment_prioritizes_user_action_with_hidden_shadow_cleanup(monkeypatch):
    import bridge.session_runtime_helpers as helpers
    facade = _Facade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    app = _App()
    app._runtime_state = {"active": True, "session_kind": "shadow_evidence", "runtime_mode": "shadow_evidence"}
    app._running_processes = {"shadow_logger_user_alice": _Proc(alive=True), "shadow_monitor_user_alice": _Proc(alive=True)}
    assert helpers.start_enrollment(app) is False
    assert "shadow_logger_user_alice" in facade.stop_requests
    assert "shadow_monitor_user_alice" in facade.stop_requests
    assert "monitor" not in facade.stop_requests
    assert app.started == []
    assert app.statuses[-1][0] == "capture_session_finishing"


def test_stop_monitor_stops_only_exact_production_monitor(monkeypatch):
    import bridge.session_runtime_helpers as helpers
    facade = _Facade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    app = _App()
    production = _Proc(alive=True)
    shadow = _Proc(alive=True)
    app._running_processes = {"monitor": production, "shadow_monitor_user_alice": shadow}
    helpers.stop_production_monitor(app, silent=True)
    assert facade.stop_requests == ["monitor", "logger_user_alice"]
    assert production.terminated is True
    assert shadow.terminated is False


def test_hidden_shadow_cleanup_stops_shadow_logger_and_monitor_only(monkeypatch):
    import bridge.session_runtime_helpers as helpers
    facade = _Facade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    app = _App()
    app._running_processes = {"shadow_logger_user_alice": _Proc(alive=True), "shadow_monitor_user_alice": _Proc(alive=True)}
    assert helpers.stop_shadow_evidence_monitor(app, reason="test_cleanup") is True
    assert "shadow_logger_user_alice" in facade.stop_requests
    assert "shadow_monitor_user_alice" in facade.stop_requests
    assert "monitor" not in facade.stop_requests
    assert "logger_user_alice" not in facade.stop_requests


def test_normal_control_user_facing_strings_do_not_expose_shadow_terms():
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    overview = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    i18n = (ROOT / "bridge" / "i18n.py").read_text(encoding="utf-8")
    enrollment_block = overview[overview.index('objectName: "overviewStartEnrollmentLoggerButton"'):]
    enrollment_block = enrollment_block[:enrollment_block.find("AppButton", 1)]
    train_block = overview[overview.index('objectName: "overviewTrainCalibrateButton"'):]
    train_block = train_block[:train_block.find("AppButton", 1)]
    forbidden = ("shadow evidence", "shadow_evidence", "shadow_monitor", "shadow_logger")
    for source in (enrollment_block, train_block):
        lowered = source.lower()
        for token in forbidden:
            assert token not in lowered
    normal_reason_block = i18n[i18n.index('"enrollment_logger_unavailable_sign_in"'):i18n.index('"hybrid_direct_test_running"')]
    training_reason_block = i18n[i18n.index('"hybrid_test_missing"'):i18n.index('"train_profile"')]
    for source in (normal_reason_block, training_reason_block):
        lowered = source.lower()
        for token in forbidden:
            assert token not in lowered
    start_reason_fn = desktop[desktop.index("def startEnrollmentLoggerUnavailableReason"):desktop.index("def _production_monitor_process_running")]
    assert "enrollment_logger_unavailable_shadow" not in start_reason_fn


def test_training_and_hybrid_safety_contracts_remain_static():
    from feedback_loop import production_positive_training_allowed
    pipeline = (ROOT / "training_core" / "pipeline.py").read_text(encoding="utf-8")
    scan_block = pipeline[pipeline.index("def _scan_positive_training_candidates"):pipeline.index("def _evaluate_and_publish_candidate")]
    assert 'session_kind == "enrollment"' in scan_block
    assert production_positive_training_allowed({"session_kind": "enrollment", "metadata_trusted": True, "source": "shadow_evidence_monitor"}) is False
    assert production_positive_training_allowed({"session_kind": "enrollment", "metadata_trusted": True, "source": "hybrid_direct_test_monitor"}) is False
    assert production_positive_training_allowed({"session_kind": "enrollment", "metadata_trusted": True, "confirmed_intruder": True}) is False
    runtime = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    validation_block = runtime[runtime.index("def validate_hybrid_direct_test_evidence"):runtime.index("def _hybrid_result_status_message")]
    for forbidden in ("write_active_runtime_pointer", "unlockProtected", "startProtected"):
        assert forbidden not in validation_block
    assert "production_promotion_allowed" in validation_block
