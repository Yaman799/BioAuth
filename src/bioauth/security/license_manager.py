from __future__ import annotations

import base64
import binascii
import datetime as _dt
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from paths import data_dir

LOGGER = logging.getLogger(__name__)

LICENSE_SCHEMA_VERSION = 1
LICENSE_CODE_PREFIX = "BIOAUTH-LIC-v1"
PUBLIC_LICENSE_KEY_ID = "bioauth-ed25519-public-2026-04"
PUBLIC_LICENSE_KEY_COMPACT_ID = "k1"
ACCEPTED_LICENSE_KEY_IDS = {PUBLIC_LICENSE_KEY_ID, PUBLIC_LICENSE_KEY_COMPACT_ID}
POLICY_VERSION = "license-policy-2026-04-29"
COMPACT_POLICY_VERSION = "2026-04-29"
LICENSE_PRODUCTION_POLICY = "offline_only_signed_license"
LICENSE_VERIFICATION_MODE = "offline_ed25519_public_key"
LICENSE_REVOCATION_SUPPORTED = False
LICENSE_REVOCATION_NOTE = "Instant online revocation is not supported in this build. Access changes are enforced by signed license expiry or by importing a replacement signed license."
LICENSE_RENEWAL_NOTE = "Renewal is performed by importing or pasting a new signed license code before or after expiry."
LICENSE_CLOCK_NOTE = "Expiry is evaluated against the local system clock, so badly incorrect local time can affect expiry decisions until corrected."
TRIAL_DAYS = 14
GRACE_DAYS = 7

