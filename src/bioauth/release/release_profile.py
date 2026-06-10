from __future__ import annotations

import os
from typing import Any, Dict

VALID_PROFILES = {"dev", "beta", "production"}
DEFAULT_PROFILE = "dev"
PROFILE_POLICY_VERSION = "release-profile-2026-04-24"
PACKAGE_PROFILE_POLICY_VERSION = "package-profile-2026-05-09"

PACKAGE_PROFILE_ALIASES = {
    "classic": "classic-minimal",
    "classic_minimal": "classic-minimal",
    "classic-minimal": "classic-minimal",
    "minimal": "classic-minimal",
    "production": "classic-minimal",
    "hybrid": "hybrid-pro",
    "pro": "hybrid-pro",
    "hybrid_pro": "hybrid-pro",
    "hybrid-pro": "hybrid-pro",
    "hybrid_pro_face": "hybrid-pro-face",
    "hybrid-pro-face": "hybrid-pro-face",
    "pro_face": "hybrid-pro-face",
    "pro-face": "hybrid-pro-face",
    "face": "hybrid-pro-face",
    "full": "hybrid-pro-face",
    "full-feature": "hybrid-pro-face",
    "full_feature": "hybrid-pro-face",
    "beta": "hybrid-pro-face",
    "dev": "dev",
    "development": "dev",
}

PACKAGE_PROFILE_MATRIX: Dict[str, Dict[str, Any]] = {
    "classic-minimal": {
        "label": "Classic Minimal",
        "requirements": ["requirements.txt"],
        "include_deep_deps": False,
        "include_lightgbm": False,
        "include_accelerated_backends": False,
        "include_face_backends": False,
        "feature_scope": ["classic_runtime", "basic_protection", "privacy_delete_flows"],
        "excluded_packages": ["torch", "openvino", "onnxruntime", "lightgbm", "cv2", "opencv"],
    },
    "hybrid-pro": {
        "label": "Hybrid / Pro",
        "requirements": ["requirements.txt", "requirements-pro.txt"],
        "include_deep_deps": True,
        "include_lightgbm": True,
        "include_accelerated_backends": False,
        "include_face_backends": False,
        "feature_scope": ["classic_runtime", "hybrid_shadow", "hybrid_runtime", "supervised_challenger"],
        "excluded_packages": ["openvino", "onnxruntime", "cv2", "opencv"],
    },
    "hybrid-pro-face": {
        "label": "Hybrid / Pro + Face",
        "requirements": ["requirements.txt", "requirements-pro.txt", "requirements-face.txt"],
        "include_deep_deps": True,
        "include_lightgbm": True,
        "include_accelerated_backends": False,
        "include_face_backends": True,
        "feature_scope": [
            "classic_runtime",
            "hybrid_shadow",
            "hybrid_runtime",
            "supervised_challenger",
            "face_confirmation",
            "opencv_camera_backend",
        ],
        "excluded_packages": ["openvino", "onnxruntime"],
    },
    "dev": {
        "label": "Developer",
        "requirements": ["requirements-dev.txt"],
        "include_deep_deps": True,
        "include_lightgbm": True,
        "include_accelerated_backends": True,
        "include_face_backends": False,
        "feature_scope": ["classic_runtime", "hybrid_runtime", "tests", "build_tools"],
        "excluded_packages": [],
    },
}

DEV_ONLY_FLAGS = (
    "BIOAUTH_DEBUG_PANEL",
    "BIOAUTH_DEV_MODE",
    "BIOAUTH_ALLOW_UNSAFE_FIXTURES",
    "BIOAUTH_DISABLE_PRIVACY_GATES",
)

DEMO_BUILD_ONLY_FLAGS = (
    "BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED",
)
DEMO_CLASSIC_BUILD_FLAVOR_ENV = "BIOAUTH_BUILD_FLAVOR"
DEMO_CLASSIC_BUILD_FLAVOR = "demo-classic-protected"


