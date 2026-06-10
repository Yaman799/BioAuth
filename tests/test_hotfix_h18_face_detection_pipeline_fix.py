from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import app_settings
from face_biometrics import FaceBox, FaceQualityError, OpenCVFaceEngine
from face_camera_provider import CAMERA_STATUS_CAPTURED, OpenCVCameraProvider
from identity_confirmation import IdentityConfirmationService
from face_template_store import FaceTemplateStore


class FakeDetector:
    def __init__(self, row):
        self.row = np.asarray(row, dtype=np.float32)
        self.input_size = None

    def setInputSize(self, size):
        self.input_size = tuple(size)

    def detect(self, frame):
        return None, np.asarray([self.row], dtype=np.float32)


class FakeRecognizer:
    def __init__(self):
        self.align_rows = []

    def alignCrop(self, frame, face_row):
        self.align_rows.append(np.asarray(face_row, dtype=np.float32).reshape(-1).copy())
        return np.asarray(frame).copy()

    def feature(self, aligned):
        return np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


class FakeFaceDetectorYN:
    detector = None

    @classmethod
    def create(cls, *args, **kwargs):
        return cls.detector


class FakeFaceRecognizerSF:
    recognizer = None

    @classmethod
    def create(cls, *args, **kwargs):
        return cls.recognizer


class FakeCV2:
    FaceDetectorYN = FakeFaceDetectorYN
    FaceRecognizerSF = FakeFaceRecognizerSF


class FakeCapture:
    def __init__(self, frames=(), *, opened=True):
        self._frames = list(frames)
        self._opened = opened
        self.released = False
        self.reads = 0

    def isOpened(self):
        return self._opened

    def read(self):
        self.reads += 1
        if self._frames:
            return self._frames.pop(0)
        return False, None

    def release(self):
        self.released = True