# Shipped desktop applications may only contain the public verification key.
# License issuance/signing is intentionally isolated in tools/issue_license.py.
PUBLIC_LICENSE_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAp3konlLPAVKxX1Ox8b37OdDumi+LeMX4OtWk5F6MX9E=
-----END PUBLIC KEY-----
"""

SAFETY_BASIC_FEATURES: Tuple[str, ...] = (
    "basic_protection",
    "start_protected_session",
    "stop_protected_session",
    "local_recovery",
    "delete_my_data",
    "delete_evidence",
    "export_support_bundle",
    "view_history_basic",
)

BASIC_FEATURES: Dict[str, bool] = {
    "basic_protection": True,
    "start_protected_session": True,
    "stop_protected_session": True,
    "delete_my_data": True,
    "delete_evidence": True,
    "export_support_bundle": True,
    "local_recovery": True,
    "view_history_basic": True,
    "incident_evidence_capture": False,
    "advanced_reports": False,
    "shadow_learning_controls": False,
    "team_policy_controls": False,
}

PRO_FEATURES: Dict[str, bool] = {
    **BASIC_FEATURES,
    "incident_evidence_capture": True,
    "advanced_reports": True,
    "shadow_learning_controls": True,
}

TEAM_FEATURES: Dict[str, bool] = {
    **PRO_FEATURES,
    "team_policy_controls": True,
}

TIER_FEATURES: Dict[str, Dict[str, bool]] = {
    "free": BASIC_FEATURES,
    "basic": BASIC_FEATURES,
    "pro": PRO_FEATURES,
    "team": TEAM_FEATURES,
}

LICENSE_TIER_VALUES = {"free", "pro", "team"}

ERROR_MESSAGES = {
    "missing_license": "No license is installed. BioAuth is running in Basic mode.",
    "invalid_license_code": "Invalid license code.",
    "malformed_license_code": "Malformed license code.",
    "unsupported_license_version": "Unsupported license version.",
    "signature_verification_failed": "Signature verification failed.",
    "expired_license": "Expired license. BioAuth is running in Basic mode.",
    "unsupported_tier": "Unsupported license tier.",
    "invalid_license_payload": "Invalid license payload.",
    "license_file_not_found": "License file not found.",
    "license_import_failed": "License import failed.",
    "license_activated": "License activated successfully.",
}


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(dt: _dt.datetime) -> str:
    return dt.astimezone(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(value: Any, *, end_of_day_for_date: bool = False) -> _dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            parsed_date = _dt.datetime.strptime(text, "%Y-%m-%d")
            if end_of_day_for_date:
                parsed_date = parsed_date.replace(hour=23, minute=59, second=59)
            return parsed_date.replace(tzinfo=_dt.timezone.utc)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt.astimezone(_dt.timezone.utc).replace(microsecond=0)
    except (TypeError, ValueError, OverflowError):
        return None


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty base64url value")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def license_file() -> Path:
    return Path(data_dir()) / "license.json"


def trial_state_file() -> Path:
    return Path(data_dir()) / "trial_state.json"


def _safe_json_read(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8") or "{}")
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Failed reading license JSON %s; using empty license record.", path.name, exc_info=True)
        return {}


def _safe_json_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def canonical_license_payload(payload: Dict[str, Any]) -> str:
    """Return the exact canonical JSON string used for Ed25519 signing."""
    clean = dict(payload or {})
    return json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_tier(value: Any) -> str:
    tier = str(value or "free").strip().lower()
    return tier if tier in TIER_FEATURES else "free"


def features_for_tier(tier: str) -> Dict[str, bool]:
    features = dict(TIER_FEATURES.get(normalize_tier(tier), BASIC_FEATURES))
    _preserve_safety_basic_features(features)
    return features


def _preserve_safety_basic_features(features: Dict[str, bool]) -> None:
    for feature_name in SAFETY_BASIC_FEATURES:
        features[feature_name] = True


def _public_key_from_pem(public_key_pem: str | bytes | None = None) -> Ed25519PublicKey:
    pem = public_key_pem or PUBLIC_LICENSE_KEY_PEM
    raw = pem.encode("utf-8") if isinstance(pem, str) else pem
    key = load_pem_public_key(raw)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Configured license verification key is not Ed25519.")
    return key


def make_license_code(payload: Dict[str, Any], signature: bytes) -> str:
    payload_bytes = canonical_license_payload(payload).encode("utf-8")
    return f"{LICENSE_CODE_PREFIX}.{_b64url_encode(payload_bytes)}.{_b64url_encode(signature)}"


def _status_base(*, state: str, effective_tier: str, premium_active: bool, license_expires_at: str = "", last_error: str = "") -> Dict[str, Any]:
    features = features_for_tier(effective_tier if premium_active or effective_tier == "team" else "free")
    if not premium_active and effective_tier not in {"pro", "team"}:
        features = features_for_tier("free")
    _preserve_safety_basic_features(features)
    return {
        "schema_version": LICENSE_SCHEMA_VERSION,
        "state": state,
        "effective_tier": effective_tier,
        "premium_active": bool(premium_active),
        "license_expires_at": license_expires_at,
        "features": features,
        "policy_version": POLICY_VERSION,
        "license_policy_mode": LICENSE_PRODUCTION_POLICY,
        "verification_mode": LICENSE_VERIFICATION_MODE,
        "revocation_supported": LICENSE_REVOCATION_SUPPORTED,
        "revocation_note": LICENSE_REVOCATION_NOTE,
        "renewal_note": LICENSE_RENEWAL_NOTE,
        "clock_policy_note": LICENSE_CLOCK_NOTE,
        "safe_mode_note": "Expired, missing, malformed, or invalid licenses fall back to Basic mode. Local protection, recovery, evidence deletion, support export, history viewing, and Delete My Data remain available.",
        "last_error": last_error,
    }


def _apply_license_feature_overrides(features: Dict[str, bool], payload: Dict[str, Any]) -> Dict[str, bool]:
    # Compact payloads use ``fo`` for explicit feature overrides. Legacy verbose
    # payloads may carry ``features`` or ``feature_overrides``. Unknown feature
    # names are ignored by local policy, and safety-critical Basic features are
    # restored after overrides so a signed override cannot disable them.
    overrides = payload.get("feature_overrides")
    if not isinstance(overrides, dict):
        overrides = payload.get("fo")
    if not isinstance(overrides, dict):
        overrides = payload.get("features")
    if isinstance(overrides, dict):
        known_features = set(BASIC_FEATURES) | set(PRO_FEATURES) | set(TEAM_FEATURES)
        for key, value in overrides.items():
            clean_key = str(key)
            if clean_key in known_features:
                features[clean_key] = bool(value)
    _preserve_safety_basic_features(features)
    return features


def _safe_error(code: str) -> str:
    return ERROR_MESSAGES.get(code, ERROR_MESSAGES["invalid_license_code"])


def _is_compact_payload(payload: Dict[str, Any]) -> bool:
    return any(key in payload for key in ("v", "lid", "cid", "em", "t", "iat", "exp", "kid", "pol", "fo"))


def normalize_license_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Map compact and legacy verbose license payloads to one internal shape.

    The original canonical payload remains the signed/verified data; this
    normalized view is only used for validation, status, and feature derivation.
    """
    source = dict(payload or {})
    if _is_compact_payload(source):
        overrides = source.get("fo") if isinstance(source.get("fo"), dict) else {}
        return {
            "payload_format": "compact",
            "schema_version": source.get("v"),
            "license_id": source.get("lid"),
            "customer_id": source.get("cid", ""),
            "customer_email": source.get("em", ""),
            "tier": source.get("t"),
            "issued_at": source.get("iat"),
            "expires_at": source.get("exp"),
            "feature_overrides": overrides,
            "policy_version": source.get("pol") or COMPACT_POLICY_VERSION,
            "key_id": source.get("kid"),
        }
    return {
        "payload_format": "verbose",
        "schema_version": source.get("schema_version"),
        "license_id": source.get("license_id"),
        "customer_id": source.get("customer_id", ""),
        "customer_email": source.get("customer_email", ""),
        "tier": source.get("tier"),
        "issued_at": source.get("issued_at"),
        "expires_at": source.get("expires_at"),
        "features": source.get("features") if isinstance(source.get("features"), dict) else {},
        "feature_overrides": source.get("feature_overrides") if isinstance(source.get("feature_overrides"), dict) else {},
        "policy_version": source.get("policy_version"),
        "key_id": source.get("key_id"),
    }


