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
    def frame(self):
        return self.frames[0] if self.frames else None

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
        self.verification_calls = 0

    def capture_verification_frame(self) -> FakeCaptureResult:
        self.verification_calls += 1
        return self.result

    def capture_enrollment_frames(self, count: int) -> FakeCaptureResult:  # pragma: no cover - guards wrong path
        raise AssertionError("verification must not use enrollment capture")


class FakeFaceService:
    def __init__(self, *, enrolled: bool = True, result: dict[str, object] | None = None) -> None:
        self.enrolled = enrolled
        self.result = dict(result or {"status": "verified", "ok": True, "verified": True, "score": 0.99})
        self.status_calls: list[str] = []
        self.test_calls: list[dict[str, object]] = []

    def status(self, user_id: str):
        self.status_calls.append(user_id)
        return {"status": "enrolled" if self.enrolled else "not_enrolled", "enrolled": self.enrolled}

    def test_verification(self, user_id: str, frame):
        self.test_calls.append({"user_id": user_id, "frame": frame})
        return dict(self.result)


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
    def __init__(
        self,
        *,
        consent: bool = True,
        face_confirmation_enabled: bool = True,
        feature_enabled: bool = True,
        camera_provider=None,
        face_service=None,
    ) -> None:
        self._current_user = {"user_id": "owner@example.com"}
        self._app_settings = {
            "enable_face_enrollment": True,
            "enable_face_confirmation": feature_enabled,
            "face_confirmation_enabled": face_confirmation_enabled,
            "face_template_consent_granted": consent,
        }
        self._face_confirmation_operation_state = {"status": "idle", "ok": True}
        self._face_confirmation_enabled = face_confirmation_enabled
        self._language = "en"
        self._t = lambda key, **_kwargs: key
        self.faceConfirmationChanged = DummySignal()
        self.statuses: list[tuple[str, str]] = []
        self._face_camera_provider_factory = lambda: camera_provider
        self._identity_confirmation_service_factory = lambda: face_service

    def _set_status(self, message: str, tone: str = "info") -> None:
        self.statuses.append((message, tone))


def test_test_face_confirmation_passes_captured_frame_and_not_none() -> None:
    frame = np.full((16, 16, 3), 7, dtype=np.uint8)
    provider = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(frame,), reason="captured"))
    service = FakeFaceService(enrolled=True)
    bridge = DummyBridge(camera_provider=provider, face_service=service)

    result = bridge.testFaceConfirmation()

    assert result["status"] == "verified"
    assert result["ok"] is True
    assert result["verified"] is True
    assert provider.verification_calls == 1
    assert service.status_calls == ["owner@example.com"]
    assert len(service.test_calls) == 1
    assert service.test_calls[0]["user_id"] == "owner@example.com"
    assert service.test_calls[0]["frame"] is frame
    assert service.test_calls[0]["frame"] is not None
    assert result["lockIntegrationEnabled"] is False
    assert bridge._face_confirmation_operation_state["rawImagesStored"] is False
    assert "frame" not in bridge._face_confirmation_operation_state
    assert "frames" not in bridge._face_confirmation_operation_state


def test_camera_unavailable_fails_closed_without_calling_verification() -> None:
    provider = FakeCameraProvider(FakeCaptureResult(status="device_open_failed", ok=False, frames=(), reason="permission_or_device_open_failure"))
    service = FakeFaceService(enrolled=True)
    bridge = DummyBridge(camera_provider=provider, face_service=service)

    result = bridge.testFaceConfirmation()

    assert result["ok"] is False
    assert result["verified"] is False
    assert result["status"] == "camera_unavailable"
    assert result["captureStatus"] == "device_open_failed"
    assert result["frameCount"] == 0
    assert provider.verification_calls == 1
    assert service.test_calls == []


def test_missing_template_fails_closed_before_camera_capture() -> None:
    frame = np.full((8, 8, 3), 5, dtype=np.uint8)
    provider = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(frame,), reason="captured"))
    service = FakeFaceService(enrolled=False)
    bridge = DummyBridge(camera_provider=provider, face_service=service)

    result = bridge.testFaceConfirmation()

    assert result["status"] == "not_enrolled"
    assert result["ok"] is False
    assert result["verified"] is False
    assert result["rawImagesStored"] is False
    assert result["lockIntegrationEnabled"] is False
    assert "timingDiagnostics" in result
    assert provider.verification_calls == 0
    assert service.status_calls == ["owner@example.com"]
    assert service.test_calls == []


def test_missing_consent_fails_closed_before_service_or_camera() -> None:
    provider = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(object(),), reason="captured"))
    service = FakeFaceService(enrolled=True)
    bridge = DummyBridge(consent=False, camera_provider=provider, face_service=service)

    result = bridge.testFaceConfirmation()

    assert result["status"] == "consent_required"
    assert result["ok"] is False
    assert result["verified"] is False
    assert provider.verification_calls == 0
    assert service.status_calls == []
    assert service.test_calls == []


def test_disabled_face_confirmation_fails_closed_before_service_or_camera() -> None:
    provider = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(object(),), reason="captured"))
    service = FakeFaceService(enrolled=True)
    bridge = DummyBridge(face_confirmation_enabled=False, camera_provider=provider, face_service=service)

    result = bridge.testFaceConfirmation()

    assert result["status"] == "disabled"
    assert result["ok"] is False
    assert result["verified"] is False
    assert provider.verification_calls == 0
    assert service.status_calls == []
    assert service.test_calls == []


def test_model_missing_fails_closed_before_camera_capture() -> None:
    provider = FakeCameraProvider(FakeCaptureResult(status="captured", ok=True, frames=(object(),), reason="captured"))
    factory = RaisingFaceServiceFactory("face_models_missing")
    bridge = DummyBridge(camera_provider=provider, face_service=None)
    bridge._identity_confirmation_service_factory = factory

    result = bridge.testFaceConfirmation()

    assert result["status"] == "face_models_missing"
    assert result["ok"] is False
    assert result["verified"] is False
    assert result["lockIntegrationEnabled"] is False
    assert factory.calls == 1
    assert provider.verification_calls == 0
