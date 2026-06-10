from __future__ import annotations

import json
from pathlib import Path

from evaluation_core.production_evidence import (
    ProductionEvidencePromotionEffect,
    ProductionEvidenceReasonCode,
    ProductionEvidenceStatus,
    assert_privacy_safe_payload,
)
from metadata_core.production_approval import build_production_approval_state
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


def _state(monkeypatch, tmp_path: Path, *, candidate_digest: str = "sha256:candidate", runtime_schema: str = "runtime-v1", shadow_status=None):
    _patch_evidence_dir(monkeypatch, tmp_path)
    return build_production_approval_state(
        candidate_paths={"metadata": str(tmp_path / "metadata.json"), "model": str(tmp_path / "model.pkl")},
        candidate_metadata={"model_status": "approved_for_shadow", "artifact_digest": candidate_digest},
        runtime_validation={"ok": False, "reason": "production_evidence_required", "metadata": {"runtime_schema_version": runtime_schema}},
        runtime_paths={},
        user_id="alice",
        shadow_status=shadow_status or {},
    )


def _summary(state):
    return state["production_evidence_summary"]


def test_shadow_evidence_ledger_records_update_windows_collected(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path)
    state = _state(monkeypatch, tmp_path)
    assert state["windows_collected"] == 1
    assert state["windowsCollected"] == 1
    assert state["reason_code"] != "shadow_validation_not_started"


def test_shadow_evidence_ledger_feeds_production_evidence_summary(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path)
    summary = _summary(_state(monkeypatch, tmp_path))
    assert summary["source"] == "shadow_evidence_monitor"
    assert summary["windows_collected"] == 1
    assert summary["runtime_safety"]["unknown_rate"] == 0.0
    assert summary["post_unlock_evidence"]["feature_quality_rate"] == 1.0


