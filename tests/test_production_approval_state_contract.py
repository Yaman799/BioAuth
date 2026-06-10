from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metadata_core.production_approval import (
    apply_production_approval_runtime_context,
    build_production_approval_state,
)
from evaluation_core.production_evidence import build_production_evidence_report


def _passing_production_evidence() -> dict:
    return build_production_evidence_report(
        candidate_artifact_digest="sha256:production-approval-contract-candidate",
        baseline_artifact_digest="sha256:production-approval-contract-baseline",
        evaluation_report_digest="sha256:production-approval-contract-eval",
        runtime_schema_version="runtime-schema-v1",
        model_comparison_windows=[
            {"window_id": f"w{idx}", "candidate_decision": "trusted", "baseline_decision": "trusted", "trusted_window": True}
            for idx in range(4)
        ],
        post_unlock_windows=[
            {"window_id": f"u{idx}", "trusted_window": True, "warning_triggered": False, "simulated_false_lock": False, "feature_quality_ok": True}
            for idx in range(3)
        ],
        confirmed_intruder_events=[],
        runtime_decision_summaries=[
            {"decision_id": f"r{idx}", "truth": "owner", "candidate_decision": "trusted", "unknown": False, "simulated_false_lock": False, "feature_quality_ok": True}
            for idx in range(4)
        ],
    ).to_dict()


def _metadata(
    status: str,
    *,
    reason: str = "",
    far: float | None = None,
    frr: float | None = None,
    gate_far: bool | None = None,
    gate_frr: bool | None = None,
    far_threshold: float | None = None,
    frr_threshold: float | None = None,
) -> dict:
    policy_metrics = {}
    if far is not None:
        policy_metrics["far"] = far
    if frr is not None:
        policy_metrics["frr"] = frr
    gate_results = {}
    if gate_far is not None:
        gate_results["far"] = gate_far
    if gate_frr is not None:
        gate_results["frr"] = gate_frr
    thresholds = {}
    if far_threshold is not None:
        thresholds["far_threshold"] = far_threshold
    if frr_threshold is not None:
        thresholds["frr_threshold"] = frr_threshold
    payload = {
        "model_status": status,
        "approval_reason": reason,
        "policy_metrics": policy_metrics,
        "policy_thresholds": thresholds,
        "policy_details": {"gate_results": gate_results},
    }
    if status == "approved_for_production":
        payload.update({
            "candidate_artifact_digest": "sha256:production-approval-contract-candidate",
            "baseline_artifact_digest": "sha256:production-approval-contract-baseline",
            "evaluation_report_digest": "sha256:production-approval-contract-eval",
            "runtime_schema_version": "runtime-schema-v1",
            "rollback_ready": True,
        })
        payload["production_evidence"] = _passing_production_evidence()
    return payload


def _state(metadata: dict | None, *, runtime_ok: bool = False, runtime_reason: str = "runtime_pointer_missing", **kwargs) -> dict:
    return build_production_approval_state(
        candidate_paths={},
        candidate_metadata=metadata,
        runtime_validation={"ok": runtime_ok, "reason": runtime_reason, "metadata": metadata or {}},
        runtime_paths={"base": "/tmp/runtime"} if runtime_ok else {},
        **kwargs,
    )


def test_no_candidate_returns_no_candidate_model() -> None:
    state = _state(None)
    assert state["status"] == "none"
    assert state["phase"] == "no_candidate"
    assert state["candidate_status"] == "none"
    assert state["reason_code"] == "no_candidate_model"
    assert state["protected_sessions_available"] is False
    assert state["protectedSessionsAvailable"] is False


def test_training_active_returns_training_in_progress() -> None:
    state = _state(None, training_active=True)
    assert state["status"] == "pending"
    assert state["phase"] == "training"
    assert state["reason_code"] == "training_in_progress"
    assert state["protected_sessions_available"] is False


def test_runtime_overlay_reports_evaluation_in_progress_without_unlocking() -> None:
    base = _state(_metadata("approved_for_shadow"))
    state = apply_production_approval_runtime_context(base, evaluation_active=True, shadow_status={"total_eval_count": 1})
    assert state["phase"] == "offline_approval"
    assert state["reason_code"] == "evaluation_in_progress"
    assert state["protected_sessions_available"] is False
    assert state["protectedSessionsAvailable"] is False


def test_offline_rejected_candidate_returns_rejection_reason_and_metrics() -> None:
    state = _state(_metadata("rejected", reason="Candidate did not meet offline gates.", far=0.07, frr=0.44))
    assert state["status"] == "blocked"
    assert state["phase"] == "offline_approval"
    assert state["candidate_status"] == "rejected"
    assert state["reason_code"] == "offline_approval_rejected"
    assert state["reason_text"] == "Candidate did not meet offline gates."
    assert state["far"] == 0.07
    assert state["frr"] == 0.44
    assert state["next_action"] == "retrain_after_more_data"


