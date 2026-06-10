from __future__ import annotations

from typing import Any

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from hybrid_candidates.adapters import (
    ONE_CLASS_DEEP_ADAPTER_IDS,
    evaluate_conv_autoencoder,
    evaluate_deep_svdd,
    evaluate_lstm_autoencoder,
    evaluate_mouse_autoencoder,
    evaluate_mouse_deep_svdd,
    evaluate_one_class_deep_candidate,
)
from hybrid_candidates.registry import get_candidate, validate_candidate_result

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None
pytestmark = pytest.mark.skipif(not TORCH_AVAILABLE, reason="PyTorch is required for C5 architecture forward-pass tests")


def _trained_artifact(*, svdd: bool = False) -> dict[str, Any]:
    artifact = {
        "state_dict": {"trained": True},
        "schema": {"layout": "NTF", "features": ["a", "b", "c"]},
        "threshold": 0.5,
        "training_metadata": {"owner_sessions": 8, "validated": True},
    }
    if svdd:
        artifact["center_vector"] = [0.0, 0.0]
    return artifact


def _assert_safe_unavailable(result: dict[str, Any], reason: str) -> None:
    assert validate_candidate_result(result)["ok"] is True
    assert result["available"] is False
    assert result["trained_artifact_loaded"] is False
    assert result["decision"] == "unavailable"
    assert result["risk"] is None
    assert result["can_vote"] is False
    assert result["can_lock_alone"] is False
    assert result["reason"] == reason


def test_c5_registry_marks_one_class_deep_candidates_as_offline_experimental() -> None:
    expected = {
        "oneclass_lstm_autoencoder": "one_class_deep",
        "oneclass_conv_autoencoder": "one_class_deep",
        "oneclass_deep_svdd": "one_class_deep",
        "mouse_autoencoder": "mouse",
        "mouse_deep_svdd": "mouse",
    }
    for candidate_id, group in expected.items():
        candidate = get_candidate(candidate_id).to_dict()
        assert candidate["group"] == group
        assert candidate["status"] == "experimental"
        assert candidate["offline_allowed"] is True
        assert candidate["live_allowed"] is False
        assert candidate["default_enabled"] is False
        assert candidate["can_vote_default"] is False
        assert candidate["can_lock_alone"] is False


def test_one_class_deep_model_architectures_import_and_forward_shapes() -> None:
    import torch
    from deep_sequence.models import (
        MouseAutoencoder,
        MouseDeepSvddNetwork,
        SequenceConvAutoencoder,
        SequenceDeepSvddNetwork,
        SequenceLstmAutoencoder,
        one_class_deep_metadata,
    )

    x = torch.randn(2, 6, 3)
    lstm = SequenceLstmAutoencoder(feature_dim=3, hidden_size=8, latent_size=4)
    conv = SequenceConvAutoencoder(feature_dim=3, channels=8, latent_channels=4)
    svdd = SequenceDeepSvddNetwork(feature_dim=3, hidden_size=8, embedding_dim=5)
    assert tuple(lstm(x).shape) == (2, 6, 3)
    assert tuple(conv(x).shape) == (2, 6, 3)
    assert tuple(svdd(x).shape) == (2, 5)

    mouse_x = torch.randn(2, 5, 9)
    mouse_autoencoder = MouseAutoencoder(channels=8, latent_channels=4)
    mouse_svdd = MouseDeepSvddNetwork(hidden_size=8, embedding_dim=6)
    assert tuple(mouse_autoencoder(mouse_x).shape) == (2, 5, 9)
    assert tuple(mouse_svdd(mouse_x).shape) == (2, 6)

    metadata = one_class_deep_metadata(
        architecture="lstm_autoencoder",
        input_modality="keyboard_mouse",
        feature_names=["a", "b", "c"],
        sequence_length=6,
    )
    assert metadata["artifact_required"] is True
    assert metadata["untrained_scores_valid"] is False
    assert metadata["can_lock_alone"] is False
    assert metadata["can_influence_device"] is False


