from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metadata_core.auto_training_scheduler import (
    AUTO_TRAINING_FAILURE_COOLDOWN_SECONDS,
    auto_training_block_reason,
    auto_training_should_start,
    background_action_from_status,
    training_readiness_signature,
)


def _session(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "session_kind": "enrollment",
        "training_counts_toward_minimum": True,
        "metadata_trusted": True,
        "bucket": "accepted",
    }


def _ready_profile() -> dict:
    return {
        "training_can_start": True,
        "session_count": 8,
        "minimum_session_count": 8,
        "recommended_session_count": 15,
        "production_ready": False,
    }


def _settings() -> dict:
    return {
        "smart_auto_enrollment_enabled": True,
        "auto_train_when_ready_enabled": True,
    }


def test_auto_training_triggers_only_when_ready_enabled_and_consented() -> None:
    allowed, reason, signature = auto_training_should_start(
        settings=_settings(),
        profile=_ready_profile(),
        runtime_state={},
        sessions=[_session(str(i)) for i in range(8)],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        now=100.0,
    )
    assert allowed is True
    assert reason == "ready"
    assert len(signature) == 64


def test_app_passcode_ui_lock_does_not_block_auto_training_when_ready() -> None:
    allowed, reason, signature = auto_training_should_start(
        settings=_settings(),
        profile=_ready_profile(),
        runtime_state={},
        sessions=[_session(str(i)) for i in range(8)],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        app_locked=True,
        now=100.0,
    )
    assert allowed is True
    assert reason == "ready"
    assert len(signature) == 64


def test_auto_training_does_not_trigger_without_consent_or_when_disabled() -> None:
    allowed, reason, _sig = auto_training_should_start(
        settings=_settings(),
        profile=_ready_profile(),
        runtime_state={},
        sessions=[_session("s1")],
        user_id="alice",
        consent_satisfied=False,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        now=100.0,
    )
    assert allowed is False
    assert reason == "consent_required"

    allowed, reason, _sig = auto_training_should_start(
        settings={"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": False},
        profile=_ready_profile(),
        runtime_state={},
        sessions=[_session("s1")],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        now=100.0,
    )
    assert allowed is False
    assert reason == "auto_training_disabled"


def test_auto_training_still_blocks_auth_setting_runtime_and_signature_failures() -> None:
    allowed, reason, _sig = auto_training_should_start(
        settings=_settings(),
        profile=_ready_profile(),
        runtime_state={},
        sessions=[_session("s1")],
        user_id="alice",
        consent_satisfied=True,
        authenticated=False,
        training_active=False,
        session_flow="idle",
        app_locked=True,
        now=100.0,
    )
    assert allowed is False
    assert reason == "not_authenticated"

    allowed, reason, _sig = auto_training_should_start(
        settings={"smart_auto_enrollment_enabled": False, "auto_train_when_ready_enabled": True},
        profile=_ready_profile(),
        runtime_state={},
        sessions=[_session("s1")],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        app_locked=True,
        now=100.0,
    )
    assert allowed is False
    assert reason == "smart_auto_enrollment_disabled"

    reason = auto_training_block_reason(
        settings=_settings(),
        profile=_ready_profile(),
        runtime_state={},
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        app_locked=True,
        cooldown_until=0.0,
        last_completed_signature="",
        current_signature="",
        now=100.0,
    )
    assert reason == "missing_training_signature"


def test_auto_training_does_not_duplicate_active_or_completed_job() -> None:
    sessions = [_session(str(i)) for i in range(8)]
    signature = training_readiness_signature(user_id="alice", profile=_ready_profile(), sessions=sessions)
    allowed, reason, _sig = auto_training_should_start(
        settings=_settings(),
        profile=_ready_profile(),
        runtime_state={},
        sessions=sessions,
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=True,
        session_flow="idle",
        now=100.0,
    )
    assert allowed is False
    assert reason == "training_active"

    allowed, reason, _sig = auto_training_should_start(
        settings=_settings(),
        profile=_ready_profile(),
        runtime_state={},
        sessions=sessions,
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        last_completed_signature=signature,
        now=100.0,
    )
    assert allowed is False
    assert reason == "already_trained_for_current_data"


