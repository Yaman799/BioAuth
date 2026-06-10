"""Privacy-safe local SQLite metadata mirror for BioAuth.

SQLite is a rebuildable metadata-only mirror used for dashboard/audit speed. It
is never the authority for session truth: encrypted/session JSON files remain the
source of truth. This module deliberately stores only allowlisted scalar fields,
relative session references, hashed user/base references, aggregate counters, and
summary status values. It must not store raw behavioral rows, templates,
embeddings, model blobs, secrets, absolute filesystem paths, raw user IDs, or raw
internal diagnostics/reason codes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional

import paths
from utils.identity import slugify_username

SCHEMA_VERSION = 2
DATABASE_KIND = "bioauth_metadata_index"
SESSION_INDEX_SCHEMA_VERSION = 1

# These terms are intentionally absent from CREATE TABLE statements. Aggregate
# counters such as keyboard_rows/mouse_rows are permitted; raw key text, pointer
# coordinates, secrets, templates, payload blobs, raw reason codes, and absolute
# path fields are not.
BANNED_SCHEMA_TERMS = (
    "password",
    "secret",
    "private_key",
    "passphrase",
    "face_template",
    "biometric_template",
    "template_blob",
    "embedding",
    "model_blob",
    "raw_key",
    "key_text",
    "typed_text",
    "keystroke",
    "mouse_x",
    "mouse_y",
    "mouse_dx",
    "mouse_dy",
    "raw_log",
    "payload_blob",
    "absolute_path",
    "user_id",
    "customer_id",
    "license",
    "reason_code",
    "diagnostic",
)

_KNOWN_TABLES = (
    "metadata_schema",
    "session_index_state",
    "session_index",
    "training_jobs",
    "model_readiness",
    "risk_events",
    "lock_events",
    "audit_events",
)

_TAG_RE = re.compile(r"[^a-z0-9_.:-]+")


def metadata_db_path() -> str:
    """Return the local metadata SQLite path under BioAuth app data."""
    resolver = getattr(paths, "metadata_db_file", None)
    if callable(resolver):
        return str(resolver())
    return os.path.join(paths.data_dir(), "metadata_index.sqlite3")


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    target = Path(str(db_path or metadata_db_path()))
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return "null"


def _json_loads(text: Any, default: Any) -> Any:
    try:
        if text in (None, ""):
            return default
        return json.loads(str(text))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _safe_text(value: Any, default: str = "", *, limit: int = 512) -> str:
    if value in (None, ""):
        return default
    text = str(value)
    return text[: max(0, int(limit))]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return int(default)
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def _safe_bool(value: Any) -> int:
    return 1 if bool(value) else 0


def _hash_ref(prefix: str, value: Any) -> str:
    text = _safe_text(value, "", limit=4096).strip()
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _base_ref(base_dir: str) -> str:
    return _hash_ref("base", os.path.realpath(base_dir))


def _user_ref(value: Any) -> str:
    slug = slugify_username(_safe_text(value, "", limit=256))
    return _hash_ref("user", slug or "unknown")


def _reason_ref(value: Any) -> str:
    text = _safe_text(value, "", limit=512).strip().lower()
    if not text:
        return ""
    # Store only a non-reversible reference so raw internal reason strings do not
    # become searchable SQLite content.
    return _hash_ref("reason", text)


def _safe_tag(value: Any, default: str = "") -> str:
    text = _safe_text(value, default, limit=128).strip().lower()
    if not text:
        return default
    text = _TAG_RE.sub("_", text).strip("_")
    return text[:128] or default


def _relative_session_path(path_value: Any, *, base_dir: str) -> Optional[str]:
    raw = _safe_text(path_value, "", limit=4096).strip()
    if not raw:
        return None
    base = os.path.realpath(base_dir)
    candidate = os.path.realpath(raw)
    try:
        if os.path.commonpath([base, candidate]) != base:
            return None
        rel = os.path.relpath(candidate, base)
    except (OSError, ValueError):
        return None
    if rel in {"", "."} or rel.startswith(".."):
        return None
    return rel.replace(os.sep, "/")


def _absolute_session_path(relative_path: str, *, base_dir: str) -> str:
    rel = str(relative_path or "").replace("\\", "/").lstrip("/")
    return os.path.realpath(os.path.join(os.path.realpath(base_dir), rel))


def _schema_sql() -> List[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS metadata_schema (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS session_index_state (
            base_ref TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            parent_signature_json TEXT NOT NULL,
            entry_count INTEGER NOT NULL DEFAULT 0,
            rebuilt_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS session_index (
            base_ref TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            session_id TEXT NOT NULL,
            user_ref TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT '',
            mtime REAL NOT NULL DEFAULT 0,
            session_kind TEXT NOT NULL DEFAULT 'unknown',
            decision TEXT NOT NULL DEFAULT 'unknown',
            bucket TEXT NOT NULL DEFAULT 'unknown',
            duration_seconds INTEGER NOT NULL DEFAULT 0,
            keyboard_rows INTEGER NOT NULL DEFAULT 0,
            mouse_rows INTEGER NOT NULL DEFAULT 0,
            training_eligible INTEGER NOT NULL DEFAULT 0,
            metadata_trusted INTEGER NOT NULL DEFAULT 0,
            metadata_integrity TEXT NOT NULL DEFAULT 'unknown',
            metadata_inferred INTEGER NOT NULL DEFAULT 0,
            auto_enrollment INTEGER NOT NULL DEFAULT 0,
            collection_source TEXT NOT NULL DEFAULT '',
            time_of_day_bucket TEXT NOT NULL DEFAULT '',
            input_coverage TEXT NOT NULL DEFAULT '',
            index_schema_version INTEGER NOT NULL DEFAULT 1,
            dir_mtime_ns INTEGER NOT NULL DEFAULT 0,
            dir_size INTEGER NOT NULL DEFAULT 0,
            metadata_mtime_ns INTEGER NOT NULL DEFAULT 0,
            metadata_size INTEGER NOT NULL DEFAULT 0,
            metadata_hash_mtime_ns INTEGER NOT NULL DEFAULT 0,
            metadata_hash_size INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (base_ref, relative_path)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_session_index_user_mtime ON session_index(base_ref, user_ref, mtime DESC)",
        "CREATE INDEX IF NOT EXISTS idx_session_index_status ON session_index(base_ref, bucket, decision)",
        """
        CREATE TABLE IF NOT EXISTS training_jobs (
            job_id TEXT PRIMARY KEY,
            user_ref TEXT NOT NULL,
            status TEXT NOT NULL,
            phase TEXT NOT NULL DEFAULT '',
            reason_ref TEXT NOT NULL DEFAULT '',
            source_ref TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS model_readiness (
            user_ref TEXT NOT NULL,
            bundle_ref TEXT NOT NULL,
            status TEXT NOT NULL,
            production_approved INTEGER NOT NULL DEFAULT 0,
            protected_sessions_available INTEGER NOT NULL DEFAULT 0,
            reason_ref TEXT NOT NULL DEFAULT '',
            source_ref TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_ref, bundle_ref)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS risk_events (
            event_id TEXT PRIMARY KEY,
            user_ref TEXT NOT NULL,
            session_ref TEXT NOT NULL DEFAULT '',
            severity TEXT NOT NULL DEFAULT '',
            reason_ref TEXT NOT NULL DEFAULT '',
            risk_score REAL NOT NULL DEFAULT 0,
            source_ref TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS lock_events (
            event_id TEXT PRIMARY KEY,
            user_ref TEXT NOT NULL,
            session_ref TEXT NOT NULL DEFAULT '',
            lock_state TEXT NOT NULL DEFAULT '',
            reason_ref TEXT NOT NULL DEFAULT '',
            source_ref TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            user_ref TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            reason_ref TEXT NOT NULL DEFAULT '',
            source_ref TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """,
    ]


def schema_statements() -> List[str]:
    """Return CREATE statements for static privacy scans/tests."""
    return list(_schema_sql())


def assert_schema_privacy() -> None:
    schema = "\n".join(_schema_sql()).lower()
    matches = [term for term in BANNED_SCHEMA_TERMS if term.lower() in schema]
    if matches:
        raise AssertionError(f"metadata DB schema contains banned sensitive terms: {matches}")


def _drop_known_tables(conn: sqlite3.Connection) -> None:
    for table in reversed(_KNOWN_TABLES):
        conn.execute(f"DROP TABLE IF EXISTS {table}")


def _schema_table_values(conn: sqlite3.Connection) -> Dict[str, str]:
    try:
        rows = conn.execute("SELECT key,value FROM metadata_schema").fetchall()
        return {str(row[0]): str(row[1]) for row in rows}
    except sqlite3.DatabaseError:
        return {}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.DatabaseError:
        return set()


def _schema_compatible(conn: sqlite3.Connection) -> bool:
    try:
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
    except sqlite3.DatabaseError:
        return False
    if user_version != SCHEMA_VERSION:
        return False
    values = _schema_table_values(conn)
    if values.get("kind") != DATABASE_KIND or values.get("schema_version") != str(SCHEMA_VERSION):
        return False
    session_cols = _table_columns(conn, "session_index")
    if not {"base_ref", "relative_path", "session_id", "user_ref"}.issubset(session_cols):
        return False
    if {"base_dir", "path", "safe_user", "metadata_diagnostic", "reason_code"} & session_cols:
        return False
    return True


def _delete_database_files(target: Path) -> None:
    for candidate in (target, Path(str(target) + "-wal"), Path(str(target) + "-shm")):
        try:
            if candidate.exists() or candidate.is_symlink():
                candidate.unlink()
        except OSError:
            # If Windows has a transient lock, the next sqlite open will fail and
            # callers will safely rebuild from JSON/session files instead.
            pass


def _initialize_schema(conn: sqlite3.Connection) -> None:
    for statement in _schema_sql():
        conn.execute(statement)
    now = _utc_now()
    conn.execute(
        "INSERT OR REPLACE INTO metadata_schema(key,value,updated_at) VALUES(?,?,?)",
        ("kind", DATABASE_KIND, now),
    )
    conn.execute(
        "INSERT OR REPLACE INTO metadata_schema(key,value,updated_at) VALUES(?,?,?)",
        ("schema_version", str(SCHEMA_VERSION), now),
    )
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def initialize_database(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Create, migrate, or recreate the rebuildable local metadata mirror.

    Incompatible v1/privacy-unsafe schemas and corrupt SQLite files are removed
    and recreated because this database is a mirror of JSON/session files, not an
    authority. Rebuild of data rows happens separately from source-of-truth files.
    """
    assert_schema_privacy()
    target = Path(str(db_path or metadata_db_path()))
    recreated = False
    try:
        with _connect(str(target)) as conn:
            if not _schema_compatible(conn):
                _drop_known_tables(conn)
                recreated = True
            _initialize_schema(conn)
    except sqlite3.DatabaseError:
        _delete_database_files(target)
        recreated = True
        with _connect(str(target)) as conn:
            _initialize_schema(conn)
    return {
        "ok": True,
        "path": str(target),
        "schema_version": SCHEMA_VERSION,
        "database_kind": DATABASE_KIND,
        "recreated": recreated,
        "source_of_truth": "json_session_files",
    }


def ensure_database_ready(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Public helper used by tests/tools to verify repairable DB readiness."""
    return initialize_database(db_path)


def _sanitize_session_entry(entry: Mapping[str, Any], *, base_dir: str) -> Optional[Dict[str, Any]]:
    relative_path = _relative_session_path(entry.get("path"), base_dir=base_dir)
    if not relative_path:
        return None
    session_ref_source = entry.get("session_id") or os.path.basename(relative_path)
    user_source = entry.get("safe_user") or entry.get("user") or entry.get("user_ref") or entry.get("user_id") or "unknown"
    return {
        "base_ref": _base_ref(base_dir),
        "relative_path": relative_path,
        "session_id": _safe_text(session_ref_source, limit=128),
        "user_ref": _user_ref(user_source),
        "created_at": _safe_text(entry.get("created_at"), limit=64),
        "mtime": _safe_float(entry.get("mtime")),
        "session_kind": _safe_tag(entry.get("session_kind") or "unknown", "unknown"),
        "decision": _safe_tag(entry.get("decision") or "unknown", "unknown"),
        "bucket": _safe_tag(entry.get("bucket") or "unknown", "unknown"),
        "duration_seconds": max(0, _safe_int(entry.get("duration_seconds"))),
        "keyboard_rows": max(0, _safe_int(entry.get("keyboard_rows"))),
        "mouse_rows": max(0, _safe_int(entry.get("mouse_rows"))),
        "training_eligible": _safe_bool(entry.get("training_eligible")),
        "metadata_trusted": _safe_bool(entry.get("metadata_trusted")),
        "metadata_integrity": _safe_tag(entry.get("metadata_integrity") or "unknown", "unknown"),
        "metadata_inferred": _safe_bool(entry.get("metadata_inferred")),
        "auto_enrollment": _safe_bool(entry.get("auto_enrollment")),
        "collection_source": _safe_tag(entry.get("collection_source"), ""),
        "time_of_day_bucket": _safe_tag(entry.get("time_of_day_bucket"), ""),
        "input_coverage": _safe_tag(entry.get("input_coverage"), ""),
        "index_schema_version": SESSION_INDEX_SCHEMA_VERSION,
        "dir_mtime_ns": _safe_int(entry.get("dir_mtime_ns")),
        "dir_size": _safe_int(entry.get("dir_size")),
        "metadata_mtime_ns": _safe_int(entry.get("metadata_mtime_ns")),
        "metadata_size": _safe_int(entry.get("metadata_size")),
        "metadata_hash_mtime_ns": _safe_int(entry.get("metadata_hash_mtime_ns")),
        "metadata_hash_size": _safe_int(entry.get("metadata_hash_size")),
        "updated_at": _utc_now(),
    }


def _row_to_session_entry(row: sqlite3.Row, *, base_dir: str) -> Dict[str, Any]:
    absolute_path = _absolute_session_path(str(row["relative_path"]), base_dir=base_dir)
    session_id = str(row["session_id"] or "")
    user_ref = str(row["user_ref"] or "")
    return {
        "path": absolute_path,
        "session_id": session_id,
        "user_id": user_ref,
        "safe_user": user_ref,
        "created_at": str(row["created_at"]),
        "mtime": float(row["mtime"] or 0.0),
        "session_kind": str(row["session_kind"]),
        "decision": str(row["decision"]),
        "bucket": str(row["bucket"]),
        "duration_seconds": int(row["duration_seconds"] or 0),
        "keyboard_rows": int(row["keyboard_rows"] or 0),
        "mouse_rows": int(row["mouse_rows"] or 0),
        "training_eligible": bool(row["training_eligible"]),
        "metadata_trusted": bool(row["metadata_trusted"]),
        "metadata_integrity": str(row["metadata_integrity"]),
        "metadata_inferred": bool(row["metadata_inferred"]),
        "metadata_diagnostic": "",
        "auto_enrollment": bool(row["auto_enrollment"]),
        "collection_source": str(row["collection_source"]),
        "time_of_day_bucket": str(row["time_of_day_bucket"]),
        "input_coverage": str(row["input_coverage"]),
        "index_schema_version": int(row["index_schema_version"] or SESSION_INDEX_SCHEMA_VERSION),
        "dir_mtime_ns": int(row["dir_mtime_ns"] or 0),
        "dir_size": int(row["dir_size"] or 0),
        "metadata_mtime_ns": int(row["metadata_mtime_ns"] or 0),
        "metadata_size": int(row["metadata_size"] or 0),
        "metadata_hash_mtime_ns": int(row["metadata_hash_mtime_ns"] or 0),
        "metadata_hash_size": int(row["metadata_hash_size"] or 0),
    }


def replace_session_index_entries(
    entries: Iterable[Mapping[str, Any]],
    *,
    base_dir: Optional[str] = None,
    parent_signature: Optional[Any] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Atomically replace metadata-only session index rows for a base dir."""
    normalized = os.path.realpath(base_dir or paths.sessions_dir())
    base = _base_ref(normalized)
    rows = [
        row
        for row in (_sanitize_session_entry(entry, base_dir=normalized) for entry in list(entries or []) if isinstance(entry, Mapping))
        if row is not None
    ]
    initialize_database(db_path)
    now = _utc_now()
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM session_index WHERE base_ref = ?", (base,))
        conn.executemany(
            """
            INSERT OR REPLACE INTO session_index(
                base_ref,relative_path,session_id,user_ref,created_at,mtime,session_kind,decision,bucket,
                duration_seconds,keyboard_rows,mouse_rows,training_eligible,metadata_trusted,metadata_integrity,
                metadata_inferred,auto_enrollment,collection_source,time_of_day_bucket,input_coverage,
                index_schema_version,dir_mtime_ns,dir_size,metadata_mtime_ns,metadata_size,metadata_hash_mtime_ns,
                metadata_hash_size,updated_at
            ) VALUES(
                :base_ref,:relative_path,:session_id,:user_ref,:created_at,:mtime,:session_kind,:decision,:bucket,
                :duration_seconds,:keyboard_rows,:mouse_rows,:training_eligible,:metadata_trusted,:metadata_integrity,
                :metadata_inferred,:auto_enrollment,:collection_source,:time_of_day_bucket,:input_coverage,
                :index_schema_version,:dir_mtime_ns,:dir_size,:metadata_mtime_ns,:metadata_size,:metadata_hash_mtime_ns,
                :metadata_hash_size,:updated_at
            )
            """,
            rows,
        )
        conn.execute(
            "INSERT OR REPLACE INTO session_index_state(base_ref,schema_version,parent_signature_json,entry_count,rebuilt_at) VALUES(?,?,?,?,?)",
            (base, SESSION_INDEX_SCHEMA_VERSION, _json_dumps(parent_signature or []), len(rows), now),
        )
    return {
        "ok": True,
        "path": str(db_path or metadata_db_path()),
        "base_ref": base,
        "entry_count": len(rows),
        "source_of_truth": "json_session_files",
    }


def list_session_index_entries_from_db(
    base_dir: Optional[str] = None,
    *,
    db_path: Optional[str] = None,
    safe_user: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Read metadata-only session index rows from SQLite."""
    normalized = os.path.realpath(base_dir or paths.sessions_dir())
    base = _base_ref(normalized)
    initialize_database(db_path)
    sql = "SELECT * FROM session_index WHERE base_ref = ?"
    params: List[Any] = [base]
    if safe_user:
        sql += " AND user_ref = ?"
        params.append(_user_ref(safe_user))
    sql += " ORDER BY mtime ASC, relative_path ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(0, int(limit)))
    with _connect(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_session_entry(row, base_dir=normalized) for row in rows]


def load_session_index_payload_from_db(
    base_dir: Optional[str] = None,
    *,
    expected_parent_signature: Optional[Any] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return a JSON-index-compatible payload when DB state matches the session tree."""
    normalized = os.path.realpath(base_dir or paths.sessions_dir())
    base = _base_ref(normalized)
    initialize_database(db_path)
    with _connect(db_path) as conn:
        state = conn.execute(
            "SELECT * FROM session_index_state WHERE base_ref = ? AND schema_version = ?",
            (base, SESSION_INDEX_SCHEMA_VERSION),
        ).fetchone()
        if state is None:
            return None
        stored_signature = _json_loads(state["parent_signature_json"], [])
        if expected_parent_signature is not None and stored_signature != expected_parent_signature:
            return None
        rows = conn.execute(
            "SELECT * FROM session_index WHERE base_ref = ? ORDER BY mtime ASC, relative_path ASC",
            (base,),
        ).fetchall()
    entries = [_row_to_session_entry(row, base_dir=normalized) for row in rows]
    if int(state["entry_count"] or 0) != len(entries):
        return None
    return {
        "version": SESSION_INDEX_SCHEMA_VERSION,
        "kind": "bioauth_session_index",
        "base_dir": normalized,
        "built_at": time.time(),
        "parent_signature": stored_signature,
        "entries": entries,
        "source": "sqlite_metadata_db",
        "source_of_truth": "json_session_files",
    }


def rebuild_from_files(base_dir: Optional[str] = None, *, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Rebuild the SQLite metadata index from existing session metadata files."""
    from metadata_core import sessions as session_index

    normalized = os.path.realpath(base_dir or paths.sessions_dir())
    payload = session_index.rebuild_session_index(normalized, write=True)
    return replace_session_index_entries(
        list(payload.get("entries") or []),
        base_dir=normalized,
        parent_signature=payload.get("parent_signature") or [],
        db_path=db_path,
    )


def _safe_source_ref(source_ref: Any) -> str:
    text = _safe_text(source_ref, "", limit=512).strip()
    if not text:
        return ""
    # Avoid storing filesystem paths or raw identifiers in free-form refs.
    if os.path.isabs(text) or "/" in text or "\\" in text:
        return _hash_ref("source", text)
    return _safe_tag(text, "")


def record_audit_event(
    event_type: str,
    *,
    user_ref: str = "",
    summary: str = "",
    reason_code: str = "",
    source_ref: str = "",
    event_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a bounded metadata-only audit event."""
    initialize_database(db_path)
    event_id = event_id or str(uuid.uuid4())
    created = _utc_now()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO audit_events(event_id,event_type,user_ref,summary,reason_ref,source_ref,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                _safe_text(event_id, limit=128),
                _safe_tag(event_type or "audit", "audit"),
                _user_ref(user_ref),
                _safe_text(summary, limit=512),
                _reason_ref(reason_code),
                _safe_source_ref(source_ref),
                created,
            ),
        )
    return {"ok": True, "event_id": event_id, "created_at": created}


def record_risk_event(
    *,
    user_ref: str,
    session_id: str = "",
    severity: str = "",
    reason_code: str = "",
    risk_score: float = 0.0,
    source_ref: str = "",
    event_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    initialize_database(db_path)
    event_id = event_id or str(uuid.uuid4())
    created = _utc_now()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO risk_events(event_id,user_ref,session_ref,severity,reason_ref,risk_score,source_ref,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                _safe_text(event_id, limit=128),
                _user_ref(user_ref),
                _hash_ref("session", session_id),
                _safe_tag(severity, ""),
                _reason_ref(reason_code),
                _safe_float(risk_score),
                _safe_source_ref(source_ref),
                created,
            ),
        )
    return {"ok": True, "event_id": event_id, "created_at": created}


def record_lock_event(
    *,
    user_ref: str,
    session_id: str = "",
    lock_state: str = "",
    reason_code: str = "",
    source_ref: str = "",
    event_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    initialize_database(db_path)
    event_id = event_id or str(uuid.uuid4())
    created = _utc_now()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO lock_events(event_id,user_ref,session_ref,lock_state,reason_ref,source_ref,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                _safe_text(event_id, limit=128),
                _user_ref(user_ref),
                _hash_ref("session", session_id),
                _safe_tag(lock_state, ""),
                _reason_ref(reason_code),
                _safe_source_ref(source_ref),
                created,
            ),
        )
    return {"ok": True, "event_id": event_id, "created_at": created}


def database_summary(db_path: Optional[str] = None) -> Dict[str, Any]:
    initialize_database(db_path)
    with _connect(db_path) as conn:
        tables = [
            "session_index",
            "training_jobs",
            "model_readiness",
            "risk_events",
            "lock_events",
            "audit_events",
        ]
        counts = {name: int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] or 0) for name in tables}
        version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
    return {
        "ok": True,
        "path": str(db_path or metadata_db_path()),
        "schema_version": version,
        "database_kind": DATABASE_KIND,
        "source_of_truth": "json_session_files",
        "counts": counts,
    }


def privacy_statement() -> Dict[str, Any]:
    """Return a machine-testable summary of what the DB may and may not hold."""
    return {
        "stores": [
            "session indexes as rebuildable mirror rows",
            "relative session paths only",
            "hashed user/base/session references",
            "session status and aggregate row counts",
            "training job status",
            "model readiness summaries",
            "risk/lock/audit event summaries",
        ],
        "does_not_store": [
            "raw keyboard or mouse event logs",
            "typed text or key names",
            "passwords, passphrases, secrets, private keys",
            "face templates or raw biometric templates",
            "model payloads, embeddings, or decrypted secure-storage payloads",
            "absolute filesystem paths",
            "raw user identifiers or customer identifiers",
            "raw internal diagnostics or raw reason codes",
        ],
        "schema_version": SCHEMA_VERSION,
        "session_index_schema_version": SESSION_INDEX_SCHEMA_VERSION,
        "database_kind": DATABASE_KIND,
        "authoritative_source": "json_session_files",
        "rebuildable": True,
    }


__all__ = [
    "BANNED_SCHEMA_TERMS",
    "DATABASE_KIND",
    "SCHEMA_VERSION",
    "SESSION_INDEX_SCHEMA_VERSION",
    "assert_schema_privacy",
    "database_summary",
    "ensure_database_ready",
    "initialize_database",
    "list_session_index_entries_from_db",
    "load_session_index_payload_from_db",
    "metadata_db_path",
    "privacy_statement",
    "rebuild_from_files",
    "record_audit_event",
    "record_lock_event",
    "record_risk_event",
    "replace_session_index_entries",
    "schema_statements",
]
