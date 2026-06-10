from __future__ import annotations

import re
import socket
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Set

STATUS_SCHEMA_VERSION = 1

TOP_LEVEL_ALLOWED_FIELDS: Set[str] = {
    "schemaVersion",
    "desktop",
    "connection",
    "profile",
    "runtimeState",
    "alerts",
    "sessions",
    "mobileSafe",
    "readOnly",
    "transport",
}
DESKTOP_ALLOWED_FIELDS: Set[str] = {"deviceId", "displayName", "paired", "serverTime"}
CONNECTION_ALLOWED_FIELDS: Set[str] = {"state", "lastSeenAt", "stale"}
PROFILE_ALLOWED_FIELDS: Set[str] = {"ready", "productionReady", "progressText"}
RUNTIME_ALLOWED_FIELDS: Set[str] = {
    "active",
    "flow",
    "statusCode",
    "decision",
    "decisionText",
    "risk",
    "trustLabel",
    "technicalFailure",
    "awaitingEvidence",
    "statusDetail",
    "updatedAt",
}
ALERT_ALLOWED_FIELDS: Set[str] = {"id", "severity", "type", "title", "message", "createdAt", "acknowledged"}
TRANSPORT_ALLOWED_FIELDS: Set[str] = {
    "statusPolling",
    "statusPath",
    "livePath",
    "rawBiometricDataIncluded",
    "controlActionsAllowed",
}

ALLOWED_DECISIONS: Set[str] = {"idle", "pending", "legit", "legitimate", "trusted", "suspicious", "intruder"}
ALLOWED_STATUS_CODES: Set[str] = {"idle", "monitoring", "warning", "technical_failure", "awaiting_evidence", "profile_not_ready"}
ALLOWED_FLOWS: Set[str] = {"idle", "protected_monitoring", "protected_warning", "learning", "profile_setup"}


BLOCKED_VALUE_MARKERS = (
    "reason_code",
    "developer_shadow",
    "raw_diagnostics",
    "raw diagnostics",
    "candidate runtime",
    "candidate_digest",
    "candidate digest",
    "shadow",
    "tokenhash",
    "deviceToken",
    "private_key",
    "model_path",
    "model blob",
    "biometric_template",
    "face_template",
    "traceback",
)

WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s]*")
UNC_PATH_RE = re.compile(r"\\\\[^\s]+")
UNIX_PRIVATE_PATH_RE = re.compile(r"/(?:Users|home|mnt|var|tmp|etc|AppData|ProgramData|Program Files)(?:/|\\b)", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_bool(value: Any) -> bool:
    return bool(value)


def _safe_int(value: Any, default: int = 0, *, minimum: int = 0, maximum: int = 100) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        number = default
    return max(minimum, min(number, maximum))


def _safe_str(value: Any, default: str = "", *, max_len: int = 160) -> str:
    text = str(value if value is not None else default)
    text = " ".join(text.replace("\x00", " ").split())
    return text[:max_len]


def _looks_like_private_path(text: str) -> bool:
    return bool(WINDOWS_ABSOLUTE_PATH_RE.search(text) or UNC_PATH_RE.search(text) or UNIX_PRIVATE_PATH_RE.search(text))


def _has_blocked_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in BLOCKED_VALUE_MARKERS)


def _safe_mobile_text(value: Any, default: str = "", *, max_len: int = 160) -> str:
    text = _safe_str(value, default, max_len=max_len)
    if not text:
        return _safe_str(default, "", max_len=max_len)
    if _looks_like_private_path(text) or _has_blocked_marker(text):
        return _safe_str(default, "", max_len=max_len)
    return text


def _bridge_dict(bridge: Any, attr: str) -> Dict[str, Any]:
    value = getattr(bridge, attr, {}) if bridge is not None else {}
    if isinstance(value, dict):
        return dict(value)
    try:
        candidate = value() if callable(value) else value
    except Exception:
        candidate = {}
    return dict(candidate) if isinstance(candidate, dict) else {}


def _safe_mapping(source: Mapping[str, Any], allowed: Set[str]) -> Dict[str, Any]:
    return {key: source[key] for key in allowed if key in source}


