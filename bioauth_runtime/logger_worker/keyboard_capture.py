"""Keyboard event normalization for the logger worker."""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from security import get_or_create_key


def privacy_safe_key(key: Any) -> str:
    """Return a stable HMAC key identifier without storing typed text."""
    raw = str(key)
    secret = get_or_create_key()
    digest = hmac.new(secret, raw.encode("utf-8", errors="ignore"), hashlib.sha256).hexdigest()[:32]
    return f"k_{digest}"


def keyboard_row(key: Any, event: str, timestamp: float | None = None) -> list[object]:
    return [privacy_safe_key(key), str(event), timestamp if timestamp is not None else time.time()]
