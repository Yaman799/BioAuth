from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

from artifact_integrity import SecurityError

from . import refresh_dashboard_helpers as _dashboard_helpers
from . import refresh_runtime_helpers as _runtime_helpers
from . import refresh_shadow_helpers as _shadow_helpers
from .shared import (
    MAX_ENROLLMENT_SESSIONS,
    MIN_ENROLLMENT_SESSIONS,
    MONITOR_SCRIPT,
    MONITOR_START_GRACE_SEC,
    QTimer,
    REFRESH_ACTIVE_MS,
    REFRESH_BACKGROUND_MS,
    REFRESH_IDLE_AUTH_MS,
    REFRESH_IDLE_SIGNED_MS,
    Slot,
    build_fast_user_dashboard_snapshot,
    build_user_dashboard_snapshot,
    summarize_user_sessions,
    user_profile_status,
    dismiss_shadow_suggestion,
    evaluate_shadow_vs_main,
    get_shadow_status,
    invalidate_session_discovery_cache,
    list_shadow_backlog_sessions,
    log_shadow_event,
    register_legit_session_for_shadow,
    request_stop,
    show_taskbar_notification,
    train_shadow_model,
    write_session_state,
    slugify_username,
    runtime_decision_key,
    runtime_policy_display_fields,
    runtime_status_detail_key,
    runtime_status_is_technical_failure,
    runtime_status_awaits_evidence,
    runtime_status_key,
    update_session_index_for_path,
)

LOGGER = logging.getLogger(__name__)


