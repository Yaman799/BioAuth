"""Extracted implementation section for `bridge/refresh_dashboard_helpers.py`."""
from __future__ import annotations
import logging
import os
from importlib import import_module
from typing import Any, Dict, List
from bioauth_runtime import runtime_boundary
from bridge.runtime_labels import runtime_policy_display_fields
from bridge import refresh_runtime_helpers as _refresh_state
from bridge.qt_thread_dispatch import dispatch_to_qt_thread

def build_profile_view(self, profile: Dict[str, Any]) -> Dict[str, Any]:
    facade = _facade()
    readiness = dict(profile.get("lock_readiness") or {})
    lock_allowed = bool(profile.get("runtime_lock_allowed")) or bool(readiness.get("lock_allowed"))
    readiness_text = (
        self._t("lock_readiness_ready")
        if lock_allowed
        else self._t(
            "lock_readiness_warning_only",
            sessions=int(readiness.get("trusted_sessions", 0) or 0),
            required_sessions=int(readiness.get("required_sessions", 0) or 0),
            windows=int(readiness.get("good_windows", 0) or 0),
            required_windows=int(readiness.get("required_good_windows", 0) or 0),
        )
    )
    return {
        **profile,
        "readyText": self._t("profile_ready_yes") if profile.get("ready") else self._t("profile_ready_no"),
        "lockReadinessText": readiness_text,
        "lockReadinessTone": "success" if lock_allowed else "warn",
        "progressText": self._t(
            "enrollment_progress",
            count=int(profile.get("session_count", 0) or 0),
            target=facade.MAX_ENROLLMENT_SESSIONS,
            minimum=facade.MIN_ENROLLMENT_SESSIONS,
        ),
    }

