from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "qml"
USER_FILES = [
    QML / "UserShell.qml",
    QML / "pages" / "user" / "UserHomePage.qml",
    QML / "pages" / "user" / "UserProtectionPage.qml",
    QML / "pages" / "user" / "UserModelUpdatePage.qml",
    QML / "pages" / "user" / "UserSettingsPage.qml",
]

USER_SETTINGS_COMPONENTS = [
    QML / "pages" / "user" / "UserGeneralSettingsSection.qml",
    QML / "pages" / "user" / "UserSecuritySettingsSection.qml",
    QML / "pages" / "user" / "UserFaceSettingsSection.qml",
    QML / "pages" / "user" / "UserPrivacySettingsSection.qml",
    QML / "pages" / "user" / "UserDeviceSettingsSection.qml",
    QML / "pages" / "user" / "UserPlanSettingsSection.qml",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_user_shell_and_pages_exist_without_replacing_developer_shell() -> None:
    for path in USER_FILES:
        assert path.exists(), f"missing user UI file: {path}"
    main = _read(QML / "Main.qml")
    assert (QML / "AppShell.qml").exists()
    assert "sourceComponent: window.selectedShellComponent()" in main or "sourceComponent: backend.authenticated ? appShell : authPage" in main
    assert "AppShell { windowRef: window }" in main
    # Phase 10 may reference UserShell through a backend-owned Loader while AppShell remains available.
    assert "AppShell { windowRef: window }" in main


def test_user_shell_loads_pages_lazily() -> None:
    shell = _read(QML / "UserShell.qml")
    for token in ["active: navSelection === 0", "active: navSelection === 1", "active: navSelection === 2", "active: navSelection === 3"]:
        assert token in shell
    for token in ["userHomePageComponent", "userProtectionPageComponent", "userModelUpdatePageComponent", "userSettingsPageComponent"]:
        assert token in shell


def test_user_ui_hides_developer_diagnostics_and_gate_internals() -> None:
    combined = "\n".join(_read(path) for path in (USER_FILES + USER_SETTINGS_COMPONENTS)).lower()
    forbidden = ["far", "frr", "reason_code", "reasoncode", "gate_results", "safety_gate_results", "shadow", "drift lab", "driftlab", "candidate_artifact_digest", "evaluation_report_digest", "runtime_schema_version", "productioneligibility", "production_eligibility"]
    for token in forbidden:
        assert token not in combined


def test_user_ui_does_not_compute_readiness_or_expose_unsafe_backend_slots() -> None:
    combined = "\n".join(_read(path) for path in (USER_FILES + USER_SETTINGS_COMPONENTS))
    for call in ["backend.startEnrollment(", "backend.trainProfile(", "backend.promoteShadowModel("]:
        assert call not in combined
    for token in ["protectedSessionsAvailable", "productionEligibilityPassed", "approvalReasonCode()", "productionStatusCode()", "candidateStatusCode()", "candidate_artifact_digest"]:
        assert token not in combined
    assert "backend.canStartProtected" in _read(QML / "pages" / "user" / "UserProtectionPage.qml")
    assert "backend.canStop" in _read(QML / "pages" / "user" / "UserProtectionPage.qml")


def test_user_i18n_keys_exist_in_english_and_arabic() -> None:
    i18n = _read(ROOT / "bridge" / "i18n.py")
    for key in ["user_shell_title", "user_shell_home", "user_home_title", "user_protection_title", "user_model_update_title", "user_settings_title", "user_protection_start_unavailable_tooltip", "user_model_update_unavailable_tooltip"]:
        assert i18n.count(f'"{key}"') >= 2
