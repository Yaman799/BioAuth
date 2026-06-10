from __future__ import annotations

import re
import sys
import types
from pathlib import Path

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

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminated = True
        self.alive = False

    def wait(self, timeout=None):
        self.alive = False
        return 0


class _FakeFacade:
    LOGGER_SCRIPT = "logger.py"
    MONITOR_SCRIPT = "monitor.py"
    LOGGER_START_GRACE_SEC = 12.0
    time = types.SimpleNamespace(monotonic=lambda: 1000.0)

    class uuid:
        _counter = 0

        @classmethod
        def uuid4(cls):
            cls._counter += 1
            return types.SimpleNamespace(hex=f"fixed-{cls._counter}")

    def __init__(self):
        self.cleared_stops = []
        self.stop_requests = []
        self.session_cleared = False
        self.cache_invalidated = False

    def clear_stop(self, name):
        self.cleared_stops.append(name)

    def request_stop(self, name):
        self.stop_requests.append(name)

    def clear_session_state(self):
        self.session_cleared = True

    def invalidate_session_discovery_cache(self):
        self.cache_invalidated = True

    def runtime_status_is_technical_failure(self, status):
        return str(status or "") == "technical_failure"

    def slugify_username(self, value):
        return str(value or "").lower().replace("@", "_").replace(".", "_")


class _EnrollmentApp:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._training_in_progress = False
        self._pending_logger_start = False
        self._pending_logger_session_kind = ""
        self._pending_monitor_start = False
        self._pending_passive_auto_enrollment = False
        self._active_live_session_dir = None
        self._runtime_state = {}
        self._running_processes = {}
        self._pending_shadow_evidence_monitor_start = False
        self._last_process_start_error = ""
        self.onboardingChanged = _Signal()
        self.controlsChanged = _Signal()
        self.started = []
        self.statuses = []
        self.refreshes = []
        self.history_watch_started = 0

    def _debug_trace(self, *args, **kwargs): return None
    def _safe_user(self): return "alice"
    def _t(self, key): return key
    def _has_current_user_welcome_consent(self): return True
    def _active_state_for_current_user(self): return dict(self._runtime_state)
    def _session_flow(self, state=None):
        data = state if isinstance(state, dict) else self._runtime_state
        if data.get("active"):
            kind = str(data.get("session_kind") or "")
            if kind == "enrollment": return "enrollment_active"
            if kind == "shadow_evidence": return "shadow_evidence_active"
            if kind == "protected": return "protected_active"
        return "idle"
    def _stop_stale_monitor(self): return True
    def _logger_key(self): return "logger_user_alice"
    def _logger_process_key(self): return "logger_user_alice"
    def _shadow_logger_process_key(self): return "shadow_logger_user_alice"
    def _shadow_monitor_process_key(self): return "shadow_monitor_user_alice"
    def _shadow_logger_stop_control_name(self): return "shadow_logger_user_alice"
    def _shadow_monitor_stop_control_name(self): return "shadow_monitor_user_alice"
    def _clear_pending_logger_start(self):
        self._pending_logger_start = False
        self._pending_logger_session_kind = ""
    def _clear_pending_shadow_evidence_monitor_start(self):
        self._pending_shadow_evidence_monitor_start = False
    def _clear_history_archive_watch(self): return None
    def _begin_history_archive_watch(self, *args, **kwargs): self.history_watch_started += 1
    def _invalidate_dashboard_snapshot_cache(self): return None
    def _new_live_session_dir(self): return "/tmp/bioauth-phase2-enrollment"
    def _session_process_env(self): return {"BIOAUTH_SESSION_ID": "session-id", "BIOAUTH_RUN_ID": "run-id"}
    def _start_process(self, key, args, extra_env=None):
        self.started.append((key, list(args), dict(extra_env or {})))
        return True
    def _set_status(self, message, tone): self.statuses.append((message, tone))
    def _update_refresh_timer(self, force=False): self.refreshes.append(("timer", force))
    def requestRefresh(self, reason, force=False): self.refreshes.append((reason, force))


def _helpers(monkeypatch):
    import bridge.session_runtime_helpers as helpers
    facade = _FakeFacade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    return helpers, facade


def _qml_button_block(source: str, object_name: str) -> str:
    marker = f'objectName: "{object_name}"'
    start = source.index(marker)
    brace_start = source.rfind("AppButton", 0, start)
    next_button = source.find("AppButton", start + len(marker))
    return source[brace_start: next_button if next_button != -1 else len(source)]


