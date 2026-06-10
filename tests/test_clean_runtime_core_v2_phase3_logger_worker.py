from __future__ import annotations

import importlib
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_root_logger_importable_without_legacy_runtime_import():
    module = importlib.import_module("logger")
    assert callable(module.run_logger)
    assert callable(module.main)


def test_root_logger_delegates_to_logger_worker_main(monkeypatch, tmp_path):
    main_mod = importlib.import_module("bioauth_runtime.logger_worker.main")
    import logger

    calls: list[str] = []

    def fake_legacy():
        return SimpleNamespace(run_logger=lambda: calls.append("run") or 0)

    monkeypatch.setattr(main_mod, "_legacy_logger_impl", fake_legacy)
    monkeypatch.setenv("BIOAUTH_SESSION_ID", "sid-1")
    monkeypatch.setenv("BIOAUTH_RUN_ID", "run-1")
    monkeypatch.setenv("BIOAUTH_LIVE_SESSION_DIR", str(tmp_path / "live"))

    assert logger.run_logger(["alice", "protected"]) == 0
    assert calls == ["run"]


def test_existing_cli_syntax_parses_protected_session(monkeypatch, tmp_path):
    from bioauth_runtime.logger_worker.config import parse_logger_config

    monkeypatch.setenv("BIOAUTH_SESSION_ID", "sid-cli")
    monkeypatch.setenv("BIOAUTH_RUN_ID", "run-cli")
    monkeypatch.setenv("BIOAUTH_LIVE_SESSION_DIR", str(tmp_path / "live"))

    cfg = parse_logger_config(["Alice Example", "protected"])
    assert cfg.user_id == "Alice Example"
    assert cfg.safe_user == "alice_example"
    assert cfg.session_kind == "protected"
    assert cfg.control_name == "logger_user_alice_example"


def test_logger_config_resolves_session_environment(monkeypatch, tmp_path):
    from bioauth_runtime.logger_worker.config import parse_logger_config

    monkeypatch.setenv("BIOAUTH_SESSION_ID", "session-env")
    monkeypatch.setenv("BIOAUTH_RUN_ID", "run-env")
    monkeypatch.setenv("BIOAUTH_LIVE_SESSION_DIR", str(tmp_path / "session"))

    cfg = parse_logger_config(["bob", "protected"])
    assert cfg.session_id == "session-env"
    assert cfg.run_id == "run-env"
    assert cfg.live_session_dir == str(tmp_path / "session")


def test_heartbeat_writer_uses_temp_file_and_replace(monkeypatch, tmp_path):
    from bioauth_runtime.logger_worker import heartbeat

    final = tmp_path / "control" / "worker_heartbeats" / "logger_heartbeat.json"
    replace_calls: list[tuple[str, str]] = []
    real_replace = os.replace

    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(final))

    def replace_spy(src: str, dst: str) -> None:
        replace_calls.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr(heartbeat.os, "replace", replace_spy)
    assert heartbeat.write_logger_heartbeat_payload({"session_id": "sid", "logger_ready": True}) is True
    assert final.exists()
    assert replace_calls
    assert replace_calls[0][0].endswith(".tmp")
    assert replace_calls[0][1] == str(final)


def test_heartbeat_writer_creates_directory(monkeypatch, tmp_path):
    from bioauth_runtime.logger_worker import heartbeat

    final = tmp_path / "missing" / "worker_heartbeats" / "logger_heartbeat.json"
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(final))
    assert heartbeat.write_logger_heartbeat_payload({"session_id": "sid"}) is True
    assert final.exists()


def test_heartbeat_permission_error_is_logged_and_nonfatal(monkeypatch, tmp_path, caplog):
    from bioauth_runtime.logger_worker import heartbeat

    final = tmp_path / "control" / "worker_heartbeats" / "logger_heartbeat.json"
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(final))
    monkeypatch.setattr(heartbeat.os, "replace", lambda *_args: (_ for _ in ()).throw(PermissionError("locked")))
    heartbeat._last_permission_warning_at = 0.0

    with caplog.at_level(logging.WARNING):
        assert heartbeat.write_logger_heartbeat_payload({"session_id": "sid"}) is False
    assert "will retry" in caplog.text


def test_clean_stale_logger_temp_heartbeats_keeps_monitor_files(monkeypatch, tmp_path):
    from bioauth_runtime.logger_worker import heartbeat

    hb_dir = tmp_path / "worker_heartbeats"
    hb_dir.mkdir()
    logger_tmp = hb_dir / "logger_heartbeat.json.1.tmp"
    monitor_tmp = hb_dir / "monitor_heartbeat.json.1.tmp"
    logger_tmp.write_text("{}", encoding="utf-8")
    monitor_tmp.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(hb_dir / "logger_heartbeat.json"))

    assert heartbeat.clean_stale_logger_temp_heartbeats() == 1
    assert not logger_tmp.exists()
    assert monitor_tmp.exists()


def test_logger_readiness_heartbeat_contains_supervisor_fields(monkeypatch, tmp_path):
    from bioauth_runtime.logger_worker import heartbeat

    final = tmp_path / "worker_heartbeats" / "logger_heartbeat.json"
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(final))
    payload = {
        "session_id": "sid",
        "run_id": "run",
        "logger_ready": True,
        "logger_pid": 123,
        "live_session_dir": "live",
        "session_kind": "protected",
    }
    assert heartbeat.write_logger_heartbeat_payload(payload)
    data = json.loads(final.read_text(encoding="utf-8"))
    for key in payload:
        assert data[key] == payload[key]
    assert data["worker_kind"] == "logger"


def test_logger_final_heartbeat_is_written(monkeypatch, tmp_path):
    from bioauth_runtime.logger_worker import heartbeat

    final = tmp_path / "worker_heartbeats" / "logger_heartbeat.json"
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(final))
    assert heartbeat.write_logger_heartbeat_payload({"session_id": "sid", "logger_finalized": True, "logger_ready": False})
    data = json.loads(final.read_text(encoding="utf-8"))
    assert data["logger_finalized"] is True
    assert data["logger_ready"] is False


def test_stop_signal_uses_existing_control_layer(monkeypatch):
    from bioauth_runtime.logger_worker import shutdown

    seen: list[str] = []
    monkeypatch.setattr(shutdown, "should_stop", lambda name: seen.append(name) or True)
    assert shutdown.should_stop_logger("logger_user_alice") is True
    assert seen == ["logger_user_alice"]


def test_logger_worker_new_modules_do_not_import_forbidden_runtime_systems():
    package = Path("bioauth_runtime/logger_worker")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    forbidden = [
        "import monitor",
        "monitor_core",
        "model_inference",
        "identity_confirmation",
        "lock_screen",
        "shadow_core",
        "auto_training",
        "auto_promotion",
        "demo_classic",
        "passive_auto",
    ]
    for token in forbidden:
        assert token not in combined


def test_root_logger_is_thin_wrapper():
    source = Path("logger.py").read_text(encoding="utf-8")
    assert "bioauth_runtime.logger_worker.main" in source
    assert "keyboard.Listener" not in source
    assert "mouse.Listener" not in source
    assert "append_encrypted_rows" not in source


def test_monitor_wrapper_remains_preserved():
    source = Path("monitor.py").read_text(encoding="utf-8")
    assert "bioauth_runtime.monitor_worker.main" in source
    assert "def monitor" in source
