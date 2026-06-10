from __future__ import annotations

"""Encrypted local storage for optional face confirmation templates."""

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

from app_settings import PRIVACY_POLICY_VERSION
from face_biometrics import FACE_TEMPLATE_KIND, FACE_TEMPLATE_SCHEMA_VERSION, FaceQualityError, embedding_from_base64
from paths import data_dir
from secure_storage import SecureEnvelopeIntegrityError, load_enveloped_json, write_enveloped_json

FACE_TEMPLATE_STORAGE_VERSION = 1


def _utc_now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def face_user_id_hash(user_id: str) -> str:
    normalized = str(user_id or "").strip().lower()
    if not normalized:
        raise ValueError("user_id_required")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class FaceTemplateStore:
    def __init__(self, base_dir: str | os.PathLike[str] | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else Path(data_dir()) / "face_templates"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def template_path(self, user_id: str) -> Path:
        return self.base_dir / f"face_template_{face_user_id_hash(user_id)}.json.enc"

    def save_template(
        self,
        user_id: str,
        template_payload: Mapping[str, Any],
        *,
        consent_granted: bool,
        consent_policy_version: str = PRIVACY_POLICY_VERSION,
    ) -> dict[str, Any]:
        if not consent_granted:
            raise PermissionError("face_template_consent_required")
        if not isinstance(template_payload, Mapping):
            raise TypeError("template_payload_required")
        if template_payload.get("kind") != FACE_TEMPLATE_KIND:
            raise FaceQualityError("invalid_template_kind")
        embedding = str(template_payload.get("embedding") or "")
        dimension = int(template_payload.get("embedding_dimension") or 0)
        embedding_from_base64(embedding, expected_dimension=dimension)
        now = _utc_now()
        payload = {
            "storage_version": FACE_TEMPLATE_STORAGE_VERSION,
            "schema_version": FACE_TEMPLATE_SCHEMA_VERSION,
            "kind": FACE_TEMPLATE_KIND,
            "user_id_hash": face_user_id_hash(user_id),
            "embedding_model_id": str(template_payload.get("embedding_model_id") or "unknown"),
            "embedding_dimension": dimension,
            "embedding": embedding,
            "template_digest": str(template_payload.get("template_digest") or ""),
            "sample_count": int(template_payload.get("sample_count") or 0),
            "quality_score": float(template_payload.get("quality_score") or 0.0),
            "consent_granted": True,
            "consent_policy_version": str(consent_policy_version or PRIVACY_POLICY_VERSION),
            "created_at": str(template_payload.get("created_at") or now),
            "updated_at": now,
            # Explicit audit guardrails.  No raw images, frames, crops, or paths are
            # accepted or persisted by this store.
            "raw_images_stored": False,
            "source_frame_paths": [],
        }
        write_enveloped_json(str(self.template_path(user_id)), payload)
        return payload

    def load_template(self, user_id: str) -> dict[str, Any] | None:
        path = self.template_path(user_id)
        if not path.exists():
            return None
        payload, _state = load_enveloped_json(str(path), default={}, rewrite_migrated=False)
        if payload.get("kind") != FACE_TEMPLATE_KIND:
            raise SecureEnvelopeIntegrityError("unexpected face template payload")
        if payload.get("user_id_hash") != face_user_id_hash(user_id):
            raise SecureEnvelopeIntegrityError("face template user hash mismatch")
        return dict(payload)

    def delete_template(self, user_id: str) -> bool:
        path = self.template_path(user_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def has_template(self, user_id: str) -> bool:
        return self.template_path(user_id).exists()

    def status(self, user_id: str) -> dict[str, Any]:
        try:
            payload = self.load_template(user_id)
        except Exception as exc:
            return {"status": "error", "enrolled": False, "reason": str(exc)}
        if not payload:
            return {"status": "not_enrolled", "enrolled": False}
        return {
            "status": "enrolled",
            "enrolled": True,
            "embedding_model_id": payload.get("embedding_model_id"),
            "sample_count": payload.get("sample_count"),
            "quality_score": payload.get("quality_score"),
            "updated_at": payload.get("updated_at"),
            "raw_images_stored": False,
        }
