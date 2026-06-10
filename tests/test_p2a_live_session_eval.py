from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from hybrid_candidates.live_session_eval import (
    REPORT_SOURCE_LATEST_LIVE_SESSION,
    discover_latest_saved_live_session,
    evaluate_latest_live_session,
)
from hybrid_candidates.registry import list_candidates
from metadata_core.constants import KB_HEADER, MS_HEADER
from security import compact_chunks, write_encrypted


def _file_manifest(root: Path) -> dict[str, tuple[int, str]]:
    rows: dict[str, tuple[int, str]] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        data = path.read_bytes()
        rows[path.relative_to(root).as_posix()] = (len(data), hashlib.sha256(data).hexdigest())
    return rows


def _write_live_session(root: Path, name: str, *, label: str = "legit", metadata: bool = True, row_count: int = 6) -> Path:
    session = root / name
    session.mkdir(parents=True)
    if metadata:
        (session / "metadata.json").write_text(
            json.dumps(
                {
                    "session_id": name,
                    "archive_label": label,
                    "final_decision": label,
                    "bucket": "authorized" if label == "legit" else "rejected",
                    "profile_id": "profile-a",
                    "session_kind": "enrollment",
                    "created_at": "2026-05-11 19:00:00",
                    "training_eligible": label == "legit",
                    "keyboard_rows": row_count,
                    "mouse_rows": row_count,
                }
            ),
            encoding="utf-8",
        )
    keyboard_rows = [["a", "press" if idx % 2 == 0 else "release", 1.0 + idx * 0.1] for idx in range(row_count)]
    mouse_rows = [[idx, idx + 1, "move", 1.0 + idx * 0.1] for idx in range(row_count)]
    keyboard_path = session / "keyboard_log.csv"
    mouse_path = session / "mouse_log.csv"
    write_encrypted(str(keyboard_path), keyboard_rows, KB_HEADER)
    compact_chunks(str(keyboard_path), KB_HEADER)
    write_encrypted(str(mouse_path), mouse_rows, MS_HEADER)
    compact_chunks(str(mouse_path), MS_HEADER)
    return session


