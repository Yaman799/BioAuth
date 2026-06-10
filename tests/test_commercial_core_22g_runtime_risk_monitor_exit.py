from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridge import refresh_dashboard_helpers as dashboard_helpers
from bridge.runtime_labels import runtime_policy_display_fields, runtime_status_is_technical_failure


class _Clock:
    @staticmethod
    def time():
        return 1000.0


class _Facade:
    time = _Clock()

    @staticmethod
    def runtime_status_is_technical_failure(status):
        from bridge.runtime_labels import runtime_status_is_technical_failure as fn
        return fn(status)

    @staticmethod
    def runtime_status_awaits_evidence(status):
        from bridge.runtime_labels import runtime_status_awaits_evidence as fn
        return fn(status)

    @staticmethod
    def runtime_status_key(status, *, active=False, restricted=False):
        from bridge.runtime_labels import runtime_status_key as fn
        return fn(status, active=active, restricted=restricted)

    @staticmethod
    def runtime_status_detail_key(status):
        from bridge.runtime_labels import runtime_status_detail_key as fn
        return fn(status)

    @staticmethod
    def runtime_decision_key(decision):
        return "status_idle" if not decision else f"runtime_decision_{decision}"


class _Bridge:
    def _t(self, key: str, **kwargs) -> str:
        return key.format(**kwargs) if kwargs else key

    def _format_elapsed(self, started_at):
        return "1s" if started_at else "--"

    def _session_flow(self, state=None):
        if state and state.get("technical_failure"):
            return "protected_technical_failure"
        return "protected_active" if state and state.get("active") else "idle"


def test_monitor_exited_after_ready_is_technical_failure_display() -> None:
    assert runtime_status_is_technical_failure("monitor_exited_after_ready") is True
    display = runtime_policy_display_fields(
        {"active": True, "status": "monitor_exited_after_ready", "risk_engine_stopped": True},
        active=True,
        technical_failure=True,
        monitor_ready=False,
    )
    assert display["runtimeDisplayPhase"] == "technical_failure"
    assert display["runtimeDisplayText"] == "Risk engine stopped"
    assert display["lockBlockedBy"] == "technical_failure"


def test_runtime_state_uses_observed_risk_as_primary_display_when_decision_pending(monkeypatch) -> None:
    old_facade = dashboard_helpers._facade
    dashboard_helpers._facade = lambda: _Facade()
    try:
        state = {
            "active": True,
            "session_kind": "protected",
            "status": "insufficient_evidence",
            "decision": "pending",
            "monitor_ready": True,
            "logger_ready": True,
            "runtime_last_window_diag": {
                "risk": 15,
                "base_risk": 15,
                "quality_ok": True,
                "quality_lock_ok": False,
                "reason_codes": ["transition_window"],
            },
            "runtime_window_count": 1,
        }
        view = dashboard_helpers.build_runtime_state_view(_Bridge(), state)
    finally:
        dashboard_helpers._facade = old_facade
    assert view["decisionRiskText"] == "--"
    assert view["observedRiskText"] == "15"
    assert view["riskText"] == "15"
    assert view["riskTextIsObserved"] is True
    assert view["riskDisplayMode"] == "observed_risk_pending"


def test_session_mixin_marks_monitor_exit_after_ready_contract() -> None:
    source = Path("bridge/session_mixin.py").read_text(encoding="utf-8")
    assert "def _mark_monitor_exited_after_ready" in source
    assert "monitor_exited_after_ready" in source
    assert "risk_engine_stopped" in source
    assert "monitor_stderr_tail" in source
    assert "if str(key) == \"monitor\"" in source


def test_monitor_impl_records_structured_exit_reason() -> None:
    source = Path("src/bioauth/runtime/monitor_impl.py").read_text(encoding="utf-8")
    assert "monitor_exit_reason = \"unknown\"" in source
    assert "session_id_mismatch" in source
    assert "session_inactive" in source
    assert "stop_requested" in source
    assert "monitor_exit_recorded_at" in source


def test_debug_panel_surfaces_monitor_exit_diagnostics() -> None:
    source = Path("debug_tools.py").read_text(encoding="utf-8")
    assert "monitor_exit_reason" in source
    assert "monitor_stderr_tail" in source
    assert "risk_engine_stopped" in source
    backend = Path("src/bioauth/app/desktop_app_impl.py").read_text(encoding="utf-8")
    assert "monitor_exit_detail" in backend
    assert "monitor_stdout_tail" in backend
