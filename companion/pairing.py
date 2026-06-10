from __future__ import annotations

import secrets
import time
from typing import Any, Dict, Optional

from .device_registry import CompanionDeviceRegistry, utc_now_iso

PAIRING_TYPE = "bioauth_companion_pairing"
DEFAULT_PAIRING_TTL_SEC = 300
MIN_PAIRING_TTL_SEC = 30
MAX_PAIRING_TTL_SEC = 300


def _sanitize_ttl_sec(value: Any) -> int:
    try:
        ttl = int(value or DEFAULT_PAIRING_TTL_SEC)
    except (TypeError, ValueError, OverflowError):
        ttl = DEFAULT_PAIRING_TTL_SEC
    return max(MIN_PAIRING_TTL_SEC, min(ttl, MAX_PAIRING_TTL_SEC))


class PairingManager:
    """In-memory, short-lived pairing challenge manager."""

    def __init__(self, registry: CompanionDeviceRegistry) -> None:
        self._registry = registry
        self._pending: Dict[str, Dict[str, Any]] = {}

    def create_pairing_payload(
        self,
        *,
        host: str,
        port: int,
        desktop_name: str = "BioAuth Desktop",
        ttl_sec: int = DEFAULT_PAIRING_TTL_SEC,
    ) -> Dict[str, Any]:
        self.prune_expired()
        ttl = _sanitize_ttl_sec(ttl_sec)
        identity = self._registry.desktop_identity(display_name=desktop_name)
        challenge = secrets.token_urlsafe(32)
        expires_at_epoch = time.time() + ttl
        payload = {
            "schemaVersion": 1,
            "type": PAIRING_TYPE,
            "apiVersion": "v1",
            "baseUrl": f"http://{host}:{int(port)}/api/v1/companion",
            "desktopName": str(desktop_name or identity.get("displayName") or "BioAuth Desktop"),
            "desktopId": str(identity.get("deviceId") or ""),
            "host": str(host or "127.0.0.1"),
            "port": int(port),
            "fingerprint": str(identity.get("fingerprint") or ""),
            "challenge": challenge,
            "expiresAt": utc_from_epoch(expires_at_epoch),
            "ttlSeconds": ttl,
            "trustedLanOnly": True,
        }
        self._pending[challenge] = {
            "challenge": challenge,
            "createdAt": utc_now_iso(),
            "expiresAtEpoch": expires_at_epoch,
            "payload": dict(payload),
            "used": False,
        }
        self.prune_expired()
        return payload

    def consume_challenge(self, challenge: str) -> Dict[str, Any]:
        self.prune_expired()
        value = str(challenge or "").strip()
        if not value:
            return {"ok": False, "reason": "missing_challenge"}
        item = self._pending.get(value)
        if not isinstance(item, dict):
            return {"ok": False, "reason": "unknown_challenge"}
        if bool(item.get("used")):
            return {"ok": False, "reason": "challenge_already_used"}
        try:
            expires_at = float(item.get("expiresAtEpoch") or 0.0)
        except (TypeError, ValueError, OverflowError):
            expires_at = 0.0
        if expires_at <= time.time():
            self._pending.pop(value, None)
            return {"ok": False, "reason": "challenge_expired"}
        item["used"] = True
        self._pending.pop(value, None)
        return {"ok": True, "payload": dict(item.get("payload") or {})}

    def prune_expired(self) -> int:
        now = time.time()
        expired = []
        for key, value in self._pending.items():
            try:
                expires_at = float(value.get("expiresAtEpoch") or 0.0)
            except (TypeError, ValueError, OverflowError):
                expires_at = 0.0
            if expires_at <= now:
                expired.append(key)
        for key in expired:
            self._pending.pop(key, None)
        return len(expired)

    def pending_count(self) -> int:
        self.prune_expired()
        return len(self._pending)

    def next_expiry_epoch(self) -> float:
        self.prune_expired()
        values = []
        for item in self._pending.values():
            try:
                values.append(float(item.get("expiresAtEpoch") or 0.0))
            except (TypeError, ValueError, OverflowError):
                pass
        return min(values) if values else 0.0


def utc_from_epoch(value: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