def _rows(path: str | Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_p2a_latest_session_discovery_selects_newest_without_writes(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    old = _write_live_session(sessions_root / "authorized", "old-session")
    new = _write_live_session(sessions_root / "authorized", "new-session")
    old_time = time.time() - 1000
    new_time = time.time()
    os.utime(old, (old_time, old_time))
    os.utime(new, (new_time, new_time))
    before = _file_manifest(sessions_root)

    discovery = discover_latest_saved_live_session(sessions_root)

    assert discovery["found"] is True
    assert discovery["session_id"] == "new-session"
    assert discovery["reason_code"] == "latest_session_found"
    assert discovery["report_only"] is True
    assert discovery["can_influence_device"] is False
    assert discovery["runtime_authoritative"] is False
    assert _file_manifest(sessions_root) == before


def test_p2a_live_eval_stages_copy_and_does_not_modify_original_session(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    source = _write_live_session(sessions_root / "authorized", "latest-owner")
    before_source = _file_manifest(source)

    summary = evaluate_latest_live_session(sessions_root=sessions_root, output_root=tmp_path / "reports")

    assert summary["status"] in {"completed", "completed_with_candidate_or_session_errors"}
    assert summary["source"] == REPORT_SOURCE_LATEST_LIVE_SESSION
    assert summary["staging"]["ok"] is True
    assert summary["staging"]["source_modified"] is False
    assert Path(summary["staged_session_dir"]).is_dir()
    assert Path(summary["staged_session_dir"]).resolve() != source.resolve()
    assert _file_manifest(source) == before_source
    assert Path(summary["report_paths"]["candidate_results"]).exists()
    assert Path(summary["report_paths"]["model_comparison"]).exists()
    assert Path(summary["report_paths"]["threshold_diagnostics"]).exists()
    assert Path(summary["report_paths"]["dataset_diagnostics"]).exists()
    assert Path(summary["report_paths"]["thresholds"]).exists()
    assert Path(summary["report_paths"]["summary"]).exists()


def test_p2a_single_live_session_report_contains_all_registered_candidates(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_live_session(sessions_root / "authorized", "latest-owner")

    summary = evaluate_latest_live_session(sessions_root=sessions_root, output_root=tmp_path / "reports")
    candidate_rows = _rows(summary["report_paths"]["candidate_results"])
    expected_ids = {candidate.id for candidate in list_candidates() if candidate.offline_allowed}

    assert summary["candidate_count"] == 24
    assert summary["candidate_result_rows"] == 24
    assert {str(row["candidate_id"]) for row in candidate_rows} == expected_ids
    assert all(row["source"] == REPORT_SOURCE_LATEST_LIVE_SESSION for row in candidate_rows)
    assert all(row["can_lock_alone"] is False for row in candidate_rows)
    assert all(row["can_influence_device"] is False for row in candidate_rows)
    assert all(row["runtime_authoritative"] is False for row in candidate_rows)
    assert all(row["trigger_face_confirmation"] is False for row in candidate_rows)
    assert "live_eval_report_written" in summary["reason_codes"]


def test_p2a_live_eval_missing_metadata_writes_all_unavailable_rows(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    source = _write_live_session(sessions_root / "authorized", "missing-meta", metadata=False)
    before = _file_manifest(source)

    summary = evaluate_latest_live_session(sessions_root=sessions_root, output_root=tmp_path / "reports")
    rows = _rows(summary["report_paths"]["candidate_results"])

    assert summary["status"] == "latest_session_metadata_missing"
    assert "latest_session_metadata_missing" in summary["reason_codes"]
    assert len(rows) == 24
    assert {row["reason"] for row in rows} == {"latest_session_metadata_missing"}
    assert all(row["available"] is False for row in rows)
    assert all(row["can_vote"] is False for row in rows)
    assert all(row["can_lock_alone"] is False for row in rows)
    assert _file_manifest(source) == before


def test_p2a_live_eval_no_session_still_writes_safe_report(tmp_path: Path) -> None:
    summary = evaluate_latest_live_session(sessions_root=tmp_path / "empty_sessions", output_root=tmp_path / "reports")
    rows = _rows(summary["report_paths"]["candidate_results"])

    assert summary["status"] == "latest_session_not_found"
    assert "latest_session_not_found" in summary["reason_codes"]
    assert len(rows) == 24
    assert {row["reason"] for row in rows} == {"latest_session_not_found"}
    assert summary["report_only"] is True
    assert summary["can_lock"] is False
    assert summary["can_influence_device"] is False
    assert summary["trigger_face_confirmation"] is False
    assert summary["runtime_authoritative"] is False


def test_p2a_qml_and_bridge_expose_display_only_latest_live_eval() -> None:
    qml = Path("qml/pages/HybridDirectTestPage.qml").read_text(encoding="utf-8")
    mixin = Path("bridge/session_mixin.py").read_text(encoding="utf-8")
    desktop = Path("desktop_app.py").read_text(encoding="utf-8")

    assert "objectName: \"hybridLiveSessionEvalButton\"" in qml
    assert "onClicked: backend.evaluateLatestHybridLiveSession()" in qml
    assert "backend.latestHybridLiveSessionEvalResult" in qml
    assert "@Slot(result=\"QVariantMap\")\n    def evaluateLatestHybridLiveSession" in mixin
    assert "latestHybridLiveSessionEvalResult" in desktop
    live_button = qml[qml.index('objectName: "hybridLiveSessionEvalButton"'): qml.index('objectName: "hybridDirectOpenLatestReportButton"')]
    assert "protectedSessionsAvailable" not in live_button
    assert "production_ready" not in live_button
    assert "backend.canRunHybridDirectTest" in live_button
