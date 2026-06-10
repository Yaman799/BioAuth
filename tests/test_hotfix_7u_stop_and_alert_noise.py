from __future__ import annotations

from types import SimpleNamespace

from bioauth_runtime.supervisor import stop_controller
from bridge.refresh_runtime_split import dashboard_state


class _Bridge:
    def __init__(self):
        self._supervisor_stop_in_progress = True
        self._supervisor_stop_in_progress_reason = "user_stop"
        self._running_processes = {}
        self._worker_pair_status_cache = {}

    def _logger_process_key(self):
        return "logger_user_alice"

    def _logger_key(self):
        return "logger_user_alice"


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _AlertBridge:
    def __init__(self, state):
        self._current_user = {"user_id": "alice"}
        self._runtime_state = dict(state)
        self._last_alert_signature = None
        self._last_alert_at = 0.0
        self.dialogMessage = _Signal()
        self.warningFeedbackPromptRequested = _Signal()

    def _session_flow(self, _state):
        return "protected_warning"

    def _t(self, key):
        return str(key)


class _Facade:
    def __init__(self):
        self.notifications = []

    def show_taskbar_notification(self, *args, **kwargs):
        self.notifications.append((args, kwargs))
        return True


def test_explicit_user_stop_does_not_pair_fail_logger_exit(monkeypatch):
    bridge = _Bridge()
    stop_calls = []
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda *_a, **_k: stop_calls.append(_k) or {})

    stop_controller.handle_logger_exit_after_ready(
        bridge,
        "logger_user_alice",
        diagnostics={"exit_code": 0, "reason": "normal_user_stop"},
    )

    assert stop_calls == []


def test_explicit_user_stop_does_not_pair_fail_monitor_exit(monkeypatch):
    bridge = _Bridge()
    stop_calls = []
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda *_a, **_k: stop_calls.append(_k) or {})

    stop_controller.handle_monitor_exit_after_ready(
        bridge,
        diagnostics={"exit_code": 0, "reason": "normal_user_stop"},
    )

    assert stop_calls == []


def test_low_risk_soft_suspicious_warning_updates_state_without_notification(monkeypatch):
    facade = _Facade()
    monkeypatch.setattr(dashboard_state, "_facade", lambda: facade, raising=False)
    bridge = _AlertBridge(
        {
            "session_id": "sess-7u",
            "decision": "suspicious",
            "runtime_diag_code": "soft_suspicious_warning",
            "alert_code": "suspicious_behavior",
            "decision_risk": 35.0,
            "avg_risk": 39.8,
        }
    )

    dashboard_state.handle_state_alerts(bridge)

    assert facade.notifications == []
    assert bridge.dialogMessage.calls == []
    assert bridge._last_alert_signature


def test_high_risk_warning_stays_dashboard_only_without_powershell(monkeypatch):
    facade = _Facade()
    monkeypatch.setattr(dashboard_state, "_facade", lambda: facade, raising=False)
    bridge = _AlertBridge(
        {
            "session_id": "sess-7u",
            "decision": "suspicious",
            "runtime_diag_code": "downgraded_intruder_snapshot",
            "alert_code": "high_risk_snapshot",
            "decision_risk": 87.0,
            "avg_risk": 87.0,
            "alert_title_key": "alert_high_risk_title",
            "alert_message_key": "alert_high_risk_msg",
        }
    )

    dashboard_state.handle_state_alerts(bridge)

    assert facade.notifications == []
    assert bridge.dialogMessage.calls == []
    assert bridge._last_alert_signature
