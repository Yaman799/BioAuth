from __future__ import annotations

from pathlib import Path


def test_terminal_stopped_state_is_heartbeat_barrier() -> None:
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "def _is_terminal_protected_state" in source
    assert "terminal/stopped protected state is authoritative" in source
    assert "Stale worker heartbeat files" in source
    assert "return merged" in source


def test_stop_finalization_clears_worker_heartbeats_around_terminal_write() -> None:
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    start = source.index("def finalize_protected_session_stop")
    end = source.index("def _clear_runtime_after_terminal_stop", start)
    block = source[start:end]
    assert "stop finalization is the hard boundary" in block
    assert block.count('facade.clear_worker_heartbeat("logger")') >= 2
    assert block.count('facade.clear_worker_heartbeat("monitor")') >= 2
    assert block.index('facade.clear_worker_heartbeat("logger")') < block.index("facade.write_session_state(terminal_state)")


def test_stale_protected_flow_without_workers_recovery_exists_and_is_used() -> None:
    helpers = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    mixin = Path("bridge/session_mixin.py").read_text(encoding="utf-8")
    assert "def recover_stale_protected_flow_without_workers" in helpers
    assert "stale_protected_flow_recovered" in helpers
    assert "_PROTECTED_STALE_FLOW_RECOVERY_HEARTBEAT_GRACE_SEC" in helpers
    assert "recover_stale_protected_flow_without_workers" in mixin
    assert "stale_protected_flow_without_workers_read" in mixin


def test_session_flow_treats_terminal_protected_state_as_idle() -> None:
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    session_flow_start = source.index("def session_flow")
    session_flow_end = source.index("def maybe_autostart_protection", session_flow_start)
    session_flow = source[session_flow_start:session_flow_end]
    normal_start = source.index("def _normal_user_session_flow")
    normal_end = source.index("def _normal_enrollment_logger_flow", normal_start)
    normal_flow = source[normal_start:normal_end]
    assert 'if _is_terminal_protected_state(state):\n        return "idle"' in session_flow
    assert 'if _is_terminal_protected_state(state):\n        return "idle"' in normal_flow
