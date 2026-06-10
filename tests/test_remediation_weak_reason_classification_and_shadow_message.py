from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation_core.production_evidence import (
    ProductionEvidencePromotionEffect,
    ProductionEvidenceReasonCode,
    ProductionEvidenceStatus,
)
from metadata_core.auto_training_scheduler import auto_training_should_start
from metadata_core.production_approval import build_production_approval_state
from metadata_core.production_evidence_pipeline import (
    ProductionEvidenceRecord,
    append_evidence_record,
    remediation_progress_from_evidence_records,
)
from metadata_core.remediation_loop import build_remediation_plan, remediation_evidence_progress_from_summary


def _patch_evidence_dir(monkeypatch, tmp_path: Path) -> None:
    from metadata_core import production_evidence_pipeline as pipe
    evidence_root = tmp_path / "evidence"
    monkeypatch.setattr(pipe.paths, "evidence_dir", lambda: str(evidence_root))


def _record_payload(idx: int = 0, **overrides):
    payload = {
        "window_id": f"shadow-window-{idx}",
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


def _progress(records, *, candidate_digest: str = "sha256:candidate", runtime_schema: str = "runtime-v1"):
    return remediation_progress_from_evidence_records(records, candidate_artifact_digest=candidate_digest, runtime_schema_version=runtime_schema)


def _append_records(monkeypatch, tmp_path: Path, count: int, **overrides):
    _patch_evidence_dir(monkeypatch, tmp_path)
    records = []
    for idx in range(count):
        payload = _record_payload(idx, **overrides)
        records.append(append_evidence_record(payload["user_id"], ProductionEvidenceRecord.from_dict(payload)))
    return records


def _state(monkeypatch, tmp_path: Path):
    _patch_evidence_dir(monkeypatch, tmp_path)
    return build_production_approval_state(
        candidate_paths={"metadata": str(tmp_path / "metadata.json"), "model": str(tmp_path / "model.pkl")},
        candidate_metadata={"model_status": "approved_for_shadow", "artifact_digest": "sha256:candidate"},
        runtime_validation={"ok": False, "reason": "production_evidence_required", "metadata": {"runtime_schema_version": "runtime-v1"}},
        runtime_paths={},
        user_id="alice",
    )


def _summary(monkeypatch, tmp_path: Path):
    return _state(monkeypatch, tmp_path)["production_evidence_summary"]


def _plan():
    return build_remediation_plan(reason_codes=["insufficient_model_agreement"], candidate_artifact_digest="sha256:candidate")


def _scheduler(monkeypatch, tmp_path: Path, *, runtime_state: dict | None = None, session_flow: str = "idle"):
    return auto_training_should_start(
        settings={"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": True},
        profile={"training_can_start": True, "session_count": 8, "minimum_session_count": 8, "production_ready": False},
        runtime_state=runtime_state or {},
        sessions=[{"session_id": str(i), "session_kind": "enrollment", "training_counts_toward_minimum": True, "metadata_trusted": True, "bucket": "accepted", "keyboard_rows": 20, "mouse_rows": 1} for i in range(8)],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow=session_flow,
        remediation_plan=_plan(),
        production_evidence_summary=_summary(monkeypatch, tmp_path),
        now=1234.0,
    )


def _qml_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "qml").rglob("*.qml"))


def test_model_agreement_missing_reason_does_not_make_shadow_record_weak():
    progress = _progress([_record_payload(reason_codes=[ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA])])
    assert progress["counts"]["shadow_comparison_windows"] == 1
    assert "remediation_shadow_evidence_insufficient_quality" not in progress["reason_codes"]


def test_baseline_decision_missing_does_not_make_shadow_record_weak():
    progress = _progress([_record_payload(reason_codes=[ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING])])
    assert progress["counts"]["shadow_comparison_windows"] == 1
    assert "remediation_shadow_evidence_progress" in progress["reason_codes"]


def test_insufficient_model_agreement_data_does_not_block_remediation_window_progress():
    progress = _progress([_record_payload(reason_codes=[ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING, ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA])])
    assert progress["counts"]["shadow_comparison_windows"] == 1


