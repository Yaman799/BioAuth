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

def _apply_dashboard_snapshot_result(self, user_id: str) -> bool:
    facade = _facade()
    if not _async_snapshot_enabled(self):
        return False
    safe_user = facade.slugify_username(user_id)
    self._dashboard_snapshot_apply_had_error = False
    lock = getattr(self, "_dashboard_snapshot_result_lock", None)
    if lock is None:
        return False
    with lock:
        result = getattr(self, "_dashboard_snapshot_result", None)
        error = str(getattr(self, "_dashboard_snapshot_result_error", "") or "")
        result_user = facade.slugify_username(getattr(self, "_dashboard_snapshot_result_user", "") or "")
        completed_at = float(getattr(self, "_dashboard_snapshot_result_completed_at", 0.0) or 0.0)
        result_generation = int(getattr(self, "_dashboard_snapshot_result_generation", 0) or 0)
        result_duration_ms = _coerce_nonnegative_int(getattr(self, "_dashboard_snapshot_result_duration_ms", 0) or 0)
        applied_generation = int(getattr(self, "_dashboard_snapshot_applied_generation", 0) or 0)
        self._dashboard_snapshot_result = None
        self._dashboard_snapshot_result_user = ""
        self._dashboard_snapshot_result_error = ""
        self._dashboard_snapshot_result_completed_at = 0.0
        self._dashboard_snapshot_result_generation = 0
        self._dashboard_snapshot_result_duration_ms = 0
    if result_user and result_user != safe_user:
        return False
    if result_generation and result_generation < applied_generation:
        return False
    if error:
        self._dashboard_snapshot_apply_had_error = True
        _refresh_state.set_dashboard_state(
            self,
            loading=False,
            updating=False,
            stale=bool(getattr(self, "_dashboard_snapshot_cache", {}) or getattr(self, "_profile", {}) or getattr(self, "_sessions", [])),
            last_snapshot_duration_ms=result_duration_ms,
            last_refresh_error=error,
            completed_at=completed_at or facade.time.time(),
        )
        self._dashboard_snapshot_last_failure_at = completed_at or facade.time.time()
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("refresh", "dashboard snapshot worker failed", payload={"user": safe_user, "error": _refresh_state._safe_dashboard_error_text(error)}, level="warn")
        return False
    if not isinstance(result, dict):
        return False
    normalized = _normalized_snapshot(result)
    self._dashboard_snapshot_cache = normalized
    self._dashboard_snapshot_user = safe_user
    self._dashboard_snapshot_cached_at = completed_at or facade.time.time()
    self._dashboard_snapshot_applied_generation = max(applied_generation, result_generation)
    _refresh_state.set_dashboard_state(
        self,
        loading=False,
        updating=False,
        stale=False,
        last_snapshot_duration_ms=result_duration_ms,
        last_refresh_error="",
        completed_at=completed_at or facade.time.time(),
    )
    self._dashboard_snapshot_last_failure_at = 0.0
    return True

def _queue_dashboard_snapshot_refresh(self, user_id: str, *, force: bool = False) -> bool:
    facade = _facade()
    if not _async_snapshot_enabled(self):
        return False
    safe_user = facade.slugify_username(user_id)
    if not safe_user:
        return False
    lock = getattr(self, "_dashboard_snapshot_result_lock", None)
    if lock is None:
        return False
    active_workers = getattr(self, "_dashboard_snapshot_active_workers", None)
    if not isinstance(active_workers, dict):
        active_workers = {}
        self._dashboard_snapshot_active_workers = active_workers
    inflight = bool(getattr(self, "_dashboard_snapshot_refresh_inflight", False))
    inflight_user = facade.slugify_username(getattr(self, "_dashboard_snapshot_refresh_user", "") or "")
    inflight_force = bool(getattr(self, "_dashboard_snapshot_refresh_force", False))
    active_worker_count = _coerce_nonnegative_int(active_workers.get(safe_user, 0))
    if active_worker_count > 0:
        if not force or inflight_force:
            return False
    elif inflight:
        if inflight_user != safe_user:
            return False
        if not force or inflight_force:
            return False

    generation = int(getattr(self, "_dashboard_snapshot_refresh_generation", 0) or 0) + 1
    self._dashboard_snapshot_refresh_generation = generation
    self._dashboard_snapshot_refresh_inflight = True
    self._dashboard_snapshot_refresh_user = safe_user
    self._dashboard_snapshot_refresh_force = bool(force or inflight_force)
    self._dashboard_snapshot_refresh_requested_at = facade.time.time()
    active_workers[safe_user] = active_worker_count + 1

    def _schedule_apply_refresh() -> None:
        request = getattr(self, "requestRefresh", None)
        if callable(request):
            dispatch_to_qt_thread(
                self,
                lambda: request("dashboard:snapshot_ready", False),
                target_action="dashboard_snapshot_ready",
            )

    def worker() -> None:
        result: Dict[str, Any] | None = None
        error = ""
        worker_started_at = _time_now(facade)
        try:
            result = _compute_dashboard_snapshot(self, user_id)
        except Exception as exc:
            LOGGER.exception("Dashboard snapshot worker failed")
            error = str(exc)
        finally:
            completed_at = facade.time.time()
            duration_ms = _elapsed_ms(facade, worker_started_at)
            with lock:
                latest_generation = int(getattr(self, "_dashboard_snapshot_refresh_generation", 0) or 0)
                if generation == latest_generation:
                    self._dashboard_snapshot_result = result
                    self._dashboard_snapshot_result_user = safe_user
                    self._dashboard_snapshot_result_error = error
                    self._dashboard_snapshot_result_completed_at = completed_at
                    self._dashboard_snapshot_result_generation = generation
                    self._dashboard_snapshot_result_duration_ms = duration_ms
            active_workers = getattr(self, "_dashboard_snapshot_active_workers", None)
            if isinstance(active_workers, dict):
                remaining = _coerce_nonnegative_int(active_workers.get(safe_user, 0)) - 1
                if remaining > 0:
                    active_workers[safe_user] = remaining
                else:
                    active_workers.pop(safe_user, None)
            if generation == int(getattr(self, "_dashboard_snapshot_refresh_generation", 0) or 0):
                self._dashboard_snapshot_refresh_inflight = False
                self._dashboard_snapshot_refresh_user = ""
                self._dashboard_snapshot_refresh_force = False
                self._dashboard_snapshot_refresh_requested_at = 0.0
                _schedule_apply_refresh()
            elif isinstance(active_workers, dict) and not active_workers:
                self._dashboard_snapshot_refresh_inflight = False
                self._dashboard_snapshot_refresh_user = ""
                self._dashboard_snapshot_refresh_force = False
                self._dashboard_snapshot_refresh_requested_at = 0.0
                _schedule_apply_refresh()

    facade.threading.Thread(target=worker, daemon=True).start()
    return True

