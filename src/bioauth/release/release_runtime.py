from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Mapping

from paths import app_data_dir, data_dir, runtime_base_dir

_RELEASE_EVENT_LOG_NAME = "release_runtime_events.jsonl"
_SAFE_REASON_RE = re.compile(r"[^a-zA-Z0-9_.:-]+")
_MAX_EVENT_DETAIL = 240


def release_event_log_file() -> str:
    """Return the per-user release/runtime event log path.

    This is intentionally under the writable BioAuth data directory, never the
    frozen install directory. Events are diagnostics only and must not contain
    raw biometric, behavioral, password, token, or model payloads.
    """
    root = Path(data_dir())
    root.mkdir(parents=True, exist_ok=True)
    return str(root / _RELEASE_EVENT_LOG_NAME)


def _safe_text(value: Any, *, max_len: int = _MAX_EVENT_DETAIL) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return ""
    # Redact obvious local paths while preserving enough context for support.
    text = re.sub(r"([A-Za-z]:\\|/)[^\s]+", "[path]", text)
    text = " ".join(text.split())
    return text[:max(0, int(max_len))]


def _safe_reason(value: Any) -> str:
    text = _SAFE_REASON_RE.sub("_", str(value or "").strip().lower()).strip("_")
    return text[:96] or "unspecified"


def write_release_runtime_event(event_type: str, **fields: Any) -> bool:
    """Append a sanitized release/runtime diagnostic event.

    The allowlist avoids raw biometric/behavioral payloads and keeps the log
    support-safe. Failures are deliberately non-fatal so diagnostics can never
    block authentication or runtime safety decisions.
    """
    allowed = {
        "key",
        "process",
        "reason",
        "exit_code",
        "phase",
        "background",
        "autostart_allowed",
        "startup_protected_sessions_enabled",
        "remember_login_enabled",
        "run_on_startup",
        "authenticated",
        "profile_production_ready",
        "model_status",
        "flow",
        "detail",
    }
    event: Dict[str, Any] = {
        "schema_version": 1,
        "event_type": _safe_reason(event_type),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    for key, value in fields.items():
        if key not in allowed:
            continue
        if isinstance(value, bool):
            event[key] = value
        elif isinstance(value, int):
            event[key] = int(value)
        elif isinstance(value, float):
            event[key] = round(float(value), 3)
        else:
            event[key] = _safe_text(value)
    try:
        path = Path(release_event_log_file())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def _bool_setting(settings: Mapping[str, Any] | None, key: str, *, default: bool = False) -> bool:
    payload = settings if isinstance(settings, Mapping) else {}
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
        return bool(default)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled", ""}:
            return False
    return bool(default)


def startup_protected_session_decision(
    *,
    settings: Mapping[str, Any] | None,
    background: bool,
    authenticated: bool,
    has_current_consent: bool,
    profile: Mapping[str, Any] | None,
    flow: str,
) -> Dict[str, Any]:
    """Return a fail-closed decision for startup protected-session autostart.

    Startup protected sessions require explicit user settings and the same
    backend-owned production readiness checks as manual protected sessions. This
    helper never changes models, thresholds, gates, or enrollment state.
    """
    payload = settings if isinstance(settings, Mapping) else {}
    profile_payload = profile if isinstance(profile, Mapping) else {}
    run_on_startup = _bool_setting(payload, "run_on_startup", default=False)
    remember_login_enabled = _bool_setting(payload, "remember_login_enabled", default=False)
    startup_protected_enabled = _bool_setting(payload, "startup_protected_sessions_enabled", default=False)
    production_ready = bool(profile_payload.get("production_ready"))
    model_status = str(profile_payload.get("model_status") or profile_payload.get("production_model_status") or "")
    flow_text = str(flow or "idle").strip().lower() or "idle"

    checks = {
        "background": bool(background),
        "run_on_startup": run_on_startup,
        "remember_login_enabled": remember_login_enabled,
        "startup_protected_sessions_enabled": startup_protected_enabled,
        "authenticated": bool(authenticated),
        "has_current_consent": bool(has_current_consent),
        "profile_production_ready": production_ready,
        "flow_idle": flow_text == "idle",
    }
    reason = "allowed"
    for key in (
        "background",
        "run_on_startup",
        "remember_login_enabled",
        "startup_protected_sessions_enabled",
        "authenticated",
        "has_current_consent",
        "profile_production_ready",
        "flow_idle",
    ):
        if not checks[key]:
            reason = key + "_required"
            break
    allowed = reason == "allowed"
    return {
        "allowed": allowed,
        "reason": reason,
        "checks": checks,
        "model_status": model_status,
        "flow": flow_text,
        "production_decision_changed": False,
        "production_threshold_changed": False,
        "protected_sessions_unlocked_by_startup": False,
        "collect_owner_enrollment_data": False,
    }


def runtime_path_report() -> Dict[str, Any]:
    """Report whether mutable runtime paths are user-writable and outside install root."""
    base = Path(runtime_base_dir()).resolve()
    data = Path(data_dir()).resolve()
    app_data = Path(app_data_dir()).resolve()
    log_path = Path(release_event_log_file()).resolve()
    def _outside(child: Path, parent: Path) -> bool:
        try:
            child.relative_to(parent)
            return False
        except ValueError:
            return True
    writable = True
    try:
        probe = data / ".bioauth_writable_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        writable = False
    return {
        "frozen": bool(getattr(sys, "frozen", False)),
        "runtime_base_dir": str(base),
        "app_data_dir": str(app_data),
        "data_dir": str(data),
        "release_event_log_file": str(log_path),
        "data_dir_writable": writable,
        "data_dir_outside_runtime_base": _outside(data, base),
        "event_log_outside_runtime_base": _outside(log_path, base),
    }


__all__ = [
    "release_event_log_file",
    "runtime_path_report",
    "startup_protected_session_decision",
    "write_release_runtime_event",
]
