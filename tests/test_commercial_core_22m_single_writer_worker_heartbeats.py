from __future__ import annotations

from pathlib import Path


def test_control_exposes_worker_heartbeat_files() -> None:
    source = Path("control.py").read_text(encoding="utf-8")
    assert "def write_worker_heartbeat" in source
    assert "def read_worker_heartbeat" in source
    assert "def clear_worker_heartbeat" in source
    assert "worker_heartbeats" in source


def test_logger_publishes_heartbeat_instead_of_session_state() -> None:
    source = Path("src/bioauth/input/logger_impl.py").read_text(encoding="utf-8")
    assert "Commercial-Core-22M makes the bridge the single writer" in source
    assert "write_logger_heartbeat_payload" in source
    assert "archive_write_logger_final_heartbeat" in source
    assert "logger_heartbeat_write_failed" in source


def test_monitor_publishes_runtime_heartbeat_instead_of_session_state() -> None:
    source = Path("monitor_core/common.py").read_text(encoding="utf-8")
    assert "monitor no longer writes session_state.json" in source
    assert "write_monitor_heartbeat_payload(state)" in source
    assert "write_runtime_summary_payload(state)" in source


def test_bridge_merges_worker_heartbeats_as_single_writer() -> None:
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "def merge_worker_heartbeats_into_state" in source
    assert "worker_heartbeat_single_writer" in source
    assert "monitor_start_wait_extended_by_worker_heartbeat" in Path("bridge/refresh_runtime_helpers.py").read_text(encoding="utf-8")
    assert "read_worker_heartbeat" in Path("bridge/shared.py").read_text(encoding="utf-8")


def test_active_state_uses_merged_worker_heartbeats() -> None:
    source = Path("bridge/session_mixin.py").read_text(encoding="utf-8")
    assert "merge_worker_heartbeats_into_state" in source


def test_protected_start_initializes_bridge_owned_state_and_clears_heartbeats() -> None:
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    assert 'clear_worker_heartbeat("logger")' in source
    assert 'clear_worker_heartbeat("monitor")' in source
    assert '"source": "bridge"' in source
    assert '"worker_heartbeat_single_writer": True' in source
