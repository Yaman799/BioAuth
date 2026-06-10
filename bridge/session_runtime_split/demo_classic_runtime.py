"""Extracted implementation section for `bridge/session_runtime_helpers.py`."""
from __future__ import annotations
import json
import logging
import os
import re
import signal
import threading
import time
from collections import deque
from importlib import import_module
from typing import Any, Dict, List, Optional
from release_runtime import startup_protected_session_decision, write_release_runtime_event

def _demo_classic_protected_enabled() -> bool:
    try:
        from app_settings import demo_classic_protected_enabled as _enabled

        return bool(_enabled())
    except Exception:
        return False

def _env_flag_enabled(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}

def _independent_shadow_evidence_monitor_enabled(self: Any | None = None) -> bool:
    """Return True only when the legacy independent shadow monitor is explicitly enabled.

    Commercial builds default to report-only/runtime-fed shadow evidence. The
    independent Shadow Evidence Monitor is retained for developer/internal
    diagnostics only because it starts its own logger/monitor processes and must
    never autostart during normal protected runtime.
    """
    if _env_flag_enabled(_INDEPENDENT_SHADOW_EVIDENCE_MONITOR_ENV):
        return True
    if self is not None:
        for name in (
            "_enable_independent_shadow_evidence_monitor",
            "_independent_shadow_evidence_monitor_enabled",
        ):
            try:
                if bool(getattr(self, name, False)):
                    return True
            except Exception:
                continue
        settings = getattr(self, "_app_settings", None)
        if isinstance(settings, dict):
            for key in (
                "enable_independent_shadow_evidence_monitor",
                "independent_shadow_evidence_monitor_enabled",
            ):
                if str(settings.get(key, "") or "").strip().lower() in {"1", "true", "yes", "on"}:
                    return True
    return False

