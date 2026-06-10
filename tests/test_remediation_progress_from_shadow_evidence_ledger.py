from __future__ import annotations

import sys
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation_core.production_evidence import ProductionEvidencePromotionEffect, ProductionEvidenceReasonCode, ProductionEvidenceStatus
from metadata_core.production_approval import build_production_approval_state
from metadata_core.production_evidence_pipeline import (
    ProductionEvidenceRecord,
    append_evidence_record,
    load_shadow_evidence_summary_for_candidate,
    remediation_progress_from_evidence_records,
)
from metadata_core.remediation_loop import build_remediation_plan, remediation_evidence_progress_from_summary
from metadata_core.auto_training_scheduler import remediation_requirements_met, auto_training_should_start
from metadata_core.dashboard import _remediation_dashboard_state


def _patch_evidence_dir(monkeypatch, tmp_path: Path) -> None:
    from metadata_core import production_evidence_pipeline as pipe

    evidence_root = tmp_path / "evidence"
    monkeypatch.setattr(pipe.paths, "evidence_dir", lambda: str(evidence_root))


def _record_payload(idx: int = 0, **overrides):
    payload = {
        "window_id": f"window-{idx}",
        "user_id": "alice",
        "candidate_artifact_digest": "sha256:candidate",
        "baseline_artifact_digest": "",
        "runtime_schema_version": "runtime-v1",
        "feature_schema_version": "feature-v1",
        "candidate_decision": "legit",
        "baseline_decision": "",
        "candidate_risk_bucket": "low",
        "baseline_risk_bucket": "unknown",
        "candidate_would_lock_if_production": False,
        "baseline_would_lock_if_production": False,
        "is_trusted_window": True,
        "trusted_anchor_type": "runtime_monitor",
        "is_post_unlock_window": False,
        "is_confirmed_intruder_window": False,
        "feature_quality_ok": True,
        "unknown_or_abstain": False,
        "schema_ok": True,
        "source": "shadow_evidence_monitor",
        "reason_codes": [],
    }
    payload.update(overrides)
    return payload


def _append_records(monkeypatch, tmp_path: Path, count: int, **overrides):
    _patch_evidence_dir(monkeypatch, tmp_path)
    records = []
    for idx in range(count):
        payload = _record_payload(idx, **overrides)
        records.append(append_evidence_record(payload["user_id"], ProductionEvidenceRecord.from_dict(payload)))
    return records


def _summary(monkeypatch, tmp_path: Path, **kwargs):
    _patch_evidence_dir(monkeypatch, tmp_path)
    return load_shadow_evidence_summary_for_candidate(
        "alice",
        candidate_artifact_digest=kwargs.get("candidate_artifact_digest", "sha256:candidate"),
        runtime_schema_version=kwargs.get("runtime_schema_version", "runtime-v1"),
    )


def _plan():
    return build_remediation_plan(reason_codes=["insufficient_model_agreement"], candidate_artifact_digest="sha256:candidate")


def test_shadow_evidence_ledger_counts_toward_shadow_comparison_remediation_progress(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5)
    summary = _summary(monkeypatch, tmp_path)
    progress = remediation_evidence_progress_from_summary(summary, _plan())
    assert progress["shadow_comparison_windows"] == 5
    assert remediation_requirements_met(_plan(), progress) is True


def test_low_quality_shadow_windows_do_not_satisfy_remediation_requirement(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, feature_quality_ok=False)
    progress = remediation_evidence_progress_from_summary(_summary(monkeypatch, tmp_path), _plan())
    assert progress.get("shadow_comparison_windows", 0) == 0
    assert remediation_requirements_met(_plan(), progress) is False


def test_startup_transition_windows_do_not_count_as_strong_remediation_evidence(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, reason_codes=["startup_transition_window"])
    progress = remediation_evidence_progress_from_summary(_summary(monkeypatch, tmp_path), _plan())
    assert progress.get("shadow_comparison_windows", 0) == 0


