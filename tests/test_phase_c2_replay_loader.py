from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hybrid_candidates.replay_loader import (
    ReplaySession,
    discover_replay_sessions,
    filter_eligible_sessions,
    load_replay_session_metadata,
    summarize_replay_dataset,
)


def _write_session(
    root: Path,
    name: str,
    *,
    metadata: dict | None = None,
    keyboard: bool = True,
    mouse: bool = True,
    invalid_metadata: bool = False,
) -> Path:
    session_dir = root / name
    session_dir.mkdir(parents=True)
    if metadata is not None or invalid_metadata:
        if invalid_metadata:
            (session_dir / "metadata.json").write_text("{not-json", encoding="utf-8")
        else:
            payload = {"session_id": name, "created_at": f"2026-05-10T00:00:{len(name):02d}Z"}
            payload.update(metadata or {})
            (session_dir / "metadata.json").write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    if keyboard:
        (session_dir / "keyboard_log.csv").write_text("ts,key\n1,a\n", encoding="utf-8")
    if mouse:
        (session_dir / "mouse_log.csv").write_text("ts,x,y\n1,2,3\n", encoding="utf-8")
    return session_dir


def _hash_tree(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def test_discover_replay_sessions_separates_eligible_and_diagnostics_only(tmp_path: Path) -> None:
    _write_session(
        tmp_path,
        "owner_session",
        metadata={"label": "legit", "safe_user": "owner-profile", "training_quality_score": 0.91, "training_eligible": True},
    )
    _write_session(
        tmp_path,
        "intruder_session",
        metadata={"final_decision": "intruder", "safe_user": "owner-profile", "training_eligible": False},
    )
    _write_session(tmp_path, "unknown_session", metadata={"label": "needs_review"})

    sessions = discover_replay_sessions(tmp_path)
    by_id = {session.session_id: session for session in sessions}
    assert list(by_id) == ["owner_session", "unknown_session", "intruder_session"]
    assert by_id["owner_session"].label == "owner"
    assert by_id["intruder_session"].label == "intruder"
    assert by_id["unknown_session"].label == "unknown"

    eligible = filter_eligible_sessions(sessions)
    assert {session.session_id for session in eligible} == {"owner_session", "intruder_session"}
    assert all(session.eligible for session in eligible)
    assert by_id["unknown_session"].diagnostics_only is True
    assert "unknown_label_diagnostics_only" in by_id["unknown_session"].reasons

    summary = summarize_replay_dataset(sessions)
    assert summary["read_only"] is True
    assert summary["runtime_influence"] is False
    assert summary["training_performed"] is False
    assert summary["raw_behavioral_data_included"] is False
    assert summary["total_sessions"] == 3
    assert summary["eligible_sessions"] == 2
    assert summary["metric_sample_labels"] == {"owner": 1, "intruder": 1, "unknown": 0}


def test_missing_keyboard_mouse_and_metadata_are_diagnostic_not_crashing(tmp_path: Path) -> None:
    _write_session(tmp_path, "keyboard_only_owner", metadata={"archive_label": "legit"}, mouse=False)
    _write_session(tmp_path, "mouse_only_intruder", metadata={"archive_label": "intruder"}, keyboard=False)
    _write_session(tmp_path, "logs_without_metadata", metadata=None, keyboard=True, mouse=True)
    _write_session(tmp_path, "metadata_without_logs", metadata={"label": "legit"}, keyboard=False, mouse=False)
    _write_session(tmp_path, "invalid_metadata", metadata=None, keyboard=True, mouse=True, invalid_metadata=True)

    sessions = {session.session_id: session for session in discover_replay_sessions(tmp_path)}
    assert sessions["keyboard_only_owner"].eligible is True
    assert "mouse_log_missing" in sessions["keyboard_only_owner"].reasons
    assert sessions["mouse_only_intruder"].eligible is True
    assert "keyboard_log_missing" in sessions["mouse_only_intruder"].reasons

    assert sessions["logs_without_metadata"].eligible is False
    assert sessions["logs_without_metadata"].label == "unknown"
    assert "metadata_missing" in sessions["logs_without_metadata"].reasons
    assert "unknown_label_diagnostics_only" in sessions["logs_without_metadata"].reasons

    assert sessions["metadata_without_logs"].eligible is False
    assert "behavior_logs_missing" in sessions["metadata_without_logs"].reasons

    assert sessions["invalid_metadata"].eligible is False
    assert "metadata_invalid" in sessions["invalid_metadata"].reasons


def test_confirmed_intruder_is_never_owner_positive_training_data(tmp_path: Path) -> None:
    _write_session(
        tmp_path,
        "confirmed_intruder_feedback",
        metadata={
            "label": "legit",
            "feedback_label": "confirmed_intruder",
            "training_eligible": True,
            "safe_user": "owner-profile",
        },
    )

    session = discover_replay_sessions(tmp_path)[0]
    assert session.label == "intruder"
    assert session.eligible is True
    assert "confirmed_intruder_not_owner_training" in session.reasons
    assert "intruder_not_owner_training" in session.reasons
    assert filter_eligible_sessions([session])[0].label == "intruder"


def test_loader_does_not_write_into_session_directories(tmp_path: Path) -> None:
    session_dir = _write_session(tmp_path, "owner_session", metadata={"label": "legit", "user_id": "owner@example.com"})
    before_hashes = _hash_tree(tmp_path)
    before_dir_mtime = session_dir.stat().st_mtime_ns

    sessions = discover_replay_sessions(tmp_path)
    metadata = load_replay_session_metadata(session_dir)
    summary = summarize_replay_dataset(sessions)

    after_hashes = _hash_tree(tmp_path)
    after_dir_mtime = session_dir.stat().st_mtime_ns
    assert before_hashes == after_hashes
    assert before_dir_mtime == after_dir_mtime
    assert metadata["label"] == "legit"
    assert summary["eligible_sessions"] == 1
    assert sessions[0].user_id.startswith("profile_hash:")
    assert "owner@example.com" not in sessions[0].user_id


def test_replay_session_dataclass_forces_unknown_labels_to_diagnostics_only() -> None:
    session = ReplaySession(
        session_id="manual",
        user_id="profile",
        label="unreviewed",
        keyboard_log_path="/tmp/keyboard_log.csv",
        mouse_log_path=None,
        metadata_path=None,
        quality={},
        eligible=True,
        reasons=["manual"],
        created_at="2026-05-10T00:00:00Z",
    )
    assert session.label == "unknown"
    assert session.eligible is False
    assert session.diagnostics_only is True


def test_replay_loader_adds_no_runtime_influence_tokens() -> None:
    source = Path("hybrid_candidates/replay_loader.py").read_text(encoding="utf-8")
    forbidden_tokens = [
        "LockWorkStation",
        "lock_screen",
        "runHybridDirectTest",
        "approveProductionModelSwitch",
        "production_pointer",
        "subprocess",
        "train_model",
        "write_session_state",
        "atomic_write",
        "os.makedirs",
        "mkdir(",
        "unlink(",
        "rmtree",
        "remove(",
    ]
    for token in forbidden_tokens:
        assert token not in source
