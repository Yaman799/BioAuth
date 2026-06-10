from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict

from companion.api import CompanionApiServer
from companion.device_registry import CompanionDeviceRegistry
from companion.pairing import PairingManager
from companion.snapshots import (
    ALERT_ALLOWED_FIELDS,
    CONNECTION_ALLOWED_FIELDS,
    DESKTOP_ALLOWED_FIELDS,
    PROFILE_ALLOWED_FIELDS,
    RUNTIME_ALLOWED_FIELDS,
    TOP_LEVEL_ALLOWED_FIELDS,
    TRANSPORT_ALLOWED_FIELDS,
    build_status_snapshot,
)


class MemorySettings:
    def __init__(self) -> None:
        self.store: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        return dict(self.store)

    def save(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        self.store.update(dict(changes or {}))
        return dict(self.store)


class UnsafeBridge:
    _current_user = {
        "user_id": "raw-user-id-must-not-leak",
        "customer_id": "raw-customer-id-must-not-leak",
        "display_name": "Phase 5 Desktop",
        "tokenHash": "must-not-leak",
    }
    _profile = {
        "ready": True,
        "production_ready": True,
        "progressText": "Profile ready",
        "licenseData": "must-not-leak",
        "model_path": r"C:\\Users\\yaman\\model.joblib",
        "unknownProfileField": "must-not-leak",
    }
    _runtime_state = {
        "active": True,
        "flow": "protected_warning",
        "statusCode": "warning",
        "decision": "suspicious",
        "risk": 88,
        "awaitingEvidence": True,
        "technicalFailure": False,
        "statusDetail": "Suspicious behavior reported",
        "updatedAt": "2026-05-16T00:00:00Z",
        "reason_code": "must-not-leak",
        "developer_shadow": "must-not-leak",
        "shadow": "must-not-leak",
        "candidateRuntime": "must-not-leak",
        "candidate_digest": "must-not-leak",
        "raw_diagnostics": "must-not-leak",
        "raw_keyboard": [{"key": "must-not-leak"}],
        "raw_mouse": [{"x": 1, "y": 2}],
        "keyboard_events": ["must-not-leak"],
        "mouse_events": ["must-not-leak"],
        "keystrokes": ["must-not-leak"],
        "biometric_template": "must-not-leak",
        "face_template": "must-not-leak",
        "model_blob": "must-not-leak",
        "model_path": r"C:\\Users\\yaman\\model.joblib",
        "private_key": "must-not-leak",
        "deviceToken": "must-not-leak",
        "tokenHash": "must-not-leak",
        "authorization": "Bearer must-not-leak",
        "license": "must-not-leak",
        "absolutePath": "/home/yaman/bioauth/session.json",
        "newFutureBackendField": "must-not-leak",
    }

    def _effective_production_ready(self) -> bool:
        return True

    def _session_flow(self, state: Dict[str, Any]) -> str:
        return str(state.get("flow") or "idle")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _http_json(url: str, *, method: str = "GET", body: Dict[str, Any] | None = None, token: str = "") -> Dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def test_phase5_status_snapshot_uses_exact_allowlist_schema() -> None:
    registry = CompanionDeviceRegistry(lambda: {}, lambda changes: changes)
    snapshot = build_status_snapshot(UnsafeBridge(), registry=registry)

    assert set(snapshot) == TOP_LEVEL_ALLOWED_FIELDS
    assert set(snapshot["desktop"]) == DESKTOP_ALLOWED_FIELDS
    assert set(snapshot["connection"]) == CONNECTION_ALLOWED_FIELDS
    assert set(snapshot["profile"]) == PROFILE_ALLOWED_FIELDS
    assert set(snapshot["runtimeState"]) == RUNTIME_ALLOWED_FIELDS
    assert set(snapshot["transport"]) == TRANSPORT_ALLOWED_FIELDS
    for alert in snapshot["alerts"]:
        assert set(alert) == ALERT_ALLOWED_FIELDS


def test_phase5_status_snapshot_blocks_sensitive_fields_values_and_unknown_backend_fields() -> None:
    registry = CompanionDeviceRegistry(lambda: {}, lambda changes: changes)
    snapshot = build_status_snapshot(UnsafeBridge(), registry=registry)
    serialized = _json(snapshot)

    assert snapshot["desktop"]["displayName"] == "Phase 5 Desktop"
    assert snapshot["profile"]["ready"] is True
    assert snapshot["runtimeState"]["decision"] == "suspicious"
    assert snapshot["runtimeState"]["risk"] == 88

    blocked_markers = [
        "raw-user-id-must-not-leak",
        "raw-customer-id-must-not-leak",
        "must-not-leak",
        "reason_code",
        "developer_shadow",
        "candidateRuntime",
        "candidate_digest",
        "raw_diagnostics",
        "raw_keyboard",
        "raw_mouse",
        "keyboard_events",
        "mouse_events",
        "keystrokes",
        "biometric_template",
        "face_template",
        "model_blob",
        "model_path",
        "private_key",
        "deviceToken",
        "tokenHash",
        "authorization",
        "license",
        "absolutePath",
        "newFutureBackendField",
        r"C:\\Users\\yaman",
        "/home/yaman",
    ]
    for marker in blocked_markers:
        assert marker not in serialized


def test_phase5_status_detail_replaces_internal_diagnostics_and_paths() -> None:
    class PathBridge(UnsafeBridge):
        _runtime_state = dict(UnsafeBridge._runtime_state)
        _runtime_state["statusDetail"] = r"reason_code=R1 shadow path=C:\\Users\\yaman\\secret.log"

    snapshot = build_status_snapshot(PathBridge(), registry=CompanionDeviceRegistry(lambda: {}, lambda changes: changes))
    detail = snapshot["runtimeState"]["statusDetail"]
    assert detail == "BioAuth is collecting more evidence."
    assert "reason_code" not in _json(snapshot)
    assert "shadow" not in _json(snapshot).lower()
    assert r"C:\\Users\\yaman" not in _json(snapshot)


def test_phase5_api_sanitizes_external_snapshot_provider_before_status_and_live_output() -> None:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)

    unsafe_provider_payload = {
        "schemaVersion": 1,
        "desktop": {
            "displayName": "Provider Desktop",
            "deviceId": "desktop-provider",
            "paired": True,
            "serverTime": "2026-05-16T00:00:00Z",
            "fingerprint": "sha256:must-not-leak",
            "customer_id": "must-not-leak",
        },
        "connection": {"state": "online", "lastSeenAt": "2026-05-16T00:00:00Z", "stale": False, "debugPath": "/home/yaman/debug.json"},
        "profile": {"ready": True, "productionReady": True, "progressText": "Ready", "licenseData": "must-not-leak"},
        "runtimeState": {
            "active": True,
            "flow": "candidate runtime",
            "statusCode": "warning",
            "decision": "suspicious",
            "risk": 66,
            "technicalFailure": False,
            "awaitingEvidence": False,
            "statusDetail": r"raw diagnostics at C:\\Users\\yaman\\diag.log",
            "updatedAt": "2026-05-16T00:00:00Z",
            "tokenHash": "must-not-leak",
        },
        "alerts": [{"id": "a1", "severity": "high", "type": "runtime_alert", "title": "Alert", "message": "Safe alert", "createdAt": "2026-05-16T00:00:00Z", "acknowledged": False, "debug": "must-not-leak"}],
        "transport": {"controlActionsAllowed": True, "rawBiometricDataIncluded": True, "unsafePath": "/home/yaman/raw.bin"},
        "debug": "must-not-leak",
        "sessions": [{"raw_keyboard": "must-not-leak"}],
    }

    server = CompanionApiServer(
        host="127.0.0.1",
        port=0,
        registry=registry,
        pairing=pairing,
        snapshot_provider=lambda: unsafe_provider_payload,
        idle_timeout_sec=0,
    )
    state = server.start()
    try:
        payload = pairing.create_pairing_payload(host=state["host"], port=int(state["port"]), desktop_name="Provider Desktop")
        paired = _http_json(state["baseUrl"] + "/pair", method="POST", body={"challenge": payload["challenge"], "deviceName": "Android"})
        token = str(paired["deviceToken"])
        status = _http_json(state["baseUrl"] + "/status", token=token)
        live = _http_json(state["baseUrl"] + "/live", token=token)
    finally:
        server.stop()

    for payload in (status, live["snapshot"]):
        serialized = _json(payload)
        assert set(payload) == TOP_LEVEL_ALLOWED_FIELDS
        assert payload["transport"]["controlActionsAllowed"] is False
        assert payload["transport"]["rawBiometricDataIncluded"] is False
        assert payload["runtimeState"]["flow"] == "protected_monitoring"
        assert "must-not-leak" not in serialized
        assert "fingerprint" not in serialized
        assert "customer_id" not in serialized
        assert "raw diagnostics" not in serialized.lower()
        assert r"C:\\Users\\yaman" not in serialized
        assert "/home/yaman" not in serialized
        assert payload["sessions"] == []
