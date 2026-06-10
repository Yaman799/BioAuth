"""Worker process-pair supervision for BioAuth protected sessions.

In a protected session, logger and monitor run as a pair:
  - Logger  captures keyboard/mouse and archives the session.
  - Monitor reads the live session and makes risk decisions.

Both must be alive for protection to work.  If either dies unexpectedly,
the UI must transition to a technical failure state, not stay stuck in
"protected_active" with an empty process list.

This module provides:
  - WorkerPair: named holder for process handles
  - worker_pair_status(): structured liveness report
  - both_workers_alive() / either_worker_alive(): fast guards

Rules enforced here:
  1. Logger-only with no monitor → technical failure, not "protected_active".
  2. Monitor-only with no logger → technical failure (no new data).
  3. Neither alive but session_state active → stale, trigger recovery.
  4. Supervision must never start or stop workers itself — that belongs to
     the session coordinator.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .heartbeat import (
    heartbeat_age_sec,
    heartbeat_is_fresh,
    heartbeat_is_stale,
    heartbeat_matches_session,
    read_heartbeat,
    HEARTBEAT_FRESH_SEC,
    HEARTBEAT_STALE_SEC,
)


# ── WorkerPair ────────────────────────────────────────────────────────────────

@dataclass
class WorkerPair:
    """Holds Popen handles for the logger + monitor pair of one protected session."""
    logger_key: str = ""
    monitor_key: str = ""
    session_id: str = ""
    user_id: str = ""

    def logger_process(self, bridge: Any) -> Optional[Any]:
        procs = getattr(bridge, "_running_processes", {}) or {}
        return procs.get(self.logger_key)

    def monitor_process(self, bridge: Any) -> Optional[Any]:
        procs = getattr(bridge, "_running_processes", {}) or {}
        return procs.get(self.monitor_key)

    def logger_alive(self, bridge: Any) -> bool:
        proc = self.logger_process(bridge)
        try:
            return proc is not None and proc.poll() is None
        except Exception:
            return False

    def monitor_alive(self, bridge: Any) -> bool:
        proc = self.monitor_process(bridge)
        try:
            return proc is not None and proc.poll() is None
        except Exception:
            return False


# ── Generic process liveness (no pair context needed) ────────────────────────

def _process_alive(proc: Any) -> bool:
    try:
        return proc is not None and proc.poll() is None
    except Exception:
        return False


def logger_alive(bridge: Any, logger_key: str) -> bool:
    """Return True if the logger process is still running."""
    procs = getattr(bridge, "_running_processes", {}) or {}
    return _process_alive(procs.get(logger_key))


def monitor_alive(bridge: Any, monitor_key: str) -> bool:
    """Return True if the monitor process is still running."""
    procs = getattr(bridge, "_running_processes", {}) or {}
    return _process_alive(procs.get(monitor_key))


def both_workers_alive(bridge: Any, logger_key: str, monitor_key: str) -> bool:
    return logger_alive(bridge, logger_key) and monitor_alive(bridge, monitor_key)


def either_worker_alive(bridge: Any, logger_key: str, monitor_key: str) -> bool:
    return logger_alive(bridge, logger_key) or monitor_alive(bridge, monitor_key)


# ── Full liveness report ──────────────────────────────────────────────────────

def worker_pair_status(
    bridge: Any,
    *,
    logger_key: str,
    monitor_key: str,
    session_id: str = "",
    user_id: str = "",
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Return a structured liveness report for a worker pair.

    Used by the bridge refresh loop to decide whether to transition to a
    technical failure state.  Does NOT modify any state itself.

    Returns::

        {
            "logger_process_alive": bool,
            "monitor_process_alive": bool,
            "logger_heartbeat_fresh": bool,
            "monitor_heartbeat_fresh": bool,
            "logger_heartbeat_age_sec": float,
            "monitor_heartbeat_age_sec": float,
            "logger_heartbeat_matches": bool,
            "monitor_heartbeat_matches": bool,
            "pair_healthy": bool,        # both alive + fresh heartbeat
            "pair_degraded": bool,       # one alive, other not
            "pair_dead": bool,           # both process-dead + both HB stale
            "pair_stale": bool,          # no process + no fresh HB
            "recommended_action": str,   # "ok" | "wait" | "recover" | "fail"
        }
    """
    current = float(now or time.time())

    l_proc_alive = logger_alive(bridge, logger_key)
    m_proc_alive = monitor_alive(bridge, monitor_key)

    l_hb = read_heartbeat(logger_key)
    m_hb = read_heartbeat(monitor_key)

    l_hb_age = heartbeat_age_sec(l_hb)
    m_hb_age = heartbeat_age_sec(m_hb)
    l_hb_fresh = heartbeat_is_fresh(l_hb)
    m_hb_fresh = heartbeat_is_fresh(m_hb)
    l_hb_stale = heartbeat_is_stale(l_hb)
    m_hb_stale = heartbeat_is_stale(m_hb)
    l_hb_match = heartbeat_matches_session(l_hb, session_id=session_id, user_id=user_id)
    m_hb_match = heartbeat_matches_session(m_hb, session_id=session_id, user_id=user_id)

    # Effective liveness: process is alive OR a fresh matching heartbeat exists
    l_effective = l_proc_alive or (l_hb_fresh and l_hb_match)
    m_effective = m_proc_alive or (m_hb_fresh and m_hb_match)

    pair_healthy = l_effective and m_effective
    pair_degraded = l_effective != m_effective  # one side alive, other dead
    pair_dead = not l_effective and not m_effective and l_hb_stale and m_hb_stale
    pair_stale = not l_proc_alive and not m_proc_alive and not l_hb_fresh and not m_hb_fresh

    if pair_healthy:
        action = "ok"
    elif pair_degraded and (l_hb_age < HEARTBEAT_STALE_SEC or m_hb_age < HEARTBEAT_STALE_SEC):
        action = "wait"     # one side recently died — give it one more cycle
    elif pair_dead or pair_stale:
        action = "recover"  # both gone — trigger stale flow recovery
    else:
        action = "fail"     # partial liveness, old heartbeats — technical failure

    return {
        "logger_process_alive": l_proc_alive,
        "monitor_process_alive": m_proc_alive,
        "logger_heartbeat_fresh": l_hb_fresh,
        "monitor_heartbeat_fresh": m_hb_fresh,
        "logger_heartbeat_age_sec": round(l_hb_age, 1),
        "monitor_heartbeat_age_sec": round(m_hb_age, 1),
        "logger_heartbeat_matches": l_hb_match,
        "monitor_heartbeat_matches": m_hb_match,
        "logger_effective_alive": l_effective,
        "monitor_effective_alive": m_effective,
        "pair_healthy": pair_healthy,
        "pair_degraded": pair_degraded,
        "pair_dead": pair_dead,
        "pair_stale": pair_stale,
        "recommended_action": action,
    }
