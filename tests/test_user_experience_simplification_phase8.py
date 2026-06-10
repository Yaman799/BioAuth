from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QML_FILES = [
    ROOT / "qml" / "pages" / "ProfilePage.qml",
    ROOT / "qml" / "pages" / "HistoryPage.qml",
    ROOT / "qml" / "pages" / "settings" / "SettingsSecurityTab.qml",
    ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml",
    ROOT / "qml" / "components" / "LiveTelemetryPanel.qml",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_profile_shows_simple_automated_journey_from_backend_state() -> None:
    qml = _read(ROOT / "qml" / "pages" / "ProfilePage.qml")
    assert "backend.autoEnrollmentState" in qml
    assert "backend.productionApprovalState" in qml
    assert "backend.modelReadinessState" in qml
    assert "setupJourneyStage" in qml
    for state in [
        "Learning your behavior",
        "Collecting natural sessions",
        "Ready to train",
        "Training your protection model",
        "Safe background validation",
        "Collecting targeted improvements",
        "Protected Sessions are ready",
        "Protected Sessions are safely locked",
    ]:
        assert state in qml
    assert "Protected Sessions stay locked until production approval passes" in qml
    assert "Automatic learning needs explicit privacy consent" in qml


def test_qml_does_not_fake_backend_readiness_or_policy_state() -> None:
    combined = "\n".join(_read(path) for path in QML_FILES)
    forbidden_assignment_fragments = [
        "productionReady:",
        "protectedSessionsAvailable:",
        "modelStatus:",
        "failedProductionGates:",
        "activeRoutedContexts:",
    ]
    for fragment in forbidden_assignment_fragments:
        assert fragment not in combined
    assert "backend.productionApprovalState" in combined
    assert "backend.modelReadinessState" in combined
    assert "backend.autoEnrollmentState" in combined
    assert "force approved_for_production" not in combined.lower()
    assert "approved_for_shadow" in combined


def test_advanced_diagnostics_keep_real_technical_details_visible() -> None:
    qml = _read(ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml")
    for detail in [
        "Model status",
        "Failed gates",
        "Active contexts",
        "Evaluation report",
        "Evaluation summary",
        "Deep runtime mode",
        "Fallback reason",
        "Runtime validation",
    ]:
        assert detail in qml
    assert "Advanced diagnostics" in qml
    assert "No exact metric values are present" in qml
    assert "setupSummaryText" in qml


def test_live_telemetry_keeps_fallback_and_background_validation_visible() -> None:
    qml = _read(ROOT / "qml" / "components" / "LiveTelemetryPanel.qml")
    assert "Protection setup" in qml
    assert "setupStatusText" in qml
    assert "BioAuth is validating your protection model safely in the background." in qml
    assert "Training your protection model in the background." in qml
    assert "Fallback reason" in qml
    assert "backend.deepRuntimeIsFallback" in qml
    assert "Production approval" in qml
    assert "Protected lock reason" in qml


def test_history_and_settings_preserve_privacy_and_destructive_confirmation_paths() -> None:
    history = _read(ROOT / "qml" / "pages" / "HistoryPage.qml")
    security = _read(ROOT / "qml" / "pages" / "settings" / "SettingsSecurityTab.qml")
    privacy = _read(ROOT / "qml" / "pages" / "settings" / "SettingsPrivacyCenterCard.qml")
    account = _read(ROOT / "qml" / "pages" / "settings" / "SettingsAccountTab.qml")
    assert "Automated learning record" in history
    assert "only accepted sessions help readiness" in history
    assert "rootWindow.requestDeleteSession(modelData.path)" in history
    assert "rootWindow.requestDeleteSessions(root.selectedPaths())" in history
    assert "backend.deleteSession(" not in history
    assert "backend.deleteSessions(" not in history
    assert "Requires explicit privacy consent" in security
    assert "existing safety gates" in security
    assert "Privacy" in privacy or "privacy" in privacy
    assert "SettingsLicenseCard" in account


def test_added_user_copy_wraps_for_rtl_and_long_text() -> None:
    # Static guard: each modified surface with new narrative copy should keep
    # long text in wrapping Labels so Arabic/RTL and English long diagnostics do
    # not force clipped layouts.
    for path in QML_FILES:
        qml = _read(path)
        assert "wrapMode: Text.Wrap" in qml, path
    profile = _read(ROOT / "qml" / "pages" / "ProfilePage.qml")
    assert profile.count("wrapMode: Text.Wrap") >= 20
    performance = _read(ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml")
    assert performance.count("wrapMode: Text.Wrap") >= 10


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("6 focused user experience simplification phase8 tests passed", flush=True)
    os._exit(0)
