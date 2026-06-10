from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metadata_core.production_approval import build_production_approval_state
from metadata_core.shadow_loop import (
    SHADOW_LOOP_MIN_NEW_ACCEPTED_SESSIONS,
    build_shadow_loop_state,
    shadow_retraining_gate,
    trusted_sessions_signature,
)


def _trusted_session(session_id: str, *, keyboard: int = 120, mouse: int = 120, bucket: str = "morning") -> dict:
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


def _shadow_production_state(*, gates=None, contexts=None, report_available: bool = True) -> dict:
    state = build_production_approval_state(
        candidate_paths={},
        candidate_metadata={
            "model_status": "approved_for_shadow",
            "approval_reason": "Approved for shadow because production margins are not met yet.",
        },
        runtime_validation={"ok": False, "reason": "runtime_pointer_missing", "metadata": {}},
    )
    state["failedProductionGates"] = list(gates or ["production_margin_not_met"])
    state["activeRoutedContexts"] = list(contexts or [])
    state["evaluationReportAvailable"] = bool(report_available)
    if not report_available:
        state["evaluationReportFile"] = ""
    return state


def test_approved_for_shadow_enters_shadow_loop_and_blocks_protected_sessions() -> None:
    state = build_shadow_loop_state(
        profile={"training_can_start": True, "session_count": 8},
        production_approval=_shadow_production_state(),
        model_readiness={"nextBestAction": "collect_diverse_high_quality_sessions"},
        sessions=[_trusted_session(str(i)) for i in range(8)],
        baseline_signature="",
        baseline_accepted_count=8,
        now=100.0,
    )
    assert state["active"] is True
    assert state["modelStatus"] == "approved_for_shadow"
    assert state["protectedSessionsAvailable"] is False
    assert state["safeUserMessage"] == "BioAuth is validating your protection model safely in the background."
    assert state["phase"] in {"collecting_targeted_sessions", "cooldown", "safe_failure_collecting"}


def test_production_margin_not_met_chooses_diverse_targeted_collection() -> None:
    state = build_shadow_loop_state(
        profile={"training_can_start": True, "session_count": 8},
        production_approval=_shadow_production_state(gates=["production_margin_not_met"]),
        model_readiness={},
        sessions=[_trusted_session(str(i), bucket="evening") for i in range(8)],
        baseline_signature="baseline",
        baseline_accepted_count=8,
        now=100.0,
    )
    assert state["targetedCollectionAction"] == "collect_diverse_high_quality_sessions"
    assert "diverse" in state["targetedCollectionText"].lower()


def test_mouse_heavy_chooses_keyboard_mixed_collection() -> None:
    state = build_shadow_loop_state(
        profile={"training_can_start": True, "session_count": 8},
        production_approval=_shadow_production_state(contexts=["mouse_heavy"]),
        model_readiness={"dominantInputContext": "mouse_heavy"},
        sessions=[_trusted_session(str(i), keyboard=2, mouse=200) for i in range(8)],
        baseline_signature="baseline",
        baseline_accepted_count=8,
        now=100.0,
    )
    assert state["targetedCollectionAction"] == "collect_keyboard_mixed_sessions"
    assert "keyboard" in state["targetedCollectionText"].lower()


def test_retraining_does_not_repeat_without_new_accepted_sessions() -> None:
    sessions = [_trusted_session(str(i)) for i in range(8)]
    baseline = trusted_sessions_signature(sessions)
    allowed, reason, state = shadow_retraining_gate(
        production_approval=_shadow_production_state(),
        model_readiness={},
        profile={"training_can_start": True, "session_count": 8},
        sessions=sessions,
        baseline_signature=baseline,
        baseline_accepted_count=8,
        cooldown_until=0.0,
        now=100.0,
    )
    assert allowed is False
    assert reason == "shadow_loop_waiting_for_new_sessions"
    assert state["newAcceptedSessionsSinceShadow"] == 0
    assert state["retrainingEligible"] is False


def test_retraining_requires_new_sessions_and_cooldown_allows_future_retry() -> None:
    old_sessions = [_trusted_session(str(i)) for i in range(8)]
    new_sessions = old_sessions + [_trusted_session("new1", bucket="afternoon"), _trusted_session("new2", bucket="night")]
    allowed, reason, state = shadow_retraining_gate(
        production_approval=_shadow_production_state(),
        model_readiness={},
        profile={"training_can_start": True, "session_count": 10},
        sessions=new_sessions,
        baseline_signature=trusted_sessions_signature(old_sessions),
        baseline_accepted_count=8,
        cooldown_until=0.0,
        now=100.0,
    )
    assert allowed is True
    assert reason == "shadow_loop_retraining_ready"
    assert state["newAcceptedSessionsSinceShadow"] >= SHADOW_LOOP_MIN_NEW_ACCEPTED_SESSIONS
    assert state["phase"] == "retraining_ready"


def test_cooldown_prevents_training_loops_even_with_new_sessions() -> None:
    old_sessions = [_trusted_session(str(i)) for i in range(8)]
    new_sessions = old_sessions + [_trusted_session("new1"), _trusted_session("new2")]
    allowed, reason, state = shadow_retraining_gate(
        production_approval=_shadow_production_state(),
        model_readiness={},
        profile={"training_can_start": True, "session_count": 10},
        sessions=new_sessions,
        baseline_signature=trusted_sessions_signature(old_sessions),
        baseline_accepted_count=8,
        cooldown_until=500.0,
        now=100.0,
    )
    assert allowed is False
    assert reason == "shadow_loop_cooldown"
    assert state["cooldownActive"] is True
    assert state["phase"] == "cooldown"


def test_missing_evaluation_report_is_safe_and_does_not_invent_metrics() -> None:
    production = _shadow_production_state(report_available=False)
    state = build_shadow_loop_state(
        profile={"training_can_start": True, "session_count": 8},
        production_approval=production,
        model_readiness={},
        sessions=[_trusted_session(str(i)) for i in range(8)],
        now=100.0,
    )
    assert state["active"] is True
    assert state["evidence"]["evaluationReportAvailable"] is False
    assert "metricValues" not in state
    assert state["protectedSessionsAvailable"] is False


def test_qml_static_displays_backend_shadow_loop_state_without_fake_state() -> None:
    files = [
        ROOT / "qml" / "pages" / "ProfilePage.qml",
        ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml",
        ROOT / "qml" / "components" / "LiveTelemetryPanel.qml",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "backend.modelReadinessState" in text
        assert "shadowLoop" in text
        assert "shadowLoopState:" not in text
        assert "targetedCollectionAction:" not in text
    assert "BioAuth is validating your protection model safely in the background" in (ROOT / "qml" / "pages" / "ProfilePage.qml").read_text(encoding="utf-8")


def test_scheduler_uses_shadow_loop_gate_and_records_shadow_cooldown() -> None:
    helper = (ROOT / "bridge" / "session_training_helpers.py").read_text(encoding="utf-8")
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    runtime = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "shadow_retraining_gate" in helper
    assert "trusted_sessions_signature" in helper
    assert "SHADOW_LOOP_RETRY_COOLDOWN_SECONDS" in helper
    assert "_shadow_loop_cooldown_until" in helper
    assert "_shadow_loop_baseline_signature" in helper
    assert "approved_for_shadow" in helper
    assert "build_shadow_loop_state" in desktop
    assert "profile.get(\"production_ready\")" in runtime


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("9 focused shadow loop phase6 tests passed", flush=True)
    os._exit(0)
