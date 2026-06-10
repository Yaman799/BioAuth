from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict

from companion.api import CompanionApiServer
from companion.device_registry import CompanionDeviceRegistry
from companion.pairing import PairingManager
from companion.snapshots import build_status_snapshot


class MemorySettings:
    def __init__(self) -> None:
        self.store: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        return dict(self.store)

    def save(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        self.store.update(dict(changes or {}))
        return dict(self.store)


class FakePhase8Bridge:
    _current_user = {"user_id": "phase8", "display_name": "Phase 8 Desktop"}
    _profile = {"ready": True, "production_ready": True, "progressText": "Profile ready"}
    _runtime_state = {
        "active": True,
        "flow": "protected_warning",
        "statusCode": "warning",
        "decision": "suspicious",
        "risk": 77,
        "awaitingEvidence": True,
        "technicalFailure": False,
        "statusDetail": "Phase 8 live status test",
        "updatedAt": "2026-05-14T01:10:00Z",
        "raw_keyboard": [{"key": "never"}],
        "raw_mouse": [{"x": 99}],
        "private_key": "must_not_leak",
        "deviceToken": "must_not_leak_either",
    }

    def _effective_production_ready(self) -> bool:
        return True

    def _session_flow(self, state: Dict[str, Any]) -> str:
        return str(state.get("flow") or "idle")


def http_json(url: str, *, method: str = "GET", body: Dict[str, Any] | None = None, token: str = "") -> Dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_phase8_status_snapshot_contract_is_live_read_only_and_mobile_safe() -> None:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    snapshot = build_status_snapshot(FakePhase8Bridge(), registry=registry)
    serialized = json.dumps(snapshot)

    assert snapshot["schemaVersion"] == 1
    assert snapshot["readOnly"] is True
    assert snapshot["mobileSafe"] is True
    assert snapshot["transport"]["statusPolling"] is True
    assert snapshot["transport"]["controlActionsAllowed"] is False
    assert snapshot["transport"]["rawBiometricDataIncluded"] is False
    assert snapshot["desktop"]["displayName"] == "Phase 8 Desktop"
    assert snapshot["runtimeState"]["decision"] == "suspicious"
    assert snapshot["runtimeState"]["risk"] == 77
    assert snapshot["alerts"][0]["type"] == "runtime_alert"
    assert "raw_keyboard" not in serialized
    assert "raw_mouse" not in serialized
    assert "must_not_leak" not in serialized


def test_phase8_status_endpoint_returns_same_contract_after_real_pairing() -> None:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)
    server = CompanionApiServer(
        host="127.0.0.1",
        port=0,
        registry=registry,
        pairing=pairing,
        snapshot_provider=lambda: build_status_snapshot(FakePhase8Bridge(), registry=registry),
    )
    state = server.start()
    base = state["baseUrl"]
    try:
        payload = pairing.create_pairing_payload(host=state["host"], port=int(state["port"]), desktop_name="Phase 8 Desktop")
        paired = http_json(base + "/pair", method="POST", body={"challenge": payload["challenge"], "deviceName": "Android", "deviceId": "android-phase8"})
        token = str(paired["deviceToken"])
        status = http_json(base + "/status", token=token)
        assert status["readOnly"] is True
        assert status["mobileSafe"] is True
        assert status["transport"]["statusPath"] == "/api/v1/companion/status"
        assert status["runtimeState"]["decision"] == "suspicious"
        assert status["runtimeState"]["awaitingEvidence"] is True
    finally:
        server.stop()
