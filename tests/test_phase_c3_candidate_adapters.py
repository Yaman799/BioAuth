from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hybrid_candidates.adapters import (
    CLASSIC_ADAPTER_IDS,
    DEEP_SEQUENCE_ADAPTER_IDS,
    SUPERVISED_ADAPTER_IDS,
    evaluate_classic_candidate,
    evaluate_deep_sequence_candidate,
    evaluate_isolation_forest,
    evaluate_keyboard_bigru_cnn_attention,
    evaluate_lightgbm,
    evaluate_mouse_resnet_gru,
    evaluate_random_forest,
    evaluate_supervised_candidate,
)
from hybrid_candidates.registry import validate_candidate_result
from hybrid_candidates.schema import CandidateResult


class FakeIsolationForest:
    def decision_function(self, X: Any) -> np.ndarray:
        assert np.asarray(X).shape == (1, 2)
        return np.asarray([-0.25], dtype=float)


class FakeRandomForest:
    def predict_proba(self, X: Any) -> np.ndarray:
        assert np.asarray(X).shape == (1, 2)
        return np.asarray([[0.12, 0.88]], dtype=float)


class FakeScoreOneArtifact:
    def score_one(self, row: Any) -> Any:
        class Result:
            def to_dict(self) -> dict[str, Any]:
                return {"risk_score": 0.2, "decision": "genuine"}

        assert np.asarray(row).shape == (2,)
        return Result()


def _assert_safe_result(result: dict[str, Any]) -> None:
    assert validate_candidate_result(result)["ok"] is True
    assert result["can_lock_alone"] is False
    assert result["can_vote"] is False or result["available"] is True
    assert result["latency_ms"] is None or result["latency_ms"] >= 0.0


def test_candidate_result_schema_accepts_c3_unavailable_decision() -> None:
    payload = CandidateResult(
        id="classic_isolation_forest",
        display_name="Classic Isolation Forest",
        group="classic",
        available=False,
        trained_artifact_loaded=False,
        risk=None,
        decision="unavailable",
        can_vote=False,
        can_lock_alone=False,
        reason="missing_trained_artifact",
        latency_ms=0.1,
        artifact_id="",
        threshold_source="not_available",
        errors=[],
    ).to_dict()
    assert payload["decision"] == "unavailable"
    assert validate_candidate_result(payload)["ok"] is True


def test_classic_adapters_return_unavailable_when_artifact_missing() -> None:
    for candidate_id in CLASSIC_ADAPTER_IDS:
        result = evaluate_classic_candidate(candidate_id, {"a": 1.0}, metadata={"feature_names": ["a"]})
        _assert_safe_result(result)
        assert result["available"] is False
        assert result["trained_artifact_loaded"] is False
        assert result["decision"] == "unavailable"
        assert result["reason"] == "missing_trained_artifact"
        assert result["risk"] is None
        assert result["can_vote"] is False


def test_classic_isolation_forest_adapter_wraps_existing_estimator_without_lock_authority() -> None:
    result = evaluate_isolation_forest(
        {"a": 1.0, "b": 2.0},
        artifact=FakeIsolationForest(),
        metadata={"feature_names": ["a", "b"], "decision_threshold": 0.5, "artifact_id": "sha256:test-iforest"},
    )
    _assert_safe_result(result)
    assert result["id"] == "classic_isolation_forest"
    assert result["available"] is True
    assert result["trained_artifact_loaded"] is True
    assert result["risk"] == 0.25
    assert result["decision"] == "genuine"
    assert result["can_vote"] is True
    assert result["can_lock_alone"] is False


def test_classic_score_one_artifacts_are_wrapped_in_candidate_schema() -> None:
    result = evaluate_classic_candidate(
        "classic_scaled_manhattan",
        [1.0, 2.0],
        artifact=FakeScoreOneArtifact(),
        metadata={"feature_names": ["a", "b"], "artifact_id": "sha256:test-scaled"},
    )
    _assert_safe_result(result)
    assert result["available"] is True
    assert result["decision"] == "genuine"
    assert result["risk"] == 0.2
    assert result["can_vote"] is False
    assert result["can_lock_alone"] is False


