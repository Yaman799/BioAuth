"""Commercial Core 22E production bootstrap and last-good runtime helpers.

This module is intentionally conservative: it never promotes a newer shadow-only
candidate over an already-valid production runtime.  It only publishes an initial
production-shaped bundle when no active runtime pointer is valid and a trained
candidate bundle can be loaded and validated as a runtime artifact after being
copied into the production bundle shape.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from artifact_integrity import load_classifier, load_metadata, load_model
from metadata_core.paths import _active_runtime_pointer_path, _user_model_paths, _user_production_paths
from metadata_core.runtime import (
    clear_runtime_model_cache,
    resolve_active_runtime_paths_with_validation,
    validate_runtime_bundle_for_activation,
    write_active_runtime_pointer,
)
from security import atomic_write_bytes, atomic_write_text, remove_user_classifier_hash, save_metadata_hash, save_model_hash, save_user_classifier_hash
from utils.identity import slugify_username

BOOTSTRAP_SOURCE = "commercial_core_22e_initial_production_bootstrap"
FALLBACK_SOURCE = "commercial_core_22e_last_good_production_fallback"
_BOOTSTRAP_ENV_DISABLE = "BIOAUTH_DISABLE_INITIAL_PRODUCTION_BOOTSTRAP"
_BOOTSTRAP_ALLOWED_STATUSES = {"approved_for_shadow", "shadow_validation", "approved_for_production", "production_ready"}
_BOOTSTRAP_REJECTED_STATUSES = {"rejected", "offline_approval_rejected", "failed", "blocked"}
_REQUIRED_ARTIFACTS = ("model", "metadata")


def _env_disabled() -> bool:
    return str(os.environ.get(_BOOTSTRAP_ENV_DISABLE, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _artifact_exists(path: Any) -> bool:
    text = str(path or "").strip()
    return bool(text and os.path.exists(text))


def _remove_path(path: Any) -> None:
    text = str(path or "").strip()
    if not text:
        return
    try:
        if os.path.isdir(text):
            shutil.rmtree(text)
        elif os.path.exists(text):
            os.remove(text)
    except OSError:
        pass


def _copy_file(src: Any, dst: Any) -> None:
    src_text = str(src or "").strip()
    dst_text = str(dst or "").strip()
    if not src_text or not dst_text:
        raise ValueError("copy_file_requires_source_and_destination")
    with open(src_text, "rb") as handle:
        atomic_write_bytes(dst_text, handle.read())


def _copy_optional_file(src: Any, dst: Any) -> None:
    if _artifact_exists(src):
        _copy_file(src, dst)


def _classifier_required(meta: Mapping[str, Any]) -> bool:
    supervised = meta.get("supervised_classifier")
    if isinstance(supervised, Mapping) and bool(supervised.get("enabled")):
        return True
    return bool(str(meta.get("classifier_family") or meta.get("classifier") or "").strip())


def _candidate_status(meta: Mapping[str, Any]) -> str:
    for key in ("model_status", "candidate_status", "approval_status", "status"):
        value = str(meta.get(key) or "").strip().lower()
        if value:
            return value
    nested = meta.get("production_approval")
    if isinstance(nested, Mapping):
        for key in ("candidate_status", "candidateStatus", "modelStatus"):
            value = str(nested.get(key) or "").strip().lower()
            if value:
                return value
    return ""


def _missing_artifacts(paths: Mapping[str, str], meta: Mapping[str, Any]) -> list[str]:
    missing = [key for key in _REQUIRED_ARTIFACTS if not _artifact_exists(paths.get(key))]
    if _classifier_required(meta) and not _artifact_exists(paths.get("classifier")):
        missing.append("classifier")
    return missing


def _load_candidate_metadata(paths: Mapping[str, str], candidate_metadata: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    meta = _as_dict(candidate_metadata)
    if meta:
        return meta
    metadata_path = str(paths.get("metadata") or "")
    if not metadata_path:
        return {}
    loaded = load_metadata(metadata_path) or {}
    return dict(loaded) if isinstance(loaded, Mapping) else {}


def _validate_candidate_artifacts(paths: Mapping[str, str], meta: Mapping[str, Any]) -> tuple[bool, str]:
    missing = _missing_artifacts(paths, meta)
    if missing:
        return False, "missing_artifact:" + ",".join(missing)
    try:
        load_model(str(paths.get("model") or ""))
        load_metadata(str(paths.get("metadata") or ""))
        if _artifact_exists(paths.get("classifier")):
            load_classifier(str(paths.get("classifier") or ""))
    except Exception as exc:
        return False, f"candidate_artifact_invalid:{exc}"
    return True, "ok"


def _build_initial_production_metadata(candidate_meta: Mapping[str, Any], *, source_status: str) -> Dict[str, Any]:
    published = dict(candidate_meta)
    rollout = _as_dict(published.get("rollout_details"))
    deep_runtime = _as_dict(published.get("deep_runtime"))
    deep_runtime.update({
        "runtime_rollout_stage": deep_runtime.get("runtime_rollout_stage") or rollout.get("rollout_status") or "initial_production_bootstrap",
        "runtime_shadow_only": False,
        "runtime_decision_influence_enabled": bool(deep_runtime.get("runtime_decision_influence_enabled", rollout.get("production_decision_enabled", True))),
        "runtime_rollback_to_classic_on_failure": bool(deep_runtime.get("runtime_rollback_to_classic_on_failure", True)),
        "commercial_core_22e_initial_production_bootstrap": True,
    })
    published.update({
        "bundle_role": "production",
        "model_status": "approved_for_production",
        "candidate_status_before_initial_bootstrap": source_status,
        "initial_production_bootstrap": True,
        "commercial_core_22e_initial_production_bootstrap": True,
        "protected_sessions_available": True,
        "production_ready": True,
        "runtime_publish_source": BOOTSTRAP_SOURCE,
        "runtime_requires_production_approval": False,
        "production_bootstrap_policy_version": "commercial-core-22e-v1",
        "production_bootstrap_created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "deep_runtime": deep_runtime,
    })
    return published


def active_runtime_state(user_id: str) -> Dict[str, Any]:
    safe = slugify_username(user_id)
    paths, validation = resolve_active_runtime_paths_with_validation(safe)
    return {
        "ok": bool(validation.get("ok")),
        "paths": dict(paths or {}),
        "validation": dict(validation or {}),
        "pointer_path": _active_runtime_pointer_path(safe),
        "source": FALLBACK_SOURCE if validation.get("ok") else "",
        "protected_sessions_available": bool(validation.get("ok")),
        "production_ready": bool(validation.get("ok")),
    }


def last_good_production_overlay(user_id: str, profile: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Return a profile overlay when an active production runtime pointer is valid."""
    state = active_runtime_state(user_id)
    if not bool(state.get("ok")):
        return {}
    validation = _as_dict(state.get("validation"))
    metadata = _as_dict(validation.get("metadata"))
    artifact_identity = _as_dict(validation.get("artifact_identity"))
    return {
        "production_ready": True,
        "productionReady": True,
        "protected_sessions_available": True,
        "protectedSessionsAvailable": True,
        "can_start_monitor": True,
        "canStartMonitor": True,
        "local_profile_can_start_monitor": True,
        "production_ready_reason": "last_good_production_runtime_valid",
        "productionReadyReason": "last_good_production_runtime_valid",
        "runtime_validation_reason": "ok",
        "runtimeValidationReason": "ok",
        "last_good_production_available": True,
        "lastGoodProductionAvailable": True,
        "last_good_production_source": FALLBACK_SOURCE,
        "lastGoodProductionSource": FALLBACK_SOURCE,
        "active_runtime_pointer_present": True,
        "activeRuntimePointerPresent": True,
        "active_runtime_source": os.path.basename(str((_as_dict(state.get("paths"))).get("base") or "")),
        "activeRuntimeSource": os.path.basename(str((_as_dict(state.get("paths"))).get("base") or "")),
        "production_model_digest": str(artifact_identity.get("model_sha256") or ""),
        "productionModelDigest": str(artifact_identity.get("model_sha256") or ""),
        "production_metadata_digest": str(artifact_identity.get("metadata_sha256") or ""),
        "productionMetadataDigest": str(artifact_identity.get("metadata_sha256") or ""),
        "production_runtime_model_status": str(metadata.get("model_status") or "approved_for_production"),
        "productionRuntimeModelStatus": str(metadata.get("model_status") or "approved_for_production"),
    }


