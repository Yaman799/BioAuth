from __future__ import annotations

from typing import Any

import numpy as np

from hybrid_candidates.adapters import (
    CLASSIC_ADAPTER_IDS,
    SUPERVISED_ADAPTER_IDS,
    evaluate_catboost,
    evaluate_classic_candidate,
    evaluate_gmm,
    evaluate_lof,
    evaluate_supervised_candidate,
    evaluate_xgboost,
)
from hybrid_candidates.registry import get_candidate, validate_candidate_result


class FakeNoveltyLof:
    def decision_function(self, X: Any) -> np.ndarray:
        assert np.asarray(X).shape == (1, 2)
        return np.asarray([-0.8], dtype=float)


class FakeGaussianMixture:
    def score_samples(self, X: Any) -> np.ndarray:
        assert np.asarray(X).shape == (1, 2)
        return np.asarray([-0.72], dtype=float)


class UnsafeLofWithoutNoveltyInference:
    negative_outlier_factor_ = np.asarray([-1.0, -1.2], dtype=float)


class FakeBoostedClassifier:
    def __init__(self, intruder_probability: float) -> None:
        self.intruder_probability = intruder_probability

    def predict_proba(self, X: Any) -> np.ndarray:
        assert np.asarray(X).shape == (1, 3)
        return np.asarray([[1.0 - self.intruder_probability, self.intruder_probability]], dtype=float)


def _assert_candidate_result(result: dict[str, Any]) -> None:
    assert validate_candidate_result(result)["ok"] is True
    assert result["can_lock_alone"] is False
    assert result["latency_ms"] is None or result["latency_ms"] >= 0.0


def test_c4_registry_marks_optional_classical_candidates_as_offline_experimental() -> None:
    expected = {
        "classic_lof": "classic",
        "classic_gmm": "classic",
        "supervised_xgboost": "optional_classic",
        "supervised_catboost": "optional_classic",
    }
    for candidate_id, group in expected.items():
        candidate = get_candidate(candidate_id).to_dict()
        assert candidate["group"] == group
        assert candidate["status"] == "experimental"
        assert candidate["offline_allowed"] is True
        assert candidate["live_allowed"] is False
        assert candidate["can_lock_alone"] is False
        assert candidate["default_enabled"] is False
        assert candidate["can_vote_default"] is False


def test_lof_candidate_is_artifact_gated_and_uses_higher_risk_for_more_suspicious_scores() -> None:
    missing = evaluate_lof({"a": 1.0, "b": 2.0}, metadata={"feature_names": ["a", "b"]})
    _assert_candidate_result(missing)
    assert missing["available"] is False
    assert missing["reason"] == "missing_trained_artifact"
    assert missing["decision"] == "unavailable"
    assert missing["risk"] is None
    assert missing["can_vote"] is False

    unsafe = evaluate_lof(
        {"a": 1.0, "b": 2.0},
        artifact=UnsafeLofWithoutNoveltyInference(),
        metadata={"feature_names": ["a", "b"], "artifact_id": "sha256:lof-no-novelty"},
    )
    _assert_candidate_result(unsafe)
    assert unsafe["available"] is False
    assert unsafe["reason"] == "safe_inference_unavailable"
    assert unsafe["risk"] is None

    available = evaluate_lof(
        {"a": 1.0, "b": 2.0},
        artifact=FakeNoveltyLof(),
        metadata={"feature_names": ["a", "b"], "decision_threshold": 0.5, "artifact_id": "sha256:lof"},
    )
    _assert_candidate_result(available)
    assert available["available"] is True
    assert available["risk"] == 0.8
    assert available["decision"] == "intruder"
    assert available["can_vote"] is False
    assert available["can_lock_alone"] is False


def test_gmm_candidate_handles_missing_and_insufficient_training_data_safely() -> None:
    missing = evaluate_gmm([1.0, 2.0], metadata={"feature_names": ["a", "b"]})
    _assert_candidate_result(missing)
    assert missing["available"] is False
    assert missing["reason"] == "missing_trained_artifact"
    assert missing["risk"] is None

    insufficient = evaluate_gmm(
        [1.0, 2.0],
        artifact=FakeGaussianMixture(),
        metadata={"feature_names": ["a", "b"], "training_sample_count": 1, "n_components": 2, "artifact_id": "sha256:gmm"},
    )
    _assert_candidate_result(insufficient)
    assert insufficient["available"] is False
    assert insufficient["reason"] == "insufficient_training_data"
    assert insufficient["risk"] is None

    available = evaluate_gmm(
        [1.0, 2.0],
        artifact=FakeGaussianMixture(),
        metadata={"feature_names": ["a", "b"], "training_sample_count": 12, "n_components": 2, "decision_threshold": 0.5, "artifact_id": "sha256:gmm"},
    )
    _assert_candidate_result(available)
    assert available["available"] is True
    assert available["risk"] == 0.72
    assert available["decision"] == "intruder"
    assert available["can_vote"] is False


def test_xgboost_and_catboost_missing_optional_dependencies_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.supervised.optional_dependency_available", lambda name: False)
    for evaluator, candidate_id in ((evaluate_xgboost, "supervised_xgboost"), (evaluate_catboost, "supervised_catboost")):
        result = evaluator({"a": 1.0}, metadata={"feature_names": ["a"]})
        _assert_candidate_result(result)
        assert result["id"] == candidate_id
        assert result["available"] is False
        assert result["decision"] == "unavailable"
        assert result["reason"] == "dependency_missing"
        assert result["risk"] is None
        assert result["can_vote"] is False


def test_xgboost_and_catboost_use_unified_schema_when_optional_dependency_is_available(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.supervised.optional_dependency_available", lambda name: True)
    for evaluator, candidate_id, probability in (
        (evaluate_xgboost, "supervised_xgboost", 0.66),
        (evaluate_catboost, "supervised_catboost", 0.44),
    ):
        result = evaluator(
            {"a": 1.0, "b": 2.0, "c": 3.0},
            artifact=FakeBoostedClassifier(probability),
            metadata={"feature_names": ["a", "b", "c"], "classifier_threshold": 0.5, "artifact_id": f"sha256:{candidate_id}"},
        )
        _assert_candidate_result(result)
        assert result["id"] == candidate_id
        assert result["available"] is True
        assert result["trained_artifact_loaded"] is True
        assert result["risk"] == probability
        assert result["decision"] == ("intruder" if probability >= 0.5 else "genuine")
        assert result["can_vote"] is False
        assert result["can_lock_alone"] is False


def test_c4_all_expanded_candidate_ids_remain_non_locking() -> None:
    expanded_ids = {"classic_lof", "classic_gmm", "supervised_xgboost", "supervised_catboost"}
    assert expanded_ids.issubset(set(CLASSIC_ADAPTER_IDS) | set(SUPERVISED_ADAPTER_IDS))
    results = [evaluate_classic_candidate(candidate_id, {"a": 1.0}, metadata={"feature_names": ["a"]}) for candidate_id in CLASSIC_ADAPTER_IDS]
    results.extend(evaluate_supervised_candidate(candidate_id, {"a": 1.0}, metadata={"feature_names": ["a"]}) for candidate_id in SUPERVISED_ADAPTER_IDS)
    assert results
    assert all(validate_candidate_result(result)["ok"] for result in results)
    assert all(result["can_lock_alone"] is False for result in results)
    assert all(result["can_vote"] is False or result["available"] is True for result in results)
