from __future__ import annotations

import ast
from pathlib import Path

import app_settings
from tests.test_hotfix_h12a_face_build_profile_gate import DummyBridge, FakeAvailability, FakeCameraProvider

ROOT = Path(__file__).resolve().parent.parent
FACE_PAGE = ROOT / "qml" / "pages" / "user" / "UserFaceConfirmationPage.qml"
USER_SETTINGS = ROOT / "qml" / "pages" / "user" / "UserSettingsPage.qml"
USER_FACE_SETTINGS_SECTION = ROOT / "qml" / "pages" / "user" / "UserFaceSettingsSection.qml"
SETTINGS_MIXIN = ROOT / "bridge" / "settings_mixin.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def bridge_slot_names() -> set[str]:
    tree = ast.parse(read(SETTINGS_MIXIN))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
            getattr(dec, "id", "") == "Slot" or (isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "Slot")
            for dec in node.decorator_list
        ):
            names.add(node.name)
    return names


def bridge_for_slots(**kwargs) -> DummyBridge:
    bridge = DummyBridge(**kwargs)
    bridge._theme = "dark"
    bridge._language = "en"
    bridge._run_on_startup = False
    bridge._risk_sensitivity = "conservative"
    bridge._mute_button_sounds = False
    bridge._remember_login_enabled = False
    bridge._incident_evidence_enabled = False
    bridge._incident_evidence_consent_granted = False
    bridge._incident_evidence_consent_policy_version = ""
    bridge._incident_evidence_consent_timestamp = ""
    bridge._incident_evidence_capture_screenshot = False
    bridge._incident_evidence_capture_webcam = False
    bridge._incident_evidence_retention_days = 30
    bridge._face_template_consent_granted = bool(bridge._app_settings.get("face_template_consent_granted", False))
    bridge._face_template_consent_policy_version = str(bridge._app_settings.get("face_template_consent_policy_version", "") or "")
    bridge._face_template_consent_timestamp = str(bridge._app_settings.get("face_template_consent_timestamp", "") or "")
    return bridge


