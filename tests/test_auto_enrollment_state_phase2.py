from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metadata_core.auto_enrollment import build_auto_enrollment_state


def test_auto_enrollment_state_exists_and_disabled_defaults_are_safe() -> None:
    state = build_auto_enrollment_state(settings={}, profile={}, sessions=[], consent_satisfied=False)

    assert set(state) >= {
        "enabled",
        "consentSatisfied",
        "collecting",
        "acceptedSessions",
        "requiredSessions",
        "recommendedSessions",
        "trainingReady",
        "timeOfDayCoverage",
        "inputCoverage",
        "collectionStatusText",
        "nextBestActionText",
        "autoTrainingEnabled",
        "autoPromotionEnabled",
    }
    assert state["enabled"] is False
    assert state["consentSatisfied"] is False
    assert state["collecting"] is False
    assert state["autoTrainingEnabled"] is False
    assert state["autoPromotionEnabled"] is False
    assert state["requiredSessions"] == 8
    assert state["recommendedSessions"] == 15
    assert "No passive collection" in state["collectionStatusText"]


def test_consent_missing_blocks_collection_even_when_setting_enabled() -> None:
    state = build_auto_enrollment_state(
        settings={
            "smart_auto_enrollment_enabled": True,
            "auto_train_when_ready_enabled": True,
            "auto_promote_when_production_safe_enabled": True,
        },
        profile={"session_count": 8, "minimum_session_count": 8, "recommended_session_count": 15, "training_can_start": True},
        sessions=[],
        consent_satisfied=False,
    )

    assert state["enabled"] is True
    assert state["consentSatisfied"] is False
    assert state["collecting"] is False
    assert state["autoTrainingEnabled"] is True
    assert state["autoPromotionEnabled"] is True
    assert "privacy consent" in state["collectionStatusText"].lower()
    assert "before any behavioral collection" in state["nextBestActionText"].lower()


def test_state_reports_training_readiness_and_safe_coverage_from_backend_snapshot() -> None:
    sessions = [
        {
            "session_kind": "enrollment",
            "training_counts_toward_minimum": True,
            "metadata_trusted": True,
            "bucket": "accepted",
            "created_at": "2026-04-29T08:15:00+03:00",
            "keyboard_rows": 120,
            "mouse_rows": 45,
        },
        {
            "session_kind": "enrollment",
            "training_counts_toward_minimum": True,
            "metadata_trusted": True,
            "bucket": "accepted",
            "created_at": "2026-04-29T19:30:00+03:00",
            "keyboard_rows": 12,
            "mouse_rows": 90,
        },
        {
            "session_kind": "protected",
            "training_counts_toward_minimum": True,
            "metadata_trusted": True,
            "bucket": "accepted",
            "created_at": "2026-04-29T22:30:00+03:00",
            "keyboard_rows": 300,
            "mouse_rows": 300,
        },
    ]
    state = build_auto_enrollment_state(
        settings={"smart_auto_enrollment_enabled": True},
        profile={"session_count": 8, "minimum_session_count": 8, "recommended_session_count": 15, "training_can_start": True},
        sessions=sessions,
        consent_satisfied=True,
    )

    assert state["enabled"] is True
    assert state["collecting"] is False
    assert state["acceptedSessions"] == 8
    assert state["trainingReady"] is True
    assert state["timeOfDayCoverage"]["morning"] == 1
    assert state["timeOfDayCoverage"]["evening"] == 1
    assert state["timeOfDayCoverage"]["night"] == 0  # protected sessions are not enrollment baseline positives
    assert state["inputCoverage"] == {"keyboard": "strong", "mouse": "strong", "mixed": "strong"}
    assert "manual training path" in state["nextBestActionText"]


def test_settings_contracts_are_persisted_by_app_settings_and_settings_mixin() -> None:
    # The implementation lives in src/bioauth/security/app_settings.py.
    # Root app_settings.py is a compatibility wrapper — read the real impl.
    impl_path = ROOT / "src" / "bioauth" / "security" / "app_settings.py"
    app_settings = impl_path.read_text(encoding="utf-8") if impl_path.exists() else (ROOT / "app_settings.py").read_text(encoding="utf-8")
    settings_mixin = (ROOT / "bridge" / "settings_mixin.py").read_text(encoding="utf-8")

    for key in (
        "smart_auto_enrollment_enabled",
        "auto_train_when_ready_enabled",
        "auto_promote_when_production_safe_enabled",
    ):
        assert f'"{key}": False' in app_settings
        assert f'merged["{key}"] = bool' in app_settings
        assert f'"{key}": bool(getattr(self, "_{key}"' in settings_mixin
        assert f'{key}=requested' in settings_mixin

    assert "def setSmartAutoEnrollmentEnabled" in settings_mixin
    assert "def setAutoTrainWhenReadyEnabled" in settings_mixin
    assert "def setAutoPromoteWhenProductionSafeEnabled" in settings_mixin


def test_qml_binds_to_backend_owned_auto_enrollment_state_only() -> None:
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
        assert "requiredSessions:" not in text
        assert "trainingReady:" not in text


def test_settings_slots_do_not_start_training_or_promotion_in_phase3() -> None:
    settings_mixin = (ROOT / "bridge" / "settings_mixin.py").read_text(encoding="utf-8")
    auto_enrollment = (ROOT / "metadata_core" / "auto_enrollment.py").read_text(encoding="utf-8")
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")

    slot_start = settings_mixin.index("def setSmartAutoEnrollmentEnabled")
    slot_end = settings_mixin.index("def setRiskSensitivityPreset", slot_start)
    settings_slots = settings_mixin[slot_start:slot_end]
    forbidden_calls = ("startEnrollment", "start_protected_session", "trainProfile", "train_profile", "model_training", "promote_candidate", "publish_candidate", "write_active_runtime_pointer")
    for forbidden in forbidden_calls:
        assert forbidden not in settings_slots
        assert forbidden not in auto_enrollment

    assert "collecting=self._passive_auto_enrollment_collecting()" in desktop
    assert "build_auto_enrollment_state" in desktop
    assert "@Property(\"QVariantMap\", notify=autoEnrollmentChanged)" in desktop


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("6 focused auto enrollment phase2 tests passed")
