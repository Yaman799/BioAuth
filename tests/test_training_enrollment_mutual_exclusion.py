from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).absolute().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridge import session_runtime_helpers, session_training_helpers
from metadata_core.auto_enrollment import passive_collection_should_start
from metadata_core.auto_training_scheduler import auto_training_should_start
from metadata_core.passive_quality import PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS


def _settings() -> dict:
    return {"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": True}


def _profile() -> dict:
    return {
        "training_can_start": True,
        "session_count": 8,
        "minimum_session_count": 8,
        "recommended_session_count": 15,
        "production_ready": False,
    }


def _session(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "session_kind": "enrollment",
        "training_counts_toward_minimum": True,
        "metadata_trusted": True,
        "bucket": "accepted",
        "keyboard_rows": PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS,
        "mouse_rows": 1,
    }


def _passive_runtime() -> dict:
    return {
        "active": True,
        "session_kind": "enrollment",
        "auto_enrollment": True,
        "collection_source": "passive_auto_enrollment",
        "started_at": 100.0,
        "last_capture_at": 999.0,
        "keyboard_event_count": 250,
        "mouse_event_count": 1,
        "capture_event_count": 251,
    }


def test_passive_auto_enrollment_does_not_start_when_training_active() -> None:
    allowed, reason = passive_collection_should_start(
        settings=_settings(),
        profile={"production_ready": False, "minimum_session_count": 8, "recommended_session_count": 15},
        runtime_state={},
        sessions=[],
        consent_satisfied=True,
        authenticated=True,
        training_active=True,
        app_locked=True,
    )
    assert allowed is False
    assert reason == "training_active"


def test_auto_training_blocks_passive_auto_enrollment_runtime() -> None:
    allowed, reason, _signature = auto_training_should_start(
        settings=_settings(),
        profile=_profile(),
        runtime_state=_passive_runtime(),
        sessions=[_session(str(i)) for i in range(8)],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="enrollment_active",
        now=1000.0,
    )
    assert allowed is False
    assert reason == "passive_auto_enrollment_active"


def test_auto_training_blocks_live_logger_process_even_if_flow_is_idle() -> None:
    allowed, reason, _signature = auto_training_should_start(
        settings=_settings(),
        profile=_profile(),
        runtime_state={"logger_process_alive": True},
        sessions=[_session(str(i)) for i in range(8)],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        now=1000.0,
    )
    assert allowed is False
    assert reason == "logger_process_active"


def test_app_locked_still_does_not_block_auto_training_by_itself() -> None:
    allowed, reason, _signature = auto_training_should_start(
        settings=_settings(),
        profile=_profile(),
        runtime_state={},
        sessions=[_session(str(i)) for i in range(8)],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        app_locked=True,
        now=1000.0,
    )
    assert allowed is True
    assert reason == "ready"


def test_manual_train_blocks_and_requests_passive_stop_before_training() -> None:
    class FakeBridge:
        def __init__(self) -> None:
            self._current_user = {"user_id": "alice"}
            self._runtime_state = _passive_runtime()
            self._running_processes = {}
            self._pending_logger_start = False
            self._training_in_progress = False
            self._status = None
            self.stop_count = 0

        def _session_flow(self, state=None):
            return "enrollment_active" if (state or self._runtime_state).get("active") else "idle"

        def _active_state_for_current_user(self):
            return dict(self._runtime_state)

        def _logger_process_key(self):
            return "logger_user_alice"

        def _set_status(self, message, tone):
            self._status = (message, tone)

        def _t(self, key, **kwargs):
            return key

        def _stop_passive_auto_enrollment_if_active(self, *, reason="opt_out"):
            self.stop_count += 1
            self.stop_reason = reason
            return True

    fake = FakeBridge()
    original_facade = session_training_helpers._facade
    session_training_helpers._facade = lambda: SimpleNamespace()
    try:
        started = session_training_helpers.train_profile(fake, auto_training=False)
    finally:
        session_training_helpers._facade = original_facade
    assert started is False
    assert fake.stop_count == 1
    assert fake.stop_reason == "manual_training_requested"
    assert fake._status == ("training_blocked_passive_enrollment_active", "warn")


def test_passive_finalizer_calls_stop_only_once_for_same_session() -> None:
    class FakeFacade:
        def __init__(self, bridge):
            self._bridge = bridge
            self.time = SimpleNamespace(time=lambda: 1000.0)

        def write_session_state(self, state):
            self._bridge.state = dict(state)

        def invalidate_session_discovery_cache(self):
            self.invalidated = True

    class FakeBridge:
        def __init__(self) -> None:
            self._current_user = {"user_id": "alice"}
            self.state = _passive_runtime()
            self._runtime_state = dict(self.state)
            self._profile = {"session_count": 15, "recommended_session_count": 15}
            self.autoEnrollmentState = {"enabled": True, "consentSatisfied": True, "acceptedSessions": 15, "recommendedSessions": 15}
            self.modelReadinessState = {}
            self._history_sync_pending = False
            self._passive_auto_enrollment_finalizing = False
            self._last_passive_auto_enrollment_block_reason = ""
            self._last_passive_auto_enrollment_finalize_reason = ""
            self.stop_count = 0

        def _active_state_for_current_user(self):
            return dict(self.state)

        def stopCurrentSession(self, silent=True):
            self.stop_count += 1

        def _debug_trace(self, *args, **kwargs):
            pass

    fake = FakeBridge()
    fake_facade = FakeFacade(fake)
    original_facade = session_runtime_helpers._facade
    session_runtime_helpers._facade = lambda: fake_facade
    try:
        assert session_runtime_helpers.maybe_finalize_passive_auto_enrollment(fake) is True
        assert session_runtime_helpers.maybe_finalize_passive_auto_enrollment(fake) is False
    finally:
        session_runtime_helpers._facade = original_facade
    assert fake.stop_count == 1
    assert fake.state["auto_enrollment_finalizing"] is True
    assert fake.state["auto_enrollment_stop_requested"] is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("6 focused training/enrollment mutual exclusion tests passed", flush=True)
    raise SystemExit(0)
