from __future__ import annotations

import re
from pathlib import Path

from metadata_core.autonomous_readiness_loop import build_autonomous_readiness_loop_state
from metadata_core.auto_training_scheduler import auto_training_should_start
from metadata_core.production_approval import build_protected_sessions_ready_notification_state
from metadata_core.production_evidence_pipeline import (
    ProductionEvidenceRecord,
    append_evidence_record,
    load_shadow_evidence_summary_for_candidate,
)
from metadata_core.remediation_loop import (
    RemediationAction,
    RemediationRetryEligibility,
    build_remediation_plan,
    remediation_evidence_progress_from_summary,
)

ROOT = Path(__file__).resolve().parent.parent


def _settings(**overrides):
    payload = {
        "smart_auto_enrollment_enabled": True,
        "auto_train_when_ready_enabled": True,
        "background_collection_consent": True,
    }
    payload.update(overrides)
    return payload


def _profile(**overrides):
    payload = {
        "training_can_start": False,
        "session_count": 0,
        "minimum_session_count": 8,
        "candidate_model_status": "no_candidate",
    }
    payload.update(overrides)
    return payload


def _production_state(**overrides):
    payload = {
        "modelStatus": "no_candidate",
        "candidate_status": "no_candidate",
        "protectedSessionsAvailable": False,
        "productionReady": False,
        "productionApprovalPassed": False,
        "productionEvidencePassed": False,
        "reason_code": "training_not_ready",
        "productionEvidenceSummary": {},
    }
    payload.update(overrides)
    return payload


def _ready_production_payload(**overrides):
    payload = {
        "modelStatus": "approved_for_production",
        "candidate_status": "approved_for_production",
        "productionReady": True,
        "protectedSessionsAvailable": True,
        "productionApprovalPassed": True,
        "productionEvidencePassed": True,
        "runtimeValidationReason": "ok",
        "reason_code": "production_ready",
        "productionEvidenceCandidateDigest": "sha256:prod-a",
        "closedBetaGateRequired": False,
        "closedBetaGateStatus": "optional_missing",
        "productionEvidenceSummary": {
            "status": "pass",
            "promotion_effect": "production_eligible",
            "allows_production_eligibility": True,
            "candidate_artifact_digest": "sha256:prod-a",
            "reason_codes": [],
        },
    }
    payload.update(overrides)
    return payload


def _state(**kwargs):
    defaults = {
        "settings": _settings(),
        "profile": _profile(),
        "runtime_state": {},
        "sessions": [],
        "consent_satisfied": True,
        "authenticated": True,
        "training_active": False,
        "evaluation_active": False,
        "session_flow": "idle",
        "remediation_state": {},
        "production_approval": _production_state(),
        "auto_training_last_reason": "",
    }
    defaults.update(kwargs)
    return build_autonomous_readiness_loop_state(**defaults)


def _record(idx=0, **overrides):
    payload = {
        "window_id": f"smoke-window-{idx}",
        "user_id": "newuser",
        "candidate_artifact_digest": "sha256:candidate-a",
        "baseline_artifact_digest": "sha256:baseline-a",
        "runtime_schema_version": "runtime-v1",
        "feature_schema_version": "feature-v1",
        "candidate_decision": "legit",
        "baseline_decision": "legit",
        "candidate_risk_bucket": "low",
        "baseline_risk_bucket": "low",
        "candidate_would_lock_if_production": False,
        "baseline_would_lock_if_production": False,
        "is_trusted_window": True,
        "trusted_anchor_type": "runtime_monitor",
        "is_post_unlock_window": True,
        "is_confirmed_intruder_window": False,
        "feature_quality_ok": True,
        "unknown_or_abstain": False,
        "schema_ok": True,
        "source": "shadow_evidence_monitor",
        "reason_codes": [],
    }
    payload.update(overrides)
    return payload


def _patch_evidence_dir(monkeypatch, tmp_path):
    from metadata_core import production_evidence_pipeline as pipe
    evidence_root = tmp_path / "evidence"
    monkeypatch.setattr(pipe.paths, "evidence_dir", lambda: str(evidence_root))
    return evidence_root


def _append_shadow_records(monkeypatch, tmp_path, count=5, **overrides):
    _patch_evidence_dir(monkeypatch, tmp_path)
    for idx in range(count):
        payload = _record(idx, **overrides)
        append_evidence_record(payload["user_id"], ProductionEvidenceRecord.from_dict(payload))
    return load_shadow_evidence_summary_for_candidate(
        "newuser",
        candidate_artifact_digest="sha256:candidate-a",
        runtime_schema_version="runtime-v1",
    )


