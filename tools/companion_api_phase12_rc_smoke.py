from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from companion.api import CompanionApiServer
from companion.device_registry import CompanionDeviceRegistry
from companion.pairing import PairingManager
from companion.snapshots import build_status_snapshot


class MemorySettings:
    def __init__(self) -> None:
        self.payload = {}

    def load(self):
        return dict(self.payload)

    def save(self, value):
        self.payload = dict(value or {})
        return dict(self.payload)


def request(url: str, method: str = "GET", body: dict | None = None, token: str = ""):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def main() -> int:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)
    server = CompanionApiServer(host="127.0.0.1", port=0, registry=registry, pairing=pairing, snapshot_provider=lambda: build_status_snapshot(None, registry=registry))
    state = server.start()
    try:
        assert state["phase"] == "phase12-release-candidate"
        base = f"http://127.0.0.1:{state['port']}/api/v1/companion"
        code, health = request(base + "/health")
        assert code == 200 and health["ok"] is True
        payload = pairing.create_pairing_payload(host="127.0.0.1", port=int(state["port"]), desktop_name="BioAuth Desktop")
        code, paired = request(base + "/pair", method="POST", body={"challenge": payload["challenge"], "deviceName": "Android", "deviceId": "android-phase12"})
        assert code == 200 and paired["ok"] is True
        token = paired["deviceToken"]
        assert token.startswith("bioauth_companion_")
        code, status = request(base + "/status", token=token)
        assert code == 200
        assert status["readOnly"] is True
        assert status["mobileSafe"] is True
        assert status["transport"]["controlActionsAllowed"] is False
        assert status["transport"]["rawBiometricDataIncluded"] is False
        code, replay = request(base + "/pair", method="POST", body={"challenge": payload["challenge"], "deviceName": "Replay"})
        assert code == 400 and replay["ok"] is False
        code, denied = request(base + "/status")
        assert code == 401 and denied["ok"] is False
    finally:
        server.stop()
    print("BioAuth Companion API Phase 12 release-candidate smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
