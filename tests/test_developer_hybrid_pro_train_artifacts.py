from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest


def _iforest_kwargs(contamination: float) -> dict:
    return {"contamination": float(contamination), "random_state": 42}


def _atomic_write(path: str, data: bytes) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)


def _dataset(keyboard: int = 10, mouse: int = 10) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict], list[str]]:
    rng = np.random.default_rng(17)
    positive_count = keyboard + mouse
    negative_count = 6
    X_pos = rng.normal(0, 0.2, size=(positive_count, 6))
    X_neg = rng.normal(2, 0.3, size=(negative_count, 6))
    X = np.vstack([X_pos, X_neg])
    y = np.asarray([0] * positive_count + [1] * negative_count, dtype=int)
    samples: list[dict] = []
    for _ in range(keyboard):
        samples.append({"keyboard_share": 0.92, "mouse_share": 0.08, "context": "keyboard_heavy"})
    for _ in range(mouse):
        samples.append({"keyboard_share": 0.05, "mouse_share": 0.95, "context": "mouse_heavy"})
    for _ in range(negative_count):
        samples.append({"keyboard_share": 0.50, "mouse_share": 0.50, "context": "mixed"})
    return X, y, X_pos, X_neg, samples, [f"f{i}" for i in range(X.shape[1])]


def test_build_hybrid_pro_artifacts_trains_keyboard_mouse_and_fusion(tmp_path: Path, monkeypatch) -> None:
    import training_core.hybrid_pro_artifacts as hpa

    monkeypatch.setattr(
        hpa,
        "hybrid_pro_dependency_status",
        lambda: {
            "libraries_available": True,
            "modules": {"torch": {"available": True, "version": "2.x"}, "lightgbm": {"available": True, "version": "4.x"}},
            "missing_libraries": [],
            "reason_codes": [],
        },
    )
    X, y, X_pos, X_neg, samples, feature_names = _dataset()
    result = hpa.build_hybrid_pro_artifacts(
        model_dir=str(tmp_path),
        X=X,
        y=y,
        X_pos=X_pos,
        X_neg=X_neg,
        samples=samples,
        feature_names=feature_names,
        iforest_factory=IsolationForest,
        iforest_fit_kwargs_fn=_iforest_kwargs,
        atomic_write_bytes_fn=_atomic_write,
        classifier_family="lightgbm",
    )

    assert result["training_strategy"] == "hybrid_pro"
    assert result["hybrid_pro_enabled"] is True
    assert set(result["layer_artifacts"]) == {"keyboard", "mouse", "combined"}
    assert (tmp_path / "keyboard_verifier.pkl").exists()
    assert (tmp_path / "mouse_verifier.pkl").exists()
    assert (tmp_path / "fusion_model.pkl").exists()
    assert "hybrid_pro_artifacts_trained" in result["skip_reason_codes"]


def test_build_hybrid_pro_artifacts_skips_missing_keyboard_data_with_reason(tmp_path: Path, monkeypatch) -> None:
    import training_core.hybrid_pro_artifacts as hpa

    monkeypatch.setattr(
        hpa,
        "hybrid_pro_dependency_status",
        lambda: {
            "libraries_available": True,
            "modules": {"torch": {"available": False, "version": ""}, "lightgbm": {"available": True, "version": "4.x"}},
            "missing_libraries": ["torch"],
            "reason_codes": ["torch_missing"],
        },
    )
    X, y, X_pos, X_neg, samples, feature_names = _dataset(keyboard=2, mouse=18)
    result = hpa.build_hybrid_pro_artifacts(
        model_dir=str(tmp_path),
        X=X,
        y=y,
        X_pos=X_pos,
        X_neg=X_neg,
        samples=samples,
        feature_names=feature_names,
        iforest_factory=IsolationForest,
        iforest_fit_kwargs_fn=_iforest_kwargs,
        atomic_write_bytes_fn=_atomic_write,
        classifier_family="random_forest",
    )

    assert result["training_strategy"] == "hybrid_pro_partial"
    assert "keyboard" in result["skipped_layers"]
    assert "keyboard_artifact_skipped_insufficient_keyboard_data" in result["skip_reason_codes"]
    assert "mouse" in result["layer_artifacts"]
    assert "combined" in result["layer_artifacts"]
    assert "torch_skipped_dependency_missing" in result["skip_reason_codes"]


def test_phase1_artifact_detector_recognizes_phase2_artifacts(tmp_path: Path, monkeypatch) -> None:
    import training_core.hybrid_pro_artifacts as hpa
    from hybrid_pro_capability import discover_hybrid_pro_artifacts

    monkeypatch.setattr(
        hpa,
        "hybrid_pro_dependency_status",
        lambda: {
            "libraries_available": True,
            "modules": {"torch": {"available": True, "version": "2.x"}, "lightgbm": {"available": True, "version": "4.x"}},
            "missing_libraries": [],
            "reason_codes": [],
        },
    )
    X, y, X_pos, X_neg, samples, feature_names = _dataset()
    result = hpa.build_hybrid_pro_artifacts(
        model_dir=str(tmp_path),
        X=X,
        y=y,
        X_pos=X_pos,
        X_neg=X_neg,
        samples=samples,
        feature_names=feature_names,
        iforest_factory=IsolationForest,
        iforest_fit_kwargs_fn=_iforest_kwargs,
        atomic_write_bytes_fn=_atomic_write,
        classifier_family="lightgbm",
    )
    metadata = {
        "model_status": "approved_for_shadow",
        "feature_schema_version": "feature-v1",
        "runtime_schema_version": "sequence-multiscale-v1",
        "layer_artifacts": result["layer_artifacts"],
        "hybrid_pro_artifacts": result["layer_artifacts"],
    }
    (tmp_path / "model.pkl").write_bytes(b"classic")
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    paths = {"base": str(tmp_path), "model": str(tmp_path / "model.pkl"), "metadata": str(tmp_path / "metadata.json")}

    inventory = discover_hybrid_pro_artifacts(bundle_paths=paths)

    assert inventory["available"] is True
    assert inventory["runtime_mode"] == "hybrid_pro"
    assert inventory["layers"]["keyboard"]["available"] is True
    assert inventory["layers"]["mouse"]["available"] is True
    assert inventory["layers"]["combined"]["available"] is True


def test_training_pipeline_records_hybrid_pro_metadata_source() -> None:
    source = Path("training_core/pipeline.py").read_text(encoding="utf-8")
    assert "build_hybrid_pro_artifacts" in source
    assert 'metadata["layer_artifacts"]' in source
    assert 'metadata["hybrid_pro_artifacts"]' in source
    assert 'metadata["training_strategy"]' in source
    assert 'metadata["hybrid_pro_enabled"]' in source
    assert "runtime_requires_production_approval" in source
    assert 'metadata["model_status"] = "pending_evaluation"' in source
    assert "approved_for_production" not in source.split("build_hybrid_pro_artifacts", 1)[1].split("positive_sample_sources", 1)[0]


def test_deep_sequence_training_updates_cnn_lstm_artifact_metadata_source() -> None:
    source = Path("src/bioauth/ml/training.py").read_text(encoding="utf-8")
    assert "cnn_lstm_artifact_trained" in source
    assert "cnn_lstm_skipped_insufficient_sequence_data" in source
    assert "metadata['layer_artifacts'] = layer_artifacts" in source
    assert "metadata['hybrid_pro_artifacts'] = hybrid_pro_artifacts" in source
