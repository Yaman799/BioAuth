from __future__ import annotations

import numpy as np

import app_settings
from face_camera_provider import CameraCaptureResult
from identity_confirmation import confirm_identity_before_lock
import monitor_core.incident as incident


def _enabled_settings(**extra):
    payload = app_settings._coerce_settings_payload(
        {
            "enable_face_confirmation": True,
            "face_confirmation_enabled": True,
            **app_settings.build_face_template_consent_fields(True),
        }
    )
    payload.update(extra)
    return payload


class FakeCameraProvider:
    def __init__(self, result: CameraCaptureResult) -> None:
        self.result = result
        self.verification_calls = 0

    def capture_verification_frame(self) -> CameraCaptureResult:
        self.verification_calls += 1
        return self.result


class FakeFaceService:
    def __init__(self, *, enrolled: bool = True, result: dict | None = None) -> None:
        self.enrolled = enrolled
        self.result = result if result is not None else {"status": "verified", "verified": True, "ok": True}
        self.status_calls: list[str] = []
        self.confirm_calls: list[dict] = []

    def status(self, user_id: str) -> dict:
        self.status_calls.append(user_id)
        return {"status": "enrolled" if self.enrolled else "not_enrolled", "enrolled": self.enrolled}

    def confirm_before_lock(self, user_id: str, frame=None) -> dict:
        self.confirm_calls.append({"user_id": user_id, "frame": frame})
        return dict(self.result)


def _captured_provider(frame):
    return FakeCameraProvider(CameraCaptureResult(status="captured", ok=True, reason="captured", frames=(frame,)))


def test_verified_face_pre_lock_path_passes_captured_frame_and_suppresses_only_lock_response():
    frame = np.full((16, 16, 3), 9, dtype=np.uint8)
    provider = _captured_provider(frame)
    service = FakeFaceService(result={"status": "verified", "verified": True, "ok": True})

    result = confirm_identity_before_lock(
        "owner",
        settings=_enabled_settings(),
        service=service,
        camera_provider=provider,
        timeout_sec=0.5,
    )

    assert result["attempted"] is True
    assert result["status"] == "verified_owner"
    assert result["lock_suppressed"] is True
    assert result["verified_owner_after_anomaly"] is True
    assert result["eligible_for_shadow_evidence"] is True
    assert result["eligible_for_direct_production_training"] is False
    assert result["lock_integration_enabled"] is True
    assert provider.verification_calls == 1
    assert service.status_calls == ["owner"]
    assert len(service.confirm_calls) == 1
    assert service.confirm_calls[0]["frame"] is frame
    assert service.confirm_calls[0]["frame"] is not None
    for forbidden in ("frame", "frames", "image", "images", "embedding", "template", "template_digest", "source_frame_paths"):
        assert forbidden not in result


def test_failed_face_pre_lock_path_keeps_existing_protection():
    frame = np.full((12, 12, 3), 3, dtype=np.uint8)
    provider = _captured_provider(frame)
    service = FakeFaceService(result={"status": "not_verified", "verified": False, "ok": False, "reason": "below_threshold"})

    result = confirm_identity_before_lock(
        "owner",
        settings=_enabled_settings(),
        service=service,
        camera_provider=provider,
        timeout_sec=0.5,
    )

    assert result["attempted"] is True
    assert result["status"] == "not_verified"
    assert result["fallback_reason"] == "below_threshold"
    assert result["lock_suppressed"] is False
    assert result["verified_owner_after_anomaly"] is False
    assert result["eligible_for_direct_production_training"] is False
    assert provider.verification_calls == 1
    assert service.confirm_calls[0]["frame"] is frame


def test_camera_unavailable_pre_lock_fails_closed_without_calling_verification():
    provider = FakeCameraProvider(CameraCaptureResult(status="device_open_failed", ok=False, reason="permission_or_device_open_failure", frames=()))
    service = FakeFaceService(result={"status": "verified", "verified": True, "ok": True})

    result = confirm_identity_before_lock(
        "owner",
        settings=_enabled_settings(),
        service=service,
        camera_provider=provider,
        timeout_sec=0.5,
    )

    assert result["attempted"] is True
    assert result["status"] == "camera_unavailable"
    assert result["fallback_reason"] == "camera_permission_or_device_open_failure"
    assert result["lock_suppressed"] is False
    assert result["verified_owner_after_anomaly"] is False
    assert provider.verification_calls == 1
    assert service.status_calls == ["owner"]
    assert service.confirm_calls == []


def test_face_disabled_pre_lock_fails_closed_before_service_or_camera():
    provider = _captured_provider(np.full((8, 8, 3), 1, dtype=np.uint8))
    service = FakeFaceService()
    disabled_settings = _enabled_settings(face_confirmation_enabled=False)

    result = confirm_identity_before_lock(
        "owner",
        settings=disabled_settings,
        service=service,
        camera_provider=provider,
        timeout_sec=0.5,
    )

    assert result["attempted"] is False
    assert result["status"] == "disabled"
    assert result["lock_suppressed"] is False
    assert provider.verification_calls == 0
    assert service.status_calls == []
    assert service.confirm_calls == []


def test_no_template_pre_lock_fails_closed_before_camera_capture():
    provider = _captured_provider(np.full((8, 8, 3), 2, dtype=np.uint8))
    service = FakeFaceService(enrolled=False)

    result = confirm_identity_before_lock(
        "owner",
        settings=_enabled_settings(),
        service=service,
        camera_provider=provider,
        timeout_sec=0.5,
    )

    assert result["attempted"] is True
    assert result["status"] == "not_enrolled"
    assert result["fallback_reason"] == "not_enrolled"
    assert result["lock_suppressed"] is False
    assert service.status_calls == ["owner"]
    assert provider.verification_calls == 0
    assert service.confirm_calls == []


def test_intended_monitor_pre_lock_entrypoint_passes_backend_factories(monkeypatch):
    provider = _captured_provider(np.full((10, 10, 3), 4, dtype=np.uint8))
    calls = {"camera_factory": 0, "service_factory": 0, "confirmation_kwargs": None}

    class FakeFacade:
        EXPECTED_USER_SLUG = "owner"

        @staticmethod
        def load_settings():
            return _enabled_settings()

        @staticmethod
        def build_default_camera_provider():
            calls["camera_factory"] += 1
            return provider

        @staticmethod
        def build_default_identity_confirmation_service():
            calls["service_factory"] += 1
            return FakeFaceService()

        @staticmethod
        def confirm_identity_before_lock(user_id, **kwargs):
            calls["confirmation_kwargs"] = dict(kwargs)
            service = kwargs.pop("service_factory")()
            camera_provider = kwargs.pop("camera_provider_factory")()
            return confirm_identity_before_lock(user_id, service=service, camera_provider=camera_provider, **kwargs)

    monkeypatch.setattr(incident, "_facade", lambda: FakeFacade, raising=False)

    result = incident._pre_lock_face_confirmation(session_id="s1", risk=99, avg_risk=90.0, ml=1)

    assert result["status"] == "verified_owner"
    assert result["lock_suppressed"] is True
    assert result["eligible_for_direct_production_training"] is False
    assert calls["confirmation_kwargs"] is not None
    assert callable(calls["confirmation_kwargs"]["service_factory"])
    assert callable(calls["confirmation_kwargs"]["camera_provider_factory"])
    assert calls["camera_factory"] == 1
    assert calls["service_factory"] == 1
    assert provider.verification_calls == 1
