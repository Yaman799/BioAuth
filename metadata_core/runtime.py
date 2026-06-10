"""Runtime bundle validation and pointer resolution helpers."""

from __future__ import annotations

import hashlib
import hmac
import copy
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from deep_runtime import build_deep_runtime_metadata_contract
from security import atomic_write_text
from utils.identity import slugify_username

from metadata_core.constants import (
    ACTIVE_RUNTIME_POINTER_FILE,
    ACTIVE_WINDOW_SCALES,
    FEATURE_SCHEMA_VERSION,
    FEATURE_WINDOW_STRATEGY,
    RUNTIME_POINTER_HMAC_LABEL,
    RUNTIME_POINTER_SCHEMA_VERSION,
)
from metadata_core.paths import _active_runtime_pointer_path, _bundle_paths, _user_model_dir


_RUNTIME_CACHE_LOCK = threading.RLock()
_RUNTIME_CACHE_FAILURE_TTL_SECONDS = 2.0
_RUNTIME_POINTER_CACHE: Dict[str, Dict[str, Any]] = {}
_RUNTIME_VALIDATION_CACHE: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
_MODEL_METADATA_CACHE: Dict[str, Dict[str, Any]] = {}
LOGGER = logging.getLogger(__name__)


def _now_monotonic() -> float:
    try:
        return time.monotonic()
    except RuntimeError:
        return time.time()


def _safe_deepcopy(value: Any) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:
        LOGGER.debug("Runtime cache deepcopy failed; returning original value.", exc_info=True)
        return value


def _cache_bool(timing_collector: Optional[Dict[str, Any]], key: str, value: bool) -> None:
    if isinstance(timing_collector, dict):
        timing_collector[key] = bool(value)


def _cache_timing_add(timing_collector: Optional[Dict[str, Any]], key: str, elapsed_ms: int) -> None:
    if not isinstance(timing_collector, dict):
        return
    try:
        timing_collector[key] = int(timing_collector.get(key, 0) or 0) + max(0, int(elapsed_ms))
    except (TypeError, ValueError, OverflowError):
        timing_collector[key] = max(0, int(elapsed_ms or 0))


def _elapsed_ms(started_at: float) -> int:
    try:
        return max(0, int(round((_now_monotonic() - float(started_at)) * 1000.0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _file_signature(path: Any) -> Tuple[str, bool, int, int]:
    resolved = os.path.abspath(str(path or "")) if path not in (None, "") else ""
    if not resolved:
        return ("", False, 0, 0)
    try:
        st = os.stat(resolved)
        return (resolved, True, int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))), int(st.st_size))
    except OSError:
        return (resolved, False, 0, 0)


def _integrity_sidecar_signature(path: Any, filename: str) -> Tuple[str, bool, int, int]:
    resolved = os.path.abspath(str(path or "")) if path not in (None, "") else ""
    if not resolved:
        return ("", False, 0, 0)
    return _file_signature(os.path.join(os.path.dirname(resolved), filename))


def _runtime_bundle_signature(paths: Optional[Dict[str, str]]) -> Tuple[Any, ...]:
    data = paths if isinstance(paths, dict) else {}
    model_path = str(data.get("model") or "")
    metadata_path = str(data.get("metadata") or "")
    classifier_path = str(data.get("classifier") or "")
    return (
        _file_signature(model_path),
        _integrity_sidecar_signature(model_path, "model.hash"),
        _file_signature(metadata_path),
        _integrity_sidecar_signature(metadata_path, "metadata.hash"),
        _file_signature(classifier_path),
        _integrity_sidecar_signature(classifier_path, "classifier.hash"),
    )


def _metadata_version(meta: Any) -> str:
    if not isinstance(meta, dict):
        return ""
    for key in (
        "metadata_version",
        "runtime_metadata_version",
        "runtime_schema_policy_version",
        "schema_version",
        "feature_schema_version",
    ):
        value = meta.get(key)
        if value not in (None, ""):
            return f"{key}:{value}"
    return ""


