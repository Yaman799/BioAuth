from __future__ import annotations

from pathlib import Path


def test_monitor_exit_after_ready_stops_logger_pair() -> None:
    source = Path("bridge/session_mixin.py").read_text(encoding="utf-8")
    assert "Monitor exited after protected readiness; stopped logger pair" in source
    assert "logger_stop_after_monitor_exit" in source
    assert "logger_stopped_because_monitor_failed" in source
    assert "monitor_exited_logger_stopped" in source
    assert "request_stop(logger_key)" in source
    assert "_terminate_process_key(" in source
    assert '"active": False' in source
    assert '"monitor_exit_stage": "after_ready"' in source


def test_logger_heartbeat_does_not_overwrite_monitor_failure() -> None:
    source = Path("src/bioauth/input/logger_impl.py").read_text(encoding="utf-8")
    assert "monitor_failed_pair_stop" in source
    assert "once the bridge marks protected monitoring as" in source
    assert '"logger_stopped_because_monitor_failed": True' in source
    assert '"logger_exit_reason": "monitor_failed_pair_stop"' in source
    assert "return" in source


def test_technical_failure_precedence_over_stale_ok_runtime_status() -> None:
    source = Path("bridge/refresh_dashboard_helpers.py").read_text(encoding="utf-8")
    assert 'flow == "protected_technical_failure"' in source
    assert 'diag_status = str(state.get("runtime_diagnostic_code")' in source
    assert 'raw_status = "monitor_exited_after_ready"' in source
    assert '"processPairState"' in source
    assert '"loggerStoppedBecauseMonitorFailed"' in source
    assert '"monitorExitStage"' in source
