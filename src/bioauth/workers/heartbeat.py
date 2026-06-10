"""Worker heartbeat helpers for BioAuth.

This module wraps control.py's heartbeat functions with clear thresholds and
type contracts.  Workers write heartbeats; the bridge reads and validates them.

Heartbeat lifecycle:
  - Worker writes every CHECK_INTERVAL seconds (typically 8s).
  - Bridge reads on every refresh (1s active, 10s idle).
  - Fresh: age < HEARTBEAT_FRESH_SEC  → worker is alive and working.
  - Stale: age > HEARTBEAT_STALE_SEC  → worker is dead or frozen.
  - Missing: heartbeat file absent      → worker never started or was cleared.

A single missed write is not treated as death.  The worker must miss at least
(HEARTBEAT_STALE_SEC / CHECK_INTERVAL) consecutive writes before the bridge
considers it dead.  Default: 30s / 8s ≈ 4 missed writes.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional


# ── Threshold constants ───────────────────────────────────────────────────────

HEARTBEAT_FRESH_SEC: float = 15.0   # age <= this → definitely alive
HEARTBEAT_STALE_SEC: float = 30.0   # age >  this → treat as dead/frozen


# ── Lazy import of control.py helpers ────────────────────────────────────────

def _ctrl():
    import control
    return control


# ── Public API ────────────────────────────────────────────────────────────────

def read_heartbeat(kind: str) -> Dict[str, Any]:
    """Return the latest heartbeat payload for a worker kind, or {} if absent."""
    try:
        result = _ctrl().read_worker_heartbeat(kind, default={})
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def write_heartbeat(kind: str, data: Dict[str, Any]) -> bool:
    """Write an atomic heartbeat for a worker kind.  Returns True on success."""
    try:
        return bool(_ctrl().write_worker_heartbeat(kind, data))
    except Exception:
        return False


def clear_heartbeat(kind: Optional[str] = None) -> None:
    """Clear the heartbeat file for a worker kind (or all workers if kind is None)."""
    try:
        _ctrl().clear_worker_heartbeat(kind)
    except Exception:
        pass


def heartbeat_age_sec(heartbeat: Dict[str, Any]) -> float:
    """Return how many seconds ago the heartbeat was written.

    Returns 999999.0 if the heartbeat is missing or has no timestamp.
    """
    if not isinstance(heartbeat, dict) or not heartbeat:
        return 999999.0
    try:
        ts = float(
            heartbeat.get("heartbeat_at")
            or heartbeat.get("logger_heartbeat_at")
            or heartbeat.get("monitor_heartbeat_at")
            or 0.0
        )
        if ts <= 0:
            return 999999.0
        return max(0.0, time.time() - ts)
    except Exception:
        return 999999.0


def heartbeat_is_fresh(heartbeat: Dict[str, Any], *, max_age_sec: float = HEARTBEAT_FRESH_SEC) -> bool:
    """Return True when the heartbeat is recent enough to confirm the worker is alive."""
    return heartbeat_age_sec(heartbeat) <= max(0.0, float(max_age_sec))


def heartbeat_is_stale(heartbeat: Dict[str, Any], *, min_age_sec: float = HEARTBEAT_STALE_SEC) -> bool:
    """Return True when the heartbeat is old enough to conclude the worker is dead."""
    return heartbeat_age_sec(heartbeat) > max(0.0, float(min_age_sec))


def heartbeat_matches_session(
    heartbeat: Dict[str, Any],
    *,
    session_id: str = "",
    user_id: str = "",
) -> bool:
    """Return True if the heartbeat belongs to the expected session and user.

    Empty session_id or user_id skips that check (permissive match).
    """
    if not isinstance(heartbeat, dict) or not heartbeat:
        return False
    if session_id:
        hb_sid = str(heartbeat.get("session_id") or "").strip()
        if hb_sid and hb_sid != str(session_id).strip():
            return False
    if user_id:
        hb_uid = str(heartbeat.get("user_id") or heartbeat.get("expected_user") or "").strip()
        if hb_uid and hb_uid != str(user_id).strip():
            return False
    return True