def status_for_dashboard(self, profile: Dict[str, Any], runtime_state: Dict[str, Any]) -> tuple[str, str]:
    flow = str(runtime_state.get("flow") or "idle")
    raw_count = int(profile.get("session_count", 0) or 0)
    training_block_reason = str(profile.get("training_block_reason") or "")
    if bool(getattr(self, "_training_in_progress", False)):
        progress = dict(getattr(self, "_training_progress", {}) or {})
        headline = str(progress.get("headline") or "").strip()
        detail = str(progress.get("detail") or "").strip()
        return (detail or headline or self._t("training_stage_evaluating_model")), "info"
    if bool(getattr(self, "_history_sync_pending", False)) or bool(runtime_state.get("archive_pending")) or bool(runtime_state.get("auto_enrollment_finalizing")):
        return "Session archive is being finalized.", "info"
    if flow == "protected_forced_stop":
        base = self._t("alert_lock_msg")
        notice = str(runtime_state.get("incident_evidence_notice") or "").strip()
        return ((base + " " + notice).strip() if notice else base), "danger"
    if flow == "protected_resume_pending":
        base = self._t("runtime_detail_resume_pending")
        notice = str(runtime_state.get("incident_evidence_notice") or "").strip()
        return ((base + " " + notice).strip() if notice else base), "warn"
    if runtime_state.get("technicalFailure"):
        message = str(runtime_state.get("statusDetail") or runtime_state.get("statusLabel") or self._t("protected_monitor_failed"))
        diagnostic = str(runtime_state.get("diagnosticText") or "").strip()
        return (f"{message} {diagnostic}".strip(), "danger")
    if runtime_state.get("awaitingEvidence"):
        if runtime_state.get("observedRiskAvailable"):
            return str(runtime_state.get("runtimeDisplayText") or self._t(
                "runtime_status_observed_line",
                active=runtime_state.get("activeText"),
                decision=runtime_state.get("trustLabel") or runtime_state.get("decisionLabel") or runtime_state.get("decisionText"),
                observed=runtime_state.get("observedRiskText"),
            )), "warn"
        return str(runtime_state.get("statusDetail") or runtime_state.get("statusLabel") or self._t("status_active")), "warn"
    if runtime_state.get("monitor_failed"):
        return self._t("protected_monitor_failed"), "danger"
    if runtime_state.get("active") and flow != "idle":
        decision = str(runtime_state.get("decisionText") or "").lower()
        tone = "success" if decision == "legit" else "warn" if decision == "suspicious" else "info"
        if runtime_state.get("riskDisplayMode") == "observed_risk_pending" and runtime_state.get("observedRiskAvailable"):
            return (
                self._t(
                    "runtime_status_observed_line",
                    active=runtime_state.get("activeText"),
                    decision=runtime_state.get("trustLabel") or runtime_state.get("decisionLabel") or runtime_state.get("decisionText"),
                    observed=runtime_state.get("observedRiskText"),
                ),
                "warn",
            )
        display_text = str(runtime_state.get("runtimeDisplayText") or runtime_state.get("activeText") or "").strip()
        risk_text = str(runtime_state.get("riskText") or runtime_state.get("displayRiskText") or "--").strip()
        if risk_text and risk_text != "--":
            return self._t("runtime_status_display_risk_line", status=display_text, risk=risk_text), tone
        return display_text or self._t("status_active"), tone
    production_state = profile.get("production_approval_state") if isinstance(profile, dict) else {}
    if isinstance(production_state, dict) and production_state:
        message, tone = _production_approval_status_for_user(production_state)
        if message:
            return message, tone
    if profile.get("production_ready"):
        return self._t("status_banner_ready"), "success"
    if profile.get("ready"):
        candidate_status = str(profile.get("candidate_model_status") or "").strip().lower()
        if candidate_status == "rejected":
            return self._t("status_banner_runtime_rejected"), "warn"
        if candidate_status == "approved_for_shadow":
            return self._t("status_banner_runtime_shadow"), "warn"
        if candidate_status == "pending_evaluation":
            return self._t("status_banner_runtime_evaluating"), "info"
        return self._t("status_banner_runtime_pending"), "warn"
    if bool(getattr(self, "_last_training_failed", False)):
        message = str(getattr(self, "_last_training_failure_message", "") or "").strip()
        tone = str(getattr(self, "_last_training_failure_tone", "danger") or "danger")
        if message:
            return message, tone
    if bool(profile.get("training_can_start")):
        return self._t("guide_training_ready"), "info"
    if training_block_reason == "need_higher_quality_sessions":
        return self._t("training_need_higher_quality_sessions"), "warn"
    if raw_count == 0:
        return self._t("status_banner_collecting"), "info"
    return self._t("status_banner_collecting"), "info"

def _normalized_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "profile": dict(snapshot.get("profile") or {}),
        "sessions": [dict(item) for item in list(snapshot.get("sessions") or [])],
    }

def _dashboard_fast_session_limit(self) -> int:
    try:
        return max(1, int(getattr(self, "DASHBOARD_FAST_SESSION_LIMIT", 10) or 10))
    except (TypeError, ValueError, OverflowError):
        return 10

