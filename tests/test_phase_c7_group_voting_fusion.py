from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hybrid_candidates.fusion import (
    FUSION_ADAPTER_IDS,
    LEARNED_FUSION_ADAPTER_IDS,
    evaluate_calibrated_stacking,
    evaluate_fusion_candidate,
    evaluate_logistic_stacking,
    evaluate_rule_based_fusion,
)
from hybrid_candidates.group_voting import (
    VOTING_GROUPS,
    build_group_votes,
    build_offline_group_voting_report,
    offline_fusion_state_from_group_votes,
)
from hybrid_candidates.registry import get_candidate, validate_candidate_result
from hybrid_candidates.schema import CandidateResult


def _result(candidate_id: str, group: str, risk: float | None, decision: str, *, can_vote: bool = True, available: bool = True) -> dict[str, Any]:
    return CandidateResult(
        id=candidate_id,
        display_name=candidate_id.replace("_", " ").title(),
        group=group,
        available=available,
        trained_artifact_loaded=available,
        risk=risk,
        decision=decision,
        can_vote=can_vote,
        can_lock_alone=False,
        reason="test",
        latency_ms=1.0,
        artifact_id="sha256:test" if available else "",
        threshold_source="test" if available else "not_available",
        errors=[],
    ).to_dict()


def _intruder(candidate_id: str, group: str, risk: float = 0.9) -> dict[str, Any]:
    return _result(candidate_id, group, risk, "intruder")


def _genuine(candidate_id: str, group: str, risk: float = 0.1) -> dict[str, Any]:
    return _result(candidate_id, group, risk, "genuine")


def test_c7_registry_marks_learned_fusion_as_offline_artifact_gated() -> None:
    assert set(FUSION_ADAPTER_IDS) == {"fusion_rule_based", "fusion_logistic_stacking", "fusion_calibrated_stacking"}
    assert set(LEARNED_FUSION_ADAPTER_IDS) == {"fusion_logistic_stacking", "fusion_calibrated_stacking"}
    for candidate_id in LEARNED_FUSION_ADAPTER_IDS:
        candidate = get_candidate(candidate_id).to_dict()
        assert candidate["group"] == "fusion"
        assert candidate["status"] == "experimental"
        assert candidate["offline_allowed"] is True
        assert candidate["live_allowed"] is False
        assert candidate["default_enabled"] is False
        assert candidate["can_vote_default"] is False
        assert candidate["can_lock_alone"] is False
        assert candidate["requires_artifact"] is True
        assert candidate["requires_training"] is True
        assert candidate["requires_threshold"] is True


def test_same_keyboard_models_count_as_one_independent_group_vote() -> None:
    results = [
        _intruder("keyboard_bigru_cnn_attention", "keyboard", 0.86),
        _intruder("keyboard_type2branch", "keyboard", 0.91),
        _intruder("keyboard_typeformer", "keyboard", 0.77),
        _genuine("mouse_resnet_gru", "mouse", 0.12),
    ]
    votes = build_group_votes(results)
    summary = {vote["group"]: vote for vote in votes if vote["can_vote"]}
    assert set(summary) == {"keyboard", "mouse"}
    assert summary["keyboard"]["decision"] == "intruder"
    assert summary["keyboard"]["selected_candidate_id"] == "keyboard_type2branch"
    assert summary["keyboard"]["candidate_ids"] == ["keyboard_bigru_cnn_attention", "keyboard_type2branch", "keyboard_typeformer"]
    state = offline_fusion_state_from_group_votes(votes)
    assert state["intruder_group_count"] == 1
    assert state["offline_state"] == "amber"
    assert state["can_lock"] is False
    assert state["trigger_face_confirmation"] is False


def test_optional_classic_and_classic_are_one_tabular_group() -> None:
    results = [
        _intruder("classic_isolation_forest", "classic", 0.8),
        _intruder("supervised_random_forest", "optional_classic", 0.9),
        _genuine("keyboard_bigru_cnn_attention", "keyboard", 0.2),
    ]
    votes = build_group_votes(results)
    active = [vote for vote in votes if vote["can_vote"]]
    assert [vote["group"] for vote in active] == ["classic", "keyboard"]
    classic_vote = active[0]
    assert classic_vote["selected_candidate_id"] == "supervised_random_forest"
    assert set(classic_vote["candidate_ids"]) == {"classic_isolation_forest", "supervised_random_forest"}
    assert set(classic_vote["source_groups"]) == {"classic", "optional_classic"}


def test_unavailable_and_nonvoting_candidates_are_ignored_but_reported() -> None:
    unavailable = _result("keyboard_typeformer", "keyboard", None, "unavailable", can_vote=False, available=False)
    nonvoting = _result("keyboard_type2branch", "keyboard", 0.99, "intruder", can_vote=False, available=True)
    good = _intruder("mouse_resnet_gru", "mouse", 0.7)
    votes = build_group_votes([unavailable, nonvoting, good])
    keyboard = next(vote for vote in votes if vote["group"] == "keyboard")
    assert keyboard["can_vote"] is False
    assert set(keyboard["ignored_candidate_ids"]) == {"keyboard_typeformer", "keyboard_type2branch"}
    mouse = next(vote for vote in votes if vote["group"] == "mouse")
    assert mouse["can_vote"] is True
    assert mouse["decision"] == "intruder"


