from __future__ import annotations

import time

from bridge import session_runtime_helpers as helpers


def test_session_heartbeat_merge_preserves_monitor_decision_fields(monkeypatch) -> None:
    class Facade:
        def slugify_username(self, value):
            return str(value)

        def read_worker_heartbeat(self, kind, default=None):
            if kind == "monitor":
                return {
                    "session_id": "s1",
                    "user_id": "u1",
                    "worker_kind": "monitor",
                    "active": True,
                    "heartbeat_at": time.time(),
                    "status": "intruder",
                    "decision": "intruder",
                    "runtime_decision": "intruder",
                    "runtime_status": "intruder",
                    "input_pipeline_status": "evaluated_window",
                    "risk_level": "high",
                    "raw_model_risk": 83.0,
                    "observed_model_risk": 83.0,
                    "decision_risk": 83.0,
                    "runtime_window_count": 4,
                    "runtime_quality_ok_windows": 4,
                }
            return default or {}

        def write_session_state(self, state):
            self.written = dict(state)

    class Bridge:
        _current_user = {"user_id": "u1"}
        _pending_logger_session_id = ""
        _pending_logger_user_id = ""
        _pending_monitor_user_id = ""

    monkeypatch.setattr(helpers, "_facade", lambda: Facade())
    merged = helpers.merge_worker_heartbeats_into_state(
        Bridge(),
        {
            "session_id": "s1",
            "user_id": "u1",
            "active": True,
            "runtime_decision": "pending",
            "runtime_status": "collecting",
            "input_pipeline_status": "pending",
            "risk_level": "unknown",
        },
    )

    assert merged["runtime_decision"] == "intruder"
    assert merged["runtime_status"] == "intruder"
    assert merged["input_pipeline_status"] == "evaluated_window"
    assert merged["risk_level"] == "high"
    assert merged["decision_risk"] == 83.0


def test_protected_lifecycle_wrappers_still_delegate(monkeypatch) -> None:
    from bioauth_runtime.supervisor import protection_session_controller, resume_controller, stop_controller

    calls = []
    monkeypatch.setattr(protection_session_controller, "start_protection", lambda bridge, **kwargs: calls.append(("start", kwargs)) or True)
    monkeypatch.setattr(stop_controller, "stop_protection", lambda bridge, **kwargs: calls.append(("stop", kwargs)) or {"ok": True})
    monkeypatch.setattr(resume_controller, "maybe_resume_after_unlock", lambda bridge, **kwargs: calls.append(("resume", kwargs)) or False)

    assert helpers.start_protected_session(object(), auto_resume=False, trigger_refresh=True) is True
    helpers.stop_production_monitor(object(), silent=True)
    assert helpers.maybe_resume_protection_after_unlock(object(), state={"status": "resume_pending"}) is False

    assert calls == [
        ("start", {"auto_resume": False, "trigger_refresh": True}),
        ("stop", {"reason": "user_requested", "silent": True}),
        ("resume", {"state": {"status": "resume_pending"}}),
    ]
