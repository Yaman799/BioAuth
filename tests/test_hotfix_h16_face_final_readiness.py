from __future__ import annotations

import json
from pathlib import Path

from build_tools.commercial_package_allowlist import collect_commercial_datas

import numpy as np

from face_biometrics import (
    DEFAULT_FACE_DETECTOR_MODEL_FILENAME,
    DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME,
    FACE_MODELS_MISSING,
    FACE_MODELS_READY,
    FaceBox,
    validate_face_model_config,
)
from face_template_store import FaceTemplateStore
from identity_confirmation import IdentityConfirmationService
from tests.test_hotfix_h15_face_verification_test_button import (
    BridgeForVerification,
    FakeCameraProvider,
    FakeCaptureResult,
    MutableFakeFaceEngine,
    _good_frame,
)
from tests.test_phase_11_face_biometrics_backend import _configure_crypto

ROOT = Path(__file__).resolve().parent.parent
FACE_PAGE = ROOT / "qml" / "pages" / "user" / "UserFaceConfirmationPage.qml"
SPEC = ROOT / "BioAuth.spec"

PERSON_A = np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
PERSON_B = np.asarray([0.0, 1.0, 0.0, 0.0], dtype=np.float32)


def _service_enrolled_as_person_a(tmp_path: Path, monkeypatch):
    _configure_crypto(tmp_path, monkeypatch)
    store = FaceTemplateStore(tmp_path / "face_templates")
    engine = MutableFakeFaceEngine(embedding=PERSON_A)
    service = IdentityConfirmationService(store=store, engine=engine)
    enrolled = service.enroll(
        "owner@example.com",
        [_good_frame(170), _good_frame(171), _good_frame(172)],
        consent_granted=True,
    )
    assert enrolled["ok"] is True
    assert store.has_template("owner@example.com") is True
    return service, engine, store


def _bridge_for_frame(*, service, frame=None, camera_ok: bool = True, consent: bool = True, model_ready: bool = True, model_status: str = FACE_MODELS_READY):
    if frame is None:
        frame = _good_frame(190)
    capture = FakeCaptureResult(
        status="captured" if camera_ok else "device_open_failed",
        ok=bool(camera_ok),
        frames=(frame,) if camera_ok else (),
        reason="captured" if camera_ok else "permission_or_device_open_failure",
    )
    camera = FakeCameraProvider(capture)
    bridge = BridgeForVerification(
        camera_provider=camera,
        service=service,
        consent=consent,
        model_ready=model_ready,
        model_status=model_status,
    )
    return bridge, camera


def test_person_a_enrollment_then_person_a_verification_succeeds_and_person_b_fails(tmp_path: Path, monkeypatch) -> None:
    service, engine, store = _service_enrolled_as_person_a(tmp_path, monkeypatch)

    engine.embedding = PERSON_A
    same_person_bridge, same_person_camera = _bridge_for_frame(service=service)
    same_person = same_person_bridge.testFaceConfirmation()

    assert same_person["status"] == "verified"
    assert same_person["ok"] is True
    assert same_person["verified"] is True
    assert same_person["lockIntegrationEnabled"] is False
    assert same_person_camera.verification_calls == 1

    engine.embedding = PERSON_B
    different_person_bridge, different_person_camera = _bridge_for_frame(service=service)
    different_person = different_person_bridge.testFaceConfirmation()

    assert different_person["status"] == "not_verified"
    assert different_person["ok"] is False
    assert different_person["verified"] is False
    assert different_person["lockIntegrationEnabled"] is False
    assert different_person_camera.verification_calls == 1

    encrypted_text = store.template_path("owner@example.com").read_text(encoding="utf-8")
    envelope = json.loads(encrypted_text)
    assert envelope["encrypted"] is True
    for forbidden in ("raw_image", "raw_frame", "screenshot", "source_frame", "PERSON_A", "PERSON_B"):
        assert forbidden.lower() not in encrypted_text.lower()
    for result in (same_person, different_person):
        for forbidden_key in ("frame", "frames", "image", "images", "embedding", "template_digest", "score", "threshold", "quality_score"):
            assert forbidden_key not in result


def test_invalid_face_conditions_fail_closed_with_backend_reason_codes(tmp_path: Path, monkeypatch) -> None:
    cases = [
        ([], "no_face_detected"),
        ([FaceBox(0, 0, 72, 72, 0.99), FaceBox(3, 3, 72, 72, 0.98)], "multiple_faces_detected"),
        ([FaceBox(0, 0, 4, 4, 0.99)], "poor_quality"),
    ]
    for detections, expected_status in cases:
        service, engine, _store = _service_enrolled_as_person_a(tmp_path / expected_status, monkeypatch)
        engine.detections = detections
        bridge, camera = _bridge_for_frame(service=service)

        result = bridge.testFaceConfirmation()

        assert result["status"] == expected_status
        assert result["ok"] is False
        assert result["verified"] is False
        assert result["lockIntegrationEnabled"] is False
        assert camera.verification_calls == 1


