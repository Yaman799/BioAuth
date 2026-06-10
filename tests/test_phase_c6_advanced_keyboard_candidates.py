from __future__ import annotations

from pathlib import Path
from typing import Any

import importlib.util

import numpy as np
import pytest

from hybrid_candidates.adapters import KEYBOARD_ADVANCED_ADAPTER_IDS, evaluate_advanced_keyboard_candidate, evaluate_keyboard_siamese_triplet, evaluate_keyboard_type2branch, evaluate_keyboard_typeformer
from hybrid_candidates.registry import get_candidate, validate_candidate_result

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


def _trained_keyboard_artifact() -> dict[str, Any]:
    return {"state_dict": {"trained": True}, "schema": {"layout": "NTF", "features": ["hold", "flight", "rate"]}, "threshold": 0.5, "training_metadata": {"owner_sessions": 8, "validated": True}, "reference_embedding": [0.1, 0.2, 0.3]}


def _assert_safe_unavailable(result: dict[str, Any], reason: str) -> None:
    assert validate_candidate_result(result)["ok"] is True
    assert result["available"] is False
    assert result["trained_artifact_loaded"] is False
    assert result["decision"] == "unavailable"
    assert result["risk"] is None
    assert result["can_vote"] is False
    assert result["can_lock_alone"] is False
    assert result["reason"] == reason


def test_c6_registry_marks_advanced_keyboard_as_offline_artifact_gated() -> None:
    expected = {"keyboard_type2branch": "Type2Branch-inspired", "keyboard_typeformer": "TypeFormer-inspired", "keyboard_siamese_triplet": "Siamese/Triplet"}
    assert set(KEYBOARD_ADVANCED_ADAPTER_IDS) == set(expected)
    for candidate_id, display_token in expected.items():
        candidate = get_candidate(candidate_id).to_dict()
        assert display_token in candidate["display_name"]
        assert candidate["group"] == "keyboard"
        assert candidate["modality"] == "keyboard"
        assert candidate["status"] == "experimental"
        assert candidate["offline_allowed"] is True
        assert candidate["live_allowed"] is False
        assert candidate["default_enabled"] is False
        assert candidate["can_vote_default"] is False
        assert candidate["can_lock_alone"] is False
        assert candidate["requires_artifact"] is True
        assert candidate["requires_training"] is True
        assert candidate["requires_threshold"] is True


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="PyTorch is required for C6 architecture forward-pass tests")
def test_advanced_keyboard_architectures_import_and_forward_shapes() -> None:
    import torch
    from deep_sequence.models import KeyboardSiameseTripletVerifier, KeyboardType2BranchInspired, KeyboardTypeFormerInspired, advanced_keyboard_metadata

    x = torch.randn(2, 10, 3)
    type2 = KeyboardType2BranchInspired(feature_dim=3, cnn_channels=8, gru_hidden_size=8, embedding_dim=6)
    typeformer = KeyboardTypeFormerInspired(feature_dim=3, model_dim=8, num_heads=2, num_layers=1, embedding_dim=5, min_free_text_length=8)
    siamese = KeyboardSiameseTripletVerifier(feature_dim=3, hidden_size=8, embedding_dim=7)
    assert tuple(type2(x).shape) == (2, 6)
    assert tuple(typeformer(x).shape) == (2, 5)
    assert tuple(siamese(x).shape) == (2, 7)
    assert tuple(siamese.pair_distance(x, x).shape) == (2,)
    positive, negative = siamese.triplet_distances(x, x, x)
    assert tuple(positive.shape) == (2,)
    assert tuple(negative.shape) == (2,)
    metadata = advanced_keyboard_metadata(architecture="typeformer_inspired", feature_names=["hold", "flight", "rate"], sequence_length=10, min_free_text_length=8)
    assert metadata["schema_version"] == "advanced-keyboard-candidate-metadata-v1"
    assert metadata["artifact_required"] is True
    assert metadata["reference_template_required"] is True
    assert metadata["untrained_scores_valid"] is False
    assert metadata["can_lock_alone"] is False
    assert metadata["can_influence_device"] is False


def test_missing_artifacts_make_advanced_keyboard_candidates_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.keyboard_advanced.optional_dependency_available", lambda name: True)
    for candidate_id in KEYBOARD_ADVANCED_ADAPTER_IDS:
        sample = [[0.1, 0.2, 0.3] for _ in range(10)]
        result = evaluate_advanced_keyboard_candidate(candidate_id, sample, metadata={"min_free_text_length": 8})
        _assert_safe_unavailable(result, "missing_trained_artifact")


