"""Flow-type boundary definitions for BioAuth session management.

Every session action belongs to exactly one flow type.  The type determines
what code can be called, what state can be written, and what UI sections are
affected.

Rules enforced here:
- USER flow: only calls user-tagged functions; never imports or calls demo/shadow/hybrid code.
- DEVELOPER flow: may call user flow functions; imports demo/hybrid; only active when
  uiMode == "developer" and explicit env vars are set.
- RESEARCH flow: shadow/algorithm kit code; never auto-starts; never affects user UI.
- TEST flow: test-only paths; must be completely absent from production builds.
"""
from __future__ import annotations

import os
from typing import Any


# ── Flow type constants ──────────────────────────────────────────────────────

FLOW_USER = "user"           # Real user product flow
FLOW_DEVELOPER = "developer" # Developer-only: demo classic, hybrid direct
FLOW_RESEARCH = "research"   # Research/shadow: shadow evidence monitor, algo kits
FLOW_TEST = "test"           # Test-only: never in production

_ALL_FLOWS = frozenset({FLOW_USER, FLOW_DEVELOPER, FLOW_RESEARCH, FLOW_TEST})


# ── Environment-based flow gate ───────────────────────────────────────────────

def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def developer_flow_allowed() -> bool:
    """Return True only when an explicit developer build profile is active.

    Production packages do NOT set these variables; developer mode is opt-in.
    """
    return (
        _env_flag("BIOAUTH_BUILD_PROFILE_DEV")
        or os.environ.get("BIOAUTH_BUILD_PROFILE", "").strip().lower() in {"dev", "debug"}
    )


def research_flow_allowed() -> bool:
    """Return True only when shadow/research features are explicitly enabled."""
    return _env_flag("BIOAUTH_ENABLE_SHADOW_EVIDENCE_MONITOR") or _env_flag("BIOAUTH_ENABLE_RESEARCH_FLOWS")


def demo_classic_flow_allowed() -> bool:
    """Return True only for an explicit Demo Classic runtime opt-in."""
    return _env_flag("BIOAUTH_DEMO_CLASSIC_PROTECTED")


# ── Bridge-state flow gate ────────────────────────────────────────────────────

def ui_is_user_mode(bridge: Any) -> bool:
    """Return True when the bridge is in user mode (real product interface)."""
    try:
        return str(getattr(bridge, "uiMode", "") or "").strip().lower() == "user"
    except Exception:
        return False


def ui_is_developer_mode(bridge: Any) -> bool:
    """Return True when the bridge is in developer mode."""
    try:
        return str(getattr(bridge, "uiMode", "") or "").strip().lower() == "developer"
    except Exception:
        return False


# ── Capability gates ──────────────────────────────────────────────────────────

def can_start_demo_classic(bridge: Any) -> bool:
    """Demo Classic start is only allowed in developer mode with the explicit env var."""
    return demo_classic_flow_allowed() and developer_flow_allowed()


def can_start_shadow_evidence_monitor(bridge: Any) -> bool:
    """Shadow evidence monitor is a research-only feature."""
    return research_flow_allowed()


def can_run_hybrid_direct_test(bridge: Any) -> bool:
    """Hybrid Direct test is developer-only."""
    return developer_flow_allowed() and _env_flag("BIOAUTH_HYBRID_TEST_ONLY")


# ── Cleanup reentry guard ─────────────────────────────────────────────────────

class CleanupReentryGuard:
    """Thread-safe one-shot guard preventing double-execution of cleanup logic.

    Usage::

        guard = CleanupReentryGuard()
        if not guard.enter():
            return  # already running, skip
        try:
            ... cleanup ...
        finally:
            guard.exit()

    After ``enter()`` returns True once, every subsequent call returns False until
    ``reset()`` is called.  This prevents the stop-protection path from running
    twice when app shutdown and manual Stop Protection fire concurrently.
    """

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()
        self._active = False

    def enter(self) -> bool:
        """Try to enter the guarded section.  Returns True iff this caller owns it."""
        with self._lock:
            if self._active:
                return False
            self._active = True
            return True

    def exit(self) -> None:
        with self._lock:
            self._active = False

    def reset(self) -> None:
        """Reset to allow a future cleanup run (e.g. after a new session starts)."""
        with self._lock:
            self._active = False

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._active


# ── Module-level reentry guards ───────────────────────────────────────────────
# One guard per bridge instance would be ideal, but since bridges are
# singletons in practice, module-level guards are safe and avoid __init__ coupling.

_shutdown_cleanup_guard = CleanupReentryGuard()
_stop_protection_guard = CleanupReentryGuard()


def get_shutdown_cleanup_guard() -> CleanupReentryGuard:
    return _shutdown_cleanup_guard


def get_stop_protection_guard() -> CleanupReentryGuard:
    return _stop_protection_guard
