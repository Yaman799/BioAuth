"""Session coordinator for the BioAuth user product flow.

This module is the authoritative coordinator for user-facing session lifecycle:
  - Enrollment session start / stop
  - Protected session start / stop
  - Session flow state query
  - Stale session recovery on startup

Design:
  Currently this module re-exports from bridge/session_runtime_helpers.py
  (the USER-tagged functions only).  Phase 3+ will move the implementations
  here so the bridge no longer owns session logic directly.

Import rules:
  - ONLY call functions tagged [FLOW: USER] or [FLOW: USER/LIFECYCLE].
  - Never import from hybrid_candidates, shadow_core, demo_classic, or
    evaluation_core from this module.
  - All callers of this module get the real user flow — no dev/research branches.

Compatibility:
  The bridge's session_mixin.py still calls session_runtime_helpers directly.
  That is acceptable for now.  Once Phase 3 extraction is complete, those
  calls will be redirected here.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

_LOG = logging.getLogger(__name__)


# ── Lazy import keeps startup fast and avoids circular deps ──────────────────

def _srh():
    from bridge import session_runtime_helpers
    return session_runtime_helpers


# ── Session flow queries ─────────────────────────────────────────────────────

def get_user_session_flow(bridge: Any, state: Optional[Dict[str, Any]] = None) -> str:
    """Canonical user-mode flow string — demo/shadow state is filtered out.

    Returns one of:
      "idle", "enrollment_starting", "enrollment_active",
      "protected_starting", "protected_collecting", "protected_active",
      "protected_warning", "protected_technical_failure",
      "protected_forced_stop", "protected_resume_pending"
    """
    return _srh()._normal_user_session_flow(bridge, state=state)


def is_enrollment_logger_running(bridge: Any) -> bool:
    return _srh()._normal_enrollment_logger_flow(bridge) == "enrollment_active"


def is_production_monitor_running(bridge: Any) -> bool:
    return _srh()._production_monitor_process_running(bridge)


def can_stop_production_monitor(bridge: Any) -> bool:
    return _srh()._protected_session_stop_available(bridge)


def is_logger_start_pending(bridge: Any) -> bool:
    return _srh()._normal_logger_start_pending(bridge)


# ── Enrollment session ───────────────────────────────────────────────────────

def start_enrollment_session(bridge: Any, *, passive: bool = False) -> bool:
    """Start a new enrollment session.

    Returns True if the session was accepted, False if blocked.
    Reasons for False: not authenticated, training in progress, another
    session is already active, consent not granted.
    """
    return _srh().start_enrollment(bridge, passive_auto_enrollment=passive)


def stop_enrollment_session(bridge: Any, *, silent: bool = False) -> bool:
    """Request stop for the active enrollment logger session.

    Returns True if a stop request was issued, False if no logger is running.
    """
    return _srh().stop_enrollment_logger(bridge, silent)


# ── Protected session ────────────────────────────────────────────────────────

def start_protection(bridge: Any, *, auto_resume: bool = False) -> bool:
    """Start a protected (production) session.

    Returns True if accepted, False if blocked.
    Common reasons for False: profile not production-ready, session already
    active, consent not granted, training in progress.
    """
    return _srh().start_protected_session(bridge, auto_resume=auto_resume, trigger_refresh=True)


def resume_protection_after_lock(bridge: Any) -> bool:
    """Resume a protected session after a Windows Lock / unlock cycle."""
    return _srh().start_protected_session(bridge, auto_resume=True, trigger_refresh=True)


def stop_protection(bridge: Any, *, silent: bool = False) -> None:
    """Stop the active protected session and finalize it."""
    _srh().stop_production_monitor(bridge, silent)


def stop_any_active_session(bridge: Any, *, silent: bool = False) -> None:
    """Stop whichever session is active (enrollment or protected)."""
    _srh().stop_current_session(bridge, silent)


# ── Shutdown lifecycle ───────────────────────────────────────────────────────

def shutdown_all_workers(bridge: Any, *, reason: str = "app_shutdown", wait_sec: float = 0.75) -> None:
    """Terminate all runtime workers on application exit.

    Safe to call from both Qt's aboutToQuit and commitDataRequest signals.
    The user_flow_boundary wrapper adds a module-level reentry guard.
    """
    from .user_flow_boundary import shutdown_runtime_workers
    shutdown_runtime_workers(bridge, reason=reason, wait_timeout=wait_sec)


# ── Stale session recovery ───────────────────────────────────────────────────

def recover_stale_session_on_startup(bridge: Any) -> bool:
    """Called once on app startup to clean up orphaned session state.

    Returns True if a stale state was detected and cleared.

    This handles the case where the user closed the app during an active
    protected session, leaving session_state.json with active=True but no
    running workers.
    """
    return _srh().recover_stale_protected_flow_without_workers(bridge)


# ── Worker process diagnostics ───────────────────────────────────────────────

def worker_diagnostics(bridge: Any, key: str) -> Dict[str, Any]:
    """Return a snapshot of stdout/stderr tail for a worker process."""
    return _srh().worker_diagnostics_snapshot(bridge, key)
