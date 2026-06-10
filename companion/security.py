from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

TOKEN_PREFIX = "bioauth_companion_"


def generate_device_token() -> str:
    """Return a high-entropy bearer token for one paired mobile device."""

    return TOKEN_PREFIX + secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    value = str(token or "").strip()
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def token_matches(token: str, stored_hash: str) -> bool:
    expected = str(stored_hash or "").strip().lower()
    actual = hash_token(token)
    if not expected or not actual:
        return False
    return hmac.compare_digest(actual, expected)


def bearer_token_from_header(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower().startswith("bearer "):
        return text[7:].strip()
    return ""
