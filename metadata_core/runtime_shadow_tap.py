from __future__ import annotations

"""Runtime-fed, report-only shadow inference tap.

Commercial-Core-02 contract:
- production runtime remains the only owner of logger/monitor/final action;
- the shadow candidate receives a copied production runtime event;
- the candidate may score the same live session in report-only mode;
- results are written only to the privacy-safe shadow evidence ledger;
- failures and queue pressure must never block protection.

This module intentionally does not write ``session_state.json`` and does not
start shadow logger/monitor processes. The legacy independent Shadow Evidence
Monitor remains developer-only elsewhere.
"""

from dataclasses import dataclass
import hashlib
import logging
import os
import queue
import threading
import time
from typing import Any, Dict, Mapping, Optional

from artifact_integrity import load_classifier, load_metadata, load_model
from metadata_core.paths import _user_model_paths
from metadata_core.production_evidence_pipeline import append_runtime_monitor_evidence_record
from metadata_core.feature_schema_contract import (
    CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION,
    FEATURE_SCHEMA_CONTRACT_VERSION,
    WINDOW_SCHEMA_VERSION,
    build_feature_schema_contract,
)
from model_metadata import LIVE_SESSION_DIR, runtime_feature_schema_mismatch_reason
from shadow_core.background_contracts import shadow_evidence_ledger_path
from utils.identity import slugify_username

LOGGER = logging.getLogger(__name__)

RUNTIME_SHADOW_TAP_SOURCE = "runtime_shadow_evidence"
RUNTIME_SHADOW_TAP_MODE = "runtime_fed_shadow_tap"
_RUNTIME_SHADOW_TAP_POLICY_VERSION = "commercial-core-02-runtime-fed-shadow-tap-v1"
_DEFAULT_QUEUE_SIZE = 16
_HIGH_RISK_THRESHOLD = 70.0

_TAP_QUEUE: "queue.Queue[RuntimeShadowTapEvent | None]" = queue.Queue(maxsize=_DEFAULT_QUEUE_SIZE)
_TAP_WORKER_STARTED = False
_TAP_WORKER_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()
_CANDIDATE_CACHE: dict[str, tuple[str, dict[str, Any]]] = {}


@dataclass(frozen=True)
class RuntimeShadowTapEvent:
    user_id: str
    session_path: str
    production_state: Dict[str, Any]
    production_runtime: Dict[str, Any]
    production_prediction: Dict[str, Any]
    enqueued_at: float


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    return bool(default)


def runtime_shadow_tap_enabled() -> bool:
    """Return whether the commercial runtime-fed shadow tap is enabled.

    The commercial default is enabled, but it is a no-op unless an approved
    shadow candidate bundle is available. It can be disabled for diagnostics or
    emergency rollback with ``BIOAUTH_DISABLE_RUNTIME_SHADOW_TAP=1``.
    """

    if _env_flag("BIOAUTH_DISABLE_RUNTIME_SHADOW_TAP"):
        return False
    return _env_flag("BIOAUTH_ENABLE_RUNTIME_SHADOW_TAP", default=True)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "n", "off", "disabled"}:
            return False
    return default


