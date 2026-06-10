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

def _shadow_baseline_evidence_fields_for_user(user_id: str) -> Dict[str, Any]:
    """Return privacy-safe production-baseline decision fields for shadow evidence.

    Shadow evidence mode compares a candidate shadow runtime against the active
    production runtime, but the candidate must remain report-only. If no active
    production baseline exists or it cannot score the same live session, this
    helper returns no baseline fields so Production Evidence remains fail-closed.
    """

    if not _shadow_evidence_mode():
        return {}
    safe_user = str(user_id or EXPECTED_USER_SLUG or EXPECTED_USER or "").strip()
    if not safe_user:
        return {}
    try:
        baseline_runtime = _load_user_runtime_bundle(safe_user)
    except Exception as exc:
        LOGGER.warning("shadow_evidence_baseline_runtime_load_failed for %s: %s", safe_user, exc)
        return {}
    if not isinstance(baseline_runtime, dict) or baseline_runtime.get("model") is None:
        return {}
    try:
        baseline_prediction = _predict_runtime(baseline_runtime)
    except Exception as exc:
        LOGGER.warning("shadow_evidence_baseline_prediction_failed for %s: %s", safe_user, exc)
        return {}
    if not isinstance(baseline_prediction, dict):
        return {}
    status = str(baseline_prediction.get("status") or "ok").strip().lower()
    if status != "ok":
        return {}
    baseline_decision = _baseline_decision_from_prediction(baseline_prediction)
    if not baseline_decision:
        return {}
    fields: Dict[str, Any] = {
        "baseline_decision": baseline_decision,
        "baseline_risk": baseline_prediction.get("risk", 0),
        "baseline_would_lock_if_production": _baseline_would_lock_from_prediction(baseline_prediction, baseline_decision),
    }
    baseline_digest = _runtime_artifact_digest(baseline_runtime)
    if baseline_digest:
        fields["baseline_artifact_digest"] = baseline_digest
    return fields

def _write_hybrid_direct_test_report(report: Dict[str, Any]) -> str:
    path = _hybrid_direct_test_report_path()
    _safe_json_write(path, report)
    return path

def _hybrid_report_base(*, passed: bool = False, reason_codes: Optional[List[str]] = None) -> Dict[str, Any]:
    codes = list(dict.fromkeys([str(code) for code in (reason_codes or []) if str(code or '').strip()]))
    if "hybrid_direct_test_only" not in codes:
        codes.append("hybrid_direct_test_only")
    if "device_influence_disabled" not in codes:
        codes.append("device_influence_disabled")
    return {
        "passed": bool(passed),
        "timestamp": _utc_timestamp(),
        "user": EXPECTED_USER_SLUG or slugify_username(EXPECTED_USER or "") or "user",
        "profile": EXPECTED_USER or EXPECTED_USER_SLUG or "user",
        "reason_codes": codes,
        "monitor": {
            "runtime_mode": HYBRID_DIRECT_TEST_SESSION_KIND,
            "source": HYBRID_DIRECT_TEST_SOURCE,
            "process_identity": CONTROL_NAME,
            "uses_shadow_monitor": False,
            "uses_production_monitor_executable": True,
            "test_only": bool(HYBRID_DIRECT_TEST_ONLY),
            "device_influence_allowed": False,
        },
        "safety": {
            "lock_allowed": False,
            "device_lock_allowed": False,
            "protected_sessions_unlock_allowed": False,
            "face_confirmation_allowed": False,
            "face_confirmation_trigger_allowed": False,
            "production_pointer_write_allowed": False,
            "production_approval_allowed": False,
            "production_promotion_allowed": False,
            "raw_behavioral_data_included": False,
        },
        "model_identity": {},
        "result": {},
        "report_path": _hybrid_direct_test_report_path(),
    }

def _run_hybrid_direct_test_once() -> int:
    clear_stop(CONTROL_NAME)
    reason_codes: List[str] = []
    if SHADOW_EVIDENCE_ONLY:
        report = _hybrid_report_base(passed=False, reason_codes=["blocked_shadow_monitor_identity", "hybrid_direct_shadow_forbidden"])
        report["monitor"]["uses_shadow_monitor"] = True
        _write_hybrid_direct_test_report(report)
        return 2
    if not HYBRID_DIRECT_TEST_ONLY:
        reason_codes.append("hybrid_test_only_env_missing")
    if HYBRID_DEVICE_INFLUENCE_ALLOWED:
        reason_codes.append("device_influence_env_not_disabled")
    existing = read_session_state(default={})
    existing = existing if isinstance(existing, dict) else {}
    try:
        runtime = _load_runtime_model()
    except SecurityError as exc:
        report = _hybrid_report_base(passed=False, reason_codes=reason_codes + ["artifact_integrity_failed"])
        report["error"] = str(exc)[:300]
        _write_hybrid_direct_test_report(report)
        return 3
    except Exception as exc:
        LOGGER.exception("Hybrid Direct Test monitor startup failed")
        report = _hybrid_report_base(passed=False, reason_codes=reason_codes + ["monitor_runtime_error"])
        report["error"] = type(exc).__name__
        _write_hybrid_direct_test_report(report)
        return 4
    if not runtime or not isinstance(runtime, dict) or runtime.get("model") is None or not runtime.get("metadata"):
        report = _hybrid_report_base(passed=False, reason_codes=reason_codes + ["model_unavailable"])
        report["model_identity"] = _runtime_identity(runtime)
        _write_hybrid_direct_test_report(report)
        return 5
    try:
        started = time.perf_counter()
        prediction = _predict_runtime(runtime)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        prediction = prediction if isinstance(prediction, dict) else {}
        diag = _prediction_diagnostics(prediction) if prediction else {}
        status = str(prediction.get("status") or "ok")
        technical_failure = runtime_status_is_technical_failure(status)
        awaiting_evidence = runtime_status_awaits_evidence(status)
        model_decision = _normalize_state_label(prediction.get("final"))
        passed = not technical_failure and bool(prediction)
        result_codes = list(reason_codes)
        result_codes.append("hybrid_direct_monitor_prediction_completed" if passed else "hybrid_direct_monitor_prediction_not_ready")
        if awaiting_evidence:
            result_codes.append("awaiting_evidence")
        if technical_failure:
            result_codes.append("technical_failure")
        report = _hybrid_report_base(passed=passed, reason_codes=result_codes)
        report["model_identity"] = _runtime_identity(runtime)
        report["result"] = {
            "status": status,
            "decision": model_decision or "pending",
            "risk": int(prediction.get("risk") or 0),
            "score": float(prediction.get("raw") or 0.0),
            "latency_ms": latency_ms,
            "window_count": int((diag or {}).get("window_count") or 0),
            "quality_ok_windows": int(((diag or {}).get("quality") or {}).get("quality_ok_window_count") or 0),
            "diagnostic_code": "awaiting_evidence" if awaiting_evidence else ("technical_failure" if technical_failure else "ok"),
        }
        report["session"] = {
            "existing_session_id": str(existing.get("session_id") or ""),
            "existing_session_kind": str(existing.get("session_kind") or ""),
            "state_written": False,
        }
        _write_hybrid_direct_test_report(report)
        return 0 if passed else 6
    except Exception as exc:
        LOGGER.exception("Hybrid Direct Test prediction failed")
        report = _hybrid_report_base(passed=False, reason_codes=reason_codes + ["hybrid_direct_prediction_error"])
        report["model_identity"] = _runtime_identity(runtime)
        report["error"] = type(exc).__name__
        _write_hybrid_direct_test_report(report)
        return 7

