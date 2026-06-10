from __future__ import annotations

"""Local, opt-in face biometric helpers for BioAuth.

Phase 11 intentionally does not connect these helpers to monitor.py, locking, or
protected-session decisions.  The module focuses on deterministic enrollment and
verification primitives that can be exercised without storing raw frames.
"""

import base64
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Protocol, Sequence

import numpy as np

FACE_TEMPLATE_SCHEMA_VERSION = 1
FACE_TEMPLATE_KIND = "face_confirmation_template"
DEFAULT_FACE_MODEL_ID = "opencv-yunet-sface-compatible-v1"
DEFAULT_VERIFY_THRESHOLD = 0.55
DEFAULT_MIN_SAMPLE_COUNT = 5
DEFAULT_MIN_FACE_SIZE = 32
DEFAULT_MIN_QUALITY_SCORE = 0.25
DEFAULT_FACE_MODEL_DIR = Path("models") / "face"
DEFAULT_FACE_DETECTOR_MODEL_FILENAME = "face_detection_yunet_2023mar.onnx"
DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME = "face_recognition_sface_2021dec.onnx"
FACE_MODELS_READY = "models_ready"
FACE_MODELS_CONFIGURED = FACE_MODELS_READY
FACE_MODELS_MISSING = "models_missing"
FACE_DETECTOR_MODEL_MISSING = "detector_model_missing"
FACE_RECOGNIZER_MODEL_MISSING = "recognizer_model_missing"
FACE_MODELS_INVALID = "face_models_invalid"
LEGACY_FACE_MODELS_CONFIGURED = "face_models_configured"
LEGACY_FACE_MODELS_MISSING = "face_models_missing"



class FaceBiometricsError(ValueError):
    """Base class for local face biometric failures."""


class FaceBackendUnavailable(FaceBiometricsError):
    """Raised when no compatible local face backend is available."""


class FaceQualityError(FaceBiometricsError):
    """Raised when a frame is unsuitable for enrollment or verification."""


class FaceEnrollmentQualityError(FaceQualityError):
    """Enrollment-level quality failure with privacy-safe rejection metadata.

    The exception message remains the broad enrollment failure reason for
    compatibility with existing tests and callers.  The per-frame rejection
    reasons are non-biometric status tokens only; they must never contain raw
    frames, crops, embeddings, or image paths.
    """

    def __init__(self, message: str, *, rejection_reasons: Iterable[str] | None = None) -> None:
        super().__init__(message)
        self.rejection_reasons = tuple(str(reason or "").strip().lower() for reason in (rejection_reasons or ()) if str(reason or "").strip())


@dataclass(frozen=True)
class FaceEngineModelConfig:
    """Project-relative/resource-resolved face model configuration.

    H7 keeps model assets explicit and backend-owned.  Defaults resolve under
    ``models/face`` relative to the runtime resource base, which is safe for
    both source-tree and frozen-app execution.  This class carries paths only;
    it never loads, logs, stores, or writes raw face images.
    """

    detector_model_path: str
    recognizer_model_path: str
    model_id: str = DEFAULT_FACE_MODEL_ID

    @classmethod
    def default(cls, *, runtime_base: str | Path | None = None) -> "FaceEngineModelConfig":
        base = _face_model_runtime_base(runtime_base)
        model_dir = base / DEFAULT_FACE_MODEL_DIR
        return cls(
            detector_model_path=str(model_dir / DEFAULT_FACE_DETECTOR_MODEL_FILENAME),
            recognizer_model_path=str(model_dir / DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME),
            model_id=DEFAULT_FACE_MODEL_ID,
        )

    def resolved(self, *, runtime_base: str | Path | None = None) -> "FaceEngineModelConfig":
        base = _face_model_runtime_base(runtime_base)
        return FaceEngineModelConfig(
            detector_model_path=str(_resolve_face_model_path(self.detector_model_path, base)),
            recognizer_model_path=str(_resolve_face_model_path(self.recognizer_model_path, base)),
            model_id=str(self.model_id or DEFAULT_FACE_MODEL_ID),
        )

    def validate(self) -> dict[str, Any]:
        detector = Path(str(self.detector_model_path or ""))
        recognizer = Path(str(self.recognizer_model_path or ""))
        invalid: list[str] = []
        missing: list[str] = []
        expected = {
            "detector": DEFAULT_FACE_DETECTOR_MODEL_FILENAME,
            "recognizer": DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME,
        }
        for label, candidate in (("detector", detector), ("recognizer", recognizer)):
            if not str(candidate).strip():
                invalid.append(label)
                continue
            if candidate.exists() and not candidate.is_file():
                invalid.append(label)
                continue
            if candidate.suffix.lower() != ".onnx":
                invalid.append(label)
                continue
            if candidate.name != expected[label]:
                invalid.append(label)
                continue
            if not candidate.exists():
                missing.append(label)
        if invalid:
            return {"ok": False, "status": FACE_MODELS_INVALID, "reason": FACE_MODELS_INVALID, "invalid": tuple(invalid)}
        if missing:
            if len(missing) == 1 and missing[0] == "detector":
                reason = FACE_DETECTOR_MODEL_MISSING
            elif len(missing) == 1 and missing[0] == "recognizer":
                reason = FACE_RECOGNIZER_MODEL_MISSING
            else:
                reason = FACE_MODELS_MISSING
            return {"ok": False, "status": reason, "reason": reason, "missing": tuple(missing)}
        return {"ok": True, "status": FACE_MODELS_READY, "reason": FACE_MODELS_READY, "missing": ()}

    def to_safe_dict(self) -> dict[str, Any]:
        status = self.validate()
        return {
            "model_id": str(self.model_id or DEFAULT_FACE_MODEL_ID),
            "detector_model_path": str(self.detector_model_path),
            "recognizer_model_path": str(self.recognizer_model_path),
            "status": status.get("status", FACE_MODELS_INVALID),
            "ok": bool(status.get("ok", False)),
        }


