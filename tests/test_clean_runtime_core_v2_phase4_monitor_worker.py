from __future__ import annotations

import importlib
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace


def test_root_monitor_importable_without_legacy_runtime_import():
    module = importlib.import_module("monitor")
    assert callable(module.monitor)
    assert callable(module.main)
    assert callable(module.run_monitor)


def test_root_monitor_delegates_to_monitor_worker_main(monkeypatch, tmp_path):
    main_mod = importlib.import_module("bioauth_runtime.monitor_worker.main")
    import monitor

    calls: list[str] = []

    def fake_legacy():
        return SimpleNamespace(monitor=lambda: calls.append("run") or 0)

    monkeypatch.setattr(main_mod, "_legacy_monitor_impl", fake_legacy)
    monkeypatch.setenv("BIOAUTH_SESSION_ID", "sid-1")
    monkeypatch.setenv("BIOAUTH_LIVE_SESSION_DIR", str(tmp_path / "live"))

    assert monitor.run_monitor(["alice"]) == 0
    assert calls == ["run"]


def test_existing_cli_syntax_parses_user(monkeypatch, tmp_path):
    from bioauth_runtime.monitor_worker.config import parse_monitor_config

    monkeypatch.setenv("BIOAUTH_SESSION_ID", "sid-cli")
    monkeypatch.setenv("BIOAUTH_LIVE_SESSION_DIR", str(tmp_path / "live"))

    cfg = parse_monitor_config(["Alice Example"])
    assert cfg.user_id == "Alice Example"
    assert cfg.safe_user == "alice_example"
    assert cfg.session_id == "sid-cli"
    assert cfg.live_session_dir == str(tmp_path / "live")
    assert cfg.control_name == "monitor"


def test_monitor_heartbeat_writer_uses_temp_file_and_replace(monkeypatch, tmp_path):
    from bioauth_runtime.monitor_worker import heartbeat

    final = tmp_path / "control" / "worker_heartbeats" / "monitor_heartbeat.json"
    replace_calls: list[tuple[str, str]] = []
    real_replace = os.replace

    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(final))

    def replace_spy(src: str, dst: str) -> None:
        replace_calls.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr(heartbeat.os, "replace", replace_spy)
    assert heartbeat.write_monitor_heartbeat_payload({"session_id": "sid", "monitor_ready": True}) is True
    assert final.exists()
    assert replace_calls
    assert replace_calls[0][0].endswith(".tmp")
    assert replace_calls[0][1] == str(final)


def test_monitor_heartbeat_writer_creates_directory(monkeypatch, tmp_path):
    from bioauth_runtime.monitor_worker import heartbeat

    final = tmp_path / "missing" / "worker_heartbeats" / "monitor_heartbeat.json"
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(final))
    assert heartbeat.write_monitor_heartbeat_payload({"session_id": "sid"}) is True
    assert final.exists()


def test_monitor_heartbeat_permission_error_is_logged_and_nonfatal(monkeypatch, tmp_path, caplog):
    from bioauth_runtime.monitor_worker import heartbeat

    final = tmp_path / "control" / "worker_heartbeats" / "monitor_heartbeat.json"
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(final))
    monkeypatch.setattr(heartbeat.os, "replace", lambda *_args: (_ for _ in ()).throw(PermissionError("locked")))
    heartbeat._last_permission_warning_at = 0.0

    with caplog.at_level(logging.WARNING):
        assert heartbeat.write_monitor_heartbeat_payload({"session_id": "sid"}) is False
    assert "will retry" in caplog.text


def test_clean_stale_monitor_temp_heartbeats_keeps_logger_files(monkeypatch, tmp_path):
    from bioauth_runtime.monitor_worker import heartbeat

    hb_dir = tmp_path / "worker_heartbeats"
    hb_dir.mkdir()
    monitor_tmp = hb_dir / "monitor_heartbeat.json.1.tmp"
    logger_tmp = hb_dir / "logger_heartbeat.json.1.tmp"
    monitor_tmp.write_text("{}", encoding="utf-8")
    logger_tmp.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(hb_dir / "monitor_heartbeat.json"))

    assert heartbeat.clean_stale_monitor_temp_heartbeats() == 1
    assert not monitor_tmp.exists()
    assert logger_tmp.exists()


def test_monitor_readiness_heartbeat_contains_supervisor_fields(monkeypatch, tmp_path):
    from bioauth_runtime.monitor_worker import heartbeat

    final = tmp_path / "worker_heartbeats" / "monitor_heartbeat.json"
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(final))
    payload = {
        "session_id": "sid",
        "run_id": "run",
        "monitor_ready": True,
        "monitor_pid": 123,
        "live_session_dir": "live",
        "session_kind": "protected",
    }
    assert heartbeat.write_monitor_heartbeat_payload(payload)
    data = json.loads(final.read_text(encoding="utf-8"))
    for key in payload:
        assert data[key] == payload[key]
    assert data["worker_kind"] == "monitor"


