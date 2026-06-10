from __future__ import annotations

"""Backend-owned webcam capture provider for BioAuth face confirmation.

Hotfix H6 adds only the capture abstraction.  It intentionally does not wire
camera frames into enrollment, verification, lock suppression, or QML.  Captured
frames are returned in memory to the caller and are never written to disk by this
module.
"""

import importlib
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence

import numpy as np

LOGGER = logging.getLogger(__name__)

CAMERA_STATUS_CAPTURED = "captured"
CAMERA_STATUS_CAMERA_READY = "camera_ready"
CAMERA_STATUS_CAMERA_UNAVAILABLE = "camera_unavailable"
CAMERA_STATUS_OPENCV_UNAVAILABLE = "opencv_unavailable"
CAMERA_STATUS_DEVICE_OPEN_FAILED = "device_open_failed"
CAMERA_STATUS_NO_FRAME_CAPTURED = "no_frame_captured"
CAMERA_STATUS_CAPTURE_TIMEOUT = "capture_timeout"
CAMERA_STATUS_INVALID_REQUEST = "invalid_request"

_AUTO_CV2 = object()


@dataclass(frozen=True)
class CameraCaptureResult:
    """Small, privacy-safe capture result.

    `frames` intentionally has `repr=False` so accidental logging of the result
    does not dump image arrays.  Use `to_safe_dict()` for UI/status surfaces; it
    omits raw frame objects entirely.
    """

    status: str
    ok: bool = False
    reason: str = ""
    frames: tuple[np.ndarray, ...] = field(default_factory=tuple, repr=False)
    raw_images_stored: bool = False
    backend_camera_index: int = 0
    selected_index: int = 0
    working_index: int = 0
    backend: str = ""
    backend_tried: str = ""
    camera_opened: bool = False
    camera_unavailable: bool = False
    cv2_import_ok: bool = False
    first_frame_ok: bool = False
    warmup_frames_read: int = 0
    capture_attempts: int = 0
    frame_read_ok: bool = False
    frame_shape: tuple[int, ...] = ()
    elapsed_ms: int = 0
    camera_open_elapsed_ms: int = 0
    first_frame_elapsed_ms: int = 0
    failure_reason: str = ""

    @property
    def frame(self) -> np.ndarray | None:
        return self.frames[0] if self.frames else None

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def to_safe_dict(self) -> dict[str, Any]:
        """Return only non-biometric metadata for logs, QML, and tests."""

        return {
            "status": str(self.status),
            "ok": bool(self.ok),
            "reason": str(self.reason or self.status),
            "frame_count": int(len(self.frames)),
            "raw_images_stored": False,
            "backend_camera_index": int(self.backend_camera_index),
            "selected_index": int(self.selected_index),
            "working_index": int(self.working_index),
            "backend": str(self.backend),
            "backend_tried": str(self.backend_tried),
            "camera_opened": bool(self.camera_opened),
            "camera_unavailable": bool(self.camera_unavailable),
            "cv2_import_ok": bool(self.cv2_import_ok),
            "first_frame_ok": bool(self.first_frame_ok),
            "warmup_frames_read": int(self.warmup_frames_read),
            "capture_attempts": int(self.capture_attempts),
            "frame_read_ok": bool(self.frame_read_ok),
            "frame_shape": tuple(int(part) for part in self.frame_shape),
            "elapsed_ms": int(self.elapsed_ms),
            "camera_open_elapsed_ms": int(self.camera_open_elapsed_ms),
            "first_frame_elapsed_ms": int(self.first_frame_elapsed_ms),
            "failure_reason": str(self.failure_reason),
        }


class CameraProvider(Protocol):
    """Backend-owned camera provider contract."""

    def availability_status(self, read_first_frame: bool = True) -> CameraCaptureResult:
        ...

    def capture_enrollment_frames(self, count: int) -> CameraCaptureResult:
        ...

    def capture_verification_frame(self) -> CameraCaptureResult:
        ...

    def capture_verification_frames(self, count: int) -> CameraCaptureResult:
        ...


