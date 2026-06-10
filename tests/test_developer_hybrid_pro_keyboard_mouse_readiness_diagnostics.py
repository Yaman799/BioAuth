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


def _dataset(keyboard: int, mouse: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict], list[str]]:
    rng = np.random.default_rng(91)
    positive_count = keyboard + mouse
    negative_count = 6
    X_pos = rng.normal(0, 0.2, size=(positive_count, 5))
    X_neg = rng.normal(2, 0.3, size=(negative_count, 5))
    X = np.vstack([X_pos, X_neg])
    y = np.asarray([0] * positive_count + [1] * negative_count, dtype=int)
    samples: list[dict] = []
    for _ in range(keyboard):
        samples.append({"keyboard_share": 0.91, "mouse_share": 0.09, "context": "keyboard_heavy"})
    for _ in range(mouse):
        samples.append({"keyboard_share": 0.04, "mouse_share": 0.96, "context": "mouse_heavy"})
    for _ in range(negative_count):
        samples.append({"keyboard_share": 0.50, "mouse_share": 0.50, "context": "mixed"})
    return X, y, X_pos, X_neg, samples, [f"f{i}" for i in range(X.shape[1])]


def test_readiness_counts_keyboard_mouse_and_gaps() -> None:
    from hybrid_pro_layer_readiness import build_hybrid_pro_layer_readiness

    positives = [
        {"keyboard_share": 0.8, "mouse_share": 0.2, "context": "keyboard_heavy"},
        {"keyboard_share": 0.7, "mouse_share": 0.3, "context": "keyboard_heavy"},
        {"keyboard_share": 0.1, "mouse_share": 0.9, "context": "mouse_heavy"},
    ]
    status = build_hybrid_pro_layer_readiness(positive_samples=positives)

    assert status["keyboard_positive_windows"] == 2
    assert status["mouse_positive_windows"] == 1
    assert status["keyboard_gap"] == 6
    assert status["mouse_gap"] == 7
    assert status["layers"]["keyboard"]["share_threshold"] == 0.55
    assert "keyboard_artifact_skipped_insufficient_keyboard_data" in status["reason_codes"]
    assert status["production_ready"] is False


def test_training_records_layer_readiness_metadata(tmp_path: Path, monkeypatch) -> None:
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
    X, y, X_pos, X_neg, samples, feature_names = _dataset(keyboard=3, mouse=9)
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

    readiness = result["layer_readiness"]
    assert readiness["keyboard_positive_windows"] == 3
    assert readiness["keyboard_gap"] == 5
    assert readiness["mouse_positive_windows"] == 9
    assert readiness["mouse_ready"] is True
    assert result["training_data_summary"]["required_layer_positive_windows"] == 8
    assert result["skipped_layers"]["keyboard"]["readiness_gap"] == 5
    assert "mouse" in result["layer_artifacts"]


def test_capability_status_exposes_layer_readiness_from_metadata(tmp_path: Path, monkeypatch) -> None:
    import hybrid_pro_capability as hpc

    monkeypatch.setattr(
        hpc,
        "check_hybrid_pro_libraries",
        lambda **_: {"available": True, "modules": {}, "missing_libraries": [], "reason_codes": [], "status_label": "Hybrid Pro libraries installed"},
    )
    metadata = {
        "model_status": "approved_for_shadow",
        "classifier_family": "random_forest",
        "context_models": {"bundles": {"mouse_heavy": {}}},
        "training_data_summary": {
            "positive_windows": 12,
            "keyboard_positive_windows": 2,
            "mouse_positive_windows": 10,
            "required_layer_positive_windows": 8,
        },
        "skipped_layers": {"keyboard": {"reason_codes": ["keyboard_artifact_skipped_insufficient_keyboard_data"]}},
    }
    (tmp_path / "model.pkl").write_bytes(b"classic")
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    status = hpc.build_hybrid_pro_status(
        bundle_paths={"base": str(tmp_path), "model": str(tmp_path / "model.pkl"), "metadata": str(tmp_path / "metadata.json")}
    )

    readiness = status["layer_readiness"]
    assert readiness["keyboard_positive_windows"] == 2
    assert readiness["keyboard_gap"] == 6
    assert readiness["mouse_ready"] is True
    assert "hybrid_pro_layer_training_data_partial" in status["reason_codes"]


def test_flattened_hybrid_direct_state_contains_layer_readiness() -> None:
    from hybrid_direct_contract import build_hybrid_direct_state

    state = build_hybrid_direct_state(
        {
            "hybridProStatus": {
                "libraries_available": True,
                "artifacts_available": False,
                "missing_artifacts": ["keyboard"],
                "reason_codes": ["keyboard_artifact_missing"],
                "runtime_mode": "context_aware",
                "runtime_model_family": "random_forest",
                "layer_readiness": {
                    "keyboard_positive_windows": 2,
                    "mouse_positive_windows": 11,
                    "layers": {
                        "keyboard": {"ready": False, "positive_windows": 2, "required_positive_windows": 8, "gap": 6},
                        "mouse": {"ready": True, "positive_windows": 11, "required_positive_windows": 8, "gap": 0},
                    },
                },
            }
        }
    )

    assert state["hybridProLayerReadiness"]["keyboard_positive_windows"] == 2
    assert state["hybridProLayerReadiness"]["layers"]["mouse"]["ready"] is True
    assert state["can_influence_device"] is False


def test_qml_reads_backend_layer_readiness_without_local_thresholds() -> None:
    source = Path("qml/pages/HybridDirectTestPage.qml").read_text(encoding="utf-8")
    assert "hybridState.hybridProLayerReadiness" in source
    assert "keyboardReadinessPill" in source
    assert "mouseReadinessPill" in source
    assert "combinedReadinessPill" in source
    assert "backend.hybridDirectState" in source
