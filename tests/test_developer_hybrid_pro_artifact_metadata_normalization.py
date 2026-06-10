from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest


def _write_layer_artifact(path: Path, *, layer: str, feature_names: list[str]) -> str:
    rng = np.random.default_rng(31 if layer == "mouse" else 29)
    X = rng.normal(0, 0.1, size=(24, len(feature_names)))
    model = IsolationForest(contamination=0.1, random_state=17).fit(X)
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


def test_normalizer_repairs_filesystem_artifact_missing_from_metadata(tmp_path: Path) -> None:
    from hybrid_pro_metadata_normalization import normalize_hybrid_pro_artifact_metadata

    feature_names = ["keyboard_share", "mouse_share", "f0"]
    _write_layer_artifact(tmp_path / "mouse_verifier.pkl", layer="mouse", feature_names=feature_names)
    (tmp_path / "fusion_model.pkl").write_bytes(b"fusion")
    metadata = {
        "model_status": "approved_for_shadow",
        "feature_names": feature_names,
        "layer_artifacts": {},
        "hybrid_pro_artifacts": {},
        "artifacts": {},
        "production_ready": False,
        "approval_status": "approved_for_shadow",
    }

    normalized = normalize_hybrid_pro_artifact_metadata(
        metadata,
        bundle_paths={"base": str(tmp_path), "metadata": str(tmp_path / "metadata.json")},
        metadata_path=str(tmp_path / "metadata.json"),
        base_dir=str(tmp_path),
    )

    assert normalized["layer_artifacts"]["mouse"]["available"] is True
    assert normalized["layer_artifacts"]["mouse"]["path"] == "mouse_verifier.pkl"
    assert "mouse_file_exists_metadata_missing_normalized" in normalized["layer_artifacts"]["mouse"]["reason_codes"]
    assert normalized["hybrid_pro_artifacts"]["combined"]["available"] is True
    assert "keyboard" in normalized["skipped_layers"]
    assert "keyboard_artifact_not_found_on_disk" in normalized["skipped_layers"]["keyboard"]["reason_codes"]
    assert normalized["production_ready"] is False
    assert normalized["approval_status"] == "approved_for_shadow"


def test_capability_detector_reports_partial_artifacts_after_normalization(tmp_path: Path) -> None:
    from hybrid_pro_capability import discover_hybrid_pro_artifacts

    (tmp_path / "model.pkl").write_bytes(b"classic")
    (tmp_path / "metadata.json").write_text(
        json.dumps({"model_status": "approved_for_shadow", "classifier_family": "random_forest", "context_models": {"bundles": {"mouse_heavy": {}}}}),
        encoding="utf-8",
    )
    (tmp_path / "mouse_verifier.pkl").write_bytes(b"mouse")
    (tmp_path / "fusion_model.pkl").write_bytes(b"fusion")

    inventory = discover_hybrid_pro_artifacts(
        bundle_paths={"base": str(tmp_path), "model": str(tmp_path / "model.pkl"), "metadata": str(tmp_path / "metadata.json")}
    )

    assert inventory["available"] is False
    assert inventory["layers"]["mouse"]["available"] is True
    assert inventory["layers"]["mouse"]["source"] in {"metadata", "filesystem_convention", "layer_artifacts"}
    assert inventory["layers"]["combined"]["available"] is True
    assert inventory["missing_artifacts"] == ["keyboard"]
    assert "keyboard_artifact_not_found_on_disk" in inventory["reason_codes"]
    assert "mouse_file_exists_metadata_missing_normalized" in inventory["reason_codes"]


def test_runtime_layer_payload_scores_filesystem_artifact_without_metadata_entry(tmp_path: Path) -> None:
    from hybrid_runtime_layers import build_runtime_layer_payloads

    feature_names = ["keyboard_share", "mouse_share", "f0"]
    _write_layer_artifact(tmp_path / "mouse_verifier.pkl", layer="mouse", feature_names=feature_names)
    metadata = {
        "feature_names": feature_names,
        "layer_artifacts": {},
        "hybrid_pro_artifacts": {},
        "classifier_family": "random_forest",
    }

    payload = build_runtime_layer_payloads(
        metadata=metadata,
        metadata_file=str(tmp_path / "metadata.json"),
        window_samples=[{"keyboard_share": 0.02, "mouse_share": 0.98, "context": "mouse_heavy", "f0": 0.1}],
        prediction={"final": "legit", "risk": 9, "status": "legitimate"},
        runtime_bundle_source="developer_shadow_candidate",
    )

    assert payload["mouse_risk"]["available"] is True
    assert payload["mouse_risk"]["source"] == "hybrid_pro_layer_artifact"
    assert "mouse_file_exists_metadata_missing_normalized" in payload["mouse_risk"]["reason_codes"]
    assert payload["keyboard_risk"]["available"] is False
    assert "keyboard_artifact_missing" in payload["keyboard_risk"]["reason_codes"]
    assert payload["combined_risk"]["can_lock"] is False
    assert payload["developer_shadow_candidate_runtime"] is True


def test_training_paths_apply_normalizer_without_production_promotion() -> None:
    pipeline = Path("training_core/pipeline.py").read_text(encoding="utf-8")
    model_training = Path("src/bioauth/ml/training.py").read_text(encoding="utf-8")
    normalizer = Path("hybrid_pro_metadata_normalization.py").read_text(encoding="utf-8")

    assert "normalize_hybrid_pro_artifact_metadata" in pipeline
    assert "normalize_hybrid_pro_artifact_metadata" in model_training
    assert "write_active_runtime_pointer" not in normalizer
    assert "approved_for_production" not in normalizer
    assert "production_ready'] = True" not in normalizer
    assert 'production_ready"] = True' not in normalizer
