from __future__ import annotations

import os
import time
from pathlib import Path
import sys

ROOT = Path(__file__).absolute().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metadata_core.auto_enrollment import (
    AUTO_ENROLLMENT_MIN_SPACING_SECONDS,
    PASSIVE_COLLECTION_SOURCE,
    build_auto_enrollment_state,
    input_coverage_summary,
    metadata_tags_from_environment,
    passive_collection_should_start,
)
def test_passive_collection_requires_enabled_setting_and_consent() -> None:
    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": False},
        profile={},
        runtime_state={},
        sessions=[],
        consent_satisfied=True,
        authenticated=True,
    )
    assert allowed is False
    assert reason == "setting_disabled"

    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": True},
        profile={},
        runtime_state={},
        sessions=[],
        consent_satisfied=False,
        authenticated=True,
    )
    assert allowed is False
    assert reason == "consent_required"

    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": True},
        profile={"session_count": 0, "recommended_session_count": 15},
        runtime_state={},
        sessions=[],
        consent_satisfied=True,
        authenticated=True,
    )
    assert allowed is True
    assert reason == "ready"


def test_passive_collection_blocks_unsafe_runtime_states() -> None:
    cases = [
        ({"active": True, "session_kind": "protected"}, "protected_session_active"),
        ({"active": True, "session_kind": "enrollment"}, "manual_or_other_session_active"),
        ({"technical_failure": True}, "runtime_technical_failure"),
    ]
    for runtime_state, expected in cases:
        allowed, reason = passive_collection_should_start(
            settings={"smart_auto_enrollment_enabled": True},
            profile={},
            runtime_state=runtime_state,
            sessions=[],
            consent_satisfied=True,
            authenticated=True,
        )
        assert allowed is False
        assert reason == expected


def test_app_passcode_ui_lock_does_not_block_passive_collection() -> None:
    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": True},
        profile={"production_ready": False, "session_count": 0, "recommended_session_count": 15},
        runtime_state={},
        sessions=[],
        consent_satisfied=True,
        authenticated=True,
        app_locked=True,
    )
    assert allowed is True
    assert reason == "ready"


def test_passive_collection_still_blocks_real_safety_failures_with_app_locked() -> None:
    cases = [
        ({"consent_satisfied": False, "authenticated": True, "training_active": False}, "consent_required"),
        ({"consent_satisfied": True, "authenticated": False, "training_active": False}, "not_authenticated"),
        ({"consent_satisfied": True, "authenticated": True, "training_active": True}, "training_active"),
    ]
    for kwargs, expected in cases:
        allowed, reason = passive_collection_should_start(
            settings={"smart_auto_enrollment_enabled": True},
            profile={"production_ready": False, "session_count": 0, "recommended_session_count": 15},
            runtime_state={},
            sessions=[],
            app_locked=True,
            **kwargs,
        )
        assert allowed is False
        assert reason == expected

    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": False},
        profile={"production_ready": False, "session_count": 0, "recommended_session_count": 15},
        runtime_state={},
        sessions=[],
        consent_satisfied=True,
        authenticated=True,
        app_locked=True,
    )
    assert allowed is False
    assert reason == "setting_disabled"


def test_passive_collection_blocks_production_ready_and_recommended_sessions() -> None:
    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": True},
        profile={"production_ready": True, "session_count": 0, "recommended_session_count": 15},
        runtime_state={},
        sessions=[],
        consent_satisfied=True,
        authenticated=True,
        app_locked=True,
    )
    assert allowed is False
    assert reason == "production_ready"

    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": True},
        profile={"production_ready": False, "session_count": 15, "minimum_session_count": 8, "recommended_session_count": 15},
        runtime_state={},
        sessions=[],
        consent_satisfied=True,
        authenticated=True,
        app_locked=True,
    )
    assert allowed is False
    assert reason == "recommended_sessions_reached"