class NullCameraProvider:
    """Fail-closed provider for builds without camera support."""

    def __init__(self, *, status: str = CAMERA_STATUS_CAMERA_UNAVAILABLE, reason: str | None = None) -> None:
        self.status = str(status or CAMERA_STATUS_CAMERA_UNAVAILABLE)
        self.reason = str(reason or self.status)

    def availability_status(self, read_first_frame: bool = True) -> CameraCaptureResult:
        return self._unavailable_result()

    def capture_enrollment_frames(self, count: int) -> CameraCaptureResult:
        return self._unavailable_result()

    def capture_verification_frame(self) -> CameraCaptureResult:
        return self._unavailable_result()

    def capture_verification_frames(self, count: int) -> CameraCaptureResult:
        return self._unavailable_result()

    def _unavailable_result(self) -> CameraCaptureResult:
        LOGGER.info("BioAuth face camera provider unavailable: %s", self.reason)
        return CameraCaptureResult(status=self.status, ok=False, reason=self.reason)


class OpenCVCameraProvider:
    """OpenCV webcam capture provider.

    OpenCV is optional and imported lazily.  Missing OpenCV, camera permission
    errors, unavailable devices, empty reads, and timeouts all return fail-closed
    `CameraCaptureResult` objects instead of raising into the app.
    """

    def __init__(
        self,
        *,
        device_index: int = 0,
        timeout_sec: float = 3.0,
        read_interval_sec: float = 0.05,
        warmup_frames: int = 10,
        cv2_module: Any = _AUTO_CV2,
        capture_factory: Callable[[int], Any] | None = None,
    ) -> None:
        self.device_index = _coerce_camera_index(device_index)
        self.timeout_sec = max(0.05, float(timeout_sec))
        self.read_interval_sec = max(0.0, float(read_interval_sec))
        try:
            requested_warmup = int(warmup_frames)
        except Exception:
            requested_warmup = 10
        self.warmup_frames = max(0, min(30, requested_warmup))
        self._cv2_module = cv2_module
        self._capture_factory = capture_factory

    def capture_enrollment_frames(self, count: int) -> CameraCaptureResult:
        try:
            requested = int(count)
        except Exception:
            return _failed(CAMERA_STATUS_INVALID_REQUEST, "invalid_count")
        if requested <= 0:
            return _failed(CAMERA_STATUS_INVALID_REQUEST, "invalid_count")
        return self._capture_frames(requested)

    def capture_verification_frame(self) -> CameraCaptureResult:
        return self._capture_frames(1)

    def capture_verification_frames(self, count: int) -> CameraCaptureResult:
        try:
            requested = int(count)
        except Exception:
            return _failed(CAMERA_STATUS_INVALID_REQUEST, "invalid_count")
        if requested <= 0:
            return _failed(CAMERA_STATUS_INVALID_REQUEST, "invalid_count")
        # Verification uses several full camera frames to reduce intermittent
        # no-face captures.  The backend face engine still evaluates each full
        # frame and no raw images are persisted.
        return self._capture_frames(requested)

    def availability_status(self, read_first_frame: bool = True) -> CameraCaptureResult:
        """Check backend camera availability without returning or persisting frames."""

        started = time.monotonic()
        capture, failed = self._open_capture()
        open_diag = dict(getattr(self, "_last_open_diagnostics", {}) or {})
        if failed is not None:
            return failed
        first_frame_ok = False
        first_shape: tuple[int, ...] = ()
        first_frame_elapsed_ms = 0
        try:
            if read_first_frame:
                frame_start = time.monotonic()
                try:
                    ok, frame = capture.read()
                except Exception:
                    ok, frame = False, None
                first_frame_elapsed_ms = int((time.monotonic() - frame_start) * 1000)
                first_frame_ok = bool(ok) and _is_valid_frame(frame)
                if first_frame_ok:
                    first_shape = _safe_frame_shape(frame)
                else:
                    LOGGER.warning("BioAuth face camera availability check failed: first frame unavailable")
                    return _failed(
                        CAMERA_STATUS_NO_FRAME_CAPTURED,
                        "first_frame_failed",
                        backend_camera_index=self.device_index,
                        selected_index=self.device_index,
                        working_index=int(open_diag.get("working_index", self.device_index) or self.device_index),
                        backend=str(open_diag.get("backend") or ""),
                        backend_tried=str(open_diag.get("backend_tried") or ""),
                        camera_opened=True,
                        camera_unavailable=True,
                        cv2_import_ok=True,
                        first_frame_ok=False,
                        frame_read_ok=False,
                        frame_shape=(),
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        camera_open_elapsed_ms=int(open_diag.get("camera_open_elapsed_ms", 0) or 0),
                        first_frame_elapsed_ms=first_frame_elapsed_ms,
                        failure_reason="first_frame_failed",
                    )
            return CameraCaptureResult(
                status=CAMERA_STATUS_CAMERA_READY,
                ok=True,
                reason=CAMERA_STATUS_CAMERA_READY,
                backend_camera_index=self.device_index,
                selected_index=self.device_index,
                working_index=int(open_diag.get("working_index", self.device_index) or self.device_index),
                backend=str(open_diag.get("backend") or ""),
                backend_tried=str(open_diag.get("backend_tried") or ""),
                camera_opened=True,
                camera_unavailable=False,
                cv2_import_ok=True,
                first_frame_ok=first_frame_ok if read_first_frame else True,
                frame_read_ok=first_frame_ok if read_first_frame else True,
                frame_shape=first_shape,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                camera_open_elapsed_ms=int(open_diag.get("camera_open_elapsed_ms", 0) or 0),
                first_frame_elapsed_ms=first_frame_elapsed_ms,
            )
        finally:
            _release_capture(capture)

    def _load_cv2(self) -> Any:
        if self._cv2_module is _AUTO_CV2:
            try:
                return importlib.import_module("cv2")
            except Exception as exc:
                raise RuntimeError(CAMERA_STATUS_OPENCV_UNAVAILABLE) from exc
        if self._cv2_module is None:
            raise RuntimeError(CAMERA_STATUS_OPENCV_UNAVAILABLE)
        return self._cv2_module

    def _open_capture(self) -> tuple[Any | None, CameraCaptureResult | None]:
        started = time.monotonic()
        self._last_open_diagnostics = {}
        try:
            cv2 = self._load_cv2()
        except RuntimeError:
            LOGGER.info("BioAuth face camera capture unavailable: OpenCV is not installed")
            return None, _failed(
                CAMERA_STATUS_OPENCV_UNAVAILABLE,
                CAMERA_STATUS_OPENCV_UNAVAILABLE,
                backend_camera_index=self.device_index,
                selected_index=self.device_index,
                working_index=0,
                backend="",
                backend_tried="",
                camera_unavailable=True,
                cv2_import_ok=False,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                failure_reason=CAMERA_STATUS_OPENCV_UNAVAILABLE,
            )
        candidates = [("CUSTOM", None)] if self._capture_factory else _opencv_backend_candidates(cv2)
        tried: list[str] = []
        last_failure_reason = "permission_or_device_open_failure"
        for backend_name, backend_flag in candidates:
            tried.append(str(backend_name))
            open_started = time.monotonic()
            capture = None
            try:
                if self._capture_factory:
                    capture = self._capture_factory(self.device_index)
                elif backend_flag is None:
                    capture = cv2.VideoCapture(self.device_index)
                else:
                    capture = cv2.VideoCapture(self.device_index, backend_flag)
            except Exception:
                last_failure_reason = "permission_or_device_open_failure"
                LOGGER.warning("BioAuth face camera capture failed: device could not be opened using %s", backend_name)
                continue
            camera_open_elapsed_ms = int((time.monotonic() - open_started) * 1000)
            try:
                opened = bool(capture.isOpened()) if hasattr(capture, "isOpened") else True
            except Exception:
                opened = False
            if opened:
                self._last_open_diagnostics = {
                    "backend": str(backend_name),
                    "backend_tried": ",".join(tried),
                    "working_index": int(self.device_index),
                    "camera_open_elapsed_ms": camera_open_elapsed_ms,
                }
                return capture, None
            _release_capture(capture)
            last_failure_reason = "permission_or_device_open_failure"
        LOGGER.warning("BioAuth face camera capture unavailable: permission or device open failure")
        return None, _failed(
            CAMERA_STATUS_DEVICE_OPEN_FAILED,
            last_failure_reason,
            backend_camera_index=self.device_index,
            selected_index=self.device_index,
            working_index=0,
            backend="",
            backend_tried=",".join(tried),
            camera_unavailable=True,
            cv2_import_ok=True,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            failure_reason=last_failure_reason,
        )

    def _capture_frames(self, count: int) -> CameraCaptureResult:
        capture, failed = self._open_capture()
        if failed is not None:
            return failed
        if capture is None:
            return _failed(CAMERA_STATUS_CAMERA_UNAVAILABLE, CAMERA_STATUS_CAMERA_UNAVAILABLE, backend_camera_index=self.device_index, camera_unavailable=True)

        deadline = time.monotonic() + self.timeout_sec
        frames: list[np.ndarray] = []
        reads_attempted = 0
        warmup_read_count = 0
        frame_read_ok = False
        last_frame_shape: tuple[int, ...] = ()
        try:
            warmup_read_count, frame_read_ok, last_frame_shape = self._discard_warmup_frames(capture, deadline)
            while len(frames) < int(count):
                if time.monotonic() >= deadline:
                    break
                reads_attempted += 1
                try:
                    ok, frame = capture.read()
                except Exception:
                    LOGGER.warning("BioAuth face camera capture failed while reading frame")
                    return _failed(
                        CAMERA_STATUS_NO_FRAME_CAPTURED,
                        CAMERA_STATUS_NO_FRAME_CAPTURED,
                        backend_camera_index=self.device_index,
                        camera_opened=True,
                        warmup_frames_read=warmup_read_count,
                        capture_attempts=reads_attempted,
                        frame_read_ok=False,
                        frame_shape=last_frame_shape,
                    )
                frame_read_ok = bool(ok)
                if ok and _is_valid_frame(frame):
                    arr = np.asarray(frame)
                    last_frame_shape = _safe_frame_shape(arr)
                    # Keep only an in-memory copy.  The provider never writes raw
                    # frames to disk and never logs frame contents.
                    frames.append(arr.copy())
                if len(frames) >= int(count):
                    break
                if self.read_interval_sec:
                    time.sleep(min(self.read_interval_sec, max(0.0, deadline - time.monotonic())))
        finally:
            _release_capture(capture)

        open_diag = dict(getattr(self, "_last_open_diagnostics", {}) or {})
        diagnostics = {
            "backend_camera_index": self.device_index,
            "selected_index": self.device_index,
            "working_index": int(open_diag.get("working_index", self.device_index) or self.device_index),
            "backend": str(open_diag.get("backend") or ""),
            "backend_tried": str(open_diag.get("backend_tried") or ""),
            "cv2_import_ok": True,
            "first_frame_ok": bool(frame_read_ok),
            "camera_open_elapsed_ms": int(open_diag.get("camera_open_elapsed_ms", 0) or 0),
            "camera_opened": True,
            "warmup_frames_read": warmup_read_count,
            "capture_attempts": reads_attempted,
            "frame_read_ok": frame_read_ok,
            "frame_shape": last_frame_shape,
        }
        if len(frames) == int(count):
            return CameraCaptureResult(
                status=CAMERA_STATUS_CAPTURED,
                ok=True,
                reason=CAMERA_STATUS_CAPTURED,
                frames=tuple(frames),
                raw_images_stored=False,
                **diagnostics,
            )
        # Fail closed: partial captures are not returned to callers because they
        # are not sufficient for the requested biometric operation.
        if frames:
            LOGGER.warning("BioAuth face camera capture timed out before collecting requested frames")
            return _failed(CAMERA_STATUS_CAPTURE_TIMEOUT, CAMERA_STATUS_CAPTURE_TIMEOUT, **diagnostics)
        if reads_attempted:
            LOGGER.warning("BioAuth face camera capture read no usable frames")
            return _failed(CAMERA_STATUS_NO_FRAME_CAPTURED, CAMERA_STATUS_NO_FRAME_CAPTURED, **diagnostics)
        LOGGER.warning("BioAuth face camera capture timed out before any frame was read")
        return _failed(CAMERA_STATUS_CAPTURE_TIMEOUT, CAMERA_STATUS_CAPTURE_TIMEOUT, **diagnostics)

    def _discard_warmup_frames(self, capture: Any, deadline: float) -> tuple[int, bool, tuple[int, ...]]:
        warmup_read_count = 0
        frame_read_ok = False
        last_frame_shape: tuple[int, ...] = ()
        while warmup_read_count < self.warmup_frames and time.monotonic() < deadline:
            try:
                ok, frame = capture.read()
            except Exception:
                break
            frame_read_ok = bool(ok)
            if ok:
                warmup_read_count += 1
                if _is_valid_frame(frame):
                    last_frame_shape = _safe_frame_shape(frame)
            if self.read_interval_sec:
                time.sleep(min(self.read_interval_sec, max(0.0, deadline - time.monotonic())))
        return warmup_read_count, frame_read_ok, last_frame_shape


