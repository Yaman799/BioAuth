from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Any, Dict, Tuple

PASSCODE_MIN_LEN = 4
PASSCODE_MAX_LEN = 8
PASSCODE_ITERATIONS = 200_000


def normalize_passcode(value: str) -> str:
    return str(value or "").strip()


def validate_passcode_value(value: str) -> Tuple[bool, str]:
    code = normalize_passcode(value)
    if not code:
        return False, "app_passcode_empty"
    if not code.isdigit():
        return False, "app_passcode_digits_only"
    if len(code) < PASSCODE_MIN_LEN or len(code) > PASSCODE_MAX_LEN:
        return False, "app_passcode_length"
    return True, ""


def _pbkdf2_sha256(passcode: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", normalize_passcode(passcode).encode("utf-8"), salt, int(iterations))


def build_passcode_record(passcode: str, *, iterations: int = PASSCODE_ITERATIONS) -> Dict[str, Any]:
    salt = secrets.token_bytes(16)
    digest = _pbkdf2_sha256(passcode, salt, iterations)
    return {
        "version": 1,
        "algorithm": "pbkdf2_sha256",
        "iterations": int(iterations),
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": base64.b64encode(digest).decode("ascii"),
    }


def is_passcode_configured(record: Dict[str, Any] | None) -> bool:
    if not isinstance(record, dict):
        return False
    return bool(record.get("salt")) and bool(record.get("hash")) and int(record.get("iterations") or 0) > 0


def verify_passcode_record(record: Dict[str, Any] | None, passcode: str) -> bool:
    if not is_passcode_configured(record):
        return False
    try:
        salt = base64.b64decode(str(record.get("salt") or ""), validate=True)
        expected = base64.b64decode(str(record.get("hash") or ""), validate=True)
        iterations = int(record.get("iterations") or PASSCODE_ITERATIONS)
    except (TypeError, ValueError):
        return False
    actual = _pbkdf2_sha256(passcode, salt, iterations)
    return hmac.compare_digest(actual, expected)