def _request_shutdown(*_args):
    global _running
    _running = False

def _sleep_with_stop(total_seconds: float, step_seconds: float = 0.5) -> bool:
    deadline = time.time() + max(0.0, float(total_seconds))
    while _running and time.time() < deadline:
        if should_stop_monitor(CONTROL_NAME):
            return False
        remaining = max(0.0, deadline - time.time())
        time.sleep(min(step_seconds, remaining if remaining > 0 else step_seconds))
    return _running and not should_stop_monitor(CONTROL_NAME)

def _monitor_sleep_interval(*, settings: Dict[str, Any], current_state: Dict[str, Any], existing_state: Dict[str, Any], warnings: int, recent_decisions: deque[str], recent_risks: deque[float]) -> float:
    base_interval = int(settings.get("monitor_interval_sec", CHECK_INTERVAL) or CHECK_INTERVAL)
    base_interval = max(5, min(120, base_interval))

    config = _runtime_config_from_settings(settings)
    fast_warning_interval = max(0.5, min(base_interval, _runtime_float(config, "runtime_warning_fast_interval_seconds", FAST_WARNING_INTERVAL)))
    fast_startup_interval = max(0.5, min(base_interval, _runtime_float(config, "runtime_startup_fast_interval_seconds", FAST_STARTUP_INTERVAL)))

    state = current_state if isinstance(current_state, dict) else {}
    existing = existing_state if isinstance(existing_state, dict) else {}
    session_status = str(state.get("status") or existing.get("status") or "").strip().lower()
    decision = _normalize_state_label(state.get("decision") or state.get("final_decision") or existing.get("decision") or existing.get("final_decision"))
    elapsed = _elapsed_seconds(state.get("started_at") or existing.get("started_at"))
    recent4 = list(recent_decisions)[-4:]
    recent_alert_hits = sum(dec in {"intruder", "suspicious"} for dec in recent4)
    recent_risk_slice = list(recent_risks)[-3:]
    recent_peak_risk = max((float(v) for v in recent_risk_slice), default=0.0)
    warning_peak = _runtime_float(config, "runtime_warning_lock_peak_risk", 76.0)

    if session_status in {"starting", "model_unavailable", "insufficient_windows", "insufficient_events", "awaiting_evidence", "transitioning", "resume_pending"} or elapsed < 12.0:
        return fast_startup_interval
    if warnings > 0 or decision == "suspicious" or recent_alert_hits > 0 or recent_peak_risk >= warning_peak:
        return fast_warning_interval
    return float(base_interval)

def _clear_runtime_memory(recent_decisions: deque[str], recent_risks: deque[float], recent_timestamps: deque[float]) -> None:
    recent_decisions.clear()
    recent_risks.clear()
    recent_timestamps.clear()

def _trim_runtime_memory(recent_decisions: deque[str], recent_risks: deque[float], recent_timestamps: deque[float], *, keep: int) -> None:
    keep_count = max(0, int(keep))
    while len(recent_decisions) > keep_count:
        recent_decisions.popleft()
    while len(recent_risks) > keep_count:
        recent_risks.popleft()
    while len(recent_timestamps) > keep_count:
        recent_timestamps.popleft()

def _apply_pending_state_decay(
    *,
    prediction_status: str,
    warnings: int,
    recent_decisions: deque[str],
    recent_risks: deque[float],
    recent_timestamps: deque[float],
    runtime_config: Dict[str, Any],
) -> int:
    status = str(prediction_status or "").strip().lower()
    hard_reset_statuses = {"resume_pending", "verifying_return"}
    if status in hard_reset_statuses:
        _clear_runtime_memory(recent_decisions, recent_risks, recent_timestamps)
        return 0
    keep_count = _runtime_int(runtime_config, "runtime_pending_memory_keep", 1)
    _trim_runtime_memory(recent_decisions, recent_risks, recent_timestamps, keep=keep_count)
    return max(0, int(warnings) - 1)
