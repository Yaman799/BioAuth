from __future__ import annotations

import importlib
import os
from pathlib import Path


def test_monitor_common_still_reads_current_chunked_live_input(monkeypatch, tmp_path) -> None:
    common = importlib.reload(importlib.import_module("monitor_core.common"))
    reader = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.live_input_reader"))
    live = tmp_path / "live-current"
    (live / "keyboard_log.csv.d").mkdir(parents=True)
    (live / "mouse_log.csv.d").mkdir(parents=True)
    (live / "keyboard_log.csv.d" / "counter").write_text("3", encoding="utf-8")
    (live / "mouse_log.csv.d" / "counter").write_text("4", encoding="utf-8")
    captured = {}

    def fake_read_decrypted(path, header, *, strict=False):
        if Path(path).name == "keyboard_log.csv":
            return "key,event,timestamp\na,press,1.0\n"
        return "x,y,event,timestamp\n1,2,move,1.0\n2,3,move,1.1\n"

    class Facade:
        LIVE_SESSION_DIR = str(tmp_path / "stale-default")

        @staticmethod
        def read_session_state(default=None):
            return {"live_session_dir": str(tmp_path / "stale-state")}

        @staticmethod
        def predict_from_session_details(model, session_path, **kwargs):
            captured["session_path"] = session_path
            return {"final": "unknown", "raw": 0.0, "risk": 0, "ml": 0, "status": "insufficient_windows", "window_count": 0, "runtime_performance": {"counts": {}}}

    monkeypatch.setattr(reader, "read_decrypted", fake_read_decrypted)
    monkeypatch.setattr(common, "_facade", lambda: Facade)
    monkeypatch.setenv("BIOAUTH_LIVE_SESSION_DIR", str(live))

    result = common._predict_runtime({"model": object(), "metadata": {}, "classifier": None})

    assert captured["session_path"] == str(live)
    assert result["live_input"]["keyboard_counter"] == 3
    assert result["live_input"]["mouse_counter"] == 4
    assert result["runtime_performance"]["counts"]["live_keyboard_counter"] == 3


def test_monitor_decision_promotion_contract_survives_split() -> None:
    from bioauth_runtime.monitor_worker import decision_engine

    payload = decision_engine.build_runtime_decision_payload(
        {
            "status": "intruder",
            "decision": "intruder",
            "runtime_decision": "pending",
            "runtime_status": "collecting",
            "input_pipeline_status": "pending",
            "risk_level": "unknown",
            "risk": 83.0,
            "decision_risk": 83.0,
            "runtime_window_count": 4,
            "runtime_quality_ok_windows": 4,
        }
    )

    assert payload["runtime_decision"] == "intruder"
    assert payload["input_pipeline_status"] == "evaluated_window"
    assert payload["risk_level"] == "high"


def test_logger_split_keeps_legacy_runner_and_heartbeat_writer() -> None:
    logger = importlib.import_module("bioauth.input.logger_impl")

    assert callable(logger.run_logger)
    assert callable(logger._write_logger_heartbeat)
    assert callable(logger._listener_health_snapshot)
    assert "write_logger_heartbeat_payload" in Path("src/bioauth/input/logger_impl.py").read_text(encoding="utf-8")