def _safe_display_name(bridge: Any) -> str:
    current_user = _bridge_dict(bridge, "_current_user")
    # Intentionally do not fall back to user_id/customer_id. The mobile app only
    # needs a friendly desktop label, not raw account identifiers.
    display = _safe_mobile_text(current_user.get("display_name") or current_user.get("displayName"), "")
    if display:
        return display
    return _safe_mobile_text(socket.gethostname(), "BioAuth Desktop") or "BioAuth Desktop"


def _session_flow(bridge: Any, runtime: Dict[str, Any], *, active: bool) -> str:
    raw_flow = ""
    fn = getattr(bridge, "_session_flow", None) if bridge is not None else None
    if callable(fn):
        try:
            raw_flow = _safe_str(fn(runtime), "")
        except Exception:
            raw_flow = ""
    if not raw_flow:
        raw_flow = _safe_str(runtime.get("flow") or "", "")
    normalized = raw_flow.strip().lower()
    if normalized in ALLOWED_FLOWS and not _has_blocked_marker(normalized):
        return normalized
    return "protected_monitoring" if active else "idle"


def _profile_payload(bridge: Any, profile_raw: Dict[str, Any]) -> Dict[str, Any]:
    production_ready = False
    eff = getattr(bridge, "_effective_production_ready", None) if bridge is not None else None
    if callable(eff):
        try:
            production_ready = bool(eff())
        except Exception:
            production_ready = False
    production_ready = bool(production_ready or profile_raw.get("production_ready") or profile_raw.get("productionReady"))
    ready = bool(profile_raw.get("ready") or production_ready or profile_raw.get("profileReady"))
    default_progress = "Profile ready" if ready else "Profile not ready"
    progress = _safe_mobile_text(profile_raw.get("progressText") or profile_raw.get("status"), default_progress)
    payload = {"ready": ready, "productionReady": production_ready, "progressText": progress or default_progress}
    return _safe_mapping(payload, PROFILE_ALLOWED_FIELDS)


def _safe_decision(runtime: Dict[str, Any], *, active: bool) -> str:
    decision = _safe_str(runtime.get("decision") or "", "").strip().lower()
    if decision in ALLOWED_DECISIONS and not _has_blocked_marker(decision):
        return "legit" if decision in {"legitimate", "trusted"} else decision
    return "pending" if active else "idle"


def _safe_status_code(runtime: Dict[str, Any], *, active: bool, technical_failure: bool, awaiting_evidence: bool) -> str:
    status = _safe_str(runtime.get("statusCode") or runtime.get("status") or "", "").strip().lower()
    if status in ALLOWED_STATUS_CODES and not _has_blocked_marker(status):
        return status
    if technical_failure:
        return "technical_failure"
    if awaiting_evidence:
        return "awaiting_evidence"
    return "monitoring" if active else "idle"