def _opencv_backend_candidates(cv2: Any) -> list[tuple[str, Any | None]]:
    if sys.platform.startswith("win"):
        return [
            ("CAP_DSHOW", getattr(cv2, "CAP_DSHOW", None)),
            ("CAP_MSMF", getattr(cv2, "CAP_MSMF", None)),
            ("DEFAULT", None),
        ]
    return [("DEFAULT", None)]


def build_default_camera_provider(*, device_index: int | None = None, warmup_frames: int = 10, timeout_sec: float | None = None) -> CameraProvider:
    """Return the default backend provider without opening the camera yet."""

    if device_index is None:
        device_index = _settings_camera_index()
    kwargs: dict[str, Any] = {"device_index": device_index, "warmup_frames": warmup_frames}
    if timeout_sec is not None:
        try:
            kwargs["timeout_sec"] = max(0.1, float(timeout_sec))
        except Exception:
            pass
    return OpenCVCameraProvider(**kwargs)


def _failed(status: str, reason: str, **diagnostics: Any) -> CameraCaptureResult:
    return CameraCaptureResult(status=str(status), ok=False, reason=str(reason or status), frames=(), raw_images_stored=False, **_safe_diagnostics(diagnostics))


def _is_valid_frame(frame: Any) -> bool:
    if frame is None:
        return False
    try:
        arr = np.asarray(frame)
    except Exception:
        return False
    return bool(arr.size and arr.ndim in {2, 3})


