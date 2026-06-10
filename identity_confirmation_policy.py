from __future__ import annotations

"""Policy helpers for optional face confirmation.

Phase 13 permits an optional fail-closed pre-lock monitor integration only.
It remains opt-in, enrollment/consent-gated, and never writes production training data.
"""

from typing import Any, Mapping

from app_settings import PRIVACY_POLICY_VERSION, feature_flag_enabled

FACE_CONFIRMATION_POLICY_VERSION = PRIVACY_POLICY_VERSION


def has_face_template_consent(settings: Mapping[str, Any] | None) -> bool:
    payload = settings if isinstance(settings, Mapping) else {}
    return (
        bool(payload.get("face_template_consent_granted", False))
        and bool(str(payload.get("face_template_consent_timestamp", "")).strip())
        and str(payload.get("face_template_consent_policy_version", "")).strip() == FACE_CONFIRMATION_POLICY_VERSION
    )


def face_backend_available_for_enrollment(settings: Mapping[str, Any] | None) -> bool:
    payload = settings if isinstance(settings, Mapping) else {}
    return bool(feature_flag_enabled(payload, "enable_face_enrollment") and has_face_template_consent(payload))


def face_backend_available_for_confirmation(settings: Mapping[str, Any] | None) -> bool:
    payload = settings if isinstance(settings, Mapping) else {}
    return bool(feature_flag_enabled(payload, "enable_face_confirmation") and has_face_template_consent(payload))
