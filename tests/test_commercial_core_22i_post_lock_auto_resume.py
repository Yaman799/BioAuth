from __future__ import annotations

from pathlib import Path


def test_intruder_lock_state_is_inactive_resume_pending() -> None:
    source = Path("bioauth_runtime/monitor_worker/lock_controller.py").read_text(encoding="utf-8")
    assert '"active": False' in source
    assert '"status": "resume_pending"' in source
    assert '"auto_resume_pending": True' in source
    assert '"resume_after_unlock": True' in source
    assert '"forced_stop_expected_monitor_exit": True' in source


def test_monitor_hold_does_not_block_inactive_resume_pending_state() -> None:
    source = Path("monitor_core/common.py").read_text(encoding="utf-8")
    assert "Resume-pending forced-stop states are intentionally inactive" in source
    assert 'if not bool(state.get("active", True)):' in source


def test_session_mixin_classifies_forced_stop_monitor_exit_as_expected() -> None:
    source = Path("bridge/session_mixin.py").read_text(encoding="utf-8")
    assert "def _expected_monitor_exit_after_forced_stop" in source
    assert "monitor_exited_after_forced_stop" in source
    assert '"technical_failure": False' in source
    assert '"risk_engine_stopped": False' in source
    assert '"auto_resume_pending": True' in source
    assert "self._expected_monitor_exit_after_forced_stop(state, diagnostics)" in source


def test_resume_pending_flow_precedes_forced_stop_flow() -> None:
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    resume_idx = source.index('if resume_pending and not state.get("active")')
    forced_idx = source.index('if forced_stop:\n        return "protected_forced_stop"')
    assert resume_idx < forced_idx
