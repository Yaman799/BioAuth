from __future__ import annotations

from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest


def _iforest_kwargs(contamination: float) -> dict:
    return {"contamination": float(contamination), "random_state": 42}


def _atomic_write(path: str, data: bytes) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)


def _scale_sample(kb: float, ms: float, *, requested: float = 60.0) -> dict:
    return {
        "scale_60s_requested_seconds": requested,
        "scale_60s_active": 1.0,
        "scale_60s_window_seconds": requested,
        "scale_60s_window_total_events": 140.0,
        "scale_60s_session_events_per_sec": 4.0,
        "scale_60s_session_kb_share": kb,
        "scale_60s_session_ms_share": ms,
        "scale_60s_session_modality_switch_ratio": 0.06,
        "multiscale_active_scale_count": 1.0,
        "multiscale_requested_scale_count": 1.0,
        "multiscale_scale_coverage": 1.0,
    }


def test_modality_mapping_extracts_prefixed_multiscale_fields() -> None:
    from hybrid_pro_modality_mapping import extract_modality_mapping, is_keyboard_window, is_mouse_window

    keyboard = _scale_sample(0.88, 0.12)
    mouse = _scale_sample(0.08, 0.92)

    keyboard_mapped = extract_modality_mapping(keyboard)
    mouse_mapped = extract_modality_mapping(mouse)

    assert keyboard_mapped["keyboard_share"] == 0.88
    assert keyboard_mapped["mouse_share"] == 0.12
    assert keyboard_mapped["source_fields"]["keyboard_share"] == "scale_60s_session_kb_share"
    assert is_keyboard_window(keyboard) is True
    assert is_mouse_window(keyboard) is False

    assert mouse_mapped["keyboard_share"] == 0.08
    assert mouse_mapped["mouse_share"] == 0.92
    assert mouse_mapped["source_fields"]["mouse_share"] == "scale_60s_session_ms_share"
    assert is_mouse_window(mouse) is True


def test_readiness_counts_multiscale_session_share_aliases() -> None:
    from hybrid_pro_layer_readiness import build_hybrid_pro_layer_readiness

    positives = [_scale_sample(0.86, 0.14) for _ in range(9)] + [_scale_sample(0.09, 0.91) for _ in range(10)]
    status = build_hybrid_pro_layer_readiness(positive_samples=positives)

    assert status["keyboard_positive_windows"] == 9
    assert status["mouse_positive_windows"] == 10
    assert status["keyboard_ready"] is True
    assert status["mouse_ready"] is True
    assert "scale_60s_session_kb_share" in status["modality_mapping"]["keyboard_source_fields"]
    assert "scale_60s_session_ms_share" in status["modality_mapping"]["mouse_source_fields"]
    assert "keyboard_modality_fields_detected" in status["reason_codes"]
    assert "mouse_modality_fields_detected" in status["reason_codes"]


def test_hybrid_pro_artifact_builder_uses_modality_mapping_for_layer_masks(tmp_path: Path, monkeypatch) -> None:
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
    keyboard_count = 9
    mouse_count = 9
    negative_count = 4
    rng = np.random.default_rng(123)
    X_pos = rng.normal(0, 0.2, size=(keyboard_count + mouse_count, 5))
    X_neg = rng.normal(2, 0.3, size=(negative_count, 5))
    X = np.vstack([X_pos, X_neg])
    y = np.asarray([0] * len(X_pos) + [1] * negative_count, dtype=int)
    samples = [_scale_sample(0.9, 0.1) for _ in range(keyboard_count)]
    samples += [_scale_sample(0.05, 0.95) for _ in range(mouse_count)]
    samples += [_scale_sample(0.5, 0.5) for _ in range(negative_count)]

    result = hpa.build_hybrid_pro_artifacts(
        model_dir=str(tmp_path),
        X=X,
        y=y,
        X_pos=X_pos,
        X_neg=X_neg,
        samples=samples,
        feature_names=[f"f{i}" for i in range(X.shape[1])],
        iforest_factory=IsolationForest,
        iforest_fit_kwargs_fn=_iforest_kwargs,
        atomic_write_bytes_fn=_atomic_write,
        classifier_family="lightgbm",
    )

    assert "keyboard" in result["layer_artifacts"]
    assert "mouse" in result["layer_artifacts"]
    assert "combined" in result["layer_artifacts"]
    assert result["training_data_summary"]["keyboard_positive_windows"] == keyboard_count
    assert result["training_data_summary"]["mouse_positive_windows"] == mouse_count
    assert "scale_60s_session_kb_share" in result["training_data_summary"]["keyboard_source_fields"]
    assert (tmp_path / "keyboard_verifier.pkl").exists()
    assert (tmp_path / "mouse_verifier.pkl").exists()


def test_qml_exposes_backend_modality_mapping_without_local_thresholds() -> None:
    source = Path("qml/pages/HybridDirectTestPage.qml").read_text(encoding="utf-8")
    assert "hybridLayerReadiness.modality_mapping" in source
    assert "hybridProModalityMappingLabel" in source
    assert "mappingFieldsText" in source
