from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metadata_core.auto_enrollment import (
    AUTO_ENROLLMENT_INACTIVITY_SECONDS,
    AUTO_ENROLLMENT_MAX_DURATION_SECONDS,
    AUTO_ENROLLMENT_MIN_DURATION_SECONDS,
    AUTO_ENROLLMENT_MIN_INACTIVITY_CAPTURE_EVENTS,
    AUTO_ENROLLMENT_MIN_INACTIVITY_KEYBOARD_EVENTS,
    AUTO_ENROLLMENT_MIN_INACTIVITY_MOUSE_EVENTS,
    AUTO_ENROLLMENT_MIN_SPACING_SECONDS,
    AUTO_ENROLLMENT_TARGET_CAPTURE_EVENTS,
    AUTO_ENROLLMENT_TARGET_KEYBOARD_EVENTS,
    AUTO_ENROLLMENT_TARGET_MOUSE_EVENTS,
    PASSIVE_COLLECTION_SOURCE,
    passive_collection_should_finalize,
)
from metadata_core.auto_training_scheduler import auto_training_should_start


def _runtime(*, now: float = 1000.0, duration: int = 90, keyboard: int = 0, mouse: int = 0, capture: int | None = None, last_capture_delta: int = 5, kind: str = "enrollment", passive: bool = True) -> dict:
    state = {
        "active": True,
        "session_kind": kind,
        "started_at": now - duration,
        "logger_heartbeat_at": now,
        "last_capture_at": now - last_capture_delta,
        "keyboard_event_count": keyboard,
        "mouse_event_count": mouse,
        "capture_event_count": keyboard + mouse if capture is None else capture,
    }
    if passive:
        state.update({"auto_enrollment": True, "collection_source": PASSIVE_COLLECTION_SOURCE})
    return state


def _auto_state(**overrides: object) -> dict:
    payload = {
        "enabled": True,
        "consentSatisfied": True,
        "acceptedSessions": 4,
        "recommendedSessions": 15,
        "trainingReady": False,
        "autoTrainingEnabled": True,
    }
    payload.update(overrides)
    return payload


def _ready_profile() -> dict:
    return {"training_can_start": True, "session_count": 8, "minimum_session_count": 8, "recommended_session_count": 15}


def _settings() -> dict:
    return {"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": True}


def _trusted_session(session_id: str) -> dict:
    return {"session_id": session_id, "session_kind": "enrollment", "training_counts_toward_minimum": True, "metadata_trusted": True, "bucket": "accepted"}


def test_passive_finalizer_constants_are_tuned_for_passive_capture() -> None:
    assert AUTO_ENROLLMENT_MIN_DURATION_SECONDS == 60
    assert AUTO_ENROLLMENT_TARGET_KEYBOARD_EVENTS == 2500
    assert AUTO_ENROLLMENT_TARGET_MOUSE_EVENTS == 100000
    assert AUTO_ENROLLMENT_TARGET_CAPTURE_EVENTS == 100000
    assert AUTO_ENROLLMENT_TARGET_CAPTURE_EVENTS >= AUTO_ENROLLMENT_TARGET_MOUSE_EVENTS
    assert AUTO_ENROLLMENT_INACTIVITY_SECONDS == 120
    assert AUTO_ENROLLMENT_MIN_INACTIVITY_KEYBOARD_EVENTS == 250
    assert AUTO_ENROLLMENT_MIN_INACTIVITY_MOUSE_EVENTS == 10000
    assert AUTO_ENROLLMENT_MIN_INACTIVITY_CAPTURE_EVENTS == 25000
    assert AUTO_ENROLLMENT_MAX_DURATION_SECONDS == 90 * 60
    assert AUTO_ENROLLMENT_MIN_SPACING_SECONDS == 10 * 60


def test_capture_event_target_finalizes_after_minimum_duration() -> None:
    ok, reason = passive_collection_should_finalize(_runtime(keyboard=0, mouse=AUTO_ENROLLMENT_TARGET_CAPTURE_EVENTS), auto_enrollment_state=_auto_state(), now=1000.0)
    assert ok is True
    assert reason == "evidence_target_reached"


def test_does_not_finalize_before_minimum_duration() -> None:
    ok, reason = passive_collection_should_finalize(_runtime(duration=AUTO_ENROLLMENT_MIN_DURATION_SECONDS - 1, keyboard=AUTO_ENROLLMENT_TARGET_KEYBOARD_EVENTS, mouse=AUTO_ENROLLMENT_TARGET_MOUSE_EVENTS), auto_enrollment_state=_auto_state(), now=1000.0)
    assert ok is False
    assert reason == "minimum_duration_waiting"


