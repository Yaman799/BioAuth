from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import re
from pathlib import Path
from typing import Any, Dict

from app_settings import load_settings, settings_storage_metadata
from license_manager import evaluate_license
from paths import app_data_dir, data_dir, models_dir
from release_profile import profile_payload

SUPPORT_BUNDLE_SCHEMA_VERSION = 2
SUPPORT_BUNDLE_HEALTH_POLICY_VERSION = "commercial-core-07-support-diagnostics-v1"
RAW_FIELD_PATTERN = re.compile(r"(keyboard|mouse|raw|event_rows|feature_vector|password|passcode|secret|token|signature|recovery_code|license_code|private_key|passphrase|embedding|template_digest|source_frame_paths|raw_image_path)", re.I)

SETTINGS_ALLOWLIST = {
    "theme",
    "language",
    "run_on_startup",
    "risk_sensitivity",
    "monitor_interval_sec",
    "privacy_policy_version",
    "privacy_consent_policy_version",
    "incident_evidence_enabled",
    "incident_evidence_capture_screenshot",
    "incident_evidence_capture_webcam",
    "incident_evidence_retention_days",
    "face_template_consent_granted",
    "face_template_consent_policy_version",
    "remember_login_enabled",
    "app_passcode_enabled",
    "deep_runtime_mode",
    "deep_runtime_manual_override",
    "package_profile",
}

MODEL_METADATA_ALLOWLIST = {
    "schema_version",
    "runtime_schema_policy_version",
    "feature_schema_version",
    "feature_window_strategy",
    "model_version",
    "created_at",
    "training_started_at",
    "training_finished_at",
    "user_calibration",
    "calibration_maturity",
    "selected_runtime_mode",
    "runtime_mode",
    "model_family",
    "candidate_id",
    "policy_version",
    "promotion_policy_version",
    "safety_metrics",
}

RUNTIME_STATE_ALLOWLIST = {
    "status",
    "active",
    "flow",
    "decision",
    "decisionText",
    "statusTone",
    "runtime_diagnostic_code",
    "runtime_diagnostic_reason",
    "runtime_diagnostic_summary",
    "runtime_confirmation_rule",
    "runtime_locking_allowed",
    "warning_count",
    "runtime_window_diag_summary",
    "runtime_performance",
    "runtime_monitor_cycle_ms",
    "monitor_failed",
    "monitor_ready",
    "monitor_exit_code",
    "monitor_startup_error_kind",
    "logger_failed",
    "logger_ready",
    "protected_failure_reason",
    "runtime_window_count",
    "runtime_quality_ok_windows",
    "quality_score",
    "quality_ok",
    "quality_reason_codes",
}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def support_bundle_dir() -> Path:
    path = Path(data_dir()) / "support_bundles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _allowlist_dict(payload: Dict[str, Any] | None, allowed: set[str]) -> Dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    clean: Dict[str, Any] = {}
    for key in sorted(allowed):
        if key in source:
            clean[key] = _json_safe(source.get(key))
    return clean


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items() if not RAW_FIELD_PATTERN.search(str(k))}
    if isinstance(value, list):
        return [_json_safe(v) for v in value[:50]]
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _read_model_metadata(user_id: str | None = None) -> Dict[str, Any]:
    candidates = []
    if user_id:
        candidates.append(Path(models_dir()) / str(user_id) / "production" / "metadata.json")
        candidates.append(Path(models_dir()) / str(user_id) / "metadata.json")
    candidates.append(Path(models_dir()) / "metadata.json")
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8") or "{}")
            if isinstance(payload, dict):
                return _allowlist_dict(payload, MODEL_METADATA_ALLOWLIST)
        except Exception:
            continue
    return {}


def _last_errors() -> list[Dict[str, Any]]:
    # Allowlist-only local diagnostics. Do not read raw session CSV or encrypted monitor payloads.
    errors_path = Path(data_dir()) / "last_errors.json"
    try:
        payload = json.loads(errors_path.read_text(encoding="utf-8") or "[]")
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    clean: list[Dict[str, Any]] = []
    for item in payload[-20:]:
        if not isinstance(item, dict):
            continue
        clean.append(_allowlist_dict(item, {"timestamp", "component", "code", "message", "severity"}))
    return clean




