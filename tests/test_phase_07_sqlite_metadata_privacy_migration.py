from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


def _patch_local_paths(monkeypatch, tmp_path: Path):
    import paths

    data = tmp_path / "data"
    models = tmp_path / "models"
    sessions = data / "sessions"
    data.mkdir(parents=True, exist_ok=True)
    models.mkdir(parents=True, exist_ok=True)
    sessions.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "data_dir", lambda: str(data))
    monkeypatch.setattr(paths, "models_dir", lambda: str(models))
    monkeypatch.setattr(paths, "sessions_dir", lambda: str(sessions))
    monkeypatch.setattr(paths, "metadata_db_file", lambda: str(data / "metadata_index.sqlite3"), raising=False)
    return data, models, sessions


def _entry(root: Path, idx: int = 1, *, user_id: str = "alice@example.com") -> dict:
    path = root / "authorized" / f"alice_enrollment_legit_s{idx:04d}"
    return {
        "path": str(path),
        "session_id": f"s{idx:04d}",
        "user_id": user_id,
        "safe_user": "alice_example_com",
        "created_at": f"2026-05-14 00:{idx:02d}:00",
        "mtime": 1778716800.0 + idx,
        "session_kind": "enrollment",
        "decision": "legit",
        "bucket": "accepted",
        "duration_seconds": 90,
        "keyboard_rows": 120,
        "mouse_rows": 80,
        "training_eligible": True,
        "metadata_trusted": True,
        "metadata_integrity": "verified",
        "metadata_inferred": False,
        "metadata_diagnostic": "C:/Users/Alice/AppData/Local/BioAuth/raw diagnostics should not persist",
        "raw_key": "SECRET_TYPED_PAYLOAD",
        "typed_text": "never store this typed phrase",
        "model_blob": "MODEL_BYTES_SHOULD_NOT_PERSIST",
        "password": "PASSWORD_SHOULD_NOT_PERSIST",
        "index_schema_version": 1,
        "dir_mtime_ns": 1,
        "dir_size": 0,
        "metadata_mtime_ns": 2,
        "metadata_size": 128,
        "metadata_hash_mtime_ns": 3,
        "metadata_hash_size": 64,
    }


