from __future__ import annotations

import numpy as np

from evaluation_core.metrics import (
    LABEL_CONVENTION,
    LABEL_GENUINE,
    LABEL_INTRUDER,
    _binary_metrics,
    _false_accept_false_reject_rates,
    calibrate_thresholds,
    compute_eer,
    error_rates_at_threshold,
)
from training_core.supervised import _evaluate_supervised_candidate, _false_accept_false_reject_rates as supervised_far_frr


class FixedProbabilityCandidate:
    def __init__(self, intruder_probabilities: list[float]):
        self._intruder_probabilities = np.asarray(intruder_probabilities, dtype=float)

    def predict_proba(self, X):
        probs = self._intruder_probabilities[: len(X)]
        return np.column_stack([1.0 - probs, probs])


def test_phase_2_label_convention_is_explicit() -> None:
    assert LABEL_GENUINE == 0
    assert LABEL_INTRUDER == 1
    assert LABEL_CONVENTION["score_direction"] == "higher_score_more_suspicious"


def test_far_frr_confusion_matrix_semantics_are_not_inverted() -> None:
    # labels: [genuine accepted, genuine rejected, intruder accepted, intruder rejected]
    # confusion: TN=1, FP=1, FN=1, TP=1
    y_true = [LABEL_GENUINE, LABEL_GENUINE, LABEL_INTRUDER, LABEL_INTRUDER]
    y_pred = [LABEL_GENUINE, LABEL_INTRUDER, LABEL_GENUINE, LABEL_INTRUDER]
    metrics = _binary_metrics(y_true, y_pred, [0.1, 0.9, 0.2, 0.8])
    assert metrics["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert metrics["far"] == 0.5  # intruder accepted / all intruders = FN / (FN + TP)
    assert metrics["frr"] == 0.5  # genuine rejected / all genuine = FP / (FP + TN)


def test_shared_far_frr_helper_matches_training_supervised_wrapper() -> None:
    counts = {"tn": 5, "fp": 4, "fn": 2, "tp": 8}
    assert _false_accept_false_reject_rates(**counts) == (0.2, 4 / 9)
    assert supervised_far_frr(**counts) == (0.2, 4 / 9)


def test_eer_threshold_computation_from_deterministic_scores() -> None:
    y_true = [LABEL_GENUINE, LABEL_GENUINE, LABEL_INTRUDER, LABEL_INTRUDER]
    scores = [0.1, 0.3, 0.7, 0.9]
    eer = compute_eer(y_true, scores)
    assert eer["available"] is True
    assert eer["eer"] == 0.0
    assert eer["far"] == 0.0
    assert eer["frr"] == 0.0
    assert 0.3 < eer["threshold"] <= 0.7


def test_threshold_selection_at_min_eer_and_target_far() -> None:
    y_true = [LABEL_GENUINE, LABEL_GENUINE, LABEL_INTRUDER, LABEL_INTRUDER]
    scores = [0.1, 0.8, 0.4, 0.9]
    calibrated = calibrate_thresholds(y_true, scores, target_far=0.0, user_id="owner-1")
    assert calibrated["available"] is True
    assert calibrated["method"] == "min_eer_threshold"
    assert calibrated["global_threshold"] == calibrated["eer"]["threshold"]
    assert calibrated["per_user_thresholds"]["owner-1"] == calibrated["eer"]["threshold"]
    assert calibrated["target_far"]["available"] is True
    assert calibrated["target_far"]["far"] == 0.0


def test_error_rates_at_threshold_uses_higher_score_as_more_suspicious() -> None:
    y_true = [LABEL_GENUINE, LABEL_GENUINE, LABEL_INTRUDER, LABEL_INTRUDER]
    scores = [0.1, 0.8, 0.4, 0.9]
    rates = error_rates_at_threshold(y_true, scores, threshold=0.5)
    assert rates["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert rates["far"] == 0.5
    assert rates["frr"] == 0.5


def test_supervised_candidate_metrics_use_shared_far_frr_semantics() -> None:
    candidate = FixedProbabilityCandidate([0.1, 0.8, 0.4, 0.9])
    X_val = np.zeros((4, 2), dtype=float)
    y_val = np.asarray([LABEL_GENUINE, LABEL_GENUINE, LABEL_INTRUDER, LABEL_INTRUDER], dtype=int)
    metrics = _evaluate_supervised_candidate(candidate, X_val, y_val)
    assert metrics["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert metrics["far"] == 0.5
    assert metrics["frr"] == 0.5
    assert metrics["eer"] is not None
    assert metrics["eer_threshold"] is not None
    assert metrics["sample_counts"] == {"total": 4, "genuine": 2, "intruder": 2}