def _runtime_payload(bridge: Any, runtime_raw: Dict[str, Any]) -> Dict[str, Any]:
    # Strict allowlist extraction: only these known, user-safe runtime keys are
    # ever read. Unknown backend fields are intentionally ignored.
    active = _safe_bool(runtime_raw.get("active"))
    technical_failure = bool(runtime_raw.get("technicalFailure") or runtime_raw.get("technical_failure") or runtime_raw.get("runtime_technical_failure"))
    awaiting_evidence = bool(runtime_raw.get("awaitingEvidence") or runtime_raw.get("awaiting_evidence"))
    flow = _session_flow(bridge, runtime_raw, active=active)
    status = _safe_status_code(runtime_raw, active=active, technical_failure=technical_failure, awaiting_evidence=awaiting_evidence)
    decision = _safe_decision(runtime_raw, active=active)
    risk_value = runtime_raw.get("risk")
    risk = _safe_int(risk_value, 0) if risk_value not in (None, "", "--") else 0
    if decision == "legit":
        trust = "Trusted"
    elif decision == "suspicious":
        trust = "Suspicious"
    elif decision == "intruder":
        trust = "Intruder"
    elif technical_failure:
        trust = "Technical failure"
    elif awaiting_evidence:
        trust = "Awaiting evidence"
    else:
        trust = "Pending" if active else "Idle"
    updated_at = _safe_mobile_text(
        runtime_raw.get("updatedAt") or runtime_raw.get("updated_at") or runtime_raw.get("last_update"),
        now_iso(),
        max_len=64,
    )
    if technical_failure:
        default_detail = "Protection status needs attention."
    elif awaiting_evidence:
        default_detail = "BioAuth is collecting more evidence."
    else:
        default_detail = "Monitoring is active" if active else "BioAuth runtime is idle"
    # statusDetail is accepted only when it already looks like user-facing copy.
    # Raw diagnostics, paths, reason codes, candidate/shadow wording, and stack
    # traces are replaced with a generic safe message.
    detail = _safe_mobile_text(runtime_raw.get("statusDetail") or runtime_raw.get("status_detail"), default_detail, max_len=220)
    payload = {
        "active": active,
        "flow": flow,
        "statusCode": status,
        "decision": decision,
        "decisionText": decision.capitalize() if decision else "Idle",
        "risk": risk,
        "trustLabel": trust,
        "technicalFailure": technical_failure,
        "awaitingEvidence": awaiting_evidence,
        "statusDetail": detail or default_detail,
        "updatedAt": updated_at or now_iso(),
    }
    return _safe_mapping(payload, RUNTIME_ALLOWED_FIELDS)


def _alert_payload(alert: Dict[str, Any]) -> Dict[str, Any]:
    safe = {
        "id": _safe_mobile_text(alert.get("id"), "alert", max_len=80),
        "severity": _safe_mobile_text(alert.get("severity"), "medium", max_len=32),
        "type": _safe_mobile_text(alert.get("type"), "security_alert", max_len=64),
        "title": _safe_mobile_text(alert.get("title"), "BioAuth notice", max_len=120),
        "message": _safe_mobile_text(alert.get("message"), "BioAuth has an update for this desktop.", max_len=220),
        "createdAt": _safe_mobile_text(alert.get("createdAt"), now_iso(), max_len=64),
        "acknowledged": bool(alert.get("acknowledged")),
    }
    return _safe_mapping(safe, ALERT_ALLOWED_FIELDS)


def _alerts(runtime: Dict[str, Any]) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    created = _safe_mobile_text(runtime.get("updatedAt"), now_iso(), max_len=64)
    decision = str(runtime.get("decision") or "").lower()
    if bool(runtime.get("technicalFailure")):
        alerts.append(_alert_payload({
            "id": "technical_failure",
            "severity": "high",
            "type": "technical_failure",
            "title": "Technical failure detected",
            "message": "BioAuth reported a runtime technical failure.",
            "createdAt": created,
            "acknowledged": False,
        }))
    if decision == "intruder":
        alerts.append(_alert_payload({
            "id": "intruder_runtime_state",
            "severity": "high",
            "type": "runtime_alert",
            "title": "Intruder decision reported",
            "message": "BioAuth reported a high-risk runtime state.",
            "createdAt": created,
            "acknowledged": False,
        }))
    elif decision == "suspicious":
        alerts.append(_alert_payload({
            "id": "suspicious_runtime_state",
            "severity": "medium",
            "type": "runtime_alert",
            "title": "Suspicious activity detected",
            "message": "BioAuth reported a suspicious runtime state.",
            "createdAt": created,
            "acknowledged": False,
        }))
    return alerts


def _desktop_payload(bridge: Any, registry: Any, server_time: str) -> Dict[str, Any]:
    display = _safe_display_name(bridge)
    identity: Dict[str, Any] = {}
    if registry is not None and hasattr(registry, "desktop_identity"):
        try:
            identity = registry.desktop_identity(display_name=display)
        except Exception:
            identity = {}
    paired = bool(registry.active_device_count() if registry is not None and hasattr(registry, "active_device_count") else False)
    # Intentionally do not expose desktop fingerprint, license/customer data, or
    # account identifiers in the status snapshot. Pairing verification data stays
    # in the short-lived QR/manual pairing payload.
    payload = {
        "deviceId": _safe_mobile_text(identity.get("deviceId"), "desktop-local", max_len=80),
        "displayName": display,
        "paired": paired,
        "serverTime": server_time,
    }
    return _safe_mapping(payload, DESKTOP_ALLOWED_FIELDS)


