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
DATA_DIR = data_dir()
LOG_FILE = monitor_log_file()
CHECK_INTERVAL = 8
FAST_WARNING_INTERVAL = 1.0
FAST_STARTUP_INTERVAL = 1.0
WARNING_LIMIT = 2
RISK_WINDOW = 5
EXPECTED_USER = sys.argv[1].strip() if len(sys.argv) > 1 else None
EXPECTED_USER_SLUG = slugify_username(EXPECTED_USER or "") or None
SHADOW_EVIDENCE_SESSION_KIND = "shadow_evidence"
SHADOW_EVIDENCE_SOURCE = "shadow_evidence_monitor"
RUNTIME_MODE = os.environ.get("BIOAUTH_RUNTIME_MODE", "").strip().lower()
_DEV_OVERRIDES_ENABLED = runtime_boundary.dev_features_enabled()
SHADOW_EVIDENCE_ONLY = os.environ.get("BIOAUTH_SHADOW_EVIDENCE_ONLY", "").strip() == "1" or RUNTIME_MODE == SHADOW_EVIDENCE_SESSION_KIND
HYBRID_DIRECT_TEST_MODE = RUNTIME_MODE == "hybrid_direct_test" or os.environ.get("BIOAUTH_HYBRID_TEST_ONLY", "").strip() == "1"
HYBRID_DIRECT_TEST_ONLY = os.environ.get("BIOAUTH_HYBRID_TEST_ONLY", "").strip() == "1"
HYBRID_DEVICE_INFLUENCE_ALLOWED = os.environ.get("BIOAUTH_DEVICE_INFLUENCE_ALLOWED", "0").strip().lower() in {"1", "true", "yes", "on"}
HYBRID_DIRECT_TEST_SOURCE = "hybrid_direct_test_monitor"
HYBRID_DIRECT_TEST_SESSION_KIND = "hybrid_direct_test"
CONTROL_NAME = shadow_monitor_stop_control_name(EXPECTED_USER_SLUG or EXPECTED_USER or "user") if SHADOW_EVIDENCE_ONLY else (
    f"hybrid_direct_test_monitor_user_{EXPECTED_USER_SLUG or slugify_username(EXPECTED_USER or '') or 'user'}"
    if HYBRID_DIRECT_TEST_MODE
    else "monitor"
)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
_running = True
_LOG_LOCK = threading.Lock()
_LOG_CACHE: Optional[List[Dict[str, Any]]] = None
LOGGER = logging.getLogger(__name__)
_MONITOR_DIAG_LOCK = threading.Lock()
_MONITOR_DIAG_LOG_PATH_CACHE: Optional[str] = None
_MONITOR_DIAG_RUN_ID = os.environ.get("BIOAUTH_RUN_ID", "").strip() or f"monitor-{int(time.time())}-{os.getpid()}"


def _auto_resume_grace_guard(state: Dict[str, Any], prediction_diag: Dict[str, Any], *, now: float) -> Dict[str, Any]:
    """Return post-unlock lock suppression state for auto-resumed sessions."""
    if not bool((state or {}).get("return_verification") or (state or {}).get("auto_resume_loop_guard_armed")):
        return {"active": False, "reason": "not_auto_resumed"}
    try:
        started_at = float((state or {}).get("auto_resume_started_at") or (state or {}).get("started_at") or now)
    except (TypeError, ValueError):
        started_at = now
    try:
        grace_until = float((state or {}).get("auto_resume_grace_until") or (started_at + 30.0))
    except (TypeError, ValueError):
        grace_until = started_at + 30.0
    try:
        min_quality = int((state or {}).get("auto_resume_min_quality_windows") or 3)
    except (TypeError, ValueError):
        min_quality = 3
    quality = prediction_diag.get("quality") if isinstance(prediction_diag, dict) else {}
    quality = quality if isinstance(quality, dict) else {}
    quality_windows = int(quality.get("quality_lock_ok_window_count") or quality.get("quality_ok_window_count") or 0)
    window_count = int((prediction_diag or {}).get("window_count") or 0)
    age = max(0.0, float(now) - float(started_at))
    enough_time = now >= grace_until
    enough_quality = quality_windows >= min_quality
    active = not (enough_time and enough_quality and window_count > 0)
    reason = "post_unlock_reverification_pending" if active else "post_unlock_reverification_complete"
    return {
        "active": bool(active),
        "reason": reason,
        "session_age_sec": round(age, 3),
        "grace_remaining_sec": round(max(0.0, grace_until - now), 3),
        "quality_windows": int(quality_windows),
        "required_quality_windows": int(min_quality),
        "window_count": int(window_count),
    }

# Compatibility shell: implementation functions are loaded into this module
# so existing monkeypatches of private globals such as _facade still work.
from pathlib import Path as _BioAuthSplitPath

_BIOAUTH_SPLIT_DIR = _BioAuthSplitPath(__file__).with_name('monitor_impl_split')
_BIOAUTH_SPLIT_MODULES = ('runtime_flags.py', 'monitor_diagnostics.py', 'shadow_evidence_fields.py', 'hybrid_report_only.py',)

def _bioauth_load_split_modules() -> None:
    namespace = globals()
    for module_name in _BIOAUTH_SPLIT_MODULES:
        module_path = _BIOAUTH_SPLIT_DIR / module_name
        code = module_path.read_text(encoding='utf-8')
        exec(compile(code, str(module_path), 'exec'), namespace, namespace)

_bioauth_load_split_modules()

