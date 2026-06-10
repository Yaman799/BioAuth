"""BioAuth session boundary package.

Public API — import from here for user-flow session management:

    from bioauth.session import (
        get_user_session_flow,
        start_enrollment_session,
        stop_enrollment_session,
        start_protection,
        stop_protection,
        stop_any_active_session,
        resume_protection_after_lock,
        shutdown_all_workers,
        recover_stale_session_on_startup,
    )

Flow gate utilities:

    from bioauth.session import developer_flow_allowed, research_flow_allowed

Reentry guards:

    from bioauth.session import get_stop_protection_guard, get_shutdown_cleanup_guard
"""
from .coordinator import (
    get_user_session_flow,
    is_enrollment_logger_running,
    is_production_monitor_running,
    can_stop_production_monitor,
    is_logger_start_pending,
    start_enrollment_session,
    stop_enrollment_session,
    start_protection,
    stop_protection,
    stop_any_active_session,
    resume_protection_after_lock,
    shutdown_all_workers,
    recover_stale_session_on_startup,
    worker_diagnostics,
)
from ._flow_types import (
    FLOW_USER,
    FLOW_DEVELOPER,
    FLOW_RESEARCH,
    FLOW_TEST,
    developer_flow_allowed,
    research_flow_allowed,
    demo_classic_flow_allowed,
    can_start_demo_classic,
    can_start_shadow_evidence_monitor,
    can_run_hybrid_direct_test,
    get_stop_protection_guard,
    get_shutdown_cleanup_guard,
    CleanupReentryGuard,
)

__all__ = [
    # Coordinator
    "get_user_session_flow",
    "is_enrollment_logger_running",
    "is_production_monitor_running",
    "can_stop_production_monitor",
    "is_logger_start_pending",
    "start_enrollment_session",
    "stop_enrollment_session",
    "start_protection",
    "stop_protection",
    "stop_any_active_session",
    "resume_protection_after_lock",
    "shutdown_all_workers",
    "recover_stale_session_on_startup",
    "worker_diagnostics",
    # Flow gates
    "FLOW_USER",
    "FLOW_DEVELOPER",
    "FLOW_RESEARCH",
    "FLOW_TEST",
    "developer_flow_allowed",
    "research_flow_allowed",
    "demo_classic_flow_allowed",
    "can_start_demo_classic",
    "can_start_shadow_evidence_monitor",
    "can_run_hybrid_direct_test",
    "get_stop_protection_guard",
    "get_shutdown_cleanup_guard",
    "CleanupReentryGuard",
]
