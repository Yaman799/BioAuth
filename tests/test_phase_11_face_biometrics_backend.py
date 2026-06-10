from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import app_settings
import bio_platform.secrets as secret_backend
import security
from face_biometrics import FaceBox, FaceQualityError, build_enrollment_template, embedding_from_base64, verify_frame_against_template
from face_template_store import FaceTemplateStore
from identity_confirmation import IdentityConfirmationService
from identity_confirmation_policy import face_backend_available_for_confirmation, face_backend_available_for_enrollment
from secure_storage import decrypt_envelope


class FakeFaceEngine:
    model_id = "fake-sface-test-v1"

    def __init__(self, *, detections=None, embedding=None):
        self.detections = detections if detections is not None else [FaceBox(4, 4, 64, 64, 0.99)]
        self.embedding = np.asarray(embedding if embedding is not None else [1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def detect_faces(self, frame):
        return self.detections

    def extract_embedding(self, frame, face):
        return self.embedding


def _configure_crypto(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(secret_backend, "keyring", None)
    monkeypatch.setattr(security, "MODELS_DIR", str(model_dir))
    monkeypatch.setattr(security, "KEY_FILE", str(model_dir / "secret.key"))
    monkeypatch.setattr(security, "KEY_FILE_DPAPI", str(model_dir / "secret.key.dpapi"))
    security.reset_security_caches()


def _good_frames(count: int = 3):
    return [np.full((96, 96, 3), 180, dtype=np.uint8) for _ in range(count)]


def test_face_template_storage_is_encrypted_and_does_not_store_raw_images(tmp_path, monkeypatch):
    _configure_crypto(tmp_path, monkeypatch)
    store = FaceTemplateStore(tmp_path / "face_templates")
    engine = FakeFaceEngine()
    template = build_enrollment_template(_good_frames(3), engine, min_samples=3)

    saved = store.save_template("owner@example.com", template, consent_granted=True)
    path = store.template_path("owner@example.com")

    assert saved["raw_images_stored"] is False
    assert saved["source_frame_paths"] == []
    assert "owner@example.com" not in path.name
    raw_text = path.read_text(encoding="utf-8")
    raw_doc = json.loads(raw_text)
    assert raw_doc["encrypted"] is True
    assert "embedding" not in raw_text
    assert "source_frame" not in raw_text
    assert "raw_image" not in raw_text

    decrypted = decrypt_envelope(raw_doc)
    assert decrypted["kind"] == "face_confirmation_template"
    assert decrypted["raw_images_stored"] is False
    assert decrypted["source_frame_paths"] == []
    assert store.load_template("owner@example.com")["template_digest"] == saved["template_digest"]


def test_delete_template_removes_encrypted_template_file(tmp_path, monkeypatch):
    _configure_crypto(tmp_path, monkeypatch)
    store = FaceTemplateStore(tmp_path / "face_templates")
    template = build_enrollment_template(_good_frames(3), FakeFaceEngine(), min_samples=3)
    store.save_template("owner", template, consent_granted=True)

    assert store.has_template("owner") is True
    assert store.delete_template("owner") is True
    assert store.has_template("owner") is False
    assert store.load_template("owner") is None


def test_enrollment_requires_consent_and_fails_closed_without_engine(tmp_path, monkeypatch):
    _configure_crypto(tmp_path, monkeypatch)
    service = IdentityConfirmationService(store=FaceTemplateStore(tmp_path / "face_templates"), engine=None)

    unavailable = service.enroll("owner", _good_frames(5), consent_granted=True)
    assert unavailable["status"] == "camera_unavailable"
    assert unavailable["ok"] is False

    service = IdentityConfirmationService(store=FaceTemplateStore(tmp_path / "face_templates"), engine=FakeFaceEngine())
    rejected = service.enroll("owner", _good_frames(5), consent_granted=False)
    assert rejected["status"] == "consent_required"
    assert rejected["ok"] is False
    assert not service.store.has_template("owner")


def test_no_face_multiple_face_and_low_quality_inputs_are_rejected():
    with pytest.raises(FaceQualityError, match="insufficient_quality_samples"):
        build_enrollment_template(_good_frames(3), FakeFaceEngine(detections=[]), min_samples=3)

    with pytest.raises(FaceQualityError, match="insufficient_quality_samples"):
        build_enrollment_template(_good_frames(3), FakeFaceEngine(detections=[FaceBox(0, 0, 64, 64), FaceBox(1, 1, 64, 64)]), min_samples=3)

    with pytest.raises(FaceQualityError, match="insufficient_quality_samples"):
        build_enrollment_template(_good_frames(3), FakeFaceEngine(detections=[FaceBox(0, 0, 4, 4)]), min_samples=3)


def test_identity_confirmation_verification_uses_template_without_lock_integration(tmp_path, monkeypatch):
    _configure_crypto(tmp_path, monkeypatch)
    store = FaceTemplateStore(tmp_path / "face_templates")
    service = IdentityConfirmationService(store=store, engine=FakeFaceEngine(embedding=[1.0, 0.0, 0.0, 0.0]))

    enrolled = service.enroll("owner", _good_frames(5), consent_granted=True)
    assert enrolled["status"] == "enrolled"
    result = service.test_verification("owner", _good_frames(1)[0], threshold=0.9)

    assert result["verified"] is True
    assert result["lock_integration_enabled"] is False
    assert result["status"] == "verified"

    failing = IdentityConfirmationService(store=store, engine=FakeFaceEngine(embedding=[0.0, 1.0, 0.0, 0.0]))
    fail_result = failing.test_verification("owner", _good_frames(1)[0], threshold=0.9)
    assert fail_result["verified"] is False
    assert fail_result["lock_integration_enabled"] is False


def test_face_consent_defaults_are_safe_and_feature_flags_stay_backend_owned():
    payload = app_settings._coerce_settings_payload({})
    assert payload["enable_face_confirmation"] is False
    assert payload["enable_face_enrollment"] is False
    assert payload["face_template_consent_granted"] is False
    assert face_backend_available_for_enrollment(payload) is False
    assert face_backend_available_for_confirmation(payload) is False

    consented = app_settings._coerce_settings_payload({
        "enable_face_enrollment": True,
        "enable_face_confirmation": True,
        **app_settings.build_face_template_consent_fields(True),
    })
    assert face_backend_available_for_enrollment(consented) is True
    assert face_backend_available_for_confirmation(consented) is True


def test_raw_face_images_are_not_written_anywhere_by_face_backend(tmp_path, monkeypatch):
    _configure_crypto(tmp_path, monkeypatch)
    store = FaceTemplateStore(tmp_path / "face_templates")
    service = IdentityConfirmationService(store=store, engine=FakeFaceEngine())
    service.enroll("owner", _good_frames(5), consent_granted=True)

    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files
    forbidden_suffixes = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".npy", ".npz"}
    assert not [p for p in files if p.suffix.lower() in forbidden_suffixes]


def test_face_backend_modules_keep_incident_evidence_and_logger_separate():
    monitor_source = Path("src/bioauth/runtime/monitor_impl.py").read_text(encoding="utf-8")
    incident_source = Path("monitor_core/incident.py").read_text(encoding="utf-8")
    evidence_source = Path("evidence_capture.py").read_text(encoding="utf-8")
    logger_source = Path("src/bioauth/input/logger_impl.py").read_text(encoding="utf-8")

    assert "confirm_identity_before_lock" in monitor_source
    assert "_pre_lock_face_confirmation" in incident_source
    for source in (evidence_source, logger_source):
        for token in ("identity_confirmation", "face_biometrics", "face_template_store", "confirm_identity_before_lock"):
            assert token not in source
    assert "face_biometrics" not in monitor_source
    assert "face_template_store" not in monitor_source


def test_template_round_trip_dimension_and_digest_are_stable():
    template = build_enrollment_template(_good_frames(3), FakeFaceEngine(embedding=[2.0, 0.0, 0.0, 0.0]), min_samples=3)
    embedding = embedding_from_base64(template["embedding"], expected_dimension=4)
    result = verify_frame_against_template(_good_frames(1)[0], template, FakeFaceEngine(embedding=[2.0, 0.0, 0.0, 0.0]), threshold=0.99)

    assert embedding.shape == (4,)
    assert result["verified"] is True
    assert result["score"] == 1.0
