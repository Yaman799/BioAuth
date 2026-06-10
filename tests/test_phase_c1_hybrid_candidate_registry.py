from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from hybrid_candidates.registry import build_unavailable_result, get_candidate, list_candidates, list_candidates_by_group, validate_candidate_result
from hybrid_candidates.schema import CANDIDATE_GROUPS, CandidateMetadata, CandidateResult

EXPECTED_CANDIDATES = {
    "classic_isolation_forest",
    "classic_one_class_svm",
    "classic_scaled_manhattan",
    "classic_nn_mahalanobis",
    "classic_lof",
    "classic_gmm",
    "supervised_random_forest",
    "supervised_lightgbm",
    "supervised_xgboost",
    "supervised_catboost",
    "keyboard_bigru_cnn_attention",
    "keyboard_type2branch",
    "keyboard_typeformer",
    "keyboard_siamese_triplet",
    "mouse_resnet_gru",
    "mouse_autoencoder",
    "mouse_deep_svdd",
    "oneclass_lstm_autoencoder",
    "oneclass_conv_autoencoder",
    "oneclass_deep_svdd",
    "combined_cnn_lstm",
    "fusion_rule_based",
    "fusion_logistic_stacking",
    "fusion_calibrated_stacking",
}

REQUIRED_METADATA_FIELDS = {
    "id",
    "display_name",
    "group",
    "modality",
    "status",
    "cost_class",
    "default_enabled",
    "allowed_modes",
    "live_allowed",
    "offline_allowed",
    "requires_artifact",
    "requires_training",
    "requires_threshold",
    "can_vote_default",
    "can_lock_alone",
    "description",
}

REQUIRED_RESULT_FIELDS = {
    "id",
    "display_name",
    "group",
    "available",
    "trained_artifact_loaded",
    "risk",
    "decision",
    "can_vote",
    "can_lock_alone",
    "reason",
    "latency_ms",
    "artifact_id",
    "threshold_source",
    "errors",
}


def test_candidate_registry_import_smoke() -> None:
    assert importlib.import_module("hybrid_candidates.registry")
    assert importlib.import_module("hybrid_candidates.schema")


def test_candidate_registry_is_complete_and_deterministic() -> None:
    first = list_candidates()
    second = list_candidates()
    ids = [candidate.id for candidate in first]
    assert ids == [candidate.id for candidate in second]
    assert set(ids) == EXPECTED_CANDIDATES
    assert len(ids) == len(EXPECTED_CANDIDATES)
    assert ids[0] == "classic_isolation_forest"
    assert ids[-1] == "fusion_calibrated_stacking"


def test_candidate_metadata_fields_and_safety_defaults() -> None:
    for candidate in list_candidates():
        assert isinstance(candidate, CandidateMetadata)
        payload = candidate.to_dict()
        assert set(payload) == REQUIRED_METADATA_FIELDS
        assert payload["id"] in EXPECTED_CANDIDATES
        assert payload["group"] in CANDIDATE_GROUPS
        assert payload["can_lock_alone"] is False
        assert payload["live_allowed"] is False
        assert "live" not in payload["allowed_modes"]
        assert payload["description"]
        if payload["status"] in {"future", "unavailable"}:
            assert payload["default_enabled"] is False
            assert payload["can_vote_default"] is False
            assert payload["offline_allowed"] is False
            assert payload["allowed_modes"] == []


def test_advanced_keyboard_candidates_are_offline_experimental_not_active() -> None:
    for candidate_id in ("keyboard_type2branch", "keyboard_typeformer", "keyboard_siamese_triplet"):
        candidate = get_candidate(candidate_id).to_dict()
        assert candidate["status"] == "experimental"
        assert candidate["default_enabled"] is False
        assert candidate["can_vote_default"] is False
        assert candidate["live_allowed"] is False
        assert candidate["offline_allowed"] is True
        assert candidate["can_lock_alone"] is False
        assert candidate["requires_artifact"] is True
        assert candidate["requires_training"] is True
        assert candidate["requires_threshold"] is True