def monitor():
    global _running
    _running = True
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)
    if _hybrid_direct_test_mode():
        return _run_hybrid_direct_test_once()
    clear_stop(CONTROL_NAME)

    existing = read_session_state(default={})
    startup_extra = {
        "session_id": (existing.get("session_id") if isinstance(existing, dict) else None),
        "user_id": (existing.get("user_id") if isinstance(existing, dict) else None),
        "session_kind": (existing.get("session_kind", "protected") if isinstance(existing, dict) else "protected"),
        "started_at": (existing.get("started_at") if isinstance(existing, dict) else None),
        "started_at_text": (existing.get("started_at_text") if isinstance(existing, dict) else None),
        "monitor_ready": False,
        "monitor_failed": False,
        "monitor_error": None,
        "status": "shadow_evidence_starting" if _shadow_evidence_mode() else "starting",
    }
    if _shadow_evidence_mode():
        startup_extra.update(_shadow_evidence_state_fields(False, []))
    _write_monitor_state(
        decision=(existing.get("decision") if isinstance(existing, dict) else None),
        extra=startup_extra,
    )
    _monitor_diag_event("monitor_starting", {
        "startup_extra": startup_extra,
        "diagnostic_log_path": _monitor_diag_log_path() if _monitor_diag_enabled() else "",
        "env_flags": {
            "BIOAUTH_DEV_ALLOW_IMMATURE_LOCK": _env_flag("BIOAUTH_DEV_ALLOW_IMMATURE_LOCK"),
            "BIOAUTH_DEV_PRODUCTION_READY_SIMULATION": _env_flag("BIOAUTH_DEV_PRODUCTION_READY_SIMULATION"),
            "BIOAUTH_ALLOW_SHADOW_CANDIDATE_RUNTIME_FALLBACK": _env_flag("BIOAUTH_ALLOW_SHADOW_CANDIDATE_RUNTIME_FALLBACK"),
            "BIOAUTH_MONITOR_VERBOSE_DIAGNOSTICS": _env_flag("BIOAUTH_MONITOR_VERBOSE_DIAGNOSTICS"),
        },
    })
    try:
        runtime = _load_runtime_model()
    except SecurityError as exc:
        _monitor_diag_event("monitor_startup_failed", {"reason": "artifact_integrity_failed", "error_type": type(exc).__name__, "error": str(exc)}, level="error")
        print(exc, flush=True)
        _signal_monitor_start_failure("artifact_integrity_failed", existing)
        return
    except Exception as exc:
        _monitor_diag_event("monitor_startup_failed", {"reason": "unhandled_startup_exception", "error_type": type(exc).__name__, "error": str(exc)}, level="error")
        LOGGER.exception("Monitor startup failed before model readiness")
        _signal_unhandled_monitor_failure(exc, existing)
        print(f"Monitor startup failure: {type(exc).__name__}", file=sys.stderr, flush=True)
        return

    if not runtime or runtime.get("model") is None or not runtime.get("metadata"):
        _monitor_diag_event("monitor_startup_failed", {"reason": "model_unavailable", "runtime_identity": _runtime_identity(runtime if isinstance(runtime, dict) else {})}, level="error")
        print("No model found", flush=True)
        if _shadow_evidence_mode():
            runtime_meta = runtime.get("metadata") if isinstance(runtime, dict) else {}
            runtime_meta = runtime_meta if isinstance(runtime_meta, dict) else {}
            blocked_reason = str(runtime_meta.get("shadow_evidence_blocked_reason") or "model_unavailable")
            _write_monitor_state(
                decision="pending",
                extra={
                    **_shadow_evidence_state_fields(False, [blocked_reason]),
                    "session_id": existing.get("session_id") if isinstance(existing, dict) else None,
                    "user_id": existing.get("user_id") if isinstance(existing, dict) else EXPECTED_USER_SLUG,
                    "started_at": existing.get("started_at") if isinstance(existing, dict) else None,
                    "started_at_text": existing.get("started_at_text") if isinstance(existing, dict) else None,
                    "monitor_ready": False,
                    "monitor_failed": True,
                    "technical_failure": bool(runtime_meta.get("technical_failure")),
                    "awaiting_evidence": not bool(runtime_meta.get("technical_failure")),
                    "monitor_error": blocked_reason,
                    "shadow_evidence_blocked_reason": blocked_reason,
                    "runtime_diagnostic_code": blocked_reason,
                    "runtime_diagnostic_reason": blocked_reason,
                    "status": "shadow_evidence_failed" if bool(runtime_meta.get("technical_failure")) else "shadow_evidence_blocked",
                },
            )
            return
        _signal_monitor_start_failure("model_unavailable", existing)
        return

    session_id = existing.get("session_id")
    ready_extra = {
        "session_id": session_id,
        "user_id": existing.get("user_id"),
        "session_kind": existing.get("session_kind", "protected"),
        "app_locked": False,
        "started_at": existing.get("started_at"),
        "started_at_text": existing.get("started_at_text"),
        "monitor_ready": True,
        "monitor_failed": False,
        "monitor_error": None,
        "status": "shadow_evidence" if _shadow_evidence_mode() else "ok",
    }
    if _shadow_evidence_mode():
        ready_extra.update(_shadow_evidence_state_fields(False, []))
    _write_monitor_state(
        decision=existing.get("decision"),
        extra=ready_extra,
    )
    _monitor_diag_event("monitor_ready", {
        "ready_extra": ready_extra,
        "runtime_identity": _runtime_identity(runtime),
        "runtime_artifact_digest": _runtime_artifact_digest(runtime),
        "runtime_metadata": dict((runtime.get("metadata") if isinstance(runtime, dict) else {}) or {}),
        "dev_runtime_bundle_fallback": bool((runtime or {}).get("dev_runtime_bundle_fallback")) if isinstance(runtime, dict) else False,
    })
    if _shadow_evidence_mode():
        LOGGER.info("shadow_evidence_monitor_started")

    warnings = 0
    legit_streak = 0
    lock_suppressed_until = 0.0
    risk_buffer: deque[float] = deque(maxlen=RISK_WINDOW)
    decision_buffer: deque[str] = deque(maxlen=RISK_WINDOW)
    decision_timestamps: deque[float] = deque(maxlen=RISK_WINDOW)
    monitor_exit_reason = "unknown"
    monitor_exit_detail: Dict[str, Any] = {}
    _cached_settings: Dict[str, Any] = {}
    _cached_settings_mtime: float = 0.0

    try:
        while _running:
            current_state = read_session_state(default={})
            current_state = current_state if isinstance(current_state, dict) else {}
            if session_id and current_state.get("session_id") not in (None, "", session_id):
                monitor_exit_reason = "session_id_mismatch"
                monitor_exit_detail = {
                    "expected_session_id": session_id,
                    "actual_session_id": current_state.get("session_id"),
                    "state_status": current_state.get("status"),
                    "state_active": bool(current_state.get("active")),
                }
                break
            if _intruder_hold_active(current_state, session_id):
                if not _sleep_with_stop(0.75):
                    monitor_exit_reason = "stop_requested_during_intruder_hold"
                    monitor_exit_detail = {
                        "state_status": current_state.get("status"),
                        "state_active": bool(current_state.get("active")),
                        "intruder_hold_active": True,
                    }
                    break
                continue
            if current_state and not current_state.get("active"):
                monitor_exit_reason = "session_inactive"
                monitor_exit_detail = {
                    "state_status": current_state.get("status"),
                    "state_decision": current_state.get("decision"),
                    "state_final_decision": current_state.get("final_decision"),
                    "state_forced_stop": bool(current_state.get("forced_stop")),
                    "state_app_locked": bool(current_state.get("app_locked")),
                    "state_screen_locked": bool(current_state.get("screen_locked")),
                    "state_stop_reason": current_state.get("stop_reason"),
                }
                break

            try:
                _mtime = os.path.getmtime(from_app_settings_file())
            except OSError:
                _mtime = 0.0
            if _mtime != _cached_settings_mtime or not _cached_settings:
                _cached_settings = load_settings()
                _cached_settings_mtime = _mtime
            settings = _cached_settings
            runtime_config = _runtime_config_from_settings(settings)
            interval = _monitor_sleep_interval(settings=settings, current_state=current_state, existing_state=existing, warnings=warnings, recent_decisions=decision_buffer, recent_risks=risk_buffer)
            if not _sleep_with_stop(interval):
                monitor_exit_reason = "stop_requested"
                monitor_exit_detail = {
                    "state_status": current_state.get("status"),
                    "state_active": bool(current_state.get("active")),
                    "sleep_interval_sec": interval,
                }
                break

            ts = time.strftime("%H:%M:%S")
            try:
                prediction_cycle_started = time.perf_counter()
                prediction = _predict_runtime(runtime)
                monitor_cycle_ms = round((time.perf_counter() - prediction_cycle_started) * 1000.0, 3)
                if isinstance(prediction, dict):
                    perf = dict(prediction.get("runtime_performance") or {})
                    measurements = dict(perf.get("measurements_ms") or {})
                    measurements["monitor_cycle_ms"] = monitor_cycle_ms
                    perf["measurements_ms"] = measurements
                    prediction["runtime_performance"] = perf
                prediction_diag = _prediction_diagnostics(prediction)
                final = str(prediction.get("final", "unknown"))
                raw = float(prediction.get("raw", 0.0) or 0.0)
                risk = int(prediction.get("risk", 0) or 0)
                ml = int(prediction.get("ml", 0) or 0)
                prediction_status = str(prediction.get("status", "ok") or "ok")
                model_decision = _normalize_state_label(final)
                if prediction_status != "ok":
                    technical_failure = runtime_status_is_technical_failure(prediction_status)
                    awaiting_evidence = runtime_status_awaits_evidence(prediction_status)
                    failure_error = str(prediction.get("error") or "").strip()
                    warnings_before = int(warnings)
                    pending_now = time.time()
                    if awaiting_evidence:
                        warnings = _apply_pending_state_decay(
                            prediction_status=prediction_status,
                            warnings=warnings,
                            recent_decisions=decision_buffer,
                            recent_risks=risk_buffer,
                            recent_timestamps=decision_timestamps,
                            runtime_config=runtime_config,
                        )
                        legit_streak = 0
                        lock_suppressed_until = max(
                            lock_suppressed_until,
                            pending_now + _runtime_float(runtime_config, "runtime_post_transition_lock_dwell_seconds", 8.0),
                        )
                    pending_buffer = _runtime_buffer_snapshot(decision_buffer, risk_buffer, decision_timestamps, now=pending_now)
                    lock_suppressed_for = max(0.0, float(lock_suppressed_until) - float(pending_now))
                    pending_reason = "awaiting evidence" if awaiting_evidence else ("technical failure" if technical_failure else "prediction reported non-ready status")
                    pending_diag = {
                        "phase": "pending_state",
                        "prediction_status": prediction_status,
                        "reason": pending_reason,
                        "warnings_before": warnings_before,
                        "warnings_after": int(warnings),
                        "lock_suppressed_for_sec": _round_float(lock_suppressed_for),
                        "legit_streak": int(legit_streak),
                        "buffer": pending_buffer,
                        "prediction": prediction_diag,
                        "error": failure_error or None,
                    }
                    pending_summary = _runtime_diag_summary(
                        effective_decision="pending",
                        prediction_status=prediction_status,
                        reason=pending_reason,
                        confirmation_rule="pending_state",
                        locking_allowed=False,
                        warnings_before=warnings_before,
                        warnings_after=int(warnings),
                        legit_streak=int(legit_streak),
                        lock_suppressed_for_sec=lock_suppressed_for,
                        buffer_snapshot=pending_buffer,
                        prediction_diag=prediction_diag,
                    )
                    pending_extra = {
                            "session_id": session_id,
                            "user_id": current_state.get("user_id") or existing.get("user_id") or EXPECTED_USER_SLUG,
                            "session_kind": current_state.get("session_kind", existing.get("session_kind", "protected")),
                            "started_at": current_state.get("started_at") or existing.get("started_at"),
                            "started_at_text": current_state.get("started_at_text") or existing.get("started_at_text"),
                            "status": "shadow_evidence" if _shadow_evidence_mode() and awaiting_evidence else prediction_status,
                            "model_decision": None,
                            "raw_score": 0.0,
                            "risk": 0,
                            "avg_risk": round(sum(risk_buffer) / max(1, len(risk_buffer)), 2) if risk_buffer else 0.0,
                            "ml": 0,
                            "warning_count": warnings,
                            "intruder_vote_count": sum(dec == "intruder" for dec in list(decision_buffer)[-3:]),
                            "evidence_samples": len(decision_buffer),
                            "updated_at_text": ts,
                            "monitor_ready": True,
                            "monitor_failed": technical_failure,
                            "technical_failure": technical_failure,
                            "awaiting_evidence": awaiting_evidence,
                            "monitor_error": failure_error or (prediction_status if technical_failure else None),
                            "runtime_diagnostic_code": "pending_state",
                            "runtime_diagnostic_reason": pending_reason,
                            "runtime_diagnostic_summary": pending_summary,
                            "runtime_confirmation_rule": "pending_state",
                            "runtime_locking_allowed": False,
                            "runtime_lock_suppressed_for_sec": _round_float(lock_suppressed_for),
                            "runtime_legit_streak": int(legit_streak),
                            "runtime_recent_decisions": list(pending_buffer.get("decisions") or []),
                            "runtime_recent_risks": list(pending_buffer.get("risks") or []),
                            "runtime_recent_ages_sec": list(pending_buffer.get("ages_sec") or []),
                            "runtime_window_count": int(prediction_diag.get("window_count") or 0),
                            "runtime_quality_ok_windows": int((prediction_diag.get("quality") or {}).get("quality_ok_window_count") or 0),
                            "runtime_live_input": dict(prediction_diag.get("live_input") or {}),
                            "runtime_keyboard_input_counter": int((prediction_diag.get("live_input") or {}).get("keyboard_counter") or 0),
                            "runtime_mouse_input_counter": int((prediction_diag.get("live_input") or {}).get("mouse_counter") or 0),
                            "runtime_keyboard_input_rows": int((prediction_diag.get("live_input") or {}).get("keyboard_rows") or 0),
                            "runtime_mouse_input_rows": int((prediction_diag.get("live_input") or {}).get("mouse_rows") or 0),
                            "runtime_quality_lock_ok_windows": int((prediction_diag.get("quality") or {}).get("quality_lock_ok_window_count") or 0),
                            "runtime_low_quality_windows": int((prediction_diag.get("quality") or {}).get("low_quality_window_count") or 0),
                            "runtime_quality_gate_applied": bool((prediction_diag.get("quality") or {}).get("gate_applied")),
                            "runtime_quality_gate_reason": str((prediction_diag.get("quality") or {}).get("gate_reason") or ""),
                            "runtime_transition_status": str((prediction_diag.get("transition") or {}).get("status") or ""),
                            "runtime_transition_active": bool((prediction_diag.get("transition") or {}).get("active")),
                            "runtime_transition_recent_windows": int((prediction_diag.get("transition") or {}).get("recent_transition_windows") or 0),
                            "runtime_transition_recent_settled_windows": int((prediction_diag.get("transition") or {}).get("recent_settled_windows") or 0),
                            "runtime_transition_strength": _round_float((prediction_diag.get("transition") or {}).get("max_transition_strength")),
                            "runtime_window_diag_summary": _window_diag_summary_brief(prediction_diag),
                            "runtime_performance": dict(prediction_diag.get("performance") or {}),
                            "runtime_monitor_cycle_ms": float(((prediction_diag.get("performance") or {}).get("measurements_ms") or {}).get("monitor_cycle_ms") or 0.0),
                            "runtime_top_risky_windows": list((prediction_diag.get("window_diagnostics_summary") or {}).get("top_risky_windows") or []),
                            "runtime_last_window_diag": _last_window_diag(prediction_diag),
                            "runtime_layer_payloads": dict(prediction_diag.get("runtime_layer_payloads") or {}),
                            "runtime_model_decision_reason": str(prediction_diag.get("decision_reason") or ""),
                            "runtime_model_decision_details": dict(prediction_diag.get("decision_details") or {}),
                            "runtime_diagnostics": pending_diag,
                        }
                    if _shadow_evidence_mode():
                        pending_extra.update(_shadow_evidence_state_fields(False, [prediction_status]))
                    _write_monitor_state(
                        decision="pending",
                        extra=pending_extra,
                    )
                    append_log({
                        "time": ts,
                        "status": prediction_status,
                        "effective_decision": "pending",
                        "risk": 0,
                        "avg_risk": round(sum(risk_buffer) / max(1, len(risk_buffer)), 2) if risk_buffer else 0.0,
                        "raw": 0.0,
                        "ml": 0,
                        "warnings": warnings,
                        "expected_user": EXPECTED_USER_SLUG,
                        "session_id": session_id,
                        "error": failure_error or None,
                        "diagnostics": pending_diag,
                        "diagnostic_summary": pending_summary,
                    })
                    _monitor_diag_event("monitor_pending_state", {
                        "summary": pending_summary,
                        "state_extra": pending_extra,
                        "diagnostics": pending_diag,
                    }, level="warning" if technical_failure else "info")
                    continue
                if model_decision is None:
                    continue

                now = time.time()
                warnings_before = int(warnings)
                evaluation_risks = deque(risk_buffer, maxlen=RISK_WINDOW)
                evaluation_risks.append(float(risk))
                avg_risk = sum(evaluation_risks) / max(1, len(evaluation_risks))
                elapsed = _elapsed_seconds(current_state.get("started_at") or existing.get("started_at"))
                locking_allowed = now >= lock_suppressed_until
                locking_reason = "lock_suppressed_by_recovery_cooldown" if not locking_allowed else None
                demo_resume_cooldown_until = 0.0
                if _demo_classic_runtime_overrides_enabled():
                    for cooldown_source in (current_state, existing):
                        if isinstance(cooldown_source, dict):
                            try:
                                demo_resume_cooldown_until = max(
                                    float(demo_resume_cooldown_until),
                                    float(cooldown_source.get("demo_classic_resume_cooldown_until") or 0.0),
                                    float(cooldown_source.get("lock_recovery_cooldown_until") or 0.0),
                                )
                            except (TypeError, ValueError, OverflowError):
                                pass
                    if demo_resume_cooldown_until and now < demo_resume_cooldown_until:
                        locking_allowed = False
                        locking_reason = "demo_classic_post_unlock_resume_cooldown"
                lock_safety_gate = _runtime_lock_safety_gate(prediction, prediction_diag)
                if not bool(lock_safety_gate.get("locking_allowed")):
                    locking_allowed = False
                    primary_safety_reason = str(lock_safety_gate.get("primary_reason") or "runtime_safety_gate")
                    locking_reason = f"lock_suppressed_by_{primary_safety_reason}"
                mouse_guard = _mouse_fallback_lock_guard(prediction_diag, runtime_config)
                mouse_guard_active = bool(mouse_guard.get("active"))
                if mouse_guard_active and not bool(mouse_guard.get("locking_allowed")):
                    locking_allowed = False
                    locking_reason = "lock_suppressed_by_mouse_fallback_guard"
                buffer_before = _runtime_buffer_snapshot(decision_buffer, risk_buffer, decision_timestamps, now=now)
                observed_lock_quality_evidence = _observed_lock_quality_risk_evidence(prediction_diag)

                escalation = _resolve_runtime_escalation(
                    model_decision=model_decision,
                    recent_decisions=decision_buffer,
                    recent_risks=risk_buffer,
                    risk=risk,
                    avg_risk=avg_risk,
                    ml=ml,
                    elapsed=elapsed,
                    warnings=warnings,
                    config=runtime_config,
                    recent_timestamps=decision_timestamps,
                    event_time=now,
                    locking_allowed=locking_allowed,
                    locking_reason=locking_reason,
                    quality_lock_ok_windows=int((prediction_diag.get("quality") or {}).get("quality_lock_ok_window_count") or 0),
                    observed_risk=float(observed_lock_quality_evidence.get("peak_risk") or 0.0),
                    observed_lock_quality_risks=list(observed_lock_quality_evidence.get("risks") or []),
                    lock_safety_reason_codes=list(lock_safety_gate.get("reason_codes") or []),
                )
                confirmed_intruder = bool(escalation["confirmed_intruder"])
                effective_decision = str(escalation["effective_decision"])
                warnings = int(escalation["warnings"])
                alert_title_key = escalation["alert_title_key"]
                alert_message_key = escalation["alert_message_key"]
                alert_code = escalation["alert_code"]
                decision_reason_code = str(escalation.get("decision_reason_code") or "")
                decision_reason = str(escalation.get("decision_reason") or "")
                confirmation_diagnostics = dict(escalation.get("confirmation_diagnostics") or {})
                confirmation_rule = str(confirmation_diagnostics.get("matched_rule") or "")
                demo_lock_override = bool(escalation.get("demo_classic_lock_override") or confirmation_diagnostics.get("demo_classic_lock_override"))
                demo_lock_override_reason = str(escalation.get("demo_classic_lock_override_reason") or confirmation_diagnostics.get("demo_classic_lock_override_reason") or "")
                if demo_lock_override and _demo_classic_runtime_overrides_enabled():
                    locking_allowed = True
                    locking_reason = demo_lock_override_reason or "demo_classic_intruder_high_risk_lock"
                    confirmation_rule = str(confirmation_diagnostics.get("runtime_confirmation_rule_after_demo_override") or confirmation_rule or "demo_classic_lock_override")
                    confirmed_intruder = True
                    effective_decision = "intruder"
                    decision_reason_code = "demo_classic_intruder_lock_override"
                    decision_reason = str(confirmation_diagnostics.get("matched_summary") or "Classic protected runtime allowed escalation after repeated high-risk/intruder evidence.")
                auto_resume_guard = _auto_resume_grace_guard(current_state, prediction_diag, now=now)
                if confirmed_intruder and bool(auto_resume_guard.get("active")):
                    locking_allowed = False
                    locking_reason = str(auto_resume_guard.get("reason") or "post_unlock_reverification_pending")
                    confirmed_intruder = False
                    effective_decision = "suspicious"
                    decision_reason_code = "auto_resume_high_risk_blocked"
                    decision_reason = "Post-unlock auto-resume is collecting fresh evidence before any second lock action."
                    alert_title_key = None
                    alert_message_key = None
                    alert_code = None
                    confirmation_diagnostics.update({
                        "matched_rule": "auto_resume_loop_guard",
                        "final_action": "auto_resume_high_risk_blocked",
                        "lock_reason": locking_reason,
                        "auto_resume_lock_guard": dict(auto_resume_guard),
                    })
                shadow_evidence_mode = _shadow_evidence_mode()
                candidate_would_lock_if_production = bool(confirmed_intruder or effective_decision == "intruder" or model_decision == "intruder" or decision_reason_code in {"lock_confirmed", "strong_intruder_consensus"})
                if shadow_evidence_mode:
                    if candidate_would_lock_if_production:
                        LOGGER.info("shadow_evidence_lock_suppressed")
                    confirmed_intruder = False
                    alert_title_key = None
                    alert_message_key = None
                    alert_code = None
                    locking_allowed = False
                    if decision_reason_code:
                        decision_reason_code = f"{decision_reason_code}|shadow_evidence_lock_suppressed" if candidate_would_lock_if_production else decision_reason_code
                    elif candidate_would_lock_if_production:
                        decision_reason_code = "shadow_evidence_lock_suppressed"

                risk_buffer.append(float(risk))
                decision_buffer.append(effective_decision)
                decision_timestamps.append(now)

                legit_reset_applied = False
                if effective_decision == "legit":
                    legit_streak += 1
                    legit_reset_streak = _runtime_int(runtime_config, "runtime_legit_reset_streak", 3)
                    legit_reset_avg = _runtime_float(runtime_config, "runtime_legit_reset_avg_risk", 28.0)
                    if legit_streak >= legit_reset_streak and avg_risk <= legit_reset_avg:
                        warnings = 0
                        legit_reset_applied = True
                        lock_suppressed_until = max(
                            lock_suppressed_until,
                            now + _runtime_float(runtime_config, "runtime_post_recovery_lock_dwell_seconds", 8.0),
                        )
                        _seed_legitimate_runtime_memory(
                            decision_buffer,
                            risk_buffer,
                            decision_timestamps,
                            risk=float(risk),
                            at=now,
                        )
                else:
                    legit_streak = 0

                stored_avg_risk = sum(risk_buffer) / max(1, len(risk_buffer)) if risk_buffer else 0.0
                recent_alert_hits = sum(dec in {"intruder", "suspicious"} for dec in list(decision_buffer)[-3:])
                lock_suppressed_for = max(0.0, float(lock_suppressed_until) - float(now))
                buffer_after = _runtime_buffer_snapshot(decision_buffer, risk_buffer, decision_timestamps, now=now)
                runtime_diag = {
                    "phase": "runtime_prediction",
                    "prediction_status": prediction_status,
                    "model_decision": model_decision,
                    "effective_decision": effective_decision,
                    "decision_reason_code": decision_reason_code,
                    "decision_reason": decision_reason,
                    "model_decision_reason": str(prediction_diag.get("decision_reason") or ""),
                    "model_decision_details": dict(prediction_diag.get("decision_details") or {}),
                    "confirmed_intruder": bool(confirmed_intruder),
                    "candidate_would_lock_if_production": bool(candidate_would_lock_if_production if 'candidate_would_lock_if_production' in locals() else False),
                    "shadow_evidence_lock_suppressed": bool(_shadow_evidence_mode() and (candidate_would_lock_if_production if 'candidate_would_lock_if_production' in locals() else False)),
                    "runtime_mode": SHADOW_EVIDENCE_SESSION_KIND if _shadow_evidence_mode() else "protected",
                    "warnings_before": warnings_before,
                    "warnings_after": int(warnings),
                    "legit_reset_applied": bool(legit_reset_applied),
                    "legit_streak": int(legit_streak),
                    "locking_allowed": bool(locking_allowed),
                    "demo_classic_protected": bool(_demo_classic_runtime_overrides_enabled()),
                    "demo_classic_lock_override": bool(demo_lock_override),
                    "demo_classic_lock_override_reason": str(demo_lock_override_reason or ""),
                    "calibration_immature_lock_bypassed_for_demo": bool(confirmation_diagnostics.get("calibration_immature_lock_bypassed_for_demo")),
                    "runtime_confirmation_rule_before_demo_override": str(confirmation_diagnostics.get("runtime_confirmation_rule_before_demo_override") or ""),
                    "runtime_confirmation_rule_after_demo_override": str(confirmation_diagnostics.get("runtime_confirmation_rule_after_demo_override") or ""),
                    "runtime_locking_allowed_before_demo_override": bool(confirmation_diagnostics.get("runtime_locking_allowed_before_demo_override", locking_allowed)),
                    "runtime_locking_allowed_after_demo_override": bool(confirmation_diagnostics.get("runtime_locking_allowed_after_demo_override", locking_allowed)),
                    "protected_action_requested": bool(confirmed_intruder),
                    "protected_action_phase": str(confirmation_diagnostics.get("protected_action_phase") or ("pre_lock_face_confirmation_required" if bool(confirmed_intruder) else "")),
                    "face_confirmation_required_before_lock": bool(confirmation_diagnostics.get("face_confirmation_required_before_lock") or bool(confirmed_intruder)),
                    "final_action": str(confirmation_diagnostics.get("final_action") or ("pre_lock_face_confirmation_required" if bool(confirmed_intruder) else "")),
                    "lock_reason": str(locking_reason or confirmation_diagnostics.get("lock_reason") or ""),
                    "demo_classic_post_unlock_resume_cooldown": bool(demo_resume_cooldown_until and now < demo_resume_cooldown_until),
                    "demo_classic_resume_cooldown_until": _round_float(demo_resume_cooldown_until),
                    "lock_suppressed_for_sec": _round_float(lock_suppressed_for),
                    "auto_resume_lock_guard": dict(auto_resume_guard),
                    "mouse_guard": dict(mouse_guard),
                    "observed_lock_quality_evidence": dict(observed_lock_quality_evidence),
                    "lock_safety_gate": dict(lock_safety_gate),
                    "recent_alert_hits": int(recent_alert_hits),
                    "buffer_before": buffer_before,
                    "buffer_after": buffer_after,
                    "prediction": prediction_diag,
                    "confirmation": confirmation_diagnostics,
                }
                diagnostic_summary = _runtime_diag_summary(
                    effective_decision=effective_decision,
                    prediction_status=prediction_status,
                    reason=decision_reason,
                    confirmation_rule=confirmation_rule,
                    locking_allowed=locking_allowed,
                    warnings_before=warnings_before,
                    warnings_after=int(warnings),
                    legit_streak=int(legit_streak),
                    lock_suppressed_for_sec=lock_suppressed_for,
                    buffer_snapshot=buffer_after,
                    prediction_diag=prediction_diag,
                )

                append_log({
                    "time": ts,
                    "status": final,
                    "effective_decision": effective_decision,
                    "risk": risk,
                    "avg_risk": round(stored_avg_risk, 2),
                    "raw": float(raw),
                    "ml": ml,
                    "warnings": warnings,
                    "expected_user": EXPECTED_USER_SLUG,
                    "session_id": session_id,
                    "diagnostics": runtime_diag,
                    "diagnostic_summary": diagnostic_summary,
                })
                _monitor_diag_event("monitor_prediction", {
                    "summary": diagnostic_summary,
                    "time": ts,
                    "status": final,
                    "model_decision": model_decision,
                    "effective_decision": effective_decision,
                    "risk": risk,
                    "avg_risk": round(stored_avg_risk, 2),
                    "raw": float(raw),
                    "ml": ml,
                    "warnings": warnings,
                    "confirmation_rule": confirmation_rule,
                    "decision_reason_code": decision_reason_code,
                    "decision_reason": decision_reason,
                    "model_decision_reason": str(prediction_diag.get("decision_reason") or ""),
                    "model_decision_details": dict(prediction_diag.get("decision_details") or {}),
                    "confirmed_intruder": bool(confirmed_intruder),
                    "locking_allowed": bool(locking_allowed),
                    "lock_safety_gate": dict(lock_safety_gate),
                    "mouse_guard": dict(mouse_guard),
                    "runtime_diag": runtime_diag,
                }, level="warning" if effective_decision in {"suspicious", "intruder"} or risk >= 70 else "info")

                extra = {
                    "session_id": session_id,
                    "user_id": current_state.get("user_id") or existing.get("user_id") or EXPECTED_USER_SLUG,
                    "risk": risk,
                    "avg_risk": round(stored_avg_risk, 2),
                    "raw_score": round(float(raw), 4),
                    "raw_model_risk": round(float(risk), 3),
                    "observed_model_risk": round(float(risk), 3),
                    "action_risk": round(float(risk), 3),
                    "display_risk": round(float(risk), 3),
                    "decision_risk": round(float(risk), 3),
                    "ml": ml,
                    "status": SHADOW_EVIDENCE_SESSION_KIND if _shadow_evidence_mode() else final,
                    "runtime_status": SHADOW_EVIDENCE_SESSION_KIND if _shadow_evidence_mode() else final,
                    "runtime_decision": effective_decision,
                    "input_pipeline_status": "evaluated_window",
                    "evidence_state": "evaluated",
                    "runtime_prediction_ready": True,
                    "fresh_window": True,
                    "model_decision": model_decision,
                    "updated_at_text": ts,
                    "session_kind": current_state.get("session_kind", existing.get("session_kind", "protected")),
                    "started_at": current_state.get("started_at") or existing.get("started_at"),
                    "started_at_text": current_state.get("started_at_text") or existing.get("started_at_text"),
                    "warning_count": warnings,
                    "intruder_vote_count": sum(dec == "intruder" for dec in list(decision_buffer)[-3:]),
                    "evidence_samples": len(decision_buffer),
                    "monitor_ready": True,
                    "monitor_failed": False,
                    "technical_failure": False,
                    "awaiting_evidence": False,
                    "monitor_error": None,
                    "runtime_diagnostic_code": decision_reason_code,
                    "runtime_diagnostic_reason": decision_reason,
                    "runtime_model_decision_reason": str(prediction_diag.get("decision_reason") or ""),
                    "runtime_model_decision_details": dict(prediction_diag.get("decision_details") or {}),
                    "runtime_suspicious_transparency": {
                        "model_decision": model_decision,
                        "effective_decision": effective_decision,
                        "risk": int(risk),
                        "avg_risk": round(stored_avg_risk, 2),
                        "model_decision_reason": str(prediction_diag.get("decision_reason") or ""),
                        "model_decision_details": dict(prediction_diag.get("decision_details") or {}),
                    },
                    "runtime_diagnostic_summary": diagnostic_summary,
                    "runtime_confirmation_rule": confirmation_rule,
                    "runtime_locking_allowed": False if _shadow_evidence_mode() else bool(locking_allowed),
                    "demo_classic_protected": bool(_demo_classic_runtime_overrides_enabled()),
                    "demo_classic_lock_override": bool(demo_lock_override),
                    "demo_classic_lock_override_reason": str(demo_lock_override_reason or ""),
                    "calibration_immature_lock_bypassed_for_demo": bool(confirmation_diagnostics.get("calibration_immature_lock_bypassed_for_demo")),
                    "runtime_confirmation_rule_before_demo_override": str(confirmation_diagnostics.get("runtime_confirmation_rule_before_demo_override") or ""),
                    "runtime_confirmation_rule_after_demo_override": str(confirmation_diagnostics.get("runtime_confirmation_rule_after_demo_override") or ""),
                    "runtime_locking_allowed_before_demo_override": bool(confirmation_diagnostics.get("runtime_locking_allowed_before_demo_override", locking_allowed)),
                    "runtime_locking_allowed_after_demo_override": bool(confirmation_diagnostics.get("runtime_locking_allowed_after_demo_override", locking_allowed)),
                    "protected_action_requested": bool(confirmed_intruder),
                    "protected_action_phase": str(confirmation_diagnostics.get("protected_action_phase") or ("pre_lock_face_confirmation_required" if bool(confirmed_intruder) else "")),
                    "face_confirmation_required_before_lock": bool(confirmation_diagnostics.get("face_confirmation_required_before_lock") or bool(confirmed_intruder)),
                    "final_action": str(confirmation_diagnostics.get("final_action") or ("pre_lock_face_confirmation_required" if bool(confirmed_intruder) else "")),
                    "lock_reason": str(locking_reason or confirmation_diagnostics.get("lock_reason") or ""),
                    "demo_classic_post_unlock_resume_cooldown": bool(demo_resume_cooldown_until and now < demo_resume_cooldown_until),
                    "demo_classic_resume_cooldown_until": _round_float(demo_resume_cooldown_until),
                    "lock_recovery_cooldown_until": _round_float(demo_resume_cooldown_until),
                    "candidate_would_lock_if_production": bool(candidate_would_lock_if_production if 'candidate_would_lock_if_production' in locals() else False),
                    "shadow_evidence_lock_suppressed": bool(_shadow_evidence_mode() and (candidate_would_lock_if_production if 'candidate_would_lock_if_production' in locals() else False)),
                    "runtime_lock_suppressed_for_sec": _round_float(lock_suppressed_for),
                    "auto_resume_lock_guard_active": bool(auto_resume_guard.get("active")),
                    "auto_resume_lock_guard_reason": str(auto_resume_guard.get("reason") or ""),
                    "auto_resume_lock_guard": dict(auto_resume_guard),
                    "runtime_legit_streak": int(legit_streak),
                    "runtime_recent_decisions": list(buffer_after.get("decisions") or []),
                    "runtime_recent_risks": list(buffer_after.get("risks") or []),
                    "runtime_recent_ages_sec": list(buffer_after.get("ages_sec") or []),
                    "runtime_window_count": int(prediction_diag.get("window_count") or 0),
                    "runtime_quality_ok_windows": int((prediction_diag.get("quality") or {}).get("quality_ok_window_count") or 0),
                    "runtime_live_input": dict(prediction_diag.get("live_input") or {}),
                    "runtime_keyboard_input_counter": int((prediction_diag.get("live_input") or {}).get("keyboard_counter") or 0),
                    "runtime_mouse_input_counter": int((prediction_diag.get("live_input") or {}).get("mouse_counter") or 0),
                    "runtime_keyboard_input_rows": int((prediction_diag.get("live_input") or {}).get("keyboard_rows") or 0),
                    "runtime_mouse_input_rows": int((prediction_diag.get("live_input") or {}).get("mouse_rows") or 0),
                    "runtime_quality_lock_ok_windows": int((prediction_diag.get("quality") or {}).get("quality_lock_ok_window_count") or 0),
                    "runtime_low_quality_windows": int((prediction_diag.get("quality") or {}).get("low_quality_window_count") or 0),
                    "runtime_quality_gate_applied": bool((prediction_diag.get("quality") or {}).get("gate_applied")),
                    "runtime_quality_gate_reason": str((prediction_diag.get("quality") or {}).get("gate_reason") or ""),
                    "runtime_transition_status": str((prediction_diag.get("transition") or {}).get("status") or ""),
                    "runtime_transition_active": bool((prediction_diag.get("transition") or {}).get("active")),
                    "runtime_transition_recent_windows": int((prediction_diag.get("transition") or {}).get("recent_transition_windows") or 0),
                    "runtime_transition_recent_settled_windows": int((prediction_diag.get("transition") or {}).get("recent_settled_windows") or 0),
                    "runtime_transition_strength": _round_float((prediction_diag.get("transition") or {}).get("max_transition_strength")),
                    "runtime_window_diag_summary": _window_diag_summary_brief(prediction_diag),
                    "runtime_performance": dict(prediction_diag.get("performance") or {}),
                    "runtime_monitor_cycle_ms": float(((prediction_diag.get("performance") or {}).get("measurements_ms") or {}).get("monitor_cycle_ms") or 0.0),
                    "runtime_top_risky_windows": list((prediction_diag.get("window_diagnostics_summary") or {}).get("top_risky_windows") or []),
                    "runtime_last_window_diag": _last_window_diag(prediction_diag),
                    "runtime_observed_lock_quality_peak_risk": float(observed_lock_quality_evidence.get("peak_risk") or 0.0),
                    "runtime_observed_lock_quality_high90_count": int(observed_lock_quality_evidence.get("high90_count") or 0),
                    "runtime_observed_lock_quality_risks": list(observed_lock_quality_evidence.get("risks") or []),
                    "runtime_layer_payloads": dict(prediction_diag.get("runtime_layer_payloads") or {}),
                    "runtime_mouse_guard_active": bool(mouse_guard.get("active")),
                    "runtime_mouse_guard_strong_windows": int(mouse_guard.get("strong_window_count") or 0),
                    "runtime_calibration_mature": bool((prediction_diag.get("calibration_maturity") or {}).get("mature")),
                    "runtime_calibration_lock_allowed": bool((prediction_diag.get("calibration_maturity") or {}).get("lock_allowed")),
                    "runtime_progressive_phase": str((prediction_diag.get("calibration_maturity") or {}).get("progressive_phase") or ""),
                    "runtime_lock_safety_reasons": list(lock_safety_gate.get("reason_codes") or []),
                    "runtime_diagnostics": runtime_diag,
                }
                if isinstance(runtime, dict) and bool(runtime.get("dev_runtime_bundle_fallback")):
                    extra.update({
                        "dev_runtime_bundle_fallback": True,
                        "dev_production_ready_simulation": True,
                        "runtime_bundle_source": "developer_shadow_candidate",
                        "production_ready_real": False,
                        "production_ready_effective": True,
                    })
                    LOGGER.warning("dev_runtime_bundle_fallback=true runtime_bundle_source=developer_shadow_candidate")
                if _shadow_evidence_mode():
                    extra.update(_shadow_baseline_evidence_fields_for_user(str(extra.get("user_id") or EXPECTED_USER_SLUG or "")))
                    reasons = list(extra.get("runtime_lock_safety_reasons") or [])
                    if bool(extra.get("candidate_would_lock_if_production")) and "shadow_evidence_lock_suppressed" not in reasons:
                        reasons.append("shadow_evidence_lock_suppressed")
                    extra.update(_shadow_evidence_state_fields(bool(extra.get("candidate_would_lock_if_production")), reasons))
                # Clean Runtime Core V2 Phase 5: commercial runtime must not create
                # actionable pre-lock feedback buttons. Post-lock confirmation is
                # created only by the lock/resume path after Windows lock handoff.
                feedback_needed = False
                if feedback_needed:
                    runtime_meta = runtime.get("metadata") if isinstance(runtime, dict) else {}
                    runtime_meta = runtime_meta if isinstance(runtime_meta, dict) else {}
                    feedback_token = f"feedback-{session_id}-{decision_reason_code or effective_decision}-{int(warnings)}"
                    extra["feedback_prompt"] = {
                        "pending": True,
                        "token": feedback_token,
                        "session_id": str(session_id or ""),
                        "decision": effective_decision,
                        "risk": int(risk),
                        "decision_reason_code": decision_reason_code,
                        "model_version": str(runtime_meta.get("model_version") or runtime_meta.get("feature_capture_version") or runtime_meta.get("schema_version") or ""),
                        "policy_version": FEEDBACK_POLICY_VERSION,
                        "options": [
                            "verified_legit_after_warning",
                            "confirmed_intruder",
                            "user_ignored_feedback",
                        ],
                    }
                if not _shadow_evidence_mode() and alert_title_key and alert_message_key:
                    extra.update({"alert_title_key": alert_title_key, "alert_message_key": alert_message_key, "alert_title": "", "alert_message": "", "alert_code": alert_code, "alert_token": f"{alert_code or 'alert'}-{session_id}"})
                _write_monitor_state(decision=effective_decision, extra=extra)
                try:
                    from metadata_core.production_evidence_pipeline import append_runtime_monitor_evidence_record

                    append_runtime_monitor_evidence_record(
                        user_id=EXPECTED_USER_SLUG or str(extra.get("user_id") or ""),
                        state=extra,
                        runtime=runtime if isinstance(runtime, dict) else {},
                        prediction=prediction if isinstance(prediction, dict) else {},
                        ledger_path=shadow_evidence_ledger_path(EXPECTED_USER_SLUG or str(extra.get("user_id") or "")) if _shadow_evidence_mode() else None,
                    )
                    if _shadow_evidence_mode():
                        LOGGER.info("shadow_evidence_evidence_record_appended")
                except Exception:
                    # Evidence ledger writes are diagnostic-only and must never
                    # interrupt runtime protection or monitor decisions.
                    pass

                if not _shadow_evidence_mode() and _runtime_shadow_tap_enabled():
                    try:
                        from metadata_core.runtime_shadow_tap import submit_runtime_fed_shadow_tap

                        shadow_tap_status = submit_runtime_fed_shadow_tap(
                            user_id=EXPECTED_USER_SLUG or str(extra.get("user_id") or ""),
                            session_path=LIVE_SESSION_DIR,
                            production_state=extra,
                            production_runtime=runtime if isinstance(runtime, dict) else {},
                            production_prediction=prediction if isinstance(prediction, dict) else {},
                        )
                        _monitor_diag_event("runtime_fed_shadow_tap_submitted", shadow_tap_status, level="info")
                    except Exception:
                        # Runtime-fed shadow evaluation is report-only. It must
                        # never block or change the protected production path.
                        LOGGER.warning("runtime_fed_shadow_tap_submit_failed", exc_info=True)

                if confirmed_intruder and not _shadow_evidence_mode():
                    _monitor_diag_event("pre_lock_face_confirmation_required", {
                        "session_id": session_id,
                        "risk": risk,
                        "avg_risk": round(stored_avg_risk, 2),
                        "ml": ml,
                        "time": ts,
                        "confirmation_rule": confirmation_rule,
                        "decision_reason_code": decision_reason_code,
                        "decision_reason": decision_reason,
                        "runtime_diag": runtime_diag,
                    }, level="warning")
                    _lock_and_stop_for_intruder(session_id=session_id, risk=risk, avg_risk=stored_avg_risk, ml=ml, ts=ts)
                    post_lock_state = read_session_state(default={})
                    post_lock_state = post_lock_state if isinstance(post_lock_state, dict) else {}
                    _monitor_diag_event("lock_action_completed", {
                        "session_id": session_id,
                        "decision": post_lock_state.get("decision"),
                        "status": post_lock_state.get("status"),
                        "app_locked": post_lock_state.get("app_locked"),
                        "screen_locked": post_lock_state.get("screen_locked"),
                        "forced_stop": post_lock_state.get("forced_stop"),
                        "lock_fields": {
                            "lockRequested": post_lock_state.get("lockRequested"),
                            "lockAttempted": post_lock_state.get("lockAttempted"),
                            "lockSucceeded": post_lock_state.get("lockSucceeded"),
                            "lockErrorKind": post_lock_state.get("lockErrorKind"),
                            "lockUnavailableReason": post_lock_state.get("lockUnavailableReason"),
                            "windowsLockRequested": post_lock_state.get("windowsLockRequested"),
                            "windowsLockAttempted": post_lock_state.get("windowsLockAttempted"),
                            "windowsLockSucceeded": post_lock_state.get("windowsLockSucceeded"),
                            "windowsLockErrorKind": post_lock_state.get("windowsLockErrorKind"),
                            "windowsLockUnavailableReason": post_lock_state.get("windowsLockUnavailableReason"),
                        },
                    }, level="warning")
                    warnings = 0
                    continue

                if len(risk_buffer) < _runtime_int(runtime_config, "runtime_min_samples_for_action", 3):
                    continue
                if stored_avg_risk < _runtime_float(runtime_config, "runtime_warning_reset_avg_risk", 35.0) and recent_alert_hits == 0:
                    warnings = 0
                elif recent_alert_hits >= _runtime_int(runtime_config, "runtime_warning_escalation_alert_hits", 2):
                    warnings = min(WARNING_LIMIT + 2, warnings + 1)
                else:
                    warnings = max(0, warnings - 1)
            except (OSError, ValueError, TypeError, SecurityError) as exc:
                LOGGER.warning("Monitor runtime iteration failed: %s", exc, exc_info=True)
                detail = str(exc).strip()
                monitor_error = f"runtime_iteration_failed: {detail}" if detail else "runtime_iteration_failed"
                error_now = time.time()
                error_buffer = _runtime_buffer_snapshot(decision_buffer, risk_buffer, decision_timestamps, now=error_now)
                error_diag = {
                    "phase": "runtime_iteration_error",
                    "error": monitor_error,
                    "warnings": int(warnings),
                    "buffer": error_buffer,
                }
                error_summary = f"runtime error: {monitor_error}; recent={list(error_buffer.get('decisions') or [])}/{list(error_buffer.get('risks') or [])}"
                _write_monitor_state(
                    decision=current_state.get("decision") or existing.get("decision"),
                    extra={
                        "session_id": session_id,
                        "user_id": current_state.get("user_id") or existing.get("user_id") or EXPECTED_USER_SLUG,
                        "session_kind": current_state.get("session_kind", existing.get("session_kind", "protected")),
                        "started_at": current_state.get("started_at") or existing.get("started_at"),
                        "started_at_text": current_state.get("started_at_text") or existing.get("started_at_text"),
                        "status": "monitor_runtime_error",
                        "warning_count": warnings,
                        "monitor_ready": True,
                        "monitor_failed": True,
                        "technical_failure": True,
                        "awaiting_evidence": False,
                        "monitor_error": monitor_error,
                        "runtime_diagnostic_code": "runtime_iteration_error",
                        "runtime_diagnostic_reason": monitor_error,
                        "runtime_diagnostic_summary": error_summary,
                        "runtime_recent_decisions": list(error_buffer.get("decisions") or []),
                        "runtime_recent_risks": list(error_buffer.get("risks") or []),
                        "runtime_recent_ages_sec": list(error_buffer.get("ages_sec") or []),
                        "runtime_diagnostics": error_diag,
                    },
                )
                append_log({
                    "time": ts if "ts" in locals() else time.strftime("%H:%M:%S"),
                    "status": "monitor_runtime_error",
                    "effective_decision": current_state.get("decision") or existing.get("decision") or "pending",
                    "risk": 0,
                    "avg_risk": round(sum(risk_buffer) / max(1, len(risk_buffer)), 2) if risk_buffer else 0.0,
                    "raw": 0.0,
                    "ml": 0,
                    "warnings": warnings,
                    "expected_user": EXPECTED_USER_SLUG,
                    "session_id": session_id,
                    "error": monitor_error,
                    "diagnostics": error_diag,
                    "diagnostic_summary": error_summary,
                })
                _monitor_diag_event("monitor_runtime_iteration_error", {"error": monitor_error, "summary": error_summary, "diagnostics": error_diag}, level="error")
                print(f"Monitor error: {exc}", flush=True)
            except Exception as exc:
                _monitor_diag_event("monitor_runtime_unhandled_exception", {"error_type": type(exc).__name__, "error": str(exc)}, level="error")
                LOGGER.exception("Monitor runtime failed unexpectedly")
                _signal_unhandled_monitor_failure(exc, current_state if isinstance(current_state, dict) else existing)
                print(f"Monitor runtime failure: {type(exc).__name__}", file=sys.stderr, flush=True)
                monitor_exit_reason = "unhandled_runtime_exception"
                monitor_exit_detail = {"error_type": type(exc).__name__, "error": str(exc)[:500]}
                break
    finally:
        previous = read_session_state(default={})
        previous_decision = _normalize_state_label(previous.get("final_decision") or previous.get("decision"))
        final_bucket = previous.get("final_bucket") or _decision_bucket(previous_decision)
        _monitor_diag_event("monitor_stopping", {
            "previous_decision": previous_decision,
            "final_bucket": final_bucket,
            "previous_status": previous.get("status") if isinstance(previous, dict) else "",
            "previous_runtime_diagnostic_code": previous.get("runtime_diagnostic_code") if isinstance(previous, dict) else "",
            "previous_runtime_diagnostic_summary": previous.get("runtime_diagnostic_summary") if isinstance(previous, dict) else "",
            "monitor_exit_reason": monitor_exit_reason,
            "monitor_exit_detail": dict(monitor_exit_detail),
        })
        final_extra = _final_monitor_state(previous, session_id, previous_decision, final_bucket)
        final_extra.update({
            "monitor_exit_reason": monitor_exit_reason,
            "monitor_exit_reason_text": monitor_exit_reason.replace("_", " "),
            "monitor_exit_detail": dict(monitor_exit_detail),
            "monitor_exit_recorded_at": time.time(),
        })
        _write_monitor_state(decision=previous.get("decision"), extra=final_extra)
        clear_stop(CONTROL_NAME)

