from __future__ import annotations

import importlib
import sys
from pathlib import Path
import types
from types import SimpleNamespace


class FakeListener:
    def __init__(self, *args, alive=True, start_error=None, **kwargs):
        self.alive = alive
        self.started = False
        self.start_error = start_error
        self.args = args
        self.kwargs = kwargs
        self.join_called = False

    def start(self):
        if self.start_error:
            raise self.start_error
        self.started = True
        return None

    def stop(self):
        self.alive = False

    def join(self, timeout=None):
        self.join_called = True
        return None

    def is_alive(self):
        return bool(self.alive)


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


def _prime(mod, monkeypatch):
    mod.ARGS.update({
        "legacy": False,
        "safe_user": "alice",
        "session_label": "alice",
        "session_kind": "protected",
        "control_name": "logger_user_alice",
    })
    mod.SESSION_ID = "sess-7f"
    mod.SESSION_RUN_ID = "run-7f"
    mod.CONTROL_NAME = "logger_user_alice"
    mod._stop_event.clear()
    mod._reset_listener_health()
    mod._reset_capture_counters()
    monkeypatch.setattr(mod.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "should_stop_logger", lambda _name: False)
    payloads = []
    monkeypatch.setattr(mod, "write_logger_heartbeat_payload", lambda payload: payloads.append(dict(payload)) or True)
    monkeypatch.setattr(mod, "read_session_state", lambda default=None: {"session_id": "sess-7f", "session_kind": "protected", "mode": "monitored", "monitor_ready": True})
    return payloads


def test_protected_logger_loop_does_not_exit_when_keyboard_listener_returns(monkeypatch):
    mod = _load_logger_impl(monkeypatch)
    _prime(mod, monkeypatch)
    mod.kb_listener = FakeListener(alive=False)
    mod.ms_listener = FakeListener(alive=True)
    mod._mark_listener_started("keyboard")
    mod._mark_listener_started("mouse")

    result = mod._supervised_capture_loop(poll_interval=0.01, heartbeat_interval=0.01, max_iterations=3)

    assert result == "test_limit"
    assert not mod._stop_event.is_set()
    snap = mod._listener_health_snapshot()
    assert snap["keyboard_listener_alive"] is False
    assert snap["mouse_listener_alive"] is True
    assert snap["capture_status"] == "capture_degraded_keyboard_listener_failed"


def test_keyboard_listener_failure_degrades_but_mouse_keeps_logger_alive(monkeypatch):
    mod = _load_logger_impl(monkeypatch)
    payloads = _prime(mod, monkeypatch)
    mod.kb_listener = FakeListener(alive=False)
    mod.ms_listener = FakeListener(alive=True)
    mod._mark_listener_started("mouse")
    mod._mark_listener_error("keyboard", RuntimeError("keyboard backend closed"))

    mod._supervised_capture_loop(poll_interval=0.01, heartbeat_interval=0.01, max_iterations=2)

    assert not mod._stop_event.is_set()
    assert payloads[-1]["capture_status"] == "capture_degraded_keyboard_listener_failed"
    assert "keyboard backend closed" in payloads[-1]["keyboard_listener_error"]


def test_keyboard_callback_exception_is_recorded_in_heartbeat(monkeypatch):
    mod = _load_logger_impl(monkeypatch)
    payloads = _prime(mod, monkeypatch)
    mod.ms_listener = FakeListener(alive=True)
    mod._mark_listener_started("mouse")
    monkeypatch.setattr(mod, "_queue_keyboard_row", lambda _row: (_ for _ in ()).throw(ValueError("bad key")))

    mod.on_press("x")
    mod._write_logger_heartbeat("ok")

    assert "bad key" in payloads[-1]["keyboard_listener_error"]
    assert payloads[-1]["capture_status"] == "capture_degraded_keyboard_listener_failed"


def test_mouse_callback_exception_is_recorded_in_heartbeat(monkeypatch):
    mod = _load_logger_impl(monkeypatch)
    payloads = _prime(mod, monkeypatch)
    mod.kb_listener = FakeListener(alive=True)
    mod._mark_listener_started("keyboard")
    monkeypatch.setattr(mod, "_queue_mouse_row", lambda _row: (_ for _ in ()).throw(ValueError("bad mouse")))

    mod.on_move(1, 2)
    mod._write_logger_heartbeat("ok")

    assert "bad mouse" in payloads[-1]["mouse_listener_error"]
    assert payloads[-1]["capture_status"] == "capture_degraded_mouse_listener_failed"


def test_protected_logger_exits_on_stop_marker(monkeypatch):
    mod = _load_logger_impl(monkeypatch)
    _prime(mod, monkeypatch)
    calls = {"count": 0}

    def should_stop(_name):
        calls["count"] += 1
        return calls["count"] >= 2

    monkeypatch.setattr(mod, "should_stop_logger", should_stop)
    mod.kb_listener = FakeListener(alive=True)
    mod.ms_listener = FakeListener(alive=True)
    mod._mark_listener_started("keyboard")
    mod._mark_listener_started("mouse")

    result = mod._supervised_capture_loop(poll_interval=0.01, heartbeat_interval=0.01, max_iterations=5)

    assert result == "control_stop"
    assert mod._current_stop_reason() == "control_stop"


def test_both_listeners_dead_causes_listener_failure(monkeypatch):
    mod = _load_logger_impl(monkeypatch)
    payloads = _prime(mod, monkeypatch)
    mod.kb_listener = FakeListener(alive=False)
    mod.ms_listener = FakeListener(alive=False)
    mod._mark_listener_started("keyboard")
    mod._mark_listener_started("mouse")

    result = mod._supervised_capture_loop(poll_interval=0.01, heartbeat_interval=0.01, max_iterations=5)

    assert result == "listener_failure"
    assert mod._current_stop_reason() == "listener_failure"
    assert payloads[-1]["capture_status"] == "capture_failed_all_listeners_dead"
    assert payloads[-1]["listener_exit_reason"]


def test_keyboard_zero_mouse_positive_is_degraded_not_failed(monkeypatch):
    mod = _load_logger_impl(monkeypatch)
    payloads = _prime(mod, monkeypatch)
    mod.kb_listener = FakeListener(alive=False)
    mod.ms_listener = FakeListener(alive=True)
    mod._mark_listener_started("keyboard")
    mod._mark_listener_started("mouse")
    mod._record_capture_event("mouse")

    mod._supervised_capture_loop(poll_interval=0.01, heartbeat_interval=0.01, max_iterations=2)

    assert payloads[-1]["keyboard_event_count"] == 0
    assert payloads[-1]["mouse_event_count"] == 1
    assert payloads[-1]["capture_status"] == "capture_degraded_keyboard_listener_failed"
    assert payloads[-1].get("logger_failed") is not True


def test_final_archive_includes_listener_health_fields():
    source = open("src/bioauth/input/logger_impl.py", encoding="utf-8").read()
    assert "**_listener_health_snapshot()" in source
    assert "listener_exit_reason" in source
    assert "archive_write_logger_final_heartbeat" in source