def test_backend_auto_enrollment_state_is_truth_derived_not_qml_invented() -> None:
    state = build_auto_enrollment_state(
        settings={"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": True},
        profile={"training_can_start": False, "production_ready": False},
        sessions=[],
        consent_satisfied=True,
        collecting=False,
        collection_block_reason="collection_spacing_active",
    )
    assert state["state"] == "cooldown_after_collection"
    assert state["trainingReady"] is False

    state = build_auto_enrollment_state(
        settings={"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": True},
        profile={"training_can_start": True, "production_ready": False},
        sessions=[],
        consent_satisfied=True,
        collecting=False,
        background_action="training_in_background",
    )
    assert state["state"] == "auto_training_running"

    state = build_auto_enrollment_state(
        settings={"smart_auto_enrollment_enabled": True},
        profile={"training_can_start": True, "production_ready": True},
        sessions=[],
        consent_satisfied=True,
        collecting=False,
    )
    assert state["state"] == "production_ready"


def test_passive_session_metadata_tags_are_safe_and_derivable() -> None:
    tags = metadata_tags_from_environment(
        {
            "BIOAUTH_AUTO_ENROLLMENT": "1",
            "BIOAUTH_COLLECTION_SOURCE": PASSIVE_COLLECTION_SOURCE,
            "BIOAUTH_TIME_OF_DAY_BUCKET": "morning",
        },
        keyboard_rows=80,
        mouse_rows=40,
    )
    assert tags == {
        "auto_enrollment": True,
        "collection_source": PASSIVE_COLLECTION_SOURCE,
        "time_of_day_bucket": "morning",
        "input_coverage": "mixed",
    }
    assert metadata_tags_from_environment({}, keyboard_rows=80, mouse_rows=40) == {}
    assert input_coverage_summary(0, 3) == "mouse_only"
    assert input_coverage_summary(3, 0) == "keyboard_only"


def test_auto_enrollment_state_uses_existing_training_flags_and_dedupes_session_ids() -> None:
    sessions = [
        {
            "session_id": "s1",
            "session_kind": "enrollment",
            "training_counts_toward_minimum": True,
            "metadata_trusted": True,
            "bucket": "accepted",
            "created_at": "2026-04-29T08:15:00+03:00",
            "time_of_day_bucket": "morning",
            "keyboard_rows": 250,
            "mouse_rows": 80,
            "auto_enrollment": True,
            "collection_source": PASSIVE_COLLECTION_SOURCE,
        },
        {
            "session_id": "s1",
            "session_kind": "enrollment",
            "training_counts_toward_minimum": True,
            "metadata_trusted": True,
            "bucket": "accepted",
            "created_at": "2026-04-29T08:16:00+03:00",
            "keyboard_rows": 250,
            "mouse_rows": 80,
        },
        {
            "session_id": "s2",
            "session_kind": "enrollment",
            "training_counts_toward_minimum": False,
            "metadata_trusted": False,
            "bucket": "rejected",
            "created_at": "2026-04-29T19:30:00+03:00",
            "keyboard_rows": 999,
            "mouse_rows": 999,
        },
    ]
    state = build_auto_enrollment_state(
        settings={"smart_auto_enrollment_enabled": True},
        profile={},
        sessions=sessions,
        consent_satisfied=True,
        collecting=True,
    )
    assert state["collecting"] is True
    assert state["acceptedSessions"] == 1
    assert state["timeOfDayCoverage"]["morning"] == 1
    assert state["timeOfDayCoverage"]["evening"] == 0
    assert state["inputCoverage"] == {"keyboard": "strong", "mouse": "partial", "mixed": "strong"}
    assert state["state"] == "collecting_passive_session"
    assert "quality gates" in state["collectionStatusText"]


