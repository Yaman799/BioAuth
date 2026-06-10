from __future__ import annotations

from types import SimpleNamespace

from bridge.dashboard_refresh_split import drift_live_cards
from bridge.refresh_runtime_split import dashboard_state
from bioauth_runtime.supervisor import resume_controller


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _WarningBridge:
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


class _StatusBridge:
    def _t(self, key, **kwargs):
        if key == "runtime_status_display_risk_line":
            return f"{kwargs['status']} · Risk {kwargs['risk']}"
        if key == "status_active":
            return "Active"
        return str(key)


def test_protected_warning_never_spawns_powershell_notification(monkeypatch):
    facade = _Facade()
    monkeypatch.setattr(dashboard_state, "_facade", lambda: facade, raising=False)
    bridge = _WarningBridge(
        {
            "session_id": "sess-7w",
            "decision": "suspicious",
            "runtime_diag_code": "downgraded_intruder_snapshot",
            "alert_code": "high_risk_snapshot",
            "decision_risk": 87.0,
            "avg_risk": 87.0,
        }
    )

    dashboard_state.handle_state_alerts(bridge)

    assert facade.notifications == []
    assert bridge.dialogMessage.calls == []
    assert bridge._last_alert_signature


def test_dashboard_status_uses_single_display_risk_without_avg():
    message, tone = drift_live_cards.status_for_dashboard(
        _StatusBridge(),
        {"production_ready": True},
        {
            "active": True,
            "flow": "protected_warning",
            "decisionText": "suspicious",
            "decisionLabel": "Suspicious",
            "trustLabel": "Suspicious",
            "runtimeDisplayText": "Suspicious · lock delayed by policy",
            "riskText": "58.6",
            "avgRiskText": "84.0",
        },
    )

    assert message == "Suspicious · lock delayed by policy · Risk 58.6"
    assert "Avg" not in message
    assert tone == "warn"


def test_auto_resume_is_scheduled_off_refresh_thread(monkeypatch):
    started = []

    class _Thread:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args
            self.name = name
            self.daemon = daemon

        def start(self):
            started.append((self.name, self.daemon, self.target, self.args))

    class _FacadeResume:
        class time:
            @staticmethod
            def time():
                return 100.0

        @staticmethod
        def is_current_session_locked():
            return False

    bridge = SimpleNamespace(
        _current_user={"user_id": "alice"},
        _last_auto_resume_attempt_at=0.0,
        _auto_resume_inflight=False,
        _logger_process_key=lambda: "logger_user_alice",
    )
    state = {
        "session_kind": "protected",
        "active": False,
        "auto_resume_pending": True,
        "resume_after_unlock": True,
        "lock_controller_handoff": True,
        "status": "resume_pending",
        "runtime_status": "resume_pending",
    }

    monkeypatch.setattr(resume_controller, "_legacy", lambda: SimpleNamespace(_facade=lambda: _FacadeResume), raising=False)
    monkeypatch.setattr(resume_controller.worker_processes, "process_alive", lambda *_a, **_k: False)
    monkeypatch.setattr(resume_controller.threading, "Thread", _Thread)

    assert resume_controller.maybe_resume_after_unlock(bridge, state=state) is True
    assert bridge._auto_resume_inflight is True
    assert started and started[0][0] == "bioauth-auto-resume"
