"""Local account management for the BioAuth desktop beta."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from paths import account_creation_limits_file, lockouts_file, users_file
from secure_storage import SecureEnvelopeIntegrityError, build_envelope, load_enveloped_json, write_enveloped_json
from utils.identity import slugify_username

MAX_LOGIN_FAILS = 5
LOCKOUT_SECONDS = 300
MAX_RECOVERY_FAILS = 5
RECOVERY_LOCKOUT_SECONDS = 600
RECOVERY_CODE_ITERATIONS = 200_000
RECOVERY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RECOVERY_CODE_GROUP_SIZE = 4
RECOVERY_CODE_GROUPS = 4
CREATE_USER_COOLDOWN_SECONDS = 3
CREATE_USER_WINDOW_SECONDS = 600
CREATE_USER_MAX_IN_WINDOW = 5
NEW_USER_ONBOARDING_VERSION = "v1"
_AUTH_LOCK = threading.RLock()
_login_failures: Dict[str, Dict[str, Any]] = {}
_lockouts_loaded = False
_LAST_USERS_STORAGE_ERROR = ""
_LAST_USERS_STORAGE_STATE = "unknown"
LOGGER = logging.getLogger(__name__)


def _users_file() -> str:
    return users_file()


def _lockouts_file() -> str:
    return lockouts_file()


def _creation_limits_file() -> str:
    return account_creation_limits_file()


def _safe_json_load(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Failed loading local JSON state %s; using safe default.", os.path.basename(path), exc_info=True)
        return default


def _safe_json_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _normalize_email(email: Any) -> str:
    return str(email or "").strip().lower()


def _normalize_recovery_code(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _format_recovery_code(raw_code: str) -> str:
    normalized = _normalize_recovery_code(raw_code)
    if not normalized:
        return ""
    size = max(1, int(RECOVERY_CODE_GROUP_SIZE))
    return "-".join(normalized[index:index + size] for index in range(0, len(normalized), size))


def _generate_recovery_code() -> str:
    raw = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(RECOVERY_CODE_GROUP_SIZE * RECOVERY_CODE_GROUPS))
    return _format_recovery_code(raw)


def _hash_secret(value: str, salt: bytes, iterations: int) -> str:
    derived = hashlib.pbkdf2_hmac("sha256", str(value or "").encode("utf-8"), salt, int(iterations))
    return base64.b64encode(derived).decode("ascii")


def _build_recovery_record(code: str, *, iterations: int = RECOVERY_CODE_ITERATIONS) -> Dict[str, Any]:
    salt = secrets.token_bytes(16)
    normalized = _normalize_recovery_code(code)
    return {
        "version": 1,
        "algorithm": "pbkdf2_sha256",
        "iterations": int(iterations),
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": _hash_secret(normalized, salt, iterations),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _has_recovery_record(user: Optional[Dict[str, Any]]) -> bool:
    record = (user or {}).get("password_recovery") if isinstance(user, dict) else None
    if not isinstance(record, dict):
        return False
    return bool(record.get("salt")) and bool(record.get("hash")) and int(record.get("iterations") or 0) > 0


def _verify_recovery_code(user: Dict[str, Any], recovery_code: str) -> bool:
    record = (user or {}).get("password_recovery")
    if not _has_recovery_record(user):
        return False
    try:
        salt = base64.b64decode(str(record.get("salt") or ""), validate=True)
        expected = str(record.get("hash") or "")
        iterations = int(record.get("iterations") or RECOVERY_CODE_ITERATIONS)
    except (TypeError, ValueError):
        return False
    actual = _hash_secret(_normalize_recovery_code(recovery_code), salt, iterations)
    return hmac.compare_digest(expected, actual)


def _issue_recovery_code(user: Dict[str, Any]) -> str:
    code = _generate_recovery_code()
    record = _build_recovery_record(code)
    existing = user.get("password_recovery") if isinstance(user.get("password_recovery"), dict) else {}
    if existing.get("created_at") and not record.get("created_at"):
        record["created_at"] = existing.get("created_at")
    if existing:
        record["rotated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        record.setdefault("created_at", str(existing.get("created_at") or record["rotated_at"]))
    user["password_recovery"] = record
    return code


def _find_user_by_password_reset_identifier(users: Dict[str, Dict[str, Any]], identifier: Any) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
    raw_identifier = str(identifier or "").strip()
    if not raw_identifier:
        return None, None, "required"
    if "@" in raw_identifier:
        normalized_email = _normalize_email(raw_identifier)
        if not _is_valid_email(normalized_email):
            return None, None, "invalid"
        matches = _find_users_by_email(users, normalized_email)
        if len(matches) != 1:
            return None, None, "unavailable"
        user = matches[0]
        user_id = slugify_username(user.get("user_id") or user.get("username") or "") or None
        return user_id, user, "ok" if user_id else "unavailable"

    user_id = slugify_username(raw_identifier)
    if not user_id:
        return None, None, "invalid"
    user = users.get(user_id)
    if not user:
        return None, None, "unavailable"
    return user_id, user, "ok"


def _is_valid_email(email: str) -> bool:
    value = _normalize_email(email)
    if not value or "@" not in value:
        return False
    local, _, domain = value.partition("@")
    return bool(local and domain and "." in domain and not domain.startswith(".") and not domain.endswith("."))


def _normalize_user_record(user_id: str, raw: Any) -> Tuple[Dict[str, Any], bool]:
    changed = False
    if isinstance(raw, dict):
        record = dict(raw)
    else:
        record = {"user_id": str(user_id)}
        changed = True

    normalized_user_id = slugify_username(record.get("user_id") or user_id) or str(user_id)
    if record.get("user_id") != normalized_user_id:
        record["user_id"] = normalized_user_id
        changed = True

    normalized_email = _normalize_email(record.get("email"))
    if normalized_email:
        if record.get("email") != normalized_email:
            record["email"] = normalized_email
            changed = True
    elif "email" in record:
        record.pop("email", None)
        changed = True

    recovery_record = record.get("password_recovery")
    if recovery_record is None:
        pass
    elif not isinstance(recovery_record, dict):
        record.pop("password_recovery", None)
        changed = True

    return record, changed


def _normalize_users_payload(data: Any) -> Tuple[Dict[str, Dict[str, Any]], bool]:
    if not isinstance(data, dict):
        return {}, bool(data)

    normalized: Dict[str, Dict[str, Any]] = {}
    changed = False
    for raw_user_id, raw_record in data.items():
        user_id = slugify_username(raw_user_id) or str(raw_user_id)
        if user_id != str(raw_user_id):
            changed = True
        record, record_changed = _normalize_user_record(user_id, raw_record)
        normalized[user_id] = record
        changed = changed or record_changed
    return normalized, changed


def _find_user_id_by_email(users: Dict[str, Dict[str, Any]], email: Any, *, exclude_user_id: str = "") -> Optional[str]:
    normalized_email = _normalize_email(email)
    normalized_exclude = slugify_username(exclude_user_id) if exclude_user_id else ""
    if not normalized_email:
        return None
    for raw_user_id, raw_user in (users or {}).items():
        user_id = slugify_username(raw_user_id) or str(raw_user_id)
        if normalized_exclude and user_id == normalized_exclude:
            continue
        if _normalize_email((raw_user or {}).get("email")) == normalized_email:
            return user_id
    return None


def _find_users_by_email(users: Dict[str, Dict[str, Any]], email: Any) -> List[Dict[str, Any]]:
    normalized_email = _normalize_email(email)
    if not normalized_email:
        return []
    matches: List[Dict[str, Any]] = []
    for raw_user in (users or {}).values():
        if _normalize_email((raw_user or {}).get("email")) == normalized_email:
            matches.append(dict(raw_user or {}))
    return matches


def _build_username_hint(username: Any) -> str:
    value = str(username or "").strip()
    if not value:
        return ""
    if len(value) <= 2:
        return f"{value}..."
    if len(value) <= 4:
        return f"{value[:2]}..."
    return f"{value[:2]}***{value[-2:]}"


def _coerce_users_payload(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    normalized, _ = _normalize_users_payload(data)
    return normalized


def get_last_users_storage_error() -> str:
    return _LAST_USERS_STORAGE_ERROR


def get_last_users_storage_state() -> str:
    return _LAST_USERS_STORAGE_STATE


def _build_users_envelope_for_tests(users: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return build_envelope(_coerce_users_payload(users))


def _load_users() -> Dict[str, Dict[str, Any]]:
    global _LAST_USERS_STORAGE_ERROR, _LAST_USERS_STORAGE_STATE
    try:
        data, state = load_enveloped_json(_users_file(), {}, coerce=_coerce_users_payload, rewrite_migrated=True)
        normalized, changed = _normalize_users_payload(data)
        if changed:
            write_enveloped_json(_users_file(), normalized)
            state = "normalized_envelope_v2"
        _LAST_USERS_STORAGE_STATE = state
        _LAST_USERS_STORAGE_ERROR = ""
        return normalized
    except SecureEnvelopeIntegrityError as exc:
        _LAST_USERS_STORAGE_STATE = "integrity_error"
        _LAST_USERS_STORAGE_ERROR = "Users file failed encrypted envelope integrity validation."
        LOGGER.warning("Users file failed encrypted envelope integrity validation; using empty user store.", exc_info=True)
        return {}
    except Exception as exc:
        _LAST_USERS_STORAGE_STATE = "load_error"
        _LAST_USERS_STORAGE_ERROR = "Users file could not be loaded."
        LOGGER.warning("Users file could not be loaded; using empty user store.", exc_info=True)
        return {}


def _save_users(users: Dict[str, Dict[str, Any]]) -> None:
    global _LAST_USERS_STORAGE_ERROR, _LAST_USERS_STORAGE_STATE
    normalized, _ = _normalize_users_payload(users)
    write_enveloped_json(_users_file(), normalized)
    _LAST_USERS_STORAGE_STATE = "envelope_v2"
    _LAST_USERS_STORAGE_ERROR = ""


def _prune_lockouts(data: Dict[str, Dict[str, Any]], now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    current = time.time() if now is None else float(now)
    cleaned: Dict[str, Dict[str, Any]] = {}
    for user_id, raw in (data or {}).items():
        if not isinstance(raw, dict):
            continue
        locked_until = float(raw.get("locked_until", 0.0) or 0.0)
        fails = int(raw.get("fails", 0) or 0)
        recovery_locked_until = float(raw.get("recovery_locked_until", 0.0) or 0.0)
        recovery_fails = int(raw.get("recovery_fails", 0) or 0)
        if locked_until > current or fails > 0 or recovery_locked_until > current or recovery_fails > 0:
            cleaned[str(user_id)] = {
                "fails": fails,
                "locked_until": locked_until,
                "recovery_fails": recovery_fails,
                "recovery_locked_until": recovery_locked_until,
            }
    return cleaned


def _load_lockouts() -> Dict[str, Dict[str, Any]]:
    global _login_failures, _lockouts_loaded
    with _AUTH_LOCK:
        try:
            data, _state = load_enveloped_json(_lockouts_file(), {}, rewrite_migrated=True)
        except SecureEnvelopeIntegrityError:
            LOGGER.warning("Lockouts file failed integrity check; resetting lockout state.", exc_info=True)
            data = {}
        except Exception:
            data = _safe_json_load(_lockouts_file(), {})
        parsed = data if isinstance(data, dict) else {}
        cleaned = _prune_lockouts(parsed)
        _login_failures = cleaned
        _lockouts_loaded = True
        if cleaned != parsed:
            _persist_lockouts()
        return dict(_login_failures)


def _ensure_lockouts_loaded() -> None:
    if _lockouts_loaded:
        return
    _load_lockouts()


def _persist_lockouts() -> None:
    try:
        write_enveloped_json(_lockouts_file(), _prune_lockouts(_login_failures))
    except Exception:
        LOGGER.warning("Failed persisting lockouts; using plaintext fallback.", exc_info=True)
        _safe_json_write(_lockouts_file(), _prune_lockouts(_login_failures))


def _clear_lockout(user_id: str) -> None:
    with _AUTH_LOCK:
        _ensure_lockouts_loaded()
        if user_id in _login_failures:
            _login_failures.pop(user_id, None)
            _persist_lockouts()


def _clear_recovery_lockout(user_id: str) -> None:
    with _AUTH_LOCK:
        _ensure_lockouts_loaded()
        entry = dict(_login_failures.get(user_id) or {})
        if not entry:
            return
        entry["recovery_fails"] = 0
        entry["recovery_locked_until"] = 0.0
        if int(entry.get("fails", 0) or 0) <= 0 and float(entry.get("locked_until", 0.0) or 0.0) <= 0.0:
            _login_failures.pop(user_id, None)
        else:
            _login_failures[user_id] = entry
        _persist_lockouts()


def _password_policy_error(password: str, *, too_short_key: str, too_short_message: str, needs_mix_key: str, needs_mix_message: str) -> Optional[Dict[str, Any]]:
    value = str(password or "")
    if len(value) < 10:
        return _auth_result(False, too_short_key, too_short_message, message_params={"minimum": 10})
    if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
        return _auth_result(False, needs_mix_key, needs_mix_message)
    return None


def _recovery_locked_result(now: float, locked_until: float) -> Dict[str, Any]:
    remaining = int(max(0, locked_until - now))
    mins = max(1, remaining // 60)
    return _auth_result(False, "auth_password_reset_locked", f"Too many recovery attempts. Try again in about {mins} minute(s).", message_params={"minutes": mins})


def _record_recovery_failure(user_id: str, now: float) -> None:
    rec = dict(_login_failures.get(user_id) or {})
    rec["recovery_fails"] = int(rec.get("recovery_fails", 0) or 0) + 1
    rec["recovery_locked_until"] = 0.0
    if rec["recovery_fails"] >= MAX_RECOVERY_FAILS:
        rec["recovery_locked_until"] = now + RECOVERY_LOCKOUT_SECONDS
        rec["recovery_fails"] = 0
    _login_failures[user_id] = rec
    _persist_lockouts()


def _load_creation_limits() -> Dict[str, Any]:
    data = _safe_json_load(_creation_limits_file(), {})
    return data if isinstance(data, dict) else {}


def _prune_creation_limits(data: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    current = time.time() if now is None else float(now)
    recent = data.get("recent_creations", []) if isinstance(data, dict) else []
    if not isinstance(recent, list):
        recent = []
    pruned = [float(ts) for ts in recent if current - float(ts) <= CREATE_USER_WINDOW_SECONDS]
    last_created_at = 0.0
    if pruned:
        last_created_at = max(pruned)
    elif isinstance(data, dict):
        try:
            last_created_at = float(data.get("last_created_at", 0.0) or 0.0)
        except (TypeError, ValueError, OverflowError):
            last_created_at = 0.0
    return {"last_created_at": last_created_at, "recent_creations": pruned}


def _save_creation_limits(data: Dict[str, Any]) -> None:
    _safe_json_write(_creation_limits_file(), _prune_creation_limits(data))


def _account_creation_throttle_message(state: Dict[str, Any], now: float) -> Optional[Dict[str, Any]]:
    pruned = _prune_creation_limits(state, now=now)
    last_created_at = float(pruned.get("last_created_at", 0.0) or 0.0)
    if last_created_at and (now - last_created_at) < CREATE_USER_COOLDOWN_SECONDS:
        remaining = max(1, int(round(CREATE_USER_COOLDOWN_SECONDS - (now - last_created_at))))
        return _auth_result(False, "auth_create_wait_seconds", f"Please wait {remaining} second(s) before creating another account.", message_params={"remaining": remaining})

    recent = pruned.get("recent_creations", [])
    if len(recent) >= CREATE_USER_MAX_IN_WINDOW:
        oldest_kept = float(recent[0])
        remaining = max(1, int(round(CREATE_USER_WINDOW_SECONDS - (now - oldest_kept))))
        mins = max(1, (remaining + 59) // 60)
        return _auth_result(False, "auth_create_wait_minutes", f"Too many accounts were created recently. Try again in about {mins} minute(s).", message_params={"minutes": mins})
    return None


def _record_account_creation(state: Dict[str, Any], now: float) -> Dict[str, Any]:
    pruned = _prune_creation_limits(state, now=now)
    recent = list(pruned.get("recent_creations", []))
    recent.append(now)
    return {"last_created_at": now, "recent_creations": recent}


def _auth_result(ok: bool, key: str, message: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ok": bool(ok), "message_key": key, "message": message}
    message_params = extra.pop("message_params", None)
    if isinstance(message_params, dict) and message_params:
        payload["message_params"] = dict(message_params)
    payload.update(extra)
    return payload


def _coerce_onboarding_state(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    record = dict(user or {})
    pending = record.get("onboarding_pending", None)
    completed_at = str(record.get("onboarding_completed_at") or "").strip()
    do_not_show = bool(record.get("onboarding_do_not_show_again", False))
    skipped_at = str(record.get("onboarding_skipped_at") or "").strip()
    version = str(record.get("onboarding_version") or NEW_USER_ONBOARDING_VERSION).strip() or NEW_USER_ONBOARDING_VERSION

    if pending is None:
        pending = False
    pending_bool = bool(pending) and not completed_at and not do_not_show

    record["onboarding_pending"] = pending_bool
    record["onboarding_completed_at"] = completed_at or None
    record["onboarding_do_not_show_again"] = do_not_show
    record["onboarding_skipped_at"] = skipped_at or None
    record["onboarding_version"] = version
    return record


def user_requires_onboarding(user: Optional[Dict[str, Any]]) -> bool:
    state = _coerce_onboarding_state(user)
    return bool(state.get("onboarding_pending")) and not bool(state.get("onboarding_do_not_show_again"))


def _hash_password(password: str, salt: bytes) -> str:
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return base64.b64encode(derived).decode("ascii")


def _verify_password(user: Dict[str, Any], password: str) -> bool:
    try:
        salt = base64.b64decode(user["password_salt"])
        expected = user["password_hash"]
    except (KeyError, TypeError, ValueError, binascii.Error):
        return False
    actual = _hash_password(password, salt)
    return hmac.compare_digest(expected, actual)


def create_user(username: str, password: str, display_name: str = "", email: str = "", *, require_email: bool = False) -> Dict[str, Any]:
    user_id = slugify_username(username)
    if not user_id:
        return _auth_result(False, "auth_invalid_username", "Please enter a valid username.")
    pw = password or ""
    policy_error = _password_policy_error(
        pw,
        too_short_key="auth_password_too_short",
        too_short_message="Password must be at least 10 characters.",
        needs_mix_key="auth_password_needs_letter_number",
        needs_mix_message="Password must include at least one letter and one number.",
    )
    if policy_error:
        return policy_error

    normalized_email = _normalize_email(email)
    if require_email and not normalized_email:
        return _auth_result(False, "auth_email_required", "Please enter an email address.")
    if normalized_email and not _is_valid_email(normalized_email):
        return _auth_result(False, "auth_invalid_email", "Please enter a valid email address.")

    now = time.time()
    with _AUTH_LOCK:
        users = _load_users()
        if user_id in users:
            return _auth_result(False, "auth_username_exists", "Username already exists.")
        if normalized_email and _find_user_id_by_email(users, normalized_email, exclude_user_id=user_id):
            return _auth_result(False, "auth_email_exists", "Email already exists.")

        creation_state = _load_creation_limits()
        throttle_message = _account_creation_throttle_message(creation_state, now=now)
        if throttle_message:
            return throttle_message

        salt = secrets.token_bytes(16)
        users[user_id] = {
            "user_id": user_id,
            "display_name": (display_name or username).strip()[:60],
            "username": username.strip(),
            "email": normalized_email,
            "password_salt": base64.b64encode(salt).decode("ascii"),
            "password_hash": _hash_password(password, salt),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_login_at": None,
            "profile_state": "new",
            "onboarding_pending": True,
            "onboarding_completed_at": None,
            "onboarding_do_not_show_again": False,
            "onboarding_skipped_at": None,
            "onboarding_version": NEW_USER_ONBOARDING_VERSION,
        }
        recovery_code = _issue_recovery_code(users[user_id])
        _save_users(users)
        _save_creation_limits(_record_account_creation(creation_state, now=now))
        return _auth_result(True, "auth_account_created_success", "Account created successfully.", user=public_user(users[user_id]), recovery_code=recovery_code)



def lookup_username_hint_by_email(email: str) -> Dict[str, Any]:
    normalized_email = _normalize_email(email)
    if not normalized_email:
        return _auth_result(False, "auth_username_hint_email_required", "Enter the email you used for this account.")
    if not _is_valid_email(normalized_email):
        return _auth_result(False, "auth_invalid_email", "Please enter a valid email address.")

    with _AUTH_LOCK:
        users = _load_users()
        matches = _find_users_by_email(users, normalized_email)

    if len(matches) != 1:
        return _auth_result(False, "auth_username_hint_unavailable", "We couldn't show a username hint. Check the email and try again.")

    user = matches[0]
    hint = _build_username_hint(user.get("username") or user.get("user_id"))
    if not hint:
        return _auth_result(False, "auth_username_hint_unavailable", "We couldn't show a username hint. Check the email and try again.")

    return _auth_result(
        True,
        "auth_username_hint_ready",
        f"Your username hint: {hint}",
        message_params={"hint": hint},
        hint=hint,
    )


def reveal_username_by_email(email: str, verification_password: str) -> Dict[str, Any]:
    normalized_email = _normalize_email(email)
    if not normalized_email:
        return _auth_result(False, "auth_username_hint_email_required", "Enter the email you used for this account.")
    if not _is_valid_email(normalized_email):
        return _auth_result(False, "auth_invalid_email", "Please enter a valid email address.")

    password = str(verification_password or "").strip()
    if not password:
        return _auth_result(False, "auth_username_reveal_password_required", "Enter your password to show the full username.")

    now = time.time()
    with _AUTH_LOCK:
        _ensure_lockouts_loaded()
        users = _load_users()
        matches = _find_users_by_email(users, normalized_email)
        if len(matches) != 1:
            return _auth_result(False, "auth_username_reveal_unavailable", "We couldn't confirm those details. Check the email and password, then try again.")

        user = matches[0]
        user_id = slugify_username(user.get("user_id") or user.get("username") or "") or "_invalid"
        entry = _login_failures.get(user_id, {"fails": 0, "locked_until": 0.0})
        locked_until = float(entry.get("locked_until", 0.0) or 0.0)
        if now < locked_until:
            remaining = int(max(0, locked_until - now))
            mins = max(1, remaining // 60)
            return _auth_result(False, "auth_login_locked", f"Too many failed attempts. Try again in about {mins} minute(s).", message_params={"minutes": mins})
        if locked_until and locked_until <= now and user_id in _login_failures:
            _login_failures.pop(user_id, None)
            _persist_lockouts()

        ok = _verify_password(user, password)
        if not ok:
            rec = _login_failures.get(user_id, {"fails": 0, "locked_until": 0.0})
            rec["fails"] = int(rec.get("fails", 0) or 0) + 1
            rec["locked_until"] = 0.0
            if rec["fails"] >= MAX_LOGIN_FAILS:
                rec["locked_until"] = now + LOCKOUT_SECONDS
                rec["fails"] = 0
            _login_failures[user_id] = rec
            _persist_lockouts()
            return _auth_result(False, "auth_username_reveal_unavailable", "We couldn't confirm those details. Check the email and password, then try again.")

        _login_failures.pop(user_id, None)
        _persist_lockouts()
        revealed_username = str(user.get("username") or user.get("user_id") or "").strip()
        if not revealed_username:
            return _auth_result(False, "auth_username_reveal_unavailable", "We couldn't confirm those details. Check the email and password, then try again.")
        return _auth_result(True, "auth_username_reveal_ready", f"Full username: {revealed_username}", message_params={"username": revealed_username}, username=revealed_username)


def verify_user(username: str, password: str) -> Dict[str, Any]:
    user_id = slugify_username(username) or "_invalid"
    now = time.time()

    with _AUTH_LOCK:
        _ensure_lockouts_loaded()
        entry = _login_failures.get(user_id, {"fails": 0, "locked_until": 0.0})
        locked_until = float(entry.get("locked_until", 0.0) or 0.0)
        if now < locked_until:
            remaining = int(max(0, locked_until - now))
            mins = max(1, remaining // 60)
            return _auth_result(False, "auth_login_locked", f"Too many failed attempts. Try again in about {mins} minute(s).", message_params={"minutes": mins})
        if locked_until and locked_until <= now and user_id in _login_failures:
            _login_failures.pop(user_id, None)
            _persist_lockouts()

        users = _load_users()
        user = users.get(user_id)
        ok = bool(user and _verify_password(user, password))

        if ok:
            _login_failures.pop(user_id, None)
            _persist_lockouts()
            user = _coerce_onboarding_state(user)
            user["last_login_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            users[user_id] = user
            _save_users(users)
            return _auth_result(
                True,
                "auth_signin_success",
                "Signed in successfully.",
                user=public_user(user),
                onboarding_required=user_requires_onboarding(user),
            )

        rec = _login_failures.get(user_id, {"fails": 0, "locked_until": 0.0})
        rec["fails"] = int(rec.get("fails", 0) or 0) + 1
        rec["locked_until"] = 0.0
        if rec["fails"] >= MAX_LOGIN_FAILS:
            rec["locked_until"] = now + LOCKOUT_SECONDS
            rec["fails"] = 0
        _login_failures[user_id] = rec
        _persist_lockouts()

    return _auth_result(False, "auth_invalid_credentials", "Invalid username or password.")



def change_password(user_id: str, current_password: str, new_password: str) -> Dict[str, Any]:
    safe_id = slugify_username(user_id)
    with _AUTH_LOCK:
        users = _load_users()
        user = users.get(safe_id)
        if not user:
            return _auth_result(False, "auth_account_not_found", "Account not found.")
        if not _verify_password(user, current_password):
            return _auth_result(False, "auth_current_password_incorrect", "Current password is incorrect.")
        policy_error = _password_policy_error(
            new_password,
            too_short_key="auth_new_password_too_short",
            too_short_message="New password must be at least 10 characters.",
            needs_mix_key="auth_new_password_needs_letter_number",
            needs_mix_message="New password must include at least one letter and one number.",
        )
        if policy_error:
            return policy_error

        salt = secrets.token_bytes(16)
        user["password_salt"] = base64.b64encode(salt).decode("ascii")
        user["password_hash"] = _hash_password(new_password, salt)
        user["password_changed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        users[safe_id] = user
        _save_users(users)
    return _auth_result(True, "password_updated", "Password updated successfully.")


def generate_password_recovery_code(user_id: str, current_password: str) -> Dict[str, Any]:
    safe_id = slugify_username(user_id)
    with _AUTH_LOCK:
        users = _load_users()
        user = users.get(safe_id)
        if not user:
            return _auth_result(False, "auth_account_not_found", "Account not found.")
        if not str(current_password or "").strip():
            return _auth_result(False, "auth_password_recovery_current_password_required", "Enter your current password to create a recovery code.")
        if not _verify_password(user, current_password):
            return _auth_result(False, "auth_current_password_incorrect", "Current password is incorrect.")
        recovery_code = _issue_recovery_code(user)
        users[safe_id] = user
        _save_users(users)
    return _auth_result(True, "auth_password_recovery_generated", "A new password recovery code is ready.", recovery_code=recovery_code, user=public_user(user))


def verify_password_reset_recovery(identifier: str, recovery_code: str) -> Dict[str, Any]:
    raw_identifier = str(identifier or "").strip()
    if not raw_identifier:
        return _auth_result(False, "auth_password_reset_identifier_required", "Enter the email or username linked to this account.")
    code = _normalize_recovery_code(recovery_code)
    if not code:
        return _auth_result(False, "auth_password_reset_recovery_required", "Enter your password recovery code.")

    now = time.time()
    with _AUTH_LOCK:
        _ensure_lockouts_loaded()
        users = _load_users()
        user_id, user, status = _find_user_by_password_reset_identifier(users, raw_identifier)
        if status == "invalid":
            return _auth_result(False, "auth_password_reset_identifier_invalid", "Enter a valid email address or username.")
        if not user_id or not user or status != "ok" or not _has_recovery_record(user):
            return _auth_result(False, "auth_password_reset_unavailable", "We couldn't verify those details. Check the identifier and recovery code, then try again.")

        entry = _login_failures.get(user_id, {})
        locked_until = float(entry.get("recovery_locked_until", 0.0) or 0.0)
        if now < locked_until:
            return _recovery_locked_result(now, locked_until)
        if locked_until and locked_until <= now and user_id in _login_failures:
            _clear_recovery_lockout(user_id)

        if not _verify_recovery_code(user, code):
            _record_recovery_failure(user_id, now)
            return _auth_result(False, "auth_password_reset_unavailable", "We couldn't verify those details. Check the identifier and recovery code, then try again.")

        _clear_recovery_lockout(user_id)
        return _auth_result(True, "auth_password_reset_verified", "Recovery verified. You can choose a new password now.")


def reset_password_with_recovery(identifier: str, recovery_code: str, new_password: str) -> Dict[str, Any]:
    raw_identifier = str(identifier or "").strip()
    if not raw_identifier:
        return _auth_result(False, "auth_password_reset_identifier_required", "Enter the email or username linked to this account.")
    code = _normalize_recovery_code(recovery_code)
    if not code:
        return _auth_result(False, "auth_password_reset_recovery_required", "Enter your password recovery code.")

    policy_error = _password_policy_error(
        new_password,
        too_short_key="auth_new_password_too_short",
        too_short_message="New password must be at least 10 characters.",
        needs_mix_key="auth_new_password_needs_letter_number",
        needs_mix_message="New password must include at least one letter and one number.",
    )
    if policy_error:
        return policy_error

    now = time.time()
    with _AUTH_LOCK:
        _ensure_lockouts_loaded()
        users = _load_users()
        user_id, user, status = _find_user_by_password_reset_identifier(users, raw_identifier)
        if status == "invalid":
            return _auth_result(False, "auth_password_reset_identifier_invalid", "Enter a valid email address or username.")
        if not user_id or not user or status != "ok" or not _has_recovery_record(user):
            return _auth_result(False, "auth_password_reset_unavailable", "We couldn't verify those details. Check the identifier and recovery code, then try again.")

        entry = _login_failures.get(user_id, {})
        locked_until = float(entry.get("recovery_locked_until", 0.0) or 0.0)
        if now < locked_until:
            return _recovery_locked_result(now, locked_until)
        if locked_until and locked_until <= now and user_id in _login_failures:
            _clear_recovery_lockout(user_id)

        if not _verify_recovery_code(user, code):
            _record_recovery_failure(user_id, now)
            return _auth_result(False, "auth_password_reset_unavailable", "We couldn't verify those details. Check the identifier and recovery code, then try again.")

        salt = secrets.token_bytes(16)
        user["password_salt"] = base64.b64encode(salt).decode("ascii")
        user["password_hash"] = _hash_password(new_password, salt)
        user["password_changed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        new_recovery_code = _issue_recovery_code(user)
        users[user_id] = user
        _save_users(users)
        _clear_recovery_lockout(user_id)
    return _auth_result(True, "auth_password_reset_success", "Password updated successfully.", recovery_code=new_recovery_code)


def mark_profile_state(user_id: str, state: str) -> None:
    safe_id = slugify_username(user_id)
    with _AUTH_LOCK:
        users = _load_users()
        user = users.get(safe_id)
        if not user:
            return
        user["profile_state"] = str(state).strip().lower()[:30]
        users[safe_id] = user
        _save_users(users)


def complete_user_onboarding(user_id: str, *, do_not_show_again: bool = False, skipped: bool = False) -> Optional[Dict[str, Any]]:
    safe_id = slugify_username(user_id)
    if not safe_id:
        return None
    with _AUTH_LOCK:
        users = _load_users()
        user = users.get(safe_id)
        if not user:
            return None
        user = _coerce_onboarding_state(user)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        user["onboarding_pending"] = False
        user["onboarding_completed_at"] = timestamp
        user["onboarding_do_not_show_again"] = bool(do_not_show_again)
        user["onboarding_version"] = NEW_USER_ONBOARDING_VERSION
        user["onboarding_skipped_at"] = timestamp if skipped else None
        users[safe_id] = user
        _save_users(users)
        return public_user(user)


def reset_user_onboarding(user_id: str) -> Optional[Dict[str, Any]]:
    safe_id = slugify_username(user_id)
    if not safe_id:
        return None
    with _AUTH_LOCK:
        users = _load_users()
        user = users.get(safe_id)
        if not user:
            return None
        user = _coerce_onboarding_state(user)
        user["onboarding_pending"] = True
        user["onboarding_completed_at"] = None
        user["onboarding_do_not_show_again"] = False
        user["onboarding_skipped_at"] = None
        user["onboarding_version"] = NEW_USER_ONBOARDING_VERSION
        users[safe_id] = user
        _save_users(users)
        return public_user(user)



def delete_user_account(user_id: str, password: str) -> Dict[str, Any]:
    safe_id = slugify_username(user_id)
    with _AUTH_LOCK:
        users = _load_users()
        user = users.get(safe_id)
        if not user:
            return _auth_result(False, "auth_account_not_found", "Account not found.")
        if not _verify_password(user, password):
            return _auth_result(False, "auth_password_incorrect", "Password is incorrect.")
        users.pop(safe_id, None)
        _save_users(users)
        _ensure_lockouts_loaded()
        _login_failures.pop(safe_id, None)
        _persist_lockouts()
    return _auth_result(True, "auth_account_deleted", "Account deleted.")



def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    user = _load_users().get(slugify_username(user_id))
    return public_user(user) if user else None



def build_local_session_state(user_id: str) -> Dict[str, Any]:
    user = _load_users().get(slugify_username(user_id))
    if not user:
        return {}
    return {
        "user_id": str(user.get("user_id") or ""),
        "password_changed_at": str(user.get("password_changed_at") or ""),
    }



def restore_local_session(user_id: str, password_changed_at: str = "") -> Dict[str, Any]:
    safe_id = slugify_username(user_id)
    if not safe_id:
        return _auth_result(False, "auth_no_remembered_user", "No remembered user.")
    user = _load_users().get(safe_id)
    if not user:
        return _auth_result(False, "auth_remembered_user_deleted", "Remembered user no longer exists.")
    current_stamp = str(user.get("password_changed_at") or "")
    if str(password_changed_at or "") != current_stamp:
        return _auth_result(False, "auth_remembered_login_stale", "Remembered login is out of date.")
    user = _coerce_onboarding_state(user)
    return {"ok": True, "user": public_user(user), "onboarding_required": user_requires_onboarding(user)}



def list_users() -> List[Dict[str, Any]]:
    users = [public_user(u) for u in _load_users().values()]
    users.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return users



def public_user(user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not user:
        return None
    state = _coerce_onboarding_state(user)
    return {
        "user_id": state.get("user_id"),
        "display_name": state.get("display_name") or state.get("username") or state.get("user_id"),
        "username": state.get("username") or state.get("user_id"),
        "created_at": state.get("created_at", ""),
        "last_login_at": state.get("last_login_at"),
        "profile_state": state.get("profile_state", "new"),
        "onboarding_pending": bool(state.get("onboarding_pending")),
        "onboarding_completed_at": state.get("onboarding_completed_at"),
        "onboarding_do_not_show_again": bool(state.get("onboarding_do_not_show_again")),
        "onboarding_skipped_at": state.get("onboarding_skipped_at"),
        "onboarding_version": state.get("onboarding_version", NEW_USER_ONBOARDING_VERSION),
        "password_recovery_ready": _has_recovery_record(state),
    }



