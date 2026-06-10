"""Profile cleanup and data deletion helpers."""

from __future__ import annotations

import shutil
from typing import Any, Callable, Dict, List

from utils.identity import slugify_username
from metadata_core.dashboard import _user_session_paths
from metadata_core.paths import _user_model_dir
from metadata_core.sessions import invalidate_session_discovery_cache, read_session_metadata, remove_session_from_index


def reset_user_profile_impl(
    user_id: str,
    *,
    delete_sessions: bool = False,
    lifecycle_lock_fn: Callable[..., Any],
    user_model_dir_fn: Callable[[str], str] = _user_model_dir,
    user_session_paths_fn: Callable[[str], List[str]] = _user_session_paths,
    read_session_metadata_fn: Callable[[str], Dict[str, Any]] = read_session_metadata,
    invalidate_session_discovery_cache_fn: Callable[[], None] = invalidate_session_discovery_cache,
    remove_session_from_index_fn: Callable[[str], Any] = remove_session_from_index,
    mark_profile_state_fn: Callable[[str, str], Any] | None = None,
    shutil_rmtree_fn=shutil.rmtree,
) -> Dict[str, Any]:
    safe = slugify_username(user_id)
    deleted_session_ids: List[str] = []
    with lifecycle_lock_fn(safe):
        shutil_rmtree_fn(user_model_dir_fn(safe), ignore_errors=True)
        if delete_sessions:
            for session_path in user_session_paths_fn(safe):
                meta = read_session_metadata_fn(session_path) or {}
                session_id = str(meta.get("session_id") or "").strip()
                if session_id:
                    deleted_session_ids.append(session_id)
                shutil_rmtree_fn(session_path, ignore_errors=True)
                try:
                    remove_session_from_index_fn(session_path)
                except Exception:
                    pass
            invalidate_session_discovery_cache_fn()
        if callable(mark_profile_state_fn):
            mark_profile_state_fn(safe, "collecting")
    if delete_sessions and deleted_session_ids:
        try:
            from evidence_capture import delete_evidence_for_session
            for session_id in deleted_session_ids:
                delete_evidence_for_session(session_id)
        except Exception:
            pass
    return {"ok": True, "message_key": "profile_reset_success", "message": "Profile reset.", "deleted_sessions": bool(delete_sessions)}


def delete_user_data_impl(
    user_id: str,
    *,
    lifecycle_lock_fn: Callable[..., Any],
    user_model_dir_fn: Callable[[str], str] = _user_model_dir,
    user_session_paths_fn: Callable[[str], List[str]] = _user_session_paths,
    read_session_metadata_fn: Callable[[str], Dict[str, Any]] = read_session_metadata,
    invalidate_session_discovery_cache_fn: Callable[[], None] = invalidate_session_discovery_cache,
    remove_session_from_index_fn: Callable[[str], Any] = remove_session_from_index,
    mark_profile_state_fn: Callable[[str, str], Any] | None = None,
    shutil_rmtree_fn=shutil.rmtree,
) -> Dict[str, Any]:
    safe = slugify_username(user_id)
    result = reset_user_profile_impl(
        safe,
        delete_sessions=True,
        lifecycle_lock_fn=lifecycle_lock_fn,
        user_model_dir_fn=user_model_dir_fn,
        user_session_paths_fn=user_session_paths_fn,
        read_session_metadata_fn=read_session_metadata_fn,
        invalidate_session_discovery_cache_fn=invalidate_session_discovery_cache_fn,
        remove_session_from_index_fn=remove_session_from_index_fn,
        mark_profile_state_fn=mark_profile_state_fn,
        shutil_rmtree_fn=shutil_rmtree_fn,
    )
    try:
        from evidence_capture import delete_evidence_for_user
        delete_evidence_for_user(safe)
    except Exception:
        pass
    try:
        from metadata_core.production_evidence_pipeline import delete_evidence_records_for_user
        delete_evidence_records_for_user(safe)
    except Exception:
        pass
    result["message"] = "User model, sessions, local incident evidence, and local shadow/production evidence records deleted."
    return result