def test_candidate_digest_mismatch_does_not_satisfy_remediation_progress(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, candidate_artifact_digest="sha256:other")
    progress_payload = remediation_progress_from_evidence_records(
        _summary(monkeypatch, tmp_path, candidate_artifact_digest="sha256:candidate").get("production_evidence", {}).get("runtime_decision_summaries", []),
        candidate_artifact_digest="sha256:candidate",
        runtime_schema_version="runtime-v1",
    )
    # The public summary path is the one consumed by dashboard; it must remain zero for mismatches.
    progress = remediation_evidence_progress_from_summary(_summary(monkeypatch, tmp_path), _plan())
    assert progress.get("shadow_comparison_windows", 0) == 0
    assert "remediation_shadow_evidence_digest_mismatch" not in progress_payload.get("reason_codes", []) or progress_payload["counts"]["shadow_comparison_windows"] == 0


def test_runtime_schema_mismatch_does_not_satisfy_remediation_progress(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, runtime_schema_version="runtime-old")
    progress = remediation_evidence_progress_from_summary(_summary(monkeypatch, tmp_path, runtime_schema_version="runtime-v1"), _plan())
    assert progress.get("shadow_comparison_windows", 0) == 0


def test_missing_baseline_keeps_model_agreement_incomplete_even_if_progress_counts_windows(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, baseline_decision="")
    summary = _summary(monkeypatch, tmp_path)
    assert remediation_evidence_progress_from_summary(summary, _plan())["shadow_comparison_windows"] == 5
    report = summary["production_evidence"]
    assert report["gate"]["status"] == ProductionEvidenceStatus.PARTIAL.value
    assert report["gate"]["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value
    assert report["model_agreement"]["overall_agreement_rate"] == 0.0
    assert ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING in report["gate"]["reason_codes"]


def test_post_unlock_requirement_not_satisfied_without_post_unlock_records(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, is_post_unlock_window=False)
    post_unlock_plan = build_remediation_plan(reason_codes=["insufficient_post_unlock_evidence"])
    progress = remediation_evidence_progress_from_summary(_summary(monkeypatch, tmp_path), post_unlock_plan)
    assert progress.get("post_unlock_windows", 0) == 0
    assert remediation_requirements_met(post_unlock_plan, progress) is False


def test_confirmed_intruder_evidence_not_counted_as_owner_positive_remediation(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 1, is_confirmed_intruder_window=True, candidate_decision="intruder", candidate_risk_bucket="high")
    summary = _summary(monkeypatch, tmp_path)
    progress = summary["remediation_progress"]
    assert progress.get("hard_negative_events", 0) == 1
    assert progress.get("trusted_owner_sessions", 0) == 0
    assert progress.get("shadow_comparison_windows", 0) == 0


def test_remediation_progress_backend_payload_uses_ledger_summary(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5)
    state = build_production_approval_state(
        candidate_paths={"metadata": str(tmp_path / "metadata.json"), "model": str(tmp_path / "model.pkl")},
        candidate_metadata={"model_status": "approved_for_shadow", "artifact_digest": "sha256:candidate"},
        runtime_validation={"ok": False, "reason": "production_evidence_required", "metadata": {"runtime_schema_version": "runtime-v1"}},
        runtime_paths={},
        user_id="alice",
    )
    remediation_state = _remediation_dashboard_state(state, [])
    assert remediation_state["current_counts"]["shadow_comparison_windows"] == 5
    assert "shadow_evidence_ledger" in remediation_state["progress_sources"]
    assert remediation_state["retry_allowed"] is True


def test_qml_does_not_compute_remediation_progress():
    qml = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "qml").rglob("*.qml"))
    # QML may display backend-provided remediation fields, but it must not
    # implement a local remediation-progress or readiness calculator.
    forbidden = [
        "function remediationProgress",
        "function remediation_progress",
        "var remediationProgress",
        "var remediation_progress",
        "function retryEligibility",
        "function productionReady",
        "function protectedSessionsAvailable",
    ]
    assert not any(item in qml for item in forbidden)
    assert re.search(r"\bproductionReady\s*=(?!=)", qml) is None
    assert re.search(r"\bprotectedSessionsAvailable\s*=(?!=)", qml) is None