def test_keyboard_targeted_collection_waits_for_keyboard_evidence() -> None:
    readiness = {"nextBestAction": "collect_keyboard_mixed_sessions"}
    ok, reason = passive_collection_should_finalize(_runtime(keyboard=5, mouse=200), auto_enrollment_state=_auto_state(), model_readiness_state=readiness, now=1000.0)
    assert ok is False
    assert reason == "collecting_more_evidence"
    ok, reason = passive_collection_should_finalize(_runtime(keyboard=AUTO_ENROLLMENT_TARGET_KEYBOARD_EVENTS, mouse=0), auto_enrollment_state=_auto_state(), model_readiness_state=readiness, now=1000.0)
    assert ok is True
    assert reason == "keyboard_target_reached"


def test_mouse_targeted_collection_waits_for_mouse_evidence() -> None:
    readiness = {"nextBestAction": "collect_mouse_mixed_sessions"}
    ok, reason = passive_collection_should_finalize(_runtime(keyboard=200, mouse=5), auto_enrollment_state=_auto_state(), model_readiness_state=readiness, now=1000.0)
    assert ok is False
    assert reason == "collecting_more_evidence"
    ok, reason = passive_collection_should_finalize(_runtime(keyboard=0, mouse=AUTO_ENROLLMENT_TARGET_MOUSE_EVENTS), auto_enrollment_state=_auto_state(), model_readiness_state=readiness, now=1000.0)
    assert ok is True
    assert reason == "mouse_target_reached"


def test_mixed_targeted_collection_uses_strong_mixed_evidence_rule() -> None:
    readiness = {"nextBestAction": "collect_mouse_mixed_sessions"}
    ok, reason = passive_collection_should_finalize(_runtime(keyboard=AUTO_ENROLLMENT_TARGET_KEYBOARD_EVENTS, mouse=AUTO_ENROLLMENT_TARGET_MOUSE_EVENTS - 1), auto_enrollment_state=_auto_state(), model_readiness_state=readiness, now=1000.0)
    assert ok is False
    assert reason == "collecting_more_evidence"
    ok, reason = passive_collection_should_finalize(_runtime(keyboard=AUTO_ENROLLMENT_TARGET_KEYBOARD_EVENTS, mouse=AUTO_ENROLLMENT_TARGET_MOUSE_EVENTS), auto_enrollment_state=_auto_state(), model_readiness_state=readiness, now=1000.0)
    assert ok is True
    assert reason == "mixed_input_target_reached"


def test_inactivity_does_not_finalize_with_legacy_weak_20_event_heuristics() -> None:
    ok, reason = passive_collection_should_finalize(
        _runtime(keyboard=20, mouse=0, last_capture_delta=AUTO_ENROLLMENT_INACTIVITY_SECONDS + 10),
        auto_enrollment_state=_auto_state(),
        now=1000.0,
    )
    assert ok is False
    assert reason == "collecting_more_evidence"

    ok, reason = passive_collection_should_finalize(
        _runtime(keyboard=0, mouse=20, last_capture_delta=AUTO_ENROLLMENT_INACTIVITY_SECONDS + 10),
        auto_enrollment_state=_auto_state(),
        now=1000.0,
    )
    assert ok is False
    assert reason == "collecting_more_evidence"


def test_inactivity_finalizes_only_after_explicit_minimum_evidence_and_threshold() -> None:
    ok, reason = passive_collection_should_finalize(_runtime(keyboard=5, mouse=5, last_capture_delta=AUTO_ENROLLMENT_INACTIVITY_SECONDS + 10), auto_enrollment_state=_auto_state(), now=1000.0)
    assert ok is False
    assert reason == "collecting_more_evidence"

    for state in (
        _runtime(keyboard=AUTO_ENROLLMENT_MIN_INACTIVITY_KEYBOARD_EVENTS, mouse=0, last_capture_delta=AUTO_ENROLLMENT_INACTIVITY_SECONDS + 10),
        _runtime(keyboard=0, mouse=AUTO_ENROLLMENT_MIN_INACTIVITY_MOUSE_EVENTS, last_capture_delta=AUTO_ENROLLMENT_INACTIVITY_SECONDS + 10),
        _runtime(keyboard=0, mouse=0, capture=AUTO_ENROLLMENT_MIN_INACTIVITY_CAPTURE_EVENTS, last_capture_delta=AUTO_ENROLLMENT_INACTIVITY_SECONDS + 10),
    ):
        ok, reason = passive_collection_should_finalize(state, auto_enrollment_state=_auto_state(), now=1000.0)
        assert ok is True
        assert reason == "inactivity_after_minimum_evidence"


