from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from hybrid_candidates.adapters import CLASSIC_ADAPTER_IDS, evaluate_classic_candidate
from hybrid_candidates.artifact_resolver import build_candidate_bundle_artifact_resolver
from hybrid_candidates.offline_runner import run_offline_candidate_replay
from hybrid_candidates.registry import validate_candidate_result
from metadata_core.constants import KB_HEADER, MS_HEADER
from security import compact_chunks, write_encrypted
from training_core.candidate_artifact_builders import (
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    CLASSICAL_CANDIDATE_ARTIFACT_FILENAMES,
    CLASSICAL_CANDIDATE_IDS,
    MANIFEST_FILENAME,
    build_classical_candidate_artifacts,
)


P2B1_CLASSICAL_IDS = {
    "classic_lof",
    "classic_one_class_svm",
    "classic_gmm",
    "classic_scaled_manhattan",
    "classic_nn_mahalanobis",
}


def _training_matrix(sample_count: int = 18, feature_count: int = 5) -> tuple[np.ndarray, list[str]]:
    rng = np.random.default_rng(20260511)
    base = rng.normal(loc=0.0, scale=0.2, size=(sample_count, feature_count))
    trend = np.linspace(0.0, 0.3, sample_count, dtype=float).reshape(-1, 1)
    X = base + trend
    names = [f"f{idx}" for idx in range(feature_count)]
    return X.astype(float), names


def _metadata_for_bundle(bundle_dir: Path, build: dict[str, object], feature_names: list[str]) -> Path:
    path = bundle_dir / "metadata.json"
    path.write_text(
        json.dumps(
            {
                "feature_names": feature_names,
                "feature_schema_version": "test-feature-schema-v1",
                "candidate_artifact_manifest": build["manifest"],
                "candidate_artifacts": build["candidate_artifacts"],
                "artifacts": {"candidate_artifacts_manifest": build["manifest_path"]},
                "report_only": True,
                "can_lock_alone": False,
                "can_influence_device": False,
                "runtime_authoritative": False,
                "trigger_face_confirmation": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _candidate_rows(path: str | Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_session(root: Path, name: str, *, row_count: int = 600, label: str = "legit") -> Path:
    session = root / name
    session.mkdir(parents=True, exist_ok=True)
    (session / "metadata.json").write_text(
        json.dumps(
            {
                "session_id": name,
                "archive_label": label,
                "final_decision": label,
                "bucket": "authorized" if label == "legit" else "rejected",
                "training_eligible": label == "legit",
                "keyboard_rows": row_count,
                "mouse_rows": row_count,
                "created_at": "2026-05-11 20:00:00",
            }
        ),
        encoding="utf-8",
    )
    keyboard_rows = []
    mouse_rows = []
    for idx in range(row_count):
        timestamp = round(idx * 0.12, 3)
        keyboard_rows.append([chr(97 + (idx % 5)), "press" if idx % 2 == 0 else "release", timestamp])
        mouse_rows.append([idx % 200, (idx * 3) % 180, "move", timestamp])
    keyboard_path = session / "keyboard_log.csv"
    mouse_path = session / "mouse_log.csv"
    write_encrypted(str(keyboard_path), keyboard_rows, KB_HEADER)
    compact_chunks(str(keyboard_path), KB_HEADER)
    write_encrypted(str(mouse_path), mouse_rows, MS_HEADER)
    compact_chunks(str(mouse_path), MS_HEADER)
    return session


def test_p2b1_classical_candidate_builders_create_real_artifacts_when_data_is_sufficient(tmp_path: Path) -> None:
    X, feature_names = _training_matrix()
    build = build_classical_candidate_artifacts(
        model_dir=tmp_path,
        X_pos=X,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
    )

    entries = build["candidate_artifacts"]
    assert set(entries) == P2B1_CLASSICAL_IDS
    assert build["status_counts"]["trained"] == len(P2B1_CLASSICAL_IDS)
    assert (tmp_path / MANIFEST_FILENAME).is_file()
    for candidate_id, entry in entries.items():
        assert entry["status"] == "trained"
        assert entry["artifact_schema"] == CANDIDATE_ARTIFACT_SCHEMA_VERSION
        assert entry["feature_names"] == feature_names
        assert entry["training_sample_count"] == len(X)
        assert entry["reason"] == "ok"
        assert entry["can_lock_alone"] is False
        assert entry["can_influence_device"] is False
        assert entry["runtime_authoritative"] is False
        assert entry["trigger_face_confirmation"] is False
        assert entry["artifact_path"] == CLASSICAL_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]
        assert (tmp_path / str(entry["artifact_path"])).is_file()


def test_p2b1_insufficient_data_writes_skipped_manifest_entries_without_fake_artifacts(tmp_path: Path) -> None:
    X, feature_names = _training_matrix(sample_count=1)
    build = build_classical_candidate_artifacts(
        model_dir=tmp_path,
        X_pos=X,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
    )

    entries = build["candidate_artifacts"]
    assert set(entries) == P2B1_CLASSICAL_IDS
    assert build["status_counts"]["trained"] == 0
    assert build["status_counts"]["skipped"] == len(P2B1_CLASSICAL_IDS)
    for candidate_id, entry in entries.items():
        assert entry["status"] == "skipped"
        assert entry["reason"] == "insufficient_genuine_samples"
        assert entry["artifact_path"] is None
        assert not (tmp_path / CLASSICAL_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]).exists()
        assert entry["can_lock_alone"] is False


def test_p2b1_artifact_resolver_maps_new_classical_candidates_to_bundle_artifacts(tmp_path: Path) -> None:
    X, feature_names = _training_matrix()
    build = build_classical_candidate_artifacts(
        model_dir=tmp_path,
        X_pos=X,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
    )
    metadata_path = _metadata_for_bundle(tmp_path, build, feature_names)
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=tmp_path, metadata_path=metadata_path)

    for candidate_id in P2B1_CLASSICAL_IDS:
        spec = resolver(candidate_id, None, {})
        assert Path(spec["artifact_path"]).name == CLASSICAL_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]
        assert Path(spec["artifact_path"]).is_file()
        assert spec["metadata"]["artifact_builder_status"] == "trained"
        assert spec["metadata"]["artifact_builder_reason"] == "ok"
        assert spec["metadata"]["feature_names"] == feature_names
        assert spec["metadata"]["can_lock_alone"] is False
        result = evaluate_classic_candidate(candidate_id, {name: 0.1 for name in feature_names}, **spec)
        assert validate_candidate_result(result)["ok"] is True
        assert result["available"] is True
        assert result["reason"] != "missing_trained_artifact"
        assert result["trained_artifact_loaded"] is True
        assert result["can_lock_alone"] is False