def test_protected_sessions_still_unavailable_when_only_remediation_progress_completes(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5)
    state = build_production_approval_state(
        candidate_paths={"metadata": str(tmp_path / "metadata.json"), "model": str(tmp_path / "model.pkl")},
        candidate_metadata={"model_status": "approved_for_shadow", "artifact_digest": "sha256:candidate"},
        runtime_validation={"ok": False, "reason": "production_evidence_required", "metadata": {"runtime_schema_version": "runtime-v1"}},
        runtime_paths={},
        user_id="alice",
    )
    assert state["protectedSessionsAvailable"] is False
    assert state["productionReady"] is False
    assert state["production_evidence_summary"]["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value


def test_evidence_gate_partial_still_blocks_production(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, baseline_decision="")
    state = build_production_approval_state(
        candidate_paths={"metadata": str(tmp_path / "metadata.json"), "model": str(tmp_path / "model.pkl")},
        candidate_metadata={"model_status": "approved_for_shadow", "artifact_digest": "sha256:candidate"},
        runtime_validation={"ok": False, "reason": "production_evidence_required", "metadata": {"runtime_schema_version": "runtime-v1"}},
        runtime_paths={},
        user_id="alice",
    )
    assert state["productionEvidencePassed"] is False
    assert state["productionApprovalPassed"] is False
    assert state["protectedSessionsAvailable"] is False


def test_auto_training_can_receive_ledger_progress_without_starting_training(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5)
    plan = _plan()
    base_sessions = [
        {
            "session_id": str(i),
            "session_kind": "enrollment",
            "training_counts_toward_minimum": True,
            "metadata_trusted": True,
            "bucket": "accepted",
            "keyboard_rows": 20,
            "mouse_rows": 1,
        }
        for i in range(8)
    ]
    allowed, reason, signature = auto_training_should_start(
        settings={"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": True},
        profile={"training_can_start": True, "session_count": 8, "minimum_session_count": 8, "production_ready": False},
        runtime_state={},
        sessions=base_sessions,
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        remediation_plan=plan,
        production_evidence_summary=_summary(monkeypatch, tmp_path),
        now=1234.0,
    )
    assert allowed is True
    assert reason == "ready"
    assert signature


def test_runtime_payload_uses_ledger_remediation_progress(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5)
    state = build_production_approval_state(
        candidate_paths={"metadata": str(tmp_path / "metadata.json"), "model": str(tmp_path / "model.pkl")},
        candidate_metadata={"model_status": "approved_for_shadow", "artifact_digest": "sha256:candidate"},
        runtime_validation={"ok": False, "reason": "production_evidence_required", "metadata": {"runtime_schema_version": "runtime-v1"}},
        runtime_paths={},
        user_id="alice",
    )
    summary = state["production_evidence_summary"]
    assert summary["windows_collected"] == 5
    assert summary["remediation_progress"]["shadow_comparison_windows"] == 5
    remediation_state = _remediation_dashboard_state(state, [])
    assert remediation_state["current_counts"]["shadow_comparison_windows"] == 5
    assert remediation_state["retry_block_reason"] == ""


def test_dashboard_remediation_progress_moves_from_zero_when_valid_ledger_windows_exist(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 8)
    state = build_production_approval_state(
        candidate_paths={"metadata": str(tmp_path / "metadata.json"), "model": str(tmp_path / "model.pkl")},
        candidate_metadata={"model_status": "approved_for_shadow", "artifact_digest": "sha256:candidate"},
        runtime_validation={"ok": False, "reason": "production_evidence_required", "metadata": {"runtime_schema_version": "runtime-v1"}},
        runtime_paths={},
        user_id="alice",
    )
    remediation_state = _remediation_dashboard_state(state, [])
    assert remediation_state["required_counts"]["shadow_comparison_windows"] == 5
    assert remediation_state["ledger_new_evidence"]["shadow_comparison_windows"] == 8
    assert remediation_state["current_counts"]["shadow_comparison_windows"] == 5
    assert remediation_state["retry_allowed"] is True


def test_retry_eligibility_no_longer_blocked_by_shadow_comparison_when_ledger_requirement_complete(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5)
    allowed, reason, signature = auto_training_should_start(
        settings={"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": True},
        profile={"training_can_start": True, "session_count": 8, "minimum_session_count": 8, "production_ready": False},
        runtime_state={},
        sessions=[{"session_id": str(i), "session_kind": "enrollment", "training_counts_toward_minimum": True, "metadata_trusted": True, "bucket": "accepted", "keyboard_rows": 20, "mouse_rows": 1} for i in range(8)],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        remediation_plan=_plan(),
        production_evidence_summary=_summary(monkeypatch, tmp_path),
        now=1234.0,
    )
    assert allowed is True
    assert reason == "ready"
    assert signature


def test_retry_eligibility_moves_to_handoff_when_shadow_monitor_still_active(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5)
    allowed, reason, _signature = auto_training_should_start(
        settings={"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": True},
        profile={"training_can_start": True, "session_count": 8, "minimum_session_count": 8, "production_ready": False},
        runtime_state={"active": True, "session_kind": "shadow_evidence", "logger_process_alive": True, "monitor_process_alive": True},
        sessions=[{"session_id": str(i), "session_kind": "enrollment", "training_counts_toward_minimum": True, "metadata_trusted": True, "bucket": "accepted", "keyboard_rows": 20, "mouse_rows": 1} for i in range(8)],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="shadow_evidence_collecting",
        remediation_plan=_plan(),
        production_evidence_summary=_summary(monkeypatch, tmp_path),
        now=1234.0,
    )
    assert allowed is False
    assert reason == "shadow_evidence_handoff_required"


def test_short_unknown_and_invalid_shadow_windows_do_not_satisfy_remediation_requirement():
    records = [
        _record_payload(1, reason_codes=["short_window"]),
        _record_payload(2, reason_codes=["unknown"]),
        _record_payload(3, reason_codes=["invalid"]),
    ]
    progress = remediation_progress_from_evidence_records(
        records,
        candidate_artifact_digest="sha256:candidate",
        runtime_schema_version="runtime-v1",
    )
    assert progress["counts"].get("shadow_comparison_windows", 0) == 0
    assert "remediation_shadow_evidence_insufficient_quality" in progress["reason_codes"]


def test_stale_session_zero_does_not_override_ledger_shadow_progress(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 8)
    state = build_production_approval_state(
        candidate_paths={"metadata": str(tmp_path / "metadata.json"), "model": str(tmp_path / "model.pkl")},
        candidate_metadata={"model_status": "approved_for_shadow", "artifact_digest": "sha256:candidate"},
        runtime_validation={"ok": False, "reason": "production_evidence_required", "metadata": {"runtime_schema_version": "runtime-v1"}},
        runtime_paths={},
        user_id="alice",
    )
    state["current_new_evidence"] = {"shadow_comparison_windows": 0}
    state["evidence_progress"] = {"shadow_comparison_windows": 0}
    remediation_state = _remediation_dashboard_state(state, [])
    assert remediation_state["ledger_new_evidence"]["shadow_comparison_windows"] == 8
    assert remediation_state["session_new_evidence"] == {}
    assert remediation_state["current_counts"]["shadow_comparison_windows"] == 5
    assert remediation_state["retry_block_reason"] == ""


def test_retry_training_does_not_start_while_shadow_monitor_running(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5)
    allowed, reason, _signature = auto_training_should_start(
        settings={"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": True},
        profile={"training_can_start": True, "session_count": 8, "minimum_session_count": 8, "production_ready": False},
        runtime_state={"active": True, "session_kind": "shadow_evidence", "logger_process_alive": True, "monitor_process_alive": True},
        sessions=[{"session_id": str(i), "session_kind": "enrollment", "training_counts_toward_minimum": True, "metadata_trusted": True, "bucket": "accepted", "keyboard_rows": 20, "mouse_rows": 1} for i in range(8)],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="shadow_evidence_collecting",
        remediation_plan=_plan(),
        production_evidence_summary=_summary(monkeypatch, tmp_path),
        now=1234.0,
    )
    assert allowed is False
    assert reason == "shadow_evidence_handoff_required"


def test_qml_does_not_compute_remediation_progress_or_retry_eligibility():
    qml = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "qml").rglob("*.qml"))
    forbidden = [
        "function remediationProgress",
        "function remediation_progress",
        "var remediationProgress",
        "var remediation_progress",
        "function retryEligibility",
        "function retry_eligibility",
        "var retryEligibility",
        "var retry_eligibility",
        "function productionReady",
        "function protectedSessionsAvailable",
        "function evidencePass",
        "function evidenceFail",
    ]
    assert not any(item in qml for item in forbidden)
    assert re.search(r"\bproductionReady\s*=(?!=)", qml) is None
    assert re.search(r"\bprotectedSessionsAvailable\s*=(?!=)", qml) is None
