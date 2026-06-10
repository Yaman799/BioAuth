from __future__ import annotations

from tests.test_hotfix_h8_real_face_enrollment_wiring import DummyBridge, FakeCameraProvider, FakeCaptureResult, FakeFaceService


def _payload_ready_bridge() -> DummyBridge:
    bridge = DummyBridge(
        camera_provider=FakeCameraProvider(FakeCaptureResult(status="captured", ok=True)),
        face_service=FakeFaceService(),
        frame_count=3,
    )
    bridge._theme = "dark"
    bridge._language = "en"
    bridge._run_on_startup = False
    bridge._app_settings.pop("backend_face_camera_index", None)
    return bridge


def test_settings_payload_accepts_legacy_int_backend_face_camera_index_shadow() -> None:
    bridge = _payload_ready_bridge()
    bridge._backend_face_camera_index = 1

    payload = bridge._settings_payload()

    assert isinstance(payload["backend_face_camera_index"], int)
    assert payload["backend_face_camera_index"] == 1


def test_settings_payload_accepts_legacy_callable_backend_face_camera_index() -> None:
    bridge = _payload_ready_bridge()
    bridge._backend_face_camera_index = lambda: 2

    payload = bridge._settings_payload()

    assert payload["backend_face_camera_index"] == 2


def test_set_backend_face_camera_index_removes_legacy_shadow_and_persists_value() -> None:
    bridge = _payload_ready_bridge()
    bridge._backend_face_camera_index = 3

    result = bridge.setBackendFaceCameraIndex(4)
    payload = bridge._settings_payload()

    assert result["ok"] is True
    assert result["backend_camera_index"] == 4
    assert "_backend_face_camera_index" not in bridge.__dict__
    assert bridge._get_backend_face_camera_index_value() == 4
    assert payload["backend_face_camera_index"] == 4
