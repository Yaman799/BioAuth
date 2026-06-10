from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pytest

from training_core import pipeline


class DummyIsolationForest:
    def fit(self, X: Any) -> "DummyIsolationForest":
        self.feature_count_ = int(getattr(X, "shape", [0, 0])[1])
        return self


def _sample_rows() -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for idx in range(8):
        rows.append(
            {
                "key_hold_mean": 0.10 + idx * 0.01,
                "flight_mean": 0.20 + idx * 0.01,
                "dx": 1.0 + idx,
                "dy": 0.5 + idx,
                "raw_text": "must-not-be-persisted",
                "typed_text": "do-not-store",
                "key": "A",
            }
        )
    return rows


def _build_matrix(samples: list[Mapping[str, Any]], feature_names: list[str]) -> np.ndarray:
    return np.asarray([[float(sample.get(name, 0.0) or 0.0) for name in feature_names] for sample in samples], dtype=float)


def _atomic_write_bytes(path: str, payload: bytes) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(payload)


def _atomic_write_text(path: str, payload: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(payload, encoding="utf-8")


def _train_model_kwargs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(pipeline, "build_classical_baselines", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        pipeline,
        "build_hybrid_pro_artifacts",
        lambda **kwargs: {
            "training_strategy": "context_aware",
            "hybrid_pro_enabled": False,
            "layer_artifacts": {},
            "skipped_layers": {},
            "skip_reason_codes": [],
            "dependency_versions": {},
            "layer_readiness": {},
            "modality_mapping": {},
        },
    )
    rows = _sample_rows()
    return {
        "sessions": ["owner-a", "owner-b"],
        "negative_sessions": [],
        "model_file": str(tmp_path / "model.pkl"),
        "classifier_file": str(tmp_path / "classifier.pkl"),
        "metadata_file": str(tmp_path / "metadata.json"),
        "list_session_dirs_fn": lambda: ["owner-a", "owner-b"],
        "normalize_window_scales_fn": lambda: [10.0],
        "emit_progress_fn": lambda *args, **kwargs: None,
        "clamp01_fn": lambda value: max(0.0, min(1.0, float(value))),
        "progress_heartbeat_factory": lambda *args, **kwargs: pipeline._ProgressHeartbeat(*args, interval_seconds=60.0, **kwargs),
        "get_label_fn": lambda session_path, kind: 0,
        "extract_window_samples_from_session_fn": lambda *args, **kwargs: [dict(row) for row in rows[:4]],
        "annotate_sequence_trend_windows_fn": lambda samples: samples,
        "annotate_transition_windows_fn": lambda samples: samples,
        "extract_from_session_fn": lambda *args, **kwargs: {},
        "apply_transition_window_policy_fn": lambda windows, **kwargs: (windows, {"kept": len(windows)}),
        "normalize_feature_dict_fn": lambda sample: {key: float(value) for key, value in dict(sample).items() if isinstance(value, (int, float))},
        "encrypted_session_read_error": RuntimeError,
        "logger": pipeline.LOGGER,
        "max_train_windows_per_session": 8,
        "window_seconds": 10.0,
        "window_step_seconds": 5.0,
        "min_window_events": 1,
        "per_scale_sample_counts_fn": lambda samples, scales: {"10.0": len(samples)},
        "sequence_feature_summary_fn": lambda feature_names: {"enabled": False, "total_feature_count": 0},
        "build_matrix_fn": _build_matrix,
        "min_positive_window_samples": 2,
        "iforest_factory": DummyIsolationForest,
        "iforest_fit_kwargs_fn": lambda contamination: {},
        "get_anomaly_scores_fn": lambda model, X: np.linspace(0.1, 0.4, int(getattr(X, "shape", [0])[0])),
        "score_percentiles_dict_fn": lambda scores: {"p50": 0.2, "p95": 0.4},
        "train_supervised_classifier_candidates_fn": lambda *args, **kwargs: (None, {"classifier_family": None, "supervised_classifier": {"head_to_head": {}}}),
        "min_negative_window_samples": 1,
        "remove_classifier_sidecar_fn": lambda path: None,
        "atomic_write_bytes_fn": _atomic_write_bytes,
        "save_model_hash_fn": lambda path: None,
        "save_classifier_sidecar_fn": lambda path: None,
        "atomic_write_text_fn": _atomic_write_text,
        "save_metadata_hash_fn": lambda path: None,
        "feature_schema_version": "phase4-test-schema-v1",
        "feature_window_strategy": "synthetic",
        "predict_window_step_seconds": 5.0,
        "max_predict_windows": 3,
        "recommended_enrollment_sessions": 2,
        "default_risk_sensitivity": "conservative",
        "classifier_selection_version": "test",
        "train_context_submodels_fn": lambda **kwargs: {"active_contexts": ["global_only"], "bundles": {}, "context_sample_counts": {}},
        "context_selection_version": "test-context",
        "summarize_transition_training_fn": lambda stats: {"session_count": len(stats)},
        "transition_policy_version": "test-transition",
        "transition_session_start_seconds": 30.0,
        "transition_post_idle_gap_seconds": 15.0,
        "transition_activity_shift_threshold": 0.25,
        "transition_keep_ratio": 0.75,
        "transition_min_keep_windows": 2,
        "compute_user_calibration_profile_fn": lambda **kwargs: {"status": "test"},
    }


def test_phase4_train_model_writes_candidate_artifact_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_candidate_build(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        manifest = {
            "schema_version": "test-manifest",
            "status_counts": {"trained": 1, "skipped": 1, "failed": 0},
            "candidates": {
                "classic_scaled_manhattan": {"candidate_id": "classic_scaled_manhattan", "status": "trained", "reason": "ok", "artifact_path": "classic_scaled_manhattan.pkl"},
                "combined_cnn_lstm": {"candidate_id": "combined_cnn_lstm", "status": "skipped", "reason": "insufficient_combined_windows", "artifact_path": None},
            },
        }
        _atomic_write_text(str(Path(kwargs["model_dir"]) / "candidate_artifacts_manifest.json"), json.dumps(manifest))
        return {
            "schema_version": "test-manifest",
            "builder_version": "phase4-test-builder",
            "manifest_path": "candidate_artifacts_manifest.json",
            "manifest": manifest,
            "candidate_artifacts": manifest["candidates"],
            "status_counts": dict(manifest["status_counts"]),
            "report_only": True,
            "can_lock": False,
            "can_lock_alone": False,
            "can_influence_device": False,
            "runtime_authoritative": False,
            "trigger_face_confirmation": False,
        }

    monkeypatch.setattr(pipeline, "build_report_only_candidate_artifacts", fake_candidate_build)
    model, status = pipeline.train_model(**_train_model_kwargs(tmp_path, monkeypatch))

    assert model is not None
    assert status == "ok"
    assert captured["include_deep_candidates"] is True
    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    training = metadata["candidate_artifact_training"]
    assert training["candidate_artifacts_built"] == ["classic_scaled_manhattan"]
    assert training["candidate_artifacts_skipped"] == {"combined_cnn_lstm": "insufficient_combined_windows"}
    assert training["status_counts"] == {"trained": 1, "skipped": 1, "failed": 0}
    assert training["artifact_manifest"] == "candidate_artifacts_manifest.json"
    assert training["report_only"] is True
    assert training["can_influence_device"] is False
    assert metadata["artifacts"]["candidate_artifacts_manifest"] == "candidate_artifacts_manifest.json"


def test_phase4_candidate_failure_is_isolated_when_not_strict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def exploding_candidate_build(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("candidate builder outage")

    monkeypatch.setattr(pipeline, "build_report_only_candidate_artifacts", exploding_candidate_build)
    model, status = pipeline.train_model(**_train_model_kwargs(tmp_path, monkeypatch), strict_candidate_training=False)

    assert model is not None
    assert status == "ok"
    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    training = metadata["candidate_artifact_training"]
    assert training["status_counts"]["failed"] >= 1
    assert set(training["candidate_artifacts_failed"])
    assert all(reason.startswith("candidate_artifact_build_failed") for reason in training["candidate_artifacts_failed"].values())
    assert training["can_lock_alone"] is False
    assert training["runtime_authoritative"] is False


def test_phase4_candidate_failure_raises_in_strict_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "build_report_only_candidate_artifacts", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("strict outage")))

    with pytest.raises(RuntimeError, match="strict outage"):
        pipeline.train_model(**_train_model_kwargs(tmp_path, monkeypatch), strict_candidate_training=True)


def test_phase4_deep_candidate_switch_writes_structured_skips(tmp_path: Path) -> None:
    from training_core.candidate_artifact_builders import build_report_only_candidate_artifacts

    rows = _sample_rows()
    feature_names = ["key_hold_mean", "flight_mean", "dx", "dy", "raw_text", "typed_text", "key"]
    build = build_report_only_candidate_artifacts(
        model_dir=tmp_path,
        X_pos=np.asarray([[0.1, 0.2, 1.0, 0.5], [0.2, 0.3, 2.0, 1.5], [0.3, 0.4, 3.0, 2.5], [0.4, 0.5, 4.0, 3.5], [0.5, 0.6, 5.0, 4.5]], dtype=float),
        X_neg=np.asarray([], dtype=float).reshape(0, 4),
        samples=rows,
        labels=[0] * len(rows),
        sample_sources=["owner-a"] * len(rows),
        feature_names=feature_names,
        feature_schema_version="phase4-test-schema-v1",
        include_deep_candidates=False,
    )

    assert build["status_counts"]["skipped"] >= 1
    for candidate_id, entry in build["candidate_artifacts"].items():
        if candidate_id.startswith(("keyboard_", "mouse_", "oneclass_")) or candidate_id == "combined_cnn_lstm":
            assert entry["status"] == "skipped"
            assert entry["reason"] == "deep_candidate_artifacts_disabled"
            assert entry["artifact_path"] is None
            assert entry["can_lock_alone"] is False
            assert "raw_text" not in entry.get("feature_names", [])
            assert "typed_text" not in entry.get("feature_names", [])
            assert "key" not in entry.get("feature_names", [])
