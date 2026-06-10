from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from auth import build_local_session_state, restore_local_session
from paths import remembered_login_file
from security import sign_persistent_login_payload, verify_persistent_login_payload

LOGIN_STATE_FILE = remembered_login_file()
REMEMBERED_LOGIN_TTL_SECONDS = 30 * 24 * 60 * 60


def _safe_json_load(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


def _safe_json_write(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def clear_persistent_login() -> None:
    try:
        if os.path.exists(LOGIN_STATE_FILE):
            os.remove(LOGIN_STATE_FILE)
    except OSError:
        pass


def remember_user(user_id: str, *, ttl_seconds: int = REMEMBERED_LOGIN_TTL_SECONDS) -> bool:
    snapshot = build_local_session_state(user_id)
    if not snapshot:
        clear_persistent_login()
        return False
    now = time.time()
    ttl = max(0, int(ttl_seconds))
    payload: Dict[str, Any] = {
        **snapshot,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "expires_at": now + ttl if ttl > 0 else now,
    }
    payload["_integrity"] = sign_persistent_login_payload(payload)
    try:
        _safe_json_write(LOGIN_STATE_FILE, payload)
        return True
    except OSError:
        return False


def restore_remembered_user() -> Optional[Dict[str, Any]]:
    data = _safe_json_load(LOGIN_STATE_FILE, {})
    if not isinstance(data, dict) or not data:
        return None
    if not verify_persistent_login_payload(data):
        clear_persistent_login()
        return None
    try:
        expires_at = float(data.get("expires_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        clear_persistent_login()
        return None
    if expires_at <= time.time():
        clear_persistent_login()
        return None
    result = restore_local_session(
        str(data.get("user_id") or ""),
        str(data.get("password_changed_at") or ""),
    )
    if result.get("ok"):
        return result.get("user")
    clear_persistent_login()
    return None
