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

def _full_history_profile_fields(self, user_id: str, *, visible_count: int, total_count: int | None = None, loading: bool = False, loaded: bool = False, error: str = "") -> Dict[str, Any]:
    total = _coerce_nonnegative_int(total_count if total_count is not None else visible_count)
    visible = _coerce_nonnegative_int(visible_count)
    if error:
        status = "error"
    elif loading:
        status = "loading"
    elif loaded:
        status = "loaded"
    elif total > visible:
        status = "partial"
    else:
        status = "loaded"
    return {
        "history_loading": bool(loading),
        "history_loaded": bool(loaded),
        "history_is_partial": bool(not loaded and total > visible),
        "history_session_count": total,
        "history_visible_session_count": visible,
        "history_status": status,
        "history_error": str(error or ""),
    }

def _merge_history_profile_fields(self, user_id: str, profile_view: Dict[str, Any], sessions_view: List[Dict[str, Any]]) -> Dict[str, Any]:
    _ensure_full_history_state(self)
    facade = _facade()
    safe_user = facade.slugify_username(user_id)
    profile = dict(profile_view or {})
    requested = bool(getattr(self, "_dashboard_full_history_requested", False))
    loading = bool(getattr(self, "_dashboard_full_history_loading", False) or getattr(self, "_dashboard_full_history_refresh_inflight", False))
    full_user = facade.slugify_username(getattr(self, "_dashboard_full_history_user", "") or "")
    full_cache = getattr(self, "_dashboard_full_history_cache", {})
    if requested and full_user == safe_user and isinstance(full_cache, dict) and full_cache:
        count = len(list(full_cache.get("sessions") or []))
        profile.update(_full_history_profile_fields(self, user_id, visible_count=count, total_count=count, loading=loading, loaded=not loading))
        return profile
    total = _coerce_nonnegative_int(profile.get("history_session_count", len(sessions_view)))
    visible = len(list(sessions_view or []))
    profile.update(_full_history_profile_fields(self, user_id, visible_count=visible, total_count=total, loading=loading, loaded=False))
    return profile

def _apply_full_history_result(self, user_id: str) -> bool:
    _ensure_full_history_state(self)
    facade = _facade()
    safe_user = facade.slugify_username(user_id)
    lock = getattr(self, "_dashboard_full_history_result_lock", None)
    if lock is None:
        return False
    with lock:
        result = getattr(self, "_dashboard_full_history_result", None)
        error = str(getattr(self, "_dashboard_full_history_result_error", "") or "")
        result_user = facade.slugify_username(getattr(self, "_dashboard_full_history_result_user", "") or "")
        completed_at = float(getattr(self, "_dashboard_full_history_result_completed_at", 0.0) or 0.0)
        result_generation = int(getattr(self, "_dashboard_full_history_result_generation", 0) or 0)
        applied_generation = int(getattr(self, "_dashboard_full_history_applied_generation", 0) or 0)
        self._dashboard_full_history_result = None
        self._dashboard_full_history_result_user = ""
        self._dashboard_full_history_result_error = ""
        self._dashboard_full_history_result_completed_at = 0.0
        self._dashboard_full_history_result_generation = 0
    if result is None and not error and not result_user and not result_generation:
        return False
    if result_user and result_user != safe_user:
        return False
    if result_generation and result_generation < applied_generation:
        return False
    self._dashboard_full_history_loading = False
    self._dashboard_full_history_refresh_inflight = False
    self._dashboard_full_history_refresh_user = ""
    _refresh_state.emit_dashboard_state_changed(self)
    if error:
        self._dashboard_full_history_error = _refresh_state._safe_dashboard_error_text(error)
        _refresh_state.set_dashboard_state(self, last_refresh_error=self._dashboard_full_history_error)
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("refresh", "full history worker failed", payload={"user": safe_user, "error": error}, level="warn")
        return False
    if not isinstance(result, dict):
        return False
    normalized = _normalized_snapshot(result)
    self._dashboard_full_history_cache = normalized
    self._dashboard_full_history_user = safe_user
    self._dashboard_full_history_cached_at = completed_at or facade.time.time()
    self._dashboard_full_history_applied_generation = max(applied_generation, result_generation)
    self._dashboard_full_history_error = ""
    _refresh_state.set_dashboard_state(self, last_refresh_error="")
    return True

