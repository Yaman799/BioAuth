from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Tuple

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


def http_json(url: str, *, method: str = "GET", body: Dict[str, Any] | None = None, token: str = "") -> Tuple[int, Dict[str, Any]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            return int(response.status), payload
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8") or "{}")
        return int(exc.code), payload


def make_server(**kwargs: Any) -> tuple[CompanionApiServer, PairingManager, MemorySettings, str]:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)
    server = CompanionApiServer(
        host="127.0.0.1",
        port=0,
        registry=registry,
        pairing=pairing,
        snapshot_provider=lambda: build_status_snapshot(None, registry=registry),
        **kwargs,
    )
    state = server.start()
    return server, pairing, memory, str(state["baseUrl"])


def test_phase4_public_health_is_minimal_and_unauthenticated() -> None:
    server, _pairing, _memory, base = make_server()
    try:
        code, payload = http_json(base + "/health")
        assert code == 200
        assert payload == {"ok": True}
        serialized = json.dumps(payload, sort_keys=True)
        assert "state" not in payload
        assert "baseUrl" not in serialized
        assert "pairedDeviceCount" not in serialized
        assert "pendingPairingCount" not in serialized
    finally:
        server.stop()


def test_phase4_status_and_live_still_require_valid_bearer_token() -> None:
    server, _pairing, _memory, base = make_server()
    try:
        status_code, status_payload = http_json(base + "/status")
        assert status_code == 401
        assert status_payload["error"] == "missing_token"
        live_code, live_payload = http_json(base + "/live")
        assert live_code == 401
        assert live_payload["error"] == "missing_token"
    finally:
        server.stop()


def test_phase4_pairing_payload_ttl_is_bounded_and_single_use() -> None:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)
    payload = pairing.create_pairing_payload(host="127.0.0.1", port=39081, ttl_sec=999999)
    assert payload["ttlSeconds"] == 300
    assert payload["trustedLanOnly"] is True
    assert pairing.pending_count() == 1
    consumed = pairing.consume_challenge(str(payload["challenge"]))
    assert consumed["ok"] is True
    assert pairing.consume_challenge(str(payload["challenge"]))["ok"] is False


def test_phase4_server_auto_stops_after_empty_pairing_window() -> None:
    server, _pairing, _memory, _base = make_server(pairing_window_sec=1, idle_timeout_sec=0)
    try:
        deadline = time.time() + 4.0
        while time.time() < deadline and server.running:
            time.sleep(0.1)
        assert server.running is False
    finally:
        server.stop()


def test_phase4_auto_stop_after_pairing_option_is_available() -> None:
    server, pairing, _memory, base = make_server(pairing_window_sec=300, idle_timeout_sec=0, auto_stop_after_pairing=True)
    try:
        payload = pairing.create_pairing_payload(host="127.0.0.1", port=server.port, desktop_name="Phase 4 Desktop")
        code, paired = http_json(base + "/pair", method="POST", body={"challenge": payload["challenge"], "deviceName": "Android"})
        assert code == 200
        assert paired["ok"] is True
        deadline = time.time() + 4.0
        while time.time() < deadline and server.running:
            time.sleep(0.1)
        assert server.running is False
    finally:
        server.stop()


def test_phase4_settings_qml_requires_trusted_lan_confirmation_and_safe_wrapper() -> None:
    qml = Path("qml/pages/settings/SettingsCompanionMobileCard.qml").read_text(encoding="utf-8")
    assert "trustedLanConfirmed" in qml
    assert "I confirm this is a trusted local network" in qml
    assert "startCompanionLanApi(card.trustedLanConfirmed)" in qml
    assert "createCompanionLanPairingPayload(card.trustedLanConfirmed)" in qml
    assert 'startCompanionApi("0.0.0.0"' not in qml
