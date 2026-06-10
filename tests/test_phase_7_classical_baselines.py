from __future__ import annotations

import numpy as np

from bioauth_model.classical_baselines import (
    BASELINE_SCORE_DIRECTION,
    CLASSICAL_BASELINE_SCHEMA_VERSION,
    NNMahalanobisVerifier,
    OneClassSVMBaseline,
    ScaledManhattanVerifier,
    build_classical_baselines,
    evaluate_classical_baselines,
)
from evaluation_core.metrics import LABEL_GENUINE, LABEL_INTRUDER
from evaluation_core.reporting import _build_summary_markdown


def _owner_train() -> np.ndarray:
    return np.asarray([[1.0, 1.0, 2.0], [1.1, 0.9, 2.1], [0.9, 1.1, 1.9], [1.05, 1.0, 2.05], [0.95, 1.0, 1.95]], dtype=float)


def test_scaled_manhattan_score_direction_and_metadata_are_safe() -> None:
    verifier = ScaledManhattanVerifier().fit(_owner_train())
    owner_score = verifier.score_one([1.0, 1.0, 2.0]).risk_score
    intruder_score = verifier.score_one([4.0, 4.0, 8.0]).risk_score
    assert owner_score is not None and intruder_score is not None
    assert intruder_score > owner_score
    meta = verifier.metadata(feature_names=["a", "b", "c"], feature_schema_version="test-schema")
    assert meta["schema_version"] == CLASSICAL_BASELINE_SCHEMA_VERSION
    assert meta["baseline_type"] == "scaled_manhattan"
    assert meta["score_direction"] == BASELINE_SCORE_DIRECTION
    assert meta["can_lock_alone"] is False
    assert meta["runtime_authoritative"] is False


def test_nn_mahalanobis_regularizes_singular_covariance() -> None:
    X = np.asarray([[1.0, 2.0, 3.0], [1.1, 2.1, 3.2], [0.9, 1.9, 2.8], [1.05, 2.05, 3.1]], dtype=float)
    verifier = NNMahalanobisVerifier(regularization=1e-4).fit(X)
    assert verifier.metadata()["available"] is True
    score = verifier.score_one([1.0, 2.0, 3.0]).risk_score
    far_score = verifier.score_one([3.0, 6.0, 9.0]).risk_score
    assert score is not None and np.isfinite(score)
    assert far_score is not None and np.isfinite(far_score)
    assert far_score > score
    assert verifier.metadata()["can_lock_alone"] is False


def test_one_class_svm_abstains_on_too_little_data() -> None:
    verifier = OneClassSVMBaseline(min_samples=5).fit(np.asarray([[1.0, 2.0], [1.1, 2.1]], dtype=float))
    assert verifier.metadata()["available"] is False
    assert verifier.score_one([1.0, 2.0]).to_dict()["decision"] == "abstain"
    assert verifier.score_one([1.0, 2.0]).to_dict()["can_lock_alone"] is False


def test_one_class_svm_fit_path_is_available_when_dependency_exists() -> None:
    verifier = OneClassSVMBaseline(min_samples=5, nu=0.1).fit(_owner_train())
    meta = verifier.metadata()
    if not meta["available"]:
        assert meta["reason"] in {"sklearn_unavailable", "insufficient_genuine_samples"}
        return
    owner_score = verifier.score_one([1.0, 1.0, 2.0]).risk_score
    intruder_score = verifier.score_one([5.0, 5.0, 9.0]).risk_score
    assert owner_score is not None and intruder_score is not None
    assert intruder_score > owner_score
    assert meta["score_direction"] == "higher_score_more_suspicious"
    assert meta["can_lock_alone"] is False


def test_build_classical_baselines_metadata_contains_all_non_authoritative_baselines() -> None:
    payload = build_classical_baselines(_owner_train(), feature_names=["a", "b", "c"], feature_schema_version="schema-v1")
    assert payload["schema_version"] == CLASSICAL_BASELINE_SCHEMA_VERSION
    assert payload["score_direction"] == "higher_score_more_suspicious"
    assert payload["can_lock_alone"] is False
    assert payload["runtime_authoritative"] is False
    assert sorted(payload["baselines"].keys()) == ["nn_mahalanobis", "one_class_svm", "scaled_manhattan"]
    for baseline in payload["baselines"].values():
        assert baseline["can_lock_alone"] is False
        assert baseline["runtime_authoritative"] is False
        assert baseline["feature_schema_version"] == "schema-v1"


def test_evaluate_classical_baselines_uses_phase_2_metric_semantics() -> None:
    train = _owner_train()
    X_eval = np.asarray([[1.0, 1.0, 2.0], [1.1, 1.0, 2.1], [4.0, 4.0, 8.0], [5.0, 5.0, 9.0]], dtype=float)
    y_true = [LABEL_GENUINE, LABEL_GENUINE, LABEL_INTRUDER, LABEL_INTRUDER]
    report = evaluate_classical_baselines(train, X_eval, y_true, target_far=0.0)
    assert report["can_lock_alone"] is False
    assert report["runtime_authoritative"] is False
    assert report["score_direction"] == "higher_score_more_suspicious"
    for name in ("scaled_manhattan", "nn_mahalanobis"):
        item = report["baselines"][name]
        assert item["available"] is True
        assert item["can_lock_alone"] is False
        assert item["metrics"]["label_convention"]["score_direction"] == "higher_score_more_suspicious"
        assert item["metrics"]["sample_counts"] == {"total": 4, "genuine": 2, "intruder": 2}
        assert item["metrics"]["far"] == 0.0
        assert item["metrics"]["frr"] == 0.0
        assert item["metrics"]["eer"] == 0.0


def test_evaluation_summary_mentions_classical_baselines_without_claiming_lock_authority() -> None:
    report = {"generated_at": "2026-05-04", "primary_evaluation": "candidate_bundle", "evaluations": {"candidate_bundle": {"metrics": {}}}, "classical_baselines": build_classical_baselines(_owner_train())}
    summary = _build_summary_markdown(report)
    assert "Classical baselines:" in summary
    assert "scaled_manhattan" in summary
    assert "Classical baselines can lock alone: False" in summary
