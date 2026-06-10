from __future__ import annotations

import base64
import hashlib
import json
import logging
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

from .device_registry import CompanionDeviceRegistry
from .pairing import PairingManager
from .security import bearer_token_from_header
from .snapshots import build_status_snapshot, sanitize_status_snapshot

_LOGGER = logging.getLogger(__name__)
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SnapshotProvider = Callable[[], Dict[str, Any]]
MAX_JSON_BODY_BYTES = 64 * 1024
_ALLOWED_BROWSER_ORIGINS = {"localhost", "127.0.0.1", "::1"}
LAN_BIND_HOSTS = {"0.0.0.0", "::", ""}
DEFAULT_PAIRING_WINDOW_SEC = 300
DEFAULT_INACTIVITY_TIMEOUT_SEC = 15 * 60


def _is_allowed_origin(origin: str) -> bool:
    """Allow CORS only for local developer browser tooling, never wildcard LAN origins."""

    text = str(origin or "").strip()
    if not text:
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    host = str(parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and host in _ALLOWED_BROWSER_ORIGINS


class _CompanionHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], context: Dict[str, Any]) -> None:
        self.context = context
        super().__init__(server_address, handler_class)


class CompanionApiServer:
    """Small stdlib-only Companion API server.

    The server is intentionally read-only for mobile clients. Phase 4 hardens
    LAN exposure by keeping public health minimal, keeping status/live behind
    bearer tokens, and supporting automatic stop after a short pairing window or
    after inactivity. Mobile clients can read status/live updates or revoke
    their own token, but cannot control BioAuth Desktop.
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 39081,
        registry: CompanionDeviceRegistry,
        pairing: PairingManager,
        snapshot_provider: Optional[SnapshotProvider] = None,
        pairing_window_sec: int = DEFAULT_PAIRING_WINDOW_SEC,
        idle_timeout_sec: int = DEFAULT_INACTIVITY_TIMEOUT_SEC,
        auto_stop_after_pairing: bool = False,
        trusted_lan_confirmed: bool = False,
    ) -> None:
        self.host = str(host or "127.0.0.1")
        self.port = int(port or 39081)
        self.registry = registry
        self.pairing = pairing
        self.snapshot_provider = snapshot_provider or (lambda: build_status_snapshot(None, registry=registry))
        self.pairing_window_sec = max(0, min(int(pairing_window_sec or 0), DEFAULT_PAIRING_WINDOW_SEC))
        self.idle_timeout_sec = max(0, min(int(idle_timeout_sec or 0), 24 * 60 * 60))
        self.auto_stop_after_pairing = bool(auto_stop_after_pairing)
        self.trusted_lan_confirmed = bool(trusted_lan_confirmed)
        self._httpd: Optional[_CompanionHttpServer] = None
        self._thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._started_at = 0.0
        self._last_activity_at = 0.0
        self._pairing_window_deadline = 0.0
        self._stop_requested = threading.Event()

    @property
    def running(self) -> bool:
        return self._httpd is not None and self._thread is not None and self._thread.is_alive()

    @property
    def lan_bound(self) -> bool:
        return self.host in {"0.0.0.0", "::"}

    def start(self) -> Dict[str, Any]:
        if self.running:
            return self.state()
        context = {
            "registry": self.registry,
            "pairing": self.pairing,
            "snapshot_provider": self.snapshot_provider,
            "server_ref": self,
        }
        self._stop_requested.clear()
        self._httpd = _CompanionHttpServer((self.host, self.port), _CompanionRequestHandler, context)
        self.host, self.port = self._httpd.server_address[0], int(self._httpd.server_address[1])
        self._started_at = time.time()
        self._last_activity_at = self._started_at
        self._pairing_window_deadline = self._started_at + self.pairing_window_sec if self.pairing_window_sec > 0 else 0.0
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="BioAuthCompanionApi", daemon=True)
        self._thread.start()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, name="BioAuthCompanionApiWatchdog", daemon=True)
        self._watchdog_thread.start()
        return self.state()

    def stop(self) -> Dict[str, Any]:
        self._stop_requested.set()
        httpd = self._httpd
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                _LOGGER.debug("Failed to stop Companion API cleanly", exc_info=True)
        self._httpd = None
        self._thread = None
        return self.state()

    def record_activity(self, *, authenticated: bool = False) -> None:
        # Health and pairing probes still count as activity for exposure timeout,
        # while authenticated reads update the same timestamp after token checks.
        self._last_activity_at = time.time()

    def schedule_stop(self, *, delay_sec: float = 0.25, reason: str = "scheduled") -> None:
        def _delayed_stop() -> None:
            try:
                time.sleep(max(0.0, float(delay_sec)))
                if self.running:
                    _LOGGER.info("Companion API auto-stop requested | %s", reason)
                    self.stop()
            except Exception:
                _LOGGER.debug("Companion API scheduled stop failed", exc_info=True)

        threading.Thread(target=_delayed_stop, name="BioAuthCompanionApiAutoStop", daemon=True).start()

    def _watchdog_loop(self) -> None:
        while not self._stop_requested.wait(1.0):
            if not self.running:
                return
            try:
                now = time.time()
                pending = int(self.pairing.pending_count()) if hasattr(self.pairing, "pending_count") else 0
                paired = int(self.registry.active_device_count()) if hasattr(self.registry, "active_device_count") else 0
                if self._pairing_window_deadline and now >= self._pairing_window_deadline and pending <= 0 and paired <= 0:
                    _LOGGER.info("Companion API auto-stopping after pairing window expired with no paired devices")
                    self.stop()
                    return
                if self.idle_timeout_sec > 0 and now - float(self._last_activity_at or now) >= self.idle_timeout_sec:
                    _LOGGER.info("Companion API auto-stopping after inactivity timeout")
                    self.stop()
                    return
            except Exception:
                _LOGGER.debug("Companion API watchdog iteration failed", exc_info=True)

    def state(self) -> Dict[str, Any]:
        pairing_expires = float(self._pairing_window_deadline or 0.0)
        now = time.time()
        return {
            "schemaVersion": 1,
            "running": self.running,
            "host": self.host,
            "port": self.port,
            "baseUrl": f"http://{self.host}:{self.port}/api/v1/companion",
            "startedAtEpoch": self._started_at,
            "pairedDeviceCount": self.registry.active_device_count(),
            "pendingPairingCount": self.pairing.pending_count(),
            "readOnly": True,
            "controlActionsAllowed": False,
            "phase": "phase12-release-candidate",
            "lanBound": self.lan_bound,
            "trustedLanConfirmed": self.trusted_lan_confirmed,
            "trustedLanOnly": self.lan_bound,
            "pairingWindowSec": int(self.pairing_window_sec),
            "pairingExpiresAtEpoch": pairing_expires,
            "pairingSecondsRemaining": max(0, int(pairing_expires - now)) if pairing_expires else 0,
            "autoStopAfterPairing": self.auto_stop_after_pairing,
            "autoStopAfterInactivitySec": int(self.idle_timeout_sec),
            "lastActivityAtEpoch": float(self._last_activity_at or 0.0),
        }


class _CompanionRequestHandler(BaseHTTPRequestHandler):
    server_version = "BioAuthCompanionAPI/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover - avoids noisy stderr in app mode
        _LOGGER.debug("Companion API: " + fmt, *args)

    @property
    def _ctx(self) -> Dict[str, Any]:
        return getattr(self.server, "context", {})  # type: ignore[attr-defined]

    @property
    def _registry(self) -> CompanionDeviceRegistry:
        return self._ctx["registry"]

    @property
    def _pairing(self) -> PairingManager:
        return self._ctx["pairing"]

    @property
    def _server_ref(self) -> Optional[CompanionApiServer]:
        server_ref = self._ctx.get("server_ref")
        return server_ref if isinstance(server_ref, CompanionApiServer) else None

    def _snapshot(self) -> Dict[str, Any]:
        provider = self._ctx.get("snapshot_provider")
        if callable(provider):
            try:
                data = provider()
                return sanitize_status_snapshot(dict(data or {}) if isinstance(data, dict) else {})
            except Exception:
                _LOGGER.debug("Companion API snapshot provider failed", exc_info=True)
        return sanitize_status_snapshot(build_status_snapshot(None, registry=self._registry))

    def _write_json(self, status: int, payload: Dict[str, Any], *, extra_headers: Optional[Dict[str, str]] = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        origin = str(self.headers.get("Origin") or "").strip()
        if _is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for key, value in dict(extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Dict[str, Any]:
        self._last_body_error = ""
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._last_body_error = "invalid_content_length"
            return {}
        if length <= 0:
            return {}
        if length > MAX_JSON_BODY_BYTES:
            self._last_body_error = "request_body_too_large"
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                self._last_body_error = "json_body_must_be_object"
                return {}
            return dict(parsed or {})
        except Exception:
            self._last_body_error = "invalid_json"
            return {}

    def _auth(self, scope: str) -> Dict[str, Any]:
        token = bearer_token_from_header(self.headers.get("Authorization"))
        return self._registry.validate_token(token, required_scope=scope, touch=True)

    def _client_ip(self) -> str:
        try:
            return str(self.client_address[0])
        except Exception:
            return "unknown"

    def _log_api(self, event: str, **payload: Any) -> None:
        safe_payload = {str(k): v for k, v in payload.items() if k not in {"token", "deviceToken", "challenge", "authorization"}}
        safe_payload.setdefault("client", self._client_ip())
        safe_payload.setdefault("path", urlparse(self.path).path.rstrip("/") or "/")
        _LOGGER.info("Companion API %s | %s", event, json.dumps(safe_payload, ensure_ascii=False, sort_keys=True))

    def do_OPTIONS(self) -> None:  # noqa: N802
        ref = self._server_ref
        if ref is not None:
            ref.record_activity()
        self._write_json(HTTPStatus.NO_CONTENT, {})

    def _method_not_allowed(self) -> None:
        self._write_json(HTTPStatus.METHOD_NOT_ALLOWED, {
            "ok": False,
            "schemaVersion": 1,
            "error": "method_not_allowed",
            "readOnly": True,
            "controlActionsAllowed": False,
        }, extra_headers={"Allow": "GET, POST, OPTIONS"})

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        ref = self._server_ref
        if ref is not None:
            ref.record_activity()
        if path == "/api/v1/companion/health":
            self._log_api("health", status=200)
            self._write_json(HTTPStatus.OK, {"ok": True})
            return
        if path == "/api/v1/companion/status":
            auth = self._auth("status:read")
            if not auth.get("ok"):
                self._log_api("status_denied", status=401, reason=str(auth.get("reason") or "unauthorized"))
                self._write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": str(auth.get("reason") or "unauthorized")})
                return
            if ref is not None:
                ref.record_activity(authenticated=True)
            device = auth.get("device") if isinstance(auth.get("device"), dict) else {}
            self._log_api("status_ok", status=200, deviceId=str(device.get("deviceId") or ""))
            self._write_json(HTTPStatus.OK, self._snapshot())
            return
        if path == "/api/v1/companion/live":
            auth = self._auth("live:read")
            if not auth.get("ok"):
                self._log_api("live_denied", status=401, reason=str(auth.get("reason") or "unauthorized"))
                self._write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": str(auth.get("reason") or "unauthorized")})
                return
            if ref is not None:
                ref.record_activity(authenticated=True)
            device = auth.get("device") if isinstance(auth.get("device"), dict) else {}
            self._log_api("live_ok", status=200, deviceId=str(device.get("deviceId") or ""), websocket=str(self.headers.get("Upgrade") or "").lower() == "websocket")
            if str(self.headers.get("Upgrade") or "").lower() == "websocket":
                self._serve_websocket_live()
            else:
                self._write_json(HTTPStatus.OK, {"schemaVersion": 1, "liveTransport": "polling", "snapshot": self._snapshot()})
            return
        self._log_api("not_found", status=404)
        self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        ref = self._server_ref
        if ref is not None:
            ref.record_activity()
        body = self._read_body()
        body_error = str(getattr(self, "_last_body_error", "") or "")
        if body_error:
            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if body_error == "request_body_too_large" else HTTPStatus.BAD_REQUEST
            self._log_api("body_rejected", status=int(status), reason=body_error)
            self._write_json(status, {"ok": False, "schemaVersion": 1, "error": body_error})
            return
        if path == "/api/v1/companion/pair":
            device_name = str(body.get("deviceName") or body.get("displayName") or "BioAuth Companion")
            device_id = str(body.get("deviceId") or "")
            self._log_api("pair_requested", deviceName=device_name[:80], deviceId=device_id[:80])
            result = self._pairing.consume_challenge(str(body.get("challenge") or ""))
            if not result.get("ok"):
                reason = str(result.get("reason") or "pairing_failed")
                self._log_api("pair_failed", status=400, reason=reason, deviceId=device_id[:80])
                self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": reason})
                return
            paired = self._registry.pair_device(
                device_name=device_name,
                device_id=device_id,
            )
            device = paired.get("device") if isinstance(paired.get("device"), dict) else {}
            self._log_api("pair_success", status=200, deviceId=str(device.get("deviceId") or ""), pairedDeviceCount=self._registry.active_device_count())
            self._write_json(HTTPStatus.OK, {
                "ok": True,
                "schemaVersion": 1,
                "device": paired.get("device"),
                "deviceToken": paired.get("deviceToken"),
                "scopes": paired.get("device", {}).get("scopes", []),
            })
            if ref is not None and ref.auto_stop_after_pairing:
                ref.schedule_stop(reason="auto_stop_after_pairing")
            return
        if path == "/api/v1/companion/unpair":
            token = bearer_token_from_header(self.headers.get("Authorization"))
            result = self._registry.revoke_token(token)
            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.UNAUTHORIZED
            self._log_api("unpair", status=int(status), ok=bool(result.get("ok")), reason=str(result.get("reason") or ""), deviceId=str(result.get("deviceId") or ""))
            self._write_json(status, result)
            return
        self._log_api("not_found", status=404)
        self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def _serve_websocket_live(self) -> None:
        key = str(self.headers.get("Sec-WebSocket-Key") or "").strip()
        if not key:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_websocket_key"})
            return
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")
        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        try:
            self.connection.settimeout(1.0)
        except Exception:
            pass
        deadline = time.time() + 60.0 * 30.0
        previous = ""
        while time.time() < deadline:
            payload = {"type": "status_snapshot", "schemaVersion": 1, "snapshot": self._snapshot()}
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if text != previous:
                previous = text
                if not self._send_ws_text(text):
                    break
            ref = self._server_ref
            if ref is not None:
                ref.record_activity(authenticated=True)
            time.sleep(2.0)

    def _send_ws_text(self, text: str) -> bool:
        data = text.encode("utf-8")
        length = len(data)
        if length < 126:
            header = bytes([0x81, length])
        elif length <= 0xFFFF:
            header = bytes([0x81, 126]) + length.to_bytes(2, "big")
        else:
            header = bytes([0x81, 127]) + length.to_bytes(8, "big")
        try:
            self.wfile.write(header + data)
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionError, OSError):
            return False


def local_ip_hint() -> str:
    """Best-effort LAN address hint for QR generation; never required for API startup."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except Exception:
        return "127.0.0.1"
