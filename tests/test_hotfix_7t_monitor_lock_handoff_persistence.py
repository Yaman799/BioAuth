from __future__ import annotations

import json


def test_monitor_writer_preserves_previous_lock_handoff_publish(monkeypatch, tmp_path):
    import monitor_core.common_split.monitor_log_store as store

    control = tmp_path / "control"
    hb_dir = control / "worker_heartbeats"
    hb_dir.mkdir(parents=True)
    monitor_hb = hb_dir / "monitor_heartbeat.json"
    summary = control / "runtime_summary.json"

    current_state = {
        "session_id": "sess-7t",
        "run_id": "run-7t",
        "user_id": "yaman",
        "session_kind": "protected",
        "active": True,
        "flow": "protected_active",
        "status": "ok",
    }
    handoff = {
        "session_id": "sess-7t",
        "run_id": "run-7t",
        "user_id": "yaman",
        "session_kind": "protected",
        "active": False,
        "flow": "protected_forced_stop",
        "status": "resume_pending",
        "runtime_status": "resume_pending",
        "auto_resume_pending": True,
        "resume_after_unlock": True,
        "forced_stop": True,
        "app_locked": True,
        "lock_controller_handoff": True,
        "lock_handoff_id": "handoff-1",
        "final_decision": "intruder",
        "runtime_telemetry_seq": 4,
    }
    monitor_hb.write_text(json.dumps(handoff), encoding="utf-8")
    summary.write_text(json.dumps(handoff), encoding="utf-8")

    writes = []

    class Facade:
        EXPECTED_USER_SLUG = "yaman"
        def read_session_state(self, default=None):
            return dict(current_state)
        def _normalize_state_label(self, decision):
            return decision

    monkeypatch.setattr(store, "_facade", lambda: Facade())
    import control
    monkeypatch.setattr(control, "CONTROL_DIR", str(control))
    monkeypatch.setattr(control, "worker_heartbeat_path", lambda kind: str(monitor_hb))

    import bioauth_runtime.monitor_worker.heartbeat as heartbeat
    import bioauth_runtime.monitor_worker.runtime_summary_writer as summary_writer
    monkeypatch.setattr(heartbeat, "write_monitor_heartbeat_payload", lambda payload: writes.append(dict(payload)) or True)
    monkeypatch.setattr(summary_writer, "write_runtime_summary_payload", lambda payload: True)

    store._write_monitor_state("pending", extra={"runtime_status": "ok"})

    assert writes, "monitor heartbeat should be rewritten"
    latest = writes[-1]
    assert latest["active"] is False
    assert latest["flow"] == "protected_forced_stop"
    assert latest["status"] == "resume_pending"
    assert latest["auto_resume_pending"] is True
    assert latest["lock_handoff_preserved_from_previous_monitor_publish"] is True


def test_supervisor_expected_exit_uses_monitor_handoff_heartbeat(monkeypatch):
    import bioauth_runtime.supervisor.stop_controller as stop_controller

    state = {
        "session_id": "sess-7t",
        "run_id": "run-7t",
        "user_id": "yaman",
        "session_kind": "protected",
        "active": True,
        "flow": "protected_active",
        "status": "ok",
    }
    monitor_hb = {
        "session_id": "sess-7t",
        "run_id": "run-7t",
        "active": False,
        "flow": "protected_forced_stop",
        "status": "resume_pending",
        "runtime_status": "resume_pending",
        "auto_resume_pending": True,
        "resume_after_unlock": True,
        "forced_stop": True,
        "lock_controller_handoff": True,
        "final_decision": "intruder",
    }
    written = []
    refreshed = []

    class Facade:
        def read_session_state(self, default=None):
            return dict(state)
        def write_session_state(self, payload):
            written.append(dict(payload))
        def read_worker_heartbeat(self, kind, default=None):
            return dict(monitor_hb) if kind == "monitor" else {}

    class Legacy:
        def _facade(self):
            return Facade()

    class Bridge:
        def requestRefresh(self, reason, force=False):
            refreshed.append(reason)

    monkeypatch.setattr(stop_controller, "_legacy", lambda: Legacy())

    ok = stop_controller._expected_exit_after_lock_handoff(Bridge(), "monitor", {"exit_code": 0})

    assert ok is True
    assert written
    latest = written[-1]
    assert latest["active"] is False
    assert latest["flow"] == "protected_forced_stop"
    assert latest["status"] == "resume_pending"
    assert latest["technical_failure"] is False
    assert latest["expected_worker_exit_after_lock_handoff"] is True