def _safe_frame_shape(frame: Any) -> tuple[int, ...]:
    try:
        arr = np.asarray(frame)
    except Exception:
        return ()
    if arr.ndim not in {2, 3}:
        return ()
    return tuple(int(part) for part in arr.shape)


def _coerce_camera_index(value: Any, *, default: int = 0, minimum: int = 0, maximum: int = 4) -> int:
    try:
        index = int(value)
    except Exception:
        index = int(default)
    return max(int(minimum), min(int(maximum), index))


def _settings_camera_index() -> int:
    try:
        from app_settings import load_settings

        settings = load_settings()
        return _coerce_camera_index(settings.get("backend_face_camera_index", 0))
    except Exception:
        return 0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "backend_camera_index": _coerce_camera_index(diagnostics.get("backend_camera_index", 0)),
        "selected_index": _coerce_camera_index(diagnostics.get("selected_index", diagnostics.get("backend_camera_index", 0))),
        "working_index": max(0, _safe_int(diagnostics.get("working_index", 0), 0)),
        "backend": str(diagnostics.get("backend") or "")[:48],
        "backend_tried": str(diagnostics.get("backend_tried") or "")[:96],
        "camera_opened": bool(diagnostics.get("camera_opened", False)),
        "camera_unavailable": bool(diagnostics.get("camera_unavailable", False)),
        "cv2_import_ok": bool(diagnostics.get("cv2_import_ok", False)),
        "first_frame_ok": bool(diagnostics.get("first_frame_ok", False)),
        "warmup_frames_read": max(0, _safe_int(diagnostics.get("warmup_frames_read", 0), 0)),
        "capture_attempts": max(0, _safe_int(diagnostics.get("capture_attempts", 0), 0)),
        "frame_read_ok": bool(diagnostics.get("frame_read_ok", False)),
        "frame_shape": tuple(int(part) for part in diagnostics.get("frame_shape", ()) or ()),
        "elapsed_ms": max(0, _safe_int(diagnostics.get("elapsed_ms", 0), 0)),
        "camera_open_elapsed_ms": max(0, _safe_int(diagnostics.get("camera_open_elapsed_ms", 0), 0)),
        "first_frame_elapsed_ms": max(0, _safe_int(diagnostics.get("first_frame_elapsed_ms", 0), 0)),
        "failure_reason": str(diagnostics.get("failure_reason") or "")[:96],
    }


def _release_capture(capture: Any) -> None:
    try:
        if capture is not None and hasattr(capture, "release"):
            capture.release()
    except Exception:
        LOGGER.warning("BioAuth face camera capture release failed")


__all__ = [
    "CAMERA_STATUS_CAMERA_UNAVAILABLE",
    "CAMERA_STATUS_CAPTURE_TIMEOUT",
    "CAMERA_STATUS_CAPTURED",
    "CAMERA_STATUS_CAMERA_READY",
    "CAMERA_STATUS_DEVICE_OPEN_FAILED",
    "CAMERA_STATUS_INVALID_REQUEST",
    "CAMERA_STATUS_NO_FRAME_CAPTURED",
    "CAMERA_STATUS_OPENCV_UNAVAILABLE",
    "CameraCaptureResult",
    "CameraProvider",
    "NullCameraProvider",
    "OpenCVCameraProvider",
    "build_default_camera_provider",
]
