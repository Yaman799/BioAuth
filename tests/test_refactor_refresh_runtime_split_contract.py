from __future__ import annotations

import inspect

from bridge import refresh_runtime_helpers as helpers


def test_refresh_perform_remains_display_oriented() -> None:
    source = inspect.getsource(helpers._perform_refresh_now)
    forbidden = (
        "_maybe_finish_pending_logger_start(",
        "_maybe_finish_pending_monitor_start(",
        "check_worker_pair_liveness(",
        "_cleanup_processes(",
        "_start_process(",
        "request_stop(",
        "recover_stale_protected_flow_without_workers(",
        "stop_current_session(",
    )
    for token in forbidden:
        assert token not in source


def test_refresh_timer_dispatch_uses_qt_dispatcher_marker() -> None:
    source = inspect.getsource(helpers.update_refresh_timer)
    assert "dispatch_to_qt_thread" in source or "QTimer" in source
