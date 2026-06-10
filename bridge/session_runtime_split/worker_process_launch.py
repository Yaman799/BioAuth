"""Extracted implementation section for `bridge/session_runtime_helpers.py`."""
from __future__ import annotations
import json
import logging
import os
import re
import signal
import threading
import time
from collections import deque
from importlib import import_module
from typing import Any, Dict, List, Optional
from release_runtime import startup_protected_session_decision, write_release_runtime_event

def _hybrid_training_not_required_summary(self, *, report_path: Optional[str] = None) -> Dict[str, Any]:
    """Return the compatibility summary used by Train/Calibrate readiness."""
    if report_path is None:
        try:
            report_path = _hybrid_direct_test_report_path(self)
        except Exception:
            report_path = ""
    safe_user = _current_safe_user(self)
    profile_user = str((getattr(self, "_current_user", {}) or {}).get("user_id") or safe_user)
    return {
        "passed": True,
        "reason_code": "hybrid_test_not_required",
        "reason_codes": ["hybrid_test_not_required", "hybrid_direct_removed_from_commercial_flow"],
        "user": safe_user,
        "profile": profile_user,
        "report_path": str(report_path or ""),
        "hybrid_removed_from_commercial_flow": True,
        "hybrid_required_for_training": False,
        "training_sample_source": "normal_enrollment_archives_only",
        "shadow_evidence_training_allowed": False,
        "hybrid_report_training_allowed": False,
        "protected_sessions_unlock_allowed": False,
        "production_promotion_allowed": False,
        "active_runtime_pointer_write_allowed": False,
    }

