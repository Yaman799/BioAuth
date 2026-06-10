from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from face_biometrics import FaceBox
from face_template_store import FaceTemplateStore
from identity_confirmation import IdentityConfirmationService
from tests.test_hotfix_h8_real_face_enrollment_wiring import DummySignal, SettingsMixin
from tests.test_phase_11_face_biometrics_backend import _configure_crypto

ROOT = Path(__file__).resolve().parent.parent
FACE_PAGE = ROOT / "qml" / "pages" / "user" / "UserFaceConfirmationPage.qml"
SETTINGS_MIXIN = ROOT / "bridge" / "settings_mixin.py"


@dataclass(frozen=True)
class FakeCaptureResult:
    status: str
    ok: bool
    frames: tuple[object, ...] = ()
    reason: str = ""
    raw_images_stored: bool = False

    @property
    def frame(self):
        return self.frames[0] if self.frames else None

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def to_safe_dict(self) -> dict[str, object]:
        return {"status": self.status, "ok": self.ok, "reason": self.reason or self.status, "frame_count": len(self.frames), "raw_images_stored": False}


class FakeCameraProvider:
    def __init__(self, result: FakeCaptureResult) -> None:
        self.result = result
        self.verification_calls = 0
        self.enrollment_calls = 0

    def capture_verification_frame(self) -> FakeCaptureResult:
        self.verification_calls += 1
        return self.result

    def capture_enrollment_frames(self, count: int) -> FakeCaptureResult:  # pragma: no cover
        self.enrollment_calls += 1
        raise AssertionError("test face confirmation must use single-frame verification capture")


class MutableFakeFaceEngine:
    model_id = "fake-sface-h15-v1"

    def __init__(self, *, embedding=None, detections=None) -> None:
        self.embedding = np.asarray(embedding if embedding is not None else [1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        self.detections = detections if detections is not None else [FaceBox(8, 8, 72, 72, 0.99)]
        self.detect_calls = 0
        self.extract_calls = 0

    def detect_faces(self, frame):
        self.detect_calls += 1
        return self.detections

    def extract_embedding(self, frame, face):
        self.extract_calls += 1
        return self.embedding


class BridgeForVerification(SettingsMixin):
    def __init__(self, *, camera_provider, service, consent: bool = True, feature_enabled: bool = True, face_confirmation_enabled: bool = True, model_ready: bool = True, model_status: str = "models_ready") -> None:
        self._current_user = {"user_id": "owner@example.com"}
        self._app_settings = {"enable_face_enrollment": bool(feature_enabled), "enable_face_confirmation": bool(feature_enabled), "face_confirmation_enabled": bool(face_confirmation_enabled), "face_template_consent_granted": bool(consent)}
        self._face_confirmation_enabled = bool(face_confirmation_enabled)
        self._face_confirmation_operation_state = {"status": "idle", "ok": True}
        self._language = "en"
        self._t = lambda key, **_kwargs: key
        self.faceConfirmationChanged = DummySignal()
        self.statuses: list[tuple[str, str]] = []
        self._camera_provider = camera_provider
        self._service = service
        self._model_ready = bool(model_ready)
        self._model_status = model_status

    def _set_status(self, message: str, tone: str = "info") -> None:
        self.statuses.append((message, tone))

    def _face_camera_provider(self):
        return self._camera_provider

    def _face_enrollment_service(self):
        return self._service

    def _face_service(self):
        return self._service

    def _face_model_readiness_state(self) -> dict[str, object]:
        return {"ok": self._model_ready, "status": self._model_status, "reason": self._model_status}


def _good_frame(value: int = 180) -> np.ndarray:
    return np.full((96, 96, 3), value, dtype=np.uint8)


def _enrolled_service(tmp_path, monkeypatch, *, enrollment_embedding=None):
    _configure_crypto(tmp_path, monkeypatch)
    store = FaceTemplateStore(tmp_path / "face_templates")
    engine = MutableFakeFaceEngine(embedding=enrollment_embedding if enrollment_embedding is not None else [1.0, 0.0, 0.0, 0.0])
    service = IdentityConfirmationService(store=store, engine=engine)
    enrolled = service.enroll("owner@example.com", [_good_frame(), _good_frame(181), _good_frame(182)], consent_granted=True)
    assert enrolled["ok"] is True
    assert store.has_template("owner@example.com") is True
    return service, engine, store


def test_test_face_confirmation_button_is_visible_backend_owned_and_gated() -> None:
    page = FACE_PAGE.read_text(encoding="utf-8")
    lowered = page.lower()
    assert 'objectName: "faceTestConfirmationButton"' in page
    assert 'text: backend.tr("face_test_confirmation")' in page
    assert "enabled: root.cantestface" in lowered
    assert "backend.testfaceconfirmation()" in lowered
    for token in ["extractembedding", "detectfaces", "cosinesimilarity", "verify_embedding", "score >=", "threshold", "face unlock", "lock_suppressed", "approved_for_production", "protectedsessionsavailable"]:
        assert token not in lowered, token


def test_matching_fake_face_verifies_with_encrypted_template(tmp_path, monkeypatch) -> None:
    service, engine, _store = _enrolled_service(tmp_path, monkeypatch, enrollment_embedding=[1.0, 0.0, 0.0, 0.0])
    engine.embedding = np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    frame = _good_frame(190)
    camera = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(frame,), reason="captured"))
    bridge = BridgeForVerification(camera_provider=camera, service=service)
    result = bridge.testFaceConfirmation()
    assert result["status"] == "verified"
    assert result["ok"] is True
    assert result["verified"] is True
    assert result["verificationStatus"] == "verified"
    assert result["lockIntegrationEnabled"] is False
    assert result["lock_integration_enabled"] is False
    assert result["rawImagesStored"] is False
    assert camera.verification_calls == 1
    assert camera.enrollment_calls == 0
    assert engine.detect_calls >= 4
    assert engine.extract_calls >= 4
    for forbidden in ("frame", "frames", "image", "images", "embedding", "template_digest", "score", "threshold", "quality_score"):
        assert forbidden not in result
        assert forbidden not in bridge._face_confirmation_operation_state