def test_supervised_adapters_missing_artifacts_and_optional_dependencies_fail_closed(monkeypatch) -> None:
    missing_rf = evaluate_random_forest({"a": 1.0}, metadata={"feature_names": ["a"]})
    _assert_safe_result(missing_rf)
    assert missing_rf["available"] is False
    assert missing_rf["decision"] == "unavailable"
    assert missing_rf["reason"] == "missing_trained_artifact"

    monkeypatch.setattr("hybrid_candidates.adapters.supervised.optional_dependency_available", lambda name: False)
    missing_lgbm = evaluate_lightgbm({"a": 1.0}, metadata={"feature_names": ["a"]})
    _assert_safe_result(missing_lgbm)
    assert missing_lgbm["available"] is False
    assert missing_lgbm["decision"] == "unavailable"
    assert missing_lgbm["reason"] == "dependency_missing"


def test_supervised_random_forest_adapter_wraps_classifier_probability() -> None:
    result = evaluate_random_forest(
        {"a": 1.0, "b": 2.0},
        artifact=FakeRandomForest(),
        metadata={"feature_names": ["a", "b"], "classifier_threshold": 0.5, "artifact_id": "sha256:test-rf"},
    )
    _assert_safe_result(result)
    assert result["available"] is True
    assert result["risk"] == 0.88
    assert result["decision"] == "intruder"
    assert result["can_vote"] is True
    assert result["can_lock_alone"] is False


def test_deep_sequence_adapters_are_artifact_gated_and_never_random_score() -> None:
    for candidate_id in DEEP_SEQUENCE_ADAPTER_IDS:
        result = evaluate_deep_sequence_candidate(candidate_id, [[1.0, 2.0], [1.5, 2.5]])
        _assert_safe_result(result)
        assert result["available"] is False
        assert result["decision"] == "unavailable"
        assert result["reason"] == "missing_trained_artifact"
        assert result["risk"] is None
        assert result["can_vote"] is False
        assert result["can_lock_alone"] is False

    loaded_without_predictor = evaluate_keyboard_bigru_cnn_attention(
        [[1.0, 2.0], [1.5, 2.5]],
        artifact={"state_dict": "trained-placeholder"},
        metadata={"sequence_threshold": 0.5, "artifact_id": "sha256:test-deep"},
    )
    assert loaded_without_predictor["available"] is False
    assert loaded_without_predictor["decision"] == "unavailable"
    assert loaded_without_predictor["reason"] == "artifact_loaded_no_inference_adapter"


def test_deep_sequence_adapter_accepts_explicit_artifact_and_predictor_only() -> None:
    calls: list[tuple[Any, tuple[int, ...]]] = []

    def predictor(artifact: Any, tensor: np.ndarray, metadata: dict[str, Any] | None) -> float:
        calls.append((artifact, tuple(tensor.shape)))
        return 0.73

    result = evaluate_mouse_resnet_gru(
        [[0.1, 0.2], [0.2, 0.3], [0.3, 0.4]],
        artifact={"state_dict": "trained-placeholder"},
        metadata={"sequence_threshold": 0.5, "artifact_id": "sha256:test-mouse"},
        predict_fn=predictor,
    )
    _assert_safe_result(result)
    assert calls == [({"state_dict": "trained-placeholder"}, (1, 3, 2))]
    assert result["available"] is True
    assert result["risk"] == 0.73
    assert result["decision"] == "intruder"
    assert result["can_vote"] is False
    assert result["can_lock_alone"] is False


def test_adapter_modules_add_no_runtime_or_presentation_influence_path() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(Path("hybrid_candidates/adapters").glob("*.py")))
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
        "KeyboardBiGruCnnAttention(",
        "MouseResNetGruVerifier(",
        "SequenceCnnLstm(",
        "QtQuick",
    ]
    for token in forbidden_tokens:
        assert token not in source


def test_all_adapter_ids_remain_non_locking() -> None:
    results = [evaluate_classic_candidate(candidate_id, {"a": 1.0}, metadata={"feature_names": ["a"]}) for candidate_id in CLASSIC_ADAPTER_IDS]
    results.extend(evaluate_deep_sequence_candidate(candidate_id, [[1.0], [2.0]]) for candidate_id in DEEP_SEQUENCE_ADAPTER_IDS)
    results.extend(evaluate_supervised_candidate(candidate_id, {"a": 1.0}, metadata={"feature_names": ["a"]}) for candidate_id in SUPERVISED_ADAPTER_IDS)
    assert results
    assert all(result["can_lock_alone"] is False for result in results)
    assert all(validate_candidate_result(result)["ok"] for result in results)
