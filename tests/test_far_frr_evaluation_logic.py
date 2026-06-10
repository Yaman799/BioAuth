from __future__ import annotations

from model_evaluation import _false_accept_false_reject_rates, _predicted_intruder
from model_policy import evaluate_model_policy


def test_predicted_intruder_ignores_non_decision_status_for_legitimate_final() -> None:
    assert _predicted_intruder({"final": "legitimate", "status": "transitioning"}) == 0
    assert _predicted_intruder({"final": "unknown", "status": "insufficient_windows"}) == 0
    assert _predicted_intruder({"final": "", "status": "prediction_failed"}) == 0



def test_predicted_intruder_tracks_explicit_intruder_like_decisions() -> None:
    for final_value in ("suspicious", "intruder", "rejected", "unauthorized"):
        assert _predicted_intruder({"final": final_value, "status": "ok"}) == 1



def test_false_accept_false_reject_rates_match_project_label_convention() -> None:
    far, frr = _false_accept_false_reject_rates(tn=5, fp=4, fn=0, tp=23)
    assert far == 0.0
    assert frr == 4 / 9



def test_policy_rejection_points_to_frr_when_far_is_clean() -> None:
    decision = evaluate_model_policy(
        {
            "primary_evaluation": "candidate_bundle",
            "evaluations": {
                "candidate_bundle": {
                    "metrics": {
                        "session_count": 32,
                        "legitimate_session_count": 9,
                        "intruder_session_count": 23,
                        "auc": 0.942,
                        "f1": 0.92,
                        "precision": 0.852,
                        "recall": 1.0,
                        "far": 0.0,
                        "frr": 4 / 9,
                    }
                }
            },
        }
    )
    assert decision["model_status"] == "rejected"
    assert "FRR" in decision["approval_reason"]
    assert "FAR" not in decision["approval_reason"]
