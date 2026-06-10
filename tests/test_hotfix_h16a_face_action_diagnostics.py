from __future__ import annotations

import ast
from pathlib import Path

from tests.test_hotfix_h12a_face_build_profile_gate import DummyBridge, FakeAvailability, FakeCameraProvider

ROOT = Path(__file__).resolve().parents[1]
FACE_PAGE = ROOT / "qml" / "pages" / "user" / "UserFaceConfirmationPage.qml"
SETTINGS_MIXIN = ROOT / "bridge" / "settings_mixin.py"
I18N = ROOT / "bridge" / "i18n.py"
REQUIREMENTS_FACE = ROOT / "requirements-face.txt"
FACE_README = ROOT / "models" / "face" / "README.md"


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


def test_backend_exposes_separate_enrollment_and_confirmation_diagnostics() -> None:
    camera = FakeCameraProvider(FakeAvailability("camera_ready", True, "camera_ready"))
    bridge = DummyBridge(flags=True, consent=True, enrolled=False, preference=False, camera=camera, model_ready=True)

    state = bridge._build_face_confirmation_state()

    assert state["faceEnrollmentAvailable"] is True
    assert state["faceEnrollmentUnavailableReason"] == "not_checked"
    assert state["faceEnrollmentStatusText"]
    assert state["faceEnrollmentStatusDetail"]
    assert state["faceConfirmationAvailable"] is False
    assert state["faceConfirmationUnavailableReason"] == "template_missing"
    assert state["faceConfirmationStatusText"]
    assert state["faceConfirmationStatusDetail"]
    assert state["rawImagesStored"] is False
    assert state["lockIntegrationEnabled"] is False
    assert camera.capture_calls == 0


def test_refresh_face_state_clears_cached_camera_availability_without_capture() -> None:
    first = FakeCameraProvider(FakeAvailability("camera_unavailable", False, "camera_unavailable"))
    second = FakeCameraProvider(FakeAvailability("camera_ready", True, "camera_ready"))
    bridge = DummyBridge(flags=True, consent=True, enrolled=False, preference=False, camera=first, model_ready=True)
    bridge._theme = "dark"
    bridge._status_messages: list[tuple[str, str]] = []
    bridge._set_status = lambda message, tone="info": bridge._status_messages.append((message, tone))

    initial = bridge._build_face_confirmation_state()
    assert initial["faceEnrollmentUnavailableReason"] == "not_checked"
    assert first.availability_calls == 0

    checked = bridge.requestFaceCameraCheck()
    assert checked["status"] == "camera_unavailable"
    assert first.availability_calls == 1

    bridge._camera = second
    refreshed = bridge.refreshFaceConfirmationState()

    assert refreshed["faceEnrollmentUnavailableReason"] == "camera_unavailable"
    assert refreshed["faceEnrollmentAvailable"] is True
    assert second.availability_calls == 0
    assert second.capture_calls == 0
    assert bridge.faceConfirmationChanged.count >= 1


def test_qml_shows_action_specific_backend_reasons_and_refresh_without_local_decisions() -> None:
    page = read(FACE_PAGE)
    lower = page.lower()

    assert 'objectName: "faceRefreshStatusButton"' in page
    assert "backend.refreshFaceConfirmationState()" in page
    assert 'objectName: "faceEnrollmentReadinessText"' in page
    assert 'objectName: "faceEnrollmentReadinessDetail"' in page
    assert 'objectName: "faceConfirmationReadinessText"' in page
    assert 'objectName: "faceConfirmationReadinessDetail"' in page
    assert "faceEnrollmentStatusText" in page
    assert "faceConfirmationStatusText" in page
    assert "face_page_consent_recorded_title" in page
    assert "face_page_consent_recorded_body" in page

    forbidden = [
        "test_verification",
        "captureverificationframe",
        "capture_verification_frame",
        "capture_enrollment_frames",
        "score >=",
        "threshold",
        "template_digest",
        "face_template_path",
        "productioneligibility",
        "protectedsessionsavailable",
        "approved_for_production",
        "lock_suppressed",
    ]
    for token in forbidden:
        assert token not in lower, token


def test_bridge_has_refresh_slot_and_safe_i18n_copy() -> None:
    assert "refreshFaceConfirmationState" in slot_names()
    assert "requestFaceCameraCheck" in slot_names()
    i18n = read(I18N)
    for key in [
        "face_refresh_status",
        "face_page_consent_recorded_title",
        "face_page_consent_recorded_body",
        "face_enrollment_readiness_prefix",
        "face_confirmation_readiness_prefix",
    ]:
        assert i18n.count(f'"{key}"') >= 2, key
    face_lines = "\n".join(line for line in i18n.splitlines() if "face_" in line).lower()
    assert "face unlock" not in face_lines
    assert "100% secure" not in face_lines


def test_optional_face_requirements_document_opencv_contrib_without_model_binaries() -> None:
    requirements = read(REQUIREMENTS_FACE).lower()
    readme = read(FACE_README).lower()

    assert "opencv-contrib-python" in requirements
    assert "requirements.txt" in requirements
    assert "pip install -r requirements-face.txt" in readme
    assert not list((ROOT / "models" / "face").glob("*.onnx"))
