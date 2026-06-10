from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from hybrid_candidates.adapters import evaluate_supervised_candidate
from hybrid_candidates.artifact_resolver import build_candidate_bundle_artifact_resolver
from hybrid_candidates.offline_runner import run_offline_candidate_replay
from hybrid_candidates.registry import validate_candidate_result
from metadata_core.constants import KB_HEADER, MS_HEADER
from security import compact_chunks, write_encrypted
from training_core.candidate_artifact_builders import (
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_FILENAMES,
    OPTIONAL_SUPERVISED_CANDIDATE_IDS,
    OptionalSupervisedDependencySpec,
    build_optional_supervised_candidate_artifacts,
)


class FakeOptionalSupervisedEstimator:
    def __init__(self, **kwargs: Any) -> None:
        self.params = dict(kwargs)
        self.offset = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> "FakeOptionalSupervisedEstimator":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=int).reshape(-1)
        owner = X[y == 0]
        intruder = X[y == 1]
        self.owner_mean_ = np.mean(owner, axis=0) if owner.size else np.zeros(X.shape[1], dtype=float)
        self.intruder_mean_ = np.mean(intruder, axis=0) if intruder.size else np.ones(X.shape[1], dtype=float)
        self.offset = float(np.mean(self.intruder_mean_ - self.owner_mean_))
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        centered = X - np.asarray(getattr(self, "owner_mean_", np.zeros(X.shape[1])), dtype=float)
        raw = np.mean(centered, axis=1) + float(getattr(self, "offset", 0.0))
        prob = 1.0 / (1.0 + np.exp(-raw))
        return np.column_stack([1.0 - prob, prob])


def _training_matrices(owner_count: int = 14, intruder_count: int = 4, feature_count: int = 6) -> tuple[np.ndarray, np.ndarray, list[str]]:
    rng = np.random.default_rng(20260512)
    X_pos = rng.normal(loc=0.0, scale=0.2, size=(owner_count, feature_count)).astype(float)
    X_neg = rng.normal(loc=1.5, scale=0.2, size=(intruder_count, feature_count)).astype(float)
    return X_pos, X_neg, [f"f{idx}" for idx in range(feature_count)]


def _fake_dependency(candidate_id: str) -> OptionalSupervisedDependencySpec:
    return OptionalSupervisedDependencySpec(
        candidate_id=candidate_id,
        dependency_name=f"fake_{candidate_id}",
        model_family=candidate_id.replace("supervised_", ""),
        estimator_class=FakeOptionalSupervisedEstimator,
        dependency_version="1.0-test",
        available=True,
    )


def _missing_dependency(candidate_id: str) -> OptionalSupervisedDependencySpec:
    return OptionalSupervisedDependencySpec(
        candidate_id=candidate_id,
        dependency_name=candidate_id.replace("supervised_", ""),
        model_family=candidate_id.replace("supervised_", ""),
        estimator_class=None,
        dependency_version=None,
        available=False,
    )


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


def _candidate_rows(path: str | Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_p2b2_dependency_missing_writes_skipped_rows_without_crashing(tmp_path: Path) -> None:
    X_pos, X_neg, feature_names = _training_matrices()
    build = build_optional_supervised_candidate_artifacts(
        model_dir=tmp_path,
        X_pos=X_pos,
        X_neg=X_neg,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
        dependency_resolver=_missing_dependency,
    )

    assert set(build["candidate_artifacts"]) == set(OPTIONAL_SUPERVISED_CANDIDATE_IDS)
    assert build["status_counts"]["trained"] == 0
    assert build["status_counts"]["skipped"] == len(OPTIONAL_SUPERVISED_CANDIDATE_IDS)
    for candidate_id, entry in build["candidate_artifacts"].items():
        assert entry["status"] == "skipped"
        assert entry["reason"] == "dependency_missing"
        assert entry["artifact_path"] is None
        assert entry["can_lock_alone"] is False
        assert not (tmp_path / OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]).exists()


def test_p2b2_insufficient_intruder_samples_writes_precise_skipped_manifest(tmp_path: Path) -> None:
    X_pos, _X_neg, feature_names = _training_matrices(intruder_count=4)
    X_neg = np.empty((0, len(feature_names)), dtype=float)
    build = build_optional_supervised_candidate_artifacts(
        model_dir=tmp_path,
        X_pos=X_pos,
        X_neg=X_neg,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
        dependency_resolver=_fake_dependency,
    )

    assert build["status_counts"]["trained"] == 0
    for entry in build["candidate_artifacts"].values():
        assert entry["status"] == "skipped"
        assert entry["reason"] == "insufficient_intruder_samples"
        assert entry["intruder_sample_count"] == 0
        assert entry["artifact_path"] is None
        assert entry["can_lock_alone"] is False


def test_p2b2_builders_create_diagnostic_shadow_artifacts_with_low_intruder_warning(tmp_path: Path) -> None:
    X_pos, X_neg, feature_names = _training_matrices(owner_count=14, intruder_count=3)
    build = build_optional_supervised_candidate_artifacts(
        model_dir=tmp_path,
        X_pos=X_pos,
        X_neg=X_neg,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
        dependency_resolver=_fake_dependency,
    )

    assert build["status_counts"]["trained"] == len(OPTIONAL_SUPERVISED_CANDIDATE_IDS)
    for candidate_id, entry in build["candidate_artifacts"].items():
        assert entry["status"] == "trained"
        assert entry["artifact_schema"] == CANDIDATE_ARTIFACT_SCHEMA_VERSION
        assert entry["artifact_path"] == OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]
        assert (tmp_path / str(entry["artifact_path"])).is_file()
        assert entry["owner_sample_count"] == len(X_pos)
        assert entry["intruder_sample_count"] == len(X_neg)
        assert entry["low_intruder_sample_warning"] is True
        assert entry["artifact_mode"] == "diagnostic_shadow"
        assert entry["can_lock_alone"] is False
        assert entry["can_influence_device"] is False
        assert entry["runtime_authoritative"] is False
        assert entry["trigger_face_confirmation"] is False


