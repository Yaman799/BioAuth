from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from companion.api import CompanionApiServer
from companion.device_registry import CompanionDeviceRegistry
from companion.pairing import PairingManager
from companion.security_audit import audit_mobile_safe_status_snapshot
from companion.snapshots import build_status_snapshot

_store: Dict[str, Any] = {}


def load_settings() -> Dict[str, Any]:
    return dict(_store)


def save_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    _store.update(dict(changes or {}))
    return dict(_store)


class Phase9SmokeBridge:
    _current_user = {"user_id": "phase9_smoke", "display_name": "Phase 9 Smoke Desktop"}
    _profile = {"ready": True, "production_ready": True, "progressText": "Profile ready"}
    _runtime_state = {
        "active": True,
        "flow": "protected_monitoring",
        "decision": "legit",
        "risk": 14,
        "updatedAt": "2026-05-14T01:35:00Z",
        "raw_keyboard": ["must_not_leak"],
        "private_key": "must_not_leak",
        "deviceToken": "must_not_leak",
    }

    def _effective_production_ready(self) -> bool:
        return True

    def _session_flow(self, state: Dict[str, Any]) -> str:
        return str(state.get("flow") or "idle")


def request_json(url: str, *, method: str = "GET", data: Dict[str, Any] | None = None, token: str = "") -> Tuple[int, Dict[str, Any]]:
    body = None if data is None else json.dumps(data).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return int(response.status), json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8") or "{}")


def main() -> int:
    registry = CompanionDeviceRegistry(load_settings, save_settings)
    pairing = PairingManager(registry)
    server = CompanionApiServer(
        host="127.0.0.1",
        port=0,
        registry=registry,
        pairing=pairing,
        snapshot_provider=lambda: build_status_snapshot(Phase9SmokeBridge(), registry=registry),
    )
    state = server.start()
    base = state["baseUrl"]
    try:
        code, missing = request_json(base + "/status")
        assert code == 401 and missing.get("error") == "missing_token"

        payload = pairing.create_pairing_payload(host=state["host"], port=int(state["port"]), desktop_name="Phase 9 Smoke Desktop")
        code, pair = request_json(base + "/pair", method="POST", data={"challenge": payload["challenge"], "deviceName": "Phase 9 Android", "deviceId": "android-smoke"})
        assert code == 200 and pair.get("ok") is True
        token = str(pair.get("deviceToken") or "")
        assert token.startswith("bioauth_companion_")
        assert token not in json.dumps(_store)

        code, replay = request_json(base + "/pair", method="POST", data={"challenge": payload["challenge"]})
        assert code == 400 and replay.get("error") in {"unknown_challenge", "challenge_already_used"}

        code, status = request_json(base + "/status", token=token)
        assert code == 200
        audit = audit_mobile_safe_status_snapshot(status)
        assert audit.get("ok") is True, audit
        assert "must_not_leak" not in json.dumps(status)

        code, _unpair = request_json(base + "/unpair", method="POST", data={}, token=token)
        assert code == 200
        code, revoked = request_json(base + "/status", token=token)
        assert code == 401 and revoked.get("error") == "invalid_token"
    finally:
        server.stop()
    print("BioAuth Companion API Phase 9 security/E2E smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
