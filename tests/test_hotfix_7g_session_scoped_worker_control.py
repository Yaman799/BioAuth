from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path
import types


class FakeListener:
    def __init__(self, *args, alive=True, **kwargs):
        self.alive = alive
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.alive = False

    def join(self, timeout=None):
        return None

    def is_alive(self):
        return bool(self.alive)


def _patch_control_dir(monkeypatch, tmp_path):
    import control

    monkeypatch.setattr(control, "CONTROL_DIR", str(tmp_path))
    tmp_path.mkdir(parents=True, exist_ok=True)
    return control


def _write_control(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _load_logger_impl(monkeypatch):
    fake_keyboard = types.ModuleType("pynput.keyboard")
    fake_mouse = types.ModuleType("pynput.mouse")
    fake_keyboard.Listener = FakeListener
    fake_mouse.Listener = FakeListener
    fake_pynput = types.ModuleType("pynput")
    fake_pynput.keyboard = fake_keyboard
    fake_pynput.mouse = fake_mouse
    monkeypatch.setitem(sys.modules, "pynput", fake_pynput)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", fake_keyboard)
    monkeypatch.setitem(sys.modules, "pynput.mouse", fake_mouse)
    src_path = str(Path.cwd() / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    sys.modules.pop("bioauth.input.logger_impl", None)
    return importlib.import_module("bioauth.input.logger_impl")


def _prime_logger(mod, monkeypatch, tmp_path):
    _patch_control_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("BIOAUTH_SESSION_ID", "sess-current")
    monkeypatch.setenv("BIOAUTH_RUN_ID", "run-current")
    mod.ARGS.update({
        "legacy": False,
        "safe_user": "yaman",
        "session_label": "yaman",
        "session_kind": "protected",
        "control_name": "logger_user_yaman",
    })
    mod.SESSION_ID = "sess-current"
    mod.SESSION_RUN_ID = "run-current"
    mod.SESSION_STARTED_AT = time.time()
    mod.CONTROL_NAME = "logger_user_yaman"
    mod._stop_event.clear()
    mod._reset_listener_health()
    mod._reset_capture_counters()
    monkeypatch.setattr(mod.time, "sleep", lambda *_args, **_kwargs: None)
    payloads: list[dict] = []
    monkeypatch.setattr(mod, "write_logger_heartbeat_payload", lambda payload: payloads.append(dict(payload)) or True)
    monkeypatch.setattr(mod, "read_session_state", lambda default=None: {"session_id": "sess-current", "session_kind": "protected", "mode": "monitored", "monitor_ready": True})
    return payloads


def test_logger_ignores_old_session_control_file(monkeypatch, tmp_path):
    control = _patch_control_dir(monkeypatch, tmp_path)
    _write_control(tmp_path, "logger_user_yaman", {
        "stop": True,
        "worker_key": "logger_user_yaman",
        "session_id": "old-session",
        "run_id": "run-current",
        "reason": "user_stop",
        "ts": time.time() + 1,
    })

    status = control.stop_control_status(
        "logger_user_yaman",
        worker_key="logger_user_yaman",
        session_id="sess-current",
        run_id="run-current",
        worker_started_at=time.time() - 1,
        allowed_reasons={"user_stop"},
    )

    assert status["should_stop"] is False
    assert status["ignored_stale_control_file"] is True
    assert status["ignore_reason"] == "session_id_mismatch_or_missing"


def test_logger_ignores_old_run_control_file(monkeypatch, tmp_path):
    control = _patch_control_dir(monkeypatch, tmp_path)
    _write_control(tmp_path, "logger_user_yaman", {
        "stop": True,
        "worker_key": "logger_user_yaman",
        "session_id": "sess-current",
        "run_id": "old-run",
        "reason": "user_stop",
        "ts": time.time() + 1,
    })

    status = control.stop_control_status(
        "logger_user_yaman",
        worker_key="logger_user_yaman",
        session_id="sess-current",
        run_id="run-current",
        worker_started_at=time.time() - 1,
        allowed_reasons={"user_stop"},
    )

    assert status["should_stop"] is False
    assert status["ignore_reason"] == "run_id_mismatch_or_missing"


def test_logger_ignores_unscoped_legacy_stop_file(monkeypatch, tmp_path):
    control = _patch_control_dir(monkeypatch, tmp_path)
    _write_control(tmp_path, "logger_user_yaman", {"stop": True, "ts": time.time() + 1})

    status = control.stop_control_status(
        "logger_user_yaman",
        worker_key="logger_user_yaman",
        session_id="sess-current",
        run_id="run-current",
        worker_started_at=time.time() - 1,
        allowed_reasons={"user_stop"},
    )

    assert status["should_stop"] is False
    assert status["ignored_stale_control_file"] is True
    assert status["ignore_reason"] == "worker_key_mismatch_or_missing"


def test_logger_honors_matching_session_control_file(monkeypatch, tmp_path):
    control = _patch_control_dir(monkeypatch, tmp_path)
    _write_control(tmp_path, "logger_user_yaman", {
        "stop": True,
        "worker_key": "logger_user_yaman",
        "session_id": "sess-current",
        "run_id": "run-current",
        "reason": "user_stop",
        "ts": time.time() + 1,
    })

    status = control.stop_control_status(
        "logger_user_yaman",
        worker_key="logger_user_yaman",
        session_id="sess-current",
        run_id="run-current",
        worker_started_at=time.time() - 1,
        allowed_reasons={"user_stop"},
    )

    assert status["should_stop"] is True
    assert status["control_file_valid"] is True


def test_monitor_ignores_old_unscoped_and_honors_matching(monkeypatch, tmp_path):
    control = _patch_control_dir(monkeypatch, tmp_path)
    _write_control(tmp_path, "monitor", {"stop": True, "ts": time.time() + 1})
    stale = control.stop_control_status(
        "monitor",
        worker_key="monitor",
        session_id="sess-current",
        run_id="run-current",
        worker_started_at=time.time() - 1,
        allowed_reasons={"user_stop"},
    )
    assert stale["should_stop"] is False

    _write_control(tmp_path, "monitor", {
        "stop": True,
        "worker_key": "monitor",
        "session_id": "sess-current",
        "run_id": "run-current",
        "reason": "user_stop",
        "ts": time.time() + 1,
    })
    valid = control.stop_control_status(
        "monitor",
        worker_key="monitor",
        session_id="sess-current",
        run_id="run-current",
        worker_started_at=time.time() - 1,
        allowed_reasons={"user_stop"},
    )
    assert valid["should_stop"] is True


def test_request_stop_writes_session_scope_from_current_state(monkeypatch, tmp_path):
    control = _patch_control_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(control, "read_session_state", lambda default=None: {
        "session_kind": "protected",
        "user_id": "yaman",
        "session_id": "sess-current",
        "run_id": "run-current",
    })

    control.request_stop("monitor", reason="user_requested", source_module="test", source_function="case")
    payload = json.loads((tmp_path / "monitor.json").read_text(encoding="utf-8"))

    assert payload["worker_key"] == "monitor"
    assert payload["user_id"] == "yaman"
    assert payload["session_id"] == "sess-current"
    assert payload["run_id"] == "run-current"
    assert payload["reason"] == "user_stop"
    assert payload["source_module"] == "test"
    assert payload["source_function"] == "case"


def test_start_protection_clears_stale_logger_and_monitor_controls():
    source = Path("bioauth_runtime/supervisor/protection_session_controller.py").read_text(encoding="utf-8")
    assert 'facade.clear_stop(bridge._logger_key())' in source
    assert 'facade.clear_stop("monitor")' in source
    assert '"logger_legit"' in source
    assert '"logger_intruder"' in source


def test_logger_remains_alive_with_stale_control_file(monkeypatch, tmp_path):
    mod = _load_logger_impl(monkeypatch)
    payloads = _prime_logger(mod, monkeypatch, tmp_path)
    _write_control(tmp_path, "logger_user_yaman", {"stop": True, "ts": time.time() + 1})
    mod.kb_listener = FakeListener(alive=True)
    mod.ms_listener = FakeListener(alive=True)
    mod._mark_listener_started("keyboard")
    mod._mark_listener_started("mouse")

    result = mod._supervised_capture_loop(poll_interval=0.01, heartbeat_interval=0.01, max_iterations=3)

    assert result == "test_limit"
    assert not mod._stop_event.is_set()
    assert payloads[-1]["ignored_stale_control_file"] is True
    assert payloads[-1]["stop_requested"] is False
    assert payloads[-1]["final_stop_reason"] != "control_stop"


def test_logger_honors_matching_control_file(monkeypatch, tmp_path):
    mod = _load_logger_impl(monkeypatch)
    payloads = _prime_logger(mod, monkeypatch, tmp_path)
    _write_control(tmp_path, "logger_user_yaman", {
        "stop": True,
        "worker_key": "logger_user_yaman",
        "session_id": "sess-current",
        "run_id": "run-current",
        "reason": "user_stop",
        "ts": time.time() + 1,
    })
    mod.kb_listener = FakeListener(alive=True)
    mod.ms_listener = FakeListener(alive=True)
    mod._mark_listener_started("keyboard")
    mod._mark_listener_started("mouse")

    result = mod._supervised_capture_loop(poll_interval=0.01, heartbeat_interval=0.01, max_iterations=5)

    assert result == "control_stop"
    assert mod._current_stop_reason() == "control_stop"
    assert mod._control_status_snapshot()["control_file_valid"] is True


def test_final_archive_source_contains_control_diagnostics():
    source = Path("src/bioauth/input/logger_impl.py").read_text(encoding="utf-8")
    assert "_control_status_snapshot()" in source
    assert "control_file_valid" in source
    assert "ignored_stale_control_file" in source


def test_refresh_dashboard_sources_do_not_request_worker_stop_during_protected_active():
    refresh = Path("bridge/refresh_runtime_helpers.py").read_text(encoding="utf-8")
    dashboard = Path("bridge/refresh_dashboard_helpers.py").read_text(encoding="utf-8")
    perform = refresh.split("def _perform_refresh_now", 1)[1].split("def _finish_refresh_cycle", 1)[0]
    assert "request_stop(" not in dashboard
    assert "request_stop(" not in perform


def test_runtime_decision_pending_maps_to_pending_not_normal():
    from bridge.runtime_labels import runtime_decision_key

    assert runtime_decision_key("pending") == "decision_pending"
    assert runtime_decision_key("") == "decision_idle"
    assert runtime_decision_key("legit") == "decision_legit"


def test_logger_allowed_stop_reasons_are_explicit_current_session_reasons_only():
    from bioauth_runtime.logger_worker import shutdown

    assert shutdown._ALLOWED_LOGGER_STOP_REASONS == {
        "user_stop",
        "app_shutdown",
        "supervisor_stop",
        "monitor_failed_pair_stop",
        "test_stop",
    }
    assert "control_stop" not in shutdown._ALLOWED_LOGGER_STOP_REASONS
    assert "logger_exited_after_ready" not in shutdown._ALLOWED_LOGGER_STOP_REASONS
    assert "monitor_exited_after_ready" not in shutdown._ALLOWED_LOGGER_STOP_REASONS


def test_monitor_allowed_stop_reasons_are_explicit_current_session_reasons_only():
    from bioauth_runtime.monitor_worker import shutdown

    assert shutdown._ALLOWED_MONITOR_STOP_REASONS == {
        "user_stop",
        "app_shutdown",
        "supervisor_stop",
        "logger_failed_pair_stop",
        "test_stop",
    }
    assert "control_stop" not in shutdown._ALLOWED_MONITOR_STOP_REASONS
    assert "logger_exited_after_ready" not in shutdown._ALLOWED_MONITOR_STOP_REASONS
    assert "monitor_exited_after_ready" not in shutdown._ALLOWED_MONITOR_STOP_REASONS


def test_unscoped_control_stop_is_ignored_by_worker_shutdown_helpers(monkeypatch, tmp_path):
    _patch_control_dir(monkeypatch, tmp_path)
    _write_control(tmp_path, "logger_user_yaman", {"stop": True, "ts": time.time() + 1})
    _write_control(tmp_path, "monitor", {"stop": True, "ts": time.time() + 1})
    monkeypatch.setenv("BIOAUTH_SESSION_ID", "sess-current")
    monkeypatch.setenv("BIOAUTH_RUN_ID", "run-current")

    from bioauth_runtime.logger_worker.shutdown import logger_stop_control_status
    from bioauth_runtime.monitor_worker.shutdown import monitor_stop_control_status

    logger_status = logger_stop_control_status("logger_user_yaman", worker_started_at=time.time() - 1)
    monitor_status = monitor_stop_control_status("monitor", worker_started_at=time.time() - 1)

    assert logger_status["should_stop"] is False
    assert logger_status["control_file_valid"] is False
    assert logger_status["ignored_stale_control_file"] is True
    assert monitor_status["should_stop"] is False
    assert monitor_status["control_file_valid"] is False
    assert monitor_status["ignored_stale_control_file"] is True
