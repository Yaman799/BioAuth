from __future__ import annotations

from pathlib import Path


def test_session_mixin_reexports_worker_heartbeat_helpers_for_facade() -> None:
    source = Path("bridge/session_mixin.py").read_text(encoding="utf-8")
    assert "read_worker_heartbeat" in source
    assert "clear_worker_heartbeat" in source
    assert "write_worker_heartbeat" in source


def test_heartbeat_merge_can_read_through_session_mixin_facade() -> None:
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "facade.read_worker_heartbeat" in source
    session_mixin = Path("bridge/session_mixin.py").read_text(encoding="utf-8")
    assert "read_worker_heartbeat," in session_mixin


def _protected_start_source() -> str:
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    start = source.index("def start_protected_session")
    end = source.index("def stop_enrollment_logger", start)
    return source[start:end]


def test_protected_start_writes_bridge_initial_state_before_logger_spawn() -> None:
    source = _protected_start_source()
    initial_marker = "bridge_initial_protected_state_written"
    spawn_marker = "started = self._start_process(\n        self._logger_process_key(),"
    assert initial_marker in source
    assert source.index(initial_marker) < source.index(spawn_marker)
    assert '"worker_heartbeat_waiting_for": "logger"' in source


def test_protected_start_clears_stale_worker_heartbeats_before_new_session() -> None:
    source = _protected_start_source()
    clear_state = "if not facade.clear_session_state():"
    clear_logger = 'facade.clear_worker_heartbeat("logger")'
    clear_monitor = 'facade.clear_worker_heartbeat("monitor")'
    new_session = "self._pending_logger_session_id = facade.uuid.uuid4().hex"
    assert clear_logger in source
    assert clear_monitor in source
    assert source.index(clear_state) < source.index(clear_logger) < source.index(new_session)