def _validate_payload_fields(payload: Dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return "invalid_license_payload"
    normalized = normalize_license_payload(payload)
    if normalized.get("schema_version") != LICENSE_SCHEMA_VERSION:
        return "unsupported_license_version"
    if str(normalized.get("key_id") or "").strip() not in ACCEPTED_LICENSE_KEY_IDS:
        return "unsupported_license_version"
    tier = str(normalized.get("tier") or "").strip().lower()
    if tier not in LICENSE_TIER_VALUES:
        return "unsupported_tier"
    for field_name in ("license_id", "issued_at", "expires_at", "key_id"):
        if not str(normalized.get(field_name) or "").strip():
            return "invalid_license_payload"
    if normalized.get("payload_format") == "verbose":
        if not (str(normalized.get("customer_email") or "").strip() or str(normalized.get("customer_id") or "").strip()):
            return "invalid_license_payload"
        if not str(normalized.get("policy_version") or "").strip():
            return "invalid_license_payload"
    if _parse_iso(normalized.get("issued_at")) is None or _parse_iso(normalized.get("expires_at"), end_of_day_for_date=True) is None:
        return "invalid_license_payload"
    return ""


def parse_license_code(code: str) -> tuple[Dict[str, Any], str, str]:
    text = str(code or "").strip()
    parts = text.split(".")
    if len(parts) != 3 or parts[0] != LICENSE_CODE_PREFIX:
        return {}, "", "malformed_license_code"
    try:
        payload_bytes = _b64url_decode(parts[1])
        signature_bytes = _b64url_decode(parts[2])
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return {}, "", "malformed_license_code"
    if not isinstance(payload, dict):
        return {}, "", "malformed_license_code"
    canonical_bytes = canonical_license_payload(payload).encode("utf-8")
    if payload_bytes != canonical_bytes:
        return {}, "", "malformed_license_code"
    if not signature_bytes:
        return {}, "", "malformed_license_code"
    return payload, _b64url_encode(signature_bytes), ""


def verify_license_signature(payload: Dict[str, Any], signature_b64url: str, public_key_pem: str | bytes | None = None) -> bool:
    try:
        signature = _b64url_decode(signature_b64url)
        _public_key_from_pem(public_key_pem).verify(signature, canonical_license_payload(payload).encode("utf-8"))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
    except Exception:
        LOGGER.warning("Unexpected license signature verification failure; treating license as invalid.", exc_info=True)
        return False


def evaluate_license_record(record: Dict[str, Any], *, now: _dt.datetime | None = None) -> Dict[str, Any]:
    now = now or _now_utc()
    payload: Dict[str, Any] = {}
    signature_b64 = ""
    if isinstance(record, dict):
        if isinstance(record.get("payload"), dict):
            payload = dict(record.get("payload") or {})
            signature_b64 = str(record.get("signature") or "").strip()
        elif str(record.get("license_code") or record.get("code") or "").strip():
            payload, signature_b64, error = parse_license_code(str(record.get("license_code") or record.get("code") or ""))
            if error:
                return _status_base(state="invalid_basic", effective_tier="free", premium_active=False, last_error=_safe_error(error))
        else:
            return _status_base(state="invalid_basic", effective_tier="free", premium_active=False, last_error=_safe_error("invalid_license_payload"))

    field_error = _validate_payload_fields(payload)
    if field_error:
        return _status_base(state="invalid_basic", effective_tier="free", premium_active=False, last_error=_safe_error(field_error))
    if not verify_license_signature(payload, signature_b64):
        return _status_base(state="invalid_basic", effective_tier="free", premium_active=False, last_error=_safe_error("signature_verification_failed"))

    normalized = normalize_license_payload(payload)
    license_exp = _parse_iso(normalized.get("expires_at"), end_of_day_for_date=True)
    expires_at = _iso(license_exp) if license_exp else ""
    if license_exp is None or license_exp < now:
        return _status_base(state="expired_basic", effective_tier="free", premium_active=False, license_expires_at=expires_at, last_error=_safe_error("expired_license"))

    tier = str(normalized.get("tier") or "free").strip().lower()
    effective_tier = normalize_tier(tier)
    premium_active = effective_tier in {"pro", "team"}
    status = _status_base(state="licensed", effective_tier=effective_tier, premium_active=premium_active, license_expires_at=expires_at, last_error="")
    status["license_id"] = str(normalized.get("license_id") or "")
    status["licensed_tier"] = tier
    status["key_id"] = str(normalized.get("key_id") or "")
    status["policy_version"] = str(normalized.get("policy_version") or POLICY_VERSION)
    status["payload_format"] = str(normalized.get("payload_format") or "verbose")
    status["features"] = _apply_license_feature_overrides(features_for_tier(effective_tier), normalized) if premium_active else features_for_tier("free")
    return status


def _load_trial_state() -> Dict[str, Any]:
    path = trial_state_file()
    if not path.exists():
        return {}
    state = _safe_json_read(path)
    return state if isinstance(state, dict) else {}


def _trial_status(now: _dt.datetime | None = None) -> Dict[str, Any]:
    now = now or _now_utc()
    state = _load_trial_state()
    started = _parse_iso(state.get("trial_started_at"))
    if started is None:
        return {"trial_active": False, "trial_phase": "missing"}
    trial_days = max(0, int(state.get("trial_days") or TRIAL_DAYS))
    grace_days = max(0, int(state.get("grace_days") or GRACE_DAYS))
    trial_ends = started + _dt.timedelta(days=trial_days)
    grace_ends = trial_ends + _dt.timedelta(days=grace_days)
    remaining_trial = max(0, int((trial_ends - now).total_seconds() // 86400) + (1 if trial_ends > now else 0))
    remaining_grace = max(0, int((grace_ends - now).total_seconds() // 86400) + (1 if grace_ends > now else 0))
    if now <= trial_ends:
        phase = "trial_active"
        active = True
    elif now <= grace_ends:
        phase = "grace_active"
        active = True
    else:
        phase = "expired"
        active = False
    return {
        "trial_started_at": _iso(started),
        "trial_ends_at": _iso(trial_ends),
        "grace_ends_at": _iso(grace_ends),
        "trial_days_remaining": remaining_trial,
        "grace_days_remaining": remaining_grace,
        "trial_active": active,
        "trial_phase": phase,
    }


def load_license_payload() -> Dict[str, Any]:
    record = _safe_json_read(license_file())
    payload = record.get("payload") if isinstance(record, dict) else {}
    return dict(payload) if isinstance(payload, dict) else {}


def load_license_record() -> Dict[str, Any]:
    payload = _safe_json_read(license_file())
    return payload if isinstance(payload, dict) else {}


def save_verified_license_record(payload: Dict[str, Any], signature_b64url: str) -> Dict[str, Any]:
    record = {
        "schema_version": LICENSE_SCHEMA_VERSION,
        "license_format": LICENSE_CODE_PREFIX,
        "saved_at": _iso(_now_utc()),
        "payload": dict(payload or {}),
        "signature": str(signature_b64url or ""),
    }
    _safe_json_write(license_file(), record)
    return record


def evaluate_license_code(code: str, *, now: _dt.datetime | None = None) -> Dict[str, Any]:
    payload, signature_b64, error = parse_license_code(code)
    if error:
        return _status_base(state="invalid_basic", effective_tier="free", premium_active=False, last_error=_safe_error(error))
    status = evaluate_license_record({"payload": payload, "signature": signature_b64}, now=now)
    return status


def activate_license_code(code: str, *, now: _dt.datetime | None = None) -> Dict[str, Any]:
    payload, signature_b64, error = parse_license_code(code)
    if error:
        status = _status_base(state="invalid_basic", effective_tier="free", premium_active=False, last_error=_safe_error(error))
        return {"ok": False, "message": status["last_error"], "state": status["state"], "licenseStatus": status}
    status = evaluate_license_record({"payload": payload, "signature": signature_b64}, now=now)
    if status.get("state") == "licensed":
        save_verified_license_record(payload, signature_b64)
        saved_status = evaluate_license_record({"payload": payload, "signature": signature_b64}, now=now)
        return {"ok": True, "message": ERROR_MESSAGES["license_activated"], "state": saved_status["state"], "licenseStatus": saved_status}
    message = str(status.get("last_error") or ERROR_MESSAGES["invalid_license_code"])
    return {"ok": False, "message": message, "state": status.get("state", "invalid_basic"), "licenseStatus": status}


def extract_license_code_from_json(payload: Dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("license_code", "code"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    nested = payload.get("license")
    if isinstance(nested, dict):
        for key in ("license_code", "code"):
            value = str(nested.get(key) or "").strip()
            if value:
                return value
    raw_payload = payload.get("payload")
    signature = str(payload.get("signature") or "").strip()
    if isinstance(raw_payload, dict) and signature:
        return f"{LICENSE_CODE_PREFIX}.{_b64url_encode(canonical_license_payload(raw_payload).encode('utf-8'))}.{signature}"
    return ""


def import_license_file(path: str | os.PathLike[str], *, now: _dt.datetime | None = None) -> Dict[str, Any]:
    candidate = Path(path).expanduser()
    if not candidate.exists() or not candidate.is_file():
        status = _status_base(state="invalid_basic", effective_tier="free", premium_active=False, last_error=_safe_error("license_file_not_found"))
        return {"ok": False, "message": status["last_error"], "state": status["state"], "licenseStatus": status}
    try:
        text = candidate.read_text(encoding="utf-8").strip()
        if text.startswith(LICENSE_CODE_PREFIX):
            code = text
        else:
            code = extract_license_code_from_json(json.loads(text or "{}"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        LOGGER.warning("License import failed while reading %s; returning invalid status.", candidate.name, exc_info=True)
        status = _status_base(state="invalid_basic", effective_tier="free", premium_active=False, last_error=_safe_error("license_import_failed"))
        return {"ok": False, "message": status["last_error"], "state": status["state"], "licenseStatus": status}
    if not code:
        status = _status_base(state="invalid_basic", effective_tier="free", premium_active=False, last_error=_safe_error("malformed_license_code"))
        return {"ok": False, "message": status["last_error"], "state": status["state"], "licenseStatus": status}
    return activate_license_code(code, now=now)


def evaluate_license(settings: Dict[str, Any] | None = None, *, now: _dt.datetime | None = None) -> Dict[str, Any]:
    del settings  # License state is persisted separately from general app settings.
    now = now or _now_utc()
    path = license_file()
    if path.exists():
        return evaluate_license_record(load_license_record(), now=now)

    trial = _trial_status(now)
    if trial.get("trial_active"):
        state = str(trial.get("trial_phase") or "trial_active")
        expires_at = str(trial.get("grace_ends_at") or trial.get("trial_ends_at") or "")
        status = _status_base(state=state, effective_tier="pro", premium_active=True, license_expires_at=expires_at, last_error="")
        status["trial"] = trial
        status["features"] = features_for_tier("pro")
        return status

    status = _status_base(state="missing_basic", effective_tier="free", premium_active=False, last_error=_safe_error("missing_license"))
    status["trial"] = trial
    return status


def feature_enabled(feature_name: str, settings: Dict[str, Any] | None = None) -> bool:
    state = evaluate_license(settings)
    return bool((state.get("features") or {}).get(str(feature_name), False))