def test_transition_window_still_blocks_remediation_window_progress():
    progress = _progress([_record_payload(reason_codes=["transition_window"])])
    assert progress["counts"]["shadow_comparison_windows"] == 0
    assert "remediation_shadow_evidence_insufficient_quality" in progress["reason_codes"]


def test_startup_window_still_blocks_remediation_window_progress():
    assert _progress([_record_payload(reason_codes=["startup_window"])])["counts"]["shadow_comparison_windows"] == 0


def test_insufficient_evidence_still_blocks_remediation_window_progress():
    assert _progress([_record_payload(reason_codes=["insufficient_evidence"])])["counts"]["shadow_comparison_windows"] == 0


def test_short_window_still_blocks_remediation_window_progress():
    assert _progress([_record_payload(reason_codes=["short_window"])])["counts"]["shadow_comparison_windows"] == 0


def test_low_quality_still_blocks_remediation_window_progress():
    assert _progress([_record_payload(reason_codes=["low_quality"])])["counts"]["shadow_comparison_windows"] == 0


def test_feature_quality_too_low_still_blocks_remediation_window_progress():
    assert _progress([_record_payload(reason_codes=["feature_quality_too_low"])])["counts"]["shadow_comparison_windows"] == 0


def test_shadow_evidence_records_without_baseline_can_reach_shadow_comparison_5_of_5(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, baseline_decision="", reason_codes=[ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING, ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA])
    progress = remediation_evidence_progress_from_summary(_summary(monkeypatch, tmp_path), _plan())
    assert progress["shadow_comparison_windows"] == 5


def test_missing_baseline_still_keeps_model_agreement_incomplete(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, baseline_decision="")
    model_agreement = _summary(monkeypatch, tmp_path)["model_agreement"]
    assert model_agreement["overall_agreement_rate"] == 0.0
    assert model_agreement["trusted_window_agreement_rate"] == 0.0


def test_missing_baseline_still_keeps_production_evidence_partial(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, baseline_decision="")
    summary = _summary(monkeypatch, tmp_path)
    assert summary["status"] == ProductionEvidenceStatus.PARTIAL.value
    assert summary["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value
    assert ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING in summary["reason_codes"]


def test_remediation_progress_complete_does_not_enable_protected_sessions(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, baseline_decision="")
    state = _state(monkeypatch, tmp_path)
    assert state["productionReady"] is False
    assert state["protectedSessionsAvailable"] is False


def test_retry_eligibility_moves_to_handoff_not_training_when_monitor_running(monkeypatch, tmp_path):
    _append_records(monkeypatch, tmp_path, 5, baseline_decision="")
    allowed, reason, _signature = _scheduler(monkeypatch, tmp_path, runtime_state={"active": True, "session_kind": "shadow_evidence", "logger_process_alive": True, "monitor_process_alive": True}, session_flow="shadow_evidence_collecting")
    assert allowed is False
    assert reason == "shadow_evidence_handoff_required"


def test_qml_shadow_mode_runtime_explanation_includes_simulated_lock_disabled_context():
    qml = (ROOT / "qml" / "components" / "LiveTelemetryPanel.qml").read_text(encoding="utf-8")
    assert "function runtimeIsShadowEvidenceMode" in qml
    assert "Shadow evidence is simulated only; lock enforcement is disabled in this mode." in qml
    assert "runtime.escalationPolicyText" in qml
    assert "runtime.evidenceWaitingReasonText" in qml


def test_qml_does_not_compute_remediation_progress():
    qml = _qml_text()
    forbidden = ["function remediationProgress", "function remediation_progress", "var remediationProgress", "var remediation_progress"]
    assert not any(item in qml for item in forbidden)


def test_qml_does_not_compute_production_readiness():
    qml = _qml_text()
    assert "function productionReady" not in qml
    assert "var productionReady" not in qml
    assert re.search(r"\bproductionReady\s*=(?!=)", qml) is None


def test_qml_does_not_compute_protected_sessions_available():
    qml = _qml_text()
    assert "function protectedSessionsAvailable" not in qml
    assert "var protectedSessionsAvailable" not in qml
    assert re.search(r"\bprotectedSessionsAvailable\s*=(?!=)", qml) is None
