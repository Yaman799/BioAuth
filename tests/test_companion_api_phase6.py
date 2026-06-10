from __future__ import annotations

import json
import time
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
    _current_user = {"user_id": "yaman", "display_name": "Yaman PC"}
    _profile = {"ready": True, "production_ready": True, "progressText": "Profile ready"}
    _runtime_state = {
        "active": True,
        "flow": "protected_monitoring",
        "status": "monitoring",
        "decision": "suspicious",
        "risk": 74,
        "raw_keyboard": [{"key": "secret"}],
        "raw_mouse": [{"x": 1, "y": 2}],
        "deviceToken": "must_not_leak",
        "updatedAt": "2026-05-14T00:00:00Z",
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
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_pairing_challenge_is_single_use_and_registry_does_not_store_plaintext_token() -> None:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)
    payload = pairing.create_pairing_payload(host="127.0.0.1", port=39081, desktop_name="Yaman PC")

    assert payload["schemaVersion"] == 1
    assert payload["type"] == "bioauth_companion_pairing"
    assert pairing.consume_challenge(payload["challenge"])["ok"] is True
    assert pairing.consume_challenge(payload["challenge"])["ok"] is False

    paired = registry.pair_device(device_name="Yaman Phone")
    token = paired["deviceToken"]
    serialized_store = json.dumps(memory.store)
    assert token not in serialized_store
    assert "tokenHash" in serialized_store
    assert registry.validate_token(token, required_scope="status:read")["ok"] is True


def test_status_snapshot_is_mobile_safe_and_excludes_raw_behavioral_data() -> None:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    snapshot = build_status_snapshot(FakeBridge(), registry=registry)
    serialized = json.dumps(snapshot)

    assert snapshot["schemaVersion"] == 1
    assert snapshot["profile"]["ready"] is True
    assert snapshot["runtimeState"]["decision"] == "suspicious"
    assert snapshot["alerts"][0]["type"] == "runtime_alert"
    assert "raw_keyboard" not in serialized
    assert "raw_mouse" not in serialized
    assert "must_not_leak" not in serialized


def test_companion_http_api_requires_token_then_returns_status_after_pairing() -> None:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)
    server = CompanionApiServer(host="127.0.0.1", port=0, registry=registry, pairing=pairing, snapshot_provider=lambda: build_status_snapshot(FakeBridge(), registry=registry))
    state = server.start()
    base = state["baseUrl"]
    try:
        try:
            http_json(base + "/status")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:  # pragma: no cover
            raise AssertionError("status endpoint must reject missing bearer tokens")

        challenge = pairing.create_pairing_payload(host=state["host"], port=int(state["port"]), desktop_name="Yaman PC")
        paired = http_json(base + "/pair", method="POST", body={"challenge": challenge["challenge"], "deviceName": "Android Phone"})
        token = str(paired["deviceToken"])
        status = http_json(base + "/status", token=token)
        assert status["desktop"]["displayName"] == "Yaman PC"
        assert status["runtimeState"]["decision"] == "suspicious"
        assert http_json(base + "/unpair", method="POST", body={}, token=token)["ok"] is True
        try:
            http_json(base + "/status", token=token)
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:  # pragma: no cover
            raise AssertionError("revoked token must be rejected")
    finally:
        server.stop()
