from __future__ import annotations

import re
import subprocess
import sys
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
        if self.alive:
            raise subprocess.TimeoutExpired(cmd="proc", timeout=timeout)
        return 0

    def kill(self):
        self.terminated = True
        self.alive = False


class _FakeFacade:
    class subprocess:
        class TimeoutExpired(Exception):
            pass

    def __init__(self):
        self.stop_requests = []
        self.stop_clears = []
        self.cache_invalidated = False
        self.state = {"active": True, "session_kind": "protected", "status": "ok", "monitor_ready": True, "logger_ready": True, "user_id": "alice"}
        import os
        import time
        self.os = os
        self.time = time

    def request_stop(self, name):
        self.stop_requests.append(str(name))

    def clear_stop(self, name):
        self.stop_clears.append(str(name))

    def read_session_state(self, default=None):
        return dict(self.state or (default or {}))

    def write_session_state(self, data):
        self.state = dict(data)
        return True

    def runtime_status_is_technical_failure(self, status):
        return str(status or "").lower() in {"failed", "monitor_unavailable"}

    def invalidate_session_discovery_cache(self):
        self.cache_invalidated = True


class _MonitorApp:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._runtime_state = {"active": True, "session_kind": "protected"}
        self._pending_monitor_start = False
        self._pending_shadow_evidence_monitor_start = False
        self._running_processes = {}
        self.controlsChanged = _Signal()
        self.runtimeStateChanged = _Signal()
        self.dashboardStateChanged = _Signal()
        self._active_live_session_dir = ""
        self._last_alert_signature = "stale"
        self.statuses = []
        self.refreshes = []
        self.history_watch_started = False
        self.shadow_pending_cleared = False
        self.logger_pending_cleared = False
        self.monitor_pending_cleared = False

    def _debug_trace(self, *args, **kwargs):
        return None

    def _t(self, key):
        return key

    def _session_flow(self, state=None):
        data = state if isinstance(state, dict) else self._runtime_state
        if data.get("active") and data.get("session_kind") == "shadow_evidence":
            return "shadow_evidence_active"
        if data.get("active") and data.get("session_kind") == "protected":
            return "protected_active"
        return "idle"

    def _active_state_for_current_user(self):
        return dict(self._runtime_state)

    def _clear_pending_monitor_start(self):
        self.monitor_pending_cleared = True
        self._pending_monitor_start = False

    def _clear_pending_logger_start(self):
        self.logger_pending_cleared = True

    def _clear_pending_shadow_evidence_monitor_start(self):
        self.shadow_pending_cleared = True
        self._pending_shadow_evidence_monitor_start = False

    def _shadow_logger_stop_control_name(self):
        return "shadow_logger_user_alice"

    def _shadow_monitor_stop_control_name(self):
        return "shadow_monitor_user_alice"

    def _runtime_state_is_orphaned(self, state):
        return False

    def _begin_history_archive_watch(self):
        self.history_watch_started = True

    def _clear_history_archive_watch(self):
        return None

    def _invalidate_dashboard_snapshot_cache(self):
        return None

    def _set_status(self, message, tone):
        self.statuses.append((message, tone))

    def _update_refresh_timer(self, force=False):
        self.refreshes.append(("timer", force))

    def requestRefresh(self, reason, force=False):
        self.refreshes.append((reason, force))

    def _logger_key(self):
        return "logger_user_alice"

    def _stop_stale_monitor(self, wait_timeout=0.5):
        return True


def _qml_button_block(source: str, object_name: str) -> str:
    marker = f'objectName: "{object_name}"'
    start = source.index(marker)
    brace_start = source.rfind("AppButton", 0, start)
    next_button = source.find("AppButton", start + len(marker))
    return source[brace_start: next_button if next_button != -1 else len(source)]


def test_overview_stop_monitor_uses_production_specific_backend_contract():
    qml = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    block = _qml_button_block(qml, "overviewStopMonitorButton")
    assert "enabled: backend.canStopProductionMonitor" in block
    assert "onClicked: backend.stopProductionMonitor(false)" in block
    assert "enabled: backend.canStop\n" not in block
    assert "backend.stopCurrentSession(false)" not in block


def test_overview_start_monitor_uses_production_specific_start_state_and_enrollment_button_remains():
    qml = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    start_block = _qml_button_block(qml, "overviewStartMonitorButton")
    enrollment_block = _qml_button_block(qml, "overviewStartEnrollmentLoggerButton")
    assert "enabled: backend.canStartProductionMonitor" in start_block
    assert "onClicked: backend.startProtected()" in start_block
    assert "enabled: backend.canStartEnrollmentLogger" in enrollment_block
    assert "onClicked: backend.startEnrollment()" in enrollment_block
    assert "visible: false" not in enrollment_block