def test_typeformer_short_free_text_is_diagnostics_only(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.keyboard_advanced.optional_dependency_available", lambda name: True)
    result = evaluate_keyboard_typeformer([[0.1, 0.2, 0.3], [0.2, 0.3, 0.4]], artifact=_trained_keyboard_artifact(), metadata={"artifact_id": "sha256:typeformer", "sequence_threshold": 0.5, "min_free_text_length": 8}, predict_fn=lambda artifact, tensor, metadata: 0.1)
    _assert_safe_unavailable(result, "insufficient_free_text_data")


def test_artifact_requirements_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.keyboard_advanced.optional_dependency_available", lambda name: True)
    missing_reference = dict(_trained_keyboard_artifact()); missing_reference.pop("reference_embedding")
    result = evaluate_keyboard_siamese_triplet([[0.1, 0.2], [0.2, 0.3], [0.3, 0.4]], artifact=missing_reference, metadata={"artifact_id": "sha256:siamese"}, predict_fn=lambda artifact, tensor, metadata: 0.2)
    _assert_safe_unavailable(result, "missing_reference_template")
    missing_threshold = dict(_trained_keyboard_artifact()); missing_threshold.pop("threshold")
    result = evaluate_keyboard_type2branch([[0.1, 0.2], [0.2, 0.3], [0.3, 0.4]], artifact=missing_threshold, metadata={"artifact_id": "sha256:type2"}, predict_fn=lambda artifact, tensor, metadata: 0.2)
    _assert_safe_unavailable(result, "missing_artifact_threshold")


def test_loaded_artifact_without_predictor_never_reports_untrained_score(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.keyboard_advanced.optional_dependency_available", lambda name: True)
    result = evaluate_keyboard_type2branch([[0.1, 0.2, 0.3], [0.2, 0.3, 0.4], [0.3, 0.4, 0.5]], artifact=_trained_keyboard_artifact(), metadata={"artifact_id": "sha256:type2", "sequence_threshold": 0.5})
    _assert_safe_unavailable(result, "artifact_loaded_no_inference_adapter")


def test_advanced_keyboard_adapter_accepts_explicit_trained_artifact_and_predictor_only(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.keyboard_advanced.optional_dependency_available", lambda name: True)
    calls: list[tuple[Any, tuple[int, ...]]] = []
    def predictor(artifact: Any, tensor: np.ndarray, metadata: dict[str, Any] | None) -> float:
        calls.append((artifact, tuple(tensor.shape))); return 0.61
    sample = [[0.1, 0.2, 0.3] for _ in range(10)]
    result = evaluate_keyboard_typeformer(sample, artifact=_trained_keyboard_artifact(), metadata={"artifact_id": "sha256:typeformer", "sequence_threshold": 0.5, "min_free_text_length": 8}, predict_fn=predictor)
    assert validate_candidate_result(result)["ok"] is True
    assert calls == [(_trained_keyboard_artifact(), (1, 10, 3))]
    assert result["available"] is True
    assert result["trained_artifact_loaded"] is True
    assert result["risk"] == 0.61
    assert result["decision"] == "intruder"
    assert result["can_vote"] is False
    assert result["can_lock_alone"] is False


def test_pytorch_unavailable_behavior_returns_dependency_missing(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.keyboard_advanced.optional_dependency_available", lambda name: False)
    result = evaluate_keyboard_siamese_triplet([[0.1, 0.2], [0.2, 0.3], [0.3, 0.4]], artifact=_trained_keyboard_artifact(), metadata={"artifact_id": "sha256:siamese", "sequence_threshold": 0.5}, predict_fn=lambda artifact, tensor, metadata: 0.1)
    _assert_safe_unavailable(result, "dependency_missing")


def test_advanced_keyboard_adapters_add_no_runtime_or_presentation_influence_path() -> None:
    source = Path("hybrid_candidates/adapters/keyboard_advanced.py").read_text(encoding="utf-8")
    forbidden_tokens = ["LockWorkStation", "lock_screen", "runHybridDirectTest", "approveProductionModelSwitch", "production_pointer", "FaceConfirmation", "atomic_write", "save_model_hash", "save_classifier_sidecar", "train_model", "KeyboardType2BranchInspired(", "KeyboardTypeFormerInspired(", "KeyboardSiameseTripletVerifier(", "QtQuick"]
    for token in forbidden_tokens:
        assert token not in source


def test_all_advanced_keyboard_candidates_remain_non_locking(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.keyboard_advanced.optional_dependency_available", lambda name: True)
    results = [evaluate_advanced_keyboard_candidate(candidate_id, [[0.1], [0.2], [0.3], [0.4], [0.5], [0.6], [0.7], [0.8]]) for candidate_id in KEYBOARD_ADVANCED_ADAPTER_IDS]
    assert results
    assert all(validate_candidate_result(result)["ok"] for result in results)
    assert all(result["can_lock_alone"] is False for result in results)
    assert all(result["can_vote"] is False for result in results)