def test_p2b2_resolver_maps_optional_supervised_candidates_to_artifacts(tmp_path: Path) -> None:
    X_pos, X_neg, feature_names = _training_matrices()
    build = build_optional_supervised_candidate_artifacts(
        model_dir=tmp_path,
        X_pos=X_pos,
        X_neg=X_neg,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
        dependency_resolver=_fake_dependency,
    )
    metadata_path = _metadata_for_bundle(tmp_path, build, feature_names)
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=tmp_path, metadata_path=metadata_path)

    for candidate_id in OPTIONAL_SUPERVISED_CANDIDATE_IDS:
        spec = resolver(candidate_id, None, {})
        assert Path(spec["artifact_path"]).name == OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]
        assert spec["metadata"]["artifact_builder_status"] == "trained"
        assert spec["metadata"]["artifact_builder_reason"] == "ok"
        assert spec["metadata"]["feature_names"] == feature_names
        assert spec["metadata"]["dependency_available"] is True
        assert spec["metadata"]["can_lock_alone"] is False
        result = evaluate_supervised_candidate(candidate_id, {name: 0.2 for name in feature_names}, **spec)
        assert validate_candidate_result(result)["ok"] is True
        assert result["available"] is True
        assert result["reason"] == "ok"
        assert result["reason"] != "missing_trained_artifact"
        assert result["can_lock_alone"] is False


def test_p2b2_hybrid_direct_reports_precise_skipped_reason_for_missing_dependency(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root / "authorized", "owner-session", row_count=12)
    feature_names = ["keyboard_row_count", "mouse_row_count", "keyboard_file_size_bytes", "mouse_file_size_bytes"]
    X_pos = np.ones((12, len(feature_names)), dtype=float)
    X_neg = np.ones((3, len(feature_names)), dtype=float) * 2.0
    bundle_dir = tmp_path / "candidate_bundle"
    build = build_optional_supervised_candidate_artifacts(
        model_dir=bundle_dir,
        X_pos=X_pos,
        X_neg=X_neg,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
        dependency_resolver=_missing_dependency,
    )
    metadata_path = _metadata_for_bundle(bundle_dir, build, feature_names)
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=bundle_dir, metadata_path=metadata_path)

    summary = run_offline_candidate_replay(
        selected_candidates=list(OPTIONAL_SUPERVISED_CANDIDATE_IDS),
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        artifact_resolver=resolver,
    )
    rows = _candidate_rows(summary["report_paths"]["candidate_results"])
    assert {row["candidate_id"] for row in rows} == set(OPTIONAL_SUPERVISED_CANDIDATE_IDS)
    for row in rows:
        assert row["available"] is False
        assert row["reason"] == "dependency_missing"
        assert row["reason"] != "missing_trained_artifact"
        assert row["can_lock_alone"] is False
        assert row["can_vote"] is False


def test_p2b2_hybrid_direct_uses_valid_optional_artifact_without_missing_artifact(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root / "authorized", "owner-session", row_count=12)
    feature_names = ["keyboard_row_count", "mouse_row_count", "keyboard_file_size_bytes", "mouse_file_size_bytes"]
    X_pos = np.ones((12, len(feature_names)), dtype=float)
    X_neg = np.ones((3, len(feature_names)), dtype=float) * 2.0
    bundle_dir = tmp_path / "candidate_bundle"
    build = build_optional_supervised_candidate_artifacts(
        model_dir=bundle_dir,
        X_pos=X_pos,
        X_neg=X_neg,
        feature_names=feature_names,
        feature_schema_version="test-feature-schema-v1",
        dependency_resolver=_fake_dependency,
    )
    metadata_path = _metadata_for_bundle(bundle_dir, build, feature_names)
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=bundle_dir, metadata_path=metadata_path)

    summary = run_offline_candidate_replay(
        selected_candidates=["supervised_xgboost"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        artifact_resolver=resolver,
    )
    rows = _candidate_rows(summary["report_paths"]["candidate_results"])
    assert len(rows) == 1
    row = rows[0]
    assert row["candidate_id"] == "supervised_xgboost"
    assert row["available"] is True
    assert row["trained_artifact_loaded"] is True
    assert row["reason"] == "ok"
    assert row["reason"] != "missing_trained_artifact"
    assert row["can_lock_alone"] is False


def test_p2b2_existing_random_forest_adapter_still_scores_supplied_artifact() -> None:
    feature_names = ["f0", "f1"]
    artifact = FakeOptionalSupervisedEstimator().fit(np.asarray([[0.0, 0.0], [1.0, 1.0]], dtype=float), np.asarray([0, 1], dtype=int))
    result = evaluate_supervised_candidate(
        "supervised_random_forest",
        {"f0": 0.1, "f1": 0.2},
        artifact=artifact,
        metadata={"feature_names": feature_names, "threshold": 0.5},
    )
    assert validate_candidate_result(result)["ok"] is True
    assert result["available"] is True
    assert result["can_lock_alone"] is False