def test_consent_camera_model_and_missing_template_paths_fail_closed(tmp_path: Path, monkeypatch) -> None:
    service, _engine, _store = _service_enrolled_as_person_a(tmp_path, monkeypatch)

    no_consent_bridge, no_consent_camera = _bridge_for_frame(service=service, consent=False)
    no_consent = no_consent_bridge.testFaceConfirmation()
    assert no_consent["status"] == "consent_required"
    assert no_consent["verified"] is False
    assert no_consent_camera.verification_calls == 0

    no_model_bridge, no_model_camera = _bridge_for_frame(service=service, model_ready=False, model_status=FACE_MODELS_MISSING)
    no_model = no_model_bridge.testFaceConfirmation()
    assert no_model["status"] == FACE_MODELS_MISSING
    assert no_model["verified"] is False
    assert no_model_camera.verification_calls == 0

    no_camera_bridge, no_camera = _bridge_for_frame(service=service, camera_ok=False)
    camera_result = no_camera_bridge.testFaceConfirmation()
    assert camera_result["status"] == "camera_unavailable"
    assert camera_result["verified"] is False
    assert no_camera.verification_calls == 1

    service.delete_template("owner@example.com")
    deleted_template_bridge, deleted_template_camera = _bridge_for_frame(service=service)
    deleted_template = deleted_template_bridge.testFaceConfirmation()
    assert deleted_template["status"] in {"not_enrolled", "template_missing"}
    assert deleted_template["ok"] is False
    assert deleted_template["verified"] is False
    assert deleted_template_camera.verification_calls == 0


def test_template_deletion_removes_verification_ability(tmp_path: Path, monkeypatch) -> None:
    service, engine, store = _service_enrolled_as_person_a(tmp_path, monkeypatch)
    engine.embedding = PERSON_A

    before_delete_bridge, _before_camera = _bridge_for_frame(service=service)
    before = before_delete_bridge.testFaceConfirmation()
    assert before["status"] == "verified"
    assert before["verified"] is True

    deleted = service.delete_template("owner@example.com")
    assert deleted["deleted"] is True
    assert store.has_template("owner@example.com") is False

    after_delete_bridge, after_camera = _bridge_for_frame(service=service)
    after = after_delete_bridge.testFaceConfirmation()
    assert after["verified"] is False
    assert after["status"] in {"not_enrolled", "template_missing"}
    assert after_camera.verification_calls == 0


def test_manual_model_files_are_required_but_fake_fixtures_can_mark_ready(tmp_path: Path) -> None:
    missing = validate_face_model_config(runtime_base=tmp_path)
    assert missing["ok"] is False
    assert missing["status"] == FACE_MODELS_MISSING

    model_dir = tmp_path / "models" / "face"
    model_dir.mkdir(parents=True)
    (model_dir / DEFAULT_FACE_DETECTOR_MODEL_FILENAME).write_bytes(b"fake detector fixture for H16 only")
    (model_dir / DEFAULT_FACE_RECOGNIZER_MODEL_FILENAME).write_bytes(b"fake recognizer fixture for H16 only")

    ready = validate_face_model_config(runtime_base=tmp_path)
    assert ready["ok"] is True
    assert ready["status"] == FACE_MODELS_READY


def test_qml_packaging_remains_display_only_and_release_safe() -> None:
    qml = FACE_PAGE.read_text(encoding="utf-8").lower()
    for required in ("facetestconfirmationbutton", "backend.testfaceconfirmation()", "cantestface"):
        assert required in qml
    for forbidden in (
        "detectfaces",
        "extractembedding",
        "cosinesimilarity",
        "verify_embedding",
        "score >=",
        "threshold",
        "face unlock",
        "lock_suppressed",
        "approved_for_production",
        "protectedsessionsavailable",
    ):
        assert forbidden not in qml, forbidden

    pairs = collect_commercial_datas(ROOT)
    assert any(source.startswith("models/face/") and dest.startswith("models/face") for source, dest in pairs)

    # Generated validation reports are kept in the external evidence bundle,
    # not in the clean release source tree. Runtime/package safety is asserted
    # through source files and packaging configuration above.


def test_no_real_onnx_binaries_are_in_delivered_models_face_directory() -> None:
    checked_in = sorted(p.name for p in (ROOT / "models" / "face").glob("*.onnx"))
    assert checked_in == []
