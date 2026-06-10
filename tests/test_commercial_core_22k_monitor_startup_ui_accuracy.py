from __future__ import annotations

from pathlib import Path


def test_monitor_startup_failure_preserves_monitor_exit_reason() -> None:
    source = Path("bridge/refresh_runtime_helpers.py").read_text(encoding="utf-8")
    assert "_monitor_start_exit_reason_from_state" in source
    assert '"session_inactive": "monitor_start_session_inactive"' in source
    assert '"session_id_mismatch": "monitor_start_session_id_mismatch"' in source
    assert '"stop_requested": "monitor_start_stop_requested"' in source
    assert '"monitor_start_exit_reason"' in source
    assert '"monitor_start_state_status"' in source
    assert '"status": reason if str(reason).startswith("monitor_start_")' in source


def test_monitor_startup_statuses_are_runtime_technical_failures() -> None:
    labels = Path("bridge/runtime_labels.py").read_text(encoding="utf-8")
    for status in [
        "monitor_process_lost",
        "monitor_start_session_inactive",
        "monitor_start_session_id_mismatch",
        "monitor_start_stop_requested",
        "monitor_start_runtime_exception",
        "monitor_start_stale_lock_recovered",
    ]:
        assert status in labels
    assert 'runtime_detail_monitor_start_session_inactive' in labels
    assert 'runtime_detail_monitor_process_lost' in labels


def test_user_home_does_not_show_running_on_technical_failure() -> None:
    qml = Path("qml/pages/user/UserHomePage.qml").read_text(encoding="utf-8")
    assert "homeProtectionFailure" in qml
    assert "homeProtectionRunning" in qml
    assert 'return root.label("فشل المراقب", "Monitor failed")' in qml
    assert 'return root.label("الحماية تعمل", "Protection running")' in qml
    assert "if (root.homeProtectionFailure)" in qml
    assert "if (root.homeProtectionRunning)" in qml


def test_debug_runtime_state_exposes_monitor_startup_exit_fields() -> None:
    dashboard = Path("bridge/refresh_dashboard_helpers.py").read_text(encoding="utf-8")
    assert '"monitorStartExitReason"' in dashboard
    assert '"monitorExitReason"' in dashboard
    assert '"monitorExitDetail"' in dashboard
    assert '"monitorStartStateStatus"' in dashboard
    assert '"monitorStartStateSessionId"' in dashboard


def test_i18n_has_specific_monitor_startup_messages() -> None:
    i18n = Path("bridge/i18n.py").read_text(encoding="utf-8")
    assert "runtime_detail_monitor_start_session_inactive" in i18n
    assert "runtime_detail_monitor_start_session_id_mismatch" in i18n
    assert "runtime_detail_monitor_start_stop_requested" in i18n
    assert "runtime_detail_monitor_process_lost" in i18n
