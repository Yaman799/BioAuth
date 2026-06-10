"""Runtime bundle loading helpers.

Structure-only split from model_inference.py. This module is responsible for
loading and validating active production runtime bundles and context bundles.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

import logging
import os
import numpy as np

from artifact_integrity import load_classifier, load_metadata, load_model
from model_metadata import (
    load_model_metadata_cached,
    resolve_active_runtime_paths,
    resolve_active_runtime_paths_with_validation,
    runtime_deep_contract_state,
    runtime_feature_schema_mismatch_reason,
    validate_runtime_bundle_for_activation,
)

LOGGER = logging.getLogger(__name__)




def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _developer_runtime_fallback_requested() -> bool:
    """Return true only for explicit Developer Mode runtime simulation workers.

    This is intentionally environment-gated so normal production runtime
    resolution keeps requiring a signed active production pointer.  The bridge
    sets these variables only after the backend-owned Developer UI shadow pause
    simulation is active.
    """

    return bool(
        _env_flag("BIOAUTH_DEV_PRODUCTION_READY_SIMULATION")
        and _env_flag("BIOAUTH_ALLOW_SHADOW_CANDIDATE_RUNTIME_FALLBACK")
        and str(os.environ.get("BIOAUTH_RUNTIME_BUNDLE_SOURCE", "") or "").strip().lower()
        == "developer_shadow_candidate"
    )


def _candidate_status_is_shadow_approved(meta: Mapping[str, Any] | None) -> bool:
    if not isinstance(meta, Mapping):
        return False
    for key in ("model_status", "candidate_status", "approval_status", "candidate_model_status"):
        value = str(meta.get(key) or "").strip().lower()
        if value == "approved_for_shadow":
            return True
    return False


def _bundle_requires_classifier(meta: Mapping[str, Any] | None) -> bool:
    if not isinstance(meta, Mapping):
        return False
    supervised = meta.get("supervised_classifier")
    if isinstance(supervised, Mapping) and bool(supervised.get("enabled")):
        return True
    if str(meta.get("classifier_family") or "").strip():
        return True
    return bool(str(meta.get("classifier") or "").strip())


def _validate_shadow_candidate_runtime_bundle(paths: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """Validate a shadow-approved candidate for Developer Mode runtime only.

    Unlike production activation validation, this does not require
    production bundle metadata.  It still validates the
    runtime schema, artifact integrity/loadability, optional classifier, and
    candidate approval state.  It never writes a production pointer.
    """

    if not isinstance(paths, dict):
        return {"ok": False, "reason": "runtime_paths_missing", "metadata": None, "paths": paths}
    model_path = str(paths.get("model") or "")
    metadata_path = str(paths.get("metadata") or "")
    classifier_path = str(paths.get("classifier") or "")
    if not model_path or not os.path.exists(model_path):
        return {"ok": False, "reason": "candidate_model_missing", "metadata": None, "paths": paths}
    if not metadata_path or not os.path.exists(metadata_path):
        return {"ok": False, "reason": "candidate_metadata_missing", "metadata": None, "paths": paths}
    try:
        meta = load_metadata(metadata_path) or {}
    except Exception as exc:
        LOGGER.warning("Developer runtime candidate metadata validation failed for %s", os.path.basename(metadata_path), exc_info=True)
        return {"ok": False, "reason": f"candidate_metadata_invalid:{exc}", "metadata": None, "paths": paths}
    if not _candidate_status_is_shadow_approved(meta):
        return {"ok": False, "reason": "candidate_not_approved_for_shadow", "metadata": meta, "paths": paths}
    schema_reason = runtime_feature_schema_mismatch_reason(dict(meta))
    if schema_reason:
        return {"ok": False, "reason": schema_reason, "metadata": meta, "paths": paths}
    try:
        load_model(model_path)
    except Exception as exc:
        LOGGER.warning("Developer runtime candidate model validation failed for %s", os.path.basename(model_path), exc_info=True)
        return {"ok": False, "reason": f"candidate_model_invalid:{exc}", "metadata": meta, "paths": paths}
    required = _bundle_requires_classifier(dict(meta))
    if required and (not classifier_path or not os.path.exists(classifier_path)):
        return {"ok": False, "reason": "candidate_classifier_required_missing", "metadata": meta, "paths": paths}
    if classifier_path and os.path.exists(classifier_path):
        try:
            load_classifier(classifier_path)
        except Exception as exc:
            LOGGER.warning("Developer runtime candidate classifier validation failed for %s", os.path.basename(classifier_path), exc_info=True)
            return {"ok": False, "reason": f"candidate_classifier_invalid:{exc}", "metadata": meta, "paths": paths}
    runtime_meta = dict(meta)
    runtime_meta.update(
        {
            "dev_runtime_bundle_fallback": True,
            "runtime_bundle_source": "developer_shadow_candidate",
            "production_ready_real": False,
            "production_ready_effective": True,
        }
    )
    return {
        "ok": True,
        "reason": "developer_shadow_candidate_runtime_fallback",
        "metadata": runtime_meta,
        "paths": paths,
        "deep_runtime": runtime_deep_contract_state(runtime_meta),
        "artifact_identity": {"developer_shadow_candidate": "true"},
        "developer_shadow_candidate_fallback": True,
        "runtime_bundle_source": "developer_shadow_candidate",
        "dev_runtime_bundle_fallback": True,
    }


def resolve_developer_shadow_candidate_runtime_paths_with_validation(user_id: str) -> Tuple[Optional[Dict[str, str]], Dict[str, Any]]:
    from metadata_core.paths import _user_model_paths
    from utils.identity import slugify_username

    safe = slugify_username(user_id)
    if not _developer_runtime_fallback_requested():
        return None, {
            "ok": False,
            "reason": "developer_shadow_candidate_fallback_not_enabled",
            "metadata": None,
            "paths": None,
            "developer_shadow_candidate_fallback": False,
        }
    candidate = _user_model_paths(safe)
    validation = _validate_shadow_candidate_runtime_bundle(candidate)
    if bool(validation.get("ok")):
        return candidate, validation
    validation = dict(validation)
    validation.setdefault("developer_shadow_candidate_fallback", False)
    return None, validation


def _resolve_context_bundle_path(metadata_file: str, relative_path: str | None) -> str:
    if not relative_path:
        return ""
    if os.path.isabs(relative_path):
        return relative_path
    return os.path.join(os.path.dirname(metadata_file), relative_path)

def _load_runtime_context_bundles(metadata_file: str, meta: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    bundles_info = (((meta or {}).get("context_models") or {}).get("bundles") or {}) if isinstance(meta, Mapping) else {}
    loaded: dict[str, dict[str, Any]] = {}
    for context_name, bundle_info in bundles_info.items():
        if not isinstance(bundle_info, Mapping):
            continue
        model_path = _resolve_context_bundle_path(metadata_file, str(bundle_info.get("model") or ""))
        metadata_path = _resolve_context_bundle_path(metadata_file, str(bundle_info.get("metadata") or ""))
        classifier_path = _resolve_context_bundle_path(metadata_file, bundle_info.get("classifier"))
        if not model_path or not metadata_path or not os.path.exists(model_path) or not os.path.exists(metadata_path):
            continue
        try:
            bundle_meta = load_metadata(metadata_path) or {}
            bundle_model = load_model(model_path)
            bundle_classifier = load_classifier(classifier_path) if classifier_path and os.path.exists(classifier_path) else None
            if bundle_model is None:
                continue
            loaded[str(context_name)] = {
                "model": bundle_model,
                "metadata": bundle_meta,
                "classifier": bundle_classifier,
            }
        except Exception as exc:
            LOGGER.warning("Skipping context bundle %s because it could not be loaded: %s", context_name, exc)
    return loaded

def _resolve_runtime_window_scales(meta: Mapping[str, Any] | None) -> list[float]:
    if not isinstance(meta, Mapping):
        return []
    raw = meta.get("active_window_scales") or meta.get("window_scales") or []
    if not isinstance(raw, (list, tuple)):
        return []
    resolved: list[float] = []
    seen = set()
    for value in raw:
        try:
            scale = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if not np.isfinite(scale) or scale <= 0.0:
            continue
        rounded = round(scale, 6)
        if rounded in seen:
            continue
        seen.add(rounded)
        resolved.append(float(scale))
    resolved.sort()
    return resolved

def _runtime_metadata_allows_model_load(meta: Mapping[str, Any] | None) -> bool:
    if not isinstance(meta, Mapping):
        return False
    if str(meta.get("bundle_role") or "").strip().lower() != "production":
        return False
    return str(meta.get("model_status") or "").strip().lower() == "approved_for_production"

def _runtime_schema_allows_model_load(meta: Mapping[str, Any] | None) -> tuple[bool, str | None]:
    if not isinstance(meta, Mapping):
        return False, "metadata_missing"
    reason = runtime_feature_schema_mismatch_reason(dict(meta))
    return reason is None, reason

def _load_user_runtime_bundle(user_id: str) -> Optional[Dict[str, Any]]:
    from utils.identity import slugify_username

    safe = slugify_username(user_id)
    paths, validation = resolve_active_runtime_paths_with_validation(safe)
    if not paths and _env_flag("BIOAUTH_DEMO_CLASSIC_PROTECTED"):
        try:
            from metadata_core.demo_classic_runtime_activation import (
                activate_existing_candidate_runtime_for_demo,
            )

            activation = activate_existing_candidate_runtime_for_demo(safe)
            if activation.get("ok"):
                paths, validation = resolve_active_runtime_paths_with_validation(safe)
                LOGGER.warning(
                    "Runtime model load activated protected runtime pointer for %s: %s",
                    safe,
                    activation.get("reason"),
                )
            else:
                LOGGER.warning(
                    "Runtime model load could not activate protected runtime pointer for %s: %s",
                    safe,
                    activation.get("reason"),
                )
        except Exception:
            LOGGER.warning("Runtime model load protected runtime activation failed for %s", safe, exc_info=True)
    if not paths and _developer_runtime_fallback_requested():
        fallback_paths, fallback_validation = resolve_developer_shadow_candidate_runtime_paths_with_validation(safe)
        if fallback_paths and bool(fallback_validation.get("ok")):
            paths, validation = fallback_paths, fallback_validation
            LOGGER.warning(
                "Runtime model load using Developer Mode shadow candidate fallback for %s; no real production pointer was written.",
                safe,
            )
        else:
            fallback_reason = fallback_validation.get("reason") if isinstance(fallback_validation, dict) else "developer_shadow_candidate_fallback_failed"
            LOGGER.warning(
                "Runtime model load blocked for %s because no active production bundle pointer was found and Developer Mode shadow candidate fallback failed: %s",
                safe,
                fallback_reason,
            )
            return None
    if not paths:
        reason = validation.get("reason") if isinstance(validation, dict) else "runtime_pointer_missing"
        LOGGER.warning(
            "Runtime model load blocked for %s because no active production bundle is registered or validation failed: %s. "
            "Developer shadow candidate fallback is not active/allowed.",
            safe,
            reason,
        )
        return None
    if not validation.get("ok"):
        LOGGER.warning("Runtime model load blocked for %s because the active runtime bundle failed validation: %s", safe, validation.get("reason"))
        return None
    try:
        meta = validation.get("metadata") if isinstance(validation.get("metadata"), dict) else None
        if meta is None:
            meta = load_model_metadata_cached(paths["metadata"]) if os.path.exists(paths["metadata"]) else None
    except Exception as exc:
        LOGGER.warning("Runtime model load blocked for %s because runtime metadata could not be loaded: %s", safe, exc)
        return None
    schema_ok, schema_reason = _runtime_schema_allows_model_load(meta)
    if not schema_ok:
        LOGGER.warning("Runtime model load blocked for %s because the active runtime schema is incompatible: %s", safe, schema_reason)
        return None
    developer_fallback = bool(validation.get("developer_shadow_candidate_fallback") or (isinstance(meta, Mapping) and meta.get("dev_runtime_bundle_fallback")))
    if not developer_fallback and not _runtime_metadata_allows_model_load(meta):
        LOGGER.warning("Runtime model load blocked for %s because the active bundle is not production-approved.", safe)
        return None
    if developer_fallback and not _candidate_status_is_shadow_approved(meta):
        LOGGER.warning("Runtime model load blocked for %s because Developer Mode fallback candidate is not approved for shadow.", safe)
        return None
    try:
        model = load_model(paths["model"])
        classifier = load_classifier(paths["classifier"]) if os.path.exists(paths["classifier"]) else None
    except Exception as exc:
        LOGGER.warning("Runtime model load blocked for %s because the active runtime bundle failed verification: %s", safe, exc)
        return None
    result = {
        "model": model,
        "metadata": meta,
        "classifier": classifier,
        "metadata_file": paths["metadata"],
        "classifier_file": paths["classifier"],
        "paths": paths,
        "deep_runtime": runtime_deep_contract_state(dict(meta or {})),
    }
    if developer_fallback:
        result.update({
            "dev_runtime_bundle_fallback": True,
            "runtime_bundle_source": "developer_shadow_candidate",
            "production_ready_real": False,
            "production_ready_effective": True,
        })
    return result