def dashboard_snapshot(self, user_id: str, *, force: bool = False) -> Dict[str, Any]:
    facade = _facade()
    safe_user = facade.slugify_username(user_id)

    _apply_dashboard_snapshot_result(self, user_id)
    applied_error = bool(getattr(self, "_dashboard_snapshot_apply_had_error", False))
    has_cache, cache_valid, cached_snapshot, cached_session_count = _dashboard_cache_state(self, user_id)

    if _async_snapshot_enabled(self):
        queued = False
        last_failure_at = float(getattr(self, "_dashboard_snapshot_last_failure_at", 0.0) or 0.0)
        recent_failure = bool(last_failure_at and (facade.time.time() - last_failure_at) < 1.0)
        if (force or not cache_valid) and not applied_error and not recent_failure:
            queued = _queue_dashboard_snapshot_refresh(self, user_id, force=force)
        if cache_valid or has_cache:
            _refresh_state.set_dashboard_state(
                self,
                loading=False,
                updating=bool(queued or getattr(self, "_dashboard_snapshot_refresh_inflight", False)),
                stale=bool(force or not cache_valid or queued),
            )
            _set_dashboard_debug_timing(self, None, cache_hit=True, session_count=cached_session_count)
            return _normalized_snapshot(cached_snapshot)
        fallback = _snapshot_fallback(self, user_id)
        fallback_count = len(list(fallback.get("sessions") or []))
        _refresh_state.set_dashboard_state(
            self,
            loading=bool(queued and fallback_count == 0 and not (fallback.get("profile") or {})),
            updating=bool(queued or getattr(self, "_dashboard_snapshot_refresh_inflight", False)),
            stale=bool(fallback_count > 0 or bool(fallback.get("profile") or {})),
        )
        _set_dashboard_debug_timing(self, None, cache_hit=False, session_count=fallback_count)
        return _normalized_snapshot(fallback)

    normalized = _compute_dashboard_snapshot(self, user_id)
    self._dashboard_snapshot_cache = normalized
    self._dashboard_snapshot_user = safe_user
    self._dashboard_snapshot_cached_at = facade.time.time()
    self._dashboard_snapshot_applied_generation = int(getattr(self, "_dashboard_snapshot_refresh_generation", 0) or 0)
    return _normalized_snapshot(normalized)

def _ensure_full_history_state(self) -> None:
    if not hasattr(self, "_dashboard_full_history_cache"):
        self._dashboard_full_history_cache = {}
    if not hasattr(self, "_dashboard_full_history_user"):
        self._dashboard_full_history_user = ""
    if not hasattr(self, "_dashboard_full_history_cached_at"):
        self._dashboard_full_history_cached_at = 0.0
    if not hasattr(self, "_dashboard_full_history_requested"):
        self._dashboard_full_history_requested = False
    if not hasattr(self, "_dashboard_full_history_loading"):
        self._dashboard_full_history_loading = False
    if not hasattr(self, "_dashboard_full_history_refresh_inflight"):
        self._dashboard_full_history_refresh_inflight = False
    if not hasattr(self, "_dashboard_full_history_refresh_user"):
        self._dashboard_full_history_refresh_user = ""
    if not hasattr(self, "_dashboard_full_history_result_lock"):
        try:
            self._dashboard_full_history_result_lock = _facade().threading.Lock()
        except Exception:
            LOGGER.debug("Failed creating full-history result lock; reusing dashboard snapshot lock.", exc_info=True)
            self._dashboard_full_history_result_lock = getattr(self, "_dashboard_snapshot_result_lock", None)
    if not hasattr(self, "_dashboard_full_history_result"):
        self._dashboard_full_history_result = None
    if not hasattr(self, "_dashboard_full_history_result_user"):
        self._dashboard_full_history_result_user = ""
    if not hasattr(self, "_dashboard_full_history_result_error"):
        self._dashboard_full_history_result_error = ""
    if not hasattr(self, "_dashboard_full_history_result_completed_at"):
        self._dashboard_full_history_result_completed_at = 0.0
    if not hasattr(self, "_dashboard_full_history_generation"):
        self._dashboard_full_history_generation = 0
    if not hasattr(self, "_dashboard_full_history_result_generation"):
        self._dashboard_full_history_result_generation = 0
    if not hasattr(self, "_dashboard_full_history_applied_generation"):
        self._dashboard_full_history_applied_generation = 0
