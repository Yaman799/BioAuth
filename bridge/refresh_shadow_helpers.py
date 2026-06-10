from __future__ import annotations

import logging
import os
from importlib import import_module
from typing import Any, Dict, Optional

LOGGER = logging.getLogger(__name__)


def _facade():
    return import_module("bridge.refresh_mixin")


def _env_flag(name: str, default: bool = False) -> bool:
    value = str(os.environ.get(name, "") or "").strip().lower()
    if not value:
        return bool(default)
    return value in {"1", "true", "yes", "on", "enabled"}


def _ui_performance_optimization_enabled() -> bool:
    return not _env_flag("BIOAUTH_DISABLE_UI_PERFORMANCE_OPTIMIZATION", False)


def _legacy_shadow_polling_enabled() -> bool:
    # Commercial-Core-22C: legacy shadow polling/backlog scans are expensive and
    # are no longer part of the commercial runtime-fed shadow path.  Keep an
    # explicit developer escape hatch for old research workflows.
    return _env_flag("BIOAUTH_ENABLE_LEGACY_SHADOW_STATUS_POLLING", False) or _env_flag("BIOAUTH_ENABLE_LEGACY_SHADOW_BACKLOG_SCAN", False)


def _dashboard_visible(self) -> bool:
    return bool(getattr(self, "_dashboard_visible", True))


def _shadow_automation_paused(self) -> bool:
    return bool(getattr(self, "_shadow_automation_paused", False))


