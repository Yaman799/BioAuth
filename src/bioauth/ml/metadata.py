"""Model/session metadata helpers and path resolution."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Tuple

import paths as _paths_module
from auth import mark_profile_state
if TYPE_CHECKING:
    from training_core.selection import build_training_selection
from metadata_core.constants import (
    ACTIVE_RUNTIME_POINTER_FILE,
    ACTIVE_WINDOW_SCALES,
    CANDIDATE_BUNDLE_DIRNAME,
    CLASSIFIER_FILE,
    CONTEXT_ROUTER_MIN_CONFIDENCE,
    CONTEXT_ROUTING_VERSION,
    FEATURE_SCHEMA_VERSION,
    FEATURE_WINDOW_STRATEGY,
    KB_HEADER,
    LIVE_SESSION_DIR,
    MAX_ENROLLMENT_TRAINING_SESSIONS,
    MAX_PREDICT_WINDOWS,
    MAX_REFERENCE_NEGATIVE_SESSIONS,
    MAX_TRAIN_WINDOWS_PER_SESSION,
    METADATA_FILE,
    MIN_CONTEXT_POSITIVE_SESSION_SUPPORT,
    MIN_CONTEXT_POSITIVE_WINDOW_SAMPLES,
    MIN_NEGATIVE_WINDOW_SAMPLES,
    MIN_POSITIVE_WINDOW_SAMPLES,
    MIN_REQUIRED_ENROLLMENT_SESSIONS,
    MIN_WINDOW_EVENTS,
    MODEL_FILE,
    MODELS_DIR,
    MODEL_LIFECYCLE_LOCK_STALE_SECONDS,
    MS_HEADER,
    PREDICT_WINDOW_STEP_SECONDS,
    PRODUCTION_BUNDLE_DIRNAME,
    RECOMMENDED_ENROLLMENT_SESSIONS,
    ROUTER_CONTEXTS,
    RUNTIME_POINTER_SCHEMA_VERSION,
    RUNTIME_SCHEMA_POLICY_VERSION,
    SESSIONS_DIR,
    SHADOW_BACKUP_DAYS,
    SHADOW_DISCARD_THRESHOLD,
    SHADOW_EVAL_SESSIONS,
    SHADOW_LOCK_STALE_SECONDS,
    SHADOW_MAX_SESSIONS,
    SHADOW_MIN_SESSIONS,
    SHADOW_PROMOTE_THRESHOLD,
    WINDOW_SECONDS,
    WINDOW_STEP_SECONDS,
)
from metadata_core.paths import (
    _active_runtime_pointer_path,
    _bundle_paths,
    _user_candidate_bundle_dir,
    _user_model_dir,
    _user_model_paths,
    _user_production_bundle_dir,
    _user_production_paths,
)
from metadata_core.runtime import (
    canonical_runtime_pointer_json,
    clear_runtime_model_cache,
    load_model_metadata_cached,
    resolve_active_runtime_paths,
    resolve_active_runtime_paths_with_validation,
    runtime_deep_contract_state,
    runtime_feature_schema_compatible,
    runtime_feature_schema_mismatch_reason,
    sign_runtime_pointer_payload,
    validate_runtime_bundle_for_activation,
    verify_runtime_pointer_payload,
    write_active_runtime_pointer,
)
from metadata_core.sessions import (
    index_entry_to_metadata,
    invalidate_session_discovery_cache,
    list_session_dirs,
    list_session_index_entries,
    load_session_index,
    read_session_metadata,
    rebuild_session_index,
    remove_session_from_index,
    update_session_index_for_path,
)
from metadata_core.helpers import (
    _append_jsonl,
    _format_timestamp,
    _now_timestamp,
    _parse_timestamp_value,
    _read_text_file,
    _unique_existing_paths,
)
from metadata_core.shadow import (
    _backup_model_dir,
    _shadow_lock_path,
    _shadow_model_dir,
    _shadow_model_paths,
    _shadow_state_defaults,
    _shadow_state_path,
)
from metadata_core.dashboard import (
    _build_training_snapshot,
    _collect_negative_sessions_for_user,
    _describe_training_block,
    _is_accepted_session,
    _session_bucket,
    _session_quality_ok,
    _session_sort_key,
    _training_session_view_defaults,
    _user_session_paths,
    _user_session_records,
)
from metadata_core.dashboard import build_fast_user_dashboard_snapshot as _build_fast_user_dashboard_snapshot_impl
from metadata_core.dashboard import build_user_dashboard_snapshot as _build_user_dashboard_snapshot_impl
from metadata_core.dashboard import summarize_user_sessions as _summarize_user_sessions_impl
from metadata_core.dashboard import user_profile_status as _user_profile_status_impl
from metadata_core.maintenance import delete_user_data_impl, reset_user_profile_impl

MODELS_DIR = _paths_module.models_dir()
SESSIONS_DIR = _paths_module.sessions_dir()
LIVE_SESSION_DIR = _paths_module.live_session_dir()
MODEL_FILE = os.path.join(MODELS_DIR, "model.pkl")
CLASSIFIER_FILE = os.path.join(MODELS_DIR, "classifier.pkl")
METADATA_FILE = os.path.join(MODELS_DIR, "metadata.json")


def models_dir() -> str:
    return _paths_module.models_dir()


def sessions_dir() -> str:
    return _paths_module.sessions_dir()


def live_session_dir() -> str:
    return _paths_module.live_session_dir()


SHADOW_LOGGER = logging.getLogger("bioauth.shadow")
_SHADOW_LOCKS_GUARD = threading.Lock()
_SHADOW_LOCK_COUNTS: Dict[Tuple[int, str], int] = {}

_MODEL_LIFECYCLE_LOCKS_GUARD = threading.Lock()
_MODEL_LIFECYCLE_LOCK_COUNTS: Dict[Tuple[int, str], int] = {}


def _user_model_lock_path(user_id: str) -> str:
    return os.path.join(_user_model_dir(user_id), ".model.lifecycle.lock")


def _pid_is_running(pid: Any) -> bool:
    """Return whether a PID exists; not sufficient alone for lock identity."""
    try:
        pid_value = int(pid or 0)
    except Exception:
        return False
    if pid_value <= 0:
        return False
    if pid_value == os.getpid():
        return True
    try:
        os.kill(pid_value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _process_created_at_for_pid(pid: Any) -> float:
    """Best-effort process birth timestamp used to guard against PID reuse."""
    try:
        pid_value = int(pid or 0)
    except Exception:
        return 0.0
    if pid_value <= 0:
        return 0.0
    try:
        import psutil  # type: ignore

        return float(psutil.Process(pid_value).create_time())
    except Exception:
        pass
    if os.name != "nt":
        try:
            with open(f"/proc/{pid_value}/stat", "r", encoding="utf-8") as handle:
                fields = handle.read().split()
            if len(fields) >= 22:
                start_ticks = float(fields[21])
                ticks_per_second = float(os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK")))
                boot_epoch = 0.0
                try:
                    with open("/proc/stat", "r", encoding="utf-8") as handle:
                        for line in handle:
                            if line.startswith("btime "):
                                boot_epoch = float(line.split()[1])
                                break
                except Exception:
                    boot_epoch = 0.0
                if boot_epoch > 0 and ticks_per_second > 0:
                    return boot_epoch + (start_ticks / ticks_per_second)
        except Exception:
            pass
        return 0.0
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$p=Get-CimInstance Win32_Process -Filter 'ProcessId = %d'; "
                    "if ($p) { "
                    "$dt=[Management.ManagementDateTimeConverter]::ToDateTime($p.CreationDate); "
                    "[Console]::Out.WriteLine(([DateTimeOffset]$dt).ToUnixTimeSeconds()) "
                    "}"
                ) % pid_value,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines = (completed.stdout or "").strip().splitlines()
        return float(lines[-1]) if lines else 0.0
    except Exception:
        return 0.0


def _current_process_created_at() -> float:
    value = _process_created_at_for_pid(os.getpid())
    return value if value > 0.0 else time.time()


def _timestamps_match(expected: float, actual: float, *, tolerance_sec: float = 2.0) -> bool:
    try:
        expected_f = float(expected or 0.0)
        actual_f = float(actual or 0.0)
    except Exception:
        return False
    if expected_f <= 0.0 or actual_f <= 0.0:
        return False
    return abs(expected_f - actual_f) <= max(0.1, float(tolerance_sec))


def _lock_expected_process_created_at(payload: Dict[str, Any]) -> float:
    payload = payload if isinstance(payload, dict) else {}
    for key in ("process_created_at", "process_create_time", "process_birth_time"):
        try:
            value = float(payload.get(key) or 0.0)
        except Exception:
            value = 0.0
        if value > 0.0:
            return value
    return 0.0


def _lock_pid_matches_owner(payload: Dict[str, Any]) -> bool:
    payload = payload if isinstance(payload, dict) else {}
    pid = payload.get("pid")
    if not _pid_is_running(pid):
        return False
    expected_created_at = _lock_expected_process_created_at(payload)
    if expected_created_at <= 0.0:
        return True
    actual_created_at = _process_created_at_for_pid(pid)
    if actual_created_at <= 0.0:
        return True
    return _timestamps_match(expected_created_at, actual_created_at)


def _read_lock_payload(lock_path: str) -> Dict[str, Any]:
    try:
        payload = json.loads(Path(lock_path).read_text(encoding="utf-8") or "{}")
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _model_lifecycle_lock_is_stale(lock_path: str) -> bool:
    payload = _read_lock_payload(lock_path)
    pid = payload.get("pid")
    created_at = payload.get("created_at")
    try:
        created_ts = float(created_at) if created_at not in (None, "") else None
    except Exception:
        created_ts = None
    if pid and not _lock_pid_matches_owner(payload):
        return True
    if created_ts is not None and (time.time() - created_ts) > MODEL_LIFECYCLE_LOCK_STALE_SECONDS and not _lock_pid_matches_owner(payload):
        return True
    if not payload:
        try:
            return (time.time() - os.path.getmtime(lock_path)) > MODEL_LIFECYCLE_LOCK_STALE_SECONDS
        except OSError:
            return True
    return False


def _remove_stale_model_lifecycle_lock(lock_path: str) -> bool:
    if not os.path.exists(lock_path) or not _model_lifecycle_lock_is_stale(lock_path):
        return False
    try:
        os.remove(lock_path)
        return True
    except OSError:
        return False


@contextmanager
def user_model_lifecycle_lock(user_id: str, timeout: float = 15.0):
    lock_path = _user_model_lock_path(user_id)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    key = (threading.get_ident(), os.path.abspath(lock_path))
    nested = False
    with _MODEL_LIFECYCLE_LOCKS_GUARD:
        count = _MODEL_LIFECYCLE_LOCK_COUNTS.get(key, 0)
        if count > 0:
            _MODEL_LIFECYCLE_LOCK_COUNTS[key] = count + 1
            nested = True
    if not nested:
        now = time.time()
        payload = {
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
            "created_at": now,
            "lock_created_at": now,
            "process_created_at": _current_process_created_at(),
            "lock_version": 2,
            "role": "model_lifecycle",
        }
        deadline = time.time() + max(0.5, float(timeout or 15.0))
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False))
                    handle.flush()
                    try:
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
                break
            except FileExistsError:
                if _remove_stale_model_lifecycle_lock(lock_path):
                    continue
                if time.time() >= deadline:
                    raise TimeoutError(f"Timed out waiting for model lifecycle lock: {lock_path}")
                time.sleep(0.1)
        with _MODEL_LIFECYCLE_LOCKS_GUARD:
            _MODEL_LIFECYCLE_LOCK_COUNTS[key] = 1
    try:
        yield
    finally:
        remove_file = False
        with _MODEL_LIFECYCLE_LOCKS_GUARD:
            remaining = _MODEL_LIFECYCLE_LOCK_COUNTS.get(key, 1) - 1
            if remaining <= 0:
                _MODEL_LIFECYCLE_LOCK_COUNTS.pop(key, None)
                remove_file = True
            else:
                _MODEL_LIFECYCLE_LOCK_COUNTS[key] = remaining
        if remove_file:
            try:
                os.remove(lock_path)
            except OSError:
                pass


def build_user_dashboard_snapshot(user_id: str, *, include_training_selection_details: bool = True, session_detail_limit: int | None = None, timing_collector: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return _build_user_dashboard_snapshot_impl(
        user_id,
        include_training_selection_details=include_training_selection_details,
        session_detail_limit=session_detail_limit,
        list_session_dirs_fn=list_session_dirs,
        read_session_metadata_fn=read_session_metadata,
        resolve_active_runtime_paths_fn=resolve_active_runtime_paths,
        validate_runtime_bundle_for_activation_fn=validate_runtime_bundle_for_activation,
        resolve_active_runtime_paths_with_validation_fn=resolve_active_runtime_paths_with_validation,
        load_model_metadata_fn=load_model_metadata_cached,
        active_runtime_pointer_path_fn=_active_runtime_pointer_path,
        user_model_paths_fn=_user_model_paths,
        user_model_dir_fn=_user_model_dir,
        timing_collector=timing_collector,
    )



def build_fast_user_dashboard_snapshot(user_id: str, *, session_detail_limit: int = 10, timing_collector: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return _build_fast_user_dashboard_snapshot_impl(
        user_id,
        session_detail_limit=session_detail_limit,
        list_session_dirs_fn=list_session_dirs,
        read_session_metadata_fn=read_session_metadata,
        resolve_active_runtime_paths_fn=resolve_active_runtime_paths,
        validate_runtime_bundle_for_activation_fn=validate_runtime_bundle_for_activation,
        resolve_active_runtime_paths_with_validation_fn=resolve_active_runtime_paths_with_validation,
        load_model_metadata_fn=load_model_metadata_cached,
        active_runtime_pointer_path_fn=_active_runtime_pointer_path,
        user_model_paths_fn=_user_model_paths,
        user_model_dir_fn=_user_model_dir,
        timing_collector=timing_collector,
    )


def summarize_user_sessions(user_id: str):
    return _summarize_user_sessions_impl(
        user_id,
        list_session_dirs_fn=list_session_dirs,
        read_session_metadata_fn=read_session_metadata,
        resolve_active_runtime_paths_fn=resolve_active_runtime_paths,
        validate_runtime_bundle_for_activation_fn=validate_runtime_bundle_for_activation,
        resolve_active_runtime_paths_with_validation_fn=resolve_active_runtime_paths_with_validation,
        load_model_metadata_fn=load_model_metadata_cached,
        active_runtime_pointer_path_fn=_active_runtime_pointer_path,
        user_model_paths_fn=_user_model_paths,
        user_model_dir_fn=_user_model_dir,
    )



def user_profile_status(user_id: str):
    return _user_profile_status_impl(
        user_id,
        list_session_dirs_fn=list_session_dirs,
        read_session_metadata_fn=read_session_metadata,
        resolve_active_runtime_paths_fn=resolve_active_runtime_paths,
        validate_runtime_bundle_for_activation_fn=validate_runtime_bundle_for_activation,
        resolve_active_runtime_paths_with_validation_fn=resolve_active_runtime_paths_with_validation,
        load_model_metadata_fn=load_model_metadata_cached,
        active_runtime_pointer_path_fn=_active_runtime_pointer_path,
        user_model_paths_fn=_user_model_paths,
        user_model_dir_fn=_user_model_dir,
    )



def reset_user_profile(user_id: str, delete_sessions: bool = False) -> Dict[str, Any]:
    return reset_user_profile_impl(
        user_id,
        delete_sessions=delete_sessions,
        lifecycle_lock_fn=user_model_lifecycle_lock,
        user_model_dir_fn=_user_model_dir,
        user_session_paths_fn=_user_session_paths,
        read_session_metadata_fn=read_session_metadata,
        invalidate_session_discovery_cache_fn=invalidate_session_discovery_cache,
        mark_profile_state_fn=mark_profile_state,
        shutil_rmtree_fn=shutil.rmtree,
    )



def delete_user_data(user_id: str) -> Dict[str, Any]:
    return delete_user_data_impl(
        user_id,
        lifecycle_lock_fn=user_model_lifecycle_lock,
        user_model_dir_fn=_user_model_dir,
        user_session_paths_fn=_user_session_paths,
        read_session_metadata_fn=read_session_metadata,
        invalidate_session_discovery_cache_fn=invalidate_session_discovery_cache,
        mark_profile_state_fn=mark_profile_state,
        shutil_rmtree_fn=shutil.rmtree,
    )


__all__ = [
    "ACTIVE_RUNTIME_POINTER_FILE",
    "ACTIVE_WINDOW_SCALES",
    "CANDIDATE_BUNDLE_DIRNAME",
    "CLASSIFIER_FILE",
    "CONTEXT_ROUTER_MIN_CONFIDENCE",
    "CONTEXT_ROUTING_VERSION",
    "FEATURE_SCHEMA_VERSION",
    "FEATURE_WINDOW_STRATEGY",
    "KB_HEADER",
    "LIVE_SESSION_DIR",
    "MAX_ENROLLMENT_TRAINING_SESSIONS",
    "MAX_PREDICT_WINDOWS",
    "MAX_REFERENCE_NEGATIVE_SESSIONS",
    "MAX_TRAIN_WINDOWS_PER_SESSION",
    "METADATA_FILE",
    "MIN_CONTEXT_POSITIVE_SESSION_SUPPORT",
    "MIN_CONTEXT_POSITIVE_WINDOW_SAMPLES",
    "MIN_NEGATIVE_WINDOW_SAMPLES",
    "MIN_POSITIVE_WINDOW_SAMPLES",
    "MIN_REQUIRED_ENROLLMENT_SESSIONS",
    "MIN_WINDOW_EVENTS",
    "MODEL_FILE",
    "MODELS_DIR",
    "MS_HEADER",
    "PREDICT_WINDOW_STEP_SECONDS",
    "PRODUCTION_BUNDLE_DIRNAME",
    "RECOMMENDED_ENROLLMENT_SESSIONS",
    "ROUTER_CONTEXTS",
    "RUNTIME_POINTER_SCHEMA_VERSION",
    "RUNTIME_SCHEMA_POLICY_VERSION",
    "SESSIONS_DIR",
    "SHADOW_BACKUP_DAYS",
    "SHADOW_DISCARD_THRESHOLD",
    "SHADOW_EVAL_SESSIONS",
    "SHADOW_LOCK_STALE_SECONDS",
    "SHADOW_MAX_SESSIONS",
    "SHADOW_MIN_SESSIONS",
    "SHADOW_PROMOTE_THRESHOLD",
    "WINDOW_SECONDS",
    "WINDOW_STEP_SECONDS",
    "build_user_dashboard_snapshot",
    "clear_runtime_model_cache",
    "canonical_runtime_pointer_json",
    "delete_user_data",
    "index_entry_to_metadata",
    "invalidate_session_discovery_cache",
    "list_session_dirs",
    "list_session_index_entries",
    "load_model_metadata_cached",
    "load_session_index",
    "read_session_metadata",
    "rebuild_session_index",
    "remove_session_from_index",
    "update_session_index_for_path",
    "reset_user_profile",
    "resolve_active_runtime_paths",
    "resolve_active_runtime_paths_with_validation",
    "runtime_deep_contract_state",
    "runtime_feature_schema_compatible",
    "runtime_feature_schema_mismatch_reason",
    "sign_runtime_pointer_payload",
    "summarize_user_sessions",
    "user_model_lifecycle_lock",
    "user_profile_status",
    "validate_runtime_bundle_for_activation",
    "verify_runtime_pointer_payload",
    "write_active_runtime_pointer",
]