def _remediation_plan():
    return build_remediation_plan(reason_codes=["insufficient_model_agreement"], candidate_artifact_digest="sha256:candidate-a")


def _training_sessions(count=8):
    return [
        {
            "session_id": f"session-{idx}",
            "session_kind": "enrollment",
            "bucket": "accepted",
            "metadata_trusted": True,
            "training_counts_toward_minimum": True,
            "excluded_from_positive_training": False,
            "keyboard_rows": 50,
            "mouse_rows": 50,
            "duration_seconds": 120,
        }
        for idx in range(count)
    ]


def test_new_user_loop_waits_for_consent():
    state = _state(consent_satisfied=False)
    assert state["autonomous_loop_state"] == "waiting_for_consent"
    assert state["autonomous_loop_next_action"] == "none"


def test_new_user_loop_collects_until_default_minimum():
    state = _state(profile=_profile(training_can_start=False, session_count=3))
    assert state["autonomous_loop_state"] == "collecting_initial_sessions"
    assert state["autonomous_loop_next_action"] == "start_passive_collection"


def test_new_user_loop_auto_trains_when_ready():
    state = _state(profile=_profile(training_can_start=True, session_count=8), sessions=_training_sessions())
    assert state["autonomous_loop_state"] == "ready_for_initial_training"
    assert state["autonomous_loop_next_action"] == "start_auto_training"


def test_new_user_loop_enters_shadow_validation():
    state = _state(
        production_approval=_production_state(modelStatus="approved_for_shadow", candidate_status="approved_for_shadow"),
        profile=_profile(candidate_model_status="approved_for_shadow"),
    )
    assert state["autonomous_loop_state"] == "approved_for_shadow"


def test_new_user_loop_starts_shadow_evidence_monitor():
    state = _state(
        production_approval=_production_state(modelStatus="approved_for_shadow", candidate_status="approved_for_shadow"),
        profile=_profile(candidate_model_status="approved_for_shadow"),
    )
    assert state["autonomous_loop_next_action"] == "start_shadow_evidence_monitor"


def test_new_user_loop_updates_evidence_ledger(monkeypatch, tmp_path):
    summary = _append_shadow_records(monkeypatch, tmp_path, count=7)
    assert summary["windows_collected"] == 7
    assert summary["records_accepted"] == 7
    assert summary["source"] == "shadow_evidence_monitor"


def test_new_user_loop_updates_remediation_progress(monkeypatch, tmp_path):
    summary = _append_shadow_records(monkeypatch, tmp_path, count=5)
    progress = remediation_evidence_progress_from_summary(summary, _remediation_plan())
    assert progress["shadow_comparison_windows"] == 5


def test_new_user_loop_retries_after_new_evidence_signature(monkeypatch, tmp_path):
    summary = _append_shadow_records(monkeypatch, tmp_path, count=5)
    ok, reason, signature = auto_training_should_start(
        settings=_settings(),
        profile=_profile(training_can_start=True, session_count=8),
        runtime_state={},
        sessions=_training_sessions(),
        user_id="newuser",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        remediation_plan=_remediation_plan(),
        production_evidence_summary=summary,
        last_attempted_signature="sha256:old-failed-signature",
        last_attempted_training_result="failed_offline_approval",
        now=1000.0,
    )
    assert ok is True
    assert reason == "ready"
    assert signature and signature != "sha256:old-failed-signature"


def test_new_user_loop_does_not_retry_same_failed_signature(monkeypatch, tmp_path):
    summary = _append_shadow_records(monkeypatch, tmp_path, count=5)
    plan = _remediation_plan()
    ok1, _reason1, signature = auto_training_should_start(
        settings=_settings(), profile=_profile(training_can_start=True, session_count=8), runtime_state={}, sessions=_training_sessions(), user_id="newuser", consent_satisfied=True, authenticated=True, training_active=False, session_flow="idle", remediation_plan=plan, production_evidence_summary=summary, now=1000.0
    )
    assert ok1 is True
    ok2, reason2, signature2 = auto_training_should_start(
        settings=_settings(), profile=_profile(training_can_start=True, session_count=8), runtime_state={}, sessions=_training_sessions(), user_id="newuser", consent_satisfied=True, authenticated=True, training_active=False, session_flow="idle", remediation_plan=plan, production_evidence_summary=summary, last_attempted_signature=signature, last_attempted_training_result="failed_offline_approval", now=1000.0
    )
    assert ok2 is False
    assert reason2 == "already_attempted_current_training_data"
    assert signature2 == signature