def test_max_duration_finalizes_at_ninety_minutes_even_if_evidence_is_weak() -> None:
    assert AUTO_ENROLLMENT_MAX_DURATION_SECONDS == 90 * 60
    ok, reason = passive_collection_should_finalize(_runtime(now=10000.0, duration=AUTO_ENROLLMENT_MAX_DURATION_SECONDS + 1, keyboard=1, mouse=1), auto_enrollment_state=_auto_state(), now=10000.0)
    assert ok is True
    assert reason == "max_duration_reached"


def test_manual_enrollment_and_protected_sessions_are_not_finalized() -> None:
    ok, reason = passive_collection_should_finalize(_runtime(passive=False, keyboard=200, mouse=200), auto_enrollment_state=_auto_state(), now=1000.0)
    assert ok is False
    assert reason == "not_passive_auto_enrollment"
    ok, reason = passive_collection_should_finalize(_runtime(kind="protected", keyboard=200, mouse=200), auto_enrollment_state=_auto_state(), now=1000.0)
    assert ok is False
    assert reason == "not_enrollment"


def test_setting_disabled_and_consent_revoked_stop_safely() -> None:
    ok, reason = passive_collection_should_finalize(_runtime(duration=1), auto_enrollment_state=_auto_state(enabled=False), now=1000.0)
    assert ok is True
    assert reason == "setting_disabled"
    ok, reason = passive_collection_should_finalize(_runtime(duration=1), auto_enrollment_state=_auto_state(consentSatisfied=False), now=1000.0)
    assert ok is True
    assert reason == "consent_revoked"


def test_auto_training_blocked_while_passive_active_and_allowed_after_finalization() -> None:
    sessions = [_trusted_session(str(i)) for i in range(8)]
    allowed, reason, _ = auto_training_should_start(
        settings=_settings(), profile=_ready_profile(), runtime_state=_runtime(), sessions=sessions, user_id="alice", consent_satisfied=True, authenticated=True, training_active=False, session_flow="enrollment_active", now=1000.0
    )
    assert allowed is False
    assert reason == "passive_auto_enrollment_active"
    allowed, reason, _ = auto_training_should_start(
        settings=_settings(), profile=_ready_profile(), runtime_state={"active": False}, sessions=sessions, user_id="alice", consent_satisfied=True, authenticated=True, training_active=False, session_flow="idle", now=1000.0
    )
    assert allowed is True
    assert reason == "ready"


def test_bridge_hook_order_and_spacing_guard_prevent_immediate_restart() -> None:
    refresh = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text(encoding="utf-8")
    runtime = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "_maybe_finalize_passive_auto_enrollment" in refresh
    assert refresh.index("passive_finalizer") < refresh.index("_maybe_start_auto_training")
    assert "not finalized_passive_auto_enrollment" in refresh
    assert "AUTO_ENROLLMENT_MIN_SPACING_SECONDS" in runtime
    assert "_last_passive_auto_enrollment_finalized_at" in runtime


def test_finalizer_is_limited_to_passive_auto_enrollment_source() -> None:
    auto = (ROOT / "metadata_core" / "auto_enrollment.py").read_text(encoding="utf-8")
    runtime = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    helper = auto[auto.index("def passive_collection_should_finalize"):auto.index("def _session_identity")]
    assert "is_passive_auto_enrollment_state" in helper
    assert "session_kind" in helper and "enrollment" in helper
    finalizer = runtime[runtime.index("def maybe_finalize_passive_auto_enrollment"):runtime.index("def start_enrollment")]
    assert "_is_passive_auto_enrollment_state" in finalizer
    assert "stopCurrentSession(silent=True)" in finalizer


def test_qml_static_displays_backend_owned_finalizer_state() -> None:
    profile = (ROOT / "qml" / "pages" / "ProfilePage.qml").read_text(encoding="utf-8")
    overview = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    assert "backend.autoEnrollmentState" in profile
    assert "autoEnrollment.backgroundAction" in profile
    assert "finalizing_passive_session" not in overview
    assert "autoEnrollmentState:" not in profile + overview
    assert "backgroundAction:" not in profile + overview
    assert "finalizing_passive_session" in desktop


def test_existing_quality_gates_remain_authoritative_after_finalization() -> None:
    auto = (ROOT / "metadata_core" / "auto_enrollment.py").read_text(encoding="utf-8")
    assert "never decides whether the\n    session counts for training" in auto
    assert "def _is_training_enrollment_session" in auto
    assert "training_counts_toward_minimum" in auto
    assert "metadata_trusted" in auto


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("16 focused quality-based auto enrollment finalizer tests passed", flush=True)
    raise SystemExit(0)
