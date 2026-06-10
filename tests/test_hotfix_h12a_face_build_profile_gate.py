from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import app_settings


class DummySignal:
    def __init__(self) -> None:
        self.count = 0

    def emit(self, *args, **kwargs) -> None:
        self.count += 1


@dataclass(frozen=True)
class FakeAvailability:
    status: str
    ok: bool
    reason: str = ""

    @property
    def frame_count(self) -> int:
        return 0

    def to_safe_dict(self) -> dict[str, object]:
        return {"status": self.status, "ok": self.ok, "reason": self.reason or self.status, "frame_count": 0}


class FakeCameraProvider:
    def __init__(self, availability: FakeAvailability) -> None:
        self.availability = availability
        self.availability_calls = 0
        self.capture_calls = 0

    def availability_status(self, read_first_frame: bool = True) -> FakeAvailability:
        self.availability_calls += 1
        return self.availability

    def capture_verification_frame(self):  # pragma: no cover - state building must not capture
        self.capture_calls += 1
        raise AssertionError("availability state must not capture frames")

    def capture_enrollment_frames(self, count: int):  # pragma: no cover - state building must not capture
        self.capture_calls += 1
        raise AssertionError("availability state must not capture frames")


class FakeStatusService:
    def __init__(self, *, enrolled: bool) -> None:
        self.enrolled = enrolled
        self.status_calls: list[str] = []

    def status(self, user_id: str) -> dict[str, object]:
        self.status_calls.append(user_id)
        return {"status": "enrolled" if self.enrolled else "not_enrolled", "enrolled": self.enrolled}


def _install_settings_mixin_import_stubs() -> dict[str, object | None]:
    names = ["deep_runtime", "license_manager", "release_profile", "bridge.shared", "bridge.settings_mixin"]
    previous = {name: sys.modules.get(name) for name in names}

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
    release_profile.current_build_profile = lambda: "dev"
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
        flags: bool = True,
        consent: bool = True,
        enrolled: bool = True,
        preference: bool = True,
        camera: FakeCameraProvider | None = None,
        model_ready: bool = True,
        use_real_model_readiness: bool = False,
        user_signed_in: bool = True,
    ) -> None:
        self._current_user = {"user_id": "owner@example.com"} if user_signed_in else None
        consent_fields = app_settings.build_face_template_consent_fields(True) if consent else {}
        self._app_settings = app_settings._coerce_settings_payload(
            {
                "build_profile": "dev",
                "enable_face_enrollment": flags,
                "enable_face_confirmation": flags,
                "face_confirmation_enabled": preference,
                **consent_fields,
            }
        )
        self._face_confirmation_enabled = preference
        self._face_confirmation_operation_state = {"status": "idle", "ok": True}
        self._face_camera_availability_cache = None
        self._face_operation_inflight = False
        self._face_status_update_allowed = False
        self._face_confirmation_cached_state = {}
        self._language = "en"
        self._t = lambda key, **_kwargs: key
        self.faceConfirmationChanged = DummySignal()
        self._camera = camera or FakeCameraProvider(FakeAvailability("camera_ready", True, "camera_ready"))
        self._status_service = FakeStatusService(enrolled=enrolled)
        self._model_ready = model_ready
        self._use_real_model_readiness = use_real_model_readiness

    def _set_status(self, message: str, tone: str = "info") -> None:
        pass

    def _face_service(self):
        return self._status_service

    def _face_status_for_current_user(self):
        user_id = self._current_face_user_id()
        if not user_id:
            return {"status": "signed_out", "enrolled": False, "ok": False}
        return self._status_service.status(user_id)

    def _face_camera_provider(self):
        return self._camera

    def _face_model_readiness_state(self) -> dict[str, object]:
        if self._use_real_model_readiness:
            return super()._face_model_readiness_state()
        if self._model_ready:
            return {"ok": True, "status": "face_models_configured", "reason": "ready"}
        return {"ok": False, "status": "face_models_missing", "reason": "models_missing"}


def test_local_dev_env_override_enables_face_flags_without_changing_safe_defaults(monkeypatch) -> None:
    payload = app_settings._coerce_settings_payload({"build_profile": "dev"})
    assert payload["enable_face_confirmation"] is False
    assert payload["enable_face_enrollment"] is False
    assert app_settings.feature_flag_enabled(payload, "enable_face_confirmation") is False

    monkeypatch.setenv("BIOAUTH_ENABLE_FACE_DEV", "1")
    assert app_settings.feature_flag_enabled(payload, "enable_face_confirmation") is True
    assert app_settings.feature_flag_enabled(payload, "enable_face_enrollment") is True

    production_payload = app_settings._coerce_settings_payload({"build_profile": "production"})
    assert app_settings.feature_flag_enabled(production_payload, "enable_face_confirmation") is False
    assert app_settings.feature_flag_enabled(production_payload, "enable_face_enrollment") is False


