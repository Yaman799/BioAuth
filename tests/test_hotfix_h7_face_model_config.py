from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from face_biometrics import (
    DEFAULT_FACE_DETECTOR_MODEL_FILENAME,
    DEFAULT_FACE_MODEL_ID,
    DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME,
    FACE_MODELS_CONFIGURED,
    FACE_MODELS_INVALID,
    FACE_MODELS_MISSING,
    FaceBackendUnavailable,
    FaceBox,
    FaceEngineModelConfig,
    OpenCVFaceEngine,
    build_enrollment_template,
    default_face_model_config,
    validate_face_model_config,
    verify_frame_against_template,
)


class FakeFaceEngine:
    model_id = "fake-face-engine-h7"

    def detect_faces(self, frame):
        return [FaceBox(0, 0, 64, 64, 0.99)]

    def extract_embedding(self, frame, face):
        return np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


class FakeFaceDetectorYN:
    created_with = None

    @classmethod
    def create(cls, model_path, config, input_size):
        cls.created_with = (model_path, config, input_size)
        return cls()

    def setInputSize(self, size):
        self.input_size = size

    def detect(self, frame):
        return None, np.asarray([[0, 0, 64, 64, 0, 0, 0, 0, 0, 0, 0.99]], dtype=np.float32)


class FakeFaceRecognizerSF:
    created_with = None

    @classmethod
    def create(cls, model_path, config):
        cls.created_with = (model_path, config)
        return cls()

    def alignCrop(self, frame, face_row):
        return frame

    def feature(self, aligned):
        return np.asarray([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)


class FakeCV2:
    FaceDetectorYN = FakeFaceDetectorYN
    FaceRecognizerSF = FakeFaceRecognizerSF


class FailingDetectorYN(FakeFaceDetectorYN):
    @classmethod
    def create(cls, model_path, config, input_size):
        raise RuntimeError("bad detector model")


class FailingCV2(FakeCV2):
    FaceDetectorYN = FailingDetectorYN


def _write_configured_models(tmp_path: Path) -> FaceEngineModelConfig:
    model_dir = tmp_path / "models" / "face"
    model_dir.mkdir(parents=True, exist_ok=True)
    detector = model_dir / DEFAULT_FACE_DETECTOR_MODEL_FILENAME
    recognizer = model_dir / DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME
    detector.write_bytes(b"fake-yunet-placeholder-for-tests")
    recognizer.write_bytes(b"fake-sface-placeholder-for-tests")
    return default_face_model_config(runtime_base=tmp_path)


def test_default_face_model_config_uses_project_relative_models_face(tmp_path):
    config = default_face_model_config(runtime_base=tmp_path)

    assert Path(config.detector_model_path) == tmp_path / "models" / "face" / DEFAULT_FACE_DETECTOR_MODEL_FILENAME
    assert Path(config.recognizer_model_path) == tmp_path / "models" / "face" / DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME
    assert config.model_id == DEFAULT_FACE_MODEL_ID
    assert Path(config.detector_model_path).is_absolute()
    assert Path(config.detector_model_path).parts[-3:] == ("models", "face", DEFAULT_FACE_DETECTOR_MODEL_FILENAME)


def test_missing_default_model_files_fail_closed_without_importing_opencv(tmp_path):
    status = validate_face_model_config(runtime_base=tmp_path)

    assert status["ok"] is False
    assert status["status"] == FACE_MODELS_MISSING
    with pytest.raises(FaceBackendUnavailable, match=FACE_MODELS_MISSING):
        OpenCVFaceEngine(runtime_base=tmp_path, cv2_module=FakeCV2)


def test_configured_model_paths_initialize_opencv_engine_with_explicit_paths(tmp_path):
    config = _write_configured_models(tmp_path)

    status = validate_face_model_config(config, runtime_base=tmp_path)
    engine = OpenCVFaceEngine(model_config=config, runtime_base=tmp_path, cv2_module=FakeCV2)

    assert status["ok"] is True
    assert status["status"] == FACE_MODELS_CONFIGURED
    assert engine.detector_model_path == str(tmp_path / "models" / "face" / DEFAULT_FACE_DETECTOR_MODEL_FILENAME)
    assert engine.recognizer_model_path == str(tmp_path / "models" / "face" / DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME)
    assert FakeFaceDetectorYN.created_with[0] == engine.detector_model_path
    assert FakeFaceRecognizerSF.created_with[0] == engine.recognizer_model_path


def test_invalid_model_configuration_fails_closed(tmp_path):
    bad_suffix = tmp_path / "models" / "face" / "detector.bin"
    recognizer = tmp_path / "models" / "face" / DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME
    recognizer.parent.mkdir(parents=True, exist_ok=True)
    bad_suffix.write_bytes(b"not-onnx")
    recognizer.write_bytes(b"fake")
    config = FaceEngineModelConfig(detector_model_path=str(bad_suffix), recognizer_model_path=str(recognizer))

    status = validate_face_model_config(config, runtime_base=tmp_path)

    assert status["ok"] is False
    assert status["status"] == FACE_MODELS_INVALID
    with pytest.raises(FaceBackendUnavailable, match=FACE_MODELS_INVALID):
        OpenCVFaceEngine(model_config=config, runtime_base=tmp_path, cv2_module=FakeCV2)


def test_opencv_create_failure_is_reported_as_invalid_model_config(tmp_path):
    config = _write_configured_models(tmp_path)

    with pytest.raises(FaceBackendUnavailable, match=FACE_MODELS_INVALID):
        OpenCVFaceEngine(model_config=config, runtime_base=tmp_path, cv2_module=FailingCV2)


def test_fake_fixture_engine_behavior_still_works_without_real_model_assets():
    frame = np.full((96, 96, 3), 180, dtype=np.uint8)
    engine = FakeFaceEngine()

    template = build_enrollment_template([frame, frame, frame], engine, min_samples=3)
    result = verify_frame_against_template(frame, template, engine, threshold=0.9)

    assert template["embedding_model_id"] == "fake-face-engine-h7"
    assert result["verified"] is True
