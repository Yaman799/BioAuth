from __future__ import annotations

import importlib


def test_legacy_and_split_modules_import() -> None:
    modules = [
        "bridge.session_runtime_helpers",
        "bridge.refresh_runtime_helpers",
        "bridge.refresh_dashboard_helpers",
        "monitor_core.common",
        "bioauth.input.logger_impl",
        "bioauth.runtime.monitor_impl",
        "bioauth.app.desktop_app_impl",
        "bridge.session_runtime_split.worker_heartbeat_merge",
        "bridge.refresh_runtime_split.pending_monitor_start",
        "bridge.dashboard_refresh_split.runtime_state_view",
        "monitor_core.common_split.monitor_state_writer",
        "bioauth.input.logger_impl_split.logger_archive_finalizer",
        "bioauth.runtime.monitor_impl_split.monitor_diagnostics",
        "bioauth.app.desktop_app_split.desktop_startup_diagnostics",
    ]

    for name in modules:
        importlib.import_module(name)


def test_legacy_public_names_remain_callable() -> None:
    session = importlib.import_module("bridge.session_runtime_helpers")
    refresh = importlib.import_module("bridge.refresh_runtime_helpers")
    dashboard = importlib.import_module("bridge.refresh_dashboard_helpers")
    common = importlib.import_module("monitor_core.common")
    logger = importlib.import_module("bioauth.input.logger_impl")
    monitor = importlib.import_module("bioauth.runtime.monitor_impl")
    desktop = importlib.import_module("bioauth.app.desktop_app_impl")

    for owner, name in [
        (session, "merge_worker_heartbeats_into_state"),
        (session, "start_process"),
        (session, "start_protected_session"),
        (session, "stop_production_monitor"),
        (session, "maybe_resume_protection_after_unlock"),
        (refresh, "_perform_refresh_now"),
        (dashboard, "build_runtime_state_view"),
        (common, "_write_monitor_state"),
        (logger, "run_logger"),
        (monitor, "monitor"),
        (desktop, "main"),
    ]:
        assert callable(getattr(owner, name))
    assert hasattr(desktop, "AppBridge")
