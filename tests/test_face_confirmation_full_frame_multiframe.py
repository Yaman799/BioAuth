from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from face_biometrics import FaceBox
from face_camera_provider import CAMERA_STATUS_CAPTURED, OpenCVCameraProvider
from face_template_store import FaceTemplateStore
from identity_confirmation import IdentityConfirmationService
from tests.test_hotfix_h15_face_verification_test_button import BridgeForVerification
from tests.test_phase_11_face_biometrics_backend import _configure_crypto

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "bridge" / "i18n.py"


def _frame(value: int) -> np.ndarray:
    return np.full((96, 96, 3), value, dtype=np.uint8)


class FakeCapture:
    def __init__(self, frames):
        self._frames = list(frames)
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        if self._frames:
            return self._frames.pop(0)
        return False, None

    def release(self):
        self.released = True


class FrameAwareEngine:
    model_id = "full-frame-multiframe-test-v1"

    def detect_faces(self, frame):
        marker = int(np.asarray(frame)[0, 0, 0])
        if marker == 0:
            return []
        if marker == 2:
            return [FaceBox(8, 8, 64, 64, 0.99), FaceBox(20, 20, 64, 64, 0.98)]
        return [FaceBox(8, 8, 64, 64, 0.99)]

    def extract_embedding(self, frame, face):
        return np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


@dataclass(frozen=True)
class FakeCaptureResult:
    status: str
    ok: bool
    frames: tuple[object, ...]
    reason: str = "captured"

    @property
    def frame(self):
        return self.frames[0] if self.frames else None

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def to_safe_dict(self):
        return {"status": self.status, "ok": self.ok, "reason": self.reason, "frame_count": len(self.frames), "raw_images_stored": False}


class MultiFrameCamera:
    def __init__(self, frames):
        self.frames = tuple(frames)
        self.verification_frame_requests: list[int] = []
        self.single_frame_calls = 0

    def capture_verification_frames(self, count: int):
        self.verification_frame_requests.append(int(count))
        return FakeCaptureResult(status="captured", ok=True, frames=self.frames[: int(count)])

    def capture_verification_frame(self):  # pragma: no cover - bridge should prefer multi-frame provider API
        self.single_frame_calls += 1
        return FakeCaptureResult(status="captured", ok=True, frames=self.frames[:1])

    def capture_enrollment_frames(self, count: int):  # pragma: no cover
        raise AssertionError("verification must not use enrollment capture")


class MultiFrameService:
    def __init__(self, result=None):
        self.status_calls: list[str] = []
        self.frame_batches: list[tuple[object, ...]] = []
        self.result = dict(result or {"status": "verified", "ok": True, "verified": True})

    def status(self, user_id: str):
        self.status_calls.append(user_id)
        return {"status": "enrolled", "enrolled": True}

    def test_verification_frames(self, user_id: str, frames):
        self.frame_batches.append(tuple(frames))
        return dict(self.result)


def test_opencv_provider_can_capture_multiple_full_verification_frames_without_persisting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(Path(tmp_path).rglob("*"))
    capture = FakeCapture(frames=[(True, _frame(10)), (True, _frame(11)), (True, _frame(12)), (True, _frame(13)), (True, _frame(14))])
    provider = OpenCVCameraProvider(warmup_frames=0, timeout_sec=0.5, read_interval_sec=0.0, capture_factory=lambda _index: capture)

    result = provider.capture_verification_frames(5)

    assert result.status == CAMERA_STATUS_CAPTURED
    assert result.ok is True
    assert result.frame_count == 5
    assert [int(frame[0, 0, 0]) for frame in result.frames] == [10, 11, 12, 13, 14]
    assert result.raw_images_stored is False
    assert "frames" not in result.to_safe_dict()
    assert set(Path(tmp_path).rglob("*")) == before
    assert capture.released is True


def test_identity_verification_frames_skip_no_face_samples_and_verify_later_full_frame(tmp_path, monkeypatch):
    _configure_crypto(tmp_path, monkeypatch)
    service = IdentityConfirmationService(store=FaceTemplateStore(tmp_path / "templates"), engine=FrameAwareEngine())
    enrolled = service.enroll("owner", [_frame(30), _frame(31), _frame(32)], consent_granted=True, min_samples=3)
    assert enrolled["ok"] is True

    result = service.test_verification_frames("owner", [_frame(0), _frame(0), _frame(40)])

    assert result["status"] == "verified"
    assert result["verified"] is True
    assert result["ok"] is True
    assert result["verification_frame_count"] == 3
    assert result["usable_frame_count"] == 1
    assert result["lock_integration_enabled"] is False
    assert "embedding" not in result


def test_identity_verification_frames_fail_closed_on_multiple_faces_even_with_later_match(tmp_path, monkeypatch):
    _configure_crypto(tmp_path, monkeypatch)
    service = IdentityConfirmationService(store=FaceTemplateStore(tmp_path / "templates"), engine=FrameAwareEngine())
    enrolled = service.enroll("owner", [_frame(30), _frame(31), _frame(32)], consent_granted=True, min_samples=3)
    assert enrolled["ok"] is True

    result = service.test_verification_frames("owner", [_frame(2), _frame(40)])

    assert result["status"] == "multiple_faces_detected"
    assert result["verified"] is False
    assert result["ok"] is False
    assert result["reason"] == "multiple_faces"
    assert result["lock_integration_enabled"] is False


def test_settings_bridge_prefers_multiframe_capture_and_keeps_qml_out_of_verification_decisions():
    frames = (_frame(1), _frame(2), _frame(3), _frame(4), _frame(5))
    camera = MultiFrameCamera(frames)
    service = MultiFrameService()
    bridge = BridgeForVerification(camera_provider=camera, service=service)

    result = bridge.testFaceConfirmation()

    assert result["status"] == "verified"
    assert result["verified"] is True
    assert result["lockIntegrationEnabled"] is False
    assert result["rawImagesStored"] is False
    assert result["frameCount"] == 5
    assert camera.verification_frame_requests == [5]
    assert camera.single_frame_calls == 0
    assert service.status_calls == ["owner@example.com"]
    assert service.frame_batches == [frames]
    assert "frames" not in result
    assert "frame" not in result
    qml_page = (ROOT / "qml" / "pages" / "user" / "UserFaceConfirmationPage.qml").read_text(encoding="utf-8").lower()
    for forbidden in ("detectfaces", "extractembedding", "cosinesimilarity", "verify_embedding", "threshold"):
        assert forbidden not in qml_page


def test_no_face_copy_describes_full_camera_view_not_center_only():
    text = I18N.read_text(encoding="utf-8")
    assert "Keep your face visible anywhere inside the camera view" in text
    assert "face centered and visible" not in text
    assert "توسيط الوجه" not in text
