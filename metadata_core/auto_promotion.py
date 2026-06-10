"""Safe automatic production promotion for BioAuth runtime bundles.

This module only publishes a candidate bundle after the existing offline policy
has marked it approved_for_production and the resulting production runtime bundle
passes the authoritative runtime validation path. It never promotes shadow-only
models and never changes model policy thresholds.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from evaluation_core.production_evidence import ProductionEvidenceReport
from metadata_core.production_approval import build_production_eligibility_state

from artifact_integrity import load_classifier, load_metadata, load_model
from metadata_core.paths import _active_runtime_pointer_path, _user_model_paths, _user_production_paths
from metadata_core.runtime import clear_runtime_model_cache, validate_runtime_bundle_for_activation, write_active_runtime_pointer
from security import atomic_write_bytes, atomic_write_text, remove_user_classifier_hash, save_metadata_hash, save_model_hash, save_user_classifier_hash
from utils.identity import slugify_username

AUTO_PROMOTION_SOURCE = "safe_auto_promotion"
USER_APPROVED_PROMOTION_SOURCE = "user_approved_model_switch"
_REQUIRED_ALWAYS = ("model", "metadata", "evaluation_report")

_CLOSED_BETA_ADVISORY_SAFETY_KEYS = {"safety_metrics_present", "warning_per_hour", "data_coverage"}


def _security_helpers():
    """Return current security helpers, even if tests reload security after import."""
    import security as _security

    return _security


def _artifact_helpers():
    """Return current artifact-integrity helpers after any test-time reloads."""
    import artifact_integrity as _artifact_integrity

    return _artifact_integrity


def _closed_beta_gate_required(meta: Mapping[str, Any] | None = None) -> bool:
    details = _as_dict((meta or {}).get("policy_details")) if isinstance(meta, Mapping) else {}
    gate = _as_dict(details.get("closed_beta_gate"))
    if "required" in gate:
        return bool(gate.get("required"))
    if "closed_beta_gate_required" in details:
        return bool(details.get("closed_beta_gate_required"))
    mode = str(os.environ.get("BIOAUTH_CLOSED_BETA_GATE_MODE") or "").strip().lower()
    if mode in {"required", "require", "blocking", "enforced"}:
        return True
    require = str(os.environ.get("BIOAUTH_REQUIRE_CLOSED_BETA_GATE") or "").strip().lower()
    return require in {"1", "true", "yes", "required", "require", "blocking", "enforced"}


def _blocking_safety_failures(safety_results: Mapping[str, Any], meta: Mapping[str, Any]) -> list[str]:
    failed = [str(key) for key, value in safety_results.items() if value is False]
    if _closed_beta_gate_required(meta):
        return failed
    return [key for key in failed if key not in _CLOSED_BETA_ADVISORY_SAFETY_KEYS]


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_bool(source: Mapping[str, Any] | None, key: str, default: bool = False) -> bool:
    if not isinstance(source, Mapping) or key not in source:
        return bool(default)
    return bool(source.get(key))


def _artifact_exists(path: Any) -> bool:
    text = str(path or "").strip()
    return bool(text and os.path.exists(text))


def _bundle_requires_classifier(meta: Mapping[str, Any]) -> bool:
    supervised = meta.get("supervised_classifier") if isinstance(meta, Mapping) else None
    if isinstance(supervised, Mapping) and bool(supervised.get("enabled")):
        return True
    return bool(str(meta.get("classifier_family") or meta.get("classifier") or "").strip())


def _production_evidence_allows_production(meta: Mapping[str, Any]) -> tuple[bool, str]:
    payload = meta.get("production_evidence") if isinstance(meta, Mapping) else None
    if not isinstance(payload, Mapping):
        return False, "production_evidence_missing"
    try:
        evidence = ProductionEvidenceReport.from_dict(payload, allow_unknown_reason_codes=True)
    except (TypeError, ValueError):
        return False, "production_evidence_invalid"
    if not evidence.gate.allows_production_eligibility:
        return False, "production_evidence_not_passed"
    return True, "ok"


def _missing_required_artifacts(paths: Mapping[str, str], meta: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in _REQUIRED_ALWAYS:
        if not _artifact_exists(paths.get(key)):
            missing.append(key)
    if _bundle_requires_classifier(meta) and not _artifact_exists(paths.get("classifier")):
        missing.append("classifier")
    return missing


def _policy_allows_production(meta: Mapping[str, Any]) -> tuple[bool, str]:
    status = str(meta.get("model_status") or "").strip().lower()
    if status != "approved_for_production":
        return False, "model_not_approved_for_production"
    evidence_ok, evidence_reason = _production_evidence_allows_production(meta)
    if not evidence_ok:
        return False, evidence_reason
    # Classic production runtime is allowed only after model_policy produced
    # approved_for_production and Production Evidence Gate v2 passed. Hybrid/deep
    # decision influence remains governed by rollout_details/deep_runtime and may
    # still fall back to classic at runtime.
    details = _as_dict(meta.get("policy_details"))
    gate_results = _as_dict(details.get("gate_results"))
    safety_results = _as_dict(details.get("safety_gate_results"))
    if gate_results and any(value is False for value in gate_results.values()):
        return False, "policy_gate_failed"
    if safety_results and _blocking_safety_failures(safety_results, meta):
        return False, "safety_gate_failed"
    return True, "ok"


def auto_promotion_block_reason(
    *,
    settings: Mapping[str, Any] | None,
    candidate_metadata: Mapping[str, Any] | None,
    runtime_validation: Mapping[str, Any] | None,
    authenticated: bool = True,
    training_active: bool = False,
    session_flow: str = "idle",
    app_locked: bool = False,
) -> str:
    """Return an empty string only when auto-promotion may attempt a publish."""

    settings_payload = _as_dict(settings)
    meta = _as_dict(candidate_metadata)
    runtime_payload = _as_dict(runtime_validation)
    if not bool(authenticated):
        return "not_authenticated"
    if not _safe_bool(settings_payload, "auto_promote_when_production_safe_enabled", False):
        return "auto_promotion_disabled"
    if bool(training_active):
        return "training_active"
    if bool(app_locked):
        return "app_locked"
    if str(session_flow or "idle").strip().lower() != "idle":
        return "session_not_idle"
    if bool(runtime_payload.get("ok")):
        return "already_production_ready"
    allowed, reason = _policy_allows_production(meta)
    if not allowed:
        return reason
    return ""


def _copy_file(src: str, dst: str) -> None:
    with open(src, "rb") as handle:
        atomic_write_bytes(dst, handle.read())


def _copy_optional_file(src: Any, dst: Any) -> None:
    src_text = str(src or "").strip()
    dst_text = str(dst or "").strip()
    if src_text and dst_text and os.path.exists(src_text):
        _copy_file(src_text, dst_text)


def _remove_path(path: str) -> None:
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _restore_file(src: str, dst: str) -> None:
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    else:
        _remove_path(dst)


def _active_pointer_backup_path(user_id: str) -> str:
    return f"{_active_runtime_pointer_path(user_id)}.auto_promotion_backup"


def _build_published_metadata(candidate_meta: Mapping[str, Any], *, source: str, user_approval: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    published = dict(candidate_meta)
    rollout_details = _as_dict(published.get("rollout_details"))
    deep_runtime = _as_dict(published.get("deep_runtime"))
    deep_runtime.update({
        "runtime_rollout_stage": published.get("rollout_status") or rollout_details.get("rollout_status") or deep_runtime.get("runtime_rollout_stage") or "classic_only_ready",
        "runtime_shadow_diagnostics_enabled": bool(rollout_details.get("shadow_diagnostics_enabled", deep_runtime.get("runtime_shadow_diagnostics_enabled", True))),
        "runtime_rollback_to_classic_on_failure": bool(rollout_details.get("rollback_to_classic_on_failure", True)),
        "runtime_activation_blocked_reason": rollout_details.get("blocked_reason"),
        "allowed_modes": list(rollout_details.get("allowed_modes") or deep_runtime.get("allowed_modes") or ["classic", "auto"]),
    })
    if "runtime_decision_influence_enabled" not in deep_runtime:
        deep_runtime["runtime_decision_influence_enabled"] = bool(rollout_details.get("production_decision_enabled", False))
    if "runtime_shadow_only" not in deep_runtime:
        deep_runtime["runtime_shadow_only"] = not bool(deep_runtime.get("runtime_decision_influence_enabled"))
    published.update({
        "bundle_role": "production",
        "model_status": "approved_for_production",
        "deep_runtime": deep_runtime,
        "runtime_requires_production_approval": True,
        "runtime_publish_source": source,
        "auto_promoted_to_runtime_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    })
    approval_payload = _as_dict(user_approval)
    if approval_payload:
        published.update({
            "user_approved_model_switch": True,
            "user_approved_at": str(approval_payload.get("approved_at") or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())),
            "user_approval_reason": str(approval_payload.get("reason") or "user_approved_model_switch"),
            "user_approval_candidate_digest": str(approval_payload.get("candidate_digest") or ""),
            "production_activation_source": source,
            "activation_requires_user_approval": True,
            "rollback_metadata_preserved": True,
        })
    return published


def _write_staging_bundle(staging_paths: Mapping[str, str], candidate_paths: Mapping[str, str], candidate_meta: Mapping[str, Any], *, source: str, user_approval: Mapping[str, Any] | None = None) -> None:
    security_helpers = _security_helpers()
    os.makedirs(str(staging_paths["base"]), exist_ok=True)
    _copy_file(str(candidate_paths["model"]), str(staging_paths["model"]))
    security_helpers.save_model_hash(str(staging_paths["model"]))
    published_meta = _build_published_metadata(candidate_meta, source=source, user_approval=user_approval)
    security_helpers.atomic_write_text(str(staging_paths["metadata"]), json.dumps(published_meta, indent=2, ensure_ascii=False))
    security_helpers.save_metadata_hash(str(staging_paths["metadata"]))
    if _artifact_exists(candidate_paths.get("classifier")):
        _copy_file(str(candidate_paths["classifier"]), str(staging_paths["classifier"]))
        security_helpers.save_user_classifier_hash(str(staging_paths["classifier"]))
    else:
        _remove_path(str(staging_paths["classifier"]))
        security_helpers.remove_user_classifier_hash(str(staging_paths["classifier"]))
    _copy_optional_file(candidate_paths.get("evaluation_report"), staging_paths.get("evaluation_report"))
    _copy_optional_file(candidate_paths.get("evaluation_summary"), staging_paths.get("evaluation_summary"))


def _pending_user_approval_response(
    *,
    source: str,
    eligibility: Mapping[str, Any],
    runtime_validation: Mapping[str, Any],
) -> Dict[str, Any]:
    candidate_digest = str(
        eligibility.get("candidate_artifact_digest")
        or eligibility.get("candidateArtifactDigest")
        or eligibility.get("evidence_candidate_artifact_digest")
        or eligibility.get("evidenceCandidateArtifactDigest")
        or ""
    ).strip()
    return {
        "ok": False,
        "changed": False,
        "reason": "production_ready_pending_user_approval",
        "status": "production_ready_pending_user_approval",
        "source": source,
        "productionReadyPendingUserApproval": True,
        "production_ready_pending_user_approval": True,
        "requiresUserApproval": True,
        "requires_user_approval": True,
        "candidateDigest": candidate_digest,
        "candidate_digest": candidate_digest,
        "productionEligibilityState": dict(eligibility),
        "runtimeValidation": dict(runtime_validation),
        "protectedSessionsAvailable": False,
        "activeRuntimePointerWritten": False,
    }


def safe_auto_promote_production_bundle(
    user_id: str,
    *,
    settings: Mapping[str, Any] | None,
    candidate_paths: Mapping[str, str] | None = None,
    candidate_metadata: Optional[Mapping[str, Any]] = None,
    runtime_validation: Mapping[str, Any] | None = None,
    authenticated: bool = True,
    training_active: bool = False,
    session_flow: str = "idle",
    app_locked: bool = False,
    source: str = AUTO_PROMOTION_SOURCE,
) -> Dict[str, Any]:
    """Return backend-owned pending approval state without silent activation.

    Phase 07 intentionally stops automatic candidate-to-production activation.
    This helper still performs candidate, policy, staging runtime, and production
    evidence checks, but it never writes the active runtime pointer. The only
    activation entry point is ``approve_production_model_switch`` with an exact
    user-approved candidate digest.
    """

    safe = slugify_username(user_id)
    candidate_paths = dict(candidate_paths or _user_model_paths(safe))
    meta = dict(candidate_metadata or {})
    if not meta and _artifact_exists(candidate_paths.get("metadata")):
        try:
            loaded = _artifact_helpers().load_metadata(str(candidate_paths["metadata"])) or {}
            meta = dict(loaded) if isinstance(loaded, Mapping) else {}
        except Exception as exc:
            return {"ok": False, "changed": False, "reason": f"candidate_metadata_invalid:{exc}", "protectedSessionsAvailable": False}

    reason = auto_promotion_block_reason(
        settings=settings,
        candidate_metadata=meta,
        runtime_validation=runtime_validation,
        authenticated=authenticated,
        training_active=training_active,
        session_flow=session_flow,
        app_locked=app_locked,
    )
    if reason:
        already_ready = reason == "already_production_ready"
        return {"ok": bool(already_ready), "changed": False, "reason": reason, "protectedSessionsAvailable": bool(already_ready)}

    missing = _missing_required_artifacts(candidate_paths, meta)
    if missing:
        return {"ok": False, "changed": False, "reason": "missing_artifact:" + ",".join(missing), "missingArtifacts": missing, "protectedSessionsAvailable": False}

    try:
        artifact_helpers = _artifact_helpers()
        artifact_helpers.load_model(str(candidate_paths["model"]))
        artifact_helpers.load_metadata(str(candidate_paths["metadata"]))
        if _artifact_exists(candidate_paths.get("classifier")):
            artifact_helpers.load_classifier(str(candidate_paths["classifier"]))
    except Exception as exc:
        return {"ok": False, "changed": False, "reason": f"candidate_artifact_invalid:{exc}", "protectedSessionsAvailable": False}

    production_paths = _user_production_paths(safe)
    parent = os.path.dirname(str(production_paths["base"]))
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    staging_base = os.path.join(parent, f"production_bundle.user_approval_preview_{timestamp}_{os.getpid()}")
    staging_paths = dict(production_paths)
    staging_paths["base"] = staging_base
    for key, path in list(staging_paths.items()):
        if key != "base":
            staging_paths[key] = os.path.join(staging_base, os.path.basename(str(path)))

    try:
        _remove_path(staging_base)
        _write_staging_bundle(staging_paths, candidate_paths, meta, source=source)
        staging_validation = validate_runtime_bundle_for_activation(staging_paths)
        if not bool(staging_validation.get("ok")):
            return {"ok": False, "changed": False, "reason": "staging_runtime_invalid:" + str(staging_validation.get("reason") or "unknown"), "runtimeValidation": staging_validation, "protectedSessionsAvailable": False}
        eligibility = build_production_eligibility_state(
            candidate_paths=candidate_paths,
            candidate_metadata=meta,
            evaluation_report={},
            runtime_validation=staging_validation,
            runtime_paths=staging_paths,
            rollback_available=True,
        )
        if not bool(eligibility.get("eligible")):
            return {
                "ok": False,
                "changed": False,
                "reason": "production_eligibility_blocked:" + str(eligibility.get("reason_code") or "unknown"),
                "productionEligibilityState": eligibility,
                "protectedSessionsAvailable": False,
            }
        return _pending_user_approval_response(source=source, eligibility=eligibility, runtime_validation=staging_validation)
    except Exception as exc:
        return {"ok": False, "changed": False, "reason": f"promotion_preview_failed_safe:{exc}", "protectedSessionsAvailable": False}
    finally:
        _remove_path(staging_base)


def approve_production_model_switch(
    user_id: str,
    candidate_digest: str,
    *,
    user_approved: bool = False,
    approval_reason: str = "user_approved_model_switch",
    approved_by: str = "local_user",
    candidate_paths: Mapping[str, str] | None = None,
    candidate_metadata: Optional[Mapping[str, Any]] = None,
    source: str = USER_APPROVED_PROMOTION_SOURCE,
) -> Dict[str, Any]:
    """Activate a production-eligible candidate only after exact user approval."""

    safe = slugify_username(user_id)
    requested_digest = str(candidate_digest or "").strip()
    if not bool(user_approved):
        return {"ok": False, "changed": False, "reason": "user_approval_required", "protectedSessionsAvailable": False}
    if not requested_digest:
        return {"ok": False, "changed": False, "reason": "candidate_digest_required", "protectedSessionsAvailable": False}

    candidate_paths = dict(candidate_paths or _user_model_paths(safe))
    meta = dict(candidate_metadata or {})
    if not meta and _artifact_exists(candidate_paths.get("metadata")):
        try:
            loaded = _artifact_helpers().load_metadata(str(candidate_paths["metadata"])) or {}
            meta = dict(loaded) if isinstance(loaded, Mapping) else {}
        except Exception as exc:
            return {"ok": False, "changed": False, "reason": f"candidate_metadata_invalid:{exc}", "protectedSessionsAvailable": False}

    allowed, policy_reason = _policy_allows_production(meta)
    if not allowed:
        return {"ok": False, "changed": False, "reason": policy_reason, "protectedSessionsAvailable": False}

    missing = _missing_required_artifacts(candidate_paths, meta)
    if missing:
        return {"ok": False, "changed": False, "reason": "missing_artifact:" + ",".join(missing), "missingArtifacts": missing, "protectedSessionsAvailable": False}

    try:
        artifact_helpers = _artifact_helpers()
        artifact_helpers.load_model(str(candidate_paths["model"]))
        artifact_helpers.load_metadata(str(candidate_paths["metadata"]))
        if _artifact_exists(candidate_paths.get("classifier")):
            artifact_helpers.load_classifier(str(candidate_paths["classifier"]))
    except Exception as exc:
        return {"ok": False, "changed": False, "reason": f"candidate_artifact_invalid:{exc}", "protectedSessionsAvailable": False}

    production_paths = _user_production_paths(safe)
    production_base = str(production_paths["base"])
    parent = os.path.dirname(production_base)
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    staging_base = os.path.join(parent, f"production_bundle.user_approval_staging_{timestamp}_{os.getpid()}")
    backup_base = os.path.join(parent, f"production_bundle.user_approval_backup_{timestamp}_{os.getpid()}")
    staging_paths = dict(production_paths)
    staging_paths["base"] = staging_base
    for key, path in list(staging_paths.items()):
        if key != "base":
            staging_paths[key] = os.path.join(staging_base, os.path.basename(str(path)))
    pointer_path = _active_runtime_pointer_path(safe)
    pointer_backup = _active_pointer_backup_path(safe)
    pointer_had_file = os.path.exists(pointer_path)
    pointer_backup_had_file = os.path.exists(pointer_backup)
    approved_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    user_approval_payload = {
        "approved_at": approved_at,
        "reason": str(approval_reason or "user_approved_model_switch"),
        "approved_by": str(approved_by or "local_user"),
        "candidate_digest": requested_digest,
    }

    try:
        _remove_path(staging_base)
        _write_staging_bundle(staging_paths, candidate_paths, meta, source=source, user_approval=user_approval_payload)
        staging_validation = validate_runtime_bundle_for_activation(staging_paths)
        if not bool(staging_validation.get("ok")):
            return {"ok": False, "changed": False, "reason": "staging_runtime_invalid:" + str(staging_validation.get("reason") or "unknown"), "runtimeValidation": staging_validation, "protectedSessionsAvailable": False}
        eligibility = build_production_eligibility_state(
            candidate_paths=candidate_paths,
            candidate_metadata=meta,
            evaluation_report={},
            runtime_validation=staging_validation,
            runtime_paths=staging_paths,
            rollback_available=True,
        )
        effective_digest = str(eligibility.get("candidate_artifact_digest") or eligibility.get("candidateArtifactDigest") or "").strip()
        evidence_digest = str(eligibility.get("evidence_candidate_artifact_digest") or eligibility.get("evidenceCandidateArtifactDigest") or "").strip()
        if requested_digest != effective_digest or (evidence_digest and requested_digest != evidence_digest):
            return {
                "ok": False,
                "changed": False,
                "reason": "candidate_digest_mismatch",
                "requestedCandidateDigest": requested_digest,
                "candidateDigest": effective_digest,
                "evidenceCandidateDigest": evidence_digest,
                "productionEligibilityState": eligibility,
                "protectedSessionsAvailable": False,
            }
        if not bool(eligibility.get("eligible")):
            return {
                "ok": False,
                "changed": False,
                "reason": "production_eligibility_blocked:" + str(eligibility.get("reason_code") or "unknown"),
                "productionEligibilityState": eligibility,
                "protectedSessionsAvailable": False,
            }

        _remove_path(backup_base)
        if os.path.exists(production_base):
            os.replace(production_base, backup_base)
        os.replace(staging_base, production_base)
        if pointer_had_file:
            _restore_file(pointer_path, pointer_backup)
        elif os.path.exists(pointer_backup):
            pointer_backup_had_file = True
        try:
            production_validation = validate_runtime_bundle_for_activation(production_paths)
            if not bool(production_validation.get("ok")):
                raise RuntimeError("production_runtime_invalid:" + str(production_validation.get("reason") or "unknown"))
            pointer_payload = write_active_runtime_pointer(safe, production_paths, source=source)
            clear_runtime_model_cache(safe)
        except Exception:
            _remove_path(production_base)
            if os.path.exists(backup_base):
                os.replace(backup_base, production_base)
            if pointer_had_file:
                _restore_file(pointer_backup, pointer_path)
            else:
                _remove_path(pointer_path)
            clear_runtime_model_cache(safe)
            raise
        finally:
            if pointer_had_file and os.path.exists(pointer_backup):
                _remove_path(pointer_backup)
            elif not pointer_backup_had_file:
                _remove_path(pointer_backup)
        _remove_path(backup_base)
        return {
            "ok": True,
            "changed": True,
            "reason": "user_approved_model_switch_activated",
            "source": source,
            "candidateDigest": requested_digest,
            "approvedAt": approved_at,
            "approvedBy": str(approved_by or "local_user"),
            "protectedSessionsAvailable": True,
            "runtimeValidation": production_validation,
            "productionEligibilityState": eligibility,
            "activePointer": pointer_payload,
            "rollbackReady": True,
        }
    except Exception as exc:
        return {"ok": False, "changed": False, "reason": f"user_approved_switch_failed_safe:{exc}", "protectedSessionsAvailable": False}
    finally:
        _remove_path(staging_base)


__all__ = [
    "AUTO_PROMOTION_SOURCE",
    "USER_APPROVED_PROMOTION_SOURCE",
    "auto_promotion_block_reason",
    "safe_auto_promote_production_bundle",
    "approve_production_model_switch",
]
