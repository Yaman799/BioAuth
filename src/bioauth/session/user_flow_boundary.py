"""User-flow boundary for BioAuth session management.

This module is the ONLY entry point for real-user-product session actions.
It wraps the underlying helpers and enforces that:
  - Developer (demo/hybrid) code paths are never invoked through here.
  - Shadow/research code paths are never invoked through here.
  - The caller does not need to know about developer/shadow internals.

Compatibility: All underlying implementations still live in
bridge/session_runtime_helpers.py and are re-exported here without modification.
This wrapper will gradually own the implementations as Phase 3 extraction proceeds.

Flow classification of the underlying functions called here:
  start_enrollment()          → USER
  start_protected_session()   → USER (demo_classic check is internally gated)
  stop_current_session()      → USER
  stop_production_monitor()   → USER
  shutdown_runtime_workers()  → USER (lifecycle)
  recover_stale_protected_flow_without_workers() → USER (recovery)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ._flow_types import (
    get_stop_protection_guard,
    get_shutdown_cleanup_guard,
)

_LOG = logging.getLogger(__name__)


# ── Lazy import of the underlying implementations ─────────────────────────────

def _srh():
    """Lazy reference to session_runtime_helpers to avoid circular imports at startup."""
    from bridge import session_runtime_helpers
    return session_runtime_helpers


# ── User-flow session state queries ──────────────────────────────────────────

def user_session_flow(bridge: Any, state: Optional[Dict[str, Any]] = None) -> str:
    """Current user session flow string — shadows/demo filtered out."""
    return _srh()._normal_user_session_flow(bridge, state=state)


def enrollment_logger_flow(bridge: Any, state: Optional[Dict[str, Any]] = None) -> str:
    return _srh()._normal_enrollment_logger_flow(bridge, state=state)


def enrollment_logger_stop_available(bridge: Any, state: Optional[Dict[str, Any]] = None) -> bool:
    return _srh()._normal_enrollment_logger_stop_available(bridge, state=state)


def production_monitor_running(bridge: Any) -> bool:
    return _srh()._production_monitor_process_running(bridge)


def production_monitor_stop_available(bridge: Any) -> bool:
    return _srh()._protected_session_stop_available(bridge)


def normal_logger_start_pending(bridge: Any) -> bool:
    return _srh()._normal_logger_start_pending(bridge)


# ── User-flow start actions ───────────────────────────────────────────────────

def start_enrollment(bridge: Any, *, passive_auto_enrollment: bool = False) -> bool:
    """Start an enrollment session for the real user product flow."""
    return _srh().start_enrollment(bridge, passive_auto_enrollment=passive_auto_enrollment)


def start_protected_session(bridge: Any, *, auto_resume: bool = False, trigger_refresh: bool = True) -> bool:
    """Start a protected (production) monitor session for the real user flow.

    Internally calls start_protected_session() from session_runtime_helpers.py.
    The demo-classic check inside is properly gated behind env var; it does not
    activate in a normal commercial build.
    """
    return _srh().start_protected_session(bridge, auto_resume=auto_resume, trigger_refresh=trigger_refresh)


# ── User-flow stop actions ────────────────────────────────────────────────────

def stop_current_session(bridge: Any, silent: bool = False) -> None:
    """Stop the current session (enrollment or protected) safely.

    Guarded by the stop-protection reentry guard.
    """
    guard = get_stop_protection_guard()
    if not guard.enter():
        _LOG.debug("stop_current_session: reentry blocked — already stopping")
        return
    try:
        _srh().stop_current_session(bridge, silent)
    except Exception:
        _LOG.warning("stop_current_session: error during stop", exc_info=True)
    finally:
        guard.exit()


def stop_production_monitor(bridge: Any, silent: bool = False) -> None:
    """Stop and finalize the production monitor session."""
    _srh().stop_production_monitor(bridge, silent)


def shutdown_runtime_workers(bridge: Any, *, reason: str = "app_shutdown", wait_timeout: float = 0.75) -> None:
    """Shut down all runtime workers on app exit.

    Guarded by the shutdown cleanup guard — safe to call from both
    aboutToQuit and commitDataRequest without double-cleanup.
    """
    guard = get_shutdown_cleanup_guard()
    if not guard.enter():
        _LOG.debug("shutdown_runtime_workers: reentry blocked — already shutting down")
        return
    try:
        _srh().shutdown_runtime_workers(bridge, reason=reason, wait_timeout=wait_timeout)
    except Exception:
        _LOG.warning("shutdown_runtime_workers: error during shutdown", exc_info=True)
    finally:
        guard.exit()


# ── User-flow stale recovery ──────────────────────────────────────────────────

def recover_stale_protected_flow(bridge: Any, state: Optional[Dict[str, Any]] = None) -> bool:
    """Recover a stale protected flow left by closing the app during protection."""
    return _srh().recover_stale_protected_flow_without_workers(bridge, state)


def can_run_hybrid_direct_test(bridge: Any) -> bool:
    """Hybrid Direct is developer-only; this gate is always false in user mode."""
    return _srh().can_run_hybrid_direct_test(bridge)


def hybrid_direct_test_blockers(bridge: Any) -> list:
    return _srh().hybrid_direct_test_blockers(bridge)
