"""User-safe status text filtering for BioAuth.

This module is the single authoritative place for filtering internal/research
terms out of user-facing status messages.

Previously this logic was duplicated across three QML files as JavaScript:
  - qml/Main.qml:userSafeStatusText()
  - qml/UserShell.qml:userSafeStatusText()
  - qml/pages/user/UserProtectionPage.qml:userSafeText()

Each copy had a slightly different keyword list, meaning some internal terms
could leak to users if only some copies were updated.  Moving the filter here
ensures one change fixes all three.

Usage (from Python bridge):
  from bioauth.ui_state.safe_text import user_safe_status_text, user_safe_protection_text

Usage (from QML — backend exposes these as properties):
  backend.safeStatusMessage   → filtered statusMessage
  backend.safeProtectionText  → filtered protection-page runtime text

Design rule: this module NEVER leaks internal codes.  When in doubt, return
the fallback string rather than the original.
"""
from __future__ import annotations

import re
from typing import Optional


# ── Terms that must never appear in user-facing text ─────────────────────────

_SHADOW_TERMS = frozenset({
    "shadow",
    "collecting evidence",
    "lock-quality",
    "waiting for evidence",
    "candidate",
    "challenger",
    "promotion",
    "ledger",
    "digest",
    "system evidence",
    "raw telemetry",
    "reason_code",
    "gate_results",
})

_DEVELOPER_TERMS = frozenset({
    "far",
    "frr",
    "eer",
    "calibration_maturity",
    "feature_schema",
    "bundle_digest",
    "artifact_digest",
    "production_approval",
})


def _contains_any(text: str, terms: frozenset) -> bool:
    lower = text.lower()
    return any(term in lower for term in terms)


def _is_attention_level(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in ("suspicious", "attention", "fail", "mismatch", "error"))


def _is_pending_level(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in ("pending", "waiting", "collecting", "partial"))


def user_safe_status_text(text: str, *, fallback: str = "", language: str = "en") -> str:
    """Return a user-safe version of a backend status message.

    Filters out shadow/research/developer terminology that should never reach
    the user-facing UI.  Returns the original text if it contains no internal
    terms.

    Args:
        text:     The raw backend status message.
        fallback: Returned when text is empty.
        language: "ar" for Arabic fallback strings, "en" for English.
    """
    value = str(text or "").strip()
    if not value:
        return fallback or ""

    ar = language == "ar"

    if _contains_any(value, _SHADOW_TERMS):
        if _is_attention_level(value):
            return "فحص الحماية يحتاج انتباهًا." if ar else "Background check needs attention."
        if _is_pending_level(value):
            return "فحص الحماية جارٍ." if ar else "Background check in progress."
        return "فحص الحماية نشط." if ar else "Background check active."

    if _contains_any(value, _DEVELOPER_TERMS):
        return "تتم مراجعة تفاصيل الحماية." if ar else "Protection details are being reviewed."

    return value


def user_safe_protection_text(text: str, *, fallback: str = "", language: str = "en") -> str:
    """Filtered version of protection-page runtime text.

    Stricter than user_safe_status_text — additionally blocks face model
    paths and internal runtime codes from showing on the protection page.
    """
    value = str(text or "").strip()
    if not value:
        return fallback or ""

    ar = language == "ar"

    if _contains_any(value, _SHADOW_TERMS):
        if _is_attention_level(value):
            return "مراجعة تحديث الحماية تحتاج انتباهًا" if ar else "Protection update review needs attention"
        if _is_pending_level(value):
            return "يتم جمع أدلة آمنة قبل إتاحة التحديث." if ar else "Safe evidence is being collected before the update becomes available."
        return "تحديث الحماية قيد المراجعة في الخلفية." if ar else "A protection update is being reviewed in the background."

    lower = value.lower()

    # Face model missing — user-safe message
    if "face" in lower and "model" in lower and ("missing" in lower or "not found" in lower):
        return "إعداد تأكيد الوجه مطلوب" if ar else "Face confirmation needs setup"

    if _contains_any(value, _DEVELOPER_TERMS):
        return "تتم مراجعة تفاصيل الحماية." if ar else "Protection details are being reviewed."

    return value


def is_safe_for_user(text: str) -> bool:
    """Return True if the text contains no internal terms."""
    value = str(text or "").strip()
    return not (_contains_any(value, _SHADOW_TERMS) or _contains_any(value, _DEVELOPER_TERMS))