def test_backend_exposes_production_monitor_properties_and_slot():
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    session_mixin = (ROOT / "bridge" / "session_mixin.py").read_text(encoding="utf-8")
    runtime_helpers = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    assert re.search(r"@Property\(bool, notify=controlsChanged\)\s+def productionMonitorRunning", desktop)
    assert re.search(r"@Property\(bool, notify=controlsChanged\)\s+def canStartProductionMonitor", desktop)
    assert re.search(r"@Property\(bool, notify=controlsChanged\)\s+def canStopProductionMonitor", desktop)
    assert re.search(r"@Slot\(bool\)\s+def stopProductionMonitor", session_mixin)
    stop_fn = runtime_helpers[runtime_helpers.index("def stop_production_monitor"):runtime_helpers.index("def maybe_resume_protection_after_unlock")]
    assert "finalize_protected_session_stop" in stop_fn
    assert "_request_shadow_stop_controls" not in stop_fn
    finalizer_fn = runtime_helpers[runtime_helpers.index("def finalize_protected_session_stop"):runtime_helpers.index("def _clear_runtime_after_terminal_stop")]
    assert 'facade.request_stop(monitor_key)' in finalizer_fn
    assert 'facade.request_stop(self._logger_key())' in finalizer_fn
    assert "shadow_monitor_user" not in finalizer_fn


def test_shadow_monitor_process_does_not_count_as_production_monitor(monkeypatch):
    import bridge.session_runtime_helpers as helpers

    app = _MonitorApp()
    app._running_processes = {"shadow_monitor_user_alice": _Proc(alive=True)}
    assert helpers._production_monitor_process_running(app) is False
    assert helpers._protected_or_unrelated_monitor_running(app) is False


def test_exact_monitor_process_counts_as_production_monitor(monkeypatch):
    import bridge.session_runtime_helpers as helpers

    app = _MonitorApp()
    app._running_processes = {"monitor": _Proc(alive=True)}
    assert helpers._production_monitor_process_running(app) is True


def test_shadow_evidence_state_excludes_even_exact_monitor_key(monkeypatch):
    import bridge.session_runtime_helpers as helpers

    app = _MonitorApp()
    app._runtime_state = {"active": True, "session_kind": "shadow_evidence", "runtime_mode": "shadow_evidence"}
    app._running_processes = {"monitor": _Proc(alive=True), "shadow_monitor_user_alice": _Proc(alive=True)}
    assert helpers._production_monitor_process_running(app) is False


def test_stop_production_monitor_finalizes_monitor_and_logger_without_shadow(monkeypatch):
    import bridge.session_runtime_helpers as helpers

    facade = _FakeFacade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    app = _MonitorApp()
    production = _Proc(alive=True)
    shadow = _Proc(alive=True)
    app._running_processes = {"monitor": production, "shadow_monitor_user_alice": shadow}
    helpers.stop_production_monitor(app, silent=True)
    assert facade.stop_requests == ["monitor", "logger_user_alice"]
    assert production.terminated is True
    assert shadow.terminated is False
    assert facade.state["active"] is False
    assert facade.state["session_state"] == "stopped"
    assert facade.state["flow"] == "idle"
    assert app.controlsChanged.count >= 1
    assert app.runtimeStateChanged.count >= 1
    assert app.shadow_pending_cleared is False


def test_shadow_cleanup_still_uses_shadow_stop_controls(monkeypatch):
    import bridge.session_runtime_helpers as helpers

    facade = _FakeFacade()
    monkeypatch.setattr(helpers, "_facade", lambda: facade)
    monkeypatch.setattr(helpers, "recover_stale_passive_auto_enrollment_finalization", lambda *args, **kwargs: False)
    app = _MonitorApp()
    app._runtime_state = {"active": True, "session_kind": "shadow_evidence", "runtime_mode": "shadow_evidence"}
    helpers.stop_current_session(app, silent=True)
    assert "shadow_logger_user_alice" in facade.stop_requests
    assert "shadow_monitor_user_alice" in facade.stop_requests
    assert "monitor" not in facade.stop_requests


def test_no_substring_matching_for_monitor_process_identity():
    runtime_helpers = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    combined = runtime_helpers + "\n" + desktop
    assert '"monitor" in key' not in combined
    assert "'monitor' in key" not in combined
    assert '.startswith("monitor")' not in combined
    assert ".startswith('monitor')" not in combined