# Commercial-Core-07 support diagnostics are intentionally allowlist-based and
# read-only.  These helpers may inspect JSON control/health files, but they must
# never read raw keyboard/mouse logs, face images, model tensors, or encrypted
# session payloads.  The output is designed for a support bundle that can be sent
# to a developer without exposing typed text, mouse streams, templates, secrets,
# or biometric samples.
_DIAGNOSTIC_JSON_MAX_BYTES = 512 * 1024
_DIAGNOSTIC_TEXT_MAX_CHARS = 240


def _redact_text(value: Any) -> str:
    text = "" if value is None else str(value)
    # Keep diagnostics useful while removing common secret-bearing fragments.
    text = re.sub(r"(?i)(?:access[_-]?token|refresh[_-]?token|api[_-]?secret|token|secret|password|passcode|recovery[_-]?code|license[_-]?code|private[_-]?key|passphrase)=([^\s;&]+)", "credential=<redacted>", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", "bearer <redacted>", text)
    if len(text) > _DIAGNOSTIC_TEXT_MAX_CHARS:
        return text[:_DIAGNOSTIC_TEXT_MAX_CHARS] + "…"
    return text


def _path_metadata(path: str | os.PathLike[str] | None) -> Dict[str, Any]:
    path_obj = Path(path) if path else Path("")
    try:
        stat = path_obj.stat()
        return {
            "exists": True,
            "size_bytes": int(stat.st_size),
            "modified_at": _dt.datetime.fromtimestamp(stat.st_mtime, _dt.timezone.utc).replace(microsecond=0).isoformat(),
            "age_sec": max(0.0, round(_dt.datetime.now(_dt.timezone.utc).timestamp() - float(stat.st_mtime), 3)),
        }
    except Exception:
        return {"exists": False, "size_bytes": 0, "modified_at": "", "age_sec": None}


def _read_json_object(path: str | os.PathLike[str] | None) -> Dict[str, Any]:
    path_obj = Path(path) if path else Path("")
    try:
        if not path_obj.exists() or path_obj.stat().st_size > _DIAGNOSTIC_JSON_MAX_BYTES:
            return {}
        payload = json.loads(path_obj.read_text(encoding="utf-8") or "{}")
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _jsonl_tail_count(path: str | os.PathLike[str] | None, *, max_lines: int = 5) -> Dict[str, Any]:
    path_obj = Path(path) if path else Path("")
    meta = _path_metadata(path_obj)
    out: Dict[str, Any] = {"file": meta, "line_count_sampled": 0, "latest_records": []}
    if not meta.get("exists"):
        return out
    try:
        # Keep this bounded.  Evidence ledgers are append-only and may rotate.
        with path_obj.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 128 * 1024), os.SEEK_SET)
            raw = handle.read().decode("utf-8", "replace")
        lines = [line for line in raw.splitlines() if line.strip()]
        latest = []
        for line in lines[-max_lines:]:
            try:
                item = json.loads(line)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            latest.append(_allowlist_dict(item, {
                "schema_version",
                "shadow_ledger_schema_version",
                "ledger_kind",
                "ledger_record_kind",
                "event_source",
                "evidence_source",
                "user_id",
                "candidate_digest_match",
                "feature_schema_contract_version",
                "window_schema_version",
                "candidate_would_lock_if_production",
                "shadow_evidence_lock_suppressed",
                "post_lock_feedback_label",
                "face_feedback_label",
                "written_at",
                "timestamp",
                "created_at",
            }))
        out["line_count_sampled"] = len(lines)
        out["latest_records"] = latest
    except Exception as exc:
        out["read_error"] = _redact_text(exc)
    return out