def test_overview_has_visible_backend_bound_normal_enrollment_logger_button():
    qml = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    block = _qml_button_block(qml, "overviewStartEnrollmentLoggerButton")
    assert 'text: backend.tr("start_enrollment_logger")' in block
    assert "enabled: backend.canStartEnrollmentLogger" in block
    assert "onClicked: backend.startEnrollment()" in block
    assert "backend.startEnrollmentLoggerUnavailableReason" in block
    assert "visible: false" not in block
    assert "productionReady" not in block
    assert "protectedSessionsAvailable" not in block


def test_overview_enrollment_logger_button_does_not_call_shadow_or_monitor_start():
    qml = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    block = _qml_button_block(qml, "overviewStartEnrollmentLoggerButton")
    for token in ["startShadow", "shadow_logger_user_", "shadow_monitor_user_", "startProtected()", "stopCurrentSession", "monitor"]:
        assert token not in block


def test_history_empty_state_uses_same_backend_owned_normal_enrollment_contract():
    qml = (ROOT / "qml" / "pages" / "HistoryPage.qml").read_text(encoding="utf-8")
    block = _qml_button_block(qml, "historyStartEnrollmentLoggerButton")
    assert 'text: backend.tr("start_enrollment_logger")' in block
    assert "enabled: backend.canStartEnrollmentLogger" in block
    assert "onClicked: backend.startEnrollment()" in block
    assert "backend.startEnrollmentLoggerUnavailableReason" in block


def test_backend_exposes_enrollment_logger_properties_as_controls_changed_state():
    source = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    assert "def _can_start_enrollment_logger(self) -> bool:" in source
    assert "def canStartEnrollmentLogger(self) -> bool:" in source
    assert "def enrollmentLoggerRunning(self) -> bool:" in source
    assert "def startEnrollmentLoggerUnavailableReason(self) -> str:" in source
    assert re.search(r"@Property\(bool, notify=controlsChanged\)\s+def canStartEnrollmentLogger", source)
    assert re.search(r"@Property\(bool, notify=controlsChanged\)\s+def enrollmentLoggerRunning", source)
    assert re.search(r"@Property\(str, notify=controlsChanged\)\s+def startEnrollmentLoggerUnavailableReason", source)
    running_block = source[source.index("def enrollmentLoggerRunning"):source.index("def startEnrollmentLoggerUnavailableReason")]
    assert '== "enrollment_active"' in running_block
    assert "shadow_evidence" not in running_block


