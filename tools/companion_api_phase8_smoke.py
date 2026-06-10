from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from companion.api import CompanionApiServer
from companion.device_registry import CompanionDeviceRegistry
from companion.pairing import PairingManager
from companion.snapshots import build_status_snapshot

_store: Dict[str, Any] = {}


def load_settings() -> Dict[str, Any]:
    return dict(_store)


def save_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    _store.update(dict(changes or {}))
    return dict(_store)


class FakeBridge:
    _current_user = {"user_id": "phase8_smoke", "display_name": "Phase 8 Smoke Desktop"}
    _profile = {"ready": True, "production_ready": True, "progressText": "Profile ready"}
    _runtime_state = {"active": True, "flow": "protected_monitoring", "decision": "legit", "risk": 18, "updatedAt": "2026-05-14T01:10:00Z"}

    def _effective_production_ready(self) -> bool:
        return True

    def _session_flow(self, state: Dict[str, Any]) -> str:
        return str(state.get("flow") or "idle")


def request_json(url: str, *, method: str = "GET", data: Dict[str, Any] | None = None, token: str = "") -> Dict[str, Any]:
    body = None if data is None else json.dumps(data).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    registry = CompanionDeviceRegistry(load_settings, save_settings)
    pairing = PairingManager(registry)
    server = CompanionApiServer(host="127.0.0.1", port=0, registry=registry, pairing=pairing, snapshot_provider=lambda: build_status_snapshot(FakeBridge(), registry=registry))
    state = server.start()
    base = state["baseUrl"]
    try:
        payload = pairing.create_pairing_payload(host=state["host"], port=int(state["port"]), desktop_name="Phase 8 Smoke Desktop")
        pair = request_json(base + "/pair", method="POST", data={"challenge": payload["challenge"], "deviceName": "Phase 8 Android", "deviceId": "android-smoke"})
        token = str(pair.get("deviceToken") or "")
        status = request_json(base + "/status", token=token)
        assert status.get("schemaVersion") == 1
        assert status.get("readOnly") is True
        assert status.get("mobileSafe") is True
        assert status.get("transport", {}).get("statusPolling") is True
        assert status.get("runtimeState", {}).get("decision") == "legit"
        assert status.get("transport", {}).get("controlActionsAllowed") is False
    finally:
        server.stop()
    print("BioAuth Companion API Phase 8 live status smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
