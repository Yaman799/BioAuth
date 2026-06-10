from __future__ import annotations

import importlib
import json
from pathlib import Path


def _valid_intruder_state() -> dict:
    return {
        "session_id": "sess-1",
        "run_id": "run-1",
        "user_id": "alice",
        "session_kind": "protected",
        "active": True,
        "logger_ready": True,
        "monitor_ready": True,
        "status": "intruder",
        "decision": "intruder",
        "runtime_decision": "pending",
        "runtime_status": "collecting",
        "input_pipeline_status": "pending",
        "risk_level": "unknown",
        "risk": 83.0,
        "raw_model_risk": 83.0,
        "observed_model_risk": 83.0,
        "decision_risk": 83.0,
        "runtime_window_count": 4,
        "runtime_quality_ok_windows": 4,
    }


def test_valid_runtime_window_risk_promotes_runtime_decision_from_pending():
    engine = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.decision_engine"))

    payload = engine.build_runtime_decision_payload(_valid_intruder_state())

    assert payload["runtime_decision"] == "intruder"
    assert payload["runtime_status"] == "intruder"
    assert payload["decision_risk"] == 83.0


def test_valid_runtime_window_does_not_leave_input_pipeline_pending():
    engine = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.decision_engine"))

    payload = engine.build_runtime_decision_payload(_valid_intruder_state())

    assert payload["input_pipeline_status"] == "evaluated_window"
    assert payload["evidence_state"] == "evaluated_window"
    assert payload["runtime_prediction_ready"] is True
    assert payload["fresh_window"] is True


def test_risk_level_is_not_unknown_when_real_risk_exists():
    engine = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.decision_engine"))

    payload = engine.build_runtime_decision_payload(_valid_intruder_state())

    assert payload["risk_level"] == "high"


def test_runtime_summary_and_monitor_heartbeat_publish_same_decision_fields(monkeypatch, tmp_path):
    engine = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.decision_engine"))
    summary = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.runtime_summary_writer"))
    heartbeat = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.heartbeat"))
    state = engine.merge_runtime_decision_payload(_valid_intruder_state())
    summary_path = tmp_path / "runtime_summary.json"
    heartbeat_path = tmp_path / "monitor_heartbeat.json"

    monkeypatch.setattr(summary, "runtime_summary_path", lambda: summary_path)
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(heartbeat_path))

    assert summary.write_runtime_summary_payload(state) is True
    assert heartbeat.write_monitor_heartbeat_payload(state) is True

    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    heartbeat_payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    for key in ("runtime_decision", "runtime_status", "decision_risk", "risk_level", "input_pipeline_status"):
        assert summary_payload[key] == heartbeat_payload[key] == state[key]


def test_bridge_merge_preserves_monitor_risk_decision_fields(monkeypatch):
    helpers = importlib.reload(importlib.import_module("bridge.session_runtime_helpers"))
    monitor_payload = importlib.import_module("bioauth_runtime.monitor_worker.decision_engine").merge_runtime_decision_payload(_valid_intruder_state())

    class Facade:
        @staticmethod
        def read_worker_heartbeat(kind, default=None):
            return monitor_payload if kind == "monitor" else {}

        @staticmethod
        def runtime_status_is_technical_failure(_status):
            return False

        @staticmethod
        def write_session_state(_state):
            return True

    monkeypatch.setattr(helpers, "_facade", lambda: Facade)
    bridge = type("Bridge", (), {"_pending_logger_session_id": "", "_pending_monitor_user_id": ""})()
    state = {"session_id": "sess-1", "run_id": "run-1", "user_id": "alice", "session_kind": "protected", "active": True, "runtime_decision": "pending"}

    merged = helpers.merge_worker_heartbeats_into_state(bridge, state)

    assert merged["runtime_decision"] == "intruder"
    assert merged["runtime_status"] == "intruder"
    assert merged["decision_risk"] == 83.0
    assert merged["risk_level"] == "high"
    assert merged["input_pipeline_status"] == "evaluated_window"


def test_empty_placeholder_windows_remain_pending_non_actionable():
    engine = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.decision_engine"))
    state = _valid_intruder_state()
    state.update({
        "status": "insufficient_windows",
        "decision": "pending",
        "runtime_decision": "pending",
        "runtime_window_count": 0,
        "runtime_quality_ok_windows": 0,
        "decision_risk": None,
        "risk": 0,
    })

    payload = engine.build_runtime_decision_payload(state)

    assert payload["runtime_decision"] == "pending"
    assert payload["input_pipeline_status"] == "pending"
    assert payload["risk_actionability"] == "pending"


def test_preserved_idle_windows_remain_non_actionable():
    engine = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.decision_engine"))
    state = _valid_intruder_state()
    state.update({"status": "preserved_idle", "runtime_status": "preserved_idle", "decision": "pending", "runtime_decision": "pending"})

    payload = engine.build_runtime_decision_payload(state)

    assert payload["runtime_decision"] == "pending"
    assert payload["runtime_status"] == "preserved_idle"
    assert payload["risk_actionability"] == "pending"
