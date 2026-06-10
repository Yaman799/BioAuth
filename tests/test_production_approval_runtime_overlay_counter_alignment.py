from __future__ import annotations

import json
import re
from pathlib import Path

from evaluation_core.production_evidence import (
    ProductionEvidencePromotionEffect,
    ProductionEvidenceReasonCode,
    ProductionEvidenceStatus,
    assert_privacy_safe_payload,
)
from metadata_core.production_approval import (
    apply_production_approval_runtime_context,
    build_production_approval_state,
)
from metadata_core.production_evidence_pipeline import ProductionEvidenceRecord
from bridge.runtime_labels import runtime_policy_display_fields

ROOT = Path(__file__).resolve().parent.parent


def _patch_evidence_dir(monkeypatch, tmp_path: Path) -> None:
    from metadata_core import production_evidence_pipeline as pipe

    evidence_root = tmp_path / "evidence"
    monkeypatch.setattr(pipe.paths, "evidence_dir", lambda: str(evidence_root))


def _append_record(monkeypatch, tmp_path: Path, **overrides):
    _patch_evidence_dir(monkeypatch, tmp_path)
    from metadata_core import production_evidence_pipeline as pipe

    payload = {
        "window_id": overrides.pop("window_id", "window-1"),
        "user_id": overrides.pop("user_id", "alice"),
        "candidate_artifact_digest": overrides.pop("candidate_artifact_digest", "sha256:candidate"),
        "baseline_artifact_digest": overrides.pop("baseline_artifact_digest", ""),
        "runtime_schema_version": overrides.pop("runtime_schema_version", "runtime-v1"),
        "feature_schema_version": overrides.pop("feature_schema_version", "runtime-v1"),
        "candidate_decision": overrides.pop("candidate_decision", "legit"),
        "baseline_decision": overrides.pop("baseline_decision", ""),
        "candidate_risk_bucket": overrides.pop("candidate_risk_bucket", "low"),
        "baseline_risk_bucket": overrides.pop("baseline_risk_bucket", "unknown"),
        "candidate_would_lock_if_production": overrides.pop("candidate_would_lock_if_production", False),
        "baseline_would_lock_if_production": overrides.pop("baseline_would_lock_if_production", False),
        "is_trusted_window": overrides.pop("is_trusted_window", True),
        "trusted_anchor_type": overrides.pop("trusted_anchor_type", "runtime_monitor"),
        "is_post_unlock_window": overrides.pop("is_post_unlock_window", False),
        "is_confirmed_intruder_window": overrides.pop("is_confirmed_intruder_window", False),
        "feature_quality_ok": overrides.pop("feature_quality_ok", True),
        "unknown_or_abstain": overrides.pop("unknown_or_abstain", False),
        "schema_ok": overrides.pop("schema_ok", True),
        "source": overrides.pop("source", "shadow_evidence_monitor"),
        "reason_codes": overrides.pop("reason_codes", []),
    }
    payload.update(overrides)
    return pipe.append_evidence_record(payload["user_id"], ProductionEvidenceRecord.from_dict(payload))


def _build_state(monkeypatch, tmp_path: Path, *, candidate_digest: str = "sha256:candidate", runtime_schema: str = "runtime-v1", shadow_status=None):
    _patch_evidence_dir(monkeypatch, tmp_path)
    metadata_file = tmp_path / "candidate_metadata.json"
    metadata_file.write_text("{}", encoding="utf-8")
    return build_production_approval_state(
        candidate_paths={"metadata": str(metadata_file), "model": str(tmp_path / "model.pkl")},
        candidate_metadata={"model_status": "approved_for_shadow", "artifact_digest": candidate_digest},
        runtime_validation={"ok": False, "reason": "production_evidence_required", "metadata": {"runtime_schema_version": runtime_schema}},
        runtime_paths={},
        user_id="alice",
        shadow_status=shadow_status or {},
    )


