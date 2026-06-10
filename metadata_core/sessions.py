"""Session discovery, metadata reading, and safe session-index cache seams."""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import paths

LOGGER = logging.getLogger(__name__)

_SESSION_METADATA_CACHE_LOCK = threading.Lock()
_SESSION_METADATA_CACHE: Dict[str, Tuple[Tuple[int, ...], Optional[Dict[str, Any]]]] = {}
_SESSION_DIRS_CACHE_TTL_SEC = 2.0
_SESSION_DIRS_CACHE_LOCK = threading.Lock()
_SESSION_DIRS_CACHE: Dict[str, Tuple[float, List[str]]] = {}

SESSION_INDEX_FILENAME = "sessions_index.json"
SESSION_INDEX_VERSION = 1
_SESSION_INDEX_LOCK = threading.Lock()
_SESSION_INDEX_MEMORY_CACHE: Dict[str, Tuple[Tuple[Any, ...], Dict[str, Any]]] = {}
_SESSION_INDEX_REBUILD_LOCKS: Dict[str, threading.Lock] = {}

_INDEX_NON_SENSITIVE_META_KEYS = (
    "session_id",
    "user_id",
    "session_kind",
    "final_decision",
    "archive_label",
    "bucket",
    "archive_group",
    "created_at",
    "started_at",
    "started_at_text",
    "duration_seconds",
    "keyboard_rows",
    "mouse_rows",
    "training_eligible",
    "stop_reason",
    "metadata_trusted",
    "metadata_integrity",
    "metadata_inferred",
    "metadata_diagnostic",
    "auto_enrollment",
    "collection_source",
    "time_of_day_bucket",
    "input_coverage",
)


def _session_bucket(path: str, meta: Optional[Dict[str, Any]] = None) -> str:
    data = meta if isinstance(meta, dict) else {}
    training_eligible = data.get("training_eligible")
    if training_eligible is True:
        return "accepted"
    bucket = str(data.get("bucket") or data.get("archive_group") or "").strip().lower()
    if bucket in {"accepted", "authorized", "legit"}:
        return "accepted"
    if bucket in {"rejected", "unauthorized", "intruder", "suspicious"}:
        return "rejected"
    decision = str(data.get("final_decision") or data.get("archive_label") or data.get("label") or "").strip().lower()
    if decision in {"legit", "legitimate", "accepted"}:
        return "accepted"
    if decision in {"intruder", "suspicious", "rejected", "unauthorized", "interrupted"}:
        return "rejected"
    sep = "\\"
    norm = path.replace("/", sep).lower()
    if f"{sep}accepted{sep}" in norm or f"{sep}authorized{sep}" in norm:
        return "accepted"
    if f"{sep}rejected{sep}" in norm or f"{sep}unauthorized{sep}" in norm:
        return "rejected"
    return "rejected"


def _format_timestamp(ts: Optional[float]) -> Optional[str]:
    if ts in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return str(ts)


def _looks_like_session_dir(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    try:
        entries = {name.lower() for name in os.listdir(path)}
    except OSError:
        return False
    if "metadata.json" in entries:
        return True
    return any(name in entries for name in {"keyboard_log.csv", "mouse_log.csv", "keyboard.csv", "mouse.csv"})


def _index_path(base_dir: Optional[str] = None) -> str:
    normalized = os.path.realpath(base_dir or paths.sessions_dir())
    return os.path.join(normalized, SESSION_INDEX_FILENAME)


def _stat_signature(path: str) -> Tuple[int, int]:
    try:
        stat = os.stat(path)
        return (int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))), int(stat.st_size))
    except OSError:
        return (0, 0)


def _metadata_cache_key(path: str) -> Optional[Tuple[int, int, int, int, int, int]]:
    meta_path = os.path.join(path, "metadata.json")
    hash_path = os.path.join(path, "metadata.hash")
    try:
        if not os.path.exists(meta_path):
            dir_stat = os.stat(path)
            return (
                int(getattr(dir_stat, "st_mtime_ns", int(dir_stat.st_mtime * 1_000_000_000))),
                int(dir_stat.st_size),
                0,
                0,
                0,
                0,
            )
        meta_sig = _stat_signature(meta_path)
        hash_sig = _stat_signature(hash_path)
        return meta_sig + hash_sig
    except OSError:
        return None


