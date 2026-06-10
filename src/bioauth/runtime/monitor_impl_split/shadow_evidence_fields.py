"""Extracted implementation section for `src/bioauth/runtime/monitor_impl.py`."""
from __future__ import annotations
import hashlib
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from collections import deque
from typing import Any, Dict, List, Optional
from app_settings import demo_classic_protected_enabled, load_settings
from bio_platform.lock_screen import lock_current_session, lock_current_session_result
from bioauth_model.scoring import resolve_runtime_escalation_config
from control import clear_stop, read_session_state, request_stop, should_stop, write_worker_heartbeat
from shadow_core.background_contracts import shadow_evidence_ledger_path, shadow_monitor_stop_control_name
from evidence_capture import capture_incident_evidence, update_incident_record
from feedback_loop import FEEDBACK_POLICY_VERSION
from face_camera_provider import build_default_camera_provider
from identity_confirmation import build_default_identity_confirmation_service, confirm_identity_before_lock
from model import SecurityError, load_model
from artifact_integrity import load_classifier, load_metadata
from model_inference import _load_user_runtime_bundle, predict_from_session_details
from bridge.shared import runtime_status_is_technical_failure, runtime_status_awaits_evidence
from model_metadata import LIVE_SESSION_DIR
from runtime_policy import normalize_calibration_maturity
from monitor_core.common import (
    _decision_bucket,
    _final_monitor_state,
    _intruder_hold_active,
    _load_log_entries,
    _load_runtime_model,
    _log_entries_cache,
    _normalize_state_label,
    _predict_runtime,
    _safe_json_write,
    _same_session,
    _save_log_entries,
    _write_monitor_state,
    append_log,
)
from monitor_core.escalation import (
    _elapsed_seconds,
    _intruder_confirmed,
    _resolve_runtime_escalation,
    _rolling_average,
    _runtime_config_from_settings,
    _runtime_float,
    _runtime_int,
)
from monitor_core.incident import (
    _capture_intruder_evidence,
    _pre_lock_face_confirmation,
    _record_face_confirmed_false_positive,
    _lock_and_stop_for_intruder,
    _lock_app_state,
    _lock_workstation,
    _lock_workstation_result,
    _signal_monitor_start_failure,
    _stop_logger_for_context,
)
from paths import data_dir, evidence_dir, monitor_log_file, settings_file as from_app_settings_file
from security import atomic_write_bytes, get_cipher
from utils.identity import slugify_username
from bioauth_runtime.monitor_worker.shutdown import should_stop_monitor
from bioauth_runtime import runtime_boundary

def _seed_legitimate_runtime_memory(
    recent_decisions: deque[str],
    recent_risks: deque[float],
    recent_timestamps: deque[float],
    *,
    risk: float,
    at: float,
) -> None:
    _clear_runtime_memory(recent_decisions, recent_risks, recent_timestamps)
    recent_decisions.append("legit")
    recent_risks.append(float(risk))
    recent_timestamps.append(float(at))

def _round_float(value: Any, digits: int = 2) -> float:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError, OverflowError):
        return 0.0

def _runtime_buffer_snapshot(recent_decisions: deque[str], recent_risks: deque[float], recent_timestamps: deque[float], *, now: Optional[float] = None, limit: int = 5) -> Dict[str, Any]:
    current_time = float(now if now is not None else time.time())
    decisions = list(recent_decisions)[-max(1, int(limit)) :]
    risks = [round(float(value), 2) for value in list(recent_risks)[-len(decisions) :]]
    times = list(recent_timestamps)[-len(decisions) :]
    ages: List[float] = []
    if len(times) == len(decisions):
        ages = [round(max(0.0, current_time - float(ts)), 2) for ts in times]
    return {
        "decisions": decisions,
        "risks": risks,
        "ages_sec": ages,
        "sample_count": len(decisions),
    }