def _face_model_runtime_base(runtime_base: str | Path | None = None) -> Path:
    if runtime_base is not None:
        return Path(runtime_base).expanduser().resolve()
    from paths import runtime_base_dir

    return Path(runtime_base_dir()).expanduser().resolve()


def _resolve_face_model_path(path: str | Path, runtime_base: Path) -> Path:
    candidate = Path(str(path or "")).expanduser()
    if not str(candidate).strip():
        return candidate
    if candidate.is_absolute():
        return candidate.resolve()
    return (runtime_base / candidate).resolve()


def default_face_model_config(*, runtime_base: str | Path | None = None) -> FaceEngineModelConfig:
    return FaceEngineModelConfig.default(runtime_base=runtime_base)


def validate_face_model_config(config: FaceEngineModelConfig | None = None, *, runtime_base: str | Path | None = None) -> dict[str, Any]:
    resolved = (config or FaceEngineModelConfig.default(runtime_base=runtime_base)).resolved(runtime_base=runtime_base)
    return resolved.validate()


@dataclass(frozen=True)
class FaceBox:
    x: float
    y: float
    width: float
    height: float
    confidence: float = 1.0
    landmarks: tuple[float, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FaceBox":
        landmarks_payload = payload.get("landmarks", ())
        if landmarks_payload is None:
            landmarks_payload = ()
        return cls(
            x=float(payload.get("x", payload.get("left", 0.0)) or 0.0),
            y=float(payload.get("y", payload.get("top", 0.0)) or 0.0),
            width=float(payload.get("width", payload.get("w", 0.0)) or 0.0),
            height=float(payload.get("height", payload.get("h", 0.0)) or 0.0),
            confidence=float(payload.get("confidence", payload.get("score", 1.0)) or 0.0),
            landmarks=tuple(float(value) for value in landmarks_payload),
        )

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)


class FaceEmbeddingEngine(Protocol):
    model_id: str

    def detect_faces(self, frame: np.ndarray) -> Sequence[FaceBox | Mapping[str, Any]]:
        ...

    def extract_embedding(self, frame: np.ndarray, face: FaceBox) -> Sequence[float] | np.ndarray:
        ...


def normalize_embedding(vector: Sequence[float] | np.ndarray) -> np.ndarray:
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        raise FaceQualityError("empty_embedding")
    if not np.all(np.isfinite(arr)):
        raise FaceQualityError("non_finite_embedding")
    norm = float(np.linalg.norm(arr))
    if norm <= 0.0 or math.isnan(norm):
        raise FaceQualityError("zero_embedding")
    return (arr / norm).astype(np.float32)


def embedding_to_base64(vector: Sequence[float] | np.ndarray) -> str:
    arr = normalize_embedding(vector).astype(np.float32)
    return base64.b64encode(arr.tobytes()).decode("ascii")


def embedding_from_base64(payload: str, *, expected_dimension: int | None = None) -> np.ndarray:
    try:
        raw = base64.b64decode(str(payload or ""), validate=True)
    except Exception as exc:
        raise FaceQualityError("invalid_template_encoding") from exc
    if len(raw) % np.dtype(np.float32).itemsize:
        raise FaceQualityError("invalid_template_size")
    arr = np.frombuffer(raw, dtype=np.float32).copy()
    if expected_dimension is not None and int(expected_dimension) != int(arr.size):
        raise FaceQualityError("template_dimension_mismatch")
    return normalize_embedding(arr)


