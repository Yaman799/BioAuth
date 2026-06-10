from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from face_biometrics import FaceBox
from face_template_store import FaceTemplateStore
from identity_confirmation import IdentityConfirmationService
from secure_storage import decrypt_envelope
from tests.test_hotfix_h8_real_face_enrollment_wiring import DummySignal, SettingsMixin
from tests.test_phase_11_face_biometrics_backend import _configure_crypto


ROOT = Path(__file__).resolve().parent.parent
FACE_DIALOG = ROOT / "qml" / "dialogs" / "FaceEnrollmentDialog.qml"
FACE_PAGE = ROOT / "qml" / "pages" / "user" / "UserFaceConfirmationPage.qml"
SETTINGS_MIXIN = ROOT / "bridge" / "settings_mixin.py"
I18N = ROOT / "bridge" / "i18n.py"


@dataclass(frozen=True)
class FakeCaptureResult:
    status: str
    ok: bool
    frames: tuple[object, ...] = ()
    reason: str = ""
    raw_images_stored: bool = False

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "ok": self.ok,
            "reason": self.reason or self.status,
            "frame_count": len(self.frames),
            "raw_images_stored": False,
        }


class FakeCameraProvider:
    def __init__(self, result: FakeCaptureResult) -> None:
        self.result = result
        self.requested_counts: list[int] = []

    def capture_enrollment_frames(self, count: int) -> FakeCaptureResult:
        self.requested_counts.append(int(count))
        return self.result


class FakeFaceEngine:
    model_id = "fake-sface-h14-v1"

    def __init__(self, *, detections=None, embedding=None) -> None:
        self.detections = detections if detections is not None else [FaceBox(8, 8, 72, 72, 0.99)]
        self.embedding = np.asarray(embedding if embedding is not None else [1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        self.detect_calls = 0
        self.extract_calls = 0

    def detect_faces(self, frame):
        self.detect_calls += 1
        return self.detections

    def extract_embedding(self, frame, face):
        self.extract_calls += 1
        return self.embedding


class BridgeForEnrollment(SettingsMixin):
    def __init__(self, *, camera_provider, service, consent: bool = True, feature_enabled: bool = True, frame_count: int = 3) -> None:
        self._current_user = {"user_id": "owner@example.com"}
        self._app_settings = {
            "enable_face_enrollment": bool(feature_enabled),
            "enable_face_confirmation": bool(feature_enabled),
            "face_template_consent_granted": bool(consent),
            "face_enrollment_frame_count": int(frame_count),
        }
        self._face_confirmation_enabled = False
        self._face_confirmation_operation_state = {"status": "idle", "ok": True}
        self._language = "en"
        self._t = lambda key, **_kwargs: key
        self.faceConfirmationChanged = DummySignal()
        self.statuses: list[tuple[str, str]] = []
        self._camera_provider = camera_provider
        self._service = service

    def _set_status(self, message: str, tone: str = "info") -> None:
        self.statuses.append((message, tone))

    def _face_camera_provider(self):
        return self._camera_provider

    def _face_enrollment_service(self):
        return self._service

    def _face_service(self):
        return self._service

    def _face_model_readiness_state(self) -> dict[str, object]:
        return {"ok": True, "status": "models_ready", "reason": "models_ready"}


def good_frames(count: int = 3) -> tuple[np.ndarray, ...]:
    return tuple(np.full((96, 96, 3), 180 + idx, dtype=np.uint8) for idx in range(count))


def encrypted_payload_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ui_start_enrollment_captures_frames_and_saves_encrypted_template(tmp_path, monkeypatch) -> None:
    _configure_crypto(tmp_path, monkeypatch)
    store = FaceTemplateStore(tmp_path / "face_templates")
    engine = FakeFaceEngine()
    service = IdentityConfirmationService(store=store, engine=engine)
    frames = good_frames(3)
    camera = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=frames, reason="captured"))
    bridge = BridgeForEnrollment(camera_provider=camera, service=service, consent=True, frame_count=3)

    result = bridge.enrollFaceTemplate()

    assert result["ok"] is True
    assert result["status"] == "enrolled"
    assert result["enrollmentStatus"] == "enrollment_success"
    assert result["operationDisplayStatus"] == "enrollment_success"
    assert result["sample_count"] == 3
    assert camera.requested_counts == [3]
    assert engine.detect_calls == 3
    assert engine.extract_calls == 3

    template_path = store.template_path("owner@example.com")
    assert template_path.exists()
    raw_text = encrypted_payload_text(template_path)
    raw_doc = json.loads(raw_text)
    assert raw_doc["encrypted"] is True
    assert "embedding" not in raw_text
    assert "raw_image" not in raw_text
    assert "source_frame" not in raw_text
    decrypted = decrypt_envelope(raw_doc)
    assert decrypted["raw_images_stored"] is False
    assert decrypted["source_frame_paths"] == []
    assert decrypted["embedding_model_id"] == engine.model_id

    state = bridge._build_face_confirmation_state()
    assert state["operationStatus"] == "enrollment_success"
    assert state["statusTone"] == "success"
    assert state["rawImagesStored"] is False
    assert state["lockIntegrationEnabled"] is False
    for forbidden in ("frames", "frame", "image", "images", "embedding", "template_digest", "source_frame_paths"):
        assert forbidden not in bridge._face_confirmation_operation_state