def maybe_bootstrap_initial_production_runtime(
    user_id: str,
    *,
    candidate_paths: Mapping[str, str] | None = None,
    candidate_metadata: Mapping[str, Any] | None = None,
    runtime_validation: Mapping[str, Any] | None = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Publish an initial production runtime only when no last-good runtime exists.

    The function fails closed for rejected/unknown candidates and never replaces a
    valid active runtime pointer.  It is for the first trained model only; later
    candidates remain shadow/report-only until the explicit promotion flow.
    """
    safe = slugify_username(user_id)
    if _env_disabled() and not force:
        return {"ok": False, "changed": False, "reason": "initial_production_bootstrap_disabled"}
    current = active_runtime_state(safe)
    if bool(current.get("ok")):
        return {"ok": True, "changed": False, "reason": "active_runtime_already_valid", "protectedSessionsAvailable": True, "runtimeValidation": current.get("validation")}

    candidate_paths = dict(candidate_paths or _user_model_paths(safe))
    meta = _load_candidate_metadata(candidate_paths, candidate_metadata)
    if not meta:
        return {"ok": False, "changed": False, "reason": "candidate_metadata_missing", "protectedSessionsAvailable": False}
    status = _candidate_status(meta)
    if status in _BOOTSTRAP_REJECTED_STATUSES:
        return {"ok": False, "changed": False, "reason": f"candidate_status_rejected:{status}", "candidate_status": status, "protectedSessionsAvailable": False}
    if status not in _BOOTSTRAP_ALLOWED_STATUSES:
        return {"ok": False, "changed": False, "reason": f"candidate_status_not_bootstrap_allowed:{status or 'missing'}", "candidate_status": status, "protectedSessionsAvailable": False}
    valid, reason = _validate_candidate_artifacts(candidate_paths, meta)
    if not valid:
        return {"ok": False, "changed": False, "reason": reason, "candidate_status": status, "protectedSessionsAvailable": False}

    production_paths = _user_production_paths(safe)
    production_base = str(production_paths["base"])
    parent = os.path.dirname(production_base)
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    staging_base = os.path.join(parent, f"production_bundle.initial_bootstrap_staging_{timestamp}_{os.getpid()}")
    backup_base = os.path.join(parent, f"production_bundle.initial_bootstrap_backup_{timestamp}_{os.getpid()}")
    staging_paths = dict(production_paths)
    staging_paths["base"] = staging_base
    for key, path in list(staging_paths.items()):
        if key != "base":
            staging_paths[key] = os.path.join(staging_base, os.path.basename(str(path)))

    pointer_path = _active_runtime_pointer_path(safe)
    pointer_had_file = os.path.exists(pointer_path)
    pointer_backup = f"{pointer_path}.core22e_backup"
    try:
        _remove_path(staging_base)
        os.makedirs(staging_base, exist_ok=True)
        _copy_file(candidate_paths["model"], staging_paths["model"])
        save_model_hash(staging_paths["model"])
        published_meta = _build_initial_production_metadata(meta, source_status=status)
        atomic_write_text(staging_paths["metadata"], json.dumps(published_meta, indent=2, ensure_ascii=False))
        save_metadata_hash(staging_paths["metadata"])
        if _artifact_exists(candidate_paths.get("classifier")):
            _copy_file(candidate_paths["classifier"], staging_paths["classifier"])
            save_user_classifier_hash(staging_paths["classifier"])
        else:
            _remove_path(staging_paths["classifier"])
            remove_user_classifier_hash(staging_paths["classifier"])
        _copy_optional_file(candidate_paths.get("evaluation_report"), staging_paths.get("evaluation_report"))
        _copy_optional_file(candidate_paths.get("evaluation_summary"), staging_paths.get("evaluation_summary"))
        staging_validation = validate_runtime_bundle_for_activation(staging_paths)
        if not bool(staging_validation.get("ok")):
            return {"ok": False, "changed": False, "reason": "staging_runtime_invalid:" + str(staging_validation.get("reason") or "unknown"), "runtimeValidation": staging_validation, "protectedSessionsAvailable": False}

        _remove_path(backup_base)
        if os.path.exists(production_base):
            os.replace(production_base, backup_base)
        os.replace(staging_base, production_base)
        if pointer_had_file:
            try:
                shutil.copy2(pointer_path, pointer_backup)
            except OSError:
                pass
        try:
            production_validation = validate_runtime_bundle_for_activation(production_paths)
            if not bool(production_validation.get("ok")):
                raise RuntimeError("production_runtime_invalid:" + str(production_validation.get("reason") or "unknown"))
            pointer_payload = write_active_runtime_pointer(safe, production_paths, source=BOOTSTRAP_SOURCE)
        except Exception:
            _remove_path(production_base)
            if os.path.exists(backup_base):
                os.replace(backup_base, production_base)
            if pointer_had_file and os.path.exists(pointer_backup):
                shutil.copy2(pointer_backup, pointer_path)
            elif not pointer_had_file:
                _remove_path(pointer_path)
            clear_runtime_model_cache(safe)
            raise
        finally:
            _remove_path(pointer_backup)
        _remove_path(backup_base)
        clear_runtime_model_cache(safe)
        return {
            "ok": True,
            "changed": True,
            "reason": "initial_production_bootstrap_activated",
            "source": BOOTSTRAP_SOURCE,
            "candidate_status_before_bootstrap": status,
            "protectedSessionsAvailable": True,
            "protected_sessions_available": True,
            "productionReady": True,
            "production_ready": True,
            "runtimeValidation": production_validation,
            "activePointer": pointer_payload,
            "rollbackReady": True,
        }
    except Exception as exc:
        return {"ok": False, "changed": False, "reason": f"initial_production_bootstrap_failed_safe:{exc}", "protectedSessionsAvailable": False}
    finally:
        _remove_path(staging_base)


__all__ = [
    "BOOTSTRAP_SOURCE",
    "FALLBACK_SOURCE",
    "active_runtime_state",
    "last_good_production_overlay",
    "maybe_bootstrap_initial_production_runtime",
]