def test_p2b1_resolver_preserves_skipped_reason_instead_of_fabricating_artifact(tmp_path: Path) -> None:
    X, feature_names = _training_matrix(sample_count=1)
    build = build_classical_candidate_artifacts(
        model_dir=tmp_path,
        X_pos=X,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
    )
    metadata_path = _metadata_for_bundle(tmp_path, build, feature_names)
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=tmp_path, metadata_path=metadata_path)

    spec = resolver("classic_lof", None, {})
    assert "artifact_path" not in spec
    result = evaluate_classic_candidate("classic_lof", {name: 0.1 for name in feature_names}, **spec)
    assert result["available"] is False
    assert result["reason"] == "insufficient_genuine_samples"
    assert result["reason"] != "missing_trained_artifact"
    assert result["can_lock_alone"] is False


def test_p2b1_hybrid_direct_run_uses_valid_classical_artifacts_without_missing_artifact(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root / "authorized", "owner-session", row_count=6)
    feature_names = [
        "keyboard_row_count",
        "mouse_row_count",
        "keyboard_file_size_bytes",
        "mouse_file_size_bytes",
        "window_feature_sample_count",
        "training_feature_extractor_used",
    ]
    X = np.asarray(
        [
            [6.0 + idx, 6.0 + idx, 1000.0 + idx * 5.0, 1100.0 + idx * 5.0, float(idx % 3), 0.0]
            for idx in range(12)
        ],
        dtype=float,
    )
    bundle_dir = tmp_path / "candidate_bundle"
    build = build_classical_candidate_artifacts(
        model_dir=bundle_dir,
        X_pos=X,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
    )
    metadata_path = _metadata_for_bundle(bundle_dir, build, feature_names)
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=bundle_dir, metadata_path=metadata_path)

    summary = run_offline_candidate_replay(
        selected_candidates=sorted(P2B1_CLASSICAL_IDS),
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        artifact_resolver=resolver,
        max_sessions=1,
    )
    rows = _candidate_rows(summary["report_paths"]["candidate_results"])
    by_id = {str(row["candidate_id"]): row for row in rows}

    assert set(by_id) == P2B1_CLASSICAL_IDS
    assert summary["training_performed"] is False
    assert summary["can_lock_alone"] is False
    for candidate_id, row in by_id.items():
        assert row["reason"] != "missing_trained_artifact"
        assert row["available"] is True
        assert row["trained_artifact_loaded"] is True
        assert row["can_lock_alone"] is False
        assert row["can_influence_device"] is False
        assert row["runtime_authoritative"] is False
        assert row["trigger_face_confirmation"] is False


def test_p2b1_all_classical_candidate_outputs_remain_non_locking(tmp_path: Path) -> None:
    X, feature_names = _training_matrix()
    build = build_classical_candidate_artifacts(
        model_dir=tmp_path,
        X_pos=X,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
    )
    metadata_path = _metadata_for_bundle(tmp_path, build, feature_names)
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=tmp_path, metadata_path=metadata_path)

    assert P2B1_CLASSICAL_IDS.issubset(set(CLASSIC_ADAPTER_IDS))
    results = []
    for candidate_id in P2B1_CLASSICAL_IDS:
        spec = resolver(candidate_id, None, {})
        results.append(evaluate_classic_candidate(candidate_id, {name: 0.2 for name in feature_names}, **spec))
    assert all(validate_candidate_result(result)["ok"] for result in results)
    assert all(result["can_lock_alone"] is False for result in results)
    assert all(result["can_vote"] is False for result in results)
