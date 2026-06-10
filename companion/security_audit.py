from __future__ import annotations

import json
from typing import Any, Dict, List

BLOCKED_CONTROL_PATHS = [
    "/api/v1/companion/start",
    "/api/v1/companion/stop",
    "/api/v1/companion/lock",
    "/api/v1/companion/unlock",
    "/api/v1/companion/retrain",
    "/api/v1/companion/delete-session",
    "/api/v1/companion/promote",
]

BLOCKED_SENSITIVE_MARKERS = [
    "raw_keyboard",
    "raw_mouse",
    "keyboard_events",
    "mouse_events",
    "keystrokes",
    "biometric_template",
    "face_template",
    "model_blob",
    "private_key",
    "deviceToken",
    "tokenHash",
    "password",
    "passcode",
    "authorization",
    "bearer",
]


def serialize_for_audit(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def find_sensitive_markers(value: Any) -> List[str]:
    text = serialize_for_audit(value)
    lowered = text.lower()
    return sorted({marker for marker in BLOCKED_SENSITIVE_MARKERS if marker.lower() in lowered})


def audit_mobile_safe_status_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deterministic read-only/mobile-safe contract audit result.

    This helper is intentionally dependency-free so it can be used by tests,
    smoke scripts, or support bundles without importing any UI code.
    """

    data = dict(snapshot or {})
    markers = find_sensitive_markers(data)
    transport = data.get("transport") if isinstance(data.get("transport"), dict) else {}
    failures: List[str] = []
    if data.get("schemaVersion") != 1:
        failures.append("schemaVersion must be 1")
    if data.get("readOnly") is not True:
        failures.append("readOnly must be true")
    if data.get("mobileSafe") is not True:
        failures.append("mobileSafe must be true")
    if transport.get("controlActionsAllowed") is not False:
        failures.append("transport.controlActionsAllowed must be false")
    if transport.get("rawBiometricDataIncluded") is not False:
        failures.append("transport.rawBiometricDataIncluded must be false")
    if markers:
        failures.append("sensitive markers leaked: " + ", ".join(markers))
    return {
        "ok": not failures,
        "schemaVersion": 1,
        "readOnly": data.get("readOnly") is True,
        "mobileSafe": data.get("mobileSafe") is True,
        "controlActionsAllowed": bool(transport.get("controlActionsAllowed")),
        "rawBiometricDataIncluded": bool(transport.get("rawBiometricDataIncluded")),
        "sensitiveMarkers": markers,
        "failures": failures,
    }
