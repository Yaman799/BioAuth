from __future__ import annotations

import json
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


def _entry(root: Path, idx: int = 1) -> dict:
    path = root / "authorized" / f"alice_enrollment_legit_s{idx:04d}"
    return {
        "path": str(path),
        "session_id": f"s{idx:04d}",
        "user_id": "alice@example.com",
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
        "metadata_diagnostic": "",
        "index_schema_version": 1,
        "dir_mtime_ns": 1,
        "dir_size": 0,
        "metadata_mtime_ns": 2,
        "metadata_size": 128,
        "metadata_hash_mtime_ns": 3,
        "metadata_hash_size": 64,
    }


def test_metadata_db_initializes_under_bioauth_local_data(monkeypatch, tmp_path):
    data, _models, _sessions = _patch_local_paths(monkeypatch, tmp_path)
    from metadata_core import metadata_db

    result = metadata_db.initialize_database()

    db_path = data / "metadata_index.sqlite3"
    assert result["ok"] is True
    assert Path(result["path"]) == db_path
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"session_index", "training_jobs", "model_readiness", "risk_events", "lock_events", "audit_events"}.issubset(tables)


def test_metadata_db_schema_is_metadata_only():
    from metadata_core import metadata_db

    metadata_db.assert_schema_privacy()
    schema = "\n".join(metadata_db.schema_statements()).lower()
    banned = [term for term in metadata_db.BANNED_SCHEMA_TERMS if term.lower() in schema]
    assert banned == []
    assert "keyboard_rows" in schema  # aggregate count, not raw keystrokes
    assert "mouse_rows" in schema  # aggregate count, not raw pointer data
    statement = metadata_db.privacy_statement()
    assert any("raw keyboard" in item for item in statement["does_not_store"])
    assert any("password" in item for item in statement["does_not_store"])


def test_session_index_entries_round_trip_through_sqlite(monkeypatch, tmp_path):
    _data, _models, sessions_root = _patch_local_paths(monkeypatch, tmp_path)
    from metadata_core import metadata_db

    entries = [_entry(sessions_root, 1), _entry(sessions_root, 2)]
    result = metadata_db.replace_session_index_entries(entries, base_dir=str(sessions_root), parent_signature=[["root", 1, 2]])
    rows = metadata_db.list_session_index_entries_from_db(str(sessions_root))

    assert result["entry_count"] == 2
    assert [row["session_id"] for row in rows] == ["s0001", "s0002"]
    assert rows[0]["keyboard_rows"] == 120
    assert rows[0]["mouse_rows"] == 80
    assert "password" not in json.dumps(rows).lower()
    assert "raw_key" not in json.dumps(rows).lower()


def test_sessions_json_index_can_fallback_to_sqlite(monkeypatch, tmp_path):
    _data, _models, sessions_root = _patch_local_paths(monkeypatch, tmp_path)
    from metadata_core import metadata_db, sessions

    parent_signature = sessions._parent_signature(str(sessions_root))
    metadata_db.replace_session_index_entries(
        [_entry(sessions_root, 1)],
        base_dir=str(sessions_root),
        parent_signature=parent_signature,
    )
    # No sessions_index.json exists yet; list_session_index_entries should safely
    # hydrate the JSON-compatible index from the metadata DB fallback.
    index_path = sessions_root / sessions.SESSION_INDEX_FILENAME
    assert not index_path.exists()

    timing: dict[str, object] = {}
    rows = sessions.list_session_index_entries(str(sessions_root), timing_collector=timing)

    assert len(rows) == 1
    assert rows[0]["session_id"] == "s0001"
    assert timing["session_index_hit"] is True
    assert timing["session_index_rebuild"] is False
    assert index_path.exists()


def test_corrupt_sqlite_fails_closed_and_json_index_rebuilds(monkeypatch, tmp_path):
    data, _models, sessions_root = _patch_local_paths(monkeypatch, tmp_path)
    from metadata_core import sessions

    (data / "metadata_index.sqlite3").write_bytes(b"not a sqlite database")
    timing: dict[str, object] = {}

    rows = sessions.list_session_index_entries(str(sessions_root), timing_collector=timing)

    assert rows == []
    assert timing["session_index_rebuild"] is True
    assert (sessions_root / sessions.SESSION_INDEX_FILENAME).exists()


def test_backup_strategy_includes_rebuildable_metadata_database(monkeypatch, tmp_path):
    data, _models, _sessions = _patch_local_paths(monkeypatch, tmp_path)
    from metadata_core import metadata_db
    import local_data_backup

    metadata_db.initialize_database()
    collected = {rel for rel, _path in local_data_backup._collect_backup_files()}
    summary = local_data_backup.backup_format_summary()

    assert "data/metadata_index.sqlite3" in collected
    assert "included_metadata_database" in summary
    assert "rebuildable" in summary["included_metadata_database"]