def _connection_payload(server_time: str) -> Dict[str, Any]:
    payload = {"state": "online", "lastSeenAt": server_time, "stale": False}
    return _safe_mapping(payload, CONNECTION_ALLOWED_FIELDS)


def _transport_payload() -> Dict[str, Any]:
    payload = {
        "statusPolling": True,
        "statusPath": "/api/v1/companion/status",
        "livePath": "/api/v1/companion/live",
        "rawBiometricDataIncluded": False,
        "controlActionsAllowed": False,
    }
    return _safe_mapping(payload, TRANSPORT_ALLOWED_FIELDS)


def _desktop_payload_from_snapshot(raw: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "deviceId": _safe_mobile_text(raw.get("deviceId"), "desktop-local", max_len=80),
        "displayName": _safe_mobile_text(raw.get("displayName"), "BioAuth Desktop", max_len=120),
        "paired": bool(raw.get("paired")),
        "serverTime": _safe_mobile_text(raw.get("serverTime"), now_iso(), max_len=64),
    }
    return _safe_mapping(payload, DESKTOP_ALLOWED_FIELDS)


def _connection_payload_from_snapshot(raw: Dict[str, Any]) -> Dict[str, Any]:
    state = _safe_mobile_text(raw.get("state"), "online", max_len=40).lower()
    if state not in {"online", "offline", "stale"}:
        state = "online"
    payload = {
        "state": state,
        "lastSeenAt": _safe_mobile_text(raw.get("lastSeenAt"), now_iso(), max_len=64),
        "stale": bool(raw.get("stale")),
    }
    return _safe_mapping(payload, CONNECTION_ALLOWED_FIELDS)


def _enforce_status_allowlist(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Defensive final allowlist pass for the mobile status schema.

    This is applied both to snapshots produced here and to externally supplied
    snapshot providers used by the API server, so unknown or unsafe provider
    fields cannot become mobile output by accident.
    """

    data = dict(snapshot or {}) if isinstance(snapshot, dict) else {}
    desktop_raw = data.get("desktop") if isinstance(data.get("desktop"), dict) else {}
    connection_raw = data.get("connection") if isinstance(data.get("connection"), dict) else {}
    profile_raw = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    runtime_raw = data.get("runtimeState") if isinstance(data.get("runtimeState"), dict) else {}
    alerts = data.get("alerts") if isinstance(data.get("alerts"), list) else []
    return {
        "schemaVersion": STATUS_SCHEMA_VERSION,
        "desktop": _desktop_payload_from_snapshot(dict(desktop_raw)),
        "connection": _connection_payload_from_snapshot(dict(connection_raw)),
        "profile": _profile_payload(None, dict(profile_raw)),
        "runtimeState": _runtime_payload(None, dict(runtime_raw)),
        "alerts": [_alert_payload(dict(item)) for item in alerts[:10] if isinstance(item, dict)],
        "sessions": [],
        "mobileSafe": True,
        "readOnly": True,
        "transport": _transport_payload(),
    }


def sanitize_status_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Return a strict allowlist mobile status snapshot."""

    return _enforce_status_allowlist(snapshot)


def build_status_snapshot(bridge: Any = None, *, registry: Any = None) -> Dict[str, Any]:
    runtime_raw = _bridge_dict(bridge, "_runtime_state")
    profile_raw = _bridge_dict(bridge, "_profile")
    runtime = _runtime_payload(bridge, runtime_raw)
    profile = _profile_payload(bridge, profile_raw)
    server_time = now_iso()
    snapshot = {
        "schemaVersion": STATUS_SCHEMA_VERSION,
        "desktop": _desktop_payload(bridge, registry, server_time),
        "connection": _connection_payload(server_time),
        "profile": profile,
        "runtimeState": runtime,
        "alerts": _alerts(runtime),
        "sessions": [],
        "mobileSafe": True,
        "readOnly": True,
        "transport": _transport_payload(),
    }
    return _enforce_status_allowlist(snapshot)