def _sqlite_dump(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        return "\n".join(conn.iterdump()).lower()


def test_phase7_schema_v2_has_no_banned_privacy_columns():
    from metadata_core import metadata_db

    metadata_db.assert_schema_privacy()
    schema = "\n".join(metadata_db.schema_statements()).lower()
    for banned in metadata_db.BANNED_SCHEMA_TERMS:
        assert banned.lower() not in schema
    assert "relative_path" in schema
    assert "base_ref" in schema
    assert "reason_ref" in schema
    assert "base_dir" not in schema
    assert "reason_code" not in schema
    assert "metadata_diagnostic" not in schema


def test_phase7_sqlite_stores_relative_paths_and_hashed_user_refs(monkeypatch, tmp_path):
    data, _models, sessions_root = _patch_local_paths(monkeypatch, tmp_path)
    from metadata_core import metadata_db

    metadata_db.replace_session_index_entries([_entry(sessions_root, 1)], base_dir=str(sessions_root))
    db_path = data / "metadata_index.sqlite3"
    dump = _sqlite_dump(db_path)

    assert str(tmp_path).lower() not in dump
    assert "alice@example.com" not in dump
    assert "alice_example_com" not in dump
    assert "relative_path" in dump
    assert "authorized/alice_enrollment_legit_s0001" in dump
    assert "user_" in dump
    assert "base_" in dump


def test_phase7_unknown_raw_backend_fields_are_not_persisted(monkeypatch, tmp_path):
    data, _models, sessions_root = _patch_local_paths(monkeypatch, tmp_path)
    from metadata_core import metadata_db

    metadata_db.replace_session_index_entries([_entry(sessions_root, 1)], base_dir=str(sessions_root))
    dump = _sqlite_dump(data / "metadata_index.sqlite3")

    forbidden_values = [
        "secret_typed_payload",
        "never store this typed phrase",
        "model_bytes_should_not_persist",
        "password_should_not_persist",
        "raw diagnostics should not persist",
        "appdata/local/bioauth",
    ]
    for value in forbidden_values:
        assert value not in dump


def test_phase7_corrupt_database_is_recreated_as_rebuildable_mirror(monkeypatch, tmp_path):
    data, _models, _sessions_root = _patch_local_paths(monkeypatch, tmp_path)
    from metadata_core import metadata_db

    db_path = data / "metadata_index.sqlite3"
    db_path.write_bytes(b"not a sqlite database")

    result = metadata_db.initialize_database()

    assert result["ok"] is True
    assert result["recreated"] is True
    with sqlite3.connect(db_path) as conn:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == metadata_db.SCHEMA_VERSION
        columns = {row[1] for row in conn.execute("PRAGMA table_info(session_index)").fetchall()}
    assert {"base_ref", "relative_path", "user_ref"}.issubset(columns)


def test_phase7_incompatible_v1_schema_is_migrated_without_privacy_unsafe_columns(monkeypatch, tmp_path):
    data, _models, _sessions_root = _patch_local_paths(monkeypatch, tmp_path)
    from metadata_core import metadata_db

    db_path = data / "metadata_index.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 1")
        conn.execute("CREATE TABLE metadata_schema(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
        conn.execute("INSERT INTO metadata_schema VALUES('kind','bioauth_metadata_index','2026-05-16T00:00:00Z')")
        conn.execute("INSERT INTO metadata_schema VALUES('schema_version','1','2026-05-16T00:00:00Z')")
        conn.execute("CREATE TABLE session_index(base_dir TEXT, path TEXT, safe_user TEXT, reason_code TEXT, metadata_diagnostic TEXT)")
        conn.execute("INSERT INTO session_index VALUES('/tmp/private','/tmp/private/alice','alice_example_com','raw_reason','raw diagnostic')")

    result = metadata_db.initialize_database()

    assert result["recreated"] is True
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(session_index)").fetchall()}
        row_count = conn.execute("SELECT COUNT(*) FROM session_index").fetchone()[0]
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    assert version == metadata_db.SCHEMA_VERSION
    assert {"base_dir", "path", "safe_user", "reason_code", "metadata_diagnostic"}.isdisjoint(columns)
    assert row_count == 0


def test_phase7_valid_json_index_wins_over_stale_sqlite_mirror(monkeypatch, tmp_path):
    _data, _models, sessions_root = _patch_local_paths(monkeypatch, tmp_path)
    from metadata_core import metadata_db, sessions

    json_entry = _entry(sessions_root, 1)
    stale_db_entry = _entry(sessions_root, 2)
    metadata_db.replace_session_index_entries(
        [stale_db_entry],
        base_dir=str(sessions_root),
        parent_signature=sessions._parent_signature(str(sessions_root)),
    )
    payload = {
        "version": sessions.SESSION_INDEX_VERSION,
        "kind": "bioauth_session_index",
        "base_dir": os.path.realpath(str(sessions_root)),
        "built_at": 1778716800.0,
        "parent_signature": sessions._parent_signature(str(sessions_root)),
        "entries": [json_entry],
    }
    index_path = sessions_root / sessions.SESSION_INDEX_FILENAME
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    timing: dict[str, object] = {}
    rows = sessions.list_session_index_entries(str(sessions_root), timing_collector=timing)

    assert [row["session_id"] for row in rows] == ["s0001"]
    assert all(row["session_id"] != "s0002" for row in rows)
    assert timing["session_index_hit"] is True
    assert timing["session_index_rebuild"] is False


def test_phase7_rebuild_from_files_uses_json_files_as_source_of_truth(monkeypatch, tmp_path):
    _data, _models, sessions_root = _patch_local_paths(monkeypatch, tmp_path)
    from metadata_core import metadata_db

    session_dir = sessions_root / "authorized" / "session0001"
    session_dir.mkdir(parents=True)
    (session_dir / "metadata.json").write_text(
        json.dumps(
            {
                "session_id": "s0001",
                "user_id": "alice@example.com",
                "session_kind": "enrollment",
                "final_decision": "legit",
                "archive_label": "legit",
                "bucket": "accepted",
                "duration_seconds": 90,
                "keyboard_rows": 12,
                "mouse_rows": 8,
                "training_eligible": True,
            }
        ),
        encoding="utf-8",
    )

    result = metadata_db.rebuild_from_files(str(sessions_root))
    rows = metadata_db.list_session_index_entries_from_db(str(sessions_root))

    assert result["ok"] is True
    assert result["source_of_truth"] == "json_session_files"
    assert len(rows) == 1
    assert rows[0]["path"].endswith("session0001")
    assert rows[0]["keyboard_rows"] >= 0