def _annotate_shadow_status(self, status: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(status or {})
    paused = _shadow_automation_paused(self)
    payload["automation_paused"] = paused
    payload["shadow_automation_paused"] = paused
    if paused:
        payload.setdefault("pause_reason", "developer_shadow_paused")
        if str(payload.get("phase") or "").strip().lower() in {"", "collecting", "training_pending", "evaluating", "ready"}:
            payload["phase"] = "developer_paused"
        payload["suggestion_pending"] = False
    else:
        payload.pop("pause_reason", None)
    return payload


def _async_shadow_status_enabled(self) -> bool:
    return bool(getattr(self, "_shadow_status_refresh_enabled", False)) and hasattr(self, "_shadow_status_result_lock")


def _consume_shadow_status_result(self) -> Optional[Dict[str, Any]]:
    facade = _facade()
    if not _async_shadow_status_enabled(self):
        return None
    lock = getattr(self, "_shadow_status_result_lock", None)
    if lock is None:
        return None
    with lock:
        status = getattr(self, "_shadow_status_result", None)
        result_user = facade.slugify_username(getattr(self, "_shadow_status_result_user", "") or "")
        error = str(getattr(self, "_shadow_status_result_error", "") or "")
        self._shadow_status_result = None
        self._shadow_status_result_user = ""
        self._shadow_status_result_error = ""
    current_user = facade.slugify_username((getattr(self, "_current_user", {}) or {}).get("user_id", "") or "")
    if result_user and current_user and result_user != current_user:
        return None
    if error:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("refresh", "shadow status worker failed", payload={"user": current_user, "error": error}, level="warn")
        return None
    return dict(status) if isinstance(status, dict) else None


def _queue_shadow_status_refresh(self, user_id: str) -> bool:
    facade = _facade()
    if not _async_shadow_status_enabled(self):
        return False
    safe_user = facade.slugify_username(user_id)
    if not safe_user:
        return False
    inflight = bool(getattr(self, "_shadow_status_refresh_inflight", False))
    inflight_user = facade.slugify_username(getattr(self, "_shadow_status_refresh_user", "") or "")
    if inflight:
        return inflight_user == safe_user
    lock = getattr(self, "_shadow_status_result_lock", None)
    if lock is None:
        return False
    self._shadow_status_refresh_inflight = True
    self._shadow_status_refresh_user = safe_user

    def worker() -> None:
        status: Optional[Dict[str, Any]] = None
        error = ""
        try:
            status = facade.get_shadow_status(user_id)
        except Exception as exc:
            error = str(exc)
        finally:
            with lock:
                self._shadow_status_result = dict(status) if isinstance(status, dict) else None
                self._shadow_status_result_user = safe_user
                self._shadow_status_result_error = error
            self._shadow_status_refresh_inflight = False
            self._shadow_status_refresh_user = ""

    facade.threading.Thread(target=worker, daemon=True).start()
    return True


def refresh_shadow_status(self, status: Optional[Dict[str, Any]] = None, *, force: bool = False) -> None:
    facade = _facade()
    if not self._current_user:
        baseline = _annotate_shadow_status(self, {"phase": "collecting", "ready": False, "suggestion_pending": False})
        if force or baseline != self._shadow_status:
            self._shadow_status = baseline
            self.shadowChanged.emit()
        return

    result_status = _consume_shadow_status_result(self)
    if result_status is not None:
        self._last_shadow_status_refresh_at = facade.time.time()
    status_map = None
    if isinstance(status, dict):
        status_map = dict(status)
    elif isinstance(result_status, dict):
        status_map = dict(result_status)
    elif force or not _async_shadow_status_enabled(self):
        status_map = facade.get_shadow_status(self._current_user["user_id"])
    else:
        status_map = dict(self._shadow_status) if isinstance(self._shadow_status, dict) else {"phase": "collecting", "ready": False, "suggestion_pending": False}

    status_map = _annotate_shadow_status(self, status_map)
    status_map["suggestion_pending"] = bool((not _shadow_automation_paused(self)) and self._pending_shadow_suggestion and status_map.get("promote_suggested"))
    status_map["pending_avg_delta"] = round(float(self._pending_shadow_avg_delta or status_map.get("avg_delta", 0.0) or 0.0), 2)
    if force or status_map != self._shadow_status:
        self._shadow_status = status_map
        self.shadowChanged.emit()


def check_shadow_suggestion(self, status: Optional[Dict[str, Any]] = None) -> None:
    facade = _facade()
    if not self._current_user:
        return
    if _shadow_automation_paused(self):
        self._pending_shadow_suggestion = False
        self._pending_shadow_avg_delta = 0.0
        self._shadow_suggestion_dismissed = True
        return
    if not isinstance(status, dict) and _ui_performance_optimization_enabled() and not _legacy_shadow_polling_enabled():
        snapshot = dict(self._shadow_status) if isinstance(getattr(self, "_shadow_status", None), dict) else {"phase": "collecting", "ready": False}
    else:
        snapshot = dict(status) if isinstance(status, dict) else facade.get_shadow_status(self._current_user["user_id"])
    snoozed_until = int(snapshot.get("suggestion_snoozed_until_total_eval_count", 0) or 0)
    total_eval_count = int(snapshot.get("total_eval_count", 0) or 0)
    should_show = bool(snapshot.get("promote_suggested")) and total_eval_count >= snoozed_until and not self._shadow_suggestion_dismissed
    if should_show:
        self._pending_shadow_suggestion = True
        self._pending_shadow_avg_delta = float(snapshot.get("avg_delta", 0.0) or 0.0)
    elif not snapshot.get("promote_suggested"):
        self._pending_shadow_suggestion = False
        self._pending_shadow_avg_delta = 0.0
        self._shadow_suggestion_dismissed = False
    elif total_eval_count >= snoozed_until:
        self._shadow_suggestion_dismissed = False


def should_refresh_shadow_status(self) -> bool:
    facade = _facade()
    if _shadow_automation_paused(self):
        return False
    if self._pending_shadow_suggestion or bool(getattr(self, "_shadow_worker_running", False)):
        return True
    if _ui_performance_optimization_enabled() and not _legacy_shadow_polling_enabled():
        # Runtime-fed shadow evidence is the commercial default.  Do not poll the
        # legacy shadow model status every refresh when there is no live worker or
        # pending promotion suggestion; the cached status is enough for UI labels.
        return False
    interval = float(getattr(self, "SHADOW_STATUS_REFRESH_SEC", 12.0) or 12.0)
    if _ui_performance_optimization_enabled() and not _dashboard_visible(self):
        interval = max(interval, 60.0)
    return (facade.time.time() - float(getattr(self, "_last_shadow_status_refresh_at", 0.0) or 0.0)) >= interval


def should_scan_shadow_backlog(self) -> bool:
    facade = _facade()
    if _shadow_automation_paused(self):
        return False
    if _ui_performance_optimization_enabled() and not _legacy_shadow_polling_enabled():
        # Avoid multi-second legacy backlog scans in the UI refresh loop.
        # Runtime-fed shadow ledger processing remains available through its own
        # explicit path; old backlog scanning can be re-enabled for research with
        # BIOAUTH_ENABLE_LEGACY_SHADOW_BACKLOG_SCAN=1.
        return False
    runtime_state = self._runtime_state if isinstance(getattr(self, "_runtime_state", None), dict) else {}
    if runtime_state.get("active"):
        return False
    interval = float(getattr(self, "SHADOW_BACKLOG_SCAN_IDLE_SEC", 30.0) or 30.0)
    if _ui_performance_optimization_enabled() and not _dashboard_visible(self):
        interval = max(interval, 120.0)
    return (facade.time.time() - float(getattr(self, "_last_shadow_backlog_scan_at", 0.0) or 0.0)) >= interval


def start_shadow_worker(self, archive_path: str, session_id: str = "", source: str = "runtime") -> None:
    facade = _facade()
    if not self._current_user or self._shadow_worker_running or _shadow_automation_paused(self):
        return
    user_id = self._current_user["user_id"]
    self._shadow_worker_running = True

    def worker() -> None:
        result = {
            "ok": True,
            "user_id": user_id,
            "archive_path": archive_path,
            "session_id": session_id,
            "source": source,
            "evaluated": False,
            "trained": False,
        }
        try:
            facade.log_shadow_event(user_id, "worker_started", session_path=archive_path, session_id=session_id, source=source)
            facade.register_legit_session_for_shadow(user_id, archive_path)
            status = facade.get_shadow_status(user_id)
            if status.get("phase") == "training_pending":
                train_result = facade.train_shadow_model(user_id)
                result["trained"] = bool(train_result.get("ok"))
                status = facade.get_shadow_status(user_id)
                if status.get("phase") in {"evaluating", "ready"}:
                    eval_result = facade.evaluate_shadow_vs_main(user_id, archive_path)
                    result["evaluated"] = bool(eval_result.get("ok"))
                    status = facade.get_shadow_status(user_id)
            elif status.get("phase") in {"evaluating", "ready"}:
                eval_result = facade.evaluate_shadow_vs_main(user_id, archive_path)
                result["evaluated"] = bool(eval_result.get("ok"))
                status = facade.get_shadow_status(user_id)
            result["status"] = status
            facade.log_shadow_event(
                user_id,
                "worker_finished",
                session_path=archive_path,
                session_id=session_id,
                source=source,
                trained=result.get("trained"),
                evaluated=result.get("evaluated"),
                phase=status.get("phase") if isinstance(status, dict) else None,
            )
        except (OSError, ValueError, TypeError, RuntimeError, TimeoutError, facade.SecurityError) as exc:
            LOGGER.warning("Shadow worker failed for %s: %s", user_id, exc, exc_info=True)
            result["ok"] = False
            result["error"] = str(exc)
            facade.log_shadow_event(user_id, "worker_failed", level="error", reason=str(exc), session_path=archive_path, session_id=session_id, source=source)
        except Exception as exc:
            LOGGER.exception("Unexpected shadow worker failure for %s", user_id)
            result["ok"] = False
            result["error"] = f"unexpected_shadow_worker_error: {exc}"
            facade.log_shadow_event(user_id, "worker_failed", level="error", reason=result["error"], session_path=archive_path, session_id=session_id, source=source)
        self.shadowWorkerFinished.emit(result)

    facade.threading.Thread(target=worker, daemon=True).start()


def apply_shadow_worker_result(self, result: Any) -> None:
    facade = _facade()
    self._shadow_worker_running = False
    self._last_shadow_status_refresh_at = 0.0
    self._last_shadow_backlog_scan_at = 0.0
    if not isinstance(result, dict):
        self._refresh_shadow_status(force=True)
        return
    if _shadow_automation_paused(self):
        self._pending_shadow_suggestion = False
        self._pending_shadow_avg_delta = 0.0
    if self._current_user and result.get("user_id") == self._current_user.get("user_id"):
        if result.get("archive_path"):
            self._last_shadow_processed_archive_path = str(result.get("archive_path") or "")
        if result.get("session_id"):
            self._last_shadow_processed_session_id = str(result.get("session_id") or "")
        status = result.get("status") if isinstance(result.get("status"), dict) else facade.get_shadow_status(self._current_user["user_id"])
        self._check_shadow_suggestion(status)
        self._refresh_shadow_status(status, force=True)
    else:
        self._refresh_shadow_status(force=True)


def maybe_process_shadow_session(self) -> None:
    if not self._current_user or self._shadow_worker_running or _shadow_automation_paused(self):
        return
    state = self._runtime_state if isinstance(self._runtime_state, dict) else {}
    if not bool(state.get("archived")):
        return
    archive_path = str(state.get("archive_path") or "").strip()
    session_id = str(state.get("session_id") or "").strip()
    decision = str(state.get("final_decision") or state.get("decision") or state.get("archive_label") or "").strip().lower()
    session_kind = str(state.get("session_kind") or "").strip().lower()
    state_user = str(state.get("user_id") or "").strip()
    if session_kind != "protected" or decision not in {"legit", "legitimate", "accepted"} or not archive_path:
        return
    if state_user and state_user != self._current_user.get("user_id"):
        return
    if archive_path == self._last_shadow_processed_archive_path or (session_id and session_id == self._last_shadow_processed_session_id):
        return
    self._start_shadow_worker(archive_path, session_id=session_id, source="runtime")


def maybe_process_shadow_backlog(self) -> None:
    facade = _facade()
    if not self._current_user or self._shadow_worker_running or not self._should_scan_shadow_backlog():
        return
    self._last_shadow_backlog_scan_at = facade.time.time()
    pending = facade.list_shadow_backlog_sessions(self._current_user["user_id"], limit=12)
    if not pending:
        return
    current_archive = str((self._runtime_state or {}).get("archive_path") or "").strip() if isinstance(self._runtime_state, dict) else ""
    for session_path in pending:
        if session_path == current_archive:
            continue
        if session_path == self._last_shadow_processed_archive_path:
            continue
        self._start_shadow_worker(session_path, session_id="", source="backlog")
        return
