from __future__ import annotations

import json
import urllib.error
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


class FakeBridge:
    _current_user = {"user_id": "phase7", "display_name": "Phase 7 Desktop"}
    _profile = {"ready": True, "production_ready": True, "progressText": "Profile ready"}
    _runtime_state = {"active": True, "decision": "legit", "risk": 20, "updatedAt": "2026-05-14T00:00:00Z"}

    def _effective_production_ready(self) -> bool:
        return True

    def _session_flow(self, state: Dict[str, Any]) -> str:
        return str(state.get("flow") or "protected_monitoring")


def http_json(url: str, *, method: str = "GET", body: Dict[str, Any] | None = None, token: str = "") -> Dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_phase7_pair_endpoint_returns_token_once_and_status_requires_scope() -> None:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)
    server = CompanionApiServer(host="127.0.0.1", port=0, registry=registry, pairing=pairing, snapshot_provider=lambda: build_status_snapshot(FakeBridge(), registry=registry))
    state = server.start()
    base = state["baseUrl"]
    try:
        payload = pairing.create_pairing_payload(host=state["host"], port=int(state["port"]), desktop_name="Phase 7 Desktop")
        assert payload["desktopId"].startswith("desktop-")
        assert payload["fingerprint"].startswith("sha256:")
        paired = http_json(base + "/pair", method="POST", body={"challenge": payload["challenge"], "deviceName": "Android", "deviceId": "android-test"})
        token = str(paired["deviceToken"])
        assert token.startswith("bioauth_companion_")
        assert token not in json.dumps(memory.store)
        assert "tokenHash" in json.dumps(memory.store)

        try:
            http_json(base + "/pair", method="POST", body={"challenge": payload["challenge"], "deviceName": "Replay"})
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:  # pragma: no cover
            raise AssertionError("Phase 7 challenge replay must fail")

        status = http_json(base + "/status", token=token)
        assert status["schemaVersion"] == 1
        assert status["desktop"]["displayName"] == "Phase 7 Desktop"
        assert status["runtimeState"]["decision"] == "legit"
    finally:
        server.stop()


def test_phase7_unpair_revokes_token() -> None:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)
    server = CompanionApiServer(host="127.0.0.1", port=0, registry=registry, pairing=pairing)
    state = server.start()
    base = state["baseUrl"]
    try:
        payload = pairing.create_pairing_payload(host=state["host"], port=int(state["port"]), desktop_name="Phase 7 Desktop")
        paired = http_json(base + "/pair", method="POST", body={"challenge": payload["challenge"], "deviceName": "Android", "deviceId": "android-test"})
        token = str(paired["deviceToken"])
        assert http_json(base + "/unpair", method="POST", body={}, token=token)["ok"] is True
        try:
            http_json(base + "/status", token=token)
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:  # pragma: no cover
            raise AssertionError("revoked token must not work")
    finally:
        server.stop()