def _file_digest(path: str) -> str:
    text = str(path or "").strip()
    if not text or not os.path.isfile(text):
        return ""
    digest = hashlib.sha256()
    try:
        with open(text, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return "sha256:" + digest.hexdigest()


def _metadata_artifact_digest(meta: Mapping[str, Any]) -> str:
    for key in ("candidate_artifact_digest", "artifact_digest", "model_digest", "bundle_digest"):
        value = meta.get(key) if isinstance(meta, Mapping) else None
        text = str(value or "").strip()
        if text:
            return text[:180]
    return ""


def _metadata_shadow_approved(meta: Mapping[str, Any]) -> bool:
    for key in ("model_status", "candidate_status", "approval_status", "candidate_model_status"):
        if str(meta.get(key) or "").strip().lower() == "approved_for_shadow":
            return True
    return False


def _bundle_requires_classifier(meta: Mapping[str, Any]) -> bool:
    supervised = meta.get("supervised_classifier")
    if isinstance(supervised, Mapping) and bool(supervised.get("enabled")):
        return True
    if str(meta.get("classifier_family") or "").strip():
        return True
    return bool(str(meta.get("classifier") or "").strip())


def _cache_key(paths: Mapping[str, str]) -> str:
    parts: list[str] = []
    for key in ("model", "metadata", "classifier"):
        path = str(paths.get(key) or "")
        try:
            stat = os.stat(path) if path else None
            parts.append(f"{key}:{path}:{stat.st_mtime_ns if stat else 0}:{stat.st_size if stat else 0}")
        except OSError:
            parts.append(f"{key}:{path}:missing")
    return "|".join(parts)


def clear_runtime_shadow_tap_cache() -> None:
    """Clear cached candidate artifacts. Intended for tests and rollback tooling."""

    with _CACHE_LOCK:
        _CANDIDATE_CACHE.clear()


def _load_shadow_candidate_bundle(user_id: str) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    safe = slugify_username(user_id or "") or "unknown"
    paths = _user_model_paths(safe)
    model_path = str(paths.get("model") or "")
    metadata_path = str(paths.get("metadata") or "")
    classifier_path = str(paths.get("classifier") or "")
    if not model_path or not os.path.exists(model_path):
        return None, {"ok": False, "reason": "candidate_model_missing", "paths": paths}
    if not metadata_path or not os.path.exists(metadata_path):
        return None, {"ok": False, "reason": "candidate_metadata_missing", "paths": paths}

    key = _cache_key(paths)
    with _CACHE_LOCK:
        cached = _CANDIDATE_CACHE.get(safe)
        if cached and cached[0] == key:
            return dict(cached[1]), {"ok": True, "reason": "cached", "paths": paths}

    try:
        meta = load_metadata(metadata_path) or {}
    except Exception as exc:
        return None, {"ok": False, "reason": f"candidate_metadata_invalid:{exc}", "paths": paths}
    if not isinstance(meta, Mapping):
        return None, {"ok": False, "reason": "candidate_metadata_invalid", "paths": paths}
    meta = dict(meta)
    if not _metadata_shadow_approved(meta):
        return None, {"ok": False, "reason": "candidate_not_approved_for_shadow", "metadata": meta, "paths": paths}
    schema_reason = runtime_feature_schema_mismatch_reason(meta)
    if schema_reason:
        return None, {"ok": False, "reason": schema_reason, "metadata": meta, "paths": paths}
    try:
        model = load_model(model_path)
    except Exception as exc:
        return None, {"ok": False, "reason": f"candidate_model_invalid:{exc}", "metadata": meta, "paths": paths}
    classifier = None
    if classifier_path and os.path.exists(classifier_path):
        try:
            classifier = load_classifier(classifier_path)
        except Exception as exc:
            return None, {"ok": False, "reason": f"candidate_classifier_invalid:{exc}", "metadata": meta, "paths": paths}
    elif _bundle_requires_classifier(meta):
        return None, {"ok": False, "reason": "candidate_classifier_required_missing", "metadata": meta, "paths": paths}

    runtime_meta = dict(meta)
    runtime_meta.update(
        {
            "runtime_bundle_source": RUNTIME_SHADOW_TAP_MODE,
            "runtime_shadow_tap": True,
            "runtime_shadow_only": True,
            "production_ready_real": False,
            "production_ready_effective": False,
        }
    )
    bundle = {
        "model": model,
        "metadata": runtime_meta,
        "classifier": classifier,
        "metadata_file": metadata_path,
        "classifier_file": classifier_path or None,
        "paths": dict(paths),
        "candidate_artifact_digest": _metadata_artifact_digest(runtime_meta) or _file_digest(model_path),
        "runtime_schema_version": str(runtime_meta.get("runtime_schema_version") or runtime_meta.get("feature_schema_version") or ""),
    }
    with _CACHE_LOCK:
        _CANDIDATE_CACHE[safe] = (key, dict(bundle))
    return bundle, {"ok": True, "reason": "candidate_loaded", "metadata": runtime_meta, "paths": paths}


def _production_artifact_digest(runtime: Mapping[str, Any]) -> str:
    meta = _as_mapping(runtime.get("metadata"))
    for key in ("artifact_digest", "bundle_digest", "production_digest", "model_digest", "candidate_artifact_digest"):
        value = meta.get(key)
        if value not in (None, ""):
            return str(value)
    paths = _as_mapping(runtime.get("paths"))
    return _file_digest(str(paths.get("model") or ""))


def _decision_from_prediction(prediction: Mapping[str, Any]) -> str:
    final = str(prediction.get("final") or prediction.get("decision") or "").strip().lower()
    risk = _as_float(prediction.get("risk"), 0.0)
    if final in {"lock", "locked", "intruder_lock", "device_locked"} or final == "intruder" or risk >= _HIGH_RISK_THRESHOLD:
        return "lock"
    if final in {"suspicious", "warning", "warn", "reject", "rejected"} or risk >= 35.0:
        return "warning"
    if final in {"legit", "trusted", "owner", "allow", "allowed", "ok", "pass"}:
        return "trusted"
    return "unknown"


def _would_lock_if_production(prediction: Mapping[str, Any], decision: str) -> bool:
    final = str(prediction.get("final") or prediction.get("decision") or "").strip().lower()
    return bool(decision == "lock" or final in {"intruder", "lock", "locked", "intruder_lock", "device_locked"} or _as_float(prediction.get("risk"), 0.0) >= _HIGH_RISK_THRESHOLD)


def _runtime_schema_from_prediction_or_runtime(prediction: Mapping[str, Any], runtime: Mapping[str, Any], fallback: str = "") -> str:
    metadata = _as_mapping(runtime.get("metadata"))
    for value in (
        metadata.get("runtime_schema_version"),
        metadata.get("feature_schema_version"),
        _as_mapping(prediction.get("deep_runtime")).get("runtime_schema_version"),
        prediction.get("feature_schema_version"),
        fallback,
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def run_runtime_fed_shadow_tap(
    *,
    user_id: str,
    session_path: str = LIVE_SESSION_DIR,
    production_state: Mapping[str, Any] | None = None,
    production_runtime: Mapping[str, Any] | None = None,
    production_prediction: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Synchronously evaluate a shadow candidate on the production live session.

    The return value is a small operational summary. Any failure is converted to
    a non-raising ``ok=False`` payload so callers can remain non-blocking.
    """

    started = time.perf_counter()
    if not runtime_shadow_tap_enabled():
        return {"ok": False, "status": "disabled", "reason": "runtime_shadow_tap_disabled"}
    safe = slugify_username(user_id or "") or "unknown"
    prod_state = dict(production_state or {})
    prod_runtime = dict(production_runtime or {})
    prod_prediction = dict(production_prediction or {})
    try:
        candidate, validation = _load_shadow_candidate_bundle(safe)
        if not candidate:
            return {
                "ok": False,
                "status": "skipped",
                "reason": str(validation.get("reason") or "candidate_unavailable"),
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
        from model_inference import predict_from_session_details

        candidate_prediction = predict_from_session_details(
            candidate.get("model"),
            session_path or LIVE_SESSION_DIR,
            metadata_file=str(candidate.get("metadata_file") or "") or None,
            classifier_file=str(candidate.get("classifier_file") or "") or None,
            metadata=_as_mapping(candidate.get("metadata")),
            classifier=candidate.get("classifier"),
        )
        if not isinstance(candidate_prediction, Mapping):
            return {"ok": False, "status": "failed", "reason": "candidate_prediction_invalid"}
        status = str(candidate_prediction.get("status") or "ok").strip().lower()
        if status != "ok":
            return {
                "ok": False,
                "status": "skipped",
                "reason": f"candidate_prediction_{status}",
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
        candidate_decision = _decision_from_prediction(candidate_prediction)
        baseline_decision = _decision_from_prediction(prod_prediction)
        candidate_would_lock = _would_lock_if_production(candidate_prediction, candidate_decision)
        baseline_would_lock = _would_lock_if_production(prod_prediction, baseline_decision)
        reason_codes = list(prod_state.get("runtime_lock_safety_reasons") or [])
        if candidate_would_lock and "shadow_evidence_lock_suppressed" not in reason_codes:
            reason_codes.append("shadow_evidence_lock_suppressed")
        runtime_schema = _runtime_schema_from_prediction_or_runtime(
            prod_prediction,
            prod_runtime,
            fallback=str(candidate.get("runtime_schema_version") or ""),
        )
        candidate_metadata = _as_mapping(candidate.get("metadata"))
        schema_contract = _as_mapping(candidate_metadata.get("feature_schema_contract")) or build_feature_schema_contract()
        schema_contract_version = str(candidate_metadata.get("feature_schema_contract_version") or schema_contract.get("contract_version") or FEATURE_SCHEMA_CONTRACT_VERSION)
        window_schema_version = str(candidate_metadata.get("window_schema_version") or schema_contract.get("window_schema_version") or WINDOW_SCHEMA_VERSION)
        feature_schema_digest = str(candidate_metadata.get("feature_schema_digest") or schema_contract.get("schema_digest") or "")
        feature_extension_profile = str(
            candidate_metadata.get("feature_extension_profile")
            or schema_contract.get("feature_extension_profile")
            or CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION
        )
        tap_state = {
            **prod_state,
            "source": RUNTIME_SHADOW_TAP_SOURCE,
            "evidence_source": RUNTIME_SHADOW_TAP_SOURCE,
            "runtime_mode": RUNTIME_SHADOW_TAP_MODE,
            "session_kind": str(prod_state.get("session_kind") or "protected"),
            "model_decision": candidate_decision,
            "decision": candidate_decision,
            "risk": int(_as_float(candidate_prediction.get("risk"), 0.0)),
            "avg_risk": _as_float(candidate_prediction.get("risk"), 0.0),
            "raw_score": _as_float(candidate_prediction.get("raw"), 0.0),
            "candidate_would_lock_if_production": bool(candidate_would_lock),
            "baseline_decision": baseline_decision,
            "baseline_risk": _as_float(prod_prediction.get("risk"), 0.0),
            "baseline_would_lock_if_production": bool(baseline_would_lock),
            "baseline_artifact_digest": _production_artifact_digest(prod_runtime),
            "runtime_schema_version": runtime_schema,
            "feature_schema_version": runtime_schema,
            "feature_schema_contract_version": schema_contract_version,
            "window_schema_version": window_schema_version,
            "feature_schema_digest": feature_schema_digest,
            "feature_extension_profile": feature_extension_profile,
            "schema_ok": True,
            "runtime_lock_safety_reasons": reason_codes,
            "runtime_shadow_tap": True,
            "runtime_shadow_tap_policy_version": _RUNTIME_SHADOW_TAP_POLICY_VERSION,
            "production_decision_changed": False,
            "production_threshold_changed": False,
            "production_model_pointer_changed": False,
            "protected_sessions_unlocked": False,
            "eligible_for_shadow_evidence": True,
            "eligible_for_direct_production_training": False,
            "production_training_allowed": False,
            "excluded_from_positive_training": True,
        }
        candidate_runtime = {
            "metadata": {
                **dict(candidate_metadata),
                "candidate_artifact_digest": str(candidate.get("candidate_artifact_digest") or ""),
                "runtime_schema_version": runtime_schema,
                "feature_schema_contract_version": schema_contract_version,
                "window_schema_version": window_schema_version,
                "feature_schema_digest": feature_schema_digest,
                "feature_extension_profile": feature_extension_profile,
                "feature_schema_contract": dict(schema_contract),
            },
            "paths": dict(_as_mapping(candidate.get("paths"))),
        }
        record = append_runtime_monitor_evidence_record(
            user_id=safe,
            state=tap_state,
            runtime=candidate_runtime,
            prediction=dict(candidate_prediction),
            ledger_path=shadow_evidence_ledger_path(safe),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return {
            "ok": True,
            "status": "recorded",
            "source": RUNTIME_SHADOW_TAP_SOURCE,
            "window_id": record.get("window_id"),
            "candidate_decision": record.get("candidate_decision"),
            "baseline_decision": record.get("baseline_decision"),
            "candidate_would_lock_if_production": bool(record.get("candidate_would_lock_if_production")),
            "elapsed_ms": elapsed_ms,
        }
    except Exception as exc:  # pragma: no cover - defensive guard for production runtime
        LOGGER.warning("runtime_fed_shadow_tap_failed for %s: %s", safe, exc, exc_info=True)
        return {
            "ok": False,
            "status": "failed",
            "reason": str(exc),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }


def _worker_loop() -> None:
    while True:
        event = _TAP_QUEUE.get()
        try:
            if event is None:
                return
            run_runtime_fed_shadow_tap(
                user_id=event.user_id,
                session_path=event.session_path,
                production_state=event.production_state,
                production_runtime=event.production_runtime,
                production_prediction=event.production_prediction,
            )
        finally:
            try:
                _TAP_QUEUE.task_done()
            except ValueError:
                pass


def _ensure_worker_started() -> None:
    global _TAP_WORKER_STARTED
    if _TAP_WORKER_STARTED:
        return
    with _TAP_WORKER_LOCK:
        if _TAP_WORKER_STARTED:
            return
        worker = threading.Thread(target=_worker_loop, name="BioAuthRuntimeShadowTap", daemon=True)
        worker.start()
        _TAP_WORKER_STARTED = True


def submit_runtime_fed_shadow_tap(
    *,
    user_id: str,
    session_path: str = LIVE_SESSION_DIR,
    production_state: Mapping[str, Any] | None = None,
    production_runtime: Mapping[str, Any] | None = None,
    production_prediction: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Queue a runtime-fed shadow event without blocking production.

    When ``BIOAUTH_RUNTIME_SHADOW_TAP_SYNC_FOR_TESTS=1`` is set, the event is
    processed synchronously to make deterministic tests possible.
    """

    if not runtime_shadow_tap_enabled():
        return {"accepted": False, "status": "disabled", "reason": "runtime_shadow_tap_disabled"}
    safe = slugify_username(user_id or "") or "unknown"
    if _env_flag("BIOAUTH_RUNTIME_SHADOW_TAP_SYNC_FOR_TESTS"):
        result = run_runtime_fed_shadow_tap(
            user_id=safe,
            session_path=session_path,
            production_state=production_state,
            production_runtime=production_runtime,
            production_prediction=production_prediction,
        )
        return {"accepted": bool(result.get("ok")), "status": str(result.get("status") or "processed"), "result": result}
    _ensure_worker_started()
    event = RuntimeShadowTapEvent(
        user_id=safe,
        session_path=session_path or LIVE_SESSION_DIR,
        production_state=dict(production_state or {}),
        production_runtime=dict(production_runtime or {}),
        production_prediction=dict(production_prediction or {}),
        enqueued_at=time.time(),
    )
    try:
        _TAP_QUEUE.put_nowait(event)
        return {"accepted": True, "status": "queued", "queue_size": int(_TAP_QUEUE.qsize())}
    except queue.Full:
        return {"accepted": False, "status": "dropped", "reason": "runtime_shadow_tap_queue_full", "queue_size": int(_TAP_QUEUE.qsize())}


__all__ = [
    "RUNTIME_SHADOW_TAP_MODE",
    "RUNTIME_SHADOW_TAP_SOURCE",
    "clear_runtime_shadow_tap_cache",
    "run_runtime_fed_shadow_tap",
    "runtime_shadow_tap_enabled",
    "submit_runtime_fed_shadow_tap",
]