def _demo_classic_candidate_or_runtime_artifact_exists(self, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Return True when a trained candidate/runtime artifact exists for the embedded classic runtime flag.

    This only answers the start-gate question; it does not validate production
    approval and must only be used when BIOAUTH_DEMO_CLASSIC_PROTECTED is set.
    """
    if not _demo_classic_protected_enabled():
        return False
    if not getattr(self, "_current_user", None):
        return False
    payload = profile if isinstance(profile, dict) else {}
    candidate_status = str(
        payload.get("candidate_model_status")
        or payload.get("model_status")
        or payload.get("modelStatus")
        or payload.get("approval_status")
        or ""
    ).strip().lower()
    production_state = payload.get("production_approval_state") if isinstance(payload.get("production_approval_state"), dict) else {}
    if not candidate_status and production_state:
        candidate_status = str(
            production_state.get("candidate_status")
            or production_state.get("candidateStatus")
            or production_state.get("modelStatus")
            or ""
        ).strip().lower()
    status_ok = candidate_status in {"approved_for_shadow", "shadow_validation", "approved_for_production", "production_ready", "demo_ready", "rejected", "offline_approval_rejected"}
    if bool(payload.get("ready")) and status_ok:
        return True
    try:
        from metadata_core.paths import _user_model_paths, _user_production_paths
        safe = _current_safe_user(self)
        for paths in (_user_production_paths(safe), _user_model_paths(safe)):
            model_path = str(paths.get("model") or "")
            meta_path = str(paths.get("metadata") or "")
            if model_path and meta_path and os.path.exists(model_path) and os.path.exists(meta_path):
                return True
    except Exception:
        LOGGER.debug("Failed checking protected runtime artifacts", exc_info=True)
    return False

def _ensure_demo_classic_runtime_pointer(self) -> Dict[str, Any]:
    """Ensure the embedded classic runtime flag has a valid production-shaped runtime pointer.

    monitor.py still requires a disk-backed active runtime pointer. Activation
    remains guarded by BIOAUTH_DEMO_CLASSIC_PROTECTED and returns a structured
    reason so Start Monitor can fail before spawning workers if no candidate exists.
    """

    if not _demo_classic_protected_enabled():
        return {"ok": False, "activated": False, "reason": "demo_classic_protected_disabled"}

    try:
        from metadata_core.demo_classic_runtime_activation import (
            activate_existing_candidate_runtime_for_demo,
        )

        safe_user = _current_safe_user(self)
        result = activate_existing_candidate_runtime_for_demo(safe_user)
    except Exception as exc:
        LOGGER.warning("Classic runtime activation failed", exc_info=True)
        result = {
            "ok": False,
            "activated": False,
            "reason": f"demo_classic_runtime_activation_exception:{exc}",
        }

    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug(
            "runtime",
            "demo_classic_runtime_activation",
            payload={
                "ok": bool(result.get("ok")),
                "activated": bool(result.get("activated")),
                "reason": str(result.get("reason") or ""),
                "demo_classic_protected": True,
                "production_approval_bypassed_for_demo": True,
                "active_runtime_pointer_path": str(result.get("active_runtime_pointer_path") or ""),
                "runtime_publish_source": str(result.get("runtime_publish_source") or ""),
                "demo_rejected_candidate_override": bool(result.get("demo_rejected_candidate_override")),
            },
            level="info" if result.get("ok") else "warn",
        )

    return result

def _demo_classic_apply_profile_overlay(profile: Dict[str, Any]) -> Dict[str, Any]:
    updated = dict(profile or {})
    if not _demo_classic_protected_enabled():
        return updated
    candidate_status = str(
        updated.get("candidate_model_status")
        or updated.get("model_status")
        or updated.get("modelStatus")
        or updated.get("approval_status")
        or updated.get("reason_code")
        or ""
    ).strip().lower()
    rejected_override = candidate_status in {"rejected", "offline_approval_rejected"}
    reason_code = "demo_classic_rejected_candidate_override" if rejected_override else "demo_classic_protected"
    runtime_source = "demo_classic_rejected_candidate_override" if rejected_override else "demo_classic_protected"
    updated.update({
        "demo_classic_protected": True,
        "production_approval_bypassed_for_demo": True,
        "demo_classic_protected_bypassed_production_gate": True,
        "production_ready": True,
        "protected_sessions_available": True,
        "can_start_monitor": True,
        "local_profile_can_start_monitor": True,
        "ready_notification_state": "ready",
        "ready_notification_reason": reason_code,
        "reason_code": reason_code,
        "status": "demo_ready",
        "runtime_publish_source": runtime_source,
        "demo_rejected_candidate_override": bool(rejected_override),
    })
    production_state = updated.get("production_approval_state")
    if isinstance(production_state, dict):
        merged = dict(production_state)
        merged.update({
            "demo_classic_protected": True,
            "production_approval_bypassed_for_demo": True,
            "demo_classic_protected_bypassed_production_gate": True,
            "productionReady": True,
            "production_ready": True,
            "protectedSessionsAvailable": True,
            "protected_sessions_available": True,
            "reason_code": reason_code,
            "reasonCode": reason_code,
            "ready_notification_state": "ready",
            "readyNotificationState": "ready",
            "ready_notification_reason": reason_code,
            "readyNotificationReason": reason_code,
            "status": "demo_ready",
            "runtime_publish_source": runtime_source,
            "demo_rejected_candidate_override": bool(rejected_override),
        })
        updated["production_approval_state"] = merged
    return updated

def _demo_classic_forced_intruder_resume_pending(state: Optional[Dict[str, Any]]) -> bool:
    """Return True for a stale forced-stop state that is allowed to resume after Windows unlock.

    The embedded classic runtime flag can legitimately lock Windows from an
    intruder event. Older bridge state left that terminal state as active=True,
    which blocks the post-unlock auto-resume path.
    """
    if not _demo_classic_protected_enabled() or not isinstance(state, dict):
        return False
    decision = str(state.get("decision") or state.get("final_decision") or state.get("archive_label") or "").strip().lower()
    return bool(
        state.get("forced_stop")
        and bool(state.get("auto_resume_pending") or state.get("resume_after_unlock"))
        and str(state.get("session_kind") or "").strip().lower() == "protected"
        and decision == "intruder"
    )

def _demo_classic_post_unlock_resume_overlay(now: float) -> Dict[str, Any]:
    """Fields that clear stale intruder UI when protection resumes after unlock."""
    cooldown_until = float(now or time.time()) + 8.0
    return {
        "decision": "pending",
        "model_decision": "",
        "final_decision": "",
        "status": "verifying_return",
        "runtime_confirmation_rule": "demo_classic_post_unlock_resume",
        "runtime_diagnostic_code": "post_unlock_resume_pending",
        "runtime_diagnostic_reason": "BioAuth started a fresh protected session after Windows unlock.",
        "forced_stop": False,
        "app_locked": False,
        "screen_locked": False,
        "monitor_holding": False,
        "restriction_active": False,
        "archive_requested": False,
        "archive_request_reason": "",
        "risk": None,
        "avg_risk": None,
        "raw_score": None,
        "warning_count": 0,
        "runtime_recent_risks": [],
        "runtime_recent_decisions": [],
        "runtime_window_count": 0,
        "runtime_top_risky_windows": [],
        "demo_classic_protected": True,
        "demo_classic_post_unlock_resumed": True,
        "demo_classic_stale_intruder_state_cleared": True,
        "demo_classic_post_unlock_resume_attempted": True,
        "demo_classic_resume_cooldown_until": cooldown_until,
        "lock_recovery_cooldown_until": cooldown_until,
    }
