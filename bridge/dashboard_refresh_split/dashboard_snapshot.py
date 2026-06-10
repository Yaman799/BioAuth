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

def update_dashboard(self) -> None:
    facade = _facade()
    if not self._current_user:
        profile_changed = bool(getattr(self, "_profile", {}))
        sessions_changed = bool(getattr(self, "_sessions", []))
        runtime_changed = bool(getattr(self, "_runtime_state", {}))
        if profile_changed:
            self._profile = {}
        if sessions_changed:
            self._sessions = []
        if runtime_changed:
            self._runtime_state = {}
        _ensure_full_history_state(self)
        self._dashboard_full_history_requested = False
        self._dashboard_full_history_cache = {}
        self._dashboard_full_history_user = ""
        self._dashboard_full_history_loading = False
        self._invalidate_dashboard_snapshot_cache()
        _refresh_state.set_dashboard_state(self, loading=False, updating=False, stale=False, last_refresh_error="")
        if profile_changed or runtime_changed:
            self._emit_controls_changed(runtime_changed=runtime_changed, profile_changed=profile_changed)
        if sessions_changed:
            self.sessionsChanged.emit()
        return

    user_id = self._current_user["user_id"]
    _ensure_full_history_state(self)
    _apply_full_history_result(self, user_id)
    state = self._active_state_for_current_user()
    runtime_view = self._build_runtime_state_view(state if isinstance(state, dict) else {})
    snapshot_getter = getattr(self, "_dashboard_snapshot")
    snapshot = snapshot_getter(user_id)
    view_started = _time_now(facade)
    profile_view = self._build_profile_view(snapshot.get("profile") or {})
    sessions_view = [dict(item) for item in list(snapshot.get("sessions") or [])]
    full_user = facade.slugify_username(getattr(self, "_dashboard_full_history_user", "") or "")
    current_safe_user = facade.slugify_username(user_id)
    full_cache = getattr(self, "_dashboard_full_history_cache", {})
    if bool(getattr(self, "_dashboard_full_history_requested", False)):
        if full_user == current_safe_user and isinstance(full_cache, dict) and full_cache:
            sessions_view = [dict(item) for item in list(full_cache.get("sessions") or [])]
        elif not bool(getattr(self, "_dashboard_full_history_refresh_inflight", False)):
            _queue_full_history_refresh(self, user_id, force=False)
    profile_view = _merge_history_profile_fields(self, user_id, profile_view, sessions_view)
    history_watch_before = (
        bool(getattr(self, "_history_sync_pending", False)),
        str(getattr(self, "_history_sync_status", "") or ""),
        str(getattr(self, "_history_sync_warning", "") or ""),
        float(getattr(self, "_history_sync_deadline", 0.0) or 0.0),
        float(getattr(self, "_history_sync_hard_deadline", 0.0) or 0.0),
    )
    profile_view, sessions_view = self._sync_history_after_archive(user_id, runtime_view, profile_view, sessions_view)
    history_watch_after = (
        bool(getattr(self, "_history_sync_pending", False)),
        str(getattr(self, "_history_sync_status", "") or ""),
        str(getattr(self, "_history_sync_warning", "") or ""),
        float(getattr(self, "_history_sync_deadline", 0.0) or 0.0),
        float(getattr(self, "_history_sync_hard_deadline", 0.0) or 0.0),
    )
    if history_watch_after != history_watch_before:
        runtime_view = self._build_runtime_state_view(state if isinstance(state, dict) else {})
    _add_dashboard_view_timing(self, _elapsed_ms(facade, view_started))

    profile_changed = profile_view != self._profile
    sessions_changed = sessions_view != self._sessions
    runtime_changed = runtime_view != self._runtime_state

    if profile_changed:
        self._profile = profile_view
    if sessions_changed:
        self._sessions = sessions_view
    deep_runtime_changed = False
    hybrid_direct_changed = False
    if runtime_changed:
        self._runtime_state = runtime_view
        refresh_deep_runtime = getattr(self, "_refresh_deep_runtime_state", None)
        if callable(refresh_deep_runtime):
            deep_runtime_changed = bool(refresh_deep_runtime())
        # Commercial-Core-22A: Hybrid Direct Test is removed from the
        # commercial runtime/training flow.  Keep a small compatibility state
        # instead of rebuilding the old Hybrid Direct dashboard state on every
        # runtime refresh.
        previous_hybrid = getattr(self, "_hybrid_direct_state", {}) if isinstance(getattr(self, "_hybrid_direct_state", {}), dict) else {}
        current_hybrid = {
            "enabled": False,
            "available": False,
            "status": "removed",
            "reason_code": "hybrid_direct_removed_from_commercial_flow",
            "reason_codes": ["hybrid_direct_removed_from_commercial_flow", "hybrid_test_not_required"],
            "hybrid_removed_from_commercial_flow": True,
            "hybrid_required_for_training": False,
            "can_block_training": False,
            "can_influence_device": False,
            "report_only": True,
            "source": "commercial_core_22a",
        }
        if current_hybrid != previous_hybrid:
            self._hybrid_direct_state = current_hybrid
            hybrid_direct_changed = True

    status_message, status_tone = self._status_for_dashboard(profile_view, runtime_view)
    self._set_status(status_message, status_tone)
    observe_production = getattr(self, "_observe_production_approval_state", None)
    if callable(observe_production) and _should_observe_production_approval_state(self, profile_view, source="dashboard_refresh"):
        observe_production(profile_view, source="dashboard_refresh")

    if profile_changed or runtime_changed:
        self._emit_controls_changed(runtime_changed=runtime_changed, profile_changed=profile_changed)
    if hybrid_direct_changed:
        hybrid_signal = getattr(self, "hybridDirectChanged", None)
        if hybrid_signal is not None and hasattr(hybrid_signal, "emit"):
            hybrid_signal.emit()
    if deep_runtime_changed:
        emit_deep_runtime = getattr(self, "_emit_deep_runtime_changed", None)
        if callable(emit_deep_runtime):
            emit_deep_runtime()
    if sessions_changed:
        self.sessionsChanged.emit()
    if profile_changed or sessions_changed:
        signal = getattr(self, "autoEnrollmentChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        readiness_signal = getattr(self, "modelReadinessChanged", None)
        if readiness_signal is not None and hasattr(readiness_signal, "emit"):
            readiness_signal.emit()