def embedding_digest(vector: Sequence[float] | np.ndarray) -> str:
    arr = normalize_embedding(vector).astype(np.float32)
    return hashlib.sha256(arr.tobytes()).hexdigest()


def _as_frame_array(frame: Any) -> np.ndarray:
    if frame is None:
        raise FaceBackendUnavailable("camera_unavailable")
    arr = np.asarray(frame)
    if arr.size == 0 or arr.ndim not in {2, 3}:
        raise FaceQualityError("invalid_frame")
    if not np.all(np.isfinite(arr.astype(np.float32, copy=False))):
        raise FaceQualityError("invalid_frame_values")
    return arr


def _face_boxes(raw_faces: Sequence[FaceBox | Mapping[str, Any]]) -> List[FaceBox]:
    boxes: List[FaceBox] = []
    for face in raw_faces:
        if isinstance(face, FaceBox):
            boxes.append(face)
        elif isinstance(face, Mapping):
            boxes.append(FaceBox.from_mapping(face))
        else:
            raise FaceQualityError("invalid_face_detection")
    return boxes


def _quality_score(frame: np.ndarray, face: FaceBox) -> float:
    # Do not log or persist frames. This score is deliberately coarse and only
    # used as an in-memory quality filter.
    arr = frame.astype(np.float32, copy=False)
    contrast = float(np.std(arr)) / 255.0 if arr.size else 0.0
    size_score = min(1.0, max(0.0, min(face.width, face.height) / float(DEFAULT_MIN_FACE_SIZE * 2)))
    confidence = min(1.0, max(0.0, face.confidence))
    return max(0.0, min(1.0, (contrast * 0.4) + (size_score * 0.4) + (confidence * 0.2)))


def select_single_quality_face(frame: Any, engine: FaceEmbeddingEngine) -> tuple[np.ndarray, FaceBox, float]:
    arr = _as_frame_array(frame)
    raw = engine.detect_faces(arr)
    boxes = _face_boxes(raw)
    if not boxes:
        raise FaceQualityError("no_face")
    if len(boxes) > 1:
        raise FaceQualityError("multiple_faces")
    face = boxes[0]
    if min(face.width, face.height) < DEFAULT_MIN_FACE_SIZE:
        raise FaceQualityError("low_quality_face_too_small")
    score = _quality_score(arr, face)
    if score < DEFAULT_MIN_QUALITY_SCORE:
        raise FaceQualityError("low_quality_face")
    return arr, face, score


def extract_quality_embedding(frame: Any, engine: FaceEmbeddingEngine) -> tuple[np.ndarray, float]:
    arr, face, score = select_single_quality_face(frame, engine)
    return normalize_embedding(engine.extract_embedding(arr, face)), score


def build_enrollment_template(
    frames: Iterable[Any],
    engine: FaceEmbeddingEngine,
    *,
    min_samples: int = DEFAULT_MIN_SAMPLE_COUNT,
    model_id: str | None = None,
) -> dict[str, Any]:
    embeddings: List[np.ndarray] = []
    qualities: List[float] = []
    rejection_reasons: List[str] = []
    for frame in frames:
        try:
            embedding, quality = extract_quality_embedding(frame, engine)
            embeddings.append(embedding)
            qualities.append(float(quality))
        except FaceBiometricsError as exc:
            rejection_reasons.append(str(exc))
    if len(embeddings) < int(min_samples):
        raise FaceEnrollmentQualityError("insufficient_quality_samples", rejection_reasons=rejection_reasons)
    average = normalize_embedding(np.mean(np.vstack(embeddings), axis=0))
    return {
        "schema_version": FACE_TEMPLATE_SCHEMA_VERSION,
        "kind": FACE_TEMPLATE_KIND,
        "embedding_model_id": str(model_id or getattr(engine, "model_id", DEFAULT_FACE_MODEL_ID)),
        "embedding_dimension": int(average.size),
        "embedding": embedding_to_base64(average),
        "template_digest": embedding_digest(average),
        "sample_count": int(len(embeddings)),
        "quality_score": round(float(np.mean(qualities)) if qualities else 0.0, 6),
        "rejected_sample_count": int(len(rejection_reasons)),
    }


def cosine_similarity(left: Sequence[float] | np.ndarray, right: Sequence[float] | np.ndarray) -> float:
    a = normalize_embedding(left)
    b = normalize_embedding(right)
    if a.size != b.size:
        raise FaceQualityError("embedding_dimension_mismatch")
    return float(np.dot(a, b))


def verify_embedding(
    probe_embedding: Sequence[float] | np.ndarray,
    stored_embedding: Sequence[float] | np.ndarray,
    *,
    threshold: float = DEFAULT_VERIFY_THRESHOLD,
) -> dict[str, Any]:
    score = cosine_similarity(probe_embedding, stored_embedding)
    return {
        "verified": bool(score >= float(threshold)),
        "score": round(score, 6),
        "threshold": float(threshold),
    }


