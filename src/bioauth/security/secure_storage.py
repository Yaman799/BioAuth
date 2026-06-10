from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any, Callable, Dict, Tuple

from security import atomic_write_text, get_cipher, get_or_create_key

STORAGE_FORMAT_VERSION = 2
ALGORITHM = "fernet-hmac-sha256"
DEFAULT_KEY_ID = "local-user-v1"
ENVELOPE_KEYS = {"storage_format_version", "encrypted", "algorithm", "key_id", "payload", "hmac"}
_HMAC_CONTEXT = b"bioauth.secure-json-envelope.v2"


class SecureEnvelopeError(ValueError):
    """Base class for encrypted envelope failures."""


class SecureEnvelopeIntegrityError(SecureEnvelopeError):
    """Raised when payload or HMAC integrity validation fails."""


def _hmac_key() -> bytes:
    return hmac.new(get_or_create_key(), _HMAC_CONTEXT, hashlib.sha256).digest()


def _canonical_hmac_body(envelope: Dict[str, Any]) -> bytes:
    body = {
        "storage_format_version": int(envelope.get("storage_format_version") or STORAGE_FORMAT_VERSION),
        "encrypted": bool(envelope.get("encrypted", True)),
        "algorithm": str(envelope.get("algorithm") or ALGORITHM),
        "key_id": str(envelope.get("key_id") or DEFAULT_KEY_ID),
        "payload": str(envelope.get("payload") or ""),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_envelope(envelope: Dict[str, Any]) -> str:
    return hmac.new(_hmac_key(), _canonical_hmac_body(envelope), hashlib.sha256).hexdigest()


def is_envelope_candidate(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    return bool(data.get("encrypted") is True and data.get("payload") and data.get("hmac"))


def envelope_plaintext_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k): v for k, v in (data or {}).items() if str(k) not in ENVELOPE_KEYS}


def build_envelope(payload: Dict[str, Any], *, key_id: str = DEFAULT_KEY_ID) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("secure envelope payload must be a dict")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    token = get_cipher().encrypt(raw).decode("ascii")
    envelope: Dict[str, Any] = {
        "storage_format_version": STORAGE_FORMAT_VERSION,
        "encrypted": True,
        "algorithm": ALGORITHM,
        "key_id": str(key_id or DEFAULT_KEY_ID),
        "payload": token,
    }
    envelope["hmac"] = sign_envelope(envelope)
    return envelope


def decrypt_envelope(envelope: Dict[str, Any]) -> Dict[str, Any]:
    if not is_envelope_candidate(envelope):
        raise SecureEnvelopeIntegrityError("encrypted envelope metadata is incomplete")
    if int(envelope.get("storage_format_version") or STORAGE_FORMAT_VERSION) != STORAGE_FORMAT_VERSION:
        raise SecureEnvelopeIntegrityError("unsupported encrypted envelope version")
    if envelope.get("encrypted") is not True:
        raise SecureEnvelopeIntegrityError("encrypted envelope flag is not true")
    if str(envelope.get("algorithm") or "") != ALGORITHM:
        raise SecureEnvelopeIntegrityError("unsupported encrypted envelope algorithm")
    if not str(envelope.get("key_id") or "").strip():
        raise SecureEnvelopeIntegrityError("encrypted envelope key id is missing")
    supplied = str(envelope.get("hmac") or "")
    expected = sign_envelope(envelope)
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise SecureEnvelopeIntegrityError("encrypted envelope HMAC validation failed")
    try:
        decrypted = get_cipher().decrypt(str(envelope.get("payload") or "").encode("ascii"))
        payload = json.loads(decrypted.decode("utf-8") or "{}")
    except Exception as exc:
        raise SecureEnvelopeIntegrityError("encrypted envelope payload could not be decrypted") from exc
    if not isinstance(payload, dict):
        raise SecureEnvelopeIntegrityError("encrypted envelope payload is not an object")
    return payload


def write_enveloped_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    envelope = build_envelope(dict(payload or {}))
    atomic_write_text(path, json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return envelope


def load_enveloped_json(
    path: str,
    default: Dict[str, Any] | None = None,
    *,
    coerce: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    rewrite_migrated: bool = True,
) -> Tuple[Dict[str, Any], str]:
    """Load a JSON object that may be legacy plaintext, mixed, or clean envelope v2.

    Returns ``(payload, state)`` where state is one of: missing, envelope_v2,
    legacy_plaintext_migrated, or mixed_envelope_migrated.
    Clean and mixed envelopes must pass HMAC validation before any plaintext sidecar
    fields are trusted. This avoids silently accepting attacker-edited premium or
    security posture fields after envelope tampering.
    """
    fallback = dict(default or {})
    if not os.path.exists(path):
        return (coerce(fallback) if coerce else fallback), "missing"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        raise SecureEnvelopeIntegrityError("secure JSON file is not valid JSON") from exc
    if not isinstance(data, dict):
        raise SecureEnvelopeIntegrityError("secure JSON root is not an object")

    if is_envelope_candidate(data):
        decrypted = decrypt_envelope(data)
        plaintext = envelope_plaintext_fields(data)
        if plaintext:
            merged = dict(decrypted)
            merged.update(plaintext)
            payload = coerce(merged) if coerce else merged
            if rewrite_migrated:
                write_enveloped_json(path, payload)
            return payload, "mixed_envelope_migrated"
        payload = coerce(decrypted) if coerce else decrypted
        return payload, "envelope_v2"

    payload = coerce(dict(data)) if coerce else dict(data)
    if rewrite_migrated:
        write_enveloped_json(path, payload)
    return payload, "legacy_plaintext_migrated"
