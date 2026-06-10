from __future__ import annotations

import importlib
import os
from pathlib import Path


def test_live_input_snapshot_reads_chunked_logs_through_decrypt_helper(monkeypatch, tmp_path):
    reader = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.live_input_reader"))
    live = tmp_path / "live"
    keyboard_chunks = live / "keyboard_log.csv.d"
    mouse_chunks = live / "mouse_log.csv.d"
    keyboard_chunks.mkdir(parents=True)
    mouse_chunks.mkdir(parents=True)
    (keyboard_chunks / "counter").write_text("2", encoding="utf-8")
    (mouse_chunks / "counter").write_text("1", encoding="utf-8")
    (keyboard_chunks / "00000000.enc").write_text("encrypted", encoding="utf-8")
    (keyboard_chunks / "00000001.enc").write_text("encrypted", encoding="utf-8")
    (mouse_chunks / "00000000.enc").write_text("encrypted", encoding="utf-8")
    calls = []

    def fake_read_decrypted(path, header, *, strict=False):
        calls.append((Path(path).name, header, strict))
        if Path(path).name == "keyboard_log.csv":
            return "key,event,timestamp\na,press,1.0\na,release,1.1\n"
        return "x,y,event,timestamp\n1,2,move,1.0\n"

    monkeypatch.setattr(reader, "read_decrypted", fake_read_decrypted)

    snapshot = reader.live_input_snapshot(str(live))

    assert snapshot["keyboard_counter"] == 2
    assert snapshot["mouse_counter"] == 1
    assert snapshot["keyboard_rows"] == 2
    assert snapshot["mouse_rows"] == 1
    assert snapshot["input_rows"] == 3
    assert snapshot["chunk_store_present"] is True
    assert calls == [
        ("keyboard_log.csv", "key,event,timestamp", True),
        ("mouse_log.csv", "x,y,event,timestamp", True),
    ]


def test_live_input_snapshot_does_not_count_empty_placeholder_logs(monkeypatch, tmp_path):
    reader = importlib.reload(importlib.import_module("bioauth_runtime.monitor_worker.live_input_reader"))
    live = tmp_path / "live"
    (live / "keyboard_log.csv.d").mkdir(parents=True)
    (live / "mouse_log.csv.d").mkdir(parents=True)
    (live / "keyboard_log.csv.d" / "counter").write_text("0", encoding="utf-8")
    (live / "mouse_log.csv.d" / "counter").write_text("0", encoding="utf-8")

    def fake_read_decrypted(path, header, *, strict=False):
        return header + "\n"

    monkeypatch.setattr(reader, "read_decrypted", fake_read_decrypted)

    snapshot = reader.live_input_snapshot(str(live))

    assert snapshot["keyboard_rows"] == 0
    assert snapshot["mouse_rows"] == 0
    assert snapshot["input_rows"] == 0


def test_predict_runtime_uses_current_live_session_dir_and_publishes_counters(monkeypatch, tmp_path):
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

    monkeypatch.setattr(reader, "read_decrypted", fake_read_decrypted)
    monkeypatch.setenv("BIOAUTH_LIVE_SESSION_DIR", str(live))

    class Facade:
        LIVE_SESSION_DIR = str(tmp_path / "stale-default")

        @staticmethod
        def read_session_state(default=None):
            return {"live_session_dir": str(tmp_path / "stale-state")}

        @staticmethod
        def predict_from_session_details(model, session_path, **kwargs):
            captured["session_path"] = session_path
            return {
                "final": "unknown",
                "raw": 0.0,
                "risk": 0,
                "ml": 0,
                "status": "insufficient_windows",
                "window_count": 0,
                "runtime_performance": {"counts": {}},
            }

    monkeypatch.setattr(common, "_facade", lambda: Facade)

    result = common._predict_runtime({"model": object(), "metadata": {}, "classifier": None})

    assert captured["session_path"] == str(live)
    assert result["status"] == "insufficient_windows"
    assert result["live_input"]["keyboard_counter"] == 3
    assert result["live_input"]["mouse_counter"] == 4
    assert result["live_input"]["keyboard_rows"] == 1
    assert result["live_input"]["mouse_rows"] == 2
    assert result["runtime_performance"]["counts"]["live_keyboard_counter"] == 3