def _control_file_diagnostics() -> Dict[str, Any]:
    try:
        import control as _control
    except Exception as exc:
        return {"available": False, "error": _redact_text(exc)}

    control_path = Path(getattr(_control, "CONTROL_DIR", Path(data_dir()) / "control"))
    session_path = Path(getattr(_control, "SESSION_STATE_FILE", control_path / "session_state.json"))
    lock_path = Path(str(session_path) + ".lock")
    runtime_summary_path = control_path / "runtime_summary.json"

    try:
        lock_info = _control.inspect_session_state_lock()
    except Exception as exc:
        lock_info = {"error": _redact_text(exc)}
    try:
        state_issue = _control.session_state_diagnostics()
    except Exception as exc:
        state_issue = {"error": _redact_text(exc)}

    quarantine_dir = control_path / "quarantine"
    quarantine_count = 0
    latest_quarantine = None
    try:
        quarantined = sorted([item for item in quarantine_dir.glob("session_state_*.json") if item.is_file()], key=lambda item: item.stat().st_mtime, reverse=True)
        quarantine_count = len(quarantined)
        latest_quarantine = _path_metadata(quarantined[0]) if quarantined else None
    except Exception:
        quarantine_count = 0
        latest_quarantine = None

    summary_payload = _read_json_object(runtime_summary_path)
    runtime_summary = _allowlist_dict(summary_payload, {
        "status",
        "active",
        "flow",
        "runtime_status",
        "runtime_ready",
        "runtime_prediction_ready",
        "runtime_diagnostic_code",
        "runtime_diagnostic_reason",
        "runtime_diagnostic_summary",
        "protected_sessions_available",
        "candidate_status",
        "production_approval_status",
        "production_approval_reason_code",
        "shadow_evidence_monitor_blocked",
        "shadow_evidence_monitor_enabled",
        "shadow_report_only_enabled",
        "feature_schema_contract_version",
        "window_schema_version",
    })

    return {
        "available": True,
        "control_dir": {"exists": control_path.exists()},
        "session_state": _path_metadata(session_path),
        "session_state_lock": _json_safe(lock_info),
        "session_state_issue": _json_safe(state_issue),
        "runtime_summary": {
            "file": _path_metadata(runtime_summary_path),
            "summary": runtime_summary,
        },
        "quarantine": {
            "count": quarantine_count,
            "latest": latest_quarantine or {},
        },
    }


def _shadow_diagnostics(user_id: str | None = None) -> Dict[str, Any]:
    safe_user = str(user_id or "").strip()
    if not safe_user:
        return {"available": False, "reason": "no_user_id"}
    try:
        from shadow_core.background_contracts import shadow_evidence_paths
    except Exception as exc:
        return {"available": False, "reason": "contracts_unavailable", "error": _redact_text(exc)}

    paths = shadow_evidence_paths(safe_user)
    state_payload = _read_json_object(paths.get("state"))
    report_payload = _read_json_object(paths.get("eval_report"))
    gate_payload = _read_json_object(paths.get("gate_result"))
    ledger_summary = _jsonl_tail_count(paths.get("ledger"), max_lines=5)

    return {
        "available": True,
        "mode": "report_only_runtime_fed_default",
        "independent_monitor_default_enabled": False,
        "developer_enable_env": "BIOAUTH_ENABLE_SHADOW_EVIDENCE_MONITOR",
        "paths": {name: _path_metadata(path) for name, path in paths.items()},
        "state": _allowlist_dict(state_payload, {
            "active",
            "session_kind",
            "runtime_mode",
            "status",
            "phase",
            "candidate_status",
            "developer_shadow_paused",
            "shadow_evidence_monitor_enabled",
            "shadow_report_only_enabled",
            "last_error",
            "updated_at",
            "created_at",
        }),
        "eval_report": _allowlist_dict(report_payload, {
            "schema_version",
            "shadow_ledger_schema_version",
            "policy_version",
            "user_id",
            "record_count",
            "valid_record_count",
            "invalid_record_count",
            "privacy_safe",
            "latest_record_kind",
            "candidate_would_lock_count",
            "candidate_lock_suppressed_count",
            "post_lock_feedback_count",
            "face_feedback_count",
            "created_at",
            "updated_at",
        }),
        "gate_result": _allowlist_dict(gate_payload, {
            "status",
            "eligible",
            "candidate_status",
            "promotion_effect",
            "reason_code",
            "reason_codes",
            "weighted_score",
            "guardrails_passed",
            "candidate_digest_match",
            "feature_schema_match",
            "window_schema_match",
            "created_at",
            "updated_at",
        }),
        "ledger": ledger_summary,
    }


