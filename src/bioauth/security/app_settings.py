from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict

from deep_runtime import normalize_benchmark_record, normalize_deep_runtime_mode
from license_manager import evaluate_license
from release_profile import current_build_profile, current_package_profile, normalize_build_profile, normalize_package_profile
from paths import data_dir, settings_file
from secure_storage import (
    ALGORITHM as SECURE_SETTINGS_ALGORITHM,
    DEFAULT_KEY_ID as SECURE_SETTINGS_KEY_ID,
    STORAGE_FORMAT_VERSION as SECURE_SETTINGS_FORMAT_VERSION,
    SecureEnvelopeIntegrityError,
    build_envelope,
    load_enveloped_json,
    write_enveloped_json,
)

DATA_DIR = data_dir()
SETTINGS_FILE = settings_file()

PRIVACY_POLICY_VERSION = "2026-04-24"
SETTINGS_STORAGE_STATE = "encrypted_envelope_v2"
INTERFACE_MODE_DEFAULT = "user"
INTERFACE_MODE_VALUES = ("user", "developer")

# Phase 03 feature flags are backend-owned settings used only as a safe
# foundation for later phases. They must not activate new behavior by default.
FEATURE_FLAG_DEFAULTS: Dict[str, bool] = {
    "enable_user_shell": True,
    "enable_manual_model_switch": False,
    "enable_face_confirmation": False,
    "enable_face_enrollment": False,
    "enable_shadow_feedback_from_face": False,
    "enable_release_autoupdate": False,
    "enable_startup_protected_sessions_after_build": False,
}
FEATURE_FLAG_KEYS = tuple(FEATURE_FLAG_DEFAULTS.keys())
FACE_LOCAL_DEV_FEATURE_FLAGS = {"enable_face_confirmation", "enable_face_enrollment"}
FACE_LOCAL_DEV_ENV_OVERRIDES = {
    "enable_face_confirmation": "BIOAUTH_ENABLE_FACE_CONFIRMATION_DEV",
    "enable_face_enrollment": "BIOAUTH_ENABLE_FACE_ENROLLMENT_DEV",
}
FACE_LOCAL_DEV_SHARED_ENV_OVERRIDE = "BIOAUTH_ENABLE_FACE_DEV"
FACE_LOCAL_DEV_BUILD_PROFILES = {"dev"}

_LOG = logging.getLogger(__name__)
_LAST_SETTINGS_STORAGE_ERROR: str = ""
_LAST_SETTINGS_STORAGE_STATE: str = "unknown"


DEMO_CLASSIC_PROTECTED_ENV = "BIOAUTH_DEMO_CLASSIC_PROTECTED"
DEMO_CLASSIC_PROTECTED_EMBEDDED_ENV = "BIOAUTH_DEMO_CLASSIC_PROTECTED_EMBEDDED"


