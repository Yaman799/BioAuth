from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "qml"
USER_QML = [
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


def _bridge_slots() -> set[str]:
    source = "\n".join([
        _read(ROOT / "bridge" / "session_mixin.py"),
        _read(ROOT / "bridge" / "auth_mixin.py"),
        _read(ROOT / "bridge" / "settings_mixin.py"),
        _read(ROOT / "bridge" / "update_mixin.py"),
    ])
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if any((getattr(dec, "id", "") == "Slot") or (isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "Slot") for dec in node.decorator_list):
                names.add(node.name)
    return names


def test_home_quick_actions_use_single_backend_owned_action_wrapper() -> None:
    qml = _read(QML / "pages" / "user" / "UserHomePage.qml")
    slots = _bridge_slots()
    assert "requestUserHomeAction" in slots
    assert "requestUserAction" in slots
    for action in ["start_enrollment", "stop_enrollment", "start_protection", "stop_protection", "train_profile"]:
        assert f'backend.requestUserHomeAction("{action}")' in qml
    for forbidden in [
        "backend.startEnrollment(",
        "backend.stopEnrollmentLogger(",
        "backend.startProtected(",
        "backend.stopProductionMonitor(",
        "backend.stopCurrentSession(",
        "backend.trainProfile(",
        "backend.requestUserStartLearning(",
        "backend.requestUserStopLearning(",
        "backend.requestUserStartProtection(",
        "backend.requestUserStopProtection(",
    ]:
        assert forbidden not in qml
    assert "property bool homeActionInFlight" in qml
    assert "if (!root.canStartHomeEnrollment)" in qml
    assert "if (!root.canStopHomeEnrollment)" in qml
    assert "if (!root.canStartHomeProtection)" in qml
    assert "if (!root.canStopHomeProtection)" in qml
    assert "if (!root.canTrainHomeModel)" in qml
    assert "readonly property bool canTrainHomeModel" in qml
    assert 'objectName: "userHomeTrainProtectionModelButton"' in qml


def test_protection_buttons_call_user_safe_backend_requests_once_with_duplicate_guard() -> None:
    qml = _read(QML / "pages" / "user" / "UserProtectionPage.qml")
    slots = _bridge_slots()
    assert "requestUserStartProtection" in slots
    assert "requestUserStopProtection" in slots
    assert qml.count("backend.requestUserStartProtection()") == 1
    assert qml.count("backend.requestUserStopProtection()") == 1
    for forbidden in ["backend.startProtected()", "backend.stopCurrentSession(false)", "backend.stopProductionMonitor(false)"]:
        assert forbidden not in qml
    assert "property bool sessionActionInFlight" in qml
    assert "if (!root.canStartProtectedSession)" in qml
    assert "if (!root.canStopProtectedSession)" in qml
    assert "backend.canStartProtected" in qml
    assert "backend.canStop" in qml


def test_model_switch_approval_uses_backend_owned_safe_request_without_digest_exposure() -> None:
    qml = _read(QML / "pages" / "user" / "UserModelUpdatePage.qml")
    slots = _bridge_slots()
    assert "requestUserApproveModelUpdate" in slots
    assert qml.count("backend.requestUserApproveModelUpdate()") == 1
    assert "backend.approveProductionModelSwitch(" not in qml
    assert "readonly property string pendingCandidateDigest" not in qml
    assert "approval.candidateDigest" not in qml
    assert "property bool approvalActionInFlight" in qml
    assert "if (!root.canApproveModelSwitch)" in qml


def test_user_settings_wires_general_startup_settings_through_guarded_apply_only() -> None:
    qml = _read(QML / "pages" / "user" / "UserSettingsPage.qml")
    settings_qml = qml + "\n" + "\n".join(_read(path) for path in USER_SETTINGS_COMPONENTS)
    slots = _bridge_slots()
    assert "openPrivacyPolicy" in slots
    assert "setThemeMode" in slots
    assert "setLanguageCode" in slots
    assert "setButtonSoundsMuted" in slots
    assert "setRememberLoginEnabled" in slots
    assert "setStartupEnabled" in slots
    assert settings_qml.count("backend.openPrivacyPolicy()") == 1
    assert settings_qml.count("backend.setThemeMode(root.draftTheme)") == 1
    assert settings_qml.count("backend.setLanguageCode(root.draftLanguage)") == 1
    assert settings_qml.count("backend.setButtonSoundsMuted(root.draftButtonSoundsMuted)") == 1
    assert settings_qml.count("backend.setRememberLoginEnabled(root.draftRememberLoginEnabled)") == 1
    assert settings_qml.count("backend.setStartupEnabled(root.draftRunOnStartup)") == 1
    assert "function applyGeneralSettings()" in settings_qml
    assert "if (root.settingsActionInFlight || root.generalApplyInFlight || !root.hasGeneralDraftChanges)" in settings_qml
    assert "root.syncGeneralDraftsFromBackend()" in settings_qml
    assert "root.syncSecurityDraftsFromBackend()" in settings_qml
    assert "function onStartupChanged()" in settings_qml
    assert "function onRememberLoginChanged()" in settings_qml
    assert "function onButtonSoundsMutedChanged()" in settings_qml
    forbidden_mutations = ["backend.deleteMyData(", "backend.deleteAccount("]
    for token in forbidden_mutations:
        assert token not in qml


def test_user_settings_wires_security_and_face_settings_through_guarded_actions_only() -> None:
    qml = _read(QML / "pages" / "user" / "UserSettingsPage.qml")
    settings_qml = qml + "\n" + "\n".join(_read(path) for path in USER_SETTINGS_COMPONENTS)
    slots = _bridge_slots()
    for slot in {
        "updateAppPasscode",
        "setAppPasscodeTimeoutSec",
        "setAppPasscodeEnabled",
        "disableAppPasscode",
        "setFaceEnrollmentFeatureEnabled",
        "setFaceConfirmationFeatureEnabled",
    }:
        assert slot in slots
    assert settings_qml.count("backend.updateAppPasscode(currentText, newText, confirmText)") == 1
    assert settings_qml.count("backend.setAppPasscodeTimeoutSec(root.draftAppPasscodeTimeoutSec)") == 1
    assert settings_qml.count("backend.setAppPasscodeEnabled(true)") == 1
    assert settings_qml.count("backend.disableAppPasscode(currentText)") == 1
    assert settings_qml.count("backend.setFaceEnrollmentFeatureEnabled(enabled)") == 1
    assert settings_qml.count("backend.setFaceConfirmationFeatureEnabled(enabled)") == 1
    assert "function applySecuritySettings()" in settings_qml
    assert "function localPasscodeErrorText()" in settings_qml
    assert "if (root.settingsActionInFlight || root.securityApplyInFlight || !root.hasSecurityDraftChanges)" in settings_qml
    assert "function onAppPasscodeChanged()" in settings_qml
    assert "root.clearPasscodeDrafts()" in settings_qml
    assert "Qt.ImhSensitiveData" in settings_qml
    assert "backend.updateAppPasscode(" not in qml.split("function applySecuritySettings()")[0]


def test_user_settings_wires_privacy_license_and_updates_through_guarded_actions_only() -> None:
    qml = _read(QML / "pages" / "user" / "UserSettingsPage.qml")
    settings_qml = qml + "\n" + "\n".join(_read(path) for path in USER_SETTINGS_COMPONENTS)
    slots = _bridge_slots()
    for slot in {
        "setIncidentEvidenceEnabled",
        "setIncidentEvidenceCaptureScreenshot",
        "setIncidentEvidenceCaptureWebcam",
        "setIncidentEvidenceRetentionDays",
        "exportSupportBundle",
        "activateLicense",
        "importLicenseFile",
        "refreshLicenseStatus",
        "checkForUpdates",
        "downloadAvailableUpdate",
        "openDownloadedUpdateInstaller",
    }:
        assert slot in slots
    assert settings_qml.count("backend.setIncidentEvidenceEnabled(root.draftIncidentEvidenceEnabled)") == 1
    assert settings_qml.count("backend.setIncidentEvidenceCaptureScreenshot(root.draftIncidentEvidenceCaptureScreenshot)") == 1
    assert settings_qml.count("backend.setIncidentEvidenceCaptureWebcam(root.draftIncidentEvidenceCaptureWebcam)") == 1
    assert settings_qml.count("backend.setIncidentEvidenceRetentionDays(root.draftIncidentEvidenceRetentionDays)") == 1
    assert settings_qml.count("backend.exportSupportBundle()") == 1
    assert settings_qml.count("backend.activateLicense(code)") == 1
    assert settings_qml.count("backend.importLicenseFile(path)") == 1
    assert settings_qml.count("backend.refreshLicenseStatus()") == 1
    assert settings_qml.count("backend.checkForUpdates()") == 1
    assert settings_qml.count("backend.downloadAvailableUpdate()") == 1
    assert settings_qml.count("backend.openDownloadedUpdateInstaller()") == 1
    assert "function applyPrivacySettings()" in settings_qml
    assert "function guardedExportSupportBundle()" in settings_qml
    assert "function activateUserLicense()" in settings_qml
    assert "function guardedCheckForUpdates()" in settings_qml
    assert "function onIncidentEvidenceChanged()" in settings_qml
    assert "function onUpdateStateChanged()" in settings_qml
    assert "root.licenseCodeField.text = \"\"" in qml
    assert "backend.setIncidentEvidenceEnabled(" not in qml.split("function applyPrivacySettings()")[0]
    assert "backend.activateLicense(" not in qml.split("function activateUserLicense()")[0]
    assert "backend.checkForUpdates(" not in qml.split("function guardedCheckForUpdates()")[0]


def test_user_settings_wires_device_fit_performance_through_guarded_actions_only() -> None:
    qml = _read(QML / "pages" / "user" / "UserSettingsPage.qml")
    settings_qml = qml + "\n" + "\n".join(_read(path) for path in USER_SETTINGS_COMPONENTS)
    slots = _bridge_slots()
    for slot in {
        "setDeepRuntimeMode",
        "runDeepRuntimeBenchmark",
        "clearDeepRuntimeBenchmark",
    }:
        assert slot in slots
    assert settings_qml.count("backend.setDeepRuntimeMode(root.draftDeepRuntimeMode)") == 1
    assert settings_qml.count("backend.runDeepRuntimeBenchmark()") == 1
    assert settings_qml.count("backend.clearDeepRuntimeBenchmark()") == 1
    assert "function applyDeviceSettings()" in settings_qml
    assert "function runUserDeviceBenchmark()" in settings_qml
    assert "function clearUserDeviceBenchmark()" in settings_qml
    assert "function useRecommendedDeviceMode()" in settings_qml
    assert "function onDeepRuntimeChanged()" in settings_qml
    assert "property bool deviceApplyInFlight" in settings_qml
    assert "property bool deviceBenchmarkInFlight" in settings_qml
    assert "readonly property bool hasDeviceDraftChanges" in settings_qml
    assert "if (root.settingsActionInFlight || root.deviceApplyInFlight || root.deviceBenchmarkInFlight || !root.hasDeviceDraftChanges)" in settings_qml
    assert "backend.setDeepRuntimeMode(" not in qml.split("function applyDeviceSettings()")[0]
    assert "backend.runDeepRuntimeBenchmark(" not in qml.split("function runUserDeviceBenchmark()")[0]
    assert "backend.clearDeepRuntimeBenchmark(" not in qml.split("function clearUserDeviceBenchmark()")[0]
    forbidden_user_device_actions = [
        "emergencyDisableHybrid(",
        "rollbackToClassic(",
        "writeSafetyGateReport(",
        "setAutoPromoteWhenProductionSafeEnabled(",
    ]
    for token in forbidden_user_device_actions:
        assert token not in qml


def test_user_ui_hides_developer_diagnostics_and_reason_codes() -> None:
    combined = "\n".join(_read(path) for path in (USER_QML + USER_SETTINGS_COMPONENTS)).lower()
    forbidden = [
        "far", "frr", "reason_code", "reasoncode", "gate_results", "safety_gate_results",
        "drift lab", "driftlab", "candidate_artifact_digest", "evaluation_report_digest",
        "runtime_schema_version", "productioneligibility", "production_eligibility", "shadowstatus",
    ]
    for token in forbidden:
        assert token not in combined


def test_user_ui_does_not_make_hidden_navigation_backend_calls() -> None:
    shell = _read(QML / "UserShell.qml")
    assert "Loader" in shell
    assert "active: navSelection === 0" in shell
    assert "active: navSelection === 1" in shell
    assert "active: navSelection === 2" in shell
    assert "active: navSelection === 3" in shell
    for token in ["startProtected(", "stopCurrentSession(", "approveProductionModelSwitch(", "openPrivacyPolicy("]:
        assert token not in shell


def test_all_active_user_buttons_call_backend_or_are_guarded() -> None:
    combined = "\n".join(_read(path) for path in (USER_QML + USER_SETTINGS_COMPONENTS))
    assert "onClicked: root.guardedStartProtected()" in combined
    assert "onClicked: root.guardedStopProtected()" in combined
    assert "onClicked: root.approvePendingModelSwitch()" in combined
    assert ("onClicked: root.openPrivacySummary()" in combined) or ("onClicked: settingsRoot.openPrivacySummary()" in combined)
    assert ("onClicked: root.applyGeneralSettings()" in combined) or ("onClicked: settingsRoot.applyGeneralSettings()" in combined)
    assert ("onClicked: root.applySecuritySettings()" in combined) or ("onClicked: settingsRoot.applySecuritySettings()" in combined)
    assert ("onClicked: root.openFaceSettingsPage()" in combined) or ("onClicked: settingsRoot.openFaceSettingsPage()" in combined)
    assert ("onClicked: root.applyPrivacySettings()" in combined) or ("onClicked: settingsRoot.applyPrivacySettings()" in combined)
    assert ("onClicked: root.guardedExportSupportBundle()" in combined) or ("onClicked: settingsRoot.guardedExportSupportBundle()" in combined)
    assert ("onClicked: root.activateUserLicense()" in combined) or ("onClicked: settingsRoot.activateUserLicense()" in combined)
    assert ("onClicked: root.guardedCheckForUpdates()" in combined) or ("onClicked: settingsRoot.guardedCheckForUpdates()" in combined)
    assert ("onClicked: root.applyDeviceSettings()" in combined) or ("onClicked: settingsRoot.applyDeviceSettings()" in combined)
    assert ("onClicked: root.runUserDeviceBenchmark()" in combined) or ("onClicked: settingsRoot.runUserDeviceBenchmark()" in combined)
    assert ("onClicked: root.useRecommendedDeviceMode()" in combined) or ("onClicked: settingsRoot.useRecommendedDeviceMode()" in combined)
    assert ("onClicked: root.clearUserDeviceBenchmark()" in combined) or ("onClicked: settingsRoot.clearUserDeviceBenchmark()" in combined)
    assert "enabled: root.canStartProtectedSession" in combined
    assert "enabled: root.canStopProtectedSession" in combined
    assert "enabled: root.canApproveModelSwitch" in combined
    assert ("enabled: root.hasGeneralDraftChanges && !root.generalApplyInFlight && !root.settingsActionInFlight" in combined) or ("enabled: settingsRoot.hasGeneralDraftChanges && !settingsRoot.generalApplyInFlight && !settingsRoot.settingsActionInFlight" in combined)
    assert ("enabled: root.hasSecurityDraftChanges && !root.securityApplyInFlight && !root.settingsActionInFlight" in combined) or ("enabled: settingsRoot.hasSecurityDraftChanges && !settingsRoot.securityApplyInFlight && !settingsRoot.settingsActionInFlight" in combined)
    assert ("enabled: root.hasPrivacyDraftChanges && !root.privacyApplyInFlight && !root.settingsActionInFlight" in combined) or ("enabled: settingsRoot.hasPrivacyDraftChanges && !settingsRoot.privacyApplyInFlight && !settingsRoot.settingsActionInFlight" in combined)
    assert ("enabled: !root.settingsActionInFlight && !root.updateOperationActive() && root.updateState.canCheck !== false" in combined) or ("enabled: !settingsRoot.settingsActionInFlight && !settingsRoot.updateOperationActive() && settingsRoot.updateState.canCheck !== false" in combined)
    assert ("enabled: root.hasDeviceDraftChanges && !root.deviceApplyInFlight && !root.deviceBenchmarkInFlight && !root.settingsActionInFlight" in combined) or ("enabled: settingsRoot.hasDeviceDraftChanges && !settingsRoot.deviceApplyInFlight && !settingsRoot.deviceBenchmarkInFlight && !settingsRoot.settingsActionInFlight" in combined)
    assert ("enabled: !root.settingsActionInFlight && !root.deviceApplyInFlight && !root.deviceBenchmarkInFlight" in combined) or ("enabled: !settingsRoot.settingsActionInFlight && !settingsRoot.deviceApplyInFlight && !settingsRoot.deviceBenchmarkInFlight" in combined)
