from __future__ import annotations

from hybrid_direct_contract import build_hybrid_direct_state, build_default_hybrid_direct_state
from hybrid_fusion_policy import evaluate_late_fusion, resolve_face_confirmation_for_hybrid_lock
import runtime_policy


def _risk(decision: str, *, available: bool = True, risk: float = 0.9, threshold: float = 0.5, reason_codes=None):
    return {
        "available": available,
        "status": "ok" if available else "unavailable",
        "decision": decision,
        "risk": risk if available else None,
        "threshold": threshold,
        "reason_codes": list(reason_codes or (["ok"] if available else ["no_model_result"])),
        "can_lock": True,
        "can_lock_alone": True,
        "can_influence_device": True,
    }


def test_default_hybrid_direct_remains_disabled_and_cannot_influence_or_lock() -> None:
    state = build_default_hybrid_direct_state(timestamp="2026-05-04T00:00:00Z")
    assert state["enabled"] is False
    assert state["can_influence_device"] is False
    assert state["experiment_can_lock_alone"] is False
    assert state["no_single_model_can_lock"] is True
    assert state["fusion_state"] == "unavailable"
    assert state["face_required"] is False
    assert state["final_action"] == "none"
    assert runtime_policy.DEVELOPER_DIRECT_TEST_ENABLED_DEFAULT is False
    assert runtime_policy.EXPERIMENT_CAN_LOCK_ALONE is False


def test_one_intruder_model_is_amber_advisory_and_never_lock() -> None:
    decision = evaluate_late_fusion(
        {
            "classic_risk": _risk("intruder"),
            "keyboard_risk": _risk("genuine"),
        },
        enabled=True,
        can_influence_device=True,
    )
    assert decision["fusion_state"] == "amber"
    assert decision["agreement_count"] == 1
    assert decision["face_required"] is False
    assert decision["final_action"] == "monitor_or_investigate"
    assert "single_model_intruder_advisory_only" in decision["reason_codes"]
    assert decision["model_provenance"]["classic_risk"]["can_lock_alone"] is False


def test_two_independent_intruder_models_require_face_confirmation_before_lock() -> None:
    decision = evaluate_late_fusion(
        {
            "classic_risk": _risk("intruder"),
            "keyboard_risk": _risk("intruder"),
            "mouse_risk": _risk("genuine"),
        },
        enabled=True,
        can_influence_device=True,
    )
    assert decision["fusion_state"] == "red"
    assert decision["agreement_count"] == 2
    assert decision["face_required"] is True
    assert decision["final_action"] == "request_face_confirmation"
    assert "hybrid_red_requires_face_confirmation" in decision["reason_codes"]
    assert "face_confirmation_required_before_hybrid_lock" in decision["reason_codes"]


def test_face_passed_suppresses_hybrid_lock_and_logs_false_positive_candidate_path() -> None:
    red = evaluate_late_fusion(
        {"classic_risk": _risk("intruder"), "mouse_risk": _risk("intruder")},
        enabled=True,
        can_influence_device=True,
    )
    resolved = resolve_face_confirmation_for_hybrid_lock(
        red,
        {"attempted": True, "verified_owner_after_anomaly": True, "raw_images_stored": False},
        timestamp="2026-05-04T00:00:00Z",
    )
    assert resolved["lock_allowed"] is False
    assert resolved["final_action"] == "no_lock_face_confirmed_owner"
    assert "face_passed_lock_suppressed" in resolved["reason_codes"]
    assert "false_positive_candidate_logged" in resolved["reason_codes"]
    assert resolved["raw_images_stored"] is False


def test_face_failed_allows_existing_incident_policy_to_handle_lock() -> None:
    red = evaluate_late_fusion(
        {"classic_risk": _risk("intruder"), "combined_risk": _risk("intruder")},
        enabled=True,
        can_influence_device=True,
    )
    resolved = resolve_face_confirmation_for_hybrid_lock(
        red,
        {"attempted": True, "verified_owner_after_anomaly": False, "raw_images_stored": False},
    )
    assert resolved["lock_allowed"] is True
    assert resolved["final_action"] == "lock_allowed_via_existing_incident_policy"
    assert resolved["final_action_provenance"] == "pre_lock_face_confirmation_failed_closed"
    assert "face_attempted_failed_lock_allowed" in resolved["reason_codes"]
    assert resolved["raw_images_stored"] is False


def test_timeout_and_schema_errors_are_ignored_and_do_not_weaken_classic_fallback() -> None:
    decision = evaluate_late_fusion(
        {
            "classic_risk": _risk("genuine"),
            "keyboard_risk": _risk("intruder", reason_codes=["timeout"]),
            "mouse_risk": _risk("intruder", reason_codes=["schema_error"]),
        },
        enabled=True,
        can_influence_device=True,
    )
    assert decision["fusion_state"] == "green"
    assert decision["agreement_count"] == 0
    assert decision["ignored_signal_count"] == 2
    assert "keyboard:timeout_ignored_fallback_classic" in decision["errors"]
    assert "mouse:schema_error_ignored_fallback_classic" in decision["errors"]
    assert decision["model_provenance"]["keyboard_risk"]["effective_weight"] == 0.0
    assert decision["model_provenance"]["mouse_risk"]["effective_weight"] == 0.0


def test_missing_mouse_data_sets_weight_zero_and_unavailable() -> None:
    decision = evaluate_late_fusion(
        {
            "classic_risk": _risk("genuine"),
            "mouse_risk": _risk("abstain", available=False, reason_codes=["missing_mouse_data"]),
        },
        enabled=True,
        can_influence_device=True,
    )
    mouse = decision["model_provenance"]["mouse_risk"]
    assert mouse["available"] is False
    assert mouse["effective_weight"] == 0.0
    assert mouse["ignore_reason"] == "mouse_unavailable_weight_zero"
    assert "mouse_unavailable_weight_zero" in decision["reason_codes"]


def test_hybrid_direct_state_uses_backend_late_fusion_outputs_without_lock_authority() -> None:
    state = build_hybrid_direct_state(
        {
            "enabled": True,
            "can_influence_device": False,
            "classic_risk": _risk("intruder"),
            "keyboard_risk": _risk("intruder"),
        },
        timestamp="2026-05-04T00:00:00Z",
    )
    assert state["fusion_state"] == "red"
    assert state["agreement_count"] == 2
    assert state["face_required"] is True
    assert state["final_action"] == "request_face_confirmation"
    assert state["can_influence_device"] is False
    assert state["classic_risk"]["can_lock"] is False
    assert state["keyboard_risk"]["can_lock_alone"] is False
    assert "model_provenance" in state
    assert "device_influence_disabled" in state["reason_codes"]