def test_disabled_face_flags_produce_feature_disabled_reason() -> None:
    bridge = DummyBridge(flags=False, consent=True, enrolled=True, preference=True)

    state = bridge._build_face_confirmation_state()

    assert state["faceConfirmationAvailable"] is False
    assert state["faceEnrollmentAvailable"] is False
    assert state["faceConfirmationUnavailableReason"] == "feature_disabled"
    assert state["faceEnrollmentUnavailableReason"] == "feature_disabled"
    assert state["operationStatus"] == "feature_disabled"
    assert state["faceModelReady"] is False


def test_enabled_flags_plus_missing_models_produce_models_missing_not_build_unavailable() -> None:
    bridge = DummyBridge(flags=True, consent=True, enrolled=True, preference=True, use_real_model_readiness=True)

    state = bridge._build_face_confirmation_state()

    assert state["faceConfirmationAvailable"] is False
    assert state["faceEnrollmentAvailable"] is False
    assert state["faceConfirmationUnavailableReason"] == "models_missing"
    assert state["faceEnrollmentUnavailableReason"] == "models_missing"
    assert state["operationStatus"] == "models_missing"
    assert "not enabled for this build" not in state["statusText"].lower()


def test_enabled_ready_model_plus_missing_camera_is_not_checked_until_explicit_action() -> None:
    camera = FakeCameraProvider(FakeAvailability("device_open_failed", False, "permission_or_device_open_failure"))
    bridge = DummyBridge(flags=True, consent=True, enrolled=True, preference=True, camera=camera, model_ready=True)

    state = bridge._build_face_confirmation_state()

    assert state["faceConfirmationAvailable"] is True
    assert state["faceEnrollmentAvailable"] is True
    assert state["faceConfirmationUnavailableReason"] == "not_checked"
    assert state["faceEnrollmentUnavailableReason"] == "not_checked"
    assert state["faceCameraAvailable"] is False
    assert state["faceCameraStatus"] == "not_checked"
    assert camera.availability_calls == 0
    assert camera.capture_calls == 0

    checked = bridge.requestFaceCameraCheck()
    assert checked["status"] == "camera_unavailable"
    assert camera.availability_calls == 1


def test_consent_missing_produces_consent_required_before_camera_check() -> None:
    camera = FakeCameraProvider(FakeAvailability("camera_ready", True, "camera_ready"))
    bridge = DummyBridge(flags=True, consent=False, enrolled=True, preference=True, camera=camera, model_ready=True)

    state = bridge._build_face_confirmation_state()

    assert state["faceConfirmationUnavailableReason"] == "consent_required"
    assert state["faceEnrollmentUnavailableReason"] == "consent_required"
    assert state["faceConsentGranted"] is False
    assert camera.availability_calls == 0


def test_missing_template_produces_template_missing_for_confirmation() -> None:
    camera = FakeCameraProvider(FakeAvailability("camera_ready", True, "camera_ready"))
    bridge = DummyBridge(flags=True, consent=True, enrolled=False, preference=True, camera=camera, model_ready=True)

    state = bridge._build_face_confirmation_state()

    assert state["faceConfirmationAvailable"] is False
    assert state["faceConfirmationUnavailableReason"] == "template_missing"
    assert state["faceTemplateEnrolled"] is False
    assert state["faceEnrollmentAvailable"] is True
    assert camera.availability_calls == 0


def test_fully_satisfied_backend_state_produces_ready_and_available() -> None:
    camera = FakeCameraProvider(FakeAvailability("camera_ready", True, "camera_ready"))
    bridge = DummyBridge(flags=True, consent=True, enrolled=True, preference=True, camera=camera, model_ready=True)

    state = bridge._build_face_confirmation_state()

    assert state["faceConfirmationAvailable"] is True
    assert state["faceEnrollmentAvailable"] is True
    assert state["faceConfirmationUnavailableReason"] == "not_checked"
    assert state["faceEnrollmentUnavailableReason"] == "not_checked"
    assert state["faceCameraAvailable"] is False
    assert camera.availability_calls == 0
    assert state["faceModelReady"] is True
    assert state["faceConsentGranted"] is True
    assert state["faceTemplateEnrolled"] is True


def test_qml_uses_backend_availability_fields_without_local_verification_logic() -> None:
    root = Path(__file__).resolve().parents[1]
    face_page = (root / "qml" / "pages" / "user" / "UserFaceConfirmationPage.qml").read_text(encoding="utf-8")
    dialog = (root / "qml" / "dialogs" / "FaceEnrollmentDialog.qml").read_text(encoding="utf-8")
    combined = (face_page + "\n" + dialog).lower()

    assert "faceconfirmationavailable" in combined
    assert "faceenrollmentavailable" in combined
    assert "faceconfirmationunavailablereason" in combined
    assert "backend.faceconfirmationstate.faceenrollmentavailable === true" in combined
    assert "backend.faceconfirmationstate.faceconfirmationavailable === true" not in dialog.lower()
    forbidden = [
        "captureverificationframe",
        "capture_verification_frame",
        "test_verification",
        "confirm_before_lock",
        "lock_suppressed",
        "verified_owner_after_anomaly",
        "approved_for_production",
        "protectedsessionsavailable",
        "template_digest",
        "source_frame_paths",
        "raw face image",
        "face unlock",
    ]
    for token in forbidden:
        assert token not in combined, token