class FixedFaceEngine:
    model_id = "fixed-h18-test-engine"

    def __init__(self, *, detections=None, embedding=None):
        self.detections = detections if detections is not None else [FaceBox(4, 4, 64, 64, 0.99, tuple(float(i) for i in range(10)))]
        self.embedding = np.asarray(embedding if embedding is not None else [1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def detect_faces(self, frame):
        return self.detections

    def extract_embedding(self, frame, face):
        if len(tuple(getattr(face, "landmarks", ()) or ())) != 10:
            raise FaceQualityError("invalid_face_geometry")
        return self.embedding


def _install_fake_models(tmp_path: Path) -> None:
    model_dir = tmp_path / "models" / "face"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "face_detection_yunet_2023mar.onnx").write_text("fake detector fixture", encoding="utf-8")
    (model_dir / "face_recognition_sface_2021dec.onnx").write_text("fake recognizer fixture", encoding="utf-8")


def _engine(tmp_path: Path, row):
    _install_fake_models(tmp_path)
    FakeFaceDetectorYN.detector = FakeDetector(row)
    FakeFaceRecognizerSF.recognizer = FakeRecognizer()
    return OpenCVFaceEngine(runtime_base=tmp_path, cv2_module=FakeCV2), FakeFaceRecognizerSF.recognizer


def _frame(value: int = 120):
    return np.full((96, 96, 3), value, dtype=np.uint8)


def test_h18_yunet_landmarks_are_preserved_by_detect_faces(tmp_path):
    row = [10, 12, 64, 66, 20, 22, 48, 22, 34, 38, 24, 56, 46, 56, 0.91]
    engine, _ = _engine(tmp_path, row)

    faces = engine.detect_faces(_frame())

    assert len(faces) == 1
    assert faces[0].landmarks == tuple(float(v) for v in row[4:14])
    assert faces[0].confidence == pytest.approx(row[14])


def test_h18_extract_embedding_passes_full_15_value_yunet_row_to_sface(tmp_path):
    row = [10, 12, 64, 66, 20, 22, 48, 22, 34, 38, 24, 56, 46, 56, 0.91]
    engine, recognizer = _engine(tmp_path, row)
    face = engine.detect_faces(_frame())[0]

    embedding = engine.extract_embedding(_frame(), face)

    assert embedding.shape == (4,)
    assert len(recognizer.align_rows) == 1
    assert recognizer.align_rows[0].shape == (15,)
    assert recognizer.align_rows[0].tolist() == pytest.approx(row)


def test_h18_missing_landmarks_fail_closed_without_random_embedding(tmp_path):
    row = [10, 12, 64, 66, 20, 22, 48, 22, 34, 38, 24, 56, 46, 56, 0.91]
    engine, recognizer = _engine(tmp_path, row)

    with pytest.raises(FaceQualityError, match="invalid_face_geometry"):
        engine.extract_embedding(_frame(), FaceBox(10, 12, 64, 66, 0.91))

    assert recognizer.align_rows == []


def test_h18_camera_provider_discards_warmup_frames_before_capture():
    frames = [
        (True, _frame(1)),
        (True, _frame(2)),
        (True, _frame(3)),
        (True, _frame(20)),
        (True, _frame(21)),
    ]
    capture = FakeCapture(frames=frames)
    provider = OpenCVCameraProvider(
        device_index=2,
        warmup_frames=3,
        timeout_sec=0.5,
        read_interval_sec=0.0,
        capture_factory=lambda index: capture,
    )

    result = provider.capture_enrollment_frames(2)

    assert result.status == CAMERA_STATUS_CAPTURED
    assert result.ok is True
    assert result.backend_camera_index == 2
    assert result.warmup_frames_read == 3
    assert result.capture_attempts == 2
    assert [int(frame[0, 0, 0]) for frame in result.frames] == [20, 21]
    assert capture.released is True


def test_h18_camera_provider_uses_selected_backend_camera_index():
    opened_indexes = []
    capture = FakeCapture(frames=[(True, _frame(7))])

    def factory(index):
        opened_indexes.append(index)
        return capture

    provider = OpenCVCameraProvider(device_index=4, warmup_frames=0, timeout_sec=0.5, read_interval_sec=0.0, capture_factory=factory)
    result = provider.capture_verification_frame()

    assert opened_indexes == [4]
    assert result.ok is True
    assert result.to_safe_dict()["backend_camera_index"] == 4


def test_h18_enrollment_receives_non_empty_captured_frames_after_warmup(tmp_path, monkeypatch):
    monkeypatch.setattr("security.MODELS_DIR", str(tmp_path / "models"))
    store = FaceTemplateStore(tmp_path / "templates")
    service = IdentityConfirmationService(store=store, engine=FixedFaceEngine())
    capture = FakeCapture(frames=[(True, _frame(1)), (True, _frame(2)), (True, _frame(80)), (True, _frame(81)), (True, _frame(82))])
    provider = OpenCVCameraProvider(warmup_frames=2, timeout_sec=0.5, read_interval_sec=0.0, capture_factory=lambda index: capture)

    captured = provider.capture_enrollment_frames(3)
    result = service.enroll("owner", captured.frames, consent_granted=True, min_samples=3)

    assert captured.ok is True
    assert captured.frame_count == 3
    assert result["status"] == "enrolled"
    assert result["ok"] is True
    assert result["raw_images_stored"] is False


def test_h18_face_quality_failures_remain_fail_closed(tmp_path):
    store = FaceTemplateStore(tmp_path / "templates")
    frames = [_frame(90), _frame(91), _frame(92)]

    no_face = IdentityConfirmationService(store=store, engine=FixedFaceEngine(detections=[])).enroll("owner", frames, consent_granted=True, min_samples=3)
    multiple = IdentityConfirmationService(
        store=store,
        engine=FixedFaceEngine(detections=[FaceBox(0, 0, 64, 64, 0.9), FaceBox(2, 2, 64, 64, 0.9)]),
    ).enroll("owner", frames, consent_granted=True, min_samples=3)
    poor = IdentityConfirmationService(store=store, engine=FixedFaceEngine(detections=[FaceBox(0, 0, 2, 2, 0.9)])).enroll("owner", frames, consent_granted=True, min_samples=3)

    assert no_face["status"] == "no_face_detected"
    assert no_face["ok"] is False
    assert multiple["status"] == "multiple_faces_detected"
    assert multiple["ok"] is False
    assert poor["status"] == "poor_quality"
    assert poor["ok"] is False


def test_h18_backend_camera_index_setting_is_persisted_safely():
    assert app_settings._coerce_settings_payload({"backend_face_camera_index": "2"})["backend_face_camera_index"] == 2
    assert app_settings._coerce_settings_payload({"backend_face_camera_index": -99})["backend_face_camera_index"] == 0
    assert app_settings._coerce_settings_payload({"backend_face_camera_index": 99})["backend_face_camera_index"] == 4
    assert app_settings._coerce_settings_payload({"face_enrollment_frame_count": 3})["face_enrollment_frame_count"] == 3
    assert app_settings._coerce_settings_payload({"face_enrollment_frame_count": 99})["face_enrollment_frame_count"] == 7


def test_h18_qml_preview_remains_display_only_and_pauses_before_backend_capture():
    qml_files = [
        Path("qml/components/FaceCameraPreview.qml"),
        Path("qml/dialogs/FaceEnrollmentDialog.qml"),
        Path("qml/pages/user/UserFaceConfirmationPage.qml"),
    ]
    sources = "\n".join(path.read_text(encoding="utf-8") for path in qml_files)
    lowered = sources.lower()

    assert "mirrored: true" in sources
    assert "pauseForBackendCapture" in sources
    assert "interval: 420" in sources
    assert "backend.setBackendFaceCameraIndex" in sources
    assert "backend.grantFaceTemplateConsent" in sources
    assert "backend.enrollFaceTemplate" in sources
    assert "backend.testFaceConfirmation" in sources

    forbidden_tokens = [
        "facedetectoryn",
        "facerecognizersf",
        "detect_faces",
        "extract_embedding",
        "aligncrop",
        "liveness",
        "anti_spoof",
        "antispoof",
        "protectedsessionsavailable",
        "productionready",
        "capturetofile",
        "grabtoimage",
        "screenshot",
        "imwrite",
        "imsave",
    ]
    for token in forbidden_tokens:
        assert token not in lowered
