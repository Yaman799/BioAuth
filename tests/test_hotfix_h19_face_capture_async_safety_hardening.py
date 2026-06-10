from __future__ import annotations

import math
from pathlib import Path

import numpy as np

import app_settings
import face_biometrics
from tests.test_hotfix_h8_real_face_enrollment_wiring import (
    DummyBridge,
    FakeCameraProvider,
    FakeCaptureResult,
    FakeFaceService,
    SettingsMixin,
)

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_MIXIN = ROOT / "bridge" / "settings_mixin.py"
FACE_DIALOG = ROOT / "qml" / "dialogs" / "FaceEnrollmentDialog.qml"
FACE_PAGE = ROOT / "qml" / "pages" / "user" / "UserFaceConfirmationPage.qml"


class _FakeSignal:
    def __init__(self) -> None:
        self._callback = None

    def connect(self, callback):
        self._callback = callback

    def emit(self, payload):
        assert self._callback is not None
        self._callback(payload)


class _FakeSignals:
    def __init__(self) -> None:
        self.finished = _FakeSignal()


class _FakeWorker:
    def __init__(self, task):
        self.task = task
        self.signals = _FakeSignals()


class _FakeThreadPool:
    started: list[_FakeWorker] = []

    @classmethod
    def globalInstance(cls):
        return cls

    @classmethod
    def start(cls, worker):
        cls.started.append(worker)


class _FakeCoreApplication:
    @staticmethod
    def instance():
        return object()


def test_h19_thresholds_and_default_enrollment_count_are_hardened() -> None:
    assert face_biometrics.DEFAULT_VERIFY_THRESHOLD >= 0.55
    assert face_biometrics.DEFAULT_MIN_QUALITY_SCORE >= 0.25
    assert app_settings.DEFAULT_SETTINGS["face_enrollment_frame_count"] == 7
    assert app_settings._coerce_settings_payload({})["face_enrollment_frame_count"] == 7
    assert app_settings._coerce_settings_payload({"face_enrollment_frame_count": 99})["face_enrollment_frame_count"] == 7
    assert app_settings._coerce_settings_payload({"face_enrollment_frame_count": 3})["face_enrollment_frame_count"] == 3

    borderline_probe = np.asarray([0.50, math.sqrt(0.75)], dtype=np.float32)
    result = face_biometrics.verify_embedding([1.0, 0.0], borderline_probe)
    assert result["verified"] is False
    assert result["threshold"] >= 0.55


def test_h19_enroll_face_template_queues_capture_off_ui_thread_when_qt_threadpool_available(monkeypatch) -> None:
    frames = tuple(np.full((16, 16, 3), idx, dtype=np.uint8) for idx in range(7))
    provider = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=frames, reason="captured"))
    service = FakeFaceService(result={"status": "enrolled", "ok": True, "sample_count": 7, "raw_images_stored": False})
    bridge = DummyBridge(camera_provider=provider, face_service=service, frame_count=7)
    globals_map = SettingsMixin._face_async_operations_enabled.__globals__
    _FakeThreadPool.started = []
    monkeypatch.setitem(globals_map, "_FaceOperationWorker", _FakeWorker)
    monkeypatch.setitem(globals_map, "_FaceQtThreadPool", _FakeThreadPool)
    monkeypatch.setitem(globals_map, "_FaceQtCoreApplication", _FakeCoreApplication)
    monkeypatch.delenv("BIOAUTH_FACE_OPERATIONS_SYNC", raising=False)

    result = bridge.enrollFaceTemplate()

    assert result["status"] == "capturing"
    assert result["faceOperationInFlight"] is True
    assert provider.requested_counts == []
    assert len(_FakeThreadPool.started) == 1

    worker = _FakeThreadPool.started[0]
    payload = worker.task()
    assert provider.requested_counts == [7]
    worker.signals.finished.emit(payload)

    assert bridge._face_confirmation_operation_state["status"] == "enrolled"
    assert bridge._face_confirmation_operation_state["faceOperationInFlight"] is False
    assert bridge._face_confirmation_operation_state["rawImagesStored"] is False
    assert "frames" not in bridge._face_confirmation_operation_state


def test_h19_settings_mixin_contains_qthreadpool_worker_and_safe_operation_state() -> None:
    source = SETTINGS_MIXIN.read_text(encoding="utf-8")
    assert "QThreadPool" in source
    assert "QRunnable" in source
    assert "_FaceOperationWorker" in source
    assert "_start_face_operation" in source
    assert "faceOperationInFlight" in source
    assert "operation_in_progress" in source
    assert "capture_enrollment_frames" in source
    assert "capture_verification_frame" in source
    assert "_face_runtime_service" in source


def test_h19_qml_uses_backend_inflight_state_and_busy_indicators_without_local_biometric_decisions() -> None:
    dialog = FACE_DIALOG.read_text(encoding="utf-8")
    page = FACE_PAGE.read_text(encoding="utf-8")
    combined = (dialog + "\n" + page).lower()

    assert "BusyIndicator" in dialog
    assert "BusyIndicator" in page
    assert "faceOperationInFlight" in dialog
    assert "faceOperationInFlight" in page
    assert "backend.enrollFaceTemplate()" in dialog
    assert "backend.testFaceConfirmation()" in page
    assert "interval: 420" in dialog
    assert "interval: 420" in page
    assert "faceGuardTimer" in page and "15000" in page

    forbidden = [
        "detectfaces",
        "extractembedding",
        "cosinesimilarity",
        "verify_embedding",
        "score >=",
        "threshold",
        "liveness",
        "antispoof",
        "anti-spoof",
        "face unlock",
        "lock_suppressed",
        "approved_for_production",
        "protectedsessionsavailable",
        "screenshot",
        "grabtoimage",
    ]
    for token in forbidden:
        assert token not in combined, token
