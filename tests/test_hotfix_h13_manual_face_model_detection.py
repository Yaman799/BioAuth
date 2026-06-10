from __future__ import annotations

from pathlib import Path

import pytest

from face_biometrics import (
    DEFAULT_FACE_DETECTOR_MODEL_FILENAME,
    DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME,
    FACE_DETECTOR_MODEL_MISSING,
    FACE_MODELS_MISSING,
    FACE_MODELS_READY,
    FACE_RECOGNIZER_MODEL_MISSING,
    FaceBackendUnavailable,
    OpenCVFaceEngine,
    default_face_model_config,
    validate_face_model_config,
)


def _write_detector(model_dir: Path) -> Path:
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / DEFAULT_FACE_DETECTOR_MODEL_FILENAME
    path.write_bytes(b"fake-yunet-onnx-fixture-for-h13")
    return path


def _write_recognizer(model_dir: Path) -> Path:
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME
    path.write_bytes(b"fake-sface-onnx-fixture-for-h13")
    return path


def test_default_model_config_uses_manual_opencv_zoo_filenames(tmp_path: Path) -> None:
    config = default_face_model_config(runtime_base=tmp_path)

    assert Path(config.detector_model_path) == tmp_path / "models" / "face" / "face_detection_yunet_2023mar.onnx"
    assert Path(config.recognizer_model_path) == tmp_path / "models" / "face" / "face_recognition_sface_2021dec.onnx"
    assert Path(config.detector_model_path).is_absolute()
    assert Path(config.recognizer_model_path).is_absolute()


def test_missing_both_expected_models_fails_closed_with_models_missing(tmp_path: Path) -> None:
    status = validate_face_model_config(runtime_base=tmp_path)

    assert status["ok"] is False
    assert status["status"] == FACE_MODELS_MISSING
    assert status["reason"] == FACE_MODELS_MISSING
    assert set(status["missing"]) == {"detector", "recognizer"}
    with pytest.raises(FaceBackendUnavailable, match=FACE_MODELS_MISSING):
        OpenCVFaceEngine(runtime_base=tmp_path, cv2_module=object())


def test_missing_detector_is_reported_without_crashing(tmp_path: Path) -> None:
    model_dir = tmp_path / "models" / "face"
    _write_recognizer(model_dir)

    status = validate_face_model_config(runtime_base=tmp_path)

    assert status["ok"] is False
    assert status["status"] == FACE_DETECTOR_MODEL_MISSING
    assert status["reason"] == FACE_DETECTOR_MODEL_MISSING
    assert status["missing"] == ("detector",)


def test_missing_recognizer_is_reported_without_crashing(tmp_path: Path) -> None:
    model_dir = tmp_path / "models" / "face"
    _write_detector(model_dir)

    status = validate_face_model_config(runtime_base=tmp_path)

    assert status["ok"] is False
    assert status["status"] == FACE_RECOGNIZER_MODEL_MISSING
    assert status["reason"] == FACE_RECOGNIZER_MODEL_MISSING
    assert status["missing"] == ("recognizer",)


def test_both_manually_installed_expected_files_report_models_ready(tmp_path: Path) -> None:
    model_dir = tmp_path / "models" / "face"
    _write_detector(model_dir)
    _write_recognizer(model_dir)

    status = validate_face_model_config(runtime_base=tmp_path)

    assert status["ok"] is True
    assert status["status"] == FACE_MODELS_READY
    assert status["reason"] == FACE_MODELS_READY
    assert status["missing"] == ()


def test_legacy_or_renamed_onnx_files_do_not_report_ready(tmp_path: Path) -> None:
    model_dir = tmp_path / "models" / "face"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "face_detection_yunet.onnx").write_bytes(b"old-name")
    (model_dir / "face_recognition_sface.onnx").write_bytes(b"old-name")

    status = validate_face_model_config(runtime_base=tmp_path)

    assert status["ok"] is False
    assert status["status"] != FACE_MODELS_READY


def test_project_readme_names_manual_files_and_forbids_face_payloads() -> None:
    readme = Path("models/face/README.md").read_text(encoding="utf-8")

    assert "face_detection_yunet_2023mar.onnx" in readme
    assert "face_recognition_sface_2021dec.onnx" in readme
    assert "does not ship or download" in readme
    assert "Do not place captured face frames" in readme


def test_no_real_onnx_binaries_are_checked_into_project_models_face() -> None:
    model_dir = Path("models/face")
    checked_in_onnx = sorted(p.name for p in model_dir.glob("*.onnx"))

    assert checked_in_onnx == []