class RefreshMixin:
    """Runtime/dashboard refresh helpers.

    Dependency note: this mixin assumes SessionMixin provides current-user helpers
    such as _safe_user(), _logger_key(), _logger_process_key(), _active_state_for_current_user(),
    _clear_pending_monitor_start(), and _start_process().
    """

    SHADOW_STATUS_REFRESH_SEC = 12.0
    SHADOW_BACKLOG_SCAN_IDLE_SEC = 30.0
    HISTORY_POST_STOP_REFRESH_MS = 300
    DASHBOARD_SNAPSHOT_ACTIVE_SEC = 4.0
    DASHBOARD_SNAPSHOT_IDLE_SEC = 12.0
    DASHBOARD_SNAPSHOT_BACKGROUND_SEC = 20.0
    REFRESH_REQUEST_DEBOUNCE_MS = 35

    def _format_elapsed(self, started_at: Any) -> str:
        return _dashboard_helpers.format_elapsed(self, started_at)

    def _set_status(self, message: str, tone: str = "info") -> bool:
        return _runtime_helpers.set_status(self, message, tone)

    def _emit_controls_changed(self, *, runtime_changed: bool = False, profile_changed: bool = False, controls_changed: bool = True) -> None:
        _runtime_helpers.emit_controls_changed(self, runtime_changed=runtime_changed, profile_changed=profile_changed, controls_changed=controls_changed)

    def _emit_all(self) -> None:
        _runtime_helpers.emit_all(self)

    def _dashboard_state(self) -> Dict[str, Any]:
        return _runtime_helpers.dashboard_state_payload(self)

    def _is_dashboard_visible(self) -> bool:
        return _runtime_helpers.is_dashboard_visible(self)

    def _set_dashboard_state(self, **kwargs) -> Dict[str, Any]:
        return _runtime_helpers.set_dashboard_state(self, **kwargs)

    @Slot(bool)
    def setDashboardVisible(self, visible: bool) -> None:
        _runtime_helpers.set_dashboard_visible(self, bool(visible))

    def _update_runtime_background_state(self) -> None:
        _runtime_helpers.update_runtime_background_state(self)

    def _desired_refresh_interval_ms(self) -> int:
        return _runtime_helpers.desired_refresh_interval_ms(self)

    def _update_refresh_timer(self, *, force: bool = False) -> None:
        _runtime_helpers.update_refresh_timer(self, force=force)

    def _invalidate_dashboard_snapshot_cache(self) -> None:
        _runtime_helpers.invalidate_dashboard_snapshot_cache(self)

    def _dashboard_snapshot_ttl_sec(self) -> float:
        return _runtime_helpers.dashboard_snapshot_ttl_sec(self)

    def _build_runtime_state_view(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return _dashboard_helpers.build_runtime_state_view(self, state)

    def _build_profile_view(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        return _dashboard_helpers.build_profile_view(self, profile)

    def _status_for_dashboard(self, profile: Dict[str, Any], runtime_state: Dict[str, Any]) -> tuple[str, str]:
        return _dashboard_helpers.status_for_dashboard(self, profile, runtime_state)

    def _dashboard_snapshot(self, user_id: str, *, force: bool = False) -> Dict[str, Any]:
        return _dashboard_helpers.dashboard_snapshot(self, user_id, force=force)

    def _sync_history_after_archive(self, user_id: str, runtime_view: Dict[str, Any], profile_view: Dict[str, Any], sessions_view: list[Dict[str, Any]]) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
        return _dashboard_helpers.sync_history_after_archive(self, user_id, runtime_view, profile_view, sessions_view)

    def _update_dashboard(self) -> None:
        _dashboard_helpers.update_dashboard(self)

    def _load_full_history(self, force: bool = False) -> None:
        _dashboard_helpers.load_full_history(self, force=force)

    def _refresh_shadow_status(self, status: Optional[Dict[str, Any]] = None, *, force: bool = False) -> None:
        _shadow_helpers.refresh_shadow_status(self, status, force=force)

    def _check_shadow_suggestion(self, status: Optional[Dict[str, Any]] = None) -> None:
        _shadow_helpers.check_shadow_suggestion(self, status)

    def _should_refresh_shadow_status(self) -> bool:
        return _shadow_helpers.should_refresh_shadow_status(self)

    def _consume_shadow_status_result(self) -> Optional[Dict[str, Any]]:
        return _shadow_helpers._consume_shadow_status_result(self)

    def _queue_shadow_status_refresh(self, user_id: str) -> bool:
        return _shadow_helpers._queue_shadow_status_refresh(self, user_id)

    def _should_scan_shadow_backlog(self) -> bool:
        return _shadow_helpers.should_scan_shadow_backlog(self)

    def _start_shadow_worker(self, archive_path: str, session_id: str = "", source: str = "runtime") -> None:
        _shadow_helpers.start_shadow_worker(self, archive_path, session_id=session_id, source=source)

    def _apply_shadow_worker_result(self, result: Any) -> None:
        _shadow_helpers.apply_shadow_worker_result(self, result)

    def _maybe_process_shadow_session(self) -> None:
        _shadow_helpers.maybe_process_shadow_session(self)

    def _maybe_process_shadow_backlog(self) -> None:
        _shadow_helpers.maybe_process_shadow_backlog(self)

    def _handle_state_alerts(self) -> None:
        _runtime_helpers.handle_state_alerts(self)

    def _fail_pending_logger_start(self, *, reason: str = "logger_unavailable", detail: str = "") -> None:
        _runtime_helpers.fail_pending_logger_start(self, reason=reason, detail=detail)

    def _maybe_finish_pending_logger_start(self) -> None:
        _runtime_helpers.maybe_finish_pending_logger_start(self)

    def _fail_pending_monitor_start(self, *, reason: str = "protected_monitor_failed", detail: str = "", diagnostics: Optional[Dict[str, Any]] = None) -> None:
        _runtime_helpers.fail_pending_monitor_start(self, reason=reason, detail=detail, diagnostics=diagnostics)

    def _fail_pending_shadow_evidence_monitor_start(self, *, reason: str = "shadow_evidence_monitor_failed", detail: str = "", diagnostics: Optional[Dict[str, Any]] = None) -> None:
        _runtime_helpers.fail_pending_shadow_evidence_monitor_start(self, reason=reason, detail=detail, diagnostics=diagnostics)

    def _maybe_finish_pending_monitor_start(self) -> None:
        _runtime_helpers.maybe_finish_pending_monitor_start(self)

    @Slot(str, bool)
    def requestRefresh(self, reason: str = "manual", force: bool = False) -> None:
        _runtime_helpers.request_refresh(self, reason=reason, force=force)

    @Slot()
    def refreshNow(self) -> None:
        _runtime_helpers.refresh_now(self)

    @Slot()
    def loadFullHistory(self) -> None:
        _dashboard_helpers.load_full_history(self, force=False)

    @Slot()
    def reloadFullHistory(self) -> None:
        _dashboard_helpers.load_full_history(self, force=True)