def test_start_enrollment_starts_normal_logger_not_shadow_logger_or_shadow_monitor(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _EnrollmentApp()
    assert helpers.start_enrollment(app) is True
    assert app.started == [("logger_user_alice", [facade.LOGGER_SCRIPT, "alice", "enrollment"], {"BIOAUTH_SESSION_ID": "session-id", "BIOAUTH_RUN_ID": "run-id"})]
    assert facade.cleared_stops == ["logger_user_alice"]
    assert not any(item[0] == "shadow_logger_user_alice" for item in app.started)
    assert not any(item[0] == "shadow_monitor_user_alice" for item in app.started)


def test_stale_shadow_state_does_not_block_start_enrollment(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _EnrollmentApp()
    app._runtime_state = {"active": True, "session_kind": "shadow_evidence", "runtime_mode": "shadow_evidence", "evidence_source": "shadow_evidence_monitor"}

    assert helpers.start_enrollment(app) is True

    assert app.started == [("logger_user_alice", [facade.LOGGER_SCRIPT, "alice", "enrollment"], {"BIOAUTH_SESSION_ID": "session-id", "BIOAUTH_RUN_ID": "run-id"})]
    assert facade.session_cleared is True
    assert not any(item[0] == "shadow_logger_user_alice" for item in app.started)
    assert not any(item[0] == "shadow_monitor_user_alice" for item in app.started)


def test_live_shadow_process_requests_hidden_cleanup_before_start_enrollment(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _EnrollmentApp()
    app._runtime_state = {"active": True, "session_kind": "shadow_evidence", "runtime_mode": "shadow_evidence", "evidence_source": "shadow_evidence_monitor"}
    app._running_processes = {"shadow_logger_user_alice": _Proc(alive=True), "shadow_monitor_user_alice": _Proc(alive=True)}

    assert helpers.start_enrollment(app) is False

    assert app.started == []
    assert facade.stop_requests == ["shadow_logger_user_alice", "shadow_monitor_user_alice"]
    assert "monitor" not in facade.stop_requests
    assert app.statuses[-1] == ("capture_session_finishing", "info")


def test_phase1_shadow_isolation_contracts_remain_present():
    runtime_helpers = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    refresh_helpers = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text(encoding="utf-8")
    logger_source = (ROOT / "src" / "bioauth" / "input" / "logger_impl.py").read_text(encoding="utf-8")
    monitor_source = (ROOT / "src" / "bioauth" / "runtime" / "monitor_impl.py").read_text(encoding="utf-8")
    assert "def _shadow_logger_process_key" in runtime_helpers
    assert "def _shadow_monitor_process_key" in runtime_helpers
    assert "_shadow_logger_process_key(self)," in runtime_helpers
    assert "monitor_key = _shadow_monitor_process_key(self) if pending_shadow else \"monitor\"" in refresh_helpers
    assert 'shadow_logger_stop_control_name(safe_user) if session_kind == SHADOW_EVIDENCE_SESSION_KIND else f"logger_user_{safe_user}"' in logger_source
    assert "if _shadow_evidence_mode():" in monitor_source
    assert "shadow_evidence_report_only_monitor" in monitor_source
    assert "production_pointer_write_allowed" in monitor_source



def test_overview_has_backend_bound_stop_enrollment_logger_button():
    qml = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    block = _qml_button_block(qml, "overviewStopEnrollmentLoggerButton")
    assert 'text: backend.tr("stop_enrollment_logger")' in block
    assert 'role: "danger"' in block
    assert "enabled: backend.canStopEnrollmentLogger" in block
    assert "backend.stopEnrollmentLoggerUnavailableReason" in block
    assert "onClicked: backend.stopEnrollmentLogger(false)" in block
    for forbidden in [
        "backend.stopCurrentSession(false)",
        "backend.stopProductionMonitor(false)",
        "backend.canStopProductionMonitor",
    ]:
        assert forbidden not in block
    assert not re.search(r"enabled:\s*backend\.canStop(?:\s|$)", block)


def test_history_has_backend_bound_stop_enrollment_logger_button():
    qml = (ROOT / "qml" / "pages" / "HistoryPage.qml").read_text(encoding="utf-8")
    block = _qml_button_block(qml, "historyStopEnrollmentLoggerButton")
    assert 'text: backend.tr("stop_enrollment_logger")' in block
    assert 'role: "danger"' in block
    assert "enabled: backend.canStopEnrollmentLogger" in block
    assert "backend.stopEnrollmentLoggerUnavailableReason" in block
    assert "onClicked: backend.stopEnrollmentLogger(false)" in block
    for forbidden in [
        "backend.stopCurrentSession(false)",
        "backend.stopProductionMonitor(false)",
        "backend.canStopProductionMonitor",
    ]:
        assert forbidden not in block
    assert not re.search(r"enabled:\s*backend\.canStop(?:\s|$)", block)


def test_backend_exposes_stop_enrollment_logger_properties_as_controls_changed_state():
    source = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    assert "def _can_stop_enrollment_logger(self) -> bool:" in source
    assert "def canStopEnrollmentLogger(self) -> bool:" in source
    assert "def stopEnrollmentLoggerUnavailableReason(self) -> str:" in source
    assert re.search(r"@Property\(bool, notify=controlsChanged\)\s+def canStopEnrollmentLogger", source)
    assert re.search(r"@Property\(str, notify=controlsChanged\)\s+def stopEnrollmentLoggerUnavailableReason", source)
    can_stop_block = source[source.index("def _can_stop_enrollment_logger"):source.index("@Property(bool, notify=controlsChanged)\n    def canStartEnrollment")]
    assert "session_runtime_helpers._normal_enrollment_logger_stop_available(self)" in can_stop_block


def test_session_mixin_exposes_stop_enrollment_logger_slot():
    source = (ROOT / "bridge" / "session_mixin.py").read_text(encoding="utf-8")
    assert re.search(r"@Slot\(bool\)\s+def stopEnrollmentLogger\(self, silent: bool = False\) -> None:", source)
    assert "session_runtime_helpers.stop_enrollment_logger(self, silent=silent)" in source


def test_runtime_helpers_exposes_dedicated_stop_enrollment_logger_contract():
    source = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "def _normal_enrollment_logger_stop_available" in source
    assert "def stop_enrollment_logger(self, silent: bool = False) -> bool:" in source
    block = source[source.index("def stop_enrollment_logger"):source.index("def stop_current_session")]
    assert "_normal_enrollment_logger_stop_available(self, state)" in block
    assert "facade.request_stop(self._logger_key())" in block
    assert 'facade.request_stop("monitor")' not in block
    assert "_request_shadow_stop_controls" not in block
    assert "shadow_logger_user_" not in block
    assert "shadow_monitor_user_" not in block
    assert "facade.clear_session_state()" not in block
    assert '"session:stop_enrollment_logger"' in block


def test_stop_enrollment_logger_requests_only_normal_logger_stop(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _EnrollmentApp()
    app._runtime_state = {"active": True, "session_kind": "enrollment", "source": "logger", "logger_ready": True, "status": "ok"}

    assert helpers.stop_enrollment_logger(app) is True
    assert facade.stop_requests == ["logger_user_alice"]
    assert "monitor" not in facade.stop_requests
    assert "shadow_logger_user_alice" not in facade.stop_requests
    assert "shadow_monitor_user_alice" not in facade.stop_requests
    assert app.history_watch_started == 1
    assert app.statuses[-1] == ("stop_requested", "info")
    assert ("session:stop_enrollment_logger", True) in app.refreshes
    assert app.controlsChanged.count == 1


def test_stop_enrollment_logger_is_idempotent_for_active_logger(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _EnrollmentApp()
    app._runtime_state = {"active": True, "session_kind": "enrollment", "source": "logger", "logger_ready": True, "status": "ok"}

    assert helpers.stop_enrollment_logger(app) is True
    assert helpers.stop_enrollment_logger(app, silent=True) is True
    assert facade.stop_requests == ["logger_user_alice", "logger_user_alice"]
    assert "monitor" not in facade.stop_requests
    assert "shadow_logger_user_alice" not in facade.stop_requests
    assert "shadow_monitor_user_alice" not in facade.stop_requests


def test_stop_enrollment_logger_when_idle_is_safe_and_creates_no_stop_controls(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _EnrollmentApp()

    assert helpers.stop_enrollment_logger(app) is False
    assert facade.stop_requests == []
    assert facade.cleared_stops == []
    assert app.started == []
    assert app.history_watch_started == 0


def test_stop_enrollment_logger_can_stop_pending_enrollment_startup_only(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _EnrollmentApp()
    app._pending_logger_start = True
    app._pending_logger_session_kind = "enrollment"

    assert helpers.stop_enrollment_logger(app) is True
    assert facade.stop_requests == ["logger_user_alice"]
    assert app._pending_logger_start is True


def test_stop_enrollment_logger_does_not_stop_pending_protected_or_shadow_startup(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _EnrollmentApp()
    app._pending_logger_start = True
    app._pending_logger_session_kind = "protected"
    assert helpers.stop_enrollment_logger(app) is False

    app._pending_logger_session_kind = "shadow_evidence"
    assert helpers.stop_enrollment_logger(app) is False
    assert facade.stop_requests == []


def test_stop_enrollment_logger_keeps_hidden_shadow_evidence_isolated(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _EnrollmentApp()
    app._runtime_state = {
        "active": True,
        "session_kind": "shadow_evidence",
        "runtime_mode": "shadow_evidence",
        "evidence_source": "shadow_evidence_monitor",
    }
    app._running_processes = {
        "shadow_logger_user_alice": _Proc(alive=True),
        "shadow_monitor_user_alice": _Proc(alive=True),
    }

    assert helpers.stop_enrollment_logger(app) is False
    assert facade.stop_requests == []
    assert app.history_watch_started == 0



def test_stop_enrollment_logger_does_not_stop_protected_session_logger_or_monitor(monkeypatch):
    helpers, facade = _helpers(monkeypatch)
    app = _EnrollmentApp()
    app._runtime_state = {"active": True, "session_kind": "protected", "source": "logger", "logger_ready": True, "monitor_ready": True, "status": "ok"}
    app._running_processes = {"logger_user_alice": _Proc(alive=True), "monitor": _Proc(alive=True)}

    assert helpers.stop_enrollment_logger(app) is False
    assert facade.stop_requests == []
    assert app.history_watch_started == 0


def test_stop_enrollment_logger_i18n_keys_exist_for_english_and_arabic():
    from bridge.i18n import STRINGS

    assert STRINGS["en"]["stop_enrollment_logger"] == "Stop Enrollment Logger"
    assert STRINGS["ar"]["stop_enrollment_logger"] == "إيقاف مسجل جلسة التعريف"
    assert STRINGS["en"]["stop_enrollment_logger_unavailable_idle"] == "The enrollment logger is not running."
    assert STRINGS["ar"]["stop_enrollment_logger_unavailable_idle"] == "مسجل جلسة التعريف لا يعمل حالياً."
    assert STRINGS["en"]["stop_enrollment_logger_unavailable_sign_in"] == "Sign in to stop the enrollment logger."
    assert STRINGS["ar"]["stop_enrollment_logger_unavailable_sign_in"] == "سجّل الدخول لإيقاف مسجل جلسة التعريف."