def test_missing_artifacts_make_every_one_class_deep_candidate_unavailable() -> None:
    for candidate_id in ONE_CLASS_DEEP_ADAPTER_IDS:
        result = evaluate_one_class_deep_candidate(candidate_id, [[1.0, 2.0], [1.5, 2.5]])
        _assert_safe_unavailable(result, "missing_trained_artifact")


def test_loaded_artifact_without_predictor_never_reports_untrained_score() -> None:
    result = evaluate_lstm_autoencoder(
        [[1.0, 2.0, 3.0], [1.1, 2.1, 3.1]],
        artifact=_trained_artifact(),
        metadata={"artifact_id": "sha256:lstm", "sequence_threshold": 0.5},
    )
    _assert_safe_unavailable(result, "artifact_loaded_no_inference_adapter")


def test_artifact_metadata_requirements_fail_closed() -> None:
    missing_weights = evaluate_conv_autoencoder(
        [[1.0, 2.0], [1.1, 2.1]],
        artifact={"schema": {"layout": "NTF"}, "threshold": 0.5, "training_metadata": {"ok": True}},
    )
    _assert_safe_unavailable(missing_weights, "missing_model_weights")

    missing_center = evaluate_deep_svdd(
        [[1.0, 2.0], [1.1, 2.1]],
        artifact=_trained_artifact(svdd=False),
    )
    _assert_safe_unavailable(missing_center, "missing_center_vector")


def test_one_class_deep_adapter_accepts_explicit_trained_artifact_and_predictor_only() -> None:
    calls: list[tuple[Any, tuple[int, ...]]] = []

    def predictor(artifact: Any, tensor: np.ndarray, metadata: dict[str, Any] | None) -> float:
        calls.append((artifact, tuple(tensor.shape)))
        return 0.64

    result = evaluate_mouse_deep_svdd(
        [[0.1, 0.2, 0.3], [0.2, 0.3, 0.4], [0.3, 0.4, 0.5]],
        artifact=_trained_artifact(svdd=True),
        metadata={"artifact_id": "sha256:mouse-svdd", "sequence_threshold": 0.5},
        predict_fn=predictor,
    )
    assert validate_candidate_result(result)["ok"] is True
    assert calls == [(_trained_artifact(svdd=True), (1, 3, 3))]
    assert result["available"] is True
    assert result["trained_artifact_loaded"] is True
    assert result["risk"] == 0.64
    assert result["decision"] == "intruder"
    assert result["can_vote"] is False
    assert result["can_lock_alone"] is False


def test_pytorch_unavailable_behavior_returns_dependency_missing(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.one_class_deep.optional_dependency_available", lambda name: False)
    result = evaluate_mouse_autoencoder(
        [[1.0, 2.0], [1.1, 2.1]],
        artifact=_trained_artifact(),
        metadata={"artifact_id": "sha256:mouse-ae", "sequence_threshold": 0.5},
        predict_fn=lambda artifact, tensor, metadata: 0.1,
    )
    _assert_safe_unavailable(result, "dependency_missing")


def test_one_class_deep_adapters_add_no_runtime_or_presentation_influence_path() -> None:
    source = Path("hybrid_candidates/adapters/one_class_deep.py").read_text(encoding="utf-8")
    forbidden_tokens = [
        "LockWorkStation",
        "lock_screen",
        "runHybridDirectTest",
        "approveProductionModelSwitch",
        "production_pointer",
        "FaceConfirmation",
        "atomic_write",
        "save_model_hash",
        "save_classifier_sidecar",
        "train_model",
        "QtQuick",
    ]
    for token in forbidden_tokens:
        assert token not in source


def test_all_one_class_deep_candidates_remain_non_locking() -> None:
    results = [evaluate_one_class_deep_candidate(candidate_id, [[1.0], [2.0]]) for candidate_id in ONE_CLASS_DEEP_ADAPTER_IDS]
    assert results
    assert all(validate_candidate_result(result)["ok"] for result in results)
    assert all(result["can_lock_alone"] is False for result in results)
    assert all(result["can_vote"] is False for result in results)