def test_shadow_evidence_without_baseline_keeps_model_agreement_partial(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path, baseline_decision="")
    summary = _summary(_state(monkeypatch, tmp_path))
    assert summary["status"] == ProductionEvidenceStatus.PARTIAL.value
    assert summary["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value
    assert ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING in summary["reason_codes"]


def test_shadow_evidence_without_baseline_does_not_fake_agreement(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path, baseline_decision="")
    model_agreement = _summary(_state(monkeypatch, tmp_path))["model_agreement"]
    assert model_agreement["overall_agreement_rate"] == 0.0
    assert model_agreement["trusted_window_agreement_rate"] == 0.0


def test_shadow_evidence_candidate_digest_mismatch_keeps_shadow_only(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path, candidate_artifact_digest="sha256:other")
    summary = _summary(_state(monkeypatch, tmp_path, candidate_digest="sha256:candidate"))
    assert summary["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value
    assert ProductionEvidenceReasonCode.CANDIDATE_DIGEST_MISMATCH in summary["reason_codes"]
    assert summary["windows_collected"] == 0


def test_shadow_evidence_runtime_schema_mismatch_keeps_shadow_only(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path, runtime_schema_version="runtime-old")
    summary = _summary(_state(monkeypatch, tmp_path, runtime_schema="runtime-v1"))
    assert summary["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value
    assert ProductionEvidenceReasonCode.RUNTIME_SCHEMA_MISMATCH in summary["reason_codes"]
    assert summary["windows_collected"] == 0


def test_shadow_evidence_low_quality_windows_not_counted_as_positive(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path, feature_quality_ok=False)
    summary = _summary(_state(monkeypatch, tmp_path))
    assert summary["windows_collected"] == 1
    assert summary["post_unlock_evidence"]["feature_quality_rate"] == 0.0
    assert ProductionEvidenceReasonCode.FEATURE_QUALITY_TOO_LOW in summary["reason_codes"]
    assert summary["promotion_effect"] == ProductionEvidencePromotionEffect.SHADOW_ONLY.value


def test_shadow_evidence_valid_quality_windows_increment_safe_counters(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path, feature_quality_ok=True)
    summary = _summary(_state(monkeypatch, tmp_path))
    assert summary["records_accepted"] == 1
    assert summary["runtime_safety"]["unknown_rate"] == 0.0
    assert summary["post_unlock_evidence"]["feature_quality_rate"] == 1.0


def test_shadow_evidence_production_approval_preserves_existing_reason_codes(monkeypatch, tmp_path):
    existing = {
        "schema_version": 1,
        "candidate_artifact_digest": "sha256:candidate",
        "baseline_artifact_digest": "",
        "evaluation_report_digest": "",
        "runtime_schema_version": "runtime-v1",
        "model_agreement": {},
        "post_unlock_evidence": {},
        "confirmed_intruder_evidence": {},
        "runtime_safety": {},
        "gate": {"status": "partial", "promotion_effect": "shadow_only", "reason_codes": ["production_evidence_missing"]},
    }
    _append_record(monkeypatch, tmp_path)
    state = build_production_approval_state(
        candidate_paths={"metadata": str(tmp_path / "metadata.json")},
        candidate_metadata={"model_status": "approved_for_shadow", "artifact_digest": "sha256:candidate", "production_evidence": existing},
        runtime_validation={"ok": False, "reason": "production_evidence_required", "metadata": {"runtime_schema_version": "runtime-v1"}},
        runtime_paths={},
        user_id="alice",
    )
    codes = state["production_evidence_summary"]["reason_codes"]
    assert "production_evidence_missing" in codes
    assert ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING in codes


def test_shadow_evidence_evidence_pass_still_does_not_unlock_protected_sessions(monkeypatch, tmp_path):
    for idx in range(3):
        _append_record(monkeypatch, tmp_path, window_id=f"w{idx}", baseline_decision="legit", baseline_risk_bucket="low", is_post_unlock_window=True)
    state = _state(monkeypatch, tmp_path)
    assert state["productionEvidencePassed"] in {True, False}
    assert state["protectedSessionsAvailable"] is False
    assert state["productionReady"] is False


def test_shadow_evidence_approved_for_shadow_never_sets_protected_sessions_available(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path)
    state = _state(monkeypatch, tmp_path)
    assert state["modelStatus"] == "approved_for_shadow"
    assert state["protectedSessionsAvailable"] is False
    assert state["productionReady"] is False


def test_shadow_evidence_dashboard_state_backend_owned():
    source = (ROOT / "metadata_core" / "dashboard.py").read_text()
    qml = "\n".join(p.read_text() for p in (ROOT / "qml").rglob("*.qml"))
    assert "user_id=safe" in source
    assert "build_production_approval_state" in source
    assert "function productionReady" not in qml
    assert "function protectedSessionsAvailable" not in qml


def test_runtime_label_protected_mode_still_says_live_protected():
    display = runtime_policy_display_fields({"active": True, "session_kind": "protected", "status": "ok", "decision": "legit", "runtime_window_count": 3, "runtime_quality_lock_ok_windows": 3}, flow="protected_active", active=True, monitor_ready=True, monitor_heartbeat_fresh=True, capture_fresh=True)
    assert display["runtimeDisplayText"] == "Live protected · Legit"


def test_runtime_label_shadow_evidence_mode_does_not_say_live_protected():
    display = runtime_policy_display_fields({"active": True, "session_kind": "shadow_evidence", "status": "shadow_evidence", "decision": "legit", "runtime_window_count": 3, "runtime_quality_lock_ok_windows": 3, "runtime_locking_allowed": False}, flow="shadow_evidence_collecting", active=True, monitor_ready=True, monitor_heartbeat_fresh=True, capture_fresh=True)
    assert "Live protected" not in display["runtimeDisplayText"]
    assert display["canLockNow"] is False


def test_runtime_label_shadow_evidence_uses_shadow_wording():
    display = runtime_policy_display_fields({"active": True, "session_kind": "shadow_evidence", "decision": "suspicious", "runtime_window_count": 3, "runtime_quality_lock_ok_windows": 3, "runtime_locking_allowed": False}, flow="shadow_evidence_collecting", active=True, monitor_ready=True, monitor_heartbeat_fresh=True, capture_fresh=True)
    assert display["runtimeDisplayText"].startswith("Shadow evidence")
    assert "simulated" in display["runtimeDisplayText"].lower()


def test_qml_does_not_compute_production_ready_or_protected_sessions_available():
    qml = "\n".join(p.read_text() for p in (ROOT / "qml").rglob("*.qml"))
    assert "function productionReady" not in qml
    assert "function protectedSessionsAvailable" not in qml
    assert "var productionReady" not in qml
    assert "var protectedSessionsAvailable" not in qml


def test_qml_does_not_compute_evidence_readiness():
    qml = "\n".join(p.read_text() for p in (ROOT / "qml").rglob("*.qml"))
    assert "allows_production_eligibility" not in qml
    assert "productionEvidencePassed =" not in qml
    assert "evidencePass" not in qml


def test_shadow_evidence_no_raw_biometric_fields_in_dashboard_payload(monkeypatch, tmp_path):
    _append_record(monkeypatch, tmp_path)
    state = _state(monkeypatch, tmp_path)
    assert_privacy_safe_payload(state)
    text = json.dumps(state).lower()
    for forbidden in ("raw_keyboard", "raw_mouse", "feature_vector", "feature_values", "biometric_features"):
        assert forbidden not in text


def test_shadow_evidence_monitor_collection_does_not_start_training():
    source = (ROOT / "bridge" / "session_runtime_helpers.py").read_text()
    shadow_fn = source[source.index("def start_shadow_evidence_monitor"):source.index("def maybe_start_shadow_evidence_monitor")]
    assert "start_training" not in shadow_fn
    assert "train" not in shadow_fn.lower().replace("training_active", "")


def test_training_passive_and_shadow_evidence_mutual_exclusion_still_holds():
    source = (ROOT / "bridge" / "session_runtime_helpers.py").read_text()
    block_fn = source[source.index("def _shadow_evidence_block_reason"):source.index("def start_shadow_evidence_monitor")]
    assert "training_active" in block_fn
    assert "evaluation_active" in block_fn
    assert "passive_auto_enrollment_active" in block_fn
    assert "protected_session_active" in block_fn