def test_different_fake_face_returns_not_verified(tmp_path, monkeypatch) -> None:
    service, engine, _store = _enrolled_service(tmp_path, monkeypatch, enrollment_embedding=[1.0, 0.0, 0.0, 0.0])
    engine.embedding = np.asarray([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
    camera = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(_good_frame(191),), reason="captured"))
    bridge = BridgeForVerification(camera_provider=camera, service=service)
    result = bridge.testFaceConfirmation()
    assert result["status"] == "not_verified"
    assert result["ok"] is False
    assert result["verified"] is False
    assert result["verificationStatus"] == "not_verified"
    assert result["lockIntegrationEnabled"] is False
    assert camera.verification_calls == 1


def test_missing_template_fails_closed_before_camera_capture(tmp_path, monkeypatch) -> None:
    _configure_crypto(tmp_path, monkeypatch)
    service = IdentityConfirmationService(store=FaceTemplateStore(tmp_path / "face_templates"), engine=MutableFakeFaceEngine())
    camera = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(_good_frame(),), reason="captured"))
    bridge = BridgeForVerification(camera_provider=camera, service=service)
    result = bridge.testFaceConfirmation()
    assert result["status"] in {"not_enrolled", "template_missing"}
    assert result["ok"] is False
    assert result["verified"] is False
    assert camera.verification_calls == 0


def test_missing_consent_models_and_camera_fail_closed(tmp_path, monkeypatch) -> None:
    service, _engine, _store = _enrolled_service(tmp_path, monkeypatch)
    available_camera = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(_good_frame(),), reason="captured"))
    no_consent = BridgeForVerification(camera_provider=available_camera, service=service, consent=False)
    consent_result = no_consent.testFaceConfirmation()
    assert consent_result["status"] == "consent_required"
    assert consent_result["verified"] is False
    assert available_camera.verification_calls == 0
    missing_models = BridgeForVerification(camera_provider=available_camera, service=service, model_ready=False, model_status="models_missing")
    model_result = missing_models.testFaceConfirmation()
    assert model_result["status"] == "models_missing"
    assert model_result["verified"] is False
    assert available_camera.verification_calls == 0
    unavailable_camera = FakeCameraProvider(FakeCaptureResult(status="device_open_failed", ok=False, frames=(), reason="permission_or_device_open_failure"))
    no_camera = BridgeForVerification(camera_provider=unavailable_camera, service=service)
    camera_result = no_camera.testFaceConfirmation()
    assert camera_result["status"] == "camera_unavailable"
    assert camera_result["verified"] is False
    assert camera_result["captureStatus"] == "device_open_failed"
    assert unavailable_camera.verification_calls == 1


def test_no_face_multiple_faces_and_poor_quality_are_backend_reason_codes(tmp_path, monkeypatch) -> None:
    cases = [([], "no_face_detected"), ([FaceBox(0, 0, 72, 72), FaceBox(1, 1, 72, 72)], "multiple_faces_detected"), ([FaceBox(0, 0, 4, 4, 0.99)], "poor_quality")]
    for detections, expected_status in cases:
        service, engine, _store = _enrolled_service(tmp_path / expected_status, monkeypatch)
        engine.detections = detections
        camera = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(_good_frame(),), reason="captured"))
        bridge = BridgeForVerification(camera_provider=camera, service=service)
        result = bridge.testFaceConfirmation()
        assert result["status"] == expected_status
        assert result["ok"] is False
        assert result["verified"] is False
        assert result["lockIntegrationEnabled"] is False
        assert camera.verification_calls == 1


def test_bridge_verification_surface_strips_scores_thresholds_and_raw_biometric_values() -> None:
    mixin = SETTINGS_MIXIN.read_text(encoding="utf-8")
    assert "service.test_verification(user_id, frame)" in mixin
    assert "capture_verification_frame()" in mixin
    assert '"score", "threshold", "quality_score"' in mixin
    assert "verification_failed" in mixin
