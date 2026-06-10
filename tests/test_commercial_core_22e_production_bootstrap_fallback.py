from __future__ import annotations

from metadata_core.production_approval import build_production_approval_state
from metadata_core.production_bootstrap import last_good_production_overlay


def test_last_good_runtime_unblocks_protected_sessions_even_when_candidate_shadow_only():
    state = build_production_approval_state(
        candidate_paths={},
        candidate_metadata={"model_status": "approved_for_shadow"},
        runtime_validation={
            "ok": True,
            "reason": "ok",
            "metadata": {"bundle_role": "production", "model_status": "approved_for_production"},
            "artifact_identity": {"model_sha256": "sha256:model"},
        },
        runtime_paths={"base": "/tmp/user_yaman/production_bundle"},
        user_id="yaman",
    )
    assert state["protectedSessionsAvailable"] is True
    assert state["productionReady"] is True
    assert state["lastGoodProductionAvailable"] is True
    assert state["pendingShadowCandidateStatus"] == "approved_for_shadow"


def test_shadow_only_candidate_without_last_good_runtime_remains_blocked():
    state = build_production_approval_state(
        candidate_paths={},
        candidate_metadata={"model_status": "approved_for_shadow"},
        runtime_validation={"ok": False, "reason": "runtime_pointer_missing", "metadata": None},
        runtime_paths={},
        user_id="yaman",
    )
    assert state["protectedSessionsAvailable"] is False
    assert state["candidateStatus"] == "approved_for_shadow"


def test_last_good_overlay_returns_empty_when_no_valid_pointer(monkeypatch):
    import metadata_core.production_bootstrap as bootstrap

    monkeypatch.setattr(
        bootstrap,
        "resolve_active_runtime_paths_with_validation",
        lambda user_id: (None, {"ok": False, "reason": "runtime_pointer_missing"}),
    )
    assert last_good_production_overlay("yaman") == {}


def test_last_good_overlay_marks_monitor_ready(monkeypatch):
    import metadata_core.production_bootstrap as bootstrap

    monkeypatch.setattr(
        bootstrap,
        "resolve_active_runtime_paths_with_validation",
        lambda user_id: (
            {"base": "/models/user_yaman/production_bundle"},
            {
                "ok": True,
                "reason": "ok",
                "metadata": {"bundle_role": "production", "model_status": "approved_for_production"},
                "artifact_identity": {"model_sha256": "sha256:model", "metadata_sha256": "sha256:meta"},
            },
        ),
    )
    overlay = last_good_production_overlay("yaman")
    assert overlay["production_ready"] is True
    assert overlay["protected_sessions_available"] is True
    assert overlay["can_start_monitor"] is True
    assert overlay["last_good_production_available"] is True