def _queue_full_history_refresh(self, user_id: str, *, force: bool = False) -> bool:
    _ensure_full_history_state(self)
    facade = _facade()
    safe_user = facade.slugify_username(user_id)
    if not safe_user:
        return False
    if bool(getattr(self, "_dashboard_full_history_refresh_inflight", False)):
        inflight_user = facade.slugify_username(getattr(self, "_dashboard_full_history_refresh_user", "") or "")
        if inflight_user == safe_user:
            return False
    if not force:
        cached_user = facade.slugify_username(getattr(self, "_dashboard_full_history_user", "") or "")
        cached = getattr(self, "_dashboard_full_history_cache", {})
        if cached_user == safe_user and isinstance(cached, dict) and cached:
            return False
    lock = getattr(self, "_dashboard_full_history_result_lock", None)
    if lock is None:
        return False
    generation = int(getattr(self, "_dashboard_full_history_generation", 0) or 0) + 1
    self._dashboard_full_history_generation = generation
    self._dashboard_full_history_requested = True
    self._dashboard_full_history_loading = True
    self._dashboard_full_history_refresh_inflight = True
    self._dashboard_full_history_refresh_user = safe_user
    _refresh_state.set_dashboard_state(self, updating=True, stale=True, last_refresh_reason="history:load_full")

    def _schedule_apply_refresh() -> None:
        request = getattr(self, "requestRefresh", None)
        if callable(request):
            dispatch_to_qt_thread(
                self,
                lambda: request("history:full_history_ready", False),
                target_action="history_full_history_ready",
            )

    def worker() -> None:
        result: Dict[str, Any] | None = None
        error = ""
        try:
            result = _compute_full_history_snapshot(self, user_id)
        except Exception as exc:
            LOGGER.exception("Dashboard full-history worker failed")
            error = str(exc)
        finally:
            completed_at = facade.time.time()
            with lock:
                latest_generation = int(getattr(self, "_dashboard_full_history_generation", 0) or 0)
                if generation == latest_generation:
                    self._dashboard_full_history_result = result
                    self._dashboard_full_history_result_user = safe_user
                    self._dashboard_full_history_result_error = error
                    self._dashboard_full_history_result_completed_at = completed_at
                    self._dashboard_full_history_result_generation = generation
            if generation == int(getattr(self, "_dashboard_full_history_generation", 0) or 0):
                self._dashboard_full_history_refresh_inflight = False
                self._dashboard_full_history_refresh_user = ""
            _schedule_apply_refresh()

    facade.threading.Thread(target=worker, daemon=True).start()
    return True

def load_full_history(self, force: bool = False) -> None:
    _ensure_full_history_state(self)
    if not getattr(self, "_current_user", None):
        return
    user_id = self._current_user["user_id"]
    self._dashboard_full_history_requested = True
    _apply_full_history_result(self, user_id)
    _queue_full_history_refresh(self, user_id, force=force)
    request = getattr(self, "requestRefresh", None)
    if callable(request):
        request("history:load_full", False)

def _history_logger_still_finalizing(self) -> bool:
    try:
        logger_key_func = getattr(self, "_logger_process_key", None) or getattr(self, "_logger_key", None)
        logger_key = logger_key_func() if callable(logger_key_func) else ""
        running = getattr(self, "_running_processes", {}) or {}
        proc = running.get(logger_key) if logger_key else None
        return bool(proc is not None and proc.poll() is None)
    except Exception:
        LOGGER.debug("Failed checking whether logger process is running; treating as stopped.", exc_info=True)
        return False

def _finish_history_archive_watch(self, *, status: str, warning: str = "") -> None:
    self._history_sync_pending = False
    self._history_sync_deadline = 0.0
    self._history_sync_hard_deadline = 0.0
    self._history_sync_status = status
    self._history_sync_warning = warning

def sync_history_after_archive(self, user_id: str, runtime_view: Dict[str, Any], profile_view: Dict[str, Any], sessions_view: list[Dict[str, Any]]) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
    facade = _facade()
    if not bool(getattr(self, "_history_sync_pending", False)):
        return profile_view, sessions_view

    now = facade.time.time()
    soft_deadline = float(getattr(self, "_history_sync_deadline", 0.0) or 0.0)
    hard_deadline = float(getattr(self, "_history_sync_hard_deadline", 0.0) or soft_deadline or 0.0)
    soft_expired = bool(soft_deadline and now >= soft_deadline)
    hard_expired = bool(hard_deadline and now >= hard_deadline)
    logger_still_finalizing = _history_logger_still_finalizing(self)

    archive_path = ""
    if bool(runtime_view.get("archived")):
        archive_path = os.path.realpath(str(runtime_view.get("archive_path") or "").strip())

    if not archive_path:
        if hard_expired:
            _finish_history_archive_watch(self, status="archive_unavailable", warning="history_archive_unavailable")
            set_status = getattr(self, "_set_status", None)
            if callable(set_status):
                set_status(self._t("history_archive_unavailable"), "warn")
        else:
            # Keep polling past the soft deadline because archive handoff may
            # still be plausibly finalizing after logger exit or slow disk I/O.
            # The hard deadline remains the bounded safety stop.
            self._history_sync_status = "finalizing_delayed" if soft_expired and not logger_still_finalizing else "finalizing"
        return profile_view, sessions_view

    session_paths = {os.path.realpath(str(item.get("path") or "")) for item in sessions_view if item.get("path")}
    if archive_path not in session_paths:
        try:
            facade.update_session_index_for_path(archive_path)
        except Exception:
            LOGGER.warning("Failed updating session index for newly archived session %s", archive_path, exc_info=True)
        facade.invalidate_session_discovery_cache()
        self._invalidate_dashboard_snapshot_cache()
        try:
            snapshot = self._dashboard_snapshot(user_id, force=True)
        except TypeError:
            snapshot = self._dashboard_snapshot(user_id)
        profile_view = self._build_profile_view(snapshot.get("profile") or {})
        sessions_view = [dict(item) for item in list(snapshot.get("sessions") or [])]
        session_paths = {os.path.realpath(str(item.get("path") or "")) for item in sessions_view if item.get("path")}

    if archive_path in session_paths:
        _finish_history_archive_watch(self, status="synced")
        self._last_history_synced_archive_path = archive_path
    elif hard_expired:
        _finish_history_archive_watch(self, status="archive_unavailable", warning="history_archive_unavailable")
        set_status = getattr(self, "_set_status", None)
        if callable(set_status):
            set_status(self._t("history_archive_unavailable"), "warn")
    else:
        self._history_sync_status = "finalizing"

    return profile_view, sessions_view