def _process_diagnostics() -> Dict[str, Any]:
    entries: list[Dict[str, Any]] = []
    try:
        import psutil  # type: ignore
        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "create_time"]):
            try:
                info = proc.info
                cmdline = " ".join(info.get("cmdline") or [])
                haystack = " ".join([str(info.get("name") or ""), str(info.get("exe") or ""), cmdline]).lower()
                if not any(term in haystack for term in ("bioauth", "desktop_app", "logger.py", "monitor.py", "start_app")):
                    continue
                entries.append({
                    "pid": int(info.get("pid") or 0),
                    "name": _redact_text(info.get("name")),
                    "created_at": float(info.get("create_time") or 0.0),
                    "command_line": _redact_text(cmdline),
                })
            except Exception:
                continue
    except Exception:
        return {"available": False, "processes": []}
    return {"available": True, "processes": entries[:30]}


def _session_readiness_diagnostics(user_id: str | None = None) -> Dict[str, Any]:
    safe_user = str(user_id or "").strip()
    if not safe_user:
        return {"available": False, "reason": "no_user_id"}
    try:
        from metadata_core.dashboard import build_session_readiness_audit
    except Exception as exc:
        return {"available": False, "reason": "session_readiness_audit_unavailable", "error": _redact_text(exc)}
    try:
        audit = build_session_readiness_audit(safe_user, session_detail_limit=40)
    except Exception as exc:
        return {"available": False, "reason": "session_readiness_audit_failed", "error": _redact_text(exc)}
    if not isinstance(audit, dict):
        return {"available": False, "reason": "session_readiness_audit_invalid"}
    # Keep only privacy-safe, metadata-derived diagnostics.  No raw event rows,
    # feature vectors, typed text, mouse streams, or paths are included.
    safe_records = []
    for record in list(audit.get("records") or [])[:40]:
        if not isinstance(record, dict):
            continue
        safe_records.append(_allowlist_dict(record, {
            "session_id",
            "session_kind",
            "user_match",
            "accepted_bucket",
            "metadata_trusted",
            "training_eligible",
            "quality_ok",
            "passive_floor_ok",
            "counts_toward_minimum",
            "selected_for_training",
            "reject_reason",
            "reason_detail",
            "input_event_count",
            "duration_seconds",
            "stop_reason",
        }))
    return {
        "available": True,
        "schema_version": str(audit.get("schema_version") or ""),
        "minimum_required_enrollment_sessions": int(audit.get("minimum_required_enrollment_sessions") or 0),
        "total_session_records": int(audit.get("total_session_records") or 0),
        "accepted_enrollment_sessions": int(audit.get("accepted_enrollment_sessions") or 0),
        "trusted_enrollment_sessions": int(audit.get("trusted_enrollment_sessions") or 0),
        "training_eligible_enrollment_sessions": int(audit.get("training_eligible_enrollment_sessions") or 0),
        "quality_ok_enrollment_sessions": int(audit.get("quality_ok_enrollment_sessions") or 0),
        "counts_toward_training_minimum": int(audit.get("counts_toward_training_minimum") or 0),
        "training_deficit": int(audit.get("training_deficit") or 0),
        "training_can_start": bool(audit.get("training_can_start")),
        "primary_blocker": str(audit.get("primary_blocker") or ""),
        "session_kind_counts": _json_safe(audit.get("session_kind_counts") or {}),
        "rejection_reason_counts": _json_safe(audit.get("rejection_reason_counts") or {}),
        "records_sampled": len(safe_records),
        "records_truncated": bool(audit.get("records_truncated")),
        "records": safe_records,
    }


