from __future__ import annotations

import re
from pathlib import Path

from metadata_core.production_approval import build_protected_sessions_ready_notification_state, with_protected_sessions_ready_notification_state

ROOT = Path(__file__).resolve().parent.parent


def _ready_payload(**overrides):
    payload = {
        "modelStatus": "approved_for_production",
        "productionReady": True,
        "protectedSessionsAvailable": True,
        "productionApprovalPassed": True,
        "productionEvidencePassed": True,
        "runtimeValidationReason": "ok",
        "reason_code": "production_ready",
        "status": "approved",
        "productionEvidenceSummary": {
            "status": "pass",
            "promotion_effect": "production_eligible",
            "allows_production_eligibility": True,
            "candidate_artifact_digest": "sha256:artifact-a",
            "reason_codes": [],
            "model_agreement": {"overall_agreement_rate": 1.0, "trusted_window_agreement_rate": 1.0},
            "post_unlock_evidence": {"trusted_post_unlock_windows": 5},
            "confirmed_intruder_evidence": {"low_risk_confirmed_intruder_count": 0},
            "runtime_safety": {"runtime_schema_ok": True},
        },
        "productionEvidenceCandidateDigest": "sha256:artifact-a",
        "closedBetaGateRequired": False,
        "closedBetaGateStatus": "optional_missing",
    }
    for key, value in overrides.items():
        if key == "summary":
            payload["productionEvidenceSummary"].update(value)
        else:
            payload[key] = value
    return payload


def test_ready_notification_not_shown_for_approved_for_shadow_only():
    state = build_protected_sessions_ready_notification_state(_ready_payload(
        modelStatus="approved_for_shadow",
        productionReady=False,
        protectedSessionsAvailable=False,
        productionApprovalPassed=False,
        reason_code="production_evidence_partial",
        summary={"status": "partial", "promotion_effect": "shadow_only"},
    ))
    assert state["protected_sessions_ready_notification_pending"] is False
    assert "candidate_not_production_ready" in state["ready_notification_blockers"]


def test_ready_notification_not_shown_when_evidence_partial():
    state = build_protected_sessions_ready_notification_state(_ready_payload(
        productionEvidencePassed=False,
        summary={"status": "partial", "promotion_effect": "shadow_only", "reason_codes": ["production_evidence_partial"]},
    ))
    assert state["protected_sessions_ready_notification_pending"] is False
    assert "production_evidence_not_passed" in state["ready_notification_blockers"]


def test_ready_notification_not_shown_when_runtime_schema_invalid():
    state = build_protected_sessions_ready_notification_state(_ready_payload(
        runtimeValidationReason="runtime_schema_mismatch",
        summary={"reason_codes": ["runtime_schema_mismatch"]},
    ))
    assert state["protected_sessions_ready_notification_pending"] is False
    assert "runtime_validation_not_ok" in state["ready_notification_blockers"]
    assert "runtime_schema_mismatch" in state["ready_notification_blockers"]


def test_ready_notification_not_shown_when_baseline_agreement_missing():
    state = build_protected_sessions_ready_notification_state(_ready_payload(
        productionEvidencePassed=False,
        summary={"status": "partial", "promotion_effect": "shadow_only", "reason_codes": ["baseline_decision_missing", "insufficient_model_agreement_data"]},
    ))
    assert state["protected_sessions_ready_notification_pending"] is False
    assert "baseline_decision_missing" in state["ready_notification_blockers"]


def test_ready_notification_not_shown_when_confirmed_intruder_low_risk_exists():
    state = build_protected_sessions_ready_notification_state(_ready_payload(
        productionEvidencePassed=False,
        summary={"status": "partial", "promotion_effect": "shadow_only", "reason_codes": ["confirmed_intruder_low_risk"]},
    ))
    assert state["protected_sessions_ready_notification_pending"] is False
    assert "confirmed_intruder_low_risk" in state["ready_notification_blockers"]


def test_ready_notification_shown_when_all_backend_gates_pass():
    state = build_protected_sessions_ready_notification_state(_ready_payload())
    assert state["protected_sessions_ready_notification_pending"] is True
    assert state["ready_notification_state"] == "pending"
    assert state["ready_notification_reason"] == "all_backend_gates_passed"
    assert state["protected_sessions_ready_message"] == "Protected Sessions are ready."


def test_ready_notification_emitted_once_per_artifact_digest():
    state = build_protected_sessions_ready_notification_state(_ready_payload(), notified_artifact_digest="sha256:artifact-a", notified_at="2026-05-02T08:00:00Z")
    assert state["protected_sessions_ready_notification_pending"] is False
    assert state["ready_notification_state"] == "already_notified"
    assert state["protected_sessions_ready_notified_at"] == "2026-05-02T08:00:00Z"


def test_ready_notification_resets_for_new_artifact_digest():
    state = build_protected_sessions_ready_notification_state(
        _ready_payload(productionEvidenceCandidateDigest="sha256:artifact-b", summary={"candidate_artifact_digest": "sha256:artifact-b"}),
        notified_artifact_digest="sha256:artifact-a",
    )
    assert state["protected_sessions_ready_notification_pending"] is True
    assert state["ready_notification_artifact_digest"] == "sha256:artifact-b"


def test_protected_sessions_available_backend_owned():
    state = build_protected_sessions_ready_notification_state(_ready_payload(protectedSessionsAvailable=False))
    assert state["protected_sessions_ready_notification_pending"] is False
    assert "protected_sessions_unavailable" in state["ready_notification_blockers"]


def test_qml_displays_ready_message_without_computing_readiness():
    qml_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (ROOT / "qml").rglob("*.qml"))
    forbidden = r"(var|let|const|function)\s+(protectedSessionsReady|readyNotification|notificationEligibility|productionReady|protectedSessionsAvailable)\b|protected_sessions_ready_notification_pending\s*:"
    assert not re.search(forbidden, qml_text)


def test_start_protected_still_uses_backend_guard():
    source = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    start_idx = source.index("def start_protected_session")
    next_def = source.find("\ndef ", start_idx + 1)
    body = source[start_idx: next_def if next_def != -1 else len(source)]
    assert 'profile.get("production_ready")' in body
    assert "start_shadow_evidence_monitor" not in body


def test_closed_beta_advisory_missing_does_not_block_notification_if_all_core_gates_pass():
    state = build_protected_sessions_ready_notification_state(_ready_payload(closedBetaGateRequired=False, closedBetaGateStatus="optional_missing", closedBetaAdvisoryReasons=["minimum_20_beta_users"]))
    assert state["protected_sessions_ready_notification_pending"] is True
    assert "minimum_20_beta_users" not in state["ready_notification_blockers"]


def test_auto_promotion_disabled_does_not_fake_ready_notification():
    state = build_protected_sessions_ready_notification_state(_ready_payload(productionReady=False, protectedSessionsAvailable=False, productionApprovalPassed=False, autoPromotionState={"enabled": False}))
    assert state["protected_sessions_ready_notification_pending"] is False
    assert "protected_sessions_unavailable" in state["ready_notification_blockers"]


def test_notification_payload_aliases_are_backend_owned_and_safe():
    payload = with_protected_sessions_ready_notification_state(_ready_payload())
    assert payload["protectedSessionsReadyNotificationPending"] is True
    assert payload["readyNotificationReason"] == "all_backend_gates_passed"
    combined = repr(payload).lower()
    for forbidden in ("feature_vector", "raw_keyboard", "raw_mouse", "raw_events", "keystroke"):
        assert forbidden not in combined
