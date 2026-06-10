from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "qml" / "components" / "FaceCameraPreview.qml"
DIALOG = ROOT / "qml" / "dialogs" / "FaceEnrollmentDialog.qml"
FACE_PAGE = ROOT / "qml" / "pages" / "user" / "UserFaceConfirmationPage.qml"
I18N = ROOT / "bridge" / "i18n.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_live_preview_component_is_qt_multimedia_display_only() -> None:
    qml = read(PREVIEW)
    lowered = qml.lower()

    assert "import QtMultimedia" in qml
    assert "Camera {" in qml
    assert "CaptureSession {" in qml
    assert "VideoOutput {" in qml
    assert 'objectName: "facePreviewVideoOutput"' in qml
    assert "face_preview_display_only_notice" in qml
    assert "previewPausedForBackendCapture" in qml

    forbidden = [
        "testfaceconfirmation",
        "enrollfacetemplate",
        "detectfaces",
        "extractembedding",
        "faceDetectorYN",
        "faceRecognizerSF",
        "verify_embedding",
        "cosinesimilarity",
        "threshold",
        "score >=",
        "capturetofile",
        "grabtoimage",
        "screenshot",
        "save(",
        "write(",
        "template_digest",
        "protectedSessionsAvailable".lower(),
        "approved_for_production",
        "lock_suppressed",
    ]
    for token in forbidden:
        assert token not in lowered, token


def test_enrollment_dialog_embeds_preview_and_pauses_before_backend_capture() -> None:
    qml = read(DIALOG)
    lowered = qml.lower()

    assert 'objectName: "faceDialogCameraPreview"' in qml
    assert "FaceCameraPreview" in qml
    assert "faceDialogCameraPreview.pauseForBackendCapture()" in qml
    assert "backend.enrollFaceTemplate()" in qml
    assert lowered.index("facedialogcamerapreview.pauseforbackendcapture()") < lowered.index("backend.enrollfacetemplate()")
    assert "faceDialogCameraPreview.resumeAfterBackendCapture()" in qml
    assert "previewEnabled: dialog.visible" in qml


def test_face_page_embeds_optional_preview_and_pauses_for_test_refresh_and_enrollment() -> None:
    qml = read(FACE_PAGE)
    lowered = qml.lower()

    assert 'objectName: "facePageCameraPreview"' in qml
    assert 'objectName: "faceTogglePreviewButton"' in qml
    assert "FaceCameraPreview" in qml
    assert "facePreviewRequested" in qml
    assert "toggleDisplayOnlyPreview" in qml
    assert "pageFacePreview.pauseForBackendCapture()" in qml
    assert "pageFacePreview.resumeAfterBackendCapture()" in qml
    assert lowered.index("pagefacepreview.pauseforbackendcapture()", lowered.index("function guardedtestface")) < lowered.index("backend.testfaceconfirmation()")
    assert lowered.index("pagefacepreview.pauseforbackendcapture()", lowered.index("function guardedrefreshfacestate")) < lowered.index("backend.refreshfaceconfirmationstate()")
    assert lowered.index("pagefacepreview.pauseforbackendcapture()", lowered.index("function openenrollmentdialog")) < lowered.index("facedialog.openfor")


def test_face_preview_i18n_copy_is_safe_and_does_not_overclaim_security() -> None:
    i18n = read(I18N)
    for key in [
        "face_preview_title",
        "face_preview_body",
        "face_preview_show",
        "face_preview_hide",
        "face_preview_live_title",
        "face_preview_display_only_detail",
        "face_preview_display_only_notice",
        "face_preview_camera_unavailable",
        "face_preview_unavailable",
        "face_preview_paused_for_backend",
        "face_preview_paused_detail",
        "face_preview_consent_required_detail",
    ]:
        assert i18n.count(f'"{key}"') >= 2, key

    face_lines = "\n".join(line for line in i18n.splitlines() if "face_" in line).lower()
    assert "face unlock" not in face_lines
    assert "100% secure" not in face_lines
    assert "display-only" in face_lines or "للعرض فقط" in face_lines


def test_preview_qml_does_not_compute_backend_owned_face_or_safety_decisions() -> None:
    combined = "\n".join(read(path) for path in [PREVIEW, DIALOG, FACE_PAGE]).lower()
    forbidden = [
        "detectfaces",
        "extractembedding",
        "verify_embedding",
        "cosinesimilarity",
        "score >=",
        "threshold",
        "verified =",
        "not_verified =",
        "liveness",
        "antispoof",
        "approved_for_production",
        "productionready",
        "protectedsessionsavailable",
        "lock_suppressed",
        "capturetofile",
        "grabtoimage",
        "save(",
        "write(",
    ]
    for token in forbidden:
        assert token not in combined, token
