from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).absolute().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridge import session_runtime_helpers
from metadata_core.auto_enrollment import (
    AUTO_ENROLLMENT_MIN_DURATION_SECONDS,
    PASSIVE_COLLECTION_SOURCE,
    passive_collection_should_finalize,
    passive_collection_should_start,
)
from metadata_core.passive_quality import (
    PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS,
    PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS,
    PASSIVE_TRUSTED_MIN_MOUSE_EVENTS,
    enrollment_session_counts_toward_trusted_minimum,
    passive_session_meets_trusted_minimum_floor,
)


def _meta(
    name: str,
    *,
    keyboard: int,
    mouse: int,
    capture: int | None = None,
    passive: bool = True,
    training_eligible: bool = True,
) -> dict:
    meta = {
        "session_id": name,
        "user_id": "alice",
        "session_kind": "enrollment",
        "bucket": "accepted",
        "archive_group": "accepted",
        "final_decision": "legit",
        "metadata_trusted": True,
        "training_eligible": bool(training_eligible),
        "keyboard_rows": int(keyboard),
        "mouse_rows": int(mouse),
        "duration_seconds": 90,
        "stop_reason": "control_stop",
    }
    if capture is not None:
        meta["capture_event_count"] = int(capture)
    if passive:
        meta["auto_enrollment"] = True
        meta["collection_source"] = PASSIVE_COLLECTION_SOURCE
    return meta


def _counts(meta: dict) -> bool:
    return enrollment_session_counts_toward_trusted_minimum(
        meta,
        accepted=True,
        trusted=True,
        training_eligible=bool(meta.get("training_eligible")),
        quality_ok=True,
    )


def _runtime(*, duration: float = 120.0, keyboard: int = 0, mouse: int = 0, capture: int | None = None) -> dict:
    now = 1000.0
    return {
        "active": True,
        "session_kind": "enrollment",
        "auto_enrollment": True,
        "collection_source": PASSIVE_COLLECTION_SOURCE,
        "started_at": now - duration,
        "last_capture_at": now - 1,
        "keyboard_event_count": keyboard,
        "mouse_event_count": mouse,
        "capture_event_count": int(capture if capture is not None else keyboard + mouse),
    }


def test_passive_evidence_floor_rejects_tiny_runtime_sample() -> None:
    tiny = _meta("passive-tiny", keyboard=32, mouse=1658)
    assert passive_session_meets_trusted_minimum_floor(tiny) is False
    assert _counts(tiny) is False


def test_passive_tiny_session_is_candidate_not_trusted_minimum_in_dashboard_source() -> None:
    dashboard = (ROOT / "metadata_core" / "dashboard.py").read_text(encoding="utf-8")
    assert "passive_candidate_below_quality_floor" in dashboard
    assert "Passive candidate archived, but it needs more evidence" in dashboard
    assert "enrollment_session_counts_toward_trusted_minimum" in dashboard
    assert "counts_toward_minimum = bool(accepted and trusted and training_eligible and quality_ok)" not in dashboard


def test_passive_keyboard_mouse_or_capture_floor_can_count_with_existing_gates() -> None:
    keyboard = _meta("passive-keyboard-floor", keyboard=PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS, mouse=1)
    mouse = _meta("passive-mouse-floor", keyboard=1, mouse=PASSIVE_TRUSTED_MIN_MOUSE_EVENTS)
    capture = _meta("passive-capture-floor", keyboard=15, mouse=15, capture=PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS)
    assert _counts(keyboard) is True
    assert _counts(mouse) is True
    assert _counts(capture) is True


def test_manual_enrollment_behavior_is_not_affected_by_passive_floor() -> None:
    manual = _meta("manual-small-but-generic-quality", keyboard=32, mouse=1658, passive=False)
    assert _counts(manual) is True


def test_passive_start_allows_more_collection_when_only_tiny_passive_archives_exist() -> None:
    tiny_sessions = [_meta(f"tiny-{index}", keyboard=32, mouse=1658) for index in range(15)]
    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": True},
        profile={"production_ready": False, "minimum_session_count": 8, "recommended_session_count": 15},
        runtime_state={},
        sessions=tiny_sessions,
        consent_satisfied=True,
        authenticated=True,
        app_locked=True,
    )
    assert allowed is True
    assert reason == "ready"