def _session_signature(path: str) -> Dict[str, int]:
    meta_path = os.path.join(path, "metadata.json")
    hash_path = os.path.join(path, "metadata.hash")
    dir_mtime, dir_size = _stat_signature(path)
    meta_mtime, meta_size = _stat_signature(meta_path)
    hash_mtime, hash_size = _stat_signature(hash_path)
    return {
        "dir_mtime_ns": int(dir_mtime),
        "dir_size": int(dir_size),
        "metadata_mtime_ns": int(meta_mtime),
        "metadata_size": int(meta_size),
        "metadata_hash_mtime_ns": int(hash_mtime),
        "metadata_hash_size": int(hash_size),
    }


def _parent_signature(base_dir: str) -> List[List[Any]]:
    """Capture cheap parent-folder mtimes that reveal new/moved archived sessions."""
    normalized = os.path.realpath(base_dir)
    signatures: List[List[Any]] = []
    # Do not include the sessions root itself: writing sessions_index.json
    # legitimately updates that directory mtime and would invalidate every hit.
    candidates: List[str] = []
    try:
        first_level = [os.path.join(normalized, name) for name in os.listdir(normalized)]
    except OSError:
        first_level = []
    for child in first_level:
        if not os.path.isdir(child):
            continue
        candidates.append(child)
        # For known rejected/<reason> style folders, include the second-level bucket
        # parent mtime without descending into session directories.
        if _looks_like_session_dir(child):
            continue
        try:
            for grandchild_name in os.listdir(child):
                grandchild = os.path.join(child, grandchild_name)
                if os.path.isdir(grandchild) and not _looks_like_session_dir(grandchild):
                    candidates.append(grandchild)
        except OSError:
            continue
    seen = set()
    for candidate in candidates:
        resolved = os.path.realpath(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        mtime_ns, size = _stat_signature(resolved)
        signatures.append([resolved, int(mtime_ns), int(size)])
    signatures.sort(key=lambda item: item[0])
    return signatures


def _scan_session_dirs(base_dir: str) -> List[str]:
    normalized = os.path.realpath(base_dir)
    if not os.path.isdir(normalized):
        return []
    result: List[str] = []
    seen = set()
    for root, dirs, files in os.walk(normalized):
        if os.path.basename(root) == SESSION_INDEX_FILENAME:
            continue
        if _looks_like_session_dir(root):
            resolved = os.path.realpath(root)
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)
            dirs[:] = []
            continue
        # Avoid treating the index file as archival content.
        if SESSION_INDEX_FILENAME in files:
            pass
    result.sort(key=lambda candidate: os.path.getmtime(candidate))
    return list(result)


def invalidate_session_discovery_cache(base_dir: Optional[str] = None) -> None:
    normalized = os.path.realpath(str(base_dir or paths.sessions_dir())) if base_dir else None
    with _SESSION_DIRS_CACHE_LOCK:
        if normalized:
            _SESSION_DIRS_CACHE.pop(normalized, None)
        else:
            _SESSION_DIRS_CACHE.clear()
    with _SESSION_METADATA_CACHE_LOCK:
        if normalized:
            prefix = normalized + os.sep
            for key in list(_SESSION_METADATA_CACHE.keys()):
                if key == normalized or key.startswith(prefix):
                    _SESSION_METADATA_CACHE.pop(key, None)
        else:
            _SESSION_METADATA_CACHE.clear()
    with _SESSION_INDEX_LOCK:
        if normalized:
            _SESSION_INDEX_MEMORY_CACHE.pop(normalized, None)
        else:
            _SESSION_INDEX_MEMORY_CACHE.clear()


def _infer_session_metadata_from_path(path: str) -> Optional[Dict[str, Any]]:
    if not _looks_like_session_dir(path):
        return None
    folder = os.path.basename(path)
    parts = folder.split("_")
    session_id = parts[-1] if parts else folder
    guessed_user = ""
    guessed_kind = "unknown"
    guessed_decision = "unknown"
    if len(parts) >= 4:
        guessed_user = parts[0]
        guessed_kind = parts[1] or "unknown"
        guessed_decision = parts[2] or "unknown"
    elif len(parts) >= 2:
        guessed_decision = parts[0] or "unknown"
    try:
        created_ts = os.path.getmtime(path)
    except OSError:
        created_ts = None
    return {
        "session_id": session_id or folder,
        "user_id": guessed_user,
        "session_kind": guessed_kind,
        "archive_label": guessed_decision,
        "final_decision": guessed_decision,
        "archive_group": _session_bucket(path, {}),
        "bucket": _session_bucket(path, {}),
        "created_at": _format_timestamp(created_ts) or "",
        "duration_seconds": 0,
        "keyboard_rows": 0,
        "mouse_rows": 0,
        "metadata_inferred": True,
    }


