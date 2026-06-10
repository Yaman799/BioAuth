from __future__ import annotations

from pathlib import Path

import numpy as np

from face_camera_provider import (
    CAMERA_STATUS_CAMERA_UNAVAILABLE,
    CAMERA_STATUS_CAPTURE_TIMEOUT,
    CAMERA_STATUS_CAPTURED,
    CAMERA_STATUS_DEVICE_OPEN_FAILED,
    CAMERA_STATUS_INVALID_REQUEST,
    CAMERA_STATUS_NO_FRAME_CAPTURED,
    CAMERA_STATUS_OPENCV_UNAVAILABLE,
    NullCameraProvider,
    OpenCVCameraProvider,
    build_default_camera_provider,
)


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
            item = self._frames.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return False, None

    def release(self):
        self.released = True


class FakeCV2:
    def __init__(self, capture):
        self.capture = capture

    def VideoCapture(self, device_index):
        self.device_index = device_index
        return self.capture


def _frame(value: int = 7):
    return np.full((4, 4, 3), value, dtype=np.uint8)


def test_null_camera_provider_fails_closed_without_frames():
    provider = NullCameraProvider()

    enrollment = provider.capture_enrollment_frames(3)
    verification = provider.capture_verification_frame()

    assert enrollment.status == CAMERA_STATUS_CAMERA_UNAVAILABLE
    assert enrollment.ok is False
    assert enrollment.frames == ()
    assert enrollment.raw_images_stored is False
    assert verification.status == CAMERA_STATUS_CAMERA_UNAVAILABLE
    assert verification.frame is None


def test_opencv_unavailable_does_not_crash_or_capture_frames():
    provider = OpenCVCameraProvider(cv2_module=None)

    result = provider.capture_verification_frame()

    assert result.status == CAMERA_STATUS_OPENCV_UNAVAILABLE
    assert result.ok is False
    assert result.frames == ()
    assert result.to_safe_dict()["raw_images_stored"] is False


def test_build_default_provider_does_not_open_camera_at_construction():
    provider = build_default_camera_provider()

    assert isinstance(provider, OpenCVCameraProvider)


def test_open_cv_provider_captures_requested_enrollment_frames_in_memory_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(Path(tmp_path).rglob("*"))
    capture = FakeCapture(frames=[(True, _frame(1)), (True, _frame(2)), (True, _frame(3))])
    provider = OpenCVCameraProvider(cv2_module=FakeCV2(capture), timeout_sec=0.25, read_interval_sec=0.0, warmup_frames=0)

    result = provider.capture_enrollment_frames(3)

    after = set(Path(tmp_path).rglob("*"))
    assert result.status == CAMERA_STATUS_CAPTURED
    assert result.ok is True
    assert result.frame_count == 3
    assert all(isinstance(frame, np.ndarray) for frame in result.frames)
    assert result.raw_images_stored is False
    assert capture.released is True
    assert after == before
    assert "frames" not in result.to_safe_dict()


def test_open_cv_provider_captures_one_verification_frame():
    capture = FakeCapture(frames=[(True, _frame(9))])
    provider = OpenCVCameraProvider(cv2_module=FakeCV2(capture), timeout_sec=0.25, read_interval_sec=0.0, warmup_frames=0)

    result = provider.capture_verification_frame()

    assert result.status == CAMERA_STATUS_CAPTURED
    assert result.ok is True
    assert result.frame_count == 1
    assert result.frame is not None
    assert result.to_safe_dict()["frame_count"] == 1


def test_device_open_failure_is_explicit_and_fail_closed():
    capture = FakeCapture(opened=False)
    provider = OpenCVCameraProvider(cv2_module=FakeCV2(capture), timeout_sec=0.25, read_interval_sec=0.0, warmup_frames=0)

    result = provider.capture_verification_frame()

    assert result.status == CAMERA_STATUS_DEVICE_OPEN_FAILED
    assert result.reason == "permission_or_device_open_failure"
    assert result.ok is False
    assert result.frames == ()
    assert capture.released is True


def test_no_frame_captured_is_explicit_and_fail_closed():
    capture = FakeCapture(frames=[(False, None), (True, None), (True, np.array([]))])
    provider = OpenCVCameraProvider(cv2_module=FakeCV2(capture), timeout_sec=0.05, read_interval_sec=0.0, warmup_frames=0)

    result = provider.capture_verification_frame()

    assert result.status == CAMERA_STATUS_NO_FRAME_CAPTURED
    assert result.ok is False
    assert result.frames == ()
    assert capture.released is True


def test_partial_enrollment_capture_times_out_and_does_not_return_partial_frames():
    capture = FakeCapture(frames=[(True, _frame(1))])
    provider = OpenCVCameraProvider(cv2_module=FakeCV2(capture), timeout_sec=0.05, read_interval_sec=0.0, warmup_frames=0)

    result = provider.capture_enrollment_frames(3)

    assert result.status == CAMERA_STATUS_CAPTURE_TIMEOUT
    assert result.ok is False
    assert result.frames == ()
    assert capture.released is True


def test_invalid_enrollment_count_fails_closed():
    capture = FakeCapture(frames=[(True, _frame(1))])
    provider = OpenCVCameraProvider(cv2_module=FakeCV2(capture), timeout_sec=0.25, read_interval_sec=0.0, warmup_frames=0)

    result = provider.capture_enrollment_frames(0)

    assert result.status == CAMERA_STATUS_INVALID_REQUEST
    assert result.ok is False
    assert result.frames == ()
    assert capture.released is False


def test_capture_result_repr_and_safe_dict_do_not_expose_frame_arrays():
    capture = FakeCapture(frames=[(True, _frame(4))])
    provider = OpenCVCameraProvider(cv2_module=FakeCV2(capture), timeout_sec=0.25, read_interval_sec=0.0, warmup_frames=0)

    result = provider.capture_verification_frame()
    safe = result.to_safe_dict()

    assert "array" not in repr(result).lower()
    assert "frame" not in safe or safe["frame_count"] == 1
    assert "frames" not in safe