def test_group_voting_truth_table_is_report_only() -> None:
    cases = [
        ([], "green", False, False),
        ([_intruder("classic_isolation_forest", "classic")], "amber", False, False),
        ([_intruder("classic_isolation_forest", "classic"), _intruder("keyboard_type2branch", "keyboard")], "face_would_be_required", True, False),
        ([_intruder("classic_isolation_forest", "classic"), _intruder("keyboard_type2branch", "keyboard"), _intruder("mouse_resnet_gru", "mouse")], "red_strong", True, True),
    ]
    for results, expected_state, expected_face, expected_red in cases:
        report = build_offline_group_voting_report(results)
        offline = report["offline_fusion"]
        assert offline["offline_state"] == expected_state
        assert offline["face_would_be_required"] is expected_face
        assert offline["red_strong"] is expected_red
        assert offline["can_lock"] is False
        assert offline["can_influence_device"] is False
        assert offline["trigger_face_confirmation"] is False
        assert report["runtime_authoritative"] is False
        assert report["benchmark_selection_performed"] is False


def test_weighted_group_vote_strategy_remains_one_vote_per_group() -> None:
    results = [
        _intruder("keyboard_type2branch", "keyboard", 0.9),
        _genuine("keyboard_typeformer", "keyboard", 0.2),
    ]
    votes = build_group_votes(results, strategy="weighted", group_weights={"keyboard_type2branch": 1.0, "keyboard_typeformer": 3.0})
    active = [vote for vote in votes if vote["can_vote"]]
    assert len(active) == 1
    assert active[0]["group"] == "keyboard"
    assert active[0]["selected_candidate_id"] == "weighted:keyboard"
    assert active[0]["risk"] == 0.375
    assert active[0]["decision"] == "genuine"
    assert active[0]["can_lock_alone"] is False


def test_rule_based_fusion_returns_unified_report_only_result() -> None:
    result = evaluate_rule_based_fusion([_intruder("classic_isolation_forest", "classic"), _intruder("keyboard_type2branch", "keyboard")])
    assert validate_candidate_result(result)["ok"] is True
    assert result["id"] == "fusion_rule_based"
    assert result["available"] is True
    assert result["can_vote"] is False
    assert result["can_lock_alone"] is False
    assert result["can_influence_device"] is False
    assert result["trigger_face_confirmation"] is False
    assert result["offline_fusion"]["offline_state"] == "face_would_be_required"


def test_learned_fusion_missing_artifacts_fail_closed() -> None:
    inputs = [_intruder("classic_isolation_forest", "classic"), _intruder("keyboard_type2branch", "keyboard")]
    for evaluator in (evaluate_logistic_stacking, evaluate_calibrated_stacking):
        result = evaluator(inputs)
        assert validate_candidate_result(result)["ok"] is True
        assert result["available"] is False
        assert result["trained_artifact_loaded"] is False
        assert result["risk"] is None
        assert result["decision"] == "unavailable"
        assert result["can_vote"] is False
        assert result["can_lock_alone"] is False
        assert result["reason"] == "missing_trained_artifact"


def test_learned_fusion_requires_calibration_threshold_and_metadata() -> None:
    inputs = [_intruder("classic_isolation_forest", "classic"), _genuine("keyboard_type2branch", "keyboard")]
    no_threshold = {"calibration_metadata": {"version": 1}}
    result = evaluate_logistic_stacking(inputs, artifact=no_threshold, predict_fn=lambda artifact, features, metadata: 0.7)
    assert result["reason"] == "missing_calibration_threshold"
    no_calibration = {"threshold": 0.5}
    result = evaluate_calibrated_stacking(inputs, artifact=no_calibration, predict_fn=lambda artifact, features, metadata: 0.7)
    assert result["reason"] == "missing_calibration_artifact"


def test_learned_fusion_accepts_explicit_artifact_and_predictor_but_never_votes_or_locks() -> None:
    inputs = [_intruder("classic_isolation_forest", "classic", 0.8), _genuine("keyboard_type2branch", "keyboard", 0.3)]
    calls: list[tuple[Any, tuple[int, ...]]] = []

    def predictor(artifact: Any, features: np.ndarray, metadata: dict[str, Any] | None) -> float:
        calls.append((artifact, tuple(features.shape)))
        assert features.tolist() == [[0.8, 0.3, 0.0, 0.0, 0.0, 0.0]]
        return 0.72

    artifact = {"threshold": 0.65, "calibration_metadata": {"validated": True}, "artifact_id": "sha256:fusion"}
    result = evaluate_fusion_candidate("fusion_logistic_stacking", inputs, artifact=artifact, predict_fn=predictor)
    assert validate_candidate_result(result)["ok"] is True
    assert calls == [(artifact, (1, len(VOTING_GROUPS)))]
    assert result["available"] is True
    assert result["trained_artifact_loaded"] is True
    assert result["risk"] == 0.72
    assert result["decision"] == "intruder"
    assert result["can_vote"] is False
    assert result["can_lock_alone"] is False
    assert result["can_influence_device"] is False
    assert result["runtime_authoritative"] is False
    assert result["trigger_face_confirmation"] is False


def test_c7_modules_add_no_live_influence_or_qml_decision_path() -> None:
    source = Path("hybrid_candidates/group_voting.py").read_text(encoding="utf-8") + "\n" + Path("hybrid_candidates/fusion.py").read_text(encoding="utf-8")
    forbidden_tokens = [
        "LockWorkStation",
        "lock_screen",
        "runHybridDirectTest",
        "approveProductionModelSwitch",
        "production_pointer",
        "atomic_write",
        "save_model_hash",
        "save_classifier_sidecar",
        "train_model",
        "QtQuick",
        "live_allowed=True",
        "can_lock_alone=True",
    ]
    for token in forbidden_tokens:
        assert token not in source

    qml_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in Path("qml").rglob("*.qml"))
    for token in ("build_group_votes", "offline_fusion_state", "face_would_be_required", "red_strong", "fusion_logistic_stacking", "fusion_calibrated_stacking"):
        assert token not in qml_text
