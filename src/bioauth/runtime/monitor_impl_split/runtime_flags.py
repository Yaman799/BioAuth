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

def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}

def _dev_immature_lock_override_enabled() -> bool:
    """Allow calibration-maturity lock bypass only in explicit dev simulation.

    Requires both a dev build profile AND the specific dev env flags.
    Has no effect in production builds.
    """
    if not _DEV_OVERRIDES_ENABLED:
        return False
    return (
        _env_flag("BIOAUTH_DEV_ALLOW_IMMATURE_LOCK")
        and _env_flag("BIOAUTH_DEV_PRODUCTION_READY_SIMULATION")
    )

def _runtime_shadow_tap_enabled() -> bool:
    """Keep runtime-fed shadow reporting out of commercial protected mode by default."""
    return runtime_boundary.runtime_shadow_tap_enabled()

def _demo_classic_runtime_overrides_enabled() -> bool:
    """Demo lock/resume overrides are explicit demo-only behavior."""
    return runtime_boundary.demo_features_enabled() and bool(demo_classic_protected_enabled())

def _monitor_diag_enabled() -> bool:
    """Return true when the dev monitor JSONL diagnostics file is enabled.

    The diagnostics are intentionally opt-in and are intended for local testing.
    They record monitor decisions, safety-gate reasons, escalation decisions, and
    lock attempts. They do not include raw keyboard/mouse rows.
    """

    return _env_flag("BIOAUTH_MONITOR_VERBOSE_DIAGNOSTICS") or bool(os.environ.get("BIOAUTH_MONITOR_DIAGNOSTIC_LOG", "").strip())

def _monitor_diag_log_path() -> str:
    global _MONITOR_DIAG_LOG_PATH_CACHE
    if _MONITOR_DIAG_LOG_PATH_CACHE:
        return _MONITOR_DIAG_LOG_PATH_CACHE
    configured = os.environ.get("BIOAUTH_MONITOR_DIAGNOSTIC_LOG", "").strip()
    if configured:
        path = configured
    else:
        path = os.path.join(DATA_DIR, "dev_monitor_logs", f"monitor_diagnostics_{EXPECTED_USER_SLUG or 'user'}_{int(time.time())}.jsonl")
    path = os.path.abspath(path)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        pass
    _MONITOR_DIAG_LOG_PATH_CACHE = path
    return path

def _monitor_diag_json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "<max_depth>"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        safe: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            # Avoid accidentally logging bulky/raw payloads if future callers add them.
            if key_text.lower() in {"raw_rows", "raw_events", "keyboard_rows", "mouse_rows", "frame", "frames", "image", "images", "embedding", "template"}:
                safe[key_text] = "<omitted>"
                continue
            safe[key_text] = _monitor_diag_json_safe(item, depth=depth + 1)
        return safe
    if isinstance(value, (list, tuple, set, frozenset, deque)):
        return [_monitor_diag_json_safe(item, depth=depth + 1) for item in list(value)[:200]]
    try:
        return float(value)  # numpy/scalar compatibility without importing numpy.
    except Exception:
        return str(value)

def _monitor_diag_event(event: str, payload: Optional[Dict[str, Any]] = None, *, level: str = "info") -> None:
    if not _monitor_diag_enabled():
        return
    record = {
        "schema_version": "bioauth-dev-monitor-diagnostics-v1",
        "created_at": _utc_timestamp() if "_utc_timestamp" in globals() else datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "run_id": _MONITOR_DIAG_RUN_ID,
        "event": str(event or "monitor_event"),
        "level": str(level or "info"),
        "pid": os.getpid(),
        "expected_user": EXPECTED_USER_SLUG or EXPECTED_USER or "",
        "control_name": CONTROL_NAME,
        "runtime_mode": RUNTIME_MODE or (SHADOW_EVIDENCE_SESSION_KIND if SHADOW_EVIDENCE_ONLY else "protected"),
        "shadow_evidence_only": bool(SHADOW_EVIDENCE_ONLY),
        "hybrid_direct_test_mode": bool(HYBRID_DIRECT_TEST_MODE),
        "dev_production_ready_simulation": _env_flag("BIOAUTH_DEV_PRODUCTION_READY_SIMULATION"),
        "dev_allow_immature_lock": _env_flag("BIOAUTH_DEV_ALLOW_IMMATURE_LOCK"),
        "payload": _monitor_diag_json_safe(payload or {}),
    }
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    try:
        path = _monitor_diag_log_path()
        with _MONITOR_DIAG_LOCK:
            with open(path, "a", encoding="utf-8", errors="replace") as handle:
                handle.write(line + "\n")
    except Exception:
        # Diagnostics must never alter protection flow.
        pass