def test_list_candidates_by_group_returns_expected_groups() -> None:
    assert [candidate.id for candidate in list_candidates_by_group("classic")] == [
        "classic_isolation_forest",
        "classic_one_class_svm",
        "classic_scaled_manhattan",
        "classic_nn_mahalanobis",
        "classic_lof",
        "classic_gmm",
    ]
    assert [candidate.id for candidate in list_candidates_by_group("keyboard")] == [
        "keyboard_bigru_cnn_attention",
        "keyboard_type2branch",
        "keyboard_typeformer",
        "keyboard_siamese_triplet",
    ]
    assert list_candidates_by_group("does_not_exist") == []


def test_build_unavailable_result_is_fail_closed_without_random_scoring() -> None:
    result = build_unavailable_result("keyboard_typeformer", "artifact_missing")
    assert set(result) == REQUIRED_RESULT_FIELDS
    assert result["id"] == "keyboard_typeformer"
    assert result["available"] is False
    assert result["trained_artifact_loaded"] is False
    assert result["risk"] is None
    assert result["decision"] == "abstain"
    assert result["can_vote"] is False
    assert result["can_lock_alone"] is False
    assert result["reason"] == "artifact_missing"
    assert result["threshold_source"] == "not_available"
    assert validate_candidate_result(result)["ok"] is True


def test_validate_candidate_result_rejects_unsafe_or_fake_unavailable_payloads() -> None:
    safe = CandidateResult(
        id="classic_isolation_forest",
        display_name="Classic Isolation Forest",
        group="classic",
        available=True,
        trained_artifact_loaded=True,
        risk=0.42,
        decision="genuine",
        can_vote=True,
        can_lock_alone=False,
        reason="ok",
        latency_ms=12.5,
        artifact_id="sha256:test",
        threshold_source="artifact_metadata",
        errors=[],
    ).to_dict()
    assert validate_candidate_result(safe) == {"ok": True, "errors": []}

    unsafe = dict(safe)
    unsafe["can_lock_alone"] = True
    assert "can_lock_alone_must_be_false" in validate_candidate_result(unsafe)["errors"]

    unavailable_with_score = build_unavailable_result("classic_lof", "artifact_missing")
    unavailable_with_score["risk"] = 0.5
    unavailable_with_score["can_vote"] = True
    unavailable_with_score["decision"] = "intruder"
    errors = validate_candidate_result(unavailable_with_score)["errors"]
    assert "unavailable_risk_must_be_none" in errors
    assert "unavailable_cannot_vote" in errors
    assert "unavailable_must_abstain" in errors


def test_registry_adds_no_runtime_influence_or_qml_decision_path() -> None:
    registry_source = Path("hybrid_candidates/registry.py").read_text(encoding="utf-8")
    schema_source = Path("hybrid_candidates/schema.py").read_text(encoding="utf-8")
    combined = registry_source + "\n" + schema_source
    forbidden_tokens = [
        "LockWorkStation",
        "lock_screen",
        "runHybridDirectTest",
        "subprocess",
        "QML",
        "production_pointer",
        "approveProductionModelSwitch",
        "can_influence_device = True",
        "live_allowed=True",
        "can_lock_alone=True",
    ]
    for token in forbidden_tokens:
        assert token not in combined


def test_metadata_constructor_refuses_single_candidate_lock_or_live_mode() -> None:
    with pytest.raises(ValueError, match="can_lock_alone"):
        CandidateMetadata(
            id="unsafe_candidate",
            display_name="Unsafe Candidate",
            group="classic",
            modality="tabular",
            status="experimental",
            cost_class="low",
            default_enabled=False,
            allowed_modes=("offline",),
            live_allowed=False,
            offline_allowed=True,
            can_lock_alone=True,
            description="unsafe",
        )
    with pytest.raises(ValueError, match="live mode"):
        CandidateMetadata(
            id="unsafe_live_candidate",
            display_name="Unsafe Live Candidate",
            group="classic",
            modality="tabular",
            status="experimental",
            cost_class="low",
            default_enabled=False,
            allowed_modes=("offline",),
            live_allowed=True,
            offline_allowed=True,
            can_lock_alone=False,
            description="unsafe",
        )