def verify_frame_against_template(
    frame: Any,
    template_payload: Mapping[str, Any],
    engine: FaceEmbeddingEngine,
    *,
    threshold: float = DEFAULT_VERIFY_THRESHOLD,
) -> dict[str, Any]:
    probe, quality = extract_quality_embedding(frame, engine)
    stored = embedding_from_base64(
        str(template_payload.get("embedding") or ""),
        expected_dimension=int(template_payload.get("embedding_dimension") or probe.size),
    )
    result = verify_embedding(probe, stored, threshold=threshold)
    result.update({"status": "verified" if result["verified"] else "not_verified", "quality_score": round(float(quality), 6)})
    return result


class OpenCVFaceEngine:
    """Optional OpenCV adapter.

    The project does not require OpenCV at import time.  H7 makes the YuNet/SFace
    model paths explicit and safe: defaults resolve under ``models/face`` and
    missing or invalid model files fail closed before any OpenCV object is
    created.
    """

    model_id = DEFAULT_FACE_MODEL_ID

    def __init__(
        self,
        *,
        detector_model_path: str | Path | None = None,
        recognizer_model_path: str | Path | None = None,
        model_config: FaceEngineModelConfig | None = None,
        runtime_base: str | Path | None = None,
        cv2_module: Any | None = None,
    ) -> None:
        if model_config is None:
            if detector_model_path is not None or recognizer_model_path is not None:
                model_config = FaceEngineModelConfig(
                    detector_model_path=str(detector_model_path or ""),
                    recognizer_model_path=str(recognizer_model_path or ""),
                    model_id=DEFAULT_FACE_MODEL_ID,
                )
            else:
                model_config = FaceEngineModelConfig.default(runtime_base=runtime_base)
        resolved_config = model_config.resolved(runtime_base=runtime_base)
        model_status = resolved_config.validate()
        if not bool(model_status.get("ok", False)):
            raise FaceBackendUnavailable(str(model_status.get("reason") or FACE_MODELS_INVALID))

        if cv2_module is None:
            try:
                import cv2  # type: ignore
            except Exception as exc:
                raise FaceBackendUnavailable("opencv_unavailable") from exc
        else:
            cv2 = cv2_module
        self.cv2 = cv2
        self.model_config = resolved_config
        self.model_id = str(resolved_config.model_id or DEFAULT_FACE_MODEL_ID)
        self.detector_model_path = resolved_config.detector_model_path
        self.recognizer_model_path = resolved_config.recognizer_model_path
        if not hasattr(cv2, "FaceDetectorYN") or not hasattr(cv2, "FaceRecognizerSF"):
            raise FaceBackendUnavailable("opencv_face_api_unavailable")
        try:
            self.detector = cv2.FaceDetectorYN.create(self.detector_model_path, "", (320, 320))
            self.recognizer = cv2.FaceRecognizerSF.create(self.recognizer_model_path, "")
        except Exception as exc:
            raise FaceBackendUnavailable(FACE_MODELS_INVALID) from exc

    def detect_faces(self, frame: np.ndarray) -> Sequence[FaceBox]:
        h, w = frame.shape[:2]
        self.detector.setInputSize((int(w), int(h)))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return []
        boxes: List[FaceBox] = []
        for row in faces:
            values = np.asarray(row, dtype=np.float32).reshape(-1)
            if values.size < 15:
                raise FaceQualityError("invalid_face_detection")
            landmarks = tuple(float(value) for value in values[4:14])
            confidence = float(values[14])
            boxes.append(
                FaceBox(
                    x=float(values[0]),
                    y=float(values[1]),
                    width=float(values[2]),
                    height=float(values[3]),
                    confidence=confidence,
                    landmarks=landmarks,
                )
            )
        return boxes

    def extract_embedding(self, frame: np.ndarray, face: FaceBox) -> np.ndarray:
        landmarks = tuple(float(value) for value in getattr(face, "landmarks", ()) or ())
        if len(landmarks) != 10 or not np.all(np.isfinite(np.asarray(landmarks, dtype=np.float32))):
            raise FaceQualityError("invalid_face_geometry")
        face_values = [
            float(face.x),
            float(face.y),
            float(face.width),
            float(face.height),
            *landmarks,
            float(face.confidence),
        ]
        face_row = np.asarray(face_values, dtype=np.float32)
        if face_row.size != 15 or not np.all(np.isfinite(face_row)):
            raise FaceQualityError("invalid_face_geometry")
        aligned = self.recognizer.alignCrop(frame, face_row)
        return np.asarray(self.recognizer.feature(aligned), dtype=np.float32).reshape(-1)
