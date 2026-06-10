from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest


def _write_layer_artifact(path: Path, *, layer: str, feature_names: list[str]) -> str:
    rng = np.random.default_rng(11 if layer == "keyboard" else 13)
    X = rng.normal(0, 0.1, size=(24, len(feature_names)))
    model = IsolationForest(contamination=0.1, random_state=7).fit(X)
    payload = {
        "artifact_version": "hybrid-pro-artifact-v1",
        "layer": layer,
        "model_family": "hybrid_pro_layer_iforest",
        "feature_names": feature_names,
        "model": model,
        "shadow_only": True,
    }
    path.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    return path.name


def test_runtime_layer_payload_builder_exports_real_keyboard_mouse_and_combined(tmp_path: Path) -> None:
    from hybrid_runtime_layers import build_runtime_layer_payloads

    feature_names = ["keyboard_share", "mouse_share", "f0"]
    keyboard_artifact = _write_layer_artifact(tmp_path / "keyboard_verifier.pkl", layer="keyboard", feature_names=feature_names)
    mouse_artifact = _write_layer_artifact(tmp_path / "mouse_verifier.pkl", layer="mouse", feature_names=feature_names)
    (tmp_path / "fusion_model.pkl").write_bytes(b"fusion")
    metadata = {
        "feature_names": feature_names,
        "feature_schema_version": "feature-v1",
        "runtime_schema_version": "sequence-multiscale-v1",
        "layer_artifacts": {
            "keyboard": {"path": keyboard_artifact, "digest": "sha256:k"},
            "mouse": {"path": mouse_artifact, "digest": "sha256:m"},
            "combined": {"path": "fusion_model.pkl", "digest": "sha256:c"},
        },
        "classifier_family": "lightgbm",
        "hybrid_pro_training": {"model_family": "hybrid_pro"},
    }
    samples = [
        {"keyboard_share": 0.95, "mouse_share": 0.05, "context": "keyboard_heavy", "f0": 0.1},
        {"keyboard_share": 0.03, "mouse_share": 0.97, "context": "mouse_heavy", "f0": 0.2},
    ]

    payload = build_runtime_layer_payloads(
        metadata=metadata,
        metadata_file=str(tmp_path / "metadata.json"),
        window_samples=samples,
        prediction={"final": "suspicious", "risk": 64, "status": "suspicious"},
        runtime_bundle_source="developer_shadow_candidate",
    )

    assert payload["keyboard_risk"]["available"] is True
    assert payload["keyboard_risk"]["source"] == "hybrid_pro_layer_artifact"
    assert payload["mouse_risk"]["available"] is True
    assert payload["mouse_risk"]["source"] == "hybrid_pro_layer_artifact"
    assert payload["combined_risk"]["available"] is True
    assert payload["combined_risk"]["source"] == "hybrid_pro_combined_artifact"
    assert payload["combined_risk"]["display_label"] == "Combined Hybrid Pro"
    assert payload["fusion"]["can_influence_device"] is False
    assert payload["developer_shadow_candidate_runtime"] is True


def test_runtime_layer_payload_builder_keeps_missing_layer_unavailable(tmp_path: Path) -> None:
    from hybrid_runtime_layers import build_runtime_layer_payloads

    metadata = {
        "feature_names": ["keyboard_share", "mouse_share"],
        "layer_artifacts": {},
    }
    payload = build_runtime_layer_payloads(
        metadata=metadata,
        metadata_file=str(tmp_path / "metadata.json"),
        window_samples=[{"keyboard_share": 1.0, "mouse_share": 0.0, "context": "keyboard_heavy"}],
        prediction={"final": "legit", "risk": 10, "status": "legitimate"},
    )

    assert payload["classic_risk"]["available"] is True
    assert payload["keyboard_risk"]["available"] is False
    assert "no_layer_artifact" in payload["keyboard_risk"]["reason_codes"]
    assert payload["mouse_risk"]["available"] is False
    assert "no_layer_artifact" in payload["mouse_risk"]["reason_codes"]
    assert payload["combined_risk"]["available"] is True
    assert payload["combined_risk"]["can_lock"] is False


def test_hybrid_direct_state_uses_backend_runtime_layer_payloads() -> None:
    from hybrid_direct_contract import build_hybrid_direct_state_from_runtime

    layer_payloads = {
        "classic_risk": {"model": "classic", "available": True, "status": "available", "decision": "legit", "risk": 5, "reason_codes": ["classic_runtime_result_available"], "can_lock": False},
        "keyboard_risk": {"model": "keyboard", "available": True, "status": "available", "decision": "suspicious", "risk": 55, "reason_codes": ["layer_runtime_result_available"], "can_lock": False},
        "mouse_risk": {"model": "mouse", "available": True, "status": "available", "decision": "legit", "risk": 12, "reason_codes": ["layer_runtime_result_available"], "can_lock": False},
        "combined_risk": {"model": "combined", "display_label": "Combined Hybrid Pro", "available": True, "status": "available", "decision": "suspicious", "risk": 60, "reason_codes": ["combined_layer_artifact_available"], "can_lock": False},
    }
    state = build_hybrid_direct_state_from_runtime(
        {
            "active": True,
            "flow": "protected_warning",
            "monitorReady": True,
            "runtime_status": "suspicious",
            "decision": "suspicious",
            "runtime_window_count": 4,
            "runtime_layer_payloads": layer_payloads,
        },
        developer_simulation=True,
        runtime_bundle_source="developer_shadow_candidate",
    )

    assert state["keyboard_risk"]["available"] is True
    assert state["keyboard_risk"]["risk"] == 55.0
    assert state["mouse_risk"]["available"] is True
    assert state["combined_risk"]["display_label"] == "Combined Hybrid Pro"
    assert "runtime_layer_payloads_available" in state["reason_codes"]
    assert state["can_influence_device"] is False
    assert state["final_action"] != "lock"


def test_monitor_and_model_inference_export_runtime_layer_payload_source() -> None:
    assert "build_runtime_layer_payloads" in Path("src/bioauth/ml/inference.py").read_text(encoding="utf-8")
    monitor_source = Path("src/bioauth/runtime/monitor_impl.py").read_text(encoding="utf-8")
    assert "runtime_layer_payloads" in monitor_source
    assert "dict(prediction_diag.get(\"runtime_layer_payloads\") or {})" in monitor_source


def test_qml_does_not_hardcode_combined_cnn_lstm_label() -> None:
    qml = Path("qml/pages/HybridDirectTestPage.qml").read_text(encoding="utf-8")
    assert "combinedRisk.display_label" in qml
    assert "SectionHeader { title: root.trx(\"Combined CNN-LSTM\"" not in qml
    assert "backend.hybridDirectState" in qml
    assert "function" in qml  # display helpers only; fusion remains backend-owned
