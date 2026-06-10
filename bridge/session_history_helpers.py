from __future__ import annotations

import logging
from importlib import import_module
from typing import Any, Dict, List

LOGGER = logging.getLogger(__name__)


def _facade():
    return import_module("bridge.session_mixin")


def _request_refresh(self, reason: str, force: bool = False) -> None:
    request = getattr(self, "requestRefresh", None)
    if callable(request):
        request(reason, force)
        return
    legacy = getattr(self, "refreshNow", None)
    if callable(legacy):
        legacy()


def session_details(self, path: str) -> Dict[str, Any]:
    facade = _facade()
    try:
        resolved, meta = self._resolve_user_session_path(path)
    except (OSError, ValueError):
        return {"path": path}
    if not meta:
        return {"path": resolved}
    evidence_meta = meta.get("incident_evidence") if isinstance(meta.get("incident_evidence"), dict) else {}
    evidence_dir_path = str(meta.get("incident_evidence_dir") or evidence_meta.get("incident_directory") or "")
    training_view: Dict[str, Any] = {}
    resolved_path = facade.os.path.abspath(resolved)
    for item in list(getattr(self, "_sessions", []) or []):
        if facade.os.path.abspath(str(item.get("path") or "")) == resolved_path:
            training_view = dict(item)
            break
    if self._current_user and not training_view:
        try:
            try:
                snapshot = facade.build_user_dashboard_snapshot(
                    self._current_user["user_id"],
                    include_training_selection_details=True,
                    session_detail_limit=None,
                )
            except TypeError:
                snapshot = facade.build_user_dashboard_snapshot(self._current_user["user_id"])
            for item in list(snapshot.get("sessions") or []):
                if facade.os.path.abspath(str(item.get("path") or "")) == resolved_path:
                    training_view = dict(item)
                    break
        except Exception:
            training_view = {}
    return {
        "path": resolved,
        "session_id": meta.get("session_id") or facade.os.path.basename(resolved),
        "created_at": meta.get("created_at", ""),
        "session_kind": meta.get("session_kind", "unknown"),
        "decision": meta.get("final_decision", meta.get("archive_label", "unknown")),
        "keyboard_rows": int(meta.get("keyboard_rows", 0) or 0),
        "mouse_rows": int(meta.get("mouse_rows", 0) or 0),
        "privacy_mode": meta.get("privacy_mode", "standard"),
        "metadata_trusted": bool(meta.get("metadata_trusted")),
        "metadata_integrity": meta.get("metadata_integrity", "unknown"),
        "metadata_diagnostic": meta.get("metadata_diagnostic", ""),
        "training_visibility": training_view.get("training_visibility", "not_applicable"),
        "training_status_tone": training_view.get("training_status_tone", "neutral"),
        "training_counts_toward_minimum": bool(training_view.get("training_counts_toward_minimum")),
        "training_selected": bool(training_view.get("training_selected")),
        "training_quality_score": training_view.get("training_quality_score"),
        "training_quality_tier": training_view.get("training_quality_tier", ""),
        "training_selection_reason": training_view.get("training_selection_reason", ""),
        "training_block_reason": training_view.get("training_block_reason", ""),
        "training_reason_detail": training_view.get("training_reason_detail", ""),
        "incident_evidence_available": bool(evidence_meta),
        "incident_evidence_status": meta.get("incident_evidence_status", evidence_meta.get("webcam_status") or ""),
        "incident_evidence_saved_count": int(meta.get("incident_evidence_saved_count", 0) or 0),
        "incident_evidence_dir": evidence_dir_path,
        "incident_evidence_notice": evidence_meta.get("trigger_reason") or "",
    }


def assert_session_is_deletable(self, resolved: str) -> None:
    facade = _facade()
    active_archive = facade.os.path.realpath(str(self._runtime_state.get("archive_path") or self._runtime_state.get("path") or ""))
    if active_archive and active_archive == resolved:
        raise ValueError(self._t("history_delete_active"))
    state = self._active_state_for_current_user()
    state_archive = facade.os.path.realpath(str(state.get("archive_path") or state.get("path") or "")) if state else ""
    if state_archive and state_archive == resolved:
        raise ValueError(self._t("history_delete_active"))


def delete_archived_session_path(self, path: str) -> str:
    facade = _facade()
    resolved, meta = self._resolve_user_session_path(path)
    self._assert_session_is_deletable(resolved)
    session_id = str(meta.get("session_id") or "").strip()
    facade.shutil.rmtree(resolved)
    try:
        facade.remove_session_from_index(resolved)
    except Exception:
        LOGGER.debug("Failed removing deleted session from index", exc_info=True)
    if session_id:
        facade.delete_evidence_for_session(session_id)
    return resolved


def drop_deleted_sessions_from_cache(self, resolved_paths: List[str]) -> None:
    facade = _facade()
    if not resolved_paths:
        return
    resolved_set = {facade.os.path.realpath(path) for path in resolved_paths}
    self._sessions = [
        session
        for session in list(getattr(self, "_sessions", []) or [])
        if facade.os.path.realpath(str(session.get("path") or "")) not in resolved_set
    ]
    self.sessionsChanged.emit()


def delete_session(self, path: str) -> None:
    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("action", "deleteSession requested", payload={"path": str(path or "")})
    if not self._current_user or not path:
        return
    try:
        resolved = self._delete_archived_session_path(path)
        facade.invalidate_session_discovery_cache()
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        self._drop_deleted_sessions_from_cache([resolved])
        self._set_status(self._t("history_delete_success"), "success")
    except ValueError as exc:
        self._set_status(str(exc) if str(exc) else self._t("history_delete_fail"), "danger")
    except OSError as exc:
        LOGGER.exception("Failed deleting archived session %s", path)
        detail = str(exc).strip()
        message = self._t("history_delete_fail")
        if detail:
            message = f"{message}: {detail}"
        self._set_status(message, "danger")
    _request_refresh(self, "history:delete_last_session", False)


def delete_sessions(self, paths: List[Any]) -> None:
    facade = _facade()
    debug = getattr(self, "_debug_trace", None)
    if callable(debug):
        debug("action", "deleteSessions requested", payload={"count": len(list(paths or []))})
    if not self._current_user or not paths:
        return
    unique_paths: List[str] = []
    seen: set[str] = set()
    for raw in list(paths or []):
        path = str(raw or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)
    if not unique_paths:
        return

    deleted: List[str] = []
    failures: List[str] = []
    for path in unique_paths:
        try:
            deleted.append(self._delete_archived_session_path(path))
        except ValueError as exc:
            failures.append(str(exc) if str(exc) else self._t("history_delete_fail"))
        except OSError as exc:
            LOGGER.exception("Failed deleting archived session %s", path)
            detail = str(exc).strip()
            message = self._t("history_delete_fail")
            if detail:
                message = f"{message}: {detail}"
            failures.append(message)

    if deleted:
        facade.invalidate_session_discovery_cache()
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        self._drop_deleted_sessions_from_cache(deleted)

    if deleted and failures:
        self._set_status(self._t("history_delete_partial", deleted=len(deleted), failed=len(failures)), "warn")
    elif deleted:
        if len(deleted) == 1:
            self._set_status(self._t("history_delete_success"), "success")
        else:
            self._set_status(self._t("history_delete_many_success", count=len(deleted)), "success")
    elif failures:
        self._set_status(failures[0], "danger")
    else:
        self._set_status(self._t("history_delete_fail"), "danger")

    _request_refresh(self, "history:delete_sessions", False)
