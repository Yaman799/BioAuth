from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "qml"
FACE_PAGE = QML / "pages" / "user" / "UserFaceConfirmationPage.qml"
FACE_DIALOG = QML / "dialogs" / "FaceEnrollmentDialog.qml"
USER_SETTINGS = QML / "pages" / "user" / "UserSettingsPage.qml"
USER_FACE_SETTINGS_SECTION = QML / "pages" / "user" / "UserFaceSettingsSection.qml"
SETTINGS_MIXIN = ROOT / "bridge" / "settings_mixin.py"
I18N = ROOT / "bridge" / "i18n.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_face_page_displays_backend_owned_status_detail_fields() -> None:
    page = read(FACE_PAGE)
    assert "readonly property string backendFaceStatusText: faceState.statusText" in page
    assert "readonly property string backendFaceStatusDetail: faceState.statusDetail" in page
    assert "readonly property string backendCameraStatusText: faceState.cameraStatusText" in page
    assert "readonly property string backendCameraStatusDetail: faceState.cameraStatusDetail" in page
    assert 'objectName: "faceBackendStatusPill"' in page
    assert 'objectName: "faceBackendCameraStatusPill"' in page
    assert 'objectName: "faceBackendStatusDetail"' in page
    assert 'objectName: "faceBackendCameraDetail"' in page
    assert "text: root.backendFaceStatusDetail" in page
    assert "text: root.backendCameraStatusDetail" in page


def test_enrollment_dialog_displays_backend_camera_and_face_status_only() -> None:
    dialog = read(FACE_DIALOG)
    assert "readonly property string backendFaceStatusText: backend.faceConfirmationState.statusText" in dialog
    assert "readonly property string backendFaceStatusDetail: backend.faceConfirmationState.statusDetail" in dialog
    assert "readonly property string backendCameraStatusText: backend.faceConfirmationState.cameraStatusText" in dialog
    assert "readonly property string backendCameraStatusDetail: backend.faceConfirmationState.cameraStatusDetail" in dialog
    assert 'objectName: "faceDialogCameraStatusTitle"' in dialog
    assert 'objectName: "faceDialogCameraStatusBody"' in dialog
    assert 'objectName: "faceDialogBackendFaceDetail"' in dialog
    assert 'objectName: "faceDialogBackendStatusPill"' in dialog
    assert "backend.enrollFaceTemplate()" in dialog
    assert "backend.faceConfirmationState.faceEnrollmentAvailable === true" in dialog


def test_backend_exposes_safe_status_copy_for_required_face_states() -> None:
    settings = read(SETTINGS_MIXIN)
    i18n = read(I18N)
    for token in [
        "face_detail_permission_device_failure",
        "face_detail_camera_unavailable",
        "face_detail_model_missing",
        "face_detail_no_face_detected",
        "face_detail_multiple_faces_detected",
        "face_detail_poor_quality",
        "face_detail_enrollment_complete",
        "face_detail_verification_failed",
        "face_detail_verification_succeeded",
        "face_camera_backend_owned_detail",
    ]:
        assert token in settings or token in i18n
    for key in [
        "face_status_verification_succeeded",
        "face_status_verification_failed",
        "face_detail_permission_device_failure",
        "face_detail_model_missing",
        "face_detail_no_face_detected",
        "face_detail_multiple_faces_detected",
        "face_detail_poor_quality",
        "face_detail_enrollment_complete",
        "face_detail_verification_failed",
        "face_detail_verification_succeeded",
        "face_camera_ready_backend_owned",
        "face_camera_backend_owned_detail",
    ]:
        assert i18n.count(f'"{key}"') >= 2, key
    assert '"statusDetail": status_detail' in settings
    assert '"cameraStatusText": self._status_text' in settings
    assert '"operationReason": str(reason or confirmation_reason or enrollment_reason)' in settings


def test_qml_does_not_compute_verification_safety_or_lock_decisions_locally() -> None:
    combined = "\n".join(read(path) for path in [FACE_PAGE, FACE_DIALOG, USER_SETTINGS, USER_FACE_SETTINGS_SECTION]).lower()
    forbidden_tokens = [
        "captureverificationframe",
        "capture_enrollment_frames",
        "test_verification",
        "confirm_before_lock",
        "lock_suppressed",
        "verified_owner_after_anomaly",
        "productioneligibility",
        "production_eligibility",
        "protectedsessionsavailable",
        "approved_for_production",
        "gate_results",
        "template_digest",
        "face_template_path",
        "source_frame_paths",
        "raw frame",
        "raw image path",
    ]
    for token in forbidden_tokens:
        assert token not in combined, token
    assert "backend.faceconfirmationstate" in combined
    assert "backend.testfaceconfirmation()" in combined


def test_ui_copy_does_not_overclaim_security_or_mention_face_unlock() -> None:
    combined = "\n".join(read(path) for path in [FACE_PAGE, FACE_DIALOG, USER_SETTINGS, USER_FACE_SETTINGS_SECTION]).lower()
    face_i18n = "\n".join(line for line in read(I18N).splitlines() if "face_" in line).lower()
    face_copy = combined + "\n" + face_i18n
    for phrase in [
        "100% secure",
        "guaranteed authentication",
        "face unlock",
        "standalone unlock",
    ]:
        assert phrase not in face_copy, phrase
    assert "pre-lock confirmation" in face_copy
    assert "raw face images are not saved" in face_copy