def test_auto_training_blocks_unsafe_runtime_states_and_cooldown() -> None:
    allowed, reason, _sig = auto_training_should_start(
        settings=_settings(),
        profile=_ready_profile(),
        runtime_state={"active": True},
        sessions=[_session("s1")],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="enrollment_active",
        now=100.0,
    )
    assert allowed is False
    assert reason == "session_not_idle"

    allowed, reason, _sig = auto_training_should_start(
        settings=_settings(),
        profile=_ready_profile(),
        runtime_state={},
        sessions=[_session("s1")],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        cooldown_until=100.0 + AUTO_TRAINING_FAILURE_COOLDOWN_SECONDS,
        now=100.0,
    )
    assert allowed is False
    assert reason == "cooldown_active"


def test_auto_training_blocks_runtime_active_even_when_session_flow_idle() -> None:
    allowed, reason, _sig = auto_training_should_start(
        settings=_settings(),
        profile=_ready_profile(),
        runtime_state={"active": True},
        sessions=[_session("s1")],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        now=100.0,
    )
    assert allowed is False
    assert reason == "runtime_session_active"


def test_background_action_reports_backend_training_state() -> None:
    assert background_action_from_status(
        auto_training_enabled=True,
        training_ready=True,
        training_active=True,
        active_training_source="auto",
        now=100.0,
    ) == "training_in_background"
    assert background_action_from_status(
        auto_training_enabled=True,
        training_ready=True,
        training_active=False,
        cooldown_until=200.0,
        now=100.0,
    ) == "training_cooldown"


def test_scheduler_reuses_existing_training_path_and_keeps_manual_train_slot() -> None:
    training_helpers = (ROOT / "bridge" / "session_training_helpers.py").read_text(encoding="utf-8")
    session_mixin = (ROOT / "bridge" / "session_mixin.py").read_text(encoding="utf-8")
    refresh_helpers = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text(encoding="utf-8")

    assert "def maybe_start_auto_training" in training_helpers
    assert "started = train_profile(self, auto_training=True)" in training_helpers
    assert "self._auto_training_active_signature = """ in training_helpers
    assert "train_user_model(" in training_helpers
    assert "def trainProfile" in session_mixin
    assert "train_profile(self, auto_training=False)" in session_mixin
    assert "_maybe_start_auto_training" in refresh_helpers
    assert "started_auto_training" in refresh_helpers


def test_training_failure_sets_safe_cooldown_and_shadow_policy_remains_blocked() -> None:
    training_helpers = (ROOT / "bridge" / "session_training_helpers.py").read_text(encoding="utf-8")
    session_runtime = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "AUTO_TRAINING_FAILURE_COOLDOWN_SECONDS" in training_helpers
    assert "_auto_training_cooldown_until" in training_helpers
    assert "approved_for_shadow" in training_helpers
    assert "profile.get(\"production_ready\")" in session_runtime
    assert "model_status == \"approved_for_shadow\"" in training_helpers


def test_qml_displays_backend_training_state_without_fake_state() -> None:
    profile_qml = (ROOT / "qml" / "pages" / "ProfilePage.qml").read_text(encoding="utf-8")
    settings_qml = (ROOT / "qml" / "pages" / "SettingsPage.qml").read_text(encoding="utf-8")
    desktop = (ROOT / "src" / "bioauth" / "app" / "desktop_app_impl.py").read_text(encoding="utf-8")

    assert "backend.modelReadinessState" in profile_qml
    assert "backend.autoEnrollmentState" in profile_qml
    assert "Training your protection model in the background" in profile_qml
    assert "autoEnrollment.backgroundAction" in profile_qml
    assert "modelReadiness.backgroundAction" in profile_qml
    assert "modelReadinessState:" not in profile_qml
    assert "backgroundAction:" not in profile_qml
    assert "backend.setAutoTrainWhenReadyEnabled" in settings_qml
    assert "def modelReadinessState" in desktop
    assert "background_action_from_status" in desktop


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("11 focused auto training scheduler phase5 tests passed", flush=True)
    raise SystemExit(0)