def _hybrid_direct_test_result_payload(self, *, passed: bool, reason_codes: List[str], report_path: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "passed": bool(passed),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user": _current_safe_user(self),
        "profile": str((getattr(self, "_current_user", {}) or {}).get("user_id") or _current_safe_user(self)),
        "reason_codes": list(dict.fromkeys([str(code) for code in reason_codes if str(code or "").strip()])),
        "monitor": {
            "runtime_mode": HYBRID_DIRECT_TEST_SESSION_KIND,
            "source": HYBRID_DIRECT_TEST_SOURCE,
            "process_key": _hybrid_direct_test_process_key(self),
            "uses_shadow_monitor": False,
            "uses_production_monitor_executable": True,
            "test_only": True,
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
        "report_path": str(report_path or ""),
    }
    if isinstance(extra, dict):
        payload.update(extra)
    return payload

def _read_hybrid_direct_test_report(path: str) -> Dict[str, Any]:
    try:
        if not path or not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        LOGGER.debug("Failed reading Hybrid Direct Test report", exc_info=True)
        return {}

def _write_backend_hybrid_direct_test_report(self, payload: Dict[str, Any], path: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
    except Exception:
        LOGGER.debug("Failed writing backend Hybrid Direct Test result", exc_info=True)

def _normalize_hybrid_direct_test_report_safety(report: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Hybrid Direct Test reports as evidence-only, test-only payloads.

    The production monitor executable may be reused for measurement, but this
    report must never authorize lock, Face Confirmation, production approval,
    promotion, protected-session unlock, raw data export, or device influence.
    Unsafe truthy fields are preserved as failure evidence through reason codes
    while the normalized report remains fail-closed for UI/training gates.
    """

    payload = dict(report or {}) if isinstance(report, dict) else {}
    reason_codes = list(payload.get("reason_codes") or []) if isinstance(payload.get("reason_codes"), list) else []
    safety = dict(payload.get("safety") or {}) if isinstance(payload.get("safety"), dict) else {}
    unsafe_keys: List[str] = []
    for key in HYBRID_DIRECT_TEST_FALSE_SAFETY_KEYS:
        if bool(safety.get(key)):
            unsafe_keys.append(key)
        safety[key] = False
    payload["safety"] = safety

    monitor = dict(payload.get("monitor") or {}) if isinstance(payload.get("monitor"), dict) else {}
    if bool(monitor.get("device_influence_allowed")):
        unsafe_keys.append("monitor.device_influence_allowed")
    monitor.setdefault("runtime_mode", HYBRID_DIRECT_TEST_SESSION_KIND)
    monitor.setdefault("source", HYBRID_DIRECT_TEST_SOURCE)
    monitor["test_only"] = True
    monitor["device_influence_allowed"] = False
    payload["monitor"] = monitor

    if unsafe_keys:
        payload["passed"] = False
        reason_codes.append("hybrid_direct_unsafe_report_rejected")
        reason_codes.extend(f"unsafe_{key}" for key in unsafe_keys)
    for code in ("hybrid_direct_test_only", "device_influence_disabled", "face_confirmation_disabled"):
        if code not in reason_codes:
            reason_codes.append(code)
    payload["reason_codes"] = list(dict.fromkeys(str(code) for code in reason_codes if str(code or "").strip()))
    return payload

def latest_hybrid_direct_test_report(self) -> Dict[str, Any]:
    """Return the latest backend-owned Hybrid Direct Test report for this user.

    The report is evidence only. It never contributes training samples, production
    approval, promotion, or Protected Sessions unlock state.
    """

    cached = getattr(self, "_latest_hybrid_direct_test_result", {})
    if isinstance(cached, dict) and cached:
        return dict(cached)
    return _read_hybrid_direct_test_report(_hybrid_direct_test_report_path(self))

def _parse_hybrid_direct_timestamp(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return float(time.mktime(time.strptime(text, fmt)))
        except Exception:
            pass
    try:
        from datetime import datetime, timezone
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return float(parsed.timestamp())
    except Exception:
        return 0.0

def validate_hybrid_direct_test_evidence(self) -> Dict[str, Any]:
    """Validate the Hybrid Direct Test report as a training gate.

    This function validates pass/fail evidence only. It deliberately does not
    expose report rows as model training samples and does not alter production
    pointer, approval, promotion, or Protected Sessions readiness.
    """

    user = getattr(self, "_current_user", None)
    if not user:
        return {"ok": False, "reason_code": "no_authenticated_user", "report": {}, "summary": {"reason_code": "no_authenticated_user"}}
    report_path = _hybrid_direct_test_report_path(self)
    summary = _hybrid_training_not_required_summary(self, report_path=report_path)
    return {
        "ok": True,
        "reason_code": "hybrid_test_not_required",
        "report_path": report_path,
        "report": _hybrid_removed_from_commercial_flow_payload(self, report_path=report_path),
        "summary": summary,
    }
    safe_user = _current_safe_user(self)
    profile_user = str((user or {}).get("user_id") or safe_user)
    report_path = _hybrid_direct_test_report_path(self)
    report = latest_hybrid_direct_test_report(self)
    if not isinstance(report, dict) or not report:
        return {"ok": False, "reason_code": "hybrid_test_missing", "report_path": report_path, "report": {}, "summary": {"reason_code": "hybrid_test_missing", "report_path": report_path}}
    reason_codes = list(report.get("reason_codes") or []) if isinstance(report.get("reason_codes"), list) else []
    monitor = report.get("monitor") if isinstance(report.get("monitor"), dict) else {}
    safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
    report_user = str(report.get("user") or "").strip()
    report_profile = str(report.get("profile") or "").strip()
    if report_user and report_user != safe_user:
        return {"ok": False, "reason_code": "hybrid_test_wrong_user", "report_path": report_path, "report": report, "summary": {"reason_code": "hybrid_test_wrong_user", "report_user": report_user, "expected_user": safe_user}}
    if report_profile and report_profile not in {profile_user, safe_user}:
        return {"ok": False, "reason_code": "hybrid_test_wrong_user", "report_path": report_path, "report": report, "summary": {"reason_code": "hybrid_test_wrong_user", "report_profile": report_profile, "expected_profile": profile_user}}
    ts = _parse_hybrid_direct_timestamp(report.get("timestamp"))
    now = float(time.time())
    max_age = float(getattr(self, "_hybrid_direct_test_max_age_seconds", HYBRID_DIRECT_TEST_MAX_AGE_SECONDS) or HYBRID_DIRECT_TEST_MAX_AGE_SECONDS)
    if ts <= 0.0:
        return {"ok": False, "reason_code": "hybrid_test_malformed", "report_path": report_path, "report": report, "summary": {"reason_code": "hybrid_test_malformed", "field": "timestamp"}}
    if max_age > 0 and now - ts > max_age:
        return {"ok": False, "reason_code": "hybrid_test_stale", "report_path": report_path, "report": report, "summary": {"reason_code": "hybrid_test_stale", "age_seconds": max(0, int(now - ts)), "max_age_seconds": int(max_age)}}
    if bool(monitor.get("uses_shadow_monitor")) or str(monitor.get("process_key") or "").startswith("shadow_monitor_user_"):
        return {"ok": False, "reason_code": "hybrid_test_malformed", "report_path": report_path, "report": report, "summary": {"reason_code": "hybrid_test_malformed", "field": "monitor.shadow"}}
    if any(bool(safety.get(key)) for key in HYBRID_DIRECT_TEST_FALSE_SAFETY_KEYS):
        return {"ok": False, "reason_code": "hybrid_test_malformed", "report_path": report_path, "report": report, "summary": {"reason_code": "hybrid_test_malformed", "field": "safety"}}
    if not bool(report.get("passed")):
        return {"ok": False, "reason_code": "hybrid_test_failed", "report_path": report_path, "report": report, "summary": {"reason_code": "hybrid_test_failed", "reason_codes": reason_codes}}
    summary = {
        "reason_code": "hybrid_test_passed",
        "passed": True,
        "timestamp": str(report.get("timestamp") or ""),
        "user": safe_user,
        "profile": profile_user,
        "reason_codes": reason_codes,
        "monitor_runtime_mode": str(monitor.get("runtime_mode") or ""),
        "monitor_source": str(monitor.get("source") or ""),
        "process_key": str(monitor.get("process_key") or ""),
        "report_path": str(report.get("report_path") or report_path),
        "model_identity": report.get("model_identity") if isinstance(report.get("model_identity"), dict) else {},
        "training_sample_source": "normal_enrollment_archives_only",
        "production_promotion_allowed": False,
        "protected_sessions_unlock_allowed": False,
        "active_runtime_pointer_write_allowed": False,
    }
    return {"ok": True, "reason_code": "", "report_path": report_path, "report": report, "summary": summary}

def _hybrid_result_status_message(self, result: Dict[str, Any]) -> str:
    if bool(result.get("passed")):
        return "Hybrid Direct Test completed in safe test-only mode."
    codes = result.get("reason_codes") if isinstance(result, dict) else []
    if isinstance(codes, list) and codes:
        return "Hybrid Direct Test did not pass: " + ", ".join(str(code) for code in codes[:3])
    return "Hybrid Direct Test did not pass."

def _hybrid_direct_reports_dir() -> str:
    try:
        facade = _facade()
        return facade.os.path.join(facade.BASE_DIR, "reports", "hybrid_direct")
    except Exception:
        return os.path.abspath(os.path.join(os.getcwd(), "reports", "hybrid_direct"))

def _hybrid_live_session_eval_reports_dir() -> str:
    try:
        facade = _facade()
        return facade.os.path.join(facade.BASE_DIR, "reports", "hybrid_live_session_eval")
    except Exception:
        return os.path.abspath(os.path.join(os.getcwd(), "reports", "hybrid_live_session_eval"))