def _file_sha256_identity(path: Any) -> str:
    resolved = os.path.abspath(str(path or "")) if path not in (None, "") else ""
    if not resolved or not os.path.isfile(resolved):
        return ""
    digest = hashlib.sha256()
    with open(resolved, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _runtime_artifact_identity(paths: Optional[Dict[str, str]]) -> Dict[str, str]:
    data = paths if isinstance(paths, dict) else {}
    identity = {
        "bundle_base": os.path.abspath(str(data.get("base") or "")) if data.get("base") else "",
        "model_sha256": _file_sha256_identity(data.get("model")),
        "metadata_sha256": _file_sha256_identity(data.get("metadata")),
        "classifier_sha256": _file_sha256_identity(data.get("classifier")),
    }
    return {key: value for key, value in identity.items() if value}


def _source_is_shadow_or_candidate(source: Any) -> bool:
    text = str(source or "").strip().lower()
    if not text:
        return True
    tokens = {"shadow", "candidate", "diagnostic", "evidence"}
    return any(token in text for token in tokens)


def _cache_entry_usable(entry: Dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    if bool(entry.get("ok", False)):
        return True
    expires_at = float(entry.get("expires_at", 0.0) or 0.0)
    return bool(expires_at and _now_monotonic() <= expires_at)


def clear_runtime_model_cache(user_id: str | None = None) -> None:
    """Clear safe runtime/model dashboard caches.

    The optional user argument is accepted for mutation hooks; caches are keyed
    by file signatures, so clearing globally is safe and simpler than attempting
    to retain stale per-user pointer state after promotions or rollbacks.
    """
    with _RUNTIME_CACHE_LOCK:
        _RUNTIME_POINTER_CACHE.clear()
        _RUNTIME_VALIDATION_CACHE.clear()
        _MODEL_METADATA_CACHE.clear()


def load_model_metadata_cached(metadata_path: str, *, loader=None, timing_collector: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    path = os.path.abspath(str(metadata_path or ""))
    signature = _file_signature(path)
    with _RUNTIME_CACHE_LOCK:
        entry = _MODEL_METADATA_CACHE.get(path)
        if isinstance(entry, dict) and entry.get("signature") == signature and _cache_entry_usable(entry):
            _cache_bool(timing_collector, "model_metadata_cache_hit", True)
            return _safe_deepcopy(entry.get("metadata"))
    _cache_bool(timing_collector, "model_metadata_cache_hit", False)
    if not path or not signature[1]:
        with _RUNTIME_CACHE_LOCK:
            _MODEL_METADATA_CACHE[path] = {
                "signature": signature,
                "ok": False,
                "metadata": None,
                "metadata_version": "",
                "expires_at": _now_monotonic() + _RUNTIME_CACHE_FAILURE_TTL_SECONDS,
            }
        return None
    if loader is None:
        from artifact_integrity import load_metadata as loader
    meta = loader(path)
    if meta is not None and not isinstance(meta, dict):
        meta = {}
    with _RUNTIME_CACHE_LOCK:
        _MODEL_METADATA_CACHE[path] = {
            "signature": signature,
            "ok": True,
            "metadata": _safe_deepcopy(meta),
            "metadata_version": _metadata_version(meta),
            "expires_at": 0.0,
        }
    return _safe_deepcopy(meta)


def _normalized_runtime_window_scales(values: Any) -> List[float]:
    raw = values if isinstance(values, (list, tuple)) else [values]
    resolved: List[float] = []
    seen = set()
    for value in raw:
        try:
            scale = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if scale <= 0.0:
            continue
        rounded = round(scale, 6)
        if rounded in seen:
            continue
        seen.add(rounded)
        resolved.append(float(scale))
    resolved.sort()
    return resolved


def runtime_feature_schema_mismatch_reason(meta: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(meta, dict):
        return "metadata_missing"
    feature_schema_version = str(meta.get("feature_schema_version") or "").strip()
    if feature_schema_version != FEATURE_SCHEMA_VERSION:
        return f"feature_schema_version_mismatch:{feature_schema_version or 'missing'}->{FEATURE_SCHEMA_VERSION}"
    window_strategy = str(meta.get("feature_window_strategy") or "").strip()
    if window_strategy != FEATURE_WINDOW_STRATEGY:
        return f"feature_window_strategy_mismatch:{window_strategy or 'missing'}->{FEATURE_WINDOW_STRATEGY}"
    actual_scales = _normalized_runtime_window_scales(meta.get("active_window_scales") or meta.get("window_scales") or [])
    expected_scales = _normalized_runtime_window_scales(ACTIVE_WINDOW_SCALES)
    if actual_scales != expected_scales:
        return f"active_window_scales_mismatch:{actual_scales}->{expected_scales}"
    return None


def runtime_feature_schema_compatible(meta: Optional[Dict[str, Any]]) -> bool:
    return runtime_feature_schema_mismatch_reason(meta) is None


def runtime_deep_contract_state(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    template = build_deep_runtime_metadata_contract()
    if not isinstance(meta, dict):
        return template
    contract = dict(template)
    incoming = meta.get("deep_runtime")
    if isinstance(incoming, dict):
        contract.update({k: v for k, v in incoming.items() if k != "sequence_model"})
        sequence_model = dict(template.get("sequence_model") or {})
        if isinstance(incoming.get("sequence_model"), dict):
            sequence_model.update(dict(incoming.get("sequence_model") or {}))
        contract["sequence_model"] = sequence_model
    return contract


def _runtime_pointer_hmac_key() -> bytes:
    from security import get_or_create_key

    return hmac.new(get_or_create_key(), RUNTIME_POINTER_HMAC_LABEL, hashlib.sha256).digest()


def canonical_runtime_pointer_json(data: Dict[str, Any]) -> str:
    body = {k: v for k, v in dict(data or {}).items() if k != "_integrity"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_runtime_pointer_payload(data: Dict[str, Any]) -> str:
    payload = canonical_runtime_pointer_json(data)
    return hmac.new(_runtime_pointer_hmac_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_runtime_pointer_payload(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    signature = data.get("_integrity")
    if not signature or not isinstance(signature, str):
        return False
    expected = sign_runtime_pointer_payload({k: v for k, v in data.items() if k != "_integrity"})
    return hmac.compare_digest(expected, signature)


def _runtime_bundle_requires_classifier(meta: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(meta, dict):
        return False
    supervised = meta.get("supervised_classifier")
    if isinstance(supervised, dict) and bool(supervised.get("enabled")):
        return True
    if str(meta.get("classifier_family") or "").strip():
        return True
    return bool(str(meta.get("classifier") or "").strip())


def _validate_runtime_bundle_for_activation_uncached(paths: Optional[Dict[str, str]]) -> Dict[str, Any]:
    if not isinstance(paths, dict):
        return {"ok": False, "reason": "runtime_paths_missing", "metadata": None, "paths": paths}
    model_path = str(paths.get("model") or "")
    metadata_path = str(paths.get("metadata") or "")
    classifier_path = str(paths.get("classifier") or "")
    if not model_path or not os.path.exists(model_path):
        return {"ok": False, "reason": "model_missing", "metadata": None, "paths": paths}
    if not metadata_path or not os.path.exists(metadata_path):
        return {"ok": False, "reason": "metadata_missing", "metadata": None, "paths": paths}
    try:
        from artifact_integrity import load_classifier, load_metadata, load_model

        meta = load_metadata(metadata_path)
    except Exception as exc:
        LOGGER.warning("Runtime bundle metadata validation failed for %s", os.path.basename(metadata_path), exc_info=True)
        return {"ok": False, "reason": f"metadata_invalid:{exc}", "metadata": None, "paths": paths}
    schema_reason = runtime_feature_schema_mismatch_reason(meta)
    if schema_reason:
        return {"ok": False, "reason": schema_reason, "metadata": meta, "paths": paths}
    if str(meta.get("bundle_role") or "").strip().lower() != "production":
        return {"ok": False, "reason": "bundle_role_not_production", "metadata": meta, "paths": paths}
    if str(meta.get("model_status") or "").strip().lower() != "approved_for_production":
        return {"ok": False, "reason": "model_not_approved_for_production", "metadata": meta, "paths": paths}
    try:
        load_model(model_path)
    except Exception as exc:
        LOGGER.warning("Runtime bundle model validation failed for %s", os.path.basename(model_path), exc_info=True)
        return {"ok": False, "reason": f"model_invalid:{exc}", "metadata": meta, "paths": paths}
    required = _runtime_bundle_requires_classifier(meta)
    if required and (not classifier_path or not os.path.exists(classifier_path)):
        return {"ok": False, "reason": "classifier_required_missing", "metadata": meta, "paths": paths}
    if classifier_path and os.path.exists(classifier_path):
        try:
            load_classifier(classifier_path)
        except Exception as exc:
            LOGGER.warning("Runtime bundle classifier validation failed for %s", os.path.basename(classifier_path), exc_info=True)
            return {"ok": False, "reason": f"classifier_invalid:{exc}", "metadata": meta, "paths": paths}
    return {
        "ok": True,
        "reason": "ok",
        "metadata": meta,
        "paths": paths,
        "deep_runtime": runtime_deep_contract_state(meta),
        "artifact_identity": _runtime_artifact_identity(paths),
    }


def validate_runtime_bundle_for_activation(paths: Optional[Dict[str, str]], *, timing_collector: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(paths, dict):
        _cache_bool(timing_collector, "runtime_validation_cache_hit", False)
        return _validate_runtime_bundle_for_activation_uncached(paths)
    signature = _runtime_bundle_signature(paths)
    key = tuple(signature)
    with _RUNTIME_CACHE_LOCK:
        entry = _RUNTIME_VALIDATION_CACHE.get(key)
        if isinstance(entry, dict) and entry.get("signature") == signature and _cache_entry_usable(entry):
            _cache_bool(timing_collector, "runtime_validation_cache_hit", True)
            return _safe_deepcopy(entry.get("result") or {})
    _cache_bool(timing_collector, "runtime_validation_cache_hit", False)
    result = _validate_runtime_bundle_for_activation_uncached(paths)
    ok = bool(isinstance(result, dict) and result.get("ok"))
    meta = result.get("metadata") if isinstance(result, dict) else None
    with _RUNTIME_CACHE_LOCK:
        _RUNTIME_VALIDATION_CACHE[key] = {
            "signature": signature,
            "ok": ok,
            "metadata_version": _metadata_version(meta),
            "result": _safe_deepcopy(result),
            "expires_at": 0.0 if ok else (_now_monotonic() + _RUNTIME_CACHE_FAILURE_TTL_SECONDS),
        }
    return _safe_deepcopy(result)




def _read_active_runtime_pointer(user_id: str) -> Optional[Dict[str, Any]]:
    path = _active_runtime_pointer_path(user_id)
    if not os.path.exists(path):
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8") or "{}")
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed reading runtime pointer for %s: %s", user_id, exc)
        return None
    if not isinstance(payload, dict):
        return None
    if verify_runtime_pointer_payload(payload):
        return payload
    if payload.get("schema_version") == "runtime-pointer-v1" and "_integrity" not in payload:
        safe = slugify_username(user_id)
        bundle_base = str(payload.get("bundle_base") or "").strip()
        if bundle_base:
            candidate = _bundle_paths(os.path.abspath(os.path.join(_user_model_dir(safe), bundle_base)))
            if validate_runtime_bundle_for_activation(candidate).get("ok"):
                migrated = dict(payload)
                migrated["schema_version"] = RUNTIME_POINTER_SCHEMA_VERSION
                migrated["migrated_from"] = "runtime-pointer-v1"
                migrated["_integrity"] = sign_runtime_pointer_payload(migrated)
                try:
                    atomic_write_text(path, json.dumps(migrated, indent=2, ensure_ascii=False))
                except Exception:
                    LOGGER.warning("Failed writing migrated runtime pointer for %s", safe, exc_info=True)
                return migrated
    logging.getLogger(__name__).warning("Runtime pointer integrity verification failed for %s", user_id)
    return None


def write_active_runtime_pointer(user_id: str, bundle_paths: Dict[str, str], *, source: str = "production_promotion") -> Dict[str, Any]:
    safe = slugify_username(user_id)
    source_text = str(source or "").strip()
    if _source_is_shadow_or_candidate(source_text):
        raise ValueError("active_runtime_pointer_requires_explicit_production_source")
    validation = validate_runtime_bundle_for_activation(bundle_paths)
    if not bool(validation.get("ok")):
        reason = str(validation.get("reason") or "unknown")
        raise ValueError(f"active_runtime_pointer_requires_production_bundle:{reason}")
    base = _user_model_dir(safe)
    bundle_base = os.path.relpath(str(bundle_paths.get("base") or ""), base)
    payload = {
        "schema_version": RUNTIME_POINTER_SCHEMA_VERSION,
        "active_runtime_pointer_file": ACTIVE_RUNTIME_POINTER_FILE,
        "bundle_base": bundle_base,
        "model_relpath": os.path.relpath(str(bundle_paths.get("model") or ""), base),
        "classifier_relpath": os.path.relpath(str(bundle_paths.get("classifier") or ""), base),
        "metadata_relpath": os.path.relpath(str(bundle_paths.get("metadata") or ""), base),
        "evaluation_report_relpath": os.path.relpath(str(bundle_paths.get("evaluation_report") or ""), base),
        "evaluation_summary_relpath": os.path.relpath(str(bundle_paths.get("evaluation_summary") or ""), base),
        "source": source_text,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": safe,
        "production_artifact_identity": dict(validation.get("artifact_identity") or {}),
    }
    payload["_integrity"] = sign_runtime_pointer_payload(payload)
    os.makedirs(base, exist_ok=True)
    atomic_write_text(_active_runtime_pointer_path(safe), json.dumps(payload, indent=2, ensure_ascii=False))
    clear_runtime_model_cache(safe)
    return payload


def _read_active_runtime_pointer_cached(user_id: str, *, timing_collector: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    safe = slugify_username(user_id)
    pointer_path = _active_runtime_pointer_path(safe)
    signature = _file_signature(pointer_path)
    key = os.path.abspath(pointer_path)
    with _RUNTIME_CACHE_LOCK:
        entry = _RUNTIME_POINTER_CACHE.get(key)
        if isinstance(entry, dict) and entry.get("signature") == signature and _cache_entry_usable(entry):
            _cache_bool(timing_collector, "active_runtime_pointer_cache_hit", True)
            return _safe_deepcopy(entry.get("pointer"))
    _cache_bool(timing_collector, "active_runtime_pointer_cache_hit", False)
    pointer = _read_active_runtime_pointer(safe)
    with _RUNTIME_CACHE_LOCK:
        _RUNTIME_POINTER_CACHE[key] = {
            "signature": _file_signature(pointer_path),
            "ok": pointer is not None,
            "pointer": _safe_deepcopy(pointer),
            "expires_at": 0.0 if pointer is not None else (_now_monotonic() + _RUNTIME_CACHE_FAILURE_TTL_SECONDS),
        }
    return _safe_deepcopy(pointer)


def resolve_active_runtime_paths_with_validation(user_id: str, *, timing_collector: Optional[Dict[str, Any]] = None) -> tuple[Optional[Dict[str, str]], Dict[str, Any]]:
    safe = slugify_username(user_id)
    pointer = _read_active_runtime_pointer_cached(safe, timing_collector=timing_collector)
    if not pointer:
        reason = "runtime_pointer_invalid" if os.path.exists(_active_runtime_pointer_path(safe)) else "runtime_pointer_missing"
        return None, {"ok": False, "reason": reason, "metadata": None, "paths": None}
    bundle_base = str(pointer.get("bundle_base") or "").strip()
    if not bundle_base:
        return None, {"ok": False, "reason": "runtime_pointer_missing_bundle_base", "metadata": None, "paths": None}
    candidate = _bundle_paths(os.path.abspath(os.path.join(_user_model_dir(safe), bundle_base)))
    validation_started = _now_monotonic()
    validation = validate_runtime_bundle_for_activation(candidate, timing_collector=timing_collector)
    _cache_timing_add(timing_collector, "runtime_validation_ms", _elapsed_ms(validation_started))
    if validation.get("ok"):
        return candidate, validation
    return None, validation


def resolve_active_runtime_paths(user_id: str) -> Optional[Dict[str, str]]:
    paths, _validation = resolve_active_runtime_paths_with_validation(user_id)
    return paths


__all__ = [
    "clear_runtime_model_cache",
    "canonical_runtime_pointer_json",
    "load_model_metadata_cached",
    "resolve_active_runtime_paths",
    "resolve_active_runtime_paths_with_validation",
    "runtime_deep_contract_state",
    "runtime_feature_schema_compatible",
    "runtime_feature_schema_mismatch_reason",
    "sign_runtime_pointer_payload",
    "validate_runtime_bundle_for_activation",
    "verify_runtime_pointer_payload",
    "write_active_runtime_pointer",
]