def _prediction_diagnostics(prediction: Dict[str, Any]) -> Dict[str, Any]:
    transition = dict(prediction.get("transition_state") or {}) if isinstance(prediction, dict) else {}
    calibration = dict(prediction.get("user_calibration") or {}) if isinstance(prediction, dict) else {}
    calibration_maturity = normalize_calibration_maturity({"calibration_maturity": dict(prediction.get("calibration_maturity") or {})}) if isinstance(prediction, dict) else normalize_calibration_maturity({})
    routing = dict(prediction.get("context_routing") or {}) if isinstance(prediction, dict) else {}
    classifier = dict(prediction.get("supervised_classifier") or {}) if isinstance(prediction, dict) else {}
    deep_sequence = dict(prediction.get("deep_sequence") or {}) if isinstance(prediction, dict) else {}
    hybrid_shadow = dict(prediction.get("hybrid_shadow") or {}) if isinstance(prediction, dict) else {}
    rollout = dict(prediction.get("runtime_rollout") or {}) if isinstance(prediction, dict) else {}
    quality = dict(prediction.get("window_quality") or {}) if isinstance(prediction, dict) else {}
    quality_gate = dict(prediction.get("window_quality_gate") or {}) if isinstance(prediction, dict) else {}
    performance = dict(prediction.get("runtime_performance") or {}) if isinstance(prediction, dict) else {}
    live_input = dict(prediction.get("live_input") or {}) if isinstance(prediction, dict) else {}
    dynamic_fusion = dict(prediction.get("dynamic_fusion") or {}) if isinstance(prediction, dict) else {}
    layer_payloads = dict(prediction.get("runtime_layer_payloads") or {}) if isinstance(prediction, dict) else {}
    return {
        "status": str(prediction.get("status") or "ok"),
        "performance": performance,
        "live_input": live_input,
        "final": str(prediction.get("final") or "unknown"),
        "decision_source": str(prediction.get("decision_source") or "classic"),
        "decision_reason": str(prediction.get("decision_reason") or ""),
        "decision_details": dict(prediction.get("decision_details") or {}),
        "window_count": int(prediction.get("window_count") or 0),
        "base_window_risk_mean": _round_float(prediction.get("base_window_risk_mean")),
        "calibrated_window_risk_mean": _round_float(prediction.get("calibrated_window_risk_mean")),
        "transition": {
            "status": str(transition.get("status") or "unknown"),
            "active": bool(transition.get("active")),
            "transition_window_count": int(transition.get("transition_window_count") or 0),
            "recent_transition_windows": int(transition.get("recent_transition_windows") or 0),
            "recent_settled_windows": int(transition.get("recent_settled_windows") or 0),
            "last_transition_flag": bool(transition.get("last_transition_flag")),
            "last_session_start_flag": bool(transition.get("last_session_start_flag")),
            "last_post_idle_flag": bool(transition.get("last_post_idle_flag")),
            "max_transition_strength": _round_float(transition.get("max_transition_strength")),
        },
        "calibration": {
            "enabled": bool(calibration.get("enabled")),
            "applied": bool(calibration.get("applied")),
            "maturity_flag": bool(calibration.get("maturity_flag")),
            "maturity_reason": str(calibration.get("maturity_reason") or ""),
        },
        "calibration_maturity": {
            "mature": bool(calibration_maturity.get("mature")),
            "lock_allowed": bool(calibration_maturity.get("lock_allowed")),
            "progressive_phase": str(calibration_maturity.get("progressive_phase") or ""),
            "reason_codes": list(calibration_maturity.get("reason_codes") or []),
            "requirements": dict(calibration_maturity.get("requirements") or {}),
            "counts": dict(calibration_maturity.get("counts") or {}),
        },
        "routing": {
            "enabled": bool(routing.get("enabled")),
            "routed_window_count": int(routing.get("routed_window_count") or 0),
            "fallback_window_count": int(routing.get("fallback_window_count") or 0),
            "min_confidence": _round_float(routing.get("min_confidence")),
            "used_context_counts": dict(routing.get("used_context_counts") or {}),
        },
        "classifier": {
            "enabled": bool(classifier.get("enabled")),
            "selected_family": str(classifier.get("selected_family") or ""),
            "selection_reason": str(classifier.get("selection_reason") or ""),
        },
        "deep_sequence": {
            "used": bool(deep_sequence.get("used")),
            "reason": str(deep_sequence.get("reason") or ""),
            "probability": _round_float(deep_sequence.get("probability")),
            "risk": int(deep_sequence.get("risk") or 0),
        },
        "hybrid_shadow": {
            "used": bool(hybrid_shadow.get("used")),
            "used_for_decision": bool(hybrid_shadow.get("used_for_decision")),
            "final": str(hybrid_shadow.get("final") or ""),
            "risk": int(hybrid_shadow.get("risk") or 0),
            "intruder_prob": _round_float(hybrid_shadow.get("intruder_prob")),
        },
        "rollout": {
            "production_decision_enabled": bool(rollout.get("production_decision_enabled")),
            "rollout_status": str(rollout.get("rollout_status") or ""),
            "runtime_activation_reason": str(rollout.get("runtime_activation_reason") or ""),
            "rollback_reason": str(rollout.get("rollback_reason") or ""),
        },
        "quality": {
            "window_count": int(quality.get("window_count") or 0),
            "quality_ok_window_count": int(quality.get("quality_ok_window_count") or 0),
            "quality_lock_ok_window_count": int(quality.get("quality_lock_ok_window_count") or 0),
            "low_quality_window_count": int(quality.get("low_quality_window_count") or 0),
            "average_quality_score": _round_float(quality.get("average_quality_score")),
            "lock_quality_allowed": bool(quality.get("lock_quality_allowed")),
            "blocked_reason_codes": list(quality.get("blocked_reason_codes") or []),
            "gate_applied": bool(quality_gate.get("applied")),
            "gate_reason": str(quality_gate.get("reason") or ""),
        },
        "runtime_layer_payloads": layer_payloads,
        "dynamic_fusion": {
            "enabled": bool(dynamic_fusion.get("enabled")),
            "policy_version": str(dynamic_fusion.get("policy_version") or ""),
            "window_count": int(dynamic_fusion.get("window_count") or 0),
            "applied_window_count": int(dynamic_fusion.get("applied_window_count") or 0),
            "risk_capped_window_count": int(dynamic_fusion.get("risk_capped_window_count") or 0),
            "probability_capped_window_count": int(dynamic_fusion.get("probability_capped_window_count") or 0),
            "average_evidence_confidence": _round_float(dynamic_fusion.get("average_evidence_confidence")),
            "can_lock": bool(dynamic_fusion.get("can_lock")),
            "can_change_threshold": bool(dynamic_fusion.get("can_change_threshold")),
            "can_change_model_pointer": bool(dynamic_fusion.get("can_change_model_pointer")),
        },
        "window_diagnostics": list(prediction.get("window_diagnostics") or []),
        "window_diagnostics_summary": dict(prediction.get("window_diagnostics_summary") or {}),
    }

