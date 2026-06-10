from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "qml"
USER_DIR = QML / "pages" / "user"

SETTINGS_COMPONENTS = [
    USER_DIR / "UserGeneralSettingsSection.qml",
    USER_DIR / "UserSecuritySettingsSection.qml",
    USER_DIR / "UserFaceSettingsSection.qml",
    USER_DIR / "UserPrivacySettingsSection.qml",
    USER_DIR / "UserDeviceSettingsSection.qml",
    USER_DIR / "UserPlanSettingsSection.qml",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_user_settings_page_is_refactored_into_section_components() -> None:
    page = _read(USER_DIR / "UserSettingsPage.qml")
    assert len(page.splitlines()) < 1800
    for component in SETTINGS_COMPONENTS:
        assert component.exists(), f"missing settings component: {component.name}"
        assert component.stem in page
        component_text = _read(component)
        assert "property var settingsRoot" in component_text
        assert "settingsRoot:" not in component_text  # components receive, not create, the controller


def test_settings_components_delegate_actions_to_settings_root() -> None:
    combined = "\n".join(_read(path) for path in SETTINGS_COMPONENTS)
    for guarded_action in [
        "settingsRoot.applyGeneralSettings()",
        "settingsRoot.applySecuritySettings()",
        "settingsRoot.openFaceSettingsPage()",
        "settingsRoot.applyPrivacySettings()",
        "settingsRoot.guardedExportSupportBundle()",
        "settingsRoot.guardedCheckForUpdates()",
        "settingsRoot.applyDeviceSettings()",
    ]:
        assert guarded_action in combined
    for direct_backend_action in [
        "backend.startEnrollment(",
        "backend.stopEnrollmentLogger(",
        "backend.startProtected(",
        "backend.stopProductionMonitor(",
        "backend.approveProductionModelSwitch(",
    ]:
        assert direct_backend_action not in combined


def test_user_brand_assets_exist_and_are_referenced() -> None:
    assert (QML / "assets" / "brand" / "bioauth_app_logo.png").exists()
    assert (QML / "assets" / "brand" / "bioauth_login_hero.png").exists()
    assert "assets/brand/bioauth_app_logo.png" in _read(QML / "UserShell.qml")
    assert "assets/brand/bioauth_login_hero.png" in _read(QML / "AuthPage.qml")


def test_refactored_user_qml_has_no_user_facing_internal_terms() -> None:
    files = [
        QML / "UserShell.qml",
        USER_DIR / "UserHomePage.qml",
        USER_DIR / "UserProtectionPage.qml",
        USER_DIR / "UserModelUpdatePage.qml",
        USER_DIR / "UserSettingsPage.qml",
        *SETTINGS_COMPONENTS,
    ]
    combined = "\n".join(_read(path) for path in files).lower()
    for token in [
        "reason_code",
        "gate_results",
        "safety_gate_results",
        "candidate_artifact_digest",
        "evaluation_report_digest",
        "runtime_schema_version",
        "production_eligibility",
        "shadowstatus",
    ]:
        assert token not in combined