def demo_classic_protected_enabled(env: Dict[str, str] | None = None) -> bool:
    """Return True only for an explicit Demo Classic runtime opt-in.

    Commercial/product runtime defaults to False because no production package
    sets this environment variable.  Dedicated demo builds set it via their
    isolated PyInstaller runtime hook; source/dev sessions may still opt in
    explicitly for the preserved demo-profile tests.  This must never be
    treated as normal production approval.
    """
    source = env if isinstance(env, dict) else os.environ
    return str(source.get(DEMO_CLASSIC_PROTECTED_ENV, "") or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _utc_timestamp() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def has_current_privacy_consent(settings: Dict[str, Any] | None) -> bool:
    payload = settings if isinstance(settings, dict) else {}
    return (
        bool(str(payload.get("privacy_consent_timestamp", "")).strip())
        and str(payload.get("privacy_consent_policy_version", "")).strip() == PRIVACY_POLICY_VERSION
    )


def has_current_evidence_consent(settings: Dict[str, Any] | None) -> bool:
    payload = settings if isinstance(settings, dict) else {}
    return (
        bool(payload.get("incident_evidence_consent_granted", False))
        and bool(str(payload.get("incident_evidence_consent_timestamp", "")).strip())
        and str(payload.get("incident_evidence_consent_policy_version", "")).strip() == PRIVACY_POLICY_VERSION
    )


def build_privacy_consent_fields() -> Dict[str, Any]:
    now = _utc_timestamp()
    return {
        "privacy_policy_version": PRIVACY_POLICY_VERSION,
        "privacy_consent_policy_version": PRIVACY_POLICY_VERSION,
        "privacy_consent_timestamp": now,
    }


def build_evidence_consent_fields(granted: bool = True) -> Dict[str, Any]:
    now = _utc_timestamp()
    if not granted:
        return {
            "incident_evidence_consent_granted": False,
            "incident_evidence_consent_policy_version": "",
            "incident_evidence_consent_timestamp": "",
        }
    return {
        "incident_evidence_consent_granted": True,
        "incident_evidence_consent_policy_version": PRIVACY_POLICY_VERSION,
        "incident_evidence_consent_timestamp": now,
    }


def has_current_face_template_consent(settings: Dict[str, Any] | None) -> bool:
    payload = settings if isinstance(settings, dict) else {}
    return (
        bool(payload.get("face_template_consent_granted", False))
        and bool(str(payload.get("face_template_consent_timestamp", "")).strip())
        and str(payload.get("face_template_consent_policy_version", "")).strip() == PRIVACY_POLICY_VERSION
    )


def build_face_template_consent_fields(granted: bool = True) -> Dict[str, Any]:
    now = _utc_timestamp()
    if not granted:
        return {
            "face_template_consent_granted": False,
            "face_template_consent_policy_version": "",
            "face_template_consent_timestamp": "",
        }
    return {
        "face_template_consent_granted": True,
        "face_template_consent_policy_version": PRIVACY_POLICY_VERSION,
        "face_template_consent_timestamp": now,
    }


def _coerce_safe_bool(value: Any, *, default: bool = False) -> bool:
    """Coerce persisted boolean settings without letting malformed values fail open."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
        return bool(default)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "on", "enabled", "yes"}:
            return True
        if normalized in {"0", "false", "off", "disabled", "", "no"}:
            return False
        return bool(default)
    return bool(default)


def _face_local_dev_override_enabled(settings: Dict[str, Any] | None, key: str, *, env: Dict[str, str] | None = None) -> bool:
    """Return the explicit local/demo face feature override without changing persisted defaults.

    Face enrollment/confirmation remain fail-closed by default. A local dev build
    may opt into camera/model validation with environment flags. The dedicated
    embedded classic-protected EXE also needs this override while using the
    production build profile, because its runtime hook is the packaged equivalent
    of launching source with BIOAUTH_DEMO_CLASSIC_PROTECTED=1. Normal production
    builds still ignore these env flags.
    """
    if key not in FACE_LOCAL_DEV_FEATURE_FLAGS:
        return False
    payload = settings if isinstance(settings, dict) else {}
    source = env if isinstance(env, dict) else os.environ
    build_profile = normalize_build_profile(payload.get("build_profile") or current_build_profile())
    embedded_classic_protected = (
        _coerce_safe_bool(source.get(DEMO_CLASSIC_PROTECTED_ENV, False), default=False)
        and _coerce_safe_bool(source.get(DEMO_CLASSIC_PROTECTED_EMBEDDED_ENV, False), default=False)
    )
    if build_profile not in FACE_LOCAL_DEV_BUILD_PROFILES and not embedded_classic_protected:
        return False
    specific = FACE_LOCAL_DEV_ENV_OVERRIDES.get(key, "")
    return _coerce_safe_bool(source.get(specific, False), default=False) or _coerce_safe_bool(source.get(FACE_LOCAL_DEV_SHARED_ENV_OVERRIDE, False), default=False)


def normalize_feature_flags(settings: Dict[str, Any] | None) -> Dict[str, bool]:
    """Return backend-owned feature flags with safe/off defaults.

    Unknown keys are ignored. Missing keys are backfilled to their safe default.
    Malformed values fail closed to the per-flag default, which is currently off
    for every Phase 03 flag.
    """
    payload = settings if isinstance(settings, dict) else {}
    normalized: Dict[str, bool] = {}
    for key, default in FEATURE_FLAG_DEFAULTS.items():
        normalized[key] = _coerce_safe_bool(payload.get(key, default), default=default)
    return normalized



def normalize_interface_mode(value: Any, *, default: str = INTERFACE_MODE_DEFAULT) -> str:
    """Normalize persisted UI mode without activating UserShell by itself."""
    candidate = str(value or "").strip().lower()
    # Map deprecated/legacy values to "user" so old settings files don't silently
    # land in developer mode on commercial installs.
    if candidate in {"legacy", "hybrid", "demo", "demo_classic", "classic"}:
        return "user"
    if candidate in INTERFACE_MODE_VALUES:
        return candidate
    return default if default in INTERFACE_MODE_VALUES else INTERFACE_MODE_DEFAULT


def resolve_ui_mode(settings: Dict[str, Any] | None) -> str:
    """Return the backend-owned QML shell mode.

    UserShell is the default for commercial builds (enable_user_shell=True).
    Developer shell is shown only when explicitly configured or when the feature
    flag is off (e.g. developer-profile builds).
    """
    payload = settings if isinstance(settings, dict) else {}
    requested = normalize_interface_mode(payload.get("interface_mode", INTERFACE_MODE_DEFAULT))
    if requested == "user" and feature_flag_enabled(payload, "enable_user_shell"):
        return "user"
    return "developer"


def feature_flag_enabled(settings: Dict[str, Any] | None, key: str) -> bool:
    """Read one known backend feature flag with safe local/dev face overrides.

    Unknown feature names are always disabled so callers cannot accidentally
    enable a future feature by typo or unrecognized configuration.  Face
    enrollment/confirmation remain off in persisted defaults, but H12A permits an
    explicit local/dev environment override for camera/model validation builds.
    """
    if key not in FEATURE_FLAG_DEFAULTS:
        return False
    normalized = normalize_feature_flags(settings)
    if normalized.get(key, False):
        return True
    return _face_local_dev_override_enabled(settings, key)

DEFAULT_SETTINGS: Dict[str, Any] = {
    "theme": "dark",
    "monitor_interval_sec": 8,
    "run_on_startup": False,
    # Keep feature-flag defaults centralized so new flags cannot drift between
    # FEATURE_FLAG_DEFAULTS and the persisted settings bootstrap payload.
    **FEATURE_FLAG_DEFAULTS,
    "interface_mode": INTERFACE_MODE_DEFAULT,
    "risk_sensitivity": "conservative",
    "risk_threshold_overrides": {},
    "mute_button_sounds": True,
    "remember_login_enabled": False,
    "startup_protected_sessions_enabled": False,
    "app_passcode_enabled": False,
    "app_passcode_timeout_sec": 60,
    "app_passcode_record": {},
    "privacy_policy_version": PRIVACY_POLICY_VERSION,
    "privacy_consent_policy_version": "",
    "privacy_consent_timestamp": "",
    "incident_evidence_enabled": False,
    "incident_evidence_consent_granted": False,
    "incident_evidence_consent_policy_version": "",
    "incident_evidence_consent_timestamp": "",
    "incident_evidence_capture_screenshot": False,
    "incident_evidence_capture_webcam": False,
    "incident_evidence_retention_days": 30,
    "face_template_consent_granted": False,
    "face_template_consent_policy_version": "",
    "face_template_consent_timestamp": "",
    "face_confirmation_enabled": False,
    "face_confirmation_pre_lock_timeout_sec": 3.0,
    "backend_face_camera_index": 0,
    "face_enrollment_frame_count": 7,
    "incident_evidence_webcam_frames": 2,
    "smart_auto_enrollment_enabled": False,
    "auto_train_when_ready_enabled": False,
    "auto_promote_when_production_safe_enabled": False,
    "shadow_automation_paused": False,
    "developer_forced_production_ready": False,
    "deep_runtime_mode": "auto",
    "deep_runtime_manual_override": False,
    "developer_direct_test_enabled": False,
    "developer_direct_consent_enabled": False,
    "enable_candidate_artifacts": True,
    "enable_deep_candidate_artifacts": True,
    "strict_candidate_training": False,
    "deep_runtime_benchmark": {},
    "build_profile": current_build_profile(),
    "package_profile": current_package_profile(),
    "license_status_cache": {},
    "license_feature_overrides": {},
    "user_welcome_ack": {},
}


_SETTINGS_LOCK = threading.RLock()
_SETTINGS_CACHE: Dict[str, Any] | None = None


def _settings_error(message: str, exc: Exception | None = None) -> None:
    global _LAST_SETTINGS_STORAGE_ERROR
    _LAST_SETTINGS_STORAGE_ERROR = message
    if exc:
        _LOG.warning("BioAuth settings storage error: %s (%s)", message, exc.__class__.__name__)
    else:
        _LOG.warning("BioAuth settings storage error: %s", message)


def get_last_settings_storage_error() -> str:
    return _LAST_SETTINGS_STORAGE_ERROR


def get_last_settings_storage_state() -> str:
    return _LAST_SETTINGS_STORAGE_STATE


def settings_storage_metadata() -> Dict[str, Any]:
    return {
        "settings_storage": SETTINGS_STORAGE_STATE,
        "storage_format_version": SECURE_SETTINGS_FORMAT_VERSION,
        "encrypted": True,
        "algorithm": SECURE_SETTINGS_ALGORITHM,
        "key_id": SECURE_SETTINGS_KEY_ID,
        "last_state": _LAST_SETTINGS_STORAGE_STATE,
        "last_error": bool(_LAST_SETTINGS_STORAGE_ERROR),
    }


def _coerce_settings_payload(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return dict(DEFAULT_SETTINGS)
    incoming = dict(data)
    merged = dict(DEFAULT_SETTINGS)
    merged.update(incoming)
    merged["privacy_policy_version"] = PRIVACY_POLICY_VERSION
    if merged.get("incident_evidence_enabled") and not has_current_evidence_consent(merged):
        merged["incident_evidence_enabled"] = False
    merged["incident_evidence_capture_screenshot"] = bool(merged.get("incident_evidence_capture_screenshot", False))
    merged["incident_evidence_capture_webcam"] = bool(merged.get("incident_evidence_capture_webcam", False))
    if not has_current_face_template_consent(merged):
        merged["face_template_consent_granted"] = False
        merged["face_template_consent_policy_version"] = ""
        merged["face_template_consent_timestamp"] = ""
        merged["face_confirmation_enabled"] = False
    merged["face_confirmation_enabled"] = _coerce_safe_bool(merged.get("face_confirmation_enabled", False), default=False)
    try:
        camera_index = int(merged.get("backend_face_camera_index", 0) or 0)
    except (TypeError, ValueError):
        camera_index = 0
    merged["backend_face_camera_index"] = max(0, min(4, camera_index))
    try:
        enrollment_count = int(merged.get("face_enrollment_frame_count", 7) or 7)
    except (TypeError, ValueError):
        enrollment_count = 7
    merged["face_enrollment_frame_count"] = max(3, min(7, enrollment_count))
    for _feature_key, _feature_value in normalize_feature_flags(merged).items():
        merged[_feature_key] = _feature_value
    merged["interface_mode"] = normalize_interface_mode(merged.get("interface_mode", INTERFACE_MODE_DEFAULT))
    merged["startup_protected_sessions_enabled"] = _coerce_safe_bool(merged.get("startup_protected_sessions_enabled", False), default=False)
    merged["smart_auto_enrollment_enabled"] = bool(merged.get("smart_auto_enrollment_enabled", False))
    merged["auto_train_when_ready_enabled"] = bool(merged.get("auto_train_when_ready_enabled", False))
    merged["auto_promote_when_production_safe_enabled"] = bool(merged.get("auto_promote_when_production_safe_enabled", False))
    merged["shadow_automation_paused"] = _coerce_safe_bool(merged.get("shadow_automation_paused", False), default=False)
    merged["developer_forced_production_ready"] = _coerce_safe_bool(merged.get("developer_forced_production_ready", False), default=False)
    merged["deep_runtime_mode"] = normalize_deep_runtime_mode(merged.get("deep_runtime_mode"), default="auto")
    merged["deep_runtime_manual_override"] = bool(merged.get("deep_runtime_manual_override", False))
    merged["developer_direct_test_enabled"] = _coerce_safe_bool(merged.get("developer_direct_test_enabled", False), default=False)
    merged["developer_direct_consent_enabled"] = _coerce_safe_bool(merged.get("developer_direct_consent_enabled", False), default=False)
    merged["enable_candidate_artifacts"] = _coerce_safe_bool(merged.get("enable_candidate_artifacts", True), default=True)
    merged["enable_deep_candidate_artifacts"] = _coerce_safe_bool(merged.get("enable_deep_candidate_artifacts", True), default=True)
    merged["strict_candidate_training"] = _coerce_safe_bool(merged.get("strict_candidate_training", False), default=False)
    merged["deep_runtime_benchmark"] = normalize_benchmark_record(merged.get("deep_runtime_benchmark"))
    merged["build_profile"] = normalize_build_profile(merged.get("build_profile") or current_build_profile())
    merged["package_profile"] = normalize_package_profile(merged.get("package_profile") or current_package_profile())
    # Cache is informational only; license_manager remains the source of truth.
    # Preserve an existing cache during storage migration/load; license_manager remains source of truth for decisions.
    existing_license_cache = incoming.get("license_status_cache") if isinstance(incoming.get("license_status_cache"), dict) else {}
    if existing_license_cache:
        merged["license_status_cache"] = dict(existing_license_cache)
    else:
        try:
            merged["license_status_cache"] = evaluate_license(merged)
        except Exception:
            _LOG.warning("License status cache refresh failed during settings normalization; keeping safe empty cache.", exc_info=True)
            merged["license_status_cache"] = {}
    return merged


def _load_settings_file_unlocked() -> Dict[str, Any]:
    global _LAST_SETTINGS_STORAGE_STATE, _LAST_SETTINGS_STORAGE_ERROR
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(SETTINGS_FILE):
        _LAST_SETTINGS_STORAGE_STATE = "missing"
        _LAST_SETTINGS_STORAGE_ERROR = ""
        return dict(DEFAULT_SETTINGS)
    try:
        settings, state = load_enveloped_json(
            SETTINGS_FILE,
            dict(DEFAULT_SETTINGS),
            coerce=_coerce_settings_payload,
            rewrite_migrated=True,
        )
        _LAST_SETTINGS_STORAGE_STATE = state
        _LAST_SETTINGS_STORAGE_ERROR = ""
        return dict(settings)
    except SecureEnvelopeIntegrityError as exc:
        _LAST_SETTINGS_STORAGE_STATE = "integrity_error"
        _settings_error("Settings file failed encrypted envelope integrity validation; using safe defaults without rewriting the original file.", exc)
        return dict(DEFAULT_SETTINGS)
    except Exception as exc:
        _LAST_SETTINGS_STORAGE_STATE = "load_error"
        _settings_error("Settings file could not be loaded; using safe defaults without rewriting the original file.", exc)
        return dict(DEFAULT_SETTINGS)


def _current_settings_unlocked() -> Dict[str, Any]:
    global _SETTINGS_CACHE
    if isinstance(_SETTINGS_CACHE, dict):
        return dict(_SETTINGS_CACHE)
    current = _load_settings_file_unlocked()
    _SETTINGS_CACHE = dict(current)
    return dict(current)


def _safe_json_write(path: str, data: Dict[str, Any]) -> None:
    """Compatibility wrapper that now writes a clean encrypted envelope only."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_enveloped_json(path, dict(data or {}))


def _build_settings_envelope_for_tests(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a production-format envelope for migration tests without writing it."""
    return build_envelope(_coerce_settings_payload(data))


def load_settings() -> Dict[str, Any]:
    with _SETTINGS_LOCK:
        return _current_settings_unlocked()


def save_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    global _SETTINGS_CACHE, _LAST_SETTINGS_STORAGE_STATE, _LAST_SETTINGS_STORAGE_ERROR
    with _SETTINGS_LOCK:
        current = _current_settings_unlocked()
        current.update(dict(changes or {}))
        current = _coerce_settings_payload(current)
        _safe_json_write(SETTINGS_FILE, current)
        _SETTINGS_CACHE = dict(current)
        _LAST_SETTINGS_STORAGE_STATE = "envelope_v2"
        _LAST_SETTINGS_STORAGE_ERROR = ""
        return dict(current)


def save_settings_async(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Serialized settings persistence.

    Historically this used a background thread per write, which could reorder
    writes and lose newer updates. The public API remains unchanged for callers,
    but persistence is now synchronous and protected by a single writer lock so
    the latest in-process update always wins atomically.
    """
    return save_settings(changes)
