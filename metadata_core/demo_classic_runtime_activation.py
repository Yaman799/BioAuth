"""Classic protected runtime activation helpers.

This module is intentionally demo-only.  It never grants real production
approval; when BIOAUTH_DEMO_CLASSIC_PROTECTED=1 it copies an already-trained
candidate bundle into the production runtime bundle shape required by the
classic monitor loader and writes the active runtime pointer.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Mapping

from app_settings import demo_classic_protected_enabled
from artifact_integrity import load_classifier, load_metadata, load_model
from artifact_integrity import remove_classifier_sidecar, save_classifier_sidecar
from metadata_core.paths import _active_runtime_pointer_path, _user_model_paths, _user_production_paths
from metadata_core.runtime import (
    clear_runtime_model_cache,
    resolve_active_runtime_paths_with_validation,
    validate_runtime_bundle_for_activation,
    write_active_runtime_pointer,
)
from security import atomic_write_bytes, atomic_write_text, save_metadata_hash, save_model_hash
from utils.identity import slugify_username

LOGGER = logging.getLogger(__name__)

DEMO_RUNTIME_SOURCE = "demo_classic_protected"
DEMO_EXISTING_CANDIDATE_SOURCE = "demo_classic_existing_candidate_activation"
DEMO_REJECTED_CANDIDATE_SOURCE = "demo_classic_rejected_candidate_override"
DEMO_REJECTED_CANDIDATE_STATUSES = {"rejected", "offline_approval_rejected"}

DEMO_CANDIDATE_STATUSES = {
    "approved_for_shadow",
    "shadow_validation",
    "approved_for_production",
    "production_ready",
    "demo_ready",
    # Presentation-build rejected candidate override. This never changes normal approval policy.
    "rejected",
    "offline_approval_rejected",
}


def _safe_status(value: Any) -> str:
    return str(value or "").strip().lower()


def _candidate_status_from_meta(meta: Mapping[str, Any]) -> str:
    for key in (
        "model_status",
        "candidate_status",
        "candidate_model_status",
        "approval_status",
        "status",
        "reason_code",
        "reasonCode",
    ):
        value = _safe_status(meta.get(key))
        if value:
            return value
    return ""


def _candidate_status_allowed(meta: Mapping[str, Any]) -> bool:
    status = _candidate_status_from_meta(meta)
    if status in DEMO_CANDIDATE_STATUSES:
        return True

    approval = meta.get("production_approval_state")
    if isinstance(approval, Mapping):
        nested = _candidate_status_from_meta(approval)
        if nested in DEMO_CANDIDATE_STATUSES:
            return True

    return False


def _copy_binary(src: str, dst: str) -> bool:
    if not src or not dst or not os.path.exists(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as handle:
        atomic_write_bytes(dst, handle.read())
    return True


def _copy_text_or_binary(src: str, dst: str) -> bool:
    return _copy_binary(src, dst)


def _remove_file_if_exists(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        LOGGER.debug("Failed removing stale demo runtime file %s", path, exc_info=True)


def _demo_runtime_metadata(candidate_meta: Mapping[str, Any], *, source_status: str) -> Dict[str, Any]:
    published_meta: Dict[str, Any] = dict(candidate_meta or {})
    rejected_override = _safe_status(source_status) in DEMO_REJECTED_CANDIDATE_STATUSES
    runtime_publish_source = DEMO_REJECTED_CANDIDATE_SOURCE if rejected_override else DEMO_EXISTING_CANDIDATE_SOURCE

    deep_runtime = dict(published_meta.get("deep_runtime") or {})
    allowed_modes = list(deep_runtime.get("allowed_modes") or [])
    for mode in ("classic_only_ready", "demo_classic_protected"):
        if mode not in allowed_modes:
            allowed_modes.append(mode)

    deep_runtime.update(
        {
            "runtime_rollout_stage": "demo_classic_protected",
            "runtime_shadow_only": False,
            "runtime_decision_influence_enabled": True,
            "runtime_shadow_diagnostics_enabled": bool(
                deep_runtime.get("runtime_shadow_diagnostics_enabled", True)
            ),
            "runtime_rollback_to_classic_on_failure": bool(
                deep_runtime.get("runtime_rollback_to_classic_on_failure", True)
            ),
            "runtime_activation_blocked_reason": None,
            "allowed_modes": allowed_modes,
            "demo_classic_protected": True,
            "classic_runtime_demo_direct": True,
        }
    )

    published_meta.update(
        {
            "bundle_role": "production",
            "model_status": "approved_for_production",
            "production_ready": True,
            "protected_sessions_available": True,
            "runtime_requires_production_approval": False,
            "demo_classic_protected": True,
            "production_approval_bypassed_for_demo": True,
            "runtime_publish_demo_only": True,
            "runtime_publish_demo_flag": "BIOAUTH_DEMO_CLASSIC_PROTECTED",
            "runtime_publish_source": runtime_publish_source,
            "runtime_bundle_source": DEMO_RUNTIME_SOURCE,
            "runtime_publish_source_candidate_status": source_status,
            "original_model_status_before_demo_publish": source_status,
            "published_to_runtime_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "deep_runtime": deep_runtime,
        }
    )
    if rejected_override:
        published_meta.update(
            {
                "demo_rejected_candidate_override": True,
                "runtime_publish_source": DEMO_REJECTED_CANDIDATE_SOURCE,
                "runtime_publish_source_candidate_status": source_status,
                "original_model_status_before_demo_publish": source_status,
                "reason_code_before_demo_publish": _safe_status(candidate_meta.get("reason_code") or candidate_meta.get("reasonCode")),
            }
        )

    return published_meta


def demo_runtime_pointer_status(user_id: str) -> Dict[str, Any]:
    safe = slugify_username(user_id)
    paths, validation = resolve_active_runtime_paths_with_validation(safe)
    return {
        "ok": bool(paths and isinstance(validation, dict) and validation.get("ok")),
        "paths": paths,
        "validation": validation,
        "reason": str(validation.get("reason") or "ok") if isinstance(validation, dict) else "unknown",
        "active_runtime_pointer_path": _active_runtime_pointer_path(safe),
    }


def activate_existing_candidate_runtime_for_demo(user_id: str, *, force: bool = False) -> Dict[str, Any]:
    """Activate an existing candidate bundle as a demo-only runtime bundle.

    The activation is available only behind BIOAUTH_DEMO_CLASSIC_PROTECTED=1.
    It validates that a candidate exists, that its status is demo-eligible, and
    that the copied production-shaped bundle passes the normal runtime
    activation validator before writing the active runtime pointer.
    """

    if not demo_classic_protected_enabled():
        return {
            "ok": False,
            "activated": False,
            "reason": "demo_classic_protected_disabled",
        }

    safe = slugify_username(user_id)
    if not safe:
        return {
            "ok": False,
            "activated": False,
            "reason": "user_id_missing",
        }

    if not force:
        current = demo_runtime_pointer_status(safe)
        if current.get("ok"):
            validation = current.get("validation") if isinstance(current.get("validation"), dict) else {}
            meta = validation.get("metadata") if isinstance(validation.get("metadata"), dict) else {}
            return {
                "ok": True,
                "activated": False,
                "reason": "active_runtime_already_valid",
                "paths": current.get("paths"),
                "validation": validation,
                "active_runtime_pointer_path": current.get("active_runtime_pointer_path"),
                "demo_classic_protected": True,
                "demo_rejected_candidate_override": bool(meta.get("demo_rejected_candidate_override")),
                "production_approval_bypassed_for_demo": bool(meta.get("production_approval_bypassed_for_demo", True)),
                "runtime_publish_source": str(meta.get("runtime_publish_source") or ""),
            }

    candidate_paths = _user_model_paths(safe)
    production_paths = _user_production_paths(safe)

    candidate_model = str(candidate_paths.get("model") or "")
    candidate_metadata = str(candidate_paths.get("metadata") or "")
    candidate_classifier = str(candidate_paths.get("classifier") or "")

    if not candidate_model or not os.path.exists(candidate_model):
        return {
            "ok": False,
            "activated": False,
            "reason": "candidate_model_missing",
            "candidate_paths": candidate_paths,
            "active_runtime_pointer_path": _active_runtime_pointer_path(safe),
        }

    if not candidate_metadata or not os.path.exists(candidate_metadata):
        return {
            "ok": False,
            "activated": False,
            "reason": "candidate_metadata_missing",
            "candidate_paths": candidate_paths,
            "active_runtime_pointer_path": _active_runtime_pointer_path(safe),
        }

    try:
        candidate_meta = load_metadata(candidate_metadata) or {}
    except Exception as exc:
        LOGGER.warning("Demo candidate metadata load failed for %s", safe, exc_info=True)
        return {
            "ok": False,
            "activated": False,
            "reason": f"candidate_metadata_invalid:{exc}",
            "candidate_paths": candidate_paths,
            "active_runtime_pointer_path": _active_runtime_pointer_path(safe),
        }

    if not isinstance(candidate_meta, Mapping):
        candidate_meta = {}

    source_status = _candidate_status_from_meta(candidate_meta)

    if not _candidate_status_allowed(candidate_meta):
        return {
            "ok": False,
            "activated": False,
            "reason": "candidate_status_not_demo_allowed",
            "candidate_status": source_status,
            "candidate_paths": candidate_paths,
            "active_runtime_pointer_path": _active_runtime_pointer_path(safe),
        }

    try:
        load_model(candidate_model)
    except Exception as exc:
        LOGGER.warning("Demo candidate model load failed for %s", safe, exc_info=True)
        return {
            "ok": False,
            "activated": False,
            "reason": f"candidate_model_invalid:{exc}",
            "candidate_paths": candidate_paths,
            "active_runtime_pointer_path": _active_runtime_pointer_path(safe),
        }

    if candidate_classifier and os.path.exists(candidate_classifier):
        try:
            load_classifier(candidate_classifier)
        except Exception as exc:
            LOGGER.warning("Demo candidate classifier load failed for %s", safe, exc_info=True)
            return {
                "ok": False,
                "activated": False,
                "reason": f"candidate_classifier_invalid:{exc}",
                "candidate_paths": candidate_paths,
                "active_runtime_pointer_path": _active_runtime_pointer_path(safe),
            }

    os.makedirs(str(production_paths.get("base") or ""), exist_ok=True)

    _copy_binary(candidate_model, production_paths["model"])
    save_model_hash(production_paths["model"])

    rejected_override = _safe_status(source_status) in DEMO_REJECTED_CANDIDATE_STATUSES
    runtime_publish_source = DEMO_REJECTED_CANDIDATE_SOURCE if rejected_override else DEMO_EXISTING_CANDIDATE_SOURCE
    published_meta = _demo_runtime_metadata(candidate_meta, source_status=source_status)
    atomic_write_text(
        production_paths["metadata"],
        json.dumps(published_meta, indent=2, ensure_ascii=False),
    )
    save_metadata_hash(production_paths["metadata"])

    if candidate_classifier and os.path.exists(candidate_classifier):
        _copy_binary(candidate_classifier, production_paths["classifier"])
        save_classifier_sidecar(production_paths["classifier"])
    else:
        _remove_file_if_exists(production_paths["classifier"])
        remove_classifier_sidecar(production_paths["classifier"])

    for extra_key in ("evaluation_report", "evaluation_summary"):
        src = str(candidate_paths.get(extra_key) or "")
        dst = str(production_paths.get(extra_key) or "")
        if src and dst and os.path.exists(src):
            _copy_text_or_binary(src, dst)

    validation = validate_runtime_bundle_for_activation(production_paths)
    if not validation.get("ok"):
        return {
            "ok": False,
            "activated": False,
            "reason": f"demo_production_bundle_validation_failed:{validation.get('reason')}",
            "candidate_paths": candidate_paths,
            "production_paths": production_paths,
            "validation": validation,
            "active_runtime_pointer_path": _active_runtime_pointer_path(safe),
        }

    try:
        pointer = write_active_runtime_pointer(
            safe,
            production_paths,
            source=DEMO_RUNTIME_SOURCE,
        )
    except Exception as exc:
        LOGGER.warning("Demo active runtime pointer write failed for %s", safe, exc_info=True)
        return {
            "ok": False,
            "activated": False,
            "reason": f"active_runtime_pointer_write_failed:{exc}",
            "candidate_paths": candidate_paths,
            "production_paths": production_paths,
            "validation": validation,
            "active_runtime_pointer_path": _active_runtime_pointer_path(safe),
        }

    clear_runtime_model_cache(safe)

    return {
        "ok": True,
        "activated": True,
        "reason": "demo_classic_runtime_activated",
        "candidate_status": source_status,
        "candidate_paths": candidate_paths,
        "production_paths": production_paths,
        "pointer": pointer,
        "validation": validation,
        "active_runtime_pointer_path": _active_runtime_pointer_path(safe),
        "demo_classic_protected": True,
        "demo_rejected_candidate_override": bool(rejected_override),
        "production_approval_bypassed_for_demo": True,
        "runtime_publish_source": runtime_publish_source,
    }


__all__ = [
    "activate_existing_candidate_runtime_for_demo",
    "demo_runtime_pointer_status",
]
