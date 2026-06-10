from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
OVERVIEW = ROOT / "qml" / "pages" / "OverviewPage.qml"
PROFILE = ROOT / "qml" / "pages" / "ProfilePage.qml"
SETTINGS_SECURITY = ROOT / "qml" / "pages" / "settings" / "SettingsSecurityTab.qml"
SETTINGS_PAGE = ROOT / "qml" / "pages" / "SettingsPage.qml"
BRIDGE_SETTINGS = ROOT / "bridge" / "settings_mixin.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_overview_no_longer_owns_smart_auto_enrollment_controls() -> None:
    qml = _read(OVERVIEW)
    assert "Mission overview" not in qml
    assert "smartAutoEnrollmentMissionBox" not in qml
    assert "StartupSwitch" not in qml
    assert "backend.setSmartAutoEnrollmentEnabled" not in qml


def test_profile_training_owns_smart_auto_enrollment_controls() -> None:
    qml = _read(PROFILE)
    assert "profileSmartAutoEnrollmentControls" in qml
    assert "Smart Auto Enrollment" in qml
    assert "Auto-train when ready" in qml
    assert "Auto-promote when safe" in qml
    assert qml.count("StartupSwitch") >= 3
    assert "checked: autoEnrollment.enabled === true" in qml
    assert "checked: autoEnrollment.autoTrainingEnabled === true" in qml
    assert "checked: autoEnrollment.autoPromotionEnabled === true" in qml
    assert "backend.setSmartAutoEnrollmentEnabled(nextChecked)" in qml
    assert "backend.setAutoTrainWhenReadyEnabled(nextChecked)" in qml
    assert "backend.setAutoPromoteWhenProductionSafeEnabled(nextChecked)" in qml


def test_settings_has_read_only_pointer_not_duplicate_smart_auto_controls() -> None:
    qml = _read(SETTINGS_SECURITY)
    assert "Smart Auto Enrollment controls are now managed from Profile & Training" in qml
    assert "Open Profile & Training" in qml
    assert "Requires explicit privacy consent" in qml
    assert "existing safety gates" in qml
    assert "backend.setSmartAutoEnrollmentEnabled" not in qml
    assert "backend.setAutoTrainWhenReadyEnabled" not in qml
    assert "backend.setAutoPromoteWhenProductionSafeEnabled" not in qml


def test_backend_contracts_are_reused_not_reimplemented() -> None:
    profile = _read(PROFILE)
    bridge = _read(BRIDGE_SETTINGS)
    settings = _read(SETTINGS_PAGE)
    for method in [
        "setSmartAutoEnrollmentEnabled",
        "setAutoTrainWhenReadyEnabled",
        "setAutoPromoteWhenProductionSafeEnabled",
    ]:
        assert f"backend.{method}(nextChecked)" in profile
        assert f"def {method}" in bridge
    assert "function syncDraftsFromBackend" in settings
    assert "onAutoEnrollmentChanged" in settings


def test_no_fake_auto_enrollment_or_production_readiness_state_in_qml() -> None:
    combined = "\n".join(
        _read(path)
        for path in [
            OVERVIEW,
            PROFILE,
            SETTINGS_SECURITY,
            ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml",
            ROOT / "qml" / "pages" / "settings" / "SettingsStartupTab.qml",
        ]
    )
    forbidden_fragments = [
        "productionReady:",
        "protectedSessionsAvailable:",
        "modelStatus:",
        "autoEnrollmentState:",
        "collecting:",
        "trainingReady:",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in combined
    assert "backend.autoEnrollmentState" in combined
    assert "BioAuth learns your natural behavior" in combined
    assert "Never unlocks Protected Sessions for a shadow-only model." in combined
    assert "Protection, monitoring, and Smart Auto Enrollment may continue while the BioAuth interface is passcode-locked." in combined
    assert "approved_for_shadow" in combined
    assert "force approved_for_production" not in combined.lower()


def test_qml_long_text_wrapping_and_unique_ids() -> None:
    for path in [OVERVIEW, PROFILE, SETTINGS_SECURITY]:
        qml = _read(path)
        assert "wrapMode: Text.Wrap" in qml
        ids: list[str] = []
        for raw_line in qml.splitlines():
            line = raw_line.strip()
            if line.startswith("id: "):
                ids.append(line.split("id:", 1)[1].strip())
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        assert not duplicates, f"duplicate QML ids in {path}: {duplicates}"