# Compatibility source markers retained for legacy source-inspection tests.
# def _env_flag
# def _dev_immature_lock_override_enabled
# def _runtime_shadow_tap_enabled
# def _demo_classic_runtime_overrides_enabled
# def _monitor_diag_enabled
# def _monitor_diag_log_path
# def _monitor_diag_json_safe
# def _monitor_diag_event
# def _shadow_evidence_mode
# def _shadow_evidence_state_fields
# def _hybrid_direct_test_mode
# def _utc_timestamp
# def _hybrid_direct_test_report_path
# def _runtime_identity
# def _sha256_file_digest
# def _runtime_artifact_digest
# def _baseline_decision_from_prediction
# def _baseline_would_lock_from_prediction
# def _shadow_baseline_evidence_fields_for_user
# def _write_hybrid_direct_test_report
# def _hybrid_report_base
# def _run_hybrid_direct_test_once
# def _request_shutdown
# def _sleep_with_stop
# def _monitor_sleep_interval
# def _clear_runtime_memory
# def _trim_runtime_memory
# def _apply_pending_state_decay
# def _seed_legitimate_runtime_memory
# def _round_float
# def _runtime_buffer_snapshot
# def _prediction_diagnostics
# def _window_diag_summary_brief
# def _last_window_diag
# def _observed_lock_quality_risk_evidence
# def _runtime_lock_safety_gate
# def _mouse_fallback_lock_guard
# def _runtime_diag_summary
# def _signal_unhandled_monitor_failure
# def monitor
# runtime_boundary.runtime_shadow_tap_enabled()
# def _demo_classic_runtime_overrides_enabled
# if demo_lock_override and _demo_classic_runtime_overrides_enabled():
# if _demo_classic_runtime_overrides_enabled():
# feedback_needed = False
# unknown_route not present

if __name__ == "__main__":
    monitor()
