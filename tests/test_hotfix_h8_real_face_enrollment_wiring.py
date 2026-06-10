from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass

import numpy as np


class DummySignal:
    def __init__(self) -> None:
        self.count = 0

    def emit(self, *args, **kwargs) -> None:
        self.count += 1


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
        self.requested_counts.append(count)
        return self.result


class FakeFaceService:
    def __init__(self, *, result: dict[str, object] | None = None) -> None:
        self.result = dict(result or {"status": "enrolled", "ok": True, "sample_count": 3, "raw_images_stored": False})
        self.enroll_calls: list[dict[str, object]] = []

    def enroll(self, user_id: str, frames, *, consent_granted: bool):
        captured = tuple(frames)
        self.enroll_calls.append({"user_id": user_id, "frames": captured, "consent_granted": consent_granted})
        return dict(self.result)

    def status(self, user_id: str):
        return {"status": "not_enrolled", "enrolled": False}


class RaisingFaceServiceFactory:
    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise RuntimeError(self.reason)


def _install_settings_mixin_import_stubs() -> dict[str, object | None]:
    names = [
        "app_settings",
        "deep_runtime",
        "license_manager",
        "release_profile",
        "bridge.shared",
        "bridge.settings_mixin",
    ]
    previous = {name: sys.modules.get(name) for name in names}

    app_settings = types.ModuleType("app_settings")
    app_settings.PRIVACY_POLICY_VERSION = "test-policy"
    app_settings.feature_flag_enabled = lambda settings, key: bool((settings or {}).get(key, False))
    app_settings.has_current_face_template_consent = lambda settings: bool((settings or {}).get("face_template_consent_granted", False))
    app_settings.normalize_interface_mode = lambda value: "user" if str(value).lower() == "user" else "developer"
    app_settings.build_evidence_consent_fields = lambda granted=True: {"incident_evidence_consent_granted": bool(granted)}
    app_settings.build_face_template_consent_fields = lambda granted=True: {"face_template_consent_granted": bool(granted)}
    app_settings.build_privacy_consent_fields = lambda: {"privacy_consent_policy_version": "test-policy"}
    sys.modules["app_settings"] = app_settings

    deep_runtime = types.ModuleType("deep_runtime")
    deep_runtime.normalize_benchmark_record = lambda value: value if isinstance(value, dict) else {}
    deep_runtime.normalize_deep_runtime_mode = lambda value, default="auto": str(value or default)
    deep_runtime.normalize_deep_runtime_fallback_reason = lambda value: str(value or "")
    deep_runtime.deep_runtime_fallback_reason_text = lambda value, language="en": str(value or "")
    deep_runtime.deep_runtime_is_fallback = lambda state=None, **kwargs: False
    deep_runtime.resolve_deep_runtime_state = lambda *_args, **_kwargs: {}
    deep_runtime.run_local_device_benchmark = lambda *_args, **_kwargs: {}
    sys.modules["deep_runtime"] = deep_runtime

    license_manager = types.ModuleType("license_manager")
    license_manager.activate_license_code = lambda *_args, **_kwargs: {}
    license_manager.import_license_file = lambda *_args, **_kwargs: {}
    sys.modules["license_manager"] = license_manager

    release_profile = types.ModuleType("release_profile")
    release_profile.current_build_profile = lambda: "test"
    release_profile.current_package_profile = lambda: "source"
    sys.modules["release_profile"] = release_profile

    shared = types.ModuleType("bridge.shared")
    shared.THEMES = {}
    shared.STRINGS = {}
    shared.WELCOME_POLICY_VERSION = "test-welcome"
    shared.ABOUT_US_PATH = "ABOUT_US.md"
    shared.QDesktopServices = object
    shared.QUrl = object
    shared.QTimer = object
    shared.Slot = lambda *args, **kwargs: (lambda func: func)
    shared.complete_user_onboarding = lambda *_args, **_kwargs: None
    shared.is_startup_enabled = lambda: False
    shared.play_button_sound = lambda *_args, **_kwargs: None
    shared.normalize_sensitivity_preset = lambda value: str(value or "balanced").lower()
    shared.save_settings_async = lambda payload: dict(payload)
    shared.set_startup_enabled = lambda *_args, **_kwargs: False
    shared.translate_string = lambda _language, key, **_kwargs: key
    sys.modules["bridge.shared"] = shared
    sys.modules.pop("bridge.settings_mixin", None)
    return previous


def _restore_import_stubs(previous: dict[str, object | None]) -> None:
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _load_settings_mixin_class():
    previous = _install_settings_mixin_import_stubs()
    try:
        module = importlib.import_module("bridge.settings_mixin")
        return module.SettingsMixin
    finally:
        _restore_import_stubs(previous)


