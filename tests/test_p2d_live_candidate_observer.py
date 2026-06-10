from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from hybrid_candidates.live_observer import (
    LIVE_OBSERVER_SCHEMA_VERSION,
    REPORT_SOURCE_LIVE_CANDIDATE_OBSERVER,
    LiveCandidateObserver,
    default_observer_state,
    normalize_observer_state,
    stage_live_session_snapshot,
)
from hybrid_candidates.registry import list_candidates
from metadata_core.constants import KB_HEADER, MS_HEADER
from security import compact_chunks, write_encrypted


def _manifest(root: Path) -> dict[str, tuple[int, str]]:
    rows: dict[str, tuple[int, str]] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        data = path.read_bytes()
        rows[path.relative_to(root).as_posix()] = (len(data), hashlib.sha256(data).hexdigest())
    return rows


def _write_live_dir(root: Path, *, rows: int = 8) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    keyboard_rows = [["key_hash:test", "press" if idx % 2 == 0 else "release", 10.0 + idx * 0.1] for idx in range(rows)]
    mouse_rows = [[idx, idx + 1, "move", 10.0 + idx * 0.1] for idx in range(rows)]
    keyboard_path = root / "keyboard_log.csv"
    mouse_path = root / "mouse_log.csv"
    write_encrypted(str(keyboard_path), keyboard_rows, KB_HEADER)
    compact_chunks(str(keyboard_path), KB_HEADER)
    write_encrypted(str(mouse_path), mouse_rows, MS_HEADER)
    compact_chunks(str(mouse_path), MS_HEADER)
    return root


