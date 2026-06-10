from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
OVERVIEW = ROOT / "qml" / "pages" / "OverviewPage.qml"
PROFILE = ROOT / "qml" / "pages" / "ProfilePage.qml"
LIVE_PANEL = ROOT / "qml" / "components" / "LiveTelemetryPanel.qml"
SETTINGS_PERFORMANCE = ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml"
USER_MODEL_UPDATE = ROOT / "qml" / "pages" / "user" / "UserModelUpdatePage.qml"
DESKTOP = ROOT / "desktop_app.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_overview_does_not_mix_full_production_approval_details() -> None:
    qml = _read(OVERVIEW)
    assert "productionApprovalMissionBox" not in qml
    assert "Candidate status" not in qml
    assert "Shadow validation" not in qml
    assert "Protected Sessions" not in qml
    assert "FAR " not in qml
    assert "FRR " not in qml
    assert "approveProductionModelSwitch" not in qml


def test_profile_settings_and_live_explain_candidate_shadow_production_and_protection_status() -> None:
    combined = "\n".join([_read(PROFILE), _read(SETTINGS_PERFORMANCE), _read(LIVE_PANEL), _read(USER_MODEL_UPDATE)])
    for expected in [
        "Protected Sessions status",
        "Model status",
        "Background validation",
        "Evaluation report",
        "requestUserApproveModelUpdate",
        "approved_for_shadow",
        "Never unlocks Protected Sessions for a shadow-only model.",
    ]:
        assert expected in combined
    assert "backend.approveProductionModelSwitch(" not in _read(USER_MODEL_UPDATE)


def test_reason_codes_progress_and_metrics_are_displayable_outside_overview() -> None:
    combined = "\n".join([_read(PROFILE), _read(SETTINGS_PERFORMANCE), _read(LIVE_PANEL)])
    for expected in [
        "approvalReasonText",
        "modelStatus",
        "protectedSessionsAvailable",
        "Evaluation report",
        "Runtime validation",
        "Failed gates",
    ]:
        assert expected in combined


def test_qml_does_not_invent_production_readiness_or_protection_state() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "qml").rglob("*.qml"))
    forbidden_fragments = [
        "productionApprovalState:",
        "productionReady:",
        "protectedAvailable:",
        "shadowPassed:",
        "approvalPassed:",
        "modelReady:",
        "protectedSessionsAvailable:",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in combined
    assert "backend.productionApprovalState" in combined
    assert "backend.canStartProtected" in combined


def test_backend_property_contract_still_exists() -> None:
    desktop = _read(DESKTOP)
    assert "def productionApprovalState" in desktop
    assert "apply_production_approval_runtime_context" in desktop
    assert "autoPromotionState" in desktop
