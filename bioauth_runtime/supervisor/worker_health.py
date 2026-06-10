"""Pure worker-pair health classification for commercial runtime supervision."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class WorkerHealthResult:
    state: str
    recommended_action: str
    details: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        payload = dict(self.details)
        payload.update({"state": self.state, "recommended_action": self.recommended_action})
        return payload


def classify_worker_pair(bridge: Any, state: Optional[Dict[str, Any]] = None) -> WorkerHealthResult:
    """Classify logger/monitor health without starting or stopping anything."""
    data = state if isinstance(state, dict) else {}
    if str(data.get("session_kind") or "").lower() != "protected":
        return WorkerHealthResult("stale", "ignore", {"reason": "not_protected"})
    try:
        from bioauth.workers.supervision import worker_pair_status

        logger_key = bridge._logger_process_key()
        status = worker_pair_status(
            bridge,
            logger_key=logger_key,
            monitor_key="monitor",
            session_id=str(data.get("session_id") or ""),
            user_id=str(data.get("user_id") or data.get("expected_user") or ""),
            now=time.time(),
        )
    except Exception as exc:
        return WorkerHealthResult("stale", "observe", {"reason": "classification_failed", "error": str(exc)})
    action = str(status.get("recommended_action") or "ok")
    if action == "ok":
        state_name = "healthy"
    elif action == "wait":
        state_name = "starting" if bool(data.get("pending_monitor_start")) else "degraded"
    elif action == "recover":
        state_name = "dead" if bool(status.get("pair_dead")) else "stale"
    elif action == "fail":
        state_name = "frozen" if _has_frozen_heartbeat(status) else "degraded"
    else:
        state_name = "stale"
    return WorkerHealthResult(state_name, action, dict(status))


def _has_frozen_heartbeat(status: Dict[str, Any]) -> bool:
    logger_age = float(status.get("logger_heartbeat_age_sec") or 999999.0)
    monitor_age = float(status.get("monitor_heartbeat_age_sec") or 999999.0)
    return bool(status.get("logger_process_alive") and logger_age > 30.0) or bool(
        status.get("monitor_process_alive") and monitor_age > 30.0
    )