def test_enrollment_requires_consent_before_camera_or_template(tmp_path, monkeypatch) -> None:
    _configure_crypto(tmp_path, monkeypatch)
    store = FaceTemplateStore(tmp_path / "face_templates")
    service = IdentityConfirmationService(store=store, engine=FakeFaceEngine())
    camera = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=good_frames(3)))
    bridge = BridgeForEnrollment(camera_provider=camera, service=service, consent=False)

    result = bridge.enrollFaceTemplate()

    assert result["ok"] is False
    assert result["status"] == "consent_required"
    assert camera.requested_counts == []
    assert not store.has_template("owner@example.com")


def test_camera_failure_and_zero_frames_fail_closed_without_template(tmp_path, monkeypatch) -> None:
    _configure_crypto(tmp_path, monkeypatch)
    store = FaceTemplateStore(tmp_path / "face_templates")
    service = IdentityConfirmationService(store=store, engine=FakeFaceEngine())
    camera = FakeCameraProvider(FakeCaptureResult(status="no_frame_captured", ok=False, frames=(), reason="no_frame_captured"))
    bridge = BridgeForEnrollment(camera_provider=camera, service=service, consent=True)

    result = bridge.enrollFaceTemplate()

    assert result["ok"] is False
    assert result["status"] == "camera_unavailable"
    assert result["captureStatus"] == "no_frame_captured"
    assert result["frameCount"] == 0
    assert result.get("rawImagesStored") is False
    assert camera.requested_counts == [3]
    assert not store.has_template("owner@example.com")


def test_no_face_multiple_faces_and_poor_quality_fail_closed(tmp_path, monkeypatch) -> None:
    _configure_crypto(tmp_path, monkeypatch)
    cases = [
        (FakeFaceEngine(detections=[]), "no_face_detected"),
        (FakeFaceEngine(detections=[FaceBox(0, 0, 72, 72), FaceBox(1, 1, 72, 72)]), "multiple_faces_detected"),
        (FakeFaceEngine(detections=[FaceBox(0, 0, 4, 4, 0.99)]), "poor_quality"),
    ]
    for engine, expected_status in cases:
        store = FaceTemplateStore(tmp_path / f"face_templates_{expected_status}")
        service = IdentityConfirmationService(store=store, engine=engine)
        camera = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=good_frames(3), reason="captured"))
        bridge = BridgeForEnrollment(camera_provider=camera, service=service, consent=True)

        result = bridge.enrollFaceTemplate()

        assert result["ok"] is False
        assert result["status"] == expected_status
        assert result["enrollmentStatus"] == "enrollment_failed"
        assert result.get("rawImagesStored") is False
        assert not store.has_template("owner@example.com")


def test_qml_enrollment_controls_are_backend_display_only() -> None:
    dialog = FACE_DIALOG.read_text(encoding="utf-8")
    page = FACE_PAGE.read_text(encoding="utf-8")
    combined = (dialog + "\n" + page).lower()

    assert 'objectName: "faceStartEnrollmentButton"' in dialog
    assert 'objectName: "faceReenrollButton"' in page
    assert 'objectName: "faceDeleteTemplateButton"' in page
    assert "backend.enrollFaceTemplate()" in dialog
    assert "backend.deleteFaceTemplate()" in page
    assert "backend.faceConfirmationState.faceEnrollmentAvailable === true" in dialog

    forbidden = [
        "detectfaces",
        "extractembedding",
        "template_digest",
        "source_frame_paths",
        "raw face image",
        "face unlock",
        "lock_suppressed",
        "approved_for_production",
        "protectedsessionsavailable",
    ]
    for token in forbidden:
        assert token not in combined, token


def test_enrollment_status_copy_and_bridge_states_are_backend_owned() -> None:
    mixin = SETTINGS_MIXIN.read_text(encoding="utf-8")
    i18n = I18N.read_text(encoding="utf-8")

    for token in ["enrollment_started", "capturing", "enrollment_success", "enrollment_failed"]:
        assert token in mixin
    for key in [
        "face_status_enrollment_started",
        "face_status_capturing",
        "face_status_enrollment_success",
        "face_status_enrollment_failed",
        "face_detail_enrollment_started",
        "face_detail_capturing",
    ]:
        assert i18n.count(f'"{key}"') >= 2, key