def test_face_feature_flags_persist_across_save_load(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "settings.enc.json"
    monkeypatch.setattr(app_settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_settings, "SETTINGS_FILE", str(settings_path))
    monkeypatch.setattr(app_settings, "_SETTINGS_CACHE", None)

    saved = app_settings.save_settings(
        {
            "build_profile": "dev",
            "enable_face_enrollment": True,
            "enable_face_confirmation": True,
        }
    )
    assert saved["enable_face_enrollment"] is True
    assert saved["enable_face_confirmation"] is True
    assert settings_path.exists()

    monkeypatch.setattr(app_settings, "_SETTINGS_CACHE", None)
    loaded = app_settings.load_settings()
    assert loaded["enable_face_enrollment"] is True
    assert loaded["enable_face_confirmation"] is True
    assert app_settings.feature_flag_enabled(loaded, "enable_face_enrollment") is True
    assert app_settings.feature_flag_enabled(loaded, "enable_face_confirmation") is True


def test_backend_slots_enable_feature_flags_without_marking_face_ready() -> None:
    bridge = bridge_for_slots(flags=False, consent=False, enrolled=False, preference=False, model_ready=True)

    enrollment_result = bridge.setFaceEnrollmentFeatureEnabled(True)
    confirmation_result = bridge.setFaceConfirmationFeatureEnabled(True)
    state = bridge._build_face_confirmation_state()

    assert enrollment_result["ok"] is True
    assert confirmation_result["ok"] is True
    assert bridge._app_settings["enable_face_enrollment"] is True
    assert bridge._app_settings["enable_face_confirmation"] is True
    assert state["faceEnrollmentFeatureEnabled"] is True
    assert state["faceConfirmationFeatureEnabled"] is True
    assert state["faceEnrollmentAvailable"] is False
    assert state["faceConfirmationAvailable"] is False
    assert state["faceEnrollmentUnavailableReason"] == "consent_required"
    assert state["faceConfirmationUnavailableReason"] == "consent_required"
    assert state["rawImagesStored"] is False
    assert state["lockIntegrationEnabled"] is False


def test_feature_enabled_but_missing_models_reports_models_missing() -> None:
    bridge = bridge_for_slots(flags=False, consent=True, enrolled=True, preference=True, use_real_model_readiness=True)
    bridge.setFaceEnrollmentFeatureEnabled(True)
    bridge.setFaceConfirmationFeatureEnabled(True)

    state = bridge._build_face_confirmation_state()

    assert state["faceEnrollmentFeatureEnabled"] is True
    assert state["faceConfirmationFeatureEnabled"] is True
    assert state["faceEnrollmentAvailable"] is False
    assert state["faceConfirmationAvailable"] is False
    assert state["faceEnrollmentUnavailableReason"] == "models_missing"
    assert state["faceConfirmationUnavailableReason"] == "models_missing"
    assert "not enabled for this build" not in state["statusText"].lower()


def test_feature_enabled_but_camera_unavailable_reports_camera_unavailable() -> None:
    camera = FakeCameraProvider(FakeAvailability("camera_unavailable", False, "camera_unavailable"))
    bridge = bridge_for_slots(flags=False, consent=True, enrolled=True, preference=True, camera=camera, model_ready=True)
    bridge.setFaceEnrollmentFeatureEnabled(True)
    bridge.setFaceConfirmationFeatureEnabled(True)

    state = bridge._build_face_confirmation_state()

    assert state["faceEnrollmentUnavailableReason"] == "not_checked"
    assert state["faceConfirmationUnavailableReason"] == "not_checked"
    assert state["faceCameraAvailable"] is False
    assert camera.availability_calls == 0
    checked = bridge.requestFaceCameraCheck()
    assert checked["status"] == "camera_unavailable"
    assert camera.availability_calls == 1
    assert camera.capture_calls == 0


def test_confirmation_feature_disable_clears_prelock_preference_fail_closed() -> None:
    bridge = bridge_for_slots(flags=True, consent=True, enrolled=True, preference=True, model_ready=True)

    result = bridge.setFaceConfirmationFeatureEnabled(False)
    state = bridge._build_face_confirmation_state()

    assert result["ok"] is True
    assert bridge._app_settings["enable_face_confirmation"] is False
    assert bridge._app_settings["face_confirmation_enabled"] is False
    assert bridge._face_confirmation_enabled is False
    assert state["faceConfirmationFeatureEnabled"] is False
    assert state["faceConfirmationAvailable"] is False
    assert state["faceConfirmationUnavailableReason"] == "feature_disabled"


def test_qml_has_display_only_user_facing_feature_toggles() -> None:
    page = read(FACE_PAGE)
    settings = read(USER_SETTINGS) + "\n" + read(USER_FACE_SETTINGS_SECTION)
    combined = (page + "\n" + settings).lower()
    slots = bridge_slot_names()

    assert "setFaceEnrollmentFeatureEnabled" in slots
    assert "setFaceConfirmationFeatureEnabled" in slots
    assert 'objectName: "faceEnrollmentFeatureToggle"' in page
    assert 'objectName: "faceConfirmationFeatureToggle"' in page
    assert 'objectName: "userSettingsFaceEnrollmentFeatureToggle"' in settings
    assert 'objectName: "userSettingsFaceConfirmationFeatureToggle"' in settings
    assert "backend.setfaceenrollmentfeatureenabled(" in combined
    assert "backend.setfaceconfirmationfeatureenabled(" in combined
    assert "faceenrollmentfeatureenabled" in combined
    assert "faceconfirmationfeatureenabled" in combined

    forbidden = [
        "test_verification",
        "captureverificationframe",
        "capture_verification_frame",
        "confirm_before_lock",
        "lock_suppressed",
        "approved_for_production",
        "productioneligibility",
        "protectedsessionsavailable",
        "template_digest",
        "source_frame_paths",
        "raw face image",
        "face unlock",
    ]
    for token in forbidden:
        assert token not in combined, token


def test_i18n_contains_safe_toggle_copy() -> None:
    i18n = read(ROOT / "bridge" / "i18n.py")
    for key in [
        "face_feature_settings_title",
        "face_feature_settings_body",
        "face_enable_enrollment_setting",
        "face_enable_confirmation_setting",
        "face_enrollment_feature_enabled",
        "face_enrollment_feature_disabled",
        "face_confirmation_feature_enabled",
        "face_confirmation_feature_disabled",
    ]:
        assert i18n.count(f'"{key}"') >= 2, key
    face_lines = "\n".join(line for line in i18n.splitlines() if "face_" in line).lower()
    assert "standalone unlock" not in face_lines
    assert "100% secure" not in face_lines
