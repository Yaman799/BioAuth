from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "qml"
OVERVIEW = QML / "pages" / "OverviewPage.qml"
PROFILE = QML / "pages" / "ProfilePage.qml"
LIVE = QML / "pages" / "LiveSessionPage.qml"
DRIFT = QML / "pages" / "DriftLabPage.qml"
HISTORY = QML / "pages" / "HistoryPage.qml"
APP_SHELL = QML / "AppShell.qml"
SETTINGS_SECURITY = QML / "pages" / "settings" / "SettingsSecurityTab.qml"
SETTINGS_PERFORMANCE = QML / "pages" / "settings" / "SettingsPerformanceTab.qml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_overview_is_high_level_control_surface_only() -> None:
    overview = _read(OVERVIEW)
    assert "overviewControlDashboardCard" in overview
    assert "overviewPrimaryActionsCard" in overview
    assert "overviewRelocationMapCard" in overview
    for required in [
        "System Status",
        "Protection Mode",
        "Profile Readiness",
        "Face Confirmation",
        "Rollback",
        "Last Decision",
        "Start Monitor",
        "Stop Monitor",
        "Run Evaluation",
        "Open Direct Test",
        "Train/Calibrate",
        "Emergency Disable Hybrid",
        "Open Latest Report",
    ]:
        assert required in overview


def test_overview_no_long_detail_panels_or_shadow_candidate_controls() -> None:
    overview = _read(OVERVIEW)
    forbidden = [
        "LiveTelemetryPanel",
        "DriftLabPanel",
        "smartAutoEnrollmentMissionBox",
        "productionApprovalMissionBox",
        "promoteShadowModel",
        "approveProductionModelSwitch",
        "setSmartAutoEnrollmentEnabled",
        "setAutoTrainWhenReadyEnabled",
        "setAutoPromoteWhenProductionSafeEnabled",
        "FAR ",
        "FRR ",
        "Candidate status",
        "Shadow validation",
        "Protected Sessions",
        "StartupSwitch",
    ]
    for token in forbidden:
        assert token not in overview


def test_detailed_content_remains_in_dedicated_pages() -> None:
    profile = _read(PROFILE)
    live = _read(LIVE)
    drift = _read(DRIFT)
    history = _read(HISTORY)
    settings_performance = _read(SETTINGS_PERFORMANCE)
    assert "LiveTelemetryPanel" in live
    assert "DriftLabPanel" in drift
    assert "backend.trainingProgress" in profile
    assert "profileSmartAutoEnrollmentControls" in profile
    assert "backend.setSmartAutoEnrollmentEnabled(nextChecked)" in profile
    assert "Protected Sessions" in history or "protectedSessionsAvailable" in history
    assert "Model status" in settings_performance
    assert "Evaluation report" in settings_performance


def test_overview_buttons_call_only_existing_safe_methods_or_navigate() -> None:
    overview = _read(OVERVIEW)
    assert "onClicked: backend.startProtected()" in overview
    assert "onClicked: backend.stopProductionMonitor(false)" in overview
    assert "onClicked: backend.trainProfile()" in overview
    assert "onClicked: root.openSection(2)" in overview
    assert "overviewRunEvaluationButton" in overview and "enabled: false" in overview
    assert "overviewEmergencyDisableHybridButton" in overview and "enabled: false" in overview
    assert "overviewOpenLatestReportButton" in overview and "enabled: false" in overview
    assert "runEvaluation(" not in overview
    assert "emergencyDisableHybrid(" not in overview
    assert "openLatestReport(" not in overview


def test_navigation_to_all_dedicated_sections_remains_available() -> None:
    app_shell = _read(APP_SHELL)
    overview = _read(OVERVIEW)
    for title in [
        "Live Session",
        "Hybrid Direct Test",
        "Profile & Training",
        "Model Evaluation",
        "Sessions & Data",
        "Drift Lab",
    ]:
        assert title in app_shell
        assert title in overview
    for index in range(1, 7):
        assert f"root.openSection({index})" in overview


def test_settings_pointer_now_sends_auto_enrollment_to_profile_training() -> None:
    settings = _read(SETTINGS_SECURITY)
    assert "Profile & Training" in settings
    assert "Smart Auto Enrollment controls are now managed from Profile & Training" in settings
    assert "Mission overview card on the Overview page" not in settings


def test_no_new_local_readiness_or_approval_state_is_introduced() -> None:
    qml_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in QML.rglob("*.qml"))
    forbidden_fragments = [
        "productionReady:",
        "protectedAvailable:",
        "shadowPassed:",
        "approvalPassed:",
        "modelReady:",
        "protectedSessionsAvailable:",
        "autoEnrollmentState:",
        "trainingReady:",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in qml_text
