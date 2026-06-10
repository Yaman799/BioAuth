from __future__ import annotations

import secrets
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from .security import generate_device_token, hash_token, token_matches

LoadSettings = Callable[[], Dict[str, Any]]
SaveSettings = Callable[[Dict[str, Any]], Dict[str, Any]]

REGISTRY_KEY = "companion_device_registry_v1"
IDENTITY_KEY = "companion_desktop_identity_v1"
DEFAULT_SCOPES = ["status:read", "alerts:read", "live:read"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_device_name(value: Any) -> str:
    text = str(value or "").strip()
    return text[:80] if text else "BioAuth Companion"


class CompanionDeviceRegistry:
    """Persistent paired-device registry.

    The registry stores only token hashes.  Raw device tokens are returned once
    during pairing and are never persisted in app settings.
    """

    def __init__(self, load_settings: LoadSettings, save_settings: SaveSettings) -> None:
        self._load_settings = load_settings
        self._save_settings = save_settings

    def _settings(self) -> Dict[str, Any]:
        try:
            settings = self._load_settings()
            return dict(settings or {})
        except Exception:
            return {}

    def _write(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return dict(self._save_settings(settings) or settings)
        except Exception:
            return settings

    def _registry_payload(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        base = dict(settings if isinstance(settings, dict) else self._settings())
        payload = base.get(REGISTRY_KEY)
        if not isinstance(payload, dict):
            payload = {}
        devices = payload.get("devices")
        if not isinstance(devices, list):
            devices = []
        return {"schemaVersion": 1, "devices": [dict(item) for item in devices if isinstance(item, dict)]}

    def desktop_identity(self, *, display_name: str = "") -> Dict[str, Any]:
        settings = self._settings()
        identity = settings.get(IDENTITY_KEY)
        if not isinstance(identity, dict):
            identity = {}
        secret = str(identity.get("secret") or "").strip()
        if not secret:
            secret = secrets.token_urlsafe(32)
        device_id = str(identity.get("deviceId") or "").strip()
        if not device_id:
            device_id = "desktop-" + uuid.uuid4().hex[:12]
        name = str(display_name or identity.get("displayName") or socket.gethostname() or "BioAuth Desktop").strip()
        fingerprint = "sha256:" + hash_token(secret)[:32]
        next_identity = {
            "schemaVersion": 1,
            "deviceId": device_id,
            "displayName": name,
            "fingerprint": fingerprint,
            "secret": secret,
            "updatedAt": utc_now_iso(),
        }
        settings[IDENTITY_KEY] = dict(next_identity)
        self._write(settings)
        safe = dict(next_identity)
        safe.pop("secret", None)
        return safe

    def list_devices(self, *, include_revoked: bool = False) -> List[Dict[str, Any]]:
        payload = self._registry_payload()
        result: List[Dict[str, Any]] = []
        for item in payload.get("devices", []):
            if not include_revoked and bool(item.get("revoked")):
                continue
            safe = dict(item)
            safe.pop("tokenHash", None)
            result.append(safe)
        return result

    def active_device_count(self) -> int:
        return len(self.list_devices(include_revoked=False))

    def pair_device(self, *, device_name: str = "", device_id: str = "", scopes: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        settings = self._settings()
        registry = self._registry_payload(settings)
        token = generate_device_token()
        now = utc_now_iso()
        resolved_id = str(device_id or "").strip() or "phone-" + uuid.uuid4().hex[:12]
        resolved_scopes = [str(item) for item in (scopes or DEFAULT_SCOPES) if str(item).strip()]
        record = {
            "schemaVersion": 1,
            "deviceId": resolved_id,
            "displayName": _normalize_device_name(device_name),
            "tokenHash": hash_token(token),
            "scopes": resolved_scopes,
            "createdAt": now,
            "lastSeenAt": "",
            "revoked": False,
            "revokedAt": "",
        }
        devices = [item for item in registry.get("devices", []) if str(item.get("deviceId") or "") != resolved_id]
        devices.append(record)
        settings[REGISTRY_KEY] = {"schemaVersion": 1, "devices": devices}
        self._write(settings)
        safe = dict(record)
        safe.pop("tokenHash", None)
        return {"ok": True, "device": safe, "deviceToken": token}

    def validate_token(self, token: str, *, required_scope: str = "status:read", touch: bool = True) -> Dict[str, Any]:
        raw = str(token or "").strip()
        if not raw:
            return {"ok": False, "reason": "missing_token"}
        settings = self._settings()
        registry = self._registry_payload(settings)
        devices = registry.get("devices", [])
        changed = False
        for item in devices:
            if bool(item.get("revoked")):
                continue
            if not token_matches(raw, str(item.get("tokenHash") or "")):
                continue
            scopes = [str(scope) for scope in item.get("scopes", [])]
            if required_scope and required_scope not in scopes:
                return {"ok": False, "reason": "scope_denied"}
            if touch:
                item["lastSeenAt"] = utc_now_iso()
                changed = True
            if changed:
                settings[REGISTRY_KEY] = {"schemaVersion": 1, "devices": devices}
                self._write(settings)
            safe = dict(item)
            safe.pop("tokenHash", None)
            return {"ok": True, "device": safe}
        return {"ok": False, "reason": "invalid_token"}

    def revoke_device(self, device_id: str) -> Dict[str, Any]:
        target = str(device_id or "").strip()
        if not target:
            return {"ok": False, "reason": "missing_device_id"}
        settings = self._settings()
        registry = self._registry_payload(settings)
        changed = False
        now = utc_now_iso()
        for item in registry.get("devices", []):
            if str(item.get("deviceId") or "") == target and not bool(item.get("revoked")):
                item["revoked"] = True
                item["revokedAt"] = now
                changed = True
        if changed:
            settings[REGISTRY_KEY] = registry
            self._write(settings)
        return {"ok": changed, "deviceId": target, "reason": "revoked" if changed else "not_found"}

    def revoke_token(self, token: str) -> Dict[str, Any]:
        validation = self.validate_token(token, required_scope="status:read", touch=False)
        if not validation.get("ok"):
            return validation
        device = validation.get("device") if isinstance(validation.get("device"), dict) else {}
        return self.revoke_device(str(device.get("deviceId") or ""))

    def revoke_all(self) -> Dict[str, Any]:
        settings = self._settings()
        registry = self._registry_payload(settings)
        now = utc_now_iso()
        count = 0
        for item in registry.get("devices", []):
            if not bool(item.get("revoked")):
                item["revoked"] = True
                item["revokedAt"] = now
                count += 1
        settings[REGISTRY_KEY] = registry
        self._write(settings)
        return {"ok": True, "revokedCount": count}