def _session_metadata_diagnostic(integrity: str) -> str:
    if integrity == "verified":
        return ""
    if integrity == "missing":
        return "Session metadata integrity sidecar is missing. Sensitive flows will ignore this metadata and fall back to path-derived values only."
    if integrity == "integrity_failed":
        return "Session metadata integrity check failed. Sensitive flows will ignore this metadata and fall back to path-derived values only."
    if integrity == "invalid":
        return "Session metadata content is invalid. Sensitive flows will ignore this metadata and fall back to path-derived values only."
    return "Session metadata is unavailable. Sensitive flows will ignore this metadata and fall back to path-derived values only."


def _finalize_session_metadata(path: str, meta: Optional[Dict[str, Any]], *, trusted: bool, integrity: str, inferred: bool) -> Optional[Dict[str, Any]]:
    if not isinstance(meta, dict):
        return None
    data = dict(meta)
    data["metadata_trusted"] = bool(trusted)
    data["metadata_integrity"] = integrity
    data["metadata_inferred"] = bool(inferred)
    data["metadata_diagnostic"] = _session_metadata_diagnostic(integrity)
    return data


def read_session_metadata(path: str) -> Optional[Dict[str, Any]]:
    resolved = os.path.abspath(str(path or "").strip())
    if not resolved:
        return None
    cache_key = _metadata_cache_key(resolved)
    if cache_key is not None:
        with _SESSION_METADATA_CACHE_LOCK:
            cached = _SESSION_METADATA_CACHE.get(resolved)
        if cached and cached[0] == cache_key:
            value = cached[1]
            return copy.deepcopy(value) if isinstance(value, dict) else value
    data: Optional[Dict[str, Any]] = None
    meta_path = os.path.join(resolved, "metadata.json")
    inferred_meta = _infer_session_metadata_from_path(resolved)
    if os.path.exists(meta_path):
        hash_path = os.path.join(resolved, "metadata.hash")
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                if not os.path.exists(hash_path):
                    data = _finalize_session_metadata(resolved, inferred_meta, trusted=False, integrity="missing", inferred=True)
                else:
                    from security import verify_metadata_hash

                    if verify_metadata_hash(meta_path):
                        data = _finalize_session_metadata(resolved, loaded, trusted=True, integrity="verified", inferred=False)
                    else:
                        data = _finalize_session_metadata(resolved, inferred_meta, trusted=False, integrity="integrity_failed", inferred=True)
            else:
                data = _finalize_session_metadata(resolved, inferred_meta, trusted=False, integrity="invalid", inferred=True)
        except (OSError, json.JSONDecodeError, ValueError, ImportError) as exc:
            LOGGER.warning("Session metadata could not be trusted for %s; using inferred metadata.", os.path.basename(resolved), exc_info=True)
            data = _finalize_session_metadata(resolved, inferred_meta, trusted=False, integrity="invalid", inferred=True)
    if data is None:
        integrity = "missing" if os.path.exists(meta_path) else "inferred_only"
        data = _finalize_session_metadata(resolved, inferred_meta, trusted=False, integrity=integrity, inferred=True)
    if cache_key is not None:
        with _SESSION_METADATA_CACHE_LOCK:
            _SESSION_METADATA_CACHE[resolved] = (cache_key, copy.deepcopy(data) if isinstance(data, dict) else data)
    return copy.deepcopy(data) if isinstance(data, dict) else data


def _safe_index_scalar(value: Any, default: Any = "") -> Any:
    if value is None:
        return default
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return default
        return float(value)
    if isinstance(value, (dict, list, tuple, set)):
        return default
    text = str(value)
    if len(text) > 500:
        text = text[:500]
    return text


