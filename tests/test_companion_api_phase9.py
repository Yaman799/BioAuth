from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Tuple

from companion.api import CompanionApiServer
from companion.device_registry import CompanionDeviceRegistry
from companion.pairing import PairingManager
from companion.security_audit import BLOCKED_CONTROL_PATHS, audit_mobile_safe_status_snapshot
from companion.snapshots import build_status_snapshot


class MemorySettings:
    def __init__(self) -> None:
        self.store: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        return dict(self.store)

    def save(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        self.store.update(dict(changes or {}))
        return dict(self.store)


class Phase9Bridge:
    _current_user = {"user_id": "phase9", "display_name": "Phase 9 Desktop"}
    _profile = {"ready": True, "production_ready": True, "progressText": "Profile ready"}
    _runtime_state = {
        "active": True,
        "flow": "protected_warning",
        "statusCode": "warning",
        "decision": "intruder",
        "risk": 93,
        "awaitingEvidence": False,
        "technicalFailure": False,
        "statusDetail": "Phase 9 E2E security audit",
        "updatedAt": "2026-05-14T01:35:00Z",
        "raw_keyboard": [{"key": "must_not_leak"}],
        "raw_mouse": [{"x": 9, "y": 9}],
        "private_key": "must_not_leak",
        "deviceToken": "must_not_leak",
        "tokenHash": "must_not_leak",
        "authorization": "Bearer must_not_leak",
        "model_blob": "must_not_leak",
        "biometric_template": "must_not_leak",
    }

    def _effective_production_ready(self) -> bool:
        return True

    def _session_flow(self, state: Dict[str, Any]) -> str:
        return str(state.get("flow") or "protected_monitoring")


def http_json(
    url: str,
    *,
    method: str = "GET",
    body: Dict[str, Any] | None = None,
    token: str = "",
    headers: Dict[str, str] | None = None,
) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    req_headers.update(headers or {})
    if token:
        req_headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            return int(response.status), payload, dict(response.headers)
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8") or "{}")
        return int(exc.code), payload, dict(exc.headers)


def start_phase9_server() -> tuple[CompanionApiServer, CompanionDeviceRegistry, PairingManager, MemorySettings, str]:
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)
    server = CompanionApiServer(
        host="127.0.0.1",
        port=0,
        registry=registry,
        pairing=pairing,
        snapshot_provider=lambda: build_status_snapshot(Phase9Bridge(), registry=registry),
    )
    state = server.start()
    return server, registry, pairing, memory, str(state["baseUrl"])


def test_phase9_snapshot_security_audit_blocks_sensitive_runtime_fields() -> None:
    registry = CompanionDeviceRegistry(lambda: {}, lambda changes: changes)
    snapshot = build_status_snapshot(Phase9Bridge(), registry=registry)
    audit = audit_mobile_safe_status_snapshot(snapshot)
    serialized = json.dumps(snapshot, sort_keys=True)

    assert audit["ok"] is True
    assert snapshot["readOnly"] is True
    assert snapshot["mobileSafe"] is True
    assert snapshot["transport"]["controlActionsAllowed"] is False
    assert snapshot["transport"]["rawBiometricDataIncluded"] is False
    assert snapshot["runtimeState"]["decision"] == "intruder"
    assert "must_not_leak" not in serialized
    assert "raw_keyboard" not in serialized
    assert "deviceToken" not in serialized
    assert "tokenHash" not in serialized


def test_phase9_pair_status_unpair_replay_and_revoked_token_e2e() -> None:
    server, _registry, pairing, memory, base = start_phase9_server()
    try:
        payload = pairing.create_pairing_payload(host="127.0.0.1", port=server.port, desktop_name="Phase 9 Desktop")
        code, paired, _headers = http_json(base + "/pair", method="POST", body={"challenge": payload["challenge"], "deviceName": "Android", "deviceId": "android-phase9"})
        assert code == 200
        token = str(paired.get("deviceToken") or "")
        assert token.startswith("bioauth_companion_")
        assert token not in json.dumps(memory.store)
        assert "tokenHash" in json.dumps(memory.store)

        replay_code, replay, _ = http_json(base + "/pair", method="POST", body={"challenge": payload["challenge"], "deviceName": "Replay"})
        assert replay_code == 400
        assert replay["error"] in {"unknown_challenge", "challenge_already_used"}

        status_code, status, headers = http_json(base + "/status", token=token)
        assert status_code == 200
        assert audit_mobile_safe_status_snapshot(status)["ok"] is True
        assert headers.get("Cache-Control", "").startswith("no-store")
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"
        assert "Access-Control-Allow-Origin" not in headers

        unpair_code, unpair, _ = http_json(base + "/unpair", method="POST", body={}, token=token)
        assert unpair_code == 200
        assert unpair["ok"] is True

        revoked_code, revoked, _ = http_json(base + "/status", token=token)
        assert revoked_code == 401
        assert revoked["error"] in {"invalid_token", "missing_token"}
    finally:
        server.stop()


def test_phase9_auth_and_body_hardening() -> None:
    server, _registry, pairing, _memory, base = start_phase9_server()
    try:
        missing_code, missing, _ = http_json(base + "/status")
        assert missing_code == 401
        assert missing["error"] == "missing_token"

        invalid_code, invalid, _ = http_json(base + "/status", token="not-a-real-token")
        assert invalid_code == 401
        assert invalid["error"] == "invalid_token"

        # Invalid JSON body must not be treated as an empty pairing attempt.
        req = urllib.request.Request(base + "/pair", data=b"{not-json", headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode("utf-8") or "{}")
            assert payload["error"] == "invalid_json"
        else:  # pragma: no cover
            raise AssertionError("invalid JSON must fail")

        huge_req = urllib.request.Request(base + "/pair", data=(b"{" + b"a" * (70 * 1024) + b"}"), headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(huge_req, timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 413
            payload = json.loads(exc.read().decode("utf-8") or "{}")
            assert payload["error"] == "request_body_too_large"
        else:  # pragma: no cover
            raise AssertionError("oversized JSON body must fail")

        payload = pairing.create_pairing_payload(host="127.0.0.1", port=server.port, desktop_name="Phase 9 Desktop")
        assert payload["challenge"]
    finally:
        server.stop()


def test_phase9_control_paths_and_control_methods_are_denied() -> None:
    server, _registry, _pairing, _memory, base = start_phase9_server()
    try:
        for path in BLOCKED_CONTROL_PATHS:
            code, payload, _headers = http_json(base.replace("/api/v1/companion", "") + path, method="POST", body={})
            assert code == 404
            assert payload["error"] == "not_found"

        code, payload, headers = http_json(base + "/status", method="DELETE")
        assert code == 405
        assert payload["controlActionsAllowed"] is False
        assert headers.get("Allow") == "GET, POST, OPTIONS"
    finally:
        server.stop()


def test_phase9_local_cors_only_for_developer_browser_origin() -> None:
    server, _registry, _pairing, _memory, base = start_phase9_server()
    try:
        code, _payload, headers = http_json(base + "/health", headers={"Origin": "http://evil.example"})
        assert code == 200
        assert "Access-Control-Allow-Origin" not in headers

        code, _payload, local_headers = http_json(base + "/health", headers={"Origin": "http://127.0.0.1:3000"})
        assert code == 200
        assert local_headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:3000"
    finally:
        server.stop()