SettingsMixin = _load_settings_mixin_class()


class DummyBridge(SettingsMixin):
    def __init__(self, *, consent: bool = True, camera_provider=None, face_service=None, frame_count: int = 3) -> None:
        self._current_user = {"user_id": "owner@example.com"}
        self._app_settings = {
            "enable_face_enrollment": True,
            "enable_face_confirmation": True,
            "face_template_consent_granted": consent,
            "face_enrollment_frame_count": frame_count,
        }
        self._face_confirmation_operation_state = {"status": "idle", "ok": True}
        self._face_confirmation_enabled = False
        self._language = "en"
        self._t = lambda key, **_kwargs: key
        self.faceConfirmationChanged = DummySignal()
        self.statuses: list[tuple[str, str]] = []
        self._face_camera_provider_factory = lambda: camera_provider
        self._identity_confirmation_service_factory = lambda: face_service

    def _set_status(self, message: str, tone: str = "info") -> None:
        self.statuses.append((message, tone))


def test_enroll_face_template_passes_captured_camera_frames_to_face_service() -> None:
    frames = tuple(np.full((16, 16, 3), idx, dtype=np.uint8) for idx in range(3))
    provider = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=frames, reason="captured"))
    service = FakeFaceService()
    bridge = DummyBridge(camera_provider=provider, face_service=service, frame_count=3)

    result = bridge.enrollFaceTemplate()

    assert result["status"] == "enrolled"
    assert result["ok"] is True
    assert provider.requested_counts == [3]
    assert len(service.enroll_calls) == 1
    assert service.enroll_calls[0]["user_id"] == "owner@example.com"
    assert service.enroll_calls[0]["consent_granted"] is True
    assert service.enroll_calls[0]["frames"] == frames
    assert service.enroll_calls[0]["frames"] != ()
    assert bridge._face_confirmation_operation_state["rawImagesStored"] is False
    assert "frames" not in bridge._face_confirmation_operation_state
    assert "template_digest" not in bridge._face_confirmation_operation_state


def test_empty_or_failed_capture_fails_closed_and_does_not_create_template() -> None:
    provider = FakeCameraProvider(FakeCaptureResult(status="no_frame_captured", ok=False, frames=(), reason="no_frame_captured"))
    service = FakeFaceService()
    bridge = DummyBridge(camera_provider=provider, face_service=service, frame_count=3)

    result = bridge.enrollFaceTemplate()

    assert result["ok"] is False
    assert result["status"] == "camera_unavailable"
    assert result["captureStatus"] == "no_frame_captured"
    assert result["frameCount"] == 0
    assert provider.requested_counts == [3]
    assert service.enroll_calls == []
    assert bridge._face_confirmation_operation_state["rawImagesStored"] is False
    assert "frames" not in bridge._face_confirmation_operation_state


def test_missing_consent_fails_closed_before_camera_capture_or_template_creation() -> None:
    provider = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(object(), object(), object())))
    service = FakeFaceService()
    bridge = DummyBridge(consent=False, camera_provider=provider, face_service=service, frame_count=3)

    result = bridge.enrollFaceTemplate()

    assert result == {"status": "consent_required", "ok": False}
    assert provider.requested_counts == []
    assert service.enroll_calls == []
    assert bridge._face_confirmation_operation_state["status"] == "consent_required"


def test_model_missing_fails_closed_before_camera_capture() -> None:
    provider = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(object(), object(), object())))
    factory = RaisingFaceServiceFactory("face_models_missing")
    bridge = DummyBridge(camera_provider=provider, face_service=None, frame_count=3)
    bridge._identity_confirmation_service_factory = factory

    result = bridge.enrollFaceTemplate()

    assert result["ok"] is False
    assert result["status"] == "face_models_missing"
    assert result["reason"] == "face_models_missing"
    assert factory.calls == 1
    assert provider.requested_counts == []


def test_backend_quality_reasons_are_normalized_to_safe_status_tokens() -> None:
    frames = tuple(np.full((16, 16, 3), idx, dtype=np.uint8) for idx in range(3))
    provider = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=frames, reason="captured"))
    service = FakeFaceService(result={"status": "quality_rejected", "ok": False, "reason": "multiple_faces"})
    bridge = DummyBridge(camera_provider=provider, face_service=service, frame_count=3)

    result = bridge.enrollFaceTemplate()

    assert result["status"] == "multiple_faces_detected"
    assert result["reason"] == "multiple_faces"
    assert service.enroll_calls[0]["frames"] == frames