def test_far_frr_specific_blockers_are_reported_without_threshold_changes() -> None:
    far_state = _state(_metadata("rejected", far=0.31, frr=0.10, gate_far=False, gate_frr=True, far_threshold=0.25, frr_threshold=0.35))
    assert far_state["reason_code"] == "far_too_high"
    assert far_state["far"] == 0.31
    assert far_state["far_threshold"] == 0.25
    assert far_state["frr_threshold"] == 0.35

    frr_state = _state(_metadata("rejected", far=0.05, frr=0.41, gate_far=True, gate_frr=False, far_threshold=0.25, frr_threshold=0.35))
    assert frr_state["reason_code"] == "frr_too_high"
    assert frr_state["frr"] == 0.41
    assert frr_state["frr_threshold"] == 0.35


def test_approved_for_shadow_only_keeps_protected_sessions_unavailable() -> None:
    state = _state(_metadata("approved_for_shadow", reason="Approved for shadow only."))
    assert state["status"] == "pending"
    assert state["phase"] == "shadow_validation"
    assert state["candidate_status"] == "approved_for_shadow"
    assert state["reason_code"] in {"approved_for_shadow_only", "shadow_validation_not_started"}
    assert state["protected_sessions_available"] is False
    assert state["productionReady"] is False


def test_insufficient_shadow_evidence_reports_windows_and_progress() -> None:
    state = _state(
        _metadata("approved_for_shadow"),
        shadow_status={"windows_collected": 2, "windows_required": 8},
    )
    assert state["reason_code"] == "insufficient_shadow_windows"
    assert state["windows_collected"] == 2
    assert state["windows_required"] == 8
    assert state["progress_percent"] == 25
    assert state["protected_sessions_available"] is False


def test_shadow_validation_in_progress_reports_backend_evidence() -> None:
    state = _state(
        _metadata("approved_for_shadow"),
        shadow_status={"total_eval_count": 9, "required_eval_count": 8},
    )
    assert state["reason_code"] == "shadow_validation_in_progress"
    assert state["windows_collected"] == 9
    assert state["windows_required"] == 8
    assert state["protectedSessionsAvailable"] is False


def test_production_ready_only_when_backend_runtime_validation_is_true() -> None:
    blocked = _state(_metadata("approved_for_production"), runtime_ok=False, runtime_reason="runtime_pointer_missing")
    assert blocked["status"] == "blocked"
    assert blocked["reason_code"] == "runtime_bundle_invalid"
    assert blocked["protected_sessions_available"] is False

    ready = _state(_metadata("approved_for_production"), runtime_ok=True, runtime_reason="ok")
    assert ready["status"] == "approved"
    assert ready["phase"] == "production_ready"
    assert ready["candidate_status"] == "production_ready"
    assert ready["reason_code"] == "production_ready"
    assert ready["protected_sessions_available"] is True
    assert ready["protectedSessionsAvailable"] is True


def test_auto_promotion_disabled_explains_block_without_changing_gate() -> None:
    state = _state(_metadata("approved_for_production"), runtime_ok=False, auto_promotion_enabled=False)
    assert state["reason_code"] == "auto_promotion_disabled"
    assert state["protected_sessions_available"] is False
    assert state["next_action"] == "manual_review_required"


def test_missing_metrics_do_not_crash_or_invent_thresholds() -> None:
    state = _state(_metadata("approved_for_shadow"))
    assert state["far"] is None
    assert state["frr"] is None
    assert state["far_threshold"] is None
    assert state["frr_threshold"] is None
    assert state["protected_sessions_available"] is False


def test_metrics_from_evaluation_report_are_reported_when_available() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        report = Path(tmpdir) / "evaluation_report.json"
        summary = Path(tmpdir) / "evaluation_summary.json"
        report.write_text(json.dumps({
            "evaluations": {"candidate_bundle": {"metrics": {"far": 0.03, "frr": 0.12}}},
            "policy_thresholds": {"far_threshold": 0.10, "frr_threshold": 0.20},
        }), encoding="utf-8")
        summary.write_text("{}", encoding="utf-8")
        state = build_production_approval_state(
            candidate_paths={"evaluation_report": str(report), "evaluation_summary": str(summary)},
            candidate_metadata=_metadata("approved_for_shadow"),
            runtime_validation={"ok": False, "reason": "runtime_pointer_missing"},
        )
    assert state["far"] == 0.03
    assert state["frr"] == 0.12
    assert state["far_threshold"] == 0.10
    assert state["frr_threshold"] == 0.20


def test_qml_backend_exposure_remains_backend_owned() -> None:
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    qml = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "qml").rglob("*.qml"))
    assert "def productionApprovalState" in desktop
    assert "apply_production_approval_runtime_context" in desktop
    assert "backend.productionApprovalState" in qml
    assert "productionApprovalState:" not in qml
    assert "protectedSessionsAvailable:" not in qml
    assert "productionReady:" not in qml


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("13 focused production approval state contract tests passed", flush=True)