def test_new_user_loop_blocks_non_retryable_runtime_failure():
    state = _state(
        profile=_profile(candidate_model_status="approved_for_shadow"),
        production_approval=_production_state(
            modelStatus="approved_for_shadow",
            candidate_status="approved_for_shadow",
            productionEvidenceSummary={"status": "partial", "promotion_effect": "shadow_only", "reason_codes": ["runtime_schema_mismatch"]},
        ),
    )
    assert state["autonomous_loop_state"] == "blocked_non_retryable_runtime_fix_required"
    assert "runtime_or_artifact_fix_required" in state["autonomous_loop_blockers"]


def test_new_user_loop_does_not_overlap_training_and_collection():
    ok, reason, _signature = auto_training_should_start(
        settings=_settings(),
        profile=_profile(training_can_start=True, session_count=8),
        runtime_state={"active": True, "session_kind": "enrollment", "auto_enrollment": True},
        sessions=_training_sessions(),
        user_id="newuser",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="enrollment_active",
        now=1000.0,
    )
    assert ok is False
    assert reason == "passive_auto_enrollment_active"


def test_new_user_loop_ready_notification_only_after_all_gates():
    partial = build_protected_sessions_ready_notification_state(
        _ready_production_payload(
            productionReady=False,
            protectedSessionsAvailable=False,
            productionApprovalPassed=False,
            productionEvidencePassed=False,
            productionEvidenceSummary={"status": "partial", "promotion_effect": "shadow_only", "reason_codes": ["production_evidence_partial"]},
        )
    )
    ready = build_protected_sessions_ready_notification_state(_ready_production_payload())
    assert partial["protected_sessions_ready_notification_pending"] is False
    assert ready["protected_sessions_ready_notification_pending"] is True
    assert ready["protected_sessions_ready_message"] == "Protected Sessions are ready."


def test_new_user_loop_protected_sessions_unavailable_until_backend_pass():
    state = _state(
        production_approval=_production_state(
            modelStatus="approved_for_shadow",
            candidate_status="approved_for_shadow",
            protectedSessionsAvailable=False,
            productionReady=False,
            productionEvidenceSummary={"status": "partial", "promotion_effect": "shadow_only"},
        )
    )
    assert state["autonomous_loop_state"] != "protected_sessions_ready"
    notification = build_protected_sessions_ready_notification_state(_ready_production_payload(protectedSessionsAvailable=False, productionReady=False, productionApprovalPassed=False))
    assert notification["protected_sessions_ready_notification_pending"] is False


def test_new_user_loop_qml_display_only():
    qml = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (ROOT / "qml").rglob("*.qml"))
    forbidden = [
        r"function\s+.*(productionReady|protectedSessionsAvailable|autonomousLoop|retryEligibility|approvalPassed)",
        r"\b(var|let|const)\s+(productionReady|protectedSessionsAvailable|autonomousLoopState|retryEligibility|approvalPassed)\b",
        r"\b(productionReady|protectedSessionsAvailable|approvalPassed)\s*=(?!=)",
    ]
    assert not any(re.search(pattern, qml) for pattern in forbidden)


def test_new_user_loop_closed_beta_advisory_non_blocking_by_default():
    state = build_protected_sessions_ready_notification_state(
        _ready_production_payload(closedBetaGateRequired=False, closedBetaGateStatus="optional_missing", closedBetaAdvisoryReasons=["minimum_20_beta_users"])
    )
    assert state["protected_sessions_ready_notification_pending"] is True
    assert "minimum_20_beta_users" not in state["ready_notification_blockers"]


def test_new_user_loop_report_does_not_contain_raw_behavioral_data():
    report = ROOT / "reports" / "autonomous_readiness_loop_smoke.md"
    if report.exists():
        text = report.read_text(encoding="utf-8", errors="ignore").lower()
        for forbidden in ("feature_vector", "raw_keyboard", "raw_mouse", "raw_events", "keystroke", "mouse_delta"):
            assert forbidden not in text