def _compute_dashboard_snapshot(self, user_id: str) -> Dict[str, Any]:
    """Compute the lightweight dashboard snapshot used by normal refresh."""
    facade = _facade()
    timing: Dict[str, Any] = {}
    compute_started = _time_now(facade)
    if getattr(facade.summarize_user_sessions, "__module__", "") != "model_metadata" or getattr(facade.user_profile_status, "__module__", "") != "model_metadata":
        snapshot_started = _time_now(facade)
        snapshot = {
            "profile": dict(facade.user_profile_status(user_id) or {}),
            "sessions": [dict(item) for item in list(facade.summarize_user_sessions(user_id) or [])[:_dashboard_fast_session_limit(self)]],
        }
        snapshot.setdefault("profile", {})["dashboard_snapshot_mode"] = "fast"
        snapshot["profile"].setdefault("history_is_partial", False)
        snapshot["profile"].setdefault("history_loading", False)
        snapshot["profile"].setdefault("history_loaded", False)
        snapshot["profile"].setdefault("history_session_count", len(snapshot.get("sessions") or []))
        snapshot["profile"].setdefault("history_visible_session_count", len(snapshot.get("sessions") or []))
        snapshot["profile"].setdefault("history_status", "partial")
        timing["dashboard_total_ms"] = _elapsed_ms(facade, snapshot_started)
    else:
        try:
            fast_builder = getattr(facade, "build_fast_user_dashboard_snapshot", None)
            if callable(fast_builder):
                snapshot = fast_builder(
                    user_id,
                    session_detail_limit=_dashboard_fast_session_limit(self),
                    timing_collector=timing,
                )
            else:
                snapshot = facade.build_user_dashboard_snapshot(
                    user_id,
                    include_training_selection_details=False,
                    session_detail_limit=_dashboard_fast_session_limit(self),
                    timing_collector=timing,
                )
        except TypeError:
            snapshot = facade.build_user_dashboard_snapshot(user_id)

    normalize_started = _time_now(facade)
    normalized = _normalized_snapshot(snapshot if isinstance(snapshot, dict) else {})
    timing["dashboard_normalization_ms"] = _coerce_nonnegative_int(timing.get("dashboard_normalization_ms", 0)) + _elapsed_ms(facade, normalize_started)
    timing["dashboard_total_ms"] = max(
        _coerce_nonnegative_int(timing.get("dashboard_total_ms", 0)),
        _elapsed_ms(facade, compute_started),
    )
    _set_dashboard_debug_timing(self, timing, cache_hit=False, session_count=len(normalized.get("sessions") or []))
    return normalized

def _compute_full_history_snapshot(self, user_id: str) -> Dict[str, Any]:
    """Compute the complete history snapshot for explicit History-page use."""
    facade = _facade()
    if getattr(facade.summarize_user_sessions, "__module__", "") != "model_metadata" or getattr(facade.user_profile_status, "__module__", "") != "model_metadata":
        return _normalized_snapshot(
            {
                "profile": dict(facade.user_profile_status(user_id) or {}),
                "sessions": [dict(item) for item in list(facade.summarize_user_sessions(user_id) or [])],
            }
        )
    try:
        return _normalized_snapshot(
            facade.build_user_dashboard_snapshot(
                user_id,
                include_training_selection_details=True,
                session_detail_limit=None,
            )
        )
    except TypeError:
        return _normalized_snapshot(facade.build_user_dashboard_snapshot(user_id))

def _snapshot_fallback(self, user_id: str) -> Dict[str, Any]:
    safe_user = _facade().slugify_username(user_id)
    current_user = _facade().slugify_username((getattr(self, "_current_user", {}) or {}).get("user_id", "") or "")
    if safe_user and safe_user == current_user:
        return {
            "profile": dict(getattr(self, "_profile", {}) or {}),
            "sessions": [dict(item) for item in list(getattr(self, "_sessions", []) or [])],
        }
    return {"profile": {}, "sessions": []}

def _async_snapshot_enabled(self) -> bool:
    return bool(getattr(self, "_dashboard_snapshot_refresh_enabled", False)) and hasattr(self, "_dashboard_snapshot_result_lock")

def _dashboard_cache_state(self, user_id: str) -> tuple[bool, bool, Dict[str, Any], int]:
    facade = _facade()
    safe_user = facade.slugify_username(user_id)
    cached_user = facade.slugify_username(getattr(self, "_dashboard_snapshot_user", "") or "")
    cached_snapshot = getattr(self, "_dashboard_snapshot_cache", {})
    cached_at = float(getattr(self, "_dashboard_snapshot_cached_at", 0.0) or 0.0)
    if not (safe_user and safe_user == cached_user and isinstance(cached_snapshot, dict) and cached_snapshot):
        return False, False, {}, 0
    normalized = _normalized_snapshot(cached_snapshot)
    session_count = len(list(normalized.get("sessions") or []))
    ttl_sec = self._dashboard_snapshot_ttl_sec()
    if bool(getattr(self, "_training_in_progress", False)):
        return True, True, normalized, session_count
    if ttl_sec > 0.0 and (facade.time.time() - cached_at) < ttl_sec:
        return True, True, normalized, session_count
    return True, False, normalized, session_count