def _shadow_evidence_mode() -> bool:
    return bool(SHADOW_EVIDENCE_ONLY)

def _shadow_evidence_state_fields(candidate_would_lock: bool = False, reason_codes: Optional[List[str]] = None) -> Dict[str, Any]:
    codes = list(reason_codes or [])
    if candidate_would_lock and "shadow_evidence_lock_suppressed" not in codes:
        codes.append("shadow_evidence_lock_suppressed")
    return {
        "mode": SHADOW_EVIDENCE_SESSION_KIND,
        "runtime_mode": SHADOW_EVIDENCE_SESSION_KIND,
        "evidence_source": SHADOW_EVIDENCE_SOURCE,
        "source": SHADOW_EVIDENCE_SOURCE,
        "session_kind": SHADOW_EVIDENCE_SESSION_KIND,
        "trust_level": "shadow_runtime",
        "excluded_from_positive_training": True,
        "training_counts_toward_minimum": False,
        "metadata_trusted": False,
        "app_locked": False,
        "screen_locked": False,
        "forced_stop": False,
        "monitor_holding": False,
        "restriction_active": False,
        "candidate_would_lock_if_production": bool(candidate_would_lock),
        "shadow_evidence_lock_suppressed": bool(candidate_would_lock),
        "runtime_lock_safety_reasons": codes,
        "protected_sessions_available": False,
        "production_ready": False,
        "production_approval_allowed": False,
        "production_promotion_allowed": False,
        "production_pointer_write_allowed": False,
        "shadow_isolation_reason_code": "shadow_evidence_report_only_monitor",
    }

def _hybrid_direct_test_mode() -> bool:
    return bool(HYBRID_DIRECT_TEST_MODE)

def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _hybrid_direct_test_report_path() -> str:
    configured = os.environ.get("BIOAUTH_HYBRID_TEST_REPORT_PATH", "").strip()
    if configured:
        os.makedirs(os.path.dirname(configured), exist_ok=True)
        return configured
    safe_user = EXPECTED_USER_SLUG or slugify_username(EXPECTED_USER or "") or "user"
    out_dir = os.path.join(evidence_dir(), "hybrid_direct_test")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"hybrid_direct_test_report_{safe_user}.json")

def _runtime_identity(runtime: Any) -> Dict[str, Any]:
    meta = runtime.get("metadata") if isinstance(runtime, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    identity: Dict[str, Any] = {}
    for key in ("model_version", "schema_version", "feature_capture_version", "bundle_digest", "artifact_digest", "candidate_digest", "production_digest", "model_path", "metadata_path"):
        value = meta.get(key)
        if value not in (None, ""):
            identity[key] = str(value)
    return identity

def _sha256_file_digest(path: Any) -> str:
    text = str(path or "").strip()
    if not text or not os.path.isfile(text):
        return ""
    try:
        digest = hashlib.sha256()
        with open(text, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    except OSError:
        return ""

def _runtime_artifact_digest(runtime: Any) -> str:
    meta = runtime.get("metadata") if isinstance(runtime, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    for key in ("artifact_digest", "bundle_digest", "production_digest", "model_digest", "candidate_artifact_digest"):
        value = meta.get(key)
        if value not in (None, ""):
            return str(value)
    paths_payload = runtime.get("paths") if isinstance(runtime, dict) else {}
    paths_payload = paths_payload if isinstance(paths_payload, dict) else {}
    model_file = paths_payload.get("model")
    if not model_file and isinstance(runtime, dict):
        model_file = runtime.get("model_file")
    return _sha256_file_digest(model_file)

def _baseline_decision_from_prediction(prediction: Any) -> str:
    if not isinstance(prediction, dict):
        return ""
    final = str(prediction.get("final") or prediction.get("decision") or "").strip().lower()
    normalized = _normalize_state_label(final)
    if normalized == "legit":
        return "trusted"
    if normalized == "suspicious":
        return "warning"
    if normalized == "intruder" or final in {"lock", "locked", "intruder_lock", "device_locked"}:
        return "lock"
    return ""

def _baseline_would_lock_from_prediction(prediction: Any, decision: str) -> bool:
    if not isinstance(prediction, dict):
        return False
    final = str(prediction.get("final") or prediction.get("decision") or "").strip().lower()
    normalized = _normalize_state_label(final)
    return decision == "lock" or normalized == "intruder" or final in {"lock", "locked", "intruder_lock", "device_locked"}
