"""Passive Smart Auto Enrollment quality-floor helpers.

These helpers deliberately do not decide model readiness, training acceptance,
shadow safety, or production promotion. They only provide a conservative floor
for deciding whether a passive auto-enrollment archive is allowed to contribute
to trusted enrollment-session counts. Existing archive/session quality gates and
training-selection gates remain authoritative after this floor.
"""

from __future__ import annotations

from typing import Any, Mapping

PASSIVE_AUTO_ENROLLMENT_SOURCE = "passive_auto_enrollment"

# Keep these aligned with the passive finalizer inactivity evidence thresholds.
# Passing this floor means a passive candidate has enough evidence to be counted
# by trusted enrollment-session summaries if all other archive/session gates also
# pass; it does not mean the session is accepted for training by itself.
PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS = 250
PASSIVE_TRUSTED_MIN_MOUSE_EVENTS = 10000
PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS = 25000


def _safe_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def is_passive_auto_enrollment_session(session: Mapping[str, Any] | None) -> bool:
    """Return whether metadata describes a passive auto-enrollment archive."""

    if not isinstance(session, Mapping):
        return False
    return bool(session.get("auto_enrollment")) or str(session.get("collection_source") or "").strip().lower() == PASSIVE_AUTO_ENROLLMENT_SOURCE


def passive_evidence_counts(session: Mapping[str, Any] | None) -> tuple[int, int, int]:
    """Return safe keyboard, mouse, and total-capture evidence counts."""

    if not isinstance(session, Mapping):
        return 0, 0, 0
    keyboard = max(0, _safe_int(session.get("keyboard_event_count"), _safe_int(session.get("keyboard_rows"))))
    mouse = max(0, _safe_int(session.get("mouse_event_count"), _safe_int(session.get("mouse_rows"))))
    capture = max(
        0,
        _safe_int(
            session.get("capture_event_count"),
            _safe_int(session.get("capture_rows"), _safe_int(session.get("total_rows"), keyboard + mouse)),
        ),
    )
    if capture < keyboard + mouse:
        capture = keyboard + mouse
    return keyboard, mouse, capture


def passive_session_meets_trusted_minimum_floor(session: Mapping[str, Any] | None) -> bool:
    """Return whether a passive candidate clears the trusted-minimum floor.

    This is stricter than the generic archive activity baseline and prevents
    very small passive candidates, such as K32/M1658, from being described as
    trusted enrollment minimum evidence. It remains only a minimum floor; normal
    archive integrity, eligibility, and training quality gates still decide any
    later training use.
    """

    keyboard, mouse, capture = passive_evidence_counts(session)
    return bool(
        keyboard >= PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS
        or mouse >= PASSIVE_TRUSTED_MIN_MOUSE_EVENTS
        or capture >= PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS
    )


def session_meets_passive_trusted_minimum_floor_if_needed(session: Mapping[str, Any] | None) -> bool:
    """Apply the passive floor only to passive auto-enrollment sessions."""

    if not is_passive_auto_enrollment_session(session):
        return True
    return passive_session_meets_trusted_minimum_floor(session)


def enrollment_session_counts_toward_trusted_minimum(
    session: Mapping[str, Any] | None,
    *,
    accepted: bool,
    trusted: bool,
    training_eligible: bool,
    quality_ok: bool,
) -> bool:
    """Return the trusted-minimum count decision without training side effects.

    This combines the existing archive/session gate facts supplied by dashboard
    code with the passive-only evidence floor. It does not train, evaluate, or
    promote a model.
    """

    return bool(
        accepted
        and trusted
        and training_eligible
        and quality_ok
        and session_meets_passive_trusted_minimum_floor_if_needed(session)
    )


__all__ = [
    "PASSIVE_AUTO_ENROLLMENT_SOURCE",
    "PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS",
    "PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS",
    "PASSIVE_TRUSTED_MIN_MOUSE_EVENTS",
    "enrollment_session_counts_toward_trusted_minimum",
    "is_passive_auto_enrollment_session",
    "passive_evidence_counts",
    "passive_session_meets_trusted_minimum_floor",
    "session_meets_passive_trusted_minimum_floor_if_needed",
]