def test_passive_start_blocks_when_recommended_quality_sessions_are_reached() -> None:
    trusted_sessions = [_meta(f"quality-{index}", keyboard=PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS, mouse=1) for index in range(15)]
    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": True},
        profile={"production_ready": False, "minimum_session_count": 8, "recommended_session_count": 15},
        runtime_state={},
        sessions=trusted_sessions,
        consent_satisfied=True,
        authenticated=True,
        app_locked=True,
    )
    assert allowed is False
    assert reason == "recommended_sessions_reached"


def test_passive_start_preserves_real_safety_blockers() -> None:
    base = {
        "settings": {"smart_auto_enrollment_enabled": True},
        "profile": {"production_ready": False, "minimum_session_count": 8, "recommended_session_count": 15},
        "runtime_state": {},
        "sessions": [],
        "consent_satisfied": True,
        "authenticated": True,
        "app_locked": True,
    }
    cases = [
        ({"consent_satisfied": False}, "consent_required"),
        ({"authenticated": False}, "not_authenticated"),
        ({"runtime_state": {"active": True, "session_kind": "enrollment"}}, "manual_or_other_session_active"),
        ({"runtime_state": {"active": True, "session_kind": "protected"}}, "protected_session_active"),
        ({"training_active": True}, "training_active"),
    ]
    for override, expected in cases:
        args = dict(base)
        args.update(override)
        allowed, reason = passive_collection_should_start(**args)
        assert allowed is False
        assert reason == expected


def test_runtime_start_helper_does_not_spawn_logger_when_recommended_reached() -> None:
    class FakeBridge:
        _current_user = {"user_id": "alice"}
        _last_passive_auto_enrollment_block_reason = ""
        _pending_passive_auto_enrollment = False
        _last_process_start_error = ""

        def _auto_enrollment_collection_decision(self):
            return False, "recommended_sessions_reached"

    fake = FakeBridge()
    assert session_runtime_helpers.maybe_start_passive_auto_enrollment(fake) is False
    assert fake._last_passive_auto_enrollment_block_reason == "recommended_sessions_reached"
    assert fake._pending_passive_auto_enrollment is False


def test_finalizer_recommended_sessions_uses_quality_count_not_tiny_archives() -> None:
    ok, reason = passive_collection_should_finalize(
        _runtime(duration=AUTO_ENROLLMENT_MIN_DURATION_SECONDS + 5, keyboard=40, mouse=1600),
        auto_enrollment_state={"enabled": True, "consentSatisfied": True, "acceptedSessions": 0, "recommendedSessions": 15},
        profile={"session_count": 0, "recommended_session_count": 15},
        now=1000.0,
    )
    assert ok is False
    assert reason == "collecting_more_evidence"

    ok, reason = passive_collection_should_finalize(
        _runtime(duration=AUTO_ENROLLMENT_MIN_DURATION_SECONDS + 5, keyboard=40, mouse=1600),
        auto_enrollment_state={"enabled": True, "consentSatisfied": True, "acceptedSessions": 15, "recommendedSessions": 15},
        profile={"session_count": 15, "recommended_session_count": 15},
        now=1000.0,
    )
    assert ok is True
    assert reason == "recommended_sessions_reached"


def test_update_session_index_for_path_warning_call_resolves() -> None:
    text = (ROOT / "bridge" / "refresh_mixin.py").read_text(encoding="utf-8")
    assert "update_session_index_for_path" in text
    assert "from .shared import" in text


def test_qml_backend_owned_and_no_fake_readiness_state() -> None:
    overview = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    profile = (ROOT / "qml" / "pages" / "ProfilePage.qml").read_text(encoding="utf-8")
    assert "backend.autoEnrollmentState" in profile
    assert "autoEnrollmentState:" not in overview + profile
    assert "productionReady:" not in overview + profile
    assert "trainingReady:" not in overview + profile
    assert "Smart Auto Enrollment" in profile
    assert "profileSmartAutoEnrollmentControls" in profile
    assert "smartAutoEnrollmentMissionBox" not in overview


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("11 focused auto enrollment recommended session quality gate tests passed", flush=True)
    raise SystemExit(0)