def test_anti_clustering_blocks_recent_auto_session_but_allows_manual_compatibility() -> None:
    recent_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - (AUTO_ENROLLMENT_MIN_SPACING_SECONDS // 2)))
    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": True},
        profile={"session_count": 1, "recommended_session_count": 15},
        runtime_state={},
        sessions=[
            {
                "session_id": "auto-recent",
                "session_kind": "enrollment",
                "training_counts_toward_minimum": True,
                "metadata_trusted": True,
                "bucket": "accepted",
                "created_at": recent_text,
                "keyboard_rows": 250,
                "mouse_rows": 1,
                "auto_enrollment": True,
                "collection_source": PASSIVE_COLLECTION_SOURCE,
            }
        ],
        consent_satisfied=True,
        authenticated=True,
    )
    assert allowed is False
    assert reason == "collection_spacing_active"

    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": True},
        profile={"session_count": 1, "recommended_session_count": 15},
        runtime_state={},
        sessions=[
            {
                "session_id": "manual-recent",
                "session_kind": "enrollment",
                "training_counts_toward_minimum": True,
                "metadata_trusted": True,
                "bucket": "accepted",
                "created_at": recent_text,
            }
        ],
        consent_satisfied=True,
        authenticated=True,
    )
    assert allowed is True
    assert reason == "ready"


def test_refresh_helper_starts_passive_collection_through_existing_enrollment_path_only() -> None:
    session_helpers = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    refresh_helpers = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text(encoding="utf-8")
    session_mixin = (ROOT / "bridge" / "session_mixin.py").read_text(encoding="utf-8")

    assert "def maybe_start_passive_auto_enrollment" in session_helpers
    assert "start_enrollment(self, passive_auto_enrollment=True)" in session_helpers
    assert "def start_enrollment(self, *, passive_auto_enrollment: bool = False)" in session_helpers
    assert "BIOAUTH_AUTO_ENROLLMENT" in session_mixin
    assert "passive_collection_env" in session_mixin
    assert "maybe_start_passive_auto_enrollment" in refresh_helpers


def test_opt_out_disables_active_passive_collection_without_touching_manual_sessions() -> None:
    settings_mixin = (ROOT / "bridge" / "settings_mixin.py").read_text(encoding="utf-8")
    session_helpers = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")

    assert "_stop_passive_auto_enrollment_if_active" in settings_mixin
    assert "setting_disabled" in settings_mixin
    assert "stop_passive_auto_enrollment_if_active" in session_helpers
    assert "is_passive_auto_enrollment_state" in session_helpers
    assert "leave manual sessions untouched" in session_helpers


def test_qml_binds_to_backend_auto_enrollment_state_without_fake_state() -> None:
    qml_files = [
        ROOT / "qml" / "pages" / "ProfilePage.qml",
        ROOT / "qml" / "pages" / "SettingsPage.qml",
        ROOT / "qml" / "pages" / "settings" / "SettingsSecurityTab.qml",
        ROOT / "qml" / "pages" / "settings" / "SettingsPrivacyCenterCard.qml",
    ]
    for qml_file in qml_files:
        text = qml_file.read_text(encoding="utf-8")
        assert "backend.autoEnrollmentState" in text
        assert "autoEnrollmentState:" not in text
        assert "acceptedSessions:" not in text
        assert "trainingReady:" not in text


def test_phase3_does_not_auto_train_promote_or_unlock_shadow_only() -> None:
    auto_enrollment = (ROOT / "metadata_core" / "auto_enrollment.py").read_text(encoding="utf-8")
    session_helpers = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    refresh_helpers = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text(encoding="utf-8")

    start_idx = session_helpers.index("def maybe_start_passive_auto_enrollment")
    stop_idx = session_helpers.index("def stop_passive_auto_enrollment_if_active", start_idx)
    passive_start_section = session_helpers[start_idx:stop_idx]
    for forbidden in ("train_user_model", "trainProfile", "promote_candidate", "write_active_runtime_pointer", "start_protected_session"):
        assert forbidden not in passive_start_section
        assert forbidden not in auto_enrollment
    assert "maybe_start_passive_auto_enrollment" in refresh_helpers

    protected_idx = session_helpers.index("def start_protected_session")
    gate_idx = session_helpers.index('if not bool(profile.get("production_ready"))', protected_idx)
    process_idx = session_helpers.index('self._start_process', protected_idx)
    assert gate_idx < process_idx


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("13 focused auto enrollment passive phase3 tests passed", flush=True)
    raise SystemExit(0)