def _ledger_overlay_payload(windows: int = 410, *, reason_codes=None, status="partial"):
    reason_codes = list(reason_codes or [
        ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING,
        ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA,
        ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PARTIAL,
    ])
    return {
        "modelStatus": "approved_for_shadow",
        "productionReady": False,
        "protectedSessionsAvailable": False,
        "productionApprovalPassed": False,
        "productionEvidencePassed": False,
        "evaluationReportAvailable": True,
        "runtimeValidationReason": "production_evidence_required",
        "failedProductionGates": ["production_evidence_partial"],
        "productionEvidenceSummary": {
            "source": "shadow_evidence_monitor",
            "status": status,
            "promotion_effect": "shadow_only",
            "allows_production_eligibility": False,
            "windows_collected": windows,
            "records_total": windows,
            "records_accepted": windows,
            "reason_codes": reason_codes,
            "model_agreement": {
                "overall_agreement_rate": 0.0,
                "trusted_window_agreement_rate": 0.0,
                "critical_disagreement_count": 0,
                "high_risk_disagreement_count": 0,
            },
        },
    }


def test_runtime_overlay_preserves_ledger_windows_collected():
    payload = _ledger_overlay_payload(410)
    result = apply_production_approval_runtime_context(payload, shadow_status={"windows_collected": 0, "shadow_windows_collected": 0})
    assert result["windows_collected"] == 410
    assert result["windowsCollected"] == 410


def test_runtime_overlay_does_not_reset_ledger_windows_to_zero():
    payload = _ledger_overlay_payload(12)
    result = apply_production_approval_runtime_context(payload, shadow_status={"phase": "collecting", "window_count": 0})
    assert result["windows_collected"] == 12
    assert result["reason_code"] != "shadow_validation_not_started"


def test_runtime_overlay_replaces_shadow_not_started_when_ledger_evidence_exists():
    payload = _ledger_overlay_payload(5)
    result = apply_production_approval_runtime_context(payload, shadow_status={"windows_collected": 0})
    assert result["reason_code"] == "production_evidence_partial"
    assert result["reasonCode"] == "production_evidence_partial"


def test_ledger_evidence_partial_keeps_protected_sessions_unavailable():
    result = apply_production_approval_runtime_context(_ledger_overlay_payload(8), shadow_status={"windows_collected": 0})
    assert result["protected_sessions_available"] is False
    assert result["protectedSessionsAvailable"] is False
    assert result["productionReady"] is False


def test_ledger_evidence_partial_keeps_status_pending():
    result = apply_production_approval_runtime_context(_ledger_overlay_payload(8), shadow_status={"windows_collected": 0})
    assert result["status"] == "pending"
    assert result["phase"] == "shadow_validation"


