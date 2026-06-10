from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridge.refresh_dashboard_helpers import status_for_dashboard
from metadata_core.production_approval import build_production_approval_state
from evaluation_core.production_evidence import build_production_evidence_report


class _DummyBridge:
    _training_in_progress = False
    _training_progress = {}
    _history_sync_pending = False
    _last_training_failed = False
    _last_training_failure_message = ""
    _last_training_failure_tone = "danger"

    def _t(self, key: str, **kwargs) -> str:
        strings = {
            "status_banner_ready": "Protected Sessions are ready.",
            "status_banner_runtime_rejected": "Training finished, but the candidate model was rejected by offline approval checks.",
            "status_banner_runtime_shadow": "Training finished, but the candidate model is approved for shadow validation only.",
            "status_banner_runtime_evaluating": "Training finished, and offline approval is still pending.",
            "status_banner_runtime_pending": "Training finished, but no production-approved runtime bundle is active yet.",
            "guide_training_ready": "Ready to train.",
            "training_need_higher_quality_sessions": "Need higher quality sessions.",
            "status_banner_collecting": "Capturing behavior.",
            "training_stage_evaluating_model": "Evaluating candidate model.",
        }
        return strings.get(key, key).format(**kwargs)


def _passing_production_evidence() -> dict:
    return build_production_evidence_report(
        candidate_artifact_digest="sha256:shadow-regression-candidate",
        baseline_artifact_digest="sha256:shadow-regression-baseline",
        evaluation_report_digest="sha256:shadow-regression-eval",
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


def _metadata(status: str, **extra) -> dict:
    payload = {"model_status": status}
    if status == "approved_for_production" and "production_evidence" not in extra:
        payload.update({
            "candidate_artifact_digest": "sha256:shadow-regression-candidate",
            "baseline_artifact_digest": "sha256:shadow-regression-baseline",
            "evaluation_report_digest": "sha256:shadow-regression-eval",
            "runtime_schema_version": "runtime-schema-v1",
            "rollback_ready": True,
        })
        payload["production_evidence"] = _passing_production_evidence()
    payload.update(extra)
    return payload


def test_dashboard_status_prefers_backend_shadow_reason_over_generic_banner() -> None:
    profile = {
        "ready": True,
        "candidate_model_status": "approved_for_shadow",
        "production_approval_state": {
            "status": "pending",
            "phase": "shadow_validation",
            "candidate_status": "approved_for_shadow",
            "reason_code": "insufficient_shadow_windows",
            "protected_sessions_available": False,
            "windows_collected": 3,
            "windows_required": 8,
        },
    }
    message, tone = status_for_dashboard(_DummyBridge(), profile, {"flow": "idle"})
    assert tone == "warn"
    assert "approved for shadow validation only" in message
    assert "3/8" in message
    assert "Protected Sessions remain unavailable" in message


def test_dashboard_status_for_offline_rejected_surfaces_reason_code() -> None:
    profile = {
        "ready": True,
        "candidate_model_status": "rejected",
        "production_approval_state": {
            "status": "blocked",
            "phase": "offline_approval",
            "candidate_status": "rejected",
            "reason_code": "far_too_high",
            "protected_sessions_available": False,
        },
    }
    message, tone = status_for_dashboard(_DummyBridge(), profile, {"flow": "idle"})
    assert tone == "warn"
    assert "rejected by offline approval checks" in message
    assert "far_too_high" in message


def test_backend_keeps_shadow_only_protected_sessions_unavailable() -> None:
    state = build_production_approval_state(
        candidate_paths={},
        candidate_metadata=_metadata("approved_for_shadow"),
        runtime_validation={"ok": False, "reason": "runtime_pointer_missing"},
        shadow_status={"windows_collected": 170, "windows_required": 600},
    )
    assert state["candidate_status"] == "approved_for_shadow"
    assert state["protected_sessions_available"] is False
    assert state["protectedSessionsAvailable"] is False
    assert state["productionReady"] is False


def test_backend_only_reports_production_ready_when_runtime_gate_is_true() -> None:
    blocked = build_production_approval_state(
        candidate_paths={},
        candidate_metadata=_metadata("approved_for_production"),
        runtime_validation={"ok": False, "reason": "runtime_pointer_missing"},
    )
    assert blocked["protected_sessions_available"] is False
    assert blocked["reason_code"] == "runtime_bundle_invalid"

    ready = build_production_approval_state(
        candidate_paths={},
        candidate_metadata=_metadata("approved_for_production"),
        runtime_validation={"ok": True, "reason": "ok", "metadata": {"model_status": "approved_for_production"}},
        runtime_paths={"base": "/tmp/runtime"},
    )
    assert ready["reason_code"] == "production_ready"
    assert ready["protected_sessions_available"] is True


def test_qml_remains_backend_owned_without_fake_readiness_state() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "qml").rglob("*.qml"))
    assert "backend.productionApprovalState" in combined
    assert "readonly property var productionApproval: backend.productionApprovalState" in combined
    for forbidden in (
        "productionApprovalState:",
        "productionReady:",
        "protectedAvailable:",
        "shadowPassed:",
        "approvalPassed:",
        "modelReady:",
        "protectedSessionsAvailable:",
    ):
        assert forbidden not in combined


def test_static_gate_files_do_not_contain_observability_policy_edits() -> None:
    changed_surfaces = "\n".join([
        (ROOT / "metadata_core" / "production_approval.py").read_text(encoding="utf-8"),
        (ROOT / "bridge" / "refresh_dashboard_helpers.py").read_text(encoding="utf-8"),
        (ROOT / "desktop_app.py").read_text(encoding="utf-8"),
    ])
    model_policy = (ROOT / "model_policy.py").read_text(encoding="utf-8")
    auto_promotion = (ROOT / "metadata_core" / "auto_promotion.py").read_text(encoding="utf-8")
    assert "production_approval_observability" in changed_surfaces
    assert "protected_sessions_available = True" not in changed_surfaces
    assert "approved_for_shadow" in changed_surfaces
    assert "threshold" in model_policy
    assert "protectedSessionsAvailable" in auto_promotion
    assert "approved_for_shadow" in auto_promotion or "production_approval" in auto_promotion


def test_existing_feature_regression_tests_are_present() -> None:
    for rel in (
        "tests/test_auto_training_idempotency_after_rejection.py",
        "tests/test_training_enrollment_mutual_exclusion.py",
        "tests/test_passive_finalization_stuck_state_recovery.py",
        "tests/test_production_approval_ui_explainability.py",
    ):
        assert (ROOT / rel).exists(), rel


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("7 focused shadow production approval regression gate tests passed", flush=True)