def test_monitor_final_heartbeat_is_written(monkeypatch, tmp_path):
    from bioauth_runtime.monitor_worker import heartbeat

    final = tmp_path / "worker_heartbeats" / "monitor_heartbeat.json"
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(final))
    assert heartbeat.write_monitor_heartbeat_payload({"session_id": "sid", "monitor_finalized": True, "monitor_ready": False})
    data = json.loads(final.read_text(encoding="utf-8"))
    assert data["monitor_finalized"] is True
    assert data["monitor_ready"] is False


def test_stop_signal_uses_existing_control_layer(monkeypatch):
    from bioauth_runtime.monitor_worker import shutdown

    seen: list[str] = []
    monkeypatch.setattr(shutdown, "should_stop", lambda name: seen.append(name) or True)
    assert shutdown.should_stop_monitor("monitor") is True
    assert seen == ["monitor"]


def test_decision_engine_returns_all_required_runtime_fields():
    from bioauth_runtime.monitor_worker.decision_engine import REQUIRED_DECISION_FIELDS, build_runtime_decision_payload

    payload = build_runtime_decision_payload({
        "risk": 91.2,
        "raw": 93.4,
        "decision": "intruder",
        "status": "monitoring",
        "fresh_window": True,
        "runtime_prediction_ready": True,
    })
    for key in REQUIRED_DECISION_FIELDS:
        assert key in payload
    assert payload["raw_model_risk"] == 93.4
    assert payload["decision_risk"] == 91.2
    assert payload["runtime_decision"] == "intruder"
    assert payload["high_risk_evidence"] is True


def test_runtime_summary_writer_publishes_exact_payload(monkeypatch, tmp_path):
    from bioauth_runtime.monitor_worker import runtime_summary_writer as writer

    monkeypatch.setattr(writer, "CONTROL_DIR", str(tmp_path))
    payload = {"session_id": "sid", "decision_risk": 88.0, "runtime_decision": "suspicious"}
    assert writer.write_runtime_summary_payload(payload)
    data = json.loads((tmp_path / "runtime_summary.json").read_text(encoding="utf-8"))
    assert data == payload


def test_monitor_core_common_publishes_authoritative_decision(monkeypatch, tmp_path):
    import monitor_core.common as common
    from bioauth_runtime.monitor_worker import heartbeat, runtime_summary_writer

    hb = tmp_path / "worker_heartbeats" / "monitor_heartbeat.json"
    monkeypatch.setattr(heartbeat, "worker_heartbeat_path", lambda _kind: str(hb))
    monkeypatch.setattr(runtime_summary_writer, "CONTROL_DIR", str(tmp_path))

    class Facade:
        EXPECTED_USER_SLUG = "alice"
        _normalize_state_label = staticmethod(lambda label: label)
        read_session_state = staticmethod(lambda default=None: {"session_id": "sid", "active": True})

    monkeypatch.setattr(common, "_facade", lambda: Facade)
    common._write_monitor_state(decision="suspicious", extra={"risk": 82.5, "monitor_ready": True, "fresh_window": True})

    data = json.loads(hb.read_text(encoding="utf-8"))
    assert data["decision_risk"] == 82.5
    assert data["runtime_decision"] == "suspicious"
    assert data["monitor_ready"] is True
    assert json.loads((tmp_path / "runtime_summary.json").read_text(encoding="utf-8"))["decision_risk"] == 82.5


def test_bridge_merge_preserves_monitor_decision_fields():
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "for key, value in monitor_hb.items():" in source
    assert "merged[key] = value" in source
    forbidden_assignments = [
        'merged["decision_risk"] =',
        'merged["raw_model_risk"] =',
        'merged["observed_model_risk"] =',
        'merged["action_risk"] =',
        'merged["display_risk"] =',
        'merged["final_action"] =',
        'merged["lock_reason"] =',
    ]
    for token in forbidden_assignments:
        assert token not in source


def test_monitor_worker_new_modules_do_not_import_forbidden_commercial_side_effects():
    package = Path("bioauth_runtime/monitor_worker")
    phase4_files = [
        path for path in package.glob("*.py")
        if path.name not in {"face_gate.py", "lock_controller.py"}
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in phase4_files)
    forbidden = [
        "auto_training",
        "auto_promotion",
        "shadow_core",
        "demo_classic",
        "passive_auto",
        "start_protection",
        "stop_protection",
        "request_stop(\"logger",
        "lock_current_session",
        "identity_confirmation",
    ]
    for token in forbidden:
        assert token not in combined


def test_root_monitor_is_thin_wrapper():
    source = Path("monitor.py").read_text(encoding="utf-8")
    assert "bioauth_runtime.monitor_worker.main" in source
    assert "bioauth.runtime.monitor_impl" not in source
    assert "predict_from_session_details" not in source
    assert "lock_current_session" not in source


def test_logger_wrapper_remains_preserved():
    source = Path("logger.py").read_text(encoding="utf-8")
    assert "bioauth_runtime.logger_worker.main" in source
    assert "keyboard.Listener" not in source