def _fake_evaluator(**kwargs: Any) -> dict[str, Any]:
    out = Path(kwargs["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    candidate_path = out / "candidate_results.jsonl"
    candidate_ids = [candidate.id for candidate in list_candidates() if candidate.offline_allowed]
    with candidate_path.open("w", encoding="utf-8") as handle:
        for idx, candidate_id in enumerate(candidate_ids):
            handle.write(
                json.dumps(
                    {
                        "candidate_id": candidate_id,
                        "available": idx == 0,
                        "trained_artifact_loaded": idx == 0,
                        "risk": 0.42 if idx == 0 else None,
                        "decision": "genuine" if idx == 0 else "unavailable",
                        "can_vote": idx == 0,
                        "can_lock_alone": False,
                        "can_influence_device": False,
                        "runtime_authoritative": False,
                        "trigger_face_confirmation": False,
                        "reason": "ok" if idx == 0 else "missing_trained_artifact",
                        "latency_ms": 1.5,
                        "metrics": {"auc": 0.8} if idx == 0 else {},
                    }
                )
                + "\n"
            )
    summary_path = out / "hybrid_direct_summary.md"
    summary_path.write_text("# fake observer report\n", encoding="utf-8")
    return {
        "status": "completed",
        "source": REPORT_SOURCE_LIVE_CANDIDATE_OBSERVER,
        "report_paths": {"candidate_results": str(candidate_path), "summary": str(summary_path)},
        "warnings": [],
        "reason_codes": ["live_observer_snapshot_report_written"],
        "report_only": True,
        "can_lock": False,
        "can_influence_device": False,
        "runtime_authoritative": False,
        "trigger_face_confirmation": False,
    }


def test_stage_live_session_snapshot_copies_without_modifying_original(tmp_path: Path) -> None:
    live_dir = _write_live_dir(tmp_path / "live")
    before = _manifest(live_dir)

    staged = stage_live_session_snapshot(
        live_dir,
        tmp_path / "observer",
        runtime_state={"session_id": "sess-1", "session_kind": "protected", "user_id": "alice"},
        snapshot_id="snapshot-1",
    )

    assert staged["ok"] is True
    assert staged["reason"] == "live_session_snapshot_staged"
    assert Path(staged["snapshot_session_dir"]).is_dir()
    assert Path(staged["snapshot_session_dir"]).resolve() != live_dir.resolve()
    assert _manifest(live_dir) == before
    metadata = json.loads(Path(staged["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["training_eligible"] is False
    assert metadata["diagnostics_only"] is True
    assert metadata["raw_text_stored"] is False
    assert metadata["can_influence_device"] is False
    metadata_text = json.dumps(metadata).lower()
    assert "supersecret" not in metadata_text
    assert "typed text" not in metadata_text


def test_live_candidate_observer_worker_lifecycle_updates_rows_and_report(tmp_path: Path) -> None:
    live_dir = _write_live_dir(tmp_path / "live")
    observed_states: list[dict[str, Any]] = []
    observer = LiveCandidateObserver(
        live_session_dir=live_dir,
        output_root=tmp_path / "reports",
        runtime_state_provider=lambda: {"session_id": "live-owner-1", "session_kind": "protected", "user_id": "alice"},
        state_callback=lambda payload: observed_states.append(dict(payload)),
        evaluator=_fake_evaluator,
        interval_seconds=0.05,
        max_snapshots=1,
    )

    assert observer.start() is True
    deadline = time.time() + 5
    while time.time() < deadline and observer.state().get("snapshot_count", 0) < 1:
        time.sleep(0.02)
    stopped = observer.stop(timeout=1.0, reason="test_stop")

    assert stopped["observer_running"] is False
    assert stopped["schema_version"] == LIVE_OBSERVER_SCHEMA_VERSION
    assert stopped["snapshot_count"] >= 1
    assert len(stopped["candidate_rows"]) == 24
    assert stopped["candidate_rows"][0]["candidate_id"]
    assert stopped["candidate_rows"][0]["available"] is True
    assert stopped["candidate_rows"][0]["can_vote"] is True
    assert stopped["can_lock"] is False
    assert stopped["can_influence_device"] is False
    assert stopped["trigger_face_confirmation"] is False
    assert stopped["runtime_authoritative"] is False
    assert Path(stopped["observer_report_path"]).is_file()
    assert observed_states


def test_live_candidate_observer_dependency_missing_snapshot_fails_closed(tmp_path: Path) -> None:
    state = LiveCandidateObserver(
        live_session_dir=tmp_path / "missing-live-dir",
        output_root=tmp_path / "reports",
        runtime_state_provider=lambda: {"session_id": "missing-live"},
        evaluator=_fake_evaluator,
        interval_seconds=0.05,
        max_snapshots=1,
    ).snapshot_once()

    assert state["observer_running"] is False
    assert state["latest_snapshot_status"] == "live_session_dir_missing"
    assert len(state["candidate_rows"]) == 24
    assert {row["reason"] for row in state["candidate_rows"]} == {"live_session_dir_missing"}
    assert all(row["can_lock_alone"] is False for row in state["candidate_rows"])
    assert state["can_lock"] is False
    assert state["trigger_face_confirmation"] is False


def test_default_and_normalized_observer_state_safety_flags() -> None:
    state = normalize_observer_state({"observer_running": True, "can_lock": True, "runtime_authoritative": True, "trigger_face_confirmation": True})
    assert state["observer_running"] is True
    assert state["report_only"] is True
    assert state["can_lock"] is False
    assert state["can_lock_alone"] is False
    assert state["can_influence_device"] is False
    assert state["runtime_authoritative"] is False
    assert state["trigger_face_confirmation"] is False
    assert default_observer_state()["source"] == REPORT_SOURCE_LIVE_CANDIDATE_OBSERVER


def test_bridge_and_qml_expose_backend_owned_live_observer_display_only() -> None:
    desktop = Path("desktop_app.py").read_text(encoding="utf-8")
    helpers = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    qml = Path("qml/pages/HybridDirectTestPage.qml").read_text(encoding="utf-8")

    assert "def liveCandidateObserverState" in desktop
    assert "session_runtime_helpers.live_candidate_observer_state" in desktop
    assert "def start_live_candidate_observer" in helpers
    assert "def stop_live_candidate_observer" in helpers
    assert "run_offline_candidate_replay" not in qml
    assert "backend.liveCandidateObserverState" in qml
    assert "objectName: \"hybridLiveCandidateObserverCard\"" in qml
    card = qml[qml.index('objectName: "hybridLiveCandidateObserverCard"'): qml.index('objectName: "hybridDirectLatestReportsCard"')]
    assert "protectedSessionsAvailable" not in card
    assert "production_ready" not in card
    assert "backend.start" not in card
    assert "backend.stop" not in card
