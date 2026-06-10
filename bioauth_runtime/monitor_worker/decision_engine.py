"""Authoritative runtime decision payload construction."""
from __future__ import annotations

from typing import Any, Mapping

REQUIRED_DECISION_FIELDS = (
    "raw_model_risk",
    "observed_model_risk",
    "action_risk",
    "display_risk",
    "decision_risk",
    "risk_level",
    "runtime_status",
    "runtime_decision",
    "risk_actionability",
    "evidence_state",
    "input_pipeline_status",
    "current_quality_window_reason",
    "fresh_window",
    "runtime_prediction_ready",
    "high_risk_evidence",
    "face_required",
    "final_action",
    "lock_reason",
)


def build_runtime_decision_payload(state: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return one normalized monitor-owned decision payload."""
    src = dict(state or {})
    risk = _first_number(src, "decision_risk", "action_risk", "display_risk", "risk", "avg_risk")
    raw = _first_number(src, "raw_model_risk", "raw", "model_risk", default=risk)
    observed = _first_number(src, "observed_model_risk", "observed_risk", "risk", default=raw)
    action = _first_number(src, "action_risk", default=observed)
    display = _first_number(src, "display_risk", default=action)
    decision = _first_number(src, "decision_risk", default=action)
    valid_window = _valid_evaluated_window(src, decision)
    runtime_decision = _runtime_decision(src, valid_window=valid_window)
    fresh = bool(src.get("fresh_window", src.get("runtime_prediction_ready", valid_window)))
    ready = bool(src.get("runtime_prediction_ready", valid_window))
    high = bool(src.get("high_risk_evidence", decision is not None and float(decision) >= 75.0))
    input_status = _input_pipeline_status(src, valid_window=valid_window)
    return {
        "raw_model_risk": raw,
        "observed_model_risk": observed,
        "action_risk": action,
        "display_risk": display,
        "decision_risk": decision,
        "risk_level": _runtime_risk_level(src, decision),
        "runtime_status": _runtime_status(src, valid_window=valid_window),
        "runtime_decision": runtime_decision,
        "risk_actionability": str(src.get("risk_actionability") or _actionability(ready, fresh)),
        "evidence_state": str(src.get("evidence_state") or input_status),
        "input_pipeline_status": input_status,
        "current_quality_window_reason": str(src.get("current_quality_window_reason") or ""),
        "fresh_window": fresh,
        "runtime_prediction_ready": ready,
        "high_risk_evidence": high,
        "face_required": bool(src.get("face_required", high and ready and fresh)),
        "final_action": str(src.get("final_action") or ""),
        "lock_reason": str(src.get("lock_reason") or src.get("lockReason") or ""),
    }


def merge_runtime_decision_payload(state: Mapping[str, Any] | None) -> dict[str, Any]:
    """Overlay normalized monitor decision fields onto a state copy."""
    merged = dict(state or {})
    merged.update(build_runtime_decision_payload(merged))
    return merged


def _first_number(src: Mapping[str, Any], *keys: str, default: Any = None) -> float | None:
    for key in keys:
        value = src.get(key)
        if value is None or value == "":
            continue
        try:
            return round(float(value), 3)
        except (TypeError, ValueError):
            continue
    if default is None or default == "":
        return None
    try:
        return round(float(default), 3)
    except (TypeError, ValueError):
        return None


def _risk_level(risk: float | None) -> str:
    if risk is None:
        return "unknown"
    if risk >= 75.0:
        return "high"
    if risk >= 45.0:
        return "medium"
    return "low"


def _runtime_risk_level(src: Mapping[str, Any], risk: float | None) -> str:
    existing = str(src.get("risk_level") or "").strip().lower()
    if existing and existing != "unknown":
        return existing
    return _risk_level(risk)


def _input_pipeline_status(src: Mapping[str, Any], *, valid_window: bool) -> str:
    existing = str(src.get("input_pipeline_status") or src.get("current_input_state") or "").strip().lower()
    if valid_window and existing in {"", "pending", "collecting", "collecting_evidence"}:
        return "evaluated_window"
    return existing or ("evaluated_window" if valid_window else "pending")


def _runtime_decision(src: Mapping[str, Any], *, valid_window: bool) -> str:
    existing = str(src.get("runtime_decision") or "").strip().lower()
    decision = str(src.get("decision") or src.get("final_decision") or "").strip().lower()
    if valid_window and decision and decision not in {"pending", "monitoring", "starting", "idle", "inactive", "stopped"}:
        return decision
    return existing or decision or "pending"


def _runtime_status(src: Mapping[str, Any], *, valid_window: bool) -> str:
    existing = str(src.get("runtime_status") or "").strip().lower()
    status = str(src.get("status") or "").strip().lower()
    if valid_window and status and status not in _NON_ACTIONABLE_STATUSES:
        return status
    return existing or status or "pending"


_NON_ACTIONABLE_STATUSES = {
    "",
    "pending",
    "collecting",
    "collecting_evidence",
    "insufficient_evidence",
    "insufficient_windows",
    "insufficient_events",
    "transitioning",
    "verifying_return",
    "resume_pending",
    "preserved_idle",
    "idle",
    "stale",
    "stopped",
}


def _valid_evaluated_window(src: Mapping[str, Any], risk: float | None) -> bool:
    if risk is None:
        return False
    status = str(src.get("status") or src.get("runtime_status") or "").strip().lower()
    if status in _NON_ACTIONABLE_STATUSES:
        return False
    window_count = _first_number(src, "runtime_window_count", "window_count") or 0
    quality_count = _first_number(src, "runtime_quality_ok_windows", "quality_ok_windows") or 0
    if window_count <= 0 or quality_count <= 0:
        return False
    return True


def _actionability(ready: bool, fresh: bool) -> str:
    if ready and fresh:
        return "actionable_fresh_window"
    if ready:
        return "observed_only"
    return "pending"