def _int_index_value(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _float_index_value(value: Any) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if result != result or result in (float("inf"), float("-inf")):
        return 0.0
    return result


def _bool_index_value(value: Any) -> bool:
    return bool(value)


def _sanitize_index_entry(entry: Any) -> Optional[Dict[str, Any]]:
    """Return a scalar-only session-index entry safe for hot-path shallow copies."""
    if not isinstance(entry, dict):
        return None
    raw_path = str(entry.get("path") or "").strip()
    if not raw_path:
        return None
    return {
        "path": os.path.realpath(raw_path),
        "session_id": _safe_index_scalar(entry.get("session_id") or os.path.basename(raw_path)),
        "user_id": _safe_index_scalar(entry.get("user_id") or entry.get("safe_user") or ""),
        "safe_user": _safe_index_scalar(entry.get("safe_user") or entry.get("user_id") or ""),
        "created_at": _safe_index_scalar(entry.get("created_at") or ""),
        "mtime": _float_index_value(entry.get("mtime")),
        "session_kind": _safe_index_scalar(entry.get("session_kind") or "unknown"),
        "decision": _safe_index_scalar(entry.get("decision") or "unknown"),
        "bucket": _safe_index_scalar(entry.get("bucket") or "unknown"),
        "duration_seconds": _int_index_value(entry.get("duration_seconds")),
        "keyboard_rows": _int_index_value(entry.get("keyboard_rows")),
        "mouse_rows": _int_index_value(entry.get("mouse_rows")),
        "training_eligible": _bool_index_value(entry.get("training_eligible")),
        "metadata_trusted": _bool_index_value(entry.get("metadata_trusted")),
        "metadata_integrity": _safe_index_scalar(entry.get("metadata_integrity") or "unknown"),
        "metadata_inferred": _bool_index_value(entry.get("metadata_inferred")),
        "metadata_diagnostic": _safe_index_scalar(entry.get("metadata_diagnostic") or ""),
        "auto_enrollment": _bool_index_value(entry.get("auto_enrollment")),
        "collection_source": _safe_index_scalar(entry.get("collection_source") or ""),
        "time_of_day_bucket": _safe_index_scalar(entry.get("time_of_day_bucket") or ""),
        "input_coverage": _safe_index_scalar(entry.get("input_coverage") or ""),
        "index_schema_version": SESSION_INDEX_VERSION,
        "dir_mtime_ns": _int_index_value(entry.get("dir_mtime_ns")),
        "dir_size": _int_index_value(entry.get("dir_size")),
        "metadata_mtime_ns": _int_index_value(entry.get("metadata_mtime_ns")),
        "metadata_size": _int_index_value(entry.get("metadata_size")),
        "metadata_hash_mtime_ns": _int_index_value(entry.get("metadata_hash_mtime_ns")),
        "metadata_hash_size": _int_index_value(entry.get("metadata_hash_size")),
    }


def _sanitize_index_payload(payload: Dict[str, Any], base_dir: str) -> Dict[str, Any]:
    normalized = os.path.realpath(base_dir)
    entries: List[Dict[str, Any]] = []
    for item in list(payload.get("entries") or []):
        sanitized = _sanitize_index_entry(item)
        if sanitized is not None:
            entries.append(sanitized)
    entries.sort(key=lambda item: (float(item.get("mtime") or 0.0), str(item.get("path") or "")))
    return {
        "version": SESSION_INDEX_VERSION,
        "kind": "bioauth_session_index",
        "base_dir": normalized,
        "built_at": _float_index_value(payload.get("built_at") or time.time()),
        "parent_signature": _parent_signature(normalized),
        "entries": entries,
    }


def _index_entry_from_metadata(path: str, meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(meta, dict):
        meta = _infer_session_metadata_from_path(path) or {}
    if not meta:
        return None
    resolved = os.path.realpath(path)
    safe_user = str(meta.get("user_id") or "").strip()
    # Keep the index layer independent from optional UI/auth helper packages.
    # This mirrors the project slug behavior closely enough for archived
    # session ownership while avoiding repeated imports in hot index builds.
    safe_user = safe_user.lower().replace(" ", "-") if safe_user else ""
    created_value = meta.get("created_at") or meta.get("started_at") or meta.get("started_at_text") or ""
    if not created_value:
        try:
            created_value = _format_timestamp(os.path.getmtime(resolved)) or ""
        except OSError:
            created_value = ""
    entry: Dict[str, Any] = {
        "path": resolved,
        "session_id": _safe_index_scalar(meta.get("session_id") or os.path.basename(resolved)),
        "user_id": _safe_index_scalar(safe_user),
        "safe_user": _safe_index_scalar(safe_user),
        "created_at": _safe_index_scalar(created_value),
        "mtime": float(os.path.getmtime(resolved)) if os.path.exists(resolved) else 0.0,
        "session_kind": _safe_index_scalar(meta.get("session_kind") or "unknown"),
        "decision": _safe_index_scalar(meta.get("final_decision") or meta.get("archive_label") or meta.get("label") or "unknown"),
        "bucket": _safe_index_scalar(_session_bucket(resolved, meta)),
        "duration_seconds": _int_index_value(meta.get("duration_seconds")),
        "keyboard_rows": _int_index_value(meta.get("keyboard_rows")),
        "mouse_rows": _int_index_value(meta.get("mouse_rows")),
        "training_eligible": bool(meta.get("training_eligible")),
        "metadata_trusted": bool(meta.get("metadata_trusted")),
        "metadata_integrity": _safe_index_scalar(meta.get("metadata_integrity") or "unknown"),
        "metadata_inferred": bool(meta.get("metadata_inferred")),
        "metadata_diagnostic": _safe_index_scalar(meta.get("metadata_diagnostic") or ""),
        "auto_enrollment": bool(meta.get("auto_enrollment")),
        "collection_source": _safe_index_scalar(meta.get("collection_source") or ""),
        "time_of_day_bucket": _safe_index_scalar(meta.get("time_of_day_bucket") or ""),
        "input_coverage": _safe_index_scalar(meta.get("input_coverage") or ""),
        "index_schema_version": SESSION_INDEX_VERSION,
    }
    entry.update(_session_signature(resolved))
    return _sanitize_index_entry(entry)


def _metadata_from_index_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    data = {
        "session_id": entry.get("session_id") or os.path.basename(str(entry.get("path") or "")),
        "user_id": entry.get("user_id") or entry.get("safe_user") or "",
        "session_kind": entry.get("session_kind") or "unknown",
        "final_decision": entry.get("decision") or "unknown",
        "archive_label": entry.get("decision") or "unknown",
        "bucket": entry.get("bucket") or "unknown",
        "archive_group": entry.get("bucket") or "unknown",
        "created_at": entry.get("created_at") or "",
        "duration_seconds": _int_index_value(entry.get("duration_seconds")),
        "keyboard_rows": _int_index_value(entry.get("keyboard_rows")),
        "mouse_rows": _int_index_value(entry.get("mouse_rows")),
        "training_eligible": bool(entry.get("training_eligible")),
        "metadata_trusted": bool(entry.get("metadata_trusted")),
        "metadata_integrity": entry.get("metadata_integrity") or "unknown",
        "metadata_inferred": bool(entry.get("metadata_inferred")),
        "metadata_diagnostic": entry.get("metadata_diagnostic") or "",
        "auto_enrollment": bool(entry.get("auto_enrollment")),
        "collection_source": entry.get("collection_source") or "",
        "time_of_day_bucket": entry.get("time_of_day_bucket") or "",
        "input_coverage": entry.get("input_coverage") or "",
    }
    return dict(data)


def _write_json_atomic(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def _index_cache_signature(index_path: str) -> Tuple[Any, ...]:
    mtime, size = _stat_signature(index_path)
    return (SESSION_INDEX_VERSION, int(mtime), int(size))


def _load_index_file(index_path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(index_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Session index file could not be loaded; rebuilding index.", exc_info=True)
        return None
    return payload if isinstance(payload, dict) else None


def _mirror_session_index_to_metadata_db(base_dir: str, payload: Dict[str, Any]) -> None:
    """Best-effort mirror of scalar session-index metadata into SQLite.

    The JSON session index remains the compatibility source of truth for callers.
    SQLite is a metadata-only performance/audit index; failures must not block
    dashboard refresh or corrupt session metadata files.
    """
    try:
        from metadata_core import metadata_db

        metadata_db.replace_session_index_entries(
            list(payload.get("entries") or []),
            base_dir=base_dir,
            parent_signature=payload.get("parent_signature") or [],
        )
    except Exception:
        LOGGER.warning("Metadata SQLite mirror update failed; continuing with JSON session index.", exc_info=True)


def _load_session_index_from_metadata_db(base_dir: str) -> Optional[Dict[str, Any]]:
    """Best-effort fallback when the JSON session index is absent/corrupt."""
    try:
        from metadata_core import metadata_db

        return metadata_db.load_session_index_payload_from_db(
            base_dir,
            expected_parent_signature=_parent_signature(base_dir),
        )
    except Exception:
        LOGGER.warning("Metadata SQLite session-index fallback failed; rebuilding from files.", exc_info=True)
        return None


def _entry_signature_matches(entry: Dict[str, Any]) -> bool:
    path = str(entry.get("path") or "")
    if not path or not os.path.isdir(path):
        return False
    current = _session_signature(path)
    for key, value in current.items():
        try:
            if int(entry.get(key, -1)) != int(value):
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    return True


def _index_payload_valid(payload: Dict[str, Any], base_dir: str) -> bool:
    if not isinstance(payload, dict):
        return False
    if int(payload.get("version", 0) or 0) != SESSION_INDEX_VERSION:
        return False
    if os.path.realpath(str(payload.get("base_dir") or "")) != os.path.realpath(base_dir):
        return False
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return False
    if list(payload.get("parent_signature") or []) != _parent_signature(base_dir):
        return False
    for item in entries:
        if not isinstance(item, dict):
            return False
        if not str(item.get("path") or ""):
            return False
        if int(item.get("index_schema_version", SESSION_INDEX_VERSION) or 0) != SESSION_INDEX_VERSION:
            return False
    return True


def rebuild_session_index(base_dir: Optional[str] = None, *, write: bool = True) -> Dict[str, Any]:
    normalized = os.path.realpath(base_dir or paths.sessions_dir())
    lock = _SESSION_INDEX_REBUILD_LOCKS.setdefault(normalized, threading.Lock())
    with lock:
        session_paths = _scan_session_dirs(normalized)
        entries: List[Dict[str, Any]] = []
        for session_path in session_paths:
            meta = read_session_metadata(session_path) or {}
            entry = _index_entry_from_metadata(session_path, meta)
            if entry is not None:
                entries.append(entry)
        entries.sort(key=lambda item: (float(item.get("mtime") or 0.0), str(item.get("path") or "")))
        payload = _sanitize_index_payload(
            {
                "version": SESSION_INDEX_VERSION,
                "kind": "bioauth_session_index",
                "base_dir": normalized,
                "built_at": time.time(),
                "parent_signature": _parent_signature(normalized),
                "entries": entries,
            },
            normalized,
        )
        index_path = _index_path(normalized)
        if write:
            _write_json_atomic(index_path, payload)
            _mirror_session_index_to_metadata_db(normalized, payload)
        with _SESSION_INDEX_LOCK:
            _SESSION_INDEX_MEMORY_CACHE[normalized] = (_index_cache_signature(index_path), copy.deepcopy(payload))
        with _SESSION_DIRS_CACHE_LOCK:
            _SESSION_DIRS_CACHE[normalized] = (time.time(), [str(entry.get("path")) for entry in entries if entry.get("path")])
        return copy.deepcopy(payload)


def load_session_index(base_dir: Optional[str] = None, *, force_rebuild: bool = False, timing_collector: Optional[Dict[str, Any]] = None, copy_result: bool = True) -> Dict[str, Any]:
    started = time.perf_counter()
    normalized = os.path.realpath(base_dir or paths.sessions_dir())
    index_path = _index_path(normalized)
    hit = False
    rebuilt = False
    payload: Optional[Dict[str, Any]] = None
    if not force_rebuild:
        sig = _index_cache_signature(index_path)
        with _SESSION_INDEX_LOCK:
            cached = _SESSION_INDEX_MEMORY_CACHE.get(normalized)
        if cached and cached[0] == sig:
            payload = cached[1]
            hit = True
        if payload is None and os.path.exists(index_path):
            candidate = _load_index_file(index_path)
            if candidate is not None and _index_payload_valid(candidate, normalized):
                payload = _sanitize_index_payload(candidate, normalized)
                # Persist scalar-only data so future hot-path shallow copies
                # cannot expose nested attacker-controlled state.
                _write_json_atomic(index_path, payload)
                hit = True
                with _SESSION_INDEX_LOCK:
                    _SESSION_INDEX_MEMORY_CACHE[normalized] = (_index_cache_signature(index_path), copy.deepcopy(payload))
    if payload is None:
        payload = _load_session_index_from_metadata_db(normalized)
        if payload is not None and _index_payload_valid(payload, normalized):
            payload = _sanitize_index_payload(payload, normalized)
            _write_json_atomic(index_path, payload)
            hit = True
            with _SESSION_INDEX_LOCK:
                _SESSION_INDEX_MEMORY_CACHE[normalized] = (_index_cache_signature(index_path), copy.deepcopy(payload))
    if payload is None:
        rebuilt = True
        payload = rebuild_session_index(normalized, write=True)
    if timing_collector is not None:
        elapsed = int(round((time.perf_counter() - started) * 1000))
        timing_collector["session_index_hit"] = bool(hit)
        timing_collector["session_index_rebuild"] = bool(rebuilt)
        timing_collector["session_index_count"] = len(list(payload.get("entries") or []))
        timing_collector["session_index_ms"] = elapsed
    return copy.deepcopy(payload) if copy_result else payload


def list_session_index_entries(base_dir: Optional[str] = None, *, force_rebuild: bool = False, timing_collector: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    # Hot dashboard refreshes only need per-entry shallow copies. Avoid a full
    # payload deepcopy on every indexed listing so large cached indexes stay
    # below the UI performance gate while keeping callers from mutating the
    # cached entry dictionaries directly.
    payload = load_session_index(base_dir, force_rebuild=force_rebuild, timing_collector=timing_collector, copy_result=False)
    return [dict(item) for item in list(payload.get("entries") or []) if isinstance(item, dict)]


def index_entry_to_metadata(entry: Dict[str, Any]) -> Dict[str, Any]:
    return _metadata_from_index_entry(dict(entry or {}))


def update_session_index_for_path(path: str, *, base_dir: Optional[str] = None, remove: bool = False) -> None:
    resolved = os.path.realpath(str(path or "").strip())
    if not resolved:
        return
    normalized = os.path.realpath(base_dir or paths.sessions_dir())
    index_path = _index_path(normalized)
    payload = load_session_index(normalized, force_rebuild=False) if os.path.exists(index_path) else rebuild_session_index(normalized, write=True)
    entries = [dict(item) for item in list(payload.get("entries") or []) if isinstance(item, dict)]
    entries = [
        item
        for item in entries
        if os.path.isdir(str(item.get("path") or ""))
        and os.path.realpath(str(item.get("path") or "")) != resolved
    ]
    if not remove and os.path.isdir(resolved):
        meta = read_session_metadata(resolved) or {}
        entry = _index_entry_from_metadata(resolved, meta)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda item: (float(item.get("mtime") or 0.0), str(item.get("path") or "")))
    payload = _sanitize_index_payload(
        {
            "version": SESSION_INDEX_VERSION,
            "kind": "bioauth_session_index",
            "base_dir": normalized,
            "built_at": time.time(),
            "parent_signature": _parent_signature(normalized),
            "entries": entries,
        },
        normalized,
    )
    _write_json_atomic(index_path, payload)
    _mirror_session_index_to_metadata_db(normalized, payload)
    invalidate_session_discovery_cache(normalized)
    with _SESSION_INDEX_LOCK:
        _SESSION_INDEX_MEMORY_CACHE[normalized] = (_index_cache_signature(index_path), copy.deepcopy(payload))


def remove_session_from_index(path: str, *, base_dir: Optional[str] = None) -> None:
    update_session_index_for_path(path, base_dir=base_dir, remove=True)


def list_session_dirs(base_dir: Optional[str] = None) -> List[str]:
    normalized = os.path.realpath(base_dir or paths.sessions_dir())
    if not os.path.isdir(normalized):
        invalidate_session_discovery_cache(normalized)
        return []
    now = time.time()
    with _SESSION_DIRS_CACHE_LOCK:
        cached = _SESSION_DIRS_CACHE.get(normalized)
        if cached and (now - float(cached[0])) < _SESSION_DIRS_CACHE_TTL_SEC:
            return list(cached[1])
    try:
        entries = list_session_index_entries(normalized)
        result = [str(entry.get("path")) for entry in entries if entry.get("path")]
    except Exception:
        LOGGER.warning("Session index lookup failed; falling back to direct session directory scan.", exc_info=True)
        result = _scan_session_dirs(normalized)
    result.sort(key=lambda candidate: os.path.getmtime(candidate) if os.path.exists(candidate) else 0.0)
    with _SESSION_DIRS_CACHE_LOCK:
        _SESSION_DIRS_CACHE[normalized] = (time.time(), list(result))
    return list(result)


__all__ = [
    "SESSION_INDEX_FILENAME",
    "SESSION_INDEX_VERSION",
    "index_entry_to_metadata",
    "invalidate_session_discovery_cache",
    "list_session_dirs",
    "list_session_index_entries",
    "load_session_index",
    "read_session_metadata",
    "rebuild_session_index",
    "remove_session_from_index",
    "update_session_index_for_path",
]
