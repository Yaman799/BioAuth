"""BioAuth worker lifecycle package.

Provides:
  - heartbeat: read/write/validate worker heartbeats
  - supervision: process-pair liveness checks, stale detection
"""
from .heartbeat import (
    read_heartbeat,
    write_heartbeat,
    clear_heartbeat,
    heartbeat_age_sec,
    heartbeat_is_fresh,
    heartbeat_is_stale,
    HEARTBEAT_FRESH_SEC,
    HEARTBEAT_STALE_SEC,
)
from .supervision import (
    WorkerPair,
    worker_pair_status,
    both_workers_alive,
    either_worker_alive,
    logger_alive,
    monitor_alive,
)

__all__ = [
    "read_heartbeat",
    "write_heartbeat",
    "clear_heartbeat",
    "heartbeat_age_sec",
    "heartbeat_is_fresh",
    "heartbeat_is_stale",
    "HEARTBEAT_FRESH_SEC",
    "HEARTBEAT_STALE_SEC",
    "WorkerPair",
    "worker_pair_status",
    "both_workers_alive",
    "either_worker_alive",
    "logger_alive",
    "monitor_alive",
]
