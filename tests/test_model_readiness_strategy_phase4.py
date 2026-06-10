from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metadata_core.model_readiness import build_model_readiness_state
from metadata_core.production_approval import build_production_approval_state


def _trusted_session(session_id: str, *, keyboard: int, mouse: int, bucket: str = "morning") -> dict:
    return {
        "session_id": session_id,
        "session_kind": "enrollment",
        "training_counts_toward_minimum": True,
        "metadata_trusted": True,
        "bucket": "accepted",
        "keyboard_rows": keyboard,
        "mouse_rows": mouse,
        "time_of_day_bucket": bucket,
    }


def test_mouse_heavy_maps_to_keyboard_mixed_recommendation() -> None:
    state = build_model_readiness_state(
        profile={"training_can_start": True, "session_count": 8, "minimum_session_count": 8},
        production_approval={
            "modelStatus": "approved_for_shadow",
            "productionReady": False,
            "protectedSessionsAvailable": False,
            "failedProductionGates": ["production_margin_not_met"],
            "activeRoutedContexts": ["mouse_heavy"],
        },
        sessions=[_trusted_session("s1", keyboard=5, mouse=200)],
    )
    assert state["dominantInputContext"] == "mouse_heavy"
    assert state["currentBlocker"] == "mouse_heavy"
    assert state["nextBestAction"] == "collect_keyboard_mixed_sessions"
    assert "keyboard" in state["nextBestActionText"].lower()
    assert state["productionReady"] is False


def test_production_margin_not_met_maps_to_collect_diverse_sessions() -> None:
    state = build_model_readiness_state(
        profile={"training_can_start": True, "session_count": 10, "minimum_session_count": 8},
        production_approval={
            "modelStatus": "approved_for_shadow",
            "productionReady": False,
            "protectedSessionsAvailable": False,
            "failedProductionGates": ["production_margin_not_met"],
            "activeRoutedContexts": [],
        },
        sessions=[_trusted_session("s1", keyboard=120, mouse=90, bucket="morning"), _trusted_session("s2", keyboard=100, mouse=110, bucket="evening")],
    )
    assert state["currentBlocker"] == "production_margin_not_met"
    assert state["nextBestAction"] == "collect_diverse_high_quality_sessions"
    assert "diverse" in state["nextBestActionText"].lower()


def test_missing_metrics_or_empty_diagnostics_do_not_crash() -> None:
    state = build_model_readiness_state(
        profile={"training_can_start": False, "training_block_reason": "need_more_trusted_sessions"},
        production_approval={},
        sessions=[],
    )
    assert state["readinessLevel"] == "collecting"
    assert state["currentBlocker"] == "need_more_trusted_sessions"
    assert state["inputCoverage"] == {"keyboard": "none", "mouse": "none", "mixed": "none"}
    assert set(state["timeOfDayCoverage"].keys()) == {"morning", "afternoon", "evening", "night"}


def test_approved_for_production_maps_to_ready_only_when_runtime_valid() -> None:
    ready = build_model_readiness_state(
        profile={"training_can_start": True, "session_count": 8, "minimum_session_count": 8},
        production_approval={"modelStatus": "approved_for_production", "productionReady": True, "protectedSessionsAvailable": True, "failedProductionGates": []},
        sessions=[_trusted_session("s1", keyboard=120, mouse=90)],
    )
    assert ready["readinessLevel"] == "production_ready"
    assert ready["productionReady"] is True
    assert ready["nextBestAction"] == "safe_promotion_ready"

    runtime_blocked = build_model_readiness_state(
        profile={"training_can_start": True, "session_count": 8, "minimum_session_count": 8},
        production_approval={"modelStatus": "approved_for_production", "productionReady": False, "protectedSessionsAvailable": False, "runtimeValidationReason": "runtime_pointer_missing"},
        sessions=[_trusted_session("s1", keyboard=120, mouse=90)],
    )
    assert runtime_blocked["readinessLevel"] == "runtime_blocked"
    assert runtime_blocked["productionReady"] is False
    assert runtime_blocked["nextBestAction"] == "verify_runtime_bundle"


def test_approved_for_shadow_remains_protected_sessions_unavailable() -> None:
    production_state = build_production_approval_state(
        candidate_paths={},
        candidate_metadata={"model_status": "approved_for_shadow", "approval_reason": "production margins were not met"},
        runtime_validation={"ok": False, "reason": "runtime_pointer_missing", "metadata": {}},
    )
    assert production_state["modelStatus"] == "approved_for_shadow"
    assert production_state["protectedSessionsAvailable"] is False
    readiness = build_model_readiness_state(
        profile={"training_can_start": True, "session_count": 8, "minimum_session_count": 8},
        production_approval=production_state,
        sessions=[_trusted_session("s1", keyboard=100, mouse=100)],
    )
    assert readiness["productionReady"] is False
    assert readiness["nextBestAction"] in {"collect_diverse_high_quality_sessions", "continue_shadow_validation_collect_targeted_sessions"}


def test_known_blockers_map_to_expected_actions() -> None:
    cases = {
        "insufficient_context_coverage": "collect_context_diversity_sessions",
        "insufficient_time_spread": "collect_time_distributed_sessions",
        "benchmark_not_run": "run_device_check",
    }
    for blocker, action in cases.items():
        state = build_model_readiness_state(
            profile={"training_can_start": True, "session_count": 8, "minimum_session_count": 8},
            production_approval={"modelStatus": "approved_for_shadow", "productionReady": False, "protectedSessionsAvailable": False, "failedProductionGates": [blocker]},
            sessions=[_trusted_session("s1", keyboard=100, mouse=100, bucket="morning"), _trusted_session("s2", keyboard=100, mouse=100, bucket="evening")],
        )
        assert state["currentBlocker"] == blocker
        assert state["nextBestAction"] == action


def test_qml_binds_to_backend_model_readiness_state_without_fake_state() -> None:
    qml_files = [
        ROOT / "qml" / "pages" / "ProfilePage.qml",
        ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml",
    ]
    for qml_file in qml_files:
        text = qml_file.read_text(encoding="utf-8")
        assert "backend.modelReadinessState" in text
        assert "modelReadinessState:" not in text
        assert "nextBestAction:" not in text
        assert "readinessLevel:" not in text


def test_phase4_strategy_does_not_auto_train_promote_or_unlock_shadow_only() -> None:
    model_readiness = (ROOT / "metadata_core" / "model_readiness.py").read_text(encoding="utf-8")
    desktop = (ROOT / "src" / "bioauth" / "app" / "desktop_app_impl.py").read_text(encoding="utf-8")
    for forbidden in ("train_user_model", "trainProfile(", "promote_candidate", "write_active_runtime_pointer", "start_protected_session"):
        assert forbidden not in model_readiness
    assert "def modelReadinessState" in desktop
    assert "profile.get(\"model_readiness_state\")" in desktop


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("8 focused model readiness strategy phase4 tests passed", flush=True)
    os._exit(0)