def test_ledger_evidence_missing_baseline_keeps_model_agreement_partial(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path, baseline_decision="")
    state = _build_state(monkeypatch, tmp_path, shadow_status={"windows_collected": 0})
    summary = state["production_evidence_summary"]
    assert summary["status"] == ProductionEvidenceStatus.PARTIAL.value
    assert summary["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value
    assert ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING in summary["reason_codes"]


def test_ledger_evidence_missing_baseline_does_not_fake_agreement(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path, baseline_decision="")
    state = _build_state(monkeypatch, tmp_path, shadow_status={"windows_collected": 0})
    model_agreement = state["production_evidence_summary"]["model_agreement"]
    assert model_agreement["overall_agreement_rate"] == 0.0
    assert model_agreement["trusted_window_agreement_rate"] == 0.0


def test_production_evidence_summary_reason_codes_preserved_after_runtime_overlay():
    payload = _ledger_overlay_payload(9, reason_codes=["baseline_decision_missing", "insufficient_model_agreement_data"])
    result = apply_production_approval_runtime_context(payload, shadow_status={"windows_collected": 0})
    assert "baseline_decision_missing" in result["productionEvidenceSummary"]["reason_codes"]
    assert "insufficient_model_agreement_data" in result["productionEvidenceSummary"]["reason_codes"]
    assert result["reason_code"] == "production_evidence_partial"


def test_shadow_loop_zero_does_not_override_ledger_evidence_count(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path, window_id="ledger-window")
    state = _build_state(monkeypatch, tmp_path, shadow_status={"windows_collected": 0, "shadow_windows_collected": 0})
    assert state["windows_collected"] == 1
    assert state["windowsCollected"] == 1
    assert state["reason_code"] != "shadow_validation_not_started"


def test_no_ledger_records_can_still_report_shadow_validation_not_started(monkeypatch, tmp_path):
    state = _build_state(monkeypatch, tmp_path, shadow_status={"windows_collected": 0})
    assert state["windows_collected"] == 0
    assert state["reason_code"] == "shadow_validation_not_started"


def test_candidate_digest_mismatch_is_ignored_as_stale_shadow_evidence(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path, candidate_artifact_digest="sha256:other")
    state = _build_state(monkeypatch, tmp_path, candidate_digest="sha256:candidate")
    summary = state["production_evidence_summary"]
    assert summary["windows_collected"] == 0
    assert summary["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value
    assert ProductionEvidenceReasonCode.CANDIDATE_DIGEST_MISMATCH not in summary["reason_codes"]
    assert summary["records_ignored_for_candidate_digest"] == 1


def test_runtime_schema_mismatch_is_ignored_as_stale_shadow_evidence(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path, runtime_schema_version="runtime-old")
    state = _build_state(monkeypatch, tmp_path, runtime_schema="runtime-v1")
    summary = state["production_evidence_summary"]
    assert summary["windows_collected"] == 0
    assert summary["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value
    assert ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH not in summary["reason_codes"]
    assert summary["records_ignored_for_runtime_schema"] == 1


def test_qml_does_not_compute_windows_collected_or_reason_code():
    qml = "\n".join(path.read_text(errors="ignore") for path in (ROOT / "qml").rglob("*.qml"))
    forbidden = r"(var|let|const|function)\s+(windows_collected|windowsCollected|reason_code|reasonCode)\b|(?:windows_collected|windowsCollected|reason_code|reasonCode)\s*:"
    assert not re.search(forbidden, qml)


def test_runtime_label_shadow_evidence_still_not_live_protected():
    display = runtime_policy_display_fields(
        {"active": True, "session_kind": "shadow_evidence", "status": "shadow_evidence", "decision": "legit", "runtime_window_count": 3, "runtime_locking_allowed": False},
        flow="shadow_evidence_collecting",
        active=True,
        monitor_ready=True,
        monitor_heartbeat_fresh=True,
        capture_fresh=True,
    )
    assert "Live protected" not in display["runtimeDisplayText"]
    assert display["runtimeDisplayText"].startswith("Shadow evidence")


def test_existing_protected_production_ready_payload_unchanged():
    result = apply_production_approval_runtime_context(
        {
            "modelStatus": "approved_for_production",
            "productionReady": True,
            "protectedSessionsAvailable": True,
            "productionApprovalPassed": True,
            "runtimeValidationReason": "ok",
            "evaluationReportAvailable": True,
        },
        shadow_status={"windows_collected": 0},
    )
    assert result["status"] == "approved"
    assert result["phase"] == "production_ready"
    assert result["reason_code"] == "production_ready"
    assert result["protectedSessionsAvailable"] is True


def test_evidence_pass_still_does_not_directly_unlock_protected_sessions():
    payload = _ledger_overlay_payload(
        20,
        reason_codes=[ProductionEvidenceReasonCode.PRODUCTION_EVIDENCE_PASSED],
        status="pass",
    )
    payload["productionEvidencePassed"] = True
    payload["productionEvidenceSummary"]["allows_production_eligibility"] = True
    result = apply_production_approval_runtime_context(payload, shadow_status={"windows_collected": 0})
    assert result["modelStatus"] == "approved_for_shadow"
    assert result["protectedSessionsAvailable"] is False
    assert result["productionReady"] is False


def test_auto_enrollment_still_does_not_decide_readiness():
    auto_source = (ROOT / "metadata_core" / "auto_enrollment.py").read_text(errors="ignore")
    assert "productionReady" not in auto_source
    assert "protectedSessionsAvailable" not in auto_source
    assert "build_production_approval_state" not in auto_source


def test_training_passive_shadow_evidence_mutual_exclusion_still_holds():
    source = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(errors="ignore")
    block_fn = source[source.index("def _shadow_evidence_block_reason"):source.index("def start_shadow_evidence_monitor")]
    assert "training_active" in block_fn
    assert "evaluation_active" in block_fn
    assert "passive_auto_enrollment_active" in block_fn
    assert "protected_session_active" in block_fn


def test_overlay_payload_has_no_raw_biometric_fields():
    result = apply_production_approval_runtime_context(_ledger_overlay_payload(3), shadow_status={"windows_collected": 0})
    assert_privacy_safe_payload(result)
    text = json.dumps(result).lower()
    for forbidden in ("raw_keyboard", "raw_mouse", "feature_vector", "feature_values", "raw_samples", "raw_events"):
        assert forbidden not in text