def _health_status(name: str, ok: bool, *, summary: str, detail: Dict[str, Any] | None = None, severity: str | None = None) -> Dict[str, Any]:
    return {
        "id": name,
        "status": "ok" if ok else "warn",
        "severity": severity or ("info" if ok else "warning"),
        "summary": summary,
        "detail": _json_safe(detail or {}),
    }


def build_health_diagnostics(*, user_id: str | None = None, runtime_state: Dict[str, Any] | None = None) -> Dict[str, Any]:
    runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
    control_diag = _control_file_diagnostics()
    shadow_diag = _shadow_diagnostics(user_id)
    process_diag = _process_diagnostics()
    session_readiness_diag = _session_readiness_diagnostics(user_id)

    checks: list[Dict[str, Any]] = []
    lock_info = ((control_diag.get("session_state_lock") or {}) if isinstance(control_diag, dict) else {})
    lock_exists = bool(lock_info.get("exists"))
    owner_alive = bool(lock_info.get("owner_alive"))
    lock_age = float(lock_info.get("age_sec") or 0.0)
    checks.append(_health_status(
        "session_state_lock",
        (not lock_exists) or (owner_alive and lock_age < 30.0),
        summary="session_state lock is absent or currently owned by a fresh process" if ((not lock_exists) or (owner_alive and lock_age < 30.0)) else "session_state lock may be stale or blocking startup",
        detail={"exists": lock_exists, "owner_alive": owner_alive, "age_sec": lock_age, "owner_pid": lock_info.get("owner_pid")},
    ))

    state_file = ((control_diag.get("session_state") or {}) if isinstance(control_diag, dict) else {})
    checks.append(_health_status(
        "session_state_file",
        bool(control_diag.get("available")),
        summary="control diagnostics are available" if bool(control_diag.get("available")) else "control diagnostics are unavailable",
        detail={"session_state_exists": bool(state_file.get("exists")), "issue": (control_diag.get("session_state_issue") or {}).get("last_issue")},
    ))

    runtime_summary = runtime_state or (((control_diag.get("runtime_summary") or {}).get("summary") or {}) if isinstance(control_diag, dict) else {})
    checks.append(_health_status(
        "runtime_summary",
        bool(runtime_summary),
        summary="runtime summary is available" if runtime_summary else "runtime summary is not available yet",
        detail={"status": runtime_summary.get("status"), "runtime_ready": runtime_summary.get("runtime_ready"), "diagnostic_code": runtime_summary.get("runtime_diagnostic_code")},
        severity="info" if runtime_summary else "warning",
    ))

    checks.append(_health_status(
        "shadow_mode",
        bool(shadow_diag.get("available")) or not user_id,
        summary="shadow diagnostics available or no user selected" if (bool(shadow_diag.get("available")) or not user_id) else "shadow diagnostics unavailable for selected user",
        detail={"available": shadow_diag.get("available"), "mode": shadow_diag.get("mode"), "independent_monitor_default_enabled": shadow_diag.get("independent_monitor_default_enabled")},
        severity="info",
    ))

    checks.append(_health_status(
        "bioauth_processes",
        bool(process_diag.get("available")),
        summary="BioAuth process diagnostics available" if bool(process_diag.get("available")) else "BioAuth process diagnostics unavailable",
        detail={"count": len(process_diag.get("processes") or [])},
        severity="info",
    ))

    readiness_available = bool(session_readiness_diag.get("available"))
    readiness_ok = bool(session_readiness_diag.get("training_can_start")) or not user_id
    checks.append(_health_status(
        "session_readiness",
        readiness_ok or readiness_available,
        summary=(
            "training session readiness is available"
            if readiness_available
            else "training session readiness audit is unavailable"
        ),
        detail={
            "available": readiness_available,
            "training_can_start": session_readiness_diag.get("training_can_start"),
            "primary_blocker": session_readiness_diag.get("primary_blocker"),
            "counts_toward_training_minimum": session_readiness_diag.get("counts_toward_training_minimum"),
            "minimum_required_enrollment_sessions": session_readiness_diag.get("minimum_required_enrollment_sessions"),
        },
        severity="info" if readiness_available else "warning",
    ))

    overall = "ok" if all(check.get("status") == "ok" or check.get("severity") == "info" for check in checks) else "warn"
    return {
        "schema_version": 1,
        "policy_version": SUPPORT_BUNDLE_HEALTH_POLICY_VERSION,
        "created_at": _now(),
        "overall_status": overall,
        "checks": checks,
        "control": control_diag,
        "shadow": shadow_diag,
        "processes": process_diag,
        "session_readiness": session_readiness_diag,
    }