def _truthy_env(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def signing_configuration_errors(env: Dict[str, str] | None = None) -> list[str]:
    """Return fail-closed signing configuration errors without exposing secret values.

    Production release builds may sign with either a certificate thumbprint
    already available in the Windows certificate store or a certificate file
    path plus password supplied by the caller/CI environment.  The function
    validates only configuration presence and never reads, logs, or returns
    secret values.
    """

    source = env if env is not None else os.environ
    errors: list[str] = []
    enabled = _truthy_env(source.get("BIOAUTH_ENABLE_SIGNING"))
    if not enabled:
        errors.append("BIOAUTH_ENABLE_SIGNING must be enabled for production builds.")
        return errors

    thumbprint = str(source.get("BIOAUTH_SIGN_CERT_SHA1", "") or "").strip()
    cert_file = str(source.get("BIOAUTH_SIGN_CERT_FILE", "") or "").strip()
    cert_password = str(source.get("BIOAUTH_SIGN_CERT_PASSWORD", "") or "").strip()
    cert_pfx_base64 = str(source.get("BIOAUTH_SIGN_CERT_PFX_BASE64", "") or "").strip()

    if thumbprint:
        return errors

    if cert_file:
        if not cert_password:
            errors.append("BIOAUTH_SIGN_CERT_PASSWORD must be provided when BIOAUTH_SIGN_CERT_FILE is used for production signing.")
        return errors

    if cert_pfx_base64:
        if not cert_password:
            errors.append("BIOAUTH_SIGN_CERT_PASSWORD must be provided when BIOAUTH_SIGN_CERT_PFX_BASE64 is used for production signing.")
        return errors

    errors.append("Production signing requires BIOAUTH_SIGN_CERT_SHA1, BIOAUTH_SIGN_CERT_FILE, or BIOAUTH_SIGN_CERT_PFX_BASE64 with BIOAUTH_SIGN_CERT_PASSWORD for file-based signing.")
    return errors


def normalize_build_profile(value: Any = None) -> str:
    raw = str(value if value is not None else os.environ.get("BIOAUTH_BUILD_PROFILE", DEFAULT_PROFILE)).strip().lower()
    return raw if raw in VALID_PROFILES else DEFAULT_PROFILE


def current_build_profile() -> str:
    return normalize_build_profile()


def normalize_package_profile(value: Any = None) -> str:
    raw = str(value if value is not None else os.environ.get("BIOAUTH_PACKAGE_PROFILE", "") or os.environ.get("BIOAUTH_BUILD_PROFILE", DEFAULT_PROFILE)).strip().lower().replace("_", "-")
    return PACKAGE_PROFILE_ALIASES.get(raw, "dev" if normalize_build_profile() == "dev" else "classic-minimal")


def current_package_profile() -> str:
    return normalize_package_profile()


def package_profile_payload(profile: Any = None) -> Dict[str, Any]:
    resolved = normalize_package_profile(profile)
    matrix = dict(PACKAGE_PROFILE_MATRIX[resolved])
    return {
        "package_profile": resolved,
        "package_profile_label": matrix["label"],
        "package_policy_version": PACKAGE_PROFILE_POLICY_VERSION,
        "requirements": list(matrix["requirements"]),
        "include_deep_deps": bool(matrix["include_deep_deps"]),
        "include_lightgbm": bool(matrix["include_lightgbm"]),
        "include_accelerated_backends": bool(matrix["include_accelerated_backends"]),
        "include_face_backends": bool(matrix.get("include_face_backends", False)),
        "feature_scope": list(matrix["feature_scope"]),
        "excluded_packages": list(matrix["excluded_packages"]),
    }


def profile_payload(profile: Any = None) -> Dict[str, Any]:
    resolved = normalize_build_profile(profile)
    package_payload = package_profile_payload()
    return {
        "profile": resolved,
        "policy_version": PROFILE_POLICY_VERSION,
        "is_production": resolved == "production",
        "is_beta": resolved == "beta",
        "is_dev": resolved == "dev",
        **package_payload,
    }


def production_profile_errors(env: Dict[str, str] | None = None) -> list[str]:
    source = env if env is not None else os.environ
    profile = normalize_build_profile(source.get("BIOAUTH_BUILD_PROFILE", DEFAULT_PROFILE))
    errors: list[str] = []
    if profile == "production":
        errors.extend(signing_configuration_errors(source))
        for flag in DEV_ONLY_FLAGS:
            value = str(source.get(flag, "") or "").strip().lower()
            if value in {"1", "true", "yes", "on"}:
                errors.append(f"{flag} must not be enabled for production builds.")
        build_flavor = str(source.get(DEMO_CLASSIC_BUILD_FLAVOR_ENV, "") or "").strip().lower()
        for flag in DEMO_BUILD_ONLY_FLAGS:
            value = str(source.get(flag, "") or "").strip().lower()
            if value in {"1", "true", "yes", "on"} and build_flavor != DEMO_CLASSIC_BUILD_FLAVOR:
                errors.append(f"{flag} requires BIOAUTH_BUILD_FLAVOR={DEMO_CLASSIC_BUILD_FLAVOR}; commercial production builds must not enable Demo Classic.")
    return errors


def assert_release_profile_safe(env: Dict[str, str] | None = None) -> None:
    errors = production_profile_errors(env)
    if errors:
        raise RuntimeError("Release profile validation failed: " + "; ".join(errors))