def _window_diag_summary_brief(prediction_diag: Dict[str, Any]) -> str:
    summary = dict(prediction_diag.get("window_diagnostics_summary") or {})
    brief = str(summary.get("brief") or "").strip()
    if brief:
        return brief
    top_windows = list(summary.get("top_risky_windows") or [])
    if not top_windows:
        return "none"
    parts: List[str] = []
    for item in top_windows[:3]:
        reasons = list(item.get("reason_codes") or [])
        reason_text = "+".join(reasons[:2]) if reasons else "-"
        parts.append(f"#{int(item.get('index') or 0)}:r{int(round(float(item.get('risk') or 0.0)))}:{str(item.get('context') or '-') or '-'}:{reason_text}")
    return " | ".join(parts)

def _last_window_diag(prediction_diag: Dict[str, Any]) -> Dict[str, Any]:
    diagnostics = list(prediction_diag.get("window_diagnostics") or [])
    return dict(diagnostics[-1] or {}) if diagnostics else {}

def _observed_lock_quality_risk_evidence(prediction_diag: Dict[str, Any]) -> Dict[str, Any]:
    """Return raw/observed risk evidence from lock-quality windows.

    The monitor's decision risk may be capped while calibration is immature.
    This helper keeps that production cap intact, but exposes the strongest
    privacy-safe observed window risks so the embedded classic presentation
    build can decide whether calibration-only suppression should be bypassed.
    """

    candidates: List[float] = []
    sources: List[Dict[str, Any]] = []

    def _risk_value(item: Dict[str, Any]) -> float:
        values: List[float] = []
        for key in ("base_risk", "risk", "observed_risk"):
            try:
                values.append(float(item.get(key) or 0.0))
            except (TypeError, ValueError, OverflowError):
                pass
        return max(values, default=0.0)

    def _eligible(item: Dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        if item.get("quality_lock_ok") is False:
            return False
        if bool(item.get("transition_flag")) or bool(item.get("session_start_flag")) or bool(item.get("post_idle_flag")):
            return False
        return _risk_value(item) > 0.0

    diagnostics = [dict(item or {}) for item in list(prediction_diag.get("window_diagnostics") or []) if isinstance(item, dict)]
    summary = dict(prediction_diag.get("window_diagnostics_summary") or {})
    top_windows = [dict(item or {}) for item in list(summary.get("top_risky_windows") or []) if isinstance(item, dict)]
    for item in diagnostics + top_windows:
        if not _eligible(item):
            continue
        value = _risk_value(item)
        candidates.append(value)
        sources.append({
            "index": int(item.get("index") or 0),
            "risk": round(value, 2),
            "context": str(item.get("context") or ""),
            "quality_lock_ok": bool(item.get("quality_lock_ok", True)),
        })

    # De-duplicate by (index, risk, context) while preserving strongest evidence.
    seen: set[tuple[int, float, str]] = set()
    unique_sources: List[Dict[str, Any]] = []
    unique_risks: List[float] = []
    for source in sorted(sources, key=lambda item: float(item.get("risk") or 0.0), reverse=True):
        key = (int(source.get("index") or 0), float(source.get("risk") or 0.0), str(source.get("context") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique_sources.append(source)
        unique_risks.append(float(source.get("risk") or 0.0))

    return {
        "peak_risk": round(max(unique_risks, default=0.0), 2),
        "high90_count": sum(1 for value in unique_risks if float(value) >= 90.0),
        "risks": [round(float(value), 2) for value in unique_risks[:6]],
        "sources": unique_sources[:6],
    }
