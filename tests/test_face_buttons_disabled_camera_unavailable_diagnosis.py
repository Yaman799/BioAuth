from __future__ import annotations

import ast
from pathlib import Path

from tests.test_hotfix_h8_real_face_enrollment_wiring import (
    DummyBridge,
    FakeCameraProvider,
    FakeCaptureResult,
    FakeFaceService,
)

ROOT = Path(__file__).resolve().parents[1]
FACE_PAGE = ROOT / "qml" / "pages" / "user" / "UserFaceConfirmationPage.qml"
FACE_DIALOG = ROOT / "qml" / "dialogs" / "FaceEnrollmentDialog.qml"
FACE_PREVIEW = ROOT / "qml" / "components" / "FaceCameraPreview.qml"
SETTINGS_MIXIN = ROOT / "bridge" / "settings_mixin.py"
I18N = ROOT / "bridge" / "i18n.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def slot_names() -> set[str]:
    tree = ast.parse(read(SETTINGS_MIXIN))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
            getattr(dec, "id", "") == "Slot" or (isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "Slot")
            for dec in node.decorator_list
        ):
            names.add(node.name)
    return names


def test_preview_paused_copy_has_component_fallbacks_and_i18n_entries() -> None:
    preview = read(FACE_PREVIEW)
    i18n = read(I18N)

    assert "function fallbackText(key)" in preview
    assert 'key === "face_preview_paused_for_backend"' in preview
    assert 'return "Preview paused for backend capture"' in preview
    assert 'key === "face_preview_paused_detail"' in preview
    assert 'return "BioAuth paused the display-only preview so the backend can use the camera safely. It resumes after the action finishes."' in preview

    for key in ["face_preview_paused_for_backend", "face_preview_paused_detail"]:
        assert i18n.count(f'"{key}"') >= 2, key


def test_enroll_entry_is_not_permanently_blocked_by_camera_unavailable_only() -> None:
    page = read(FACE_PAGE)
    dialog = read(FACE_DIALOG)

    assert "faceEnrollmentCameraUnavailableOnlyBlocker" in page
    assert 'faceState.faceEnrollmentUnavailableReason === "camera_unavailable"' in page
    assert "faceState.faceModelReady === true" in page
    assert "faceState.canGrantConsent === true" in page
    assert "enabled: root.canOpenEnrollmentDialog" in page
    assert 'faceDialog.openFor(reenroll ? "reenroll" : "enroll", root.faceEnrollmentCameraUnavailableOnlyBlocker)' in page
    assert "face_prepare_enrollment" in page
    assert "faceEnrollmentActionHint" in page

    assert "cameraUnavailableOnlyEnrollmentBlocker" in dialog
    assert 'backend.faceConfirmationState.faceEnrollmentUnavailableReason === "camera_unavailable"' in dialog
    assert "backend.faceConfirmationState.faceModelReady === true" in dialog
    assert "backend.faceConfirmationState.canGrantConsent === true" in dialog
    assert "dialog.cameraUnavailableOnlyEnrollmentBlocker" in dialog
    assert "face_retry_with_preview_paused" in dialog


def test_enrollment_flow_pauses_preview_invalidates_backend_camera_cache_then_captures() -> None:
    dialog = read(FACE_DIALOG)
    lowered = dialog.lower()

    assert "prepareFaceBackendCapture" in slot_names()
    assert "faceDialogCameraPreview.pauseForBackendCapture()" in dialog
    assert "backend.prepareFaceBackendCapture()" in dialog
    assert "backend.enrollFaceTemplate()" in dialog
    assert lowered.index("facedialogcamerapreview.pauseforbackendcapture()") < lowered.index("backend.preparefacebackendcapture()")
    assert lowered.index("backend.preparefacebackendcapture()") < lowered.index("backend.enrollfacetemplate()")


def test_backend_capture_open_failure_has_actionable_message_and_does_not_enroll() -> None:
    provider = FakeCameraProvider(FakeCaptureResult(status="device_open_failed", ok=False, frames=(), reason="permission_or_device_open_failure"))
    service = FakeFaceService()
    bridge = DummyBridge(camera_provider=provider, face_service=service, frame_count=3)

    result = bridge.enrollFaceTemplate()
    state = bridge._build_face_confirmation_state()

    assert result["ok"] is False
    assert result["status"] == "camera_unavailable"
    assert result["detailKey"] == "face_detail_backend_capture_open_failed"
    assert bridge._face_confirmation_operation_state["rawImagesStored"] is False
    assert state["faceTemplateEnrolled"] is False
    assert state["statusDetail"] == "face_detail_backend_capture_open_failed"
    assert service.enroll_calls == []


def test_backend_capture_open_failure_copy_exists_in_both_languages() -> None:
    i18n = read(I18N)

    assert i18n.count('"face_detail_backend_capture_open_failed"') >= 2
    assert "Camera preview works, but backend capture could not open the selected camera. Try another Backend camera index or close other camera apps." in i18n
    for key in [
        "face_enrollment_camera_retry_hint",
        "face_enrollment_disabled_reason_hint",
        "face_retry_with_preview_paused",
        "face_prepare_enrollment",
        "face_prepare_reenrollment",
    ]:
        assert i18n.count(f'"{key}"') >= 2, key
