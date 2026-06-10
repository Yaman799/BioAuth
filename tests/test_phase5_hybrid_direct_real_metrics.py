from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pytest

from hybrid_candidates.offline_runner import run_offline_candidate_replay
from hybrid_candidates.schema import CandidateResult
from metadata_core.constants import KB_HEADER, MS_HEADER
from security import compact_chunks, write_encrypted
from tests.encrypted_session_fixtures import isolate_encrypted_session_runtime


@pytest.fixture(autouse=True)
def _isolate_encrypted_replay_security(tmp_path: Path, monkeypatch: Any) -> None:
    isolate_encrypted_session_runtime(tmp_path, monkeypatch)


def _write_session(root: Path, name: str, label: str) -> Path:
    session = root / name
    session.mkdir(parents=True)
    (session / "metadata.json").write_text(
        json.dumps({"session_id": name, "label": label, "profile_id": "profile-a", "quality_score": 0.95}),
        encoding="utf-8",
    )
    keyboard_path = session / "keyboard_log.csv"
    mouse_path = session / "mouse_log.csv"
    write_encrypted(str(keyboard_path), [["a", "press", 1.0], ["a", "release", 1.1]], KB_HEADER)
    compact_chunks(str(keyboard_path), KB_HEADER)
    write_encrypted(str(mouse_path), [[2, 3, "move", 1.0], [4, 5, "move", 1.1]], MS_HEADER)
    compact_chunks(str(mouse_path), MS_HEADER)
    return session


def _scored_result(candidate_id: str, session: Any, _context: Mapping[str, Any]) -> dict[str, Any]:
    label = str(getattr(session, "label", ""))
    risk = 0.15 if label == "owner" else 0.85
    return CandidateResult(
        id=candidate_id,
        display_name="Isolation Forest",
        group="classic",
        available=True,
        trained_artifact_loaded=True,
        risk=risk,
        decision="intruder" if risk >= 0.5 else "genuine",
        can_vote=True,
        can_lock_alone=False,
        reason="test_phase5_real_metrics",
        latency_ms=2.0 if label == "owner" else 4.0,
        artifact_id="sha256:test-artifact",
        threshold_source="artifact_metadata",
        errors=(),
    ).to_dict()


def test_phase5_candidate_metrics_json_contains_real_owner_intruder_rates(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, "owner-a", "owner")
    _write_session(sessions_root, "owner-b", "owner")
    _write_session(sessions_root, "intruder-a", "intruder")
    _write_session(sessions_root, "intruder-b", "intruder")

    summary = run_offline_candidate_replay(
        selected_candidates=["classic_isolation_forest"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        adapter_overrides={"classic_isolation_forest": _scored_result},
    )

    metrics_path = Path(summary["report_paths"]["candidate_metrics"])
    assert metrics_path.exists()
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    candidate = payload["candidates"]["classic_isolation_forest"]
    assert candidate["evaluation_status"] == "evaluated"
    assert candidate["trained"] is True
    assert candidate["available"] is True
    assert candidate["metrics_available"] is True
    assert candidate["intruder_detection"] == 1.0
    assert candidate["owner_false_reject"] == 0.0
    assert candidate["owner_accept_rate"] == 1.0
    assert candidate["suspicious_rate"] == 0.5
    assert candidate["session_level_detection"] == 1.0
    assert candidate["window_level_detection"] is None
    assert candidate["window_level_reason"] == "per_window_decisions_not_available"
    assert candidate["average_latency_ms"] == 3.0
    assert candidate["p95_latency_ms"] is not None
    assert candidate["threshold_source_counts"] == {"artifact_metadata": 4}
    assert candidate["can_lock_alone"] is False
    assert candidate["can_influence_device"] is False
    assert summary["candidate_metrics_status_counts"]["evaluated"] >= 1


def test_phase5_invalid_split_is_reported_without_fake_metrics(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, "owner-overlap", "owner")
    _write_session(sessions_root, "intruder-clean", "intruder")

    class Artifact:
        def decision_function(self, X: np.ndarray) -> np.ndarray:
            return np.asarray([-0.8 for _ in range(X.shape[0])], dtype=float)

    def resolver(candidate_id: str, _session: Any, _context: Mapping[str, Any]) -> dict[str, Any]:
        assert candidate_id == "classic_isolation_forest"
        return {
            "artifact": Artifact(),
            "metadata": {
                "artifact_id": "sha256:split-test",
                "feature_names": ["keyboard_row_count", "mouse_row_count"],
                "training_session_ids": ["owner-overlap"],
            },
        }

    summary = run_offline_candidate_replay(
        selected_candidates=["classic_isolation_forest"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        artifact_resolver=resolver,
    )

    rows = [json.loads(line) for line in Path(summary["report_paths"]["candidate_results"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    overlap = [row for row in rows if row["session_id"] == "owner-overlap"][0]
    assert overlap["available"] is False
    assert overlap["reason"] == "invalid_split"
    assert overlap["result_status"] == "invalid_split"
    assert overlap["split_validation_status"] == "invalid_split"
    assert overlap["risk"] is None

    payload = json.loads(Path(summary["report_paths"]["candidate_metrics"]).read_text(encoding="utf-8"))
    candidate = payload["candidates"]["classic_isolation_forest"]
    assert candidate["evaluation_status"] == "invalid_split"
    assert candidate["metrics_available"] is False
    assert candidate["metrics_reason"] == "invalid_split"
    assert candidate["intruder_detection"] is None
    assert candidate["split_validation_statuses"]["invalid_split"] == 1


def test_phase5_missing_artifact_status_is_structured_and_non_crashing(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, "owner-a", "owner")
    _write_session(sessions_root, "intruder-a", "intruder")

    summary = run_offline_candidate_replay(
        selected_candidates=["classic_isolation_forest"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
    )

    payload = json.loads(Path(summary["report_paths"]["candidate_metrics"]).read_text(encoding="utf-8"))
    candidate = payload["candidates"]["classic_isolation_forest"]
    assert candidate["evaluation_status"] == "missing_artifact"
    assert candidate["metrics_available"] is False
    assert candidate["skip_failure_reasons"] == {"missing_trained_artifact": 2}
    assert candidate["can_lock"] is False
    assert candidate["trigger_face_confirmation"] is False