def bundle_payload(*, user_id: str | None = None, runtime_state: Dict[str, Any] | None = None, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    settings = load_settings()
    payload = {
        "schema_version": SUPPORT_BUNDLE_SCHEMA_VERSION,
        "created_at": _now(),
        "privacy_boundary": {
            "allowlist_only": True,
            "contains_raw_input_events": False,
            "contains_model_feature_values": False,
            "contains_secret_values": False,
            "contains_screenshots_or_webcam": False,
        },
        "app": {
            "name": "BioAuth",
            "version": _read_version_file(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "app_data_dir_kind": "per-user-local",
        },
        "build_profile": profile_payload(),
        "license": _sanitize_license_state(evaluate_license(settings)),
        "settings_storage": settings_storage_metadata(),
        "model_metadata": _read_model_metadata(user_id),
        "runtime_diagnostics": _allowlist_dict(runtime_state or {}, RUNTIME_STATE_ALLOWLIST),
        "support_diagnostics": build_health_diagnostics(user_id=user_id, runtime_state=runtime_state or {}),
        "last_errors": _last_errors(),
    }
    if extra:
        payload["extra"] = _json_safe(extra)
    assert_support_bundle_safe(payload)
    return payload


def _read_version_file() -> str:
    try:
        return (Path(__file__).resolve().parent / "version_info.txt").read_text(encoding="utf-8").strip().splitlines()[0]
    except Exception:
        return "unknown"


def _sanitize_license_state(state: Dict[str, Any]) -> Dict[str, Any]:
    clean = _allowlist_dict(
        state,
        {"schema_version", "policy_version", "license_policy_mode", "verification_mode", "revocation_supported", "revocation_note", "renewal_note", "clock_policy_note", "state", "effective_tier", "premium_active", "license_expires_at", "safe_mode_note", "last_error"},
    )
    features = state.get("features") if isinstance(state, dict) else {}
    if isinstance(features, dict):
        clean["features"] = {str(k): bool(v) for k, v in sorted(features.items())}
    return clean


def assert_support_bundle_safe(payload: Dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    forbidden = [
        "raw_keyboard_events",
        "raw_mouse",
        "mouse_rows",
        "keyboard_rows",
        "feature_vector",
        "keystrokes",
        "password_hash",
        "passcode_record",
        "recovery_code",
        "api_secret",
        "access_token",
        "refresh_token",
        "license_signature",
        "license_code",
        "private_key",
        "passphrase",
        "screenshot_path",
        "webcam_path",
        "raw_face_image",
        "raw_image_path",
        "source_frame_paths",
        "template_digest",
        "embedding",
    ]
    hits = [word for word in forbidden if word in encoded]
    if hits:
        raise ValueError("support bundle contains forbidden sensitive fields: " + ", ".join(sorted(set(hits))))


def write_support_bundle(*, user_id: str | None = None, runtime_state: Dict[str, Any] | None = None, extra: Dict[str, Any] | None = None) -> Path:
    payload = bundle_payload(user_id=user_id, runtime_state=runtime_state, extra=extra)
    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_user = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(user_id or "anonymous"))[:48]
    path = support_bundle_dir() / f"bioauth_support_{safe_user}_{timestamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
