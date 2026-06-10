from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridge.session_training_helpers import _training_start_block_reason
from metadata_core.auto_enrollment import passive_collection_should_start
from metadata_core.auto_training_scheduler import (
    auto_training_should_start,
    remediation_evidence_progress_from_sessions,
    remediation_retry_signature,
    training_readiness_signature,
)
from metadata_core.passive_quality import PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS, PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS
from metadata_core.remediation_loop import build_remediation_plan


def _settings() -> dict:
    return {"smart_auto_enrollment_enabled": True, "auto_train_when_ready_enabled": True}


def _profile(count: int = 8) -> dict:
    return {
        "training_can_start": True,
        "session_count": count,
        "minimum_session_count": 8,
        "recommended_session_count": 15,
        "production_ready": False,
    }


def _owner_session(session_id: str, *, keyboard: int = PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS, mouse: int = 1, **extra: object) -> dict:
    payload = {
        "session_id": session_id,
        "session_kind": "enrollment",
        "training_counts_toward_minimum": True,
        "metadata_trusted": True,
        "bucket": "accepted",
        "keyboard_rows": int(keyboard),
        "mouse_rows": int(mouse),
    }
    payload.update(extra)
    return payload


def _passive_runtime() -> dict:
    return {
        "active": True,
        "session_kind": "enrollment",
        "auto_enrollment": True,
        "collection_source": "passive_auto_enrollment",
    }


def test_auto_training_does_not_retry_same_failed_signature():
    sessions = [_owner_session(str(i)) for i in range(8)]
    signature = training_readiness_signature(user_id="alice", profile=_profile(), sessions=sessions)

    allowed, reason, current = auto_training_should_start(
        settings=_settings(),
        profile=_profile(),
        runtime_state={},
        sessions=sessions,
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        last_attempted_signature=signature,
        last_attempted_training_result="failed_offline_approval",
        last_attempted_training_status="failed_offline_approval",
        now=1000.0,
    )

    assert current == signature
    assert allowed is False
    assert reason == "already_attempted_current_training_data"


def test_retry_allowed_after_required_new_evidence_changes_signature():
    sessions = [_owner_session(str(i)) for i in range(8)]
    plan_without_progress = build_remediation_plan(
        reason_codes=["feature_quality_too_low"],
        training_data_signature="sha256:training-v1",
        evidence_report_digest="sha256:evidence-v1",
        candidate_artifact_digest="sha256:candidate-v1",
    )
    old_signature = remediation_retry_signature(
        base_training_signature=training_readiness_signature(user_id="alice", profile=_profile(), sessions=sessions),
        remediation_plan=plan_without_progress,
        current_new_evidence={},
    )
    remediated_sessions = sessions + [
        _owner_session(
            "new-quality-1",
            auto_enrollment=True,
            collection_source="passive_auto_enrollment",
            targeted_collection_action="collect_higher_quality_owner_sessions",
        ),
        _owner_session(
            "new-quality-2",
            auto_enrollment=True,
            collection_source="passive_auto_enrollment",
            targeted_collection_action="collect_higher_quality_owner_sessions",
        ),
    ]

    allowed, reason, new_signature = auto_training_should_start(
        settings=_settings(),
        profile=_profile(count=10),
        runtime_state={},
        sessions=remediated_sessions,
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        last_attempted_signature=old_signature,
        last_attempted_training_result="failed_offline_approval",
        last_attempted_training_status="failed_offline_approval",
        remediation_plan=plan_without_progress,
        now=2000.0,
    )

    assert new_signature != old_signature
    assert remediation_evidence_progress_from_sessions(remediated_sessions, plan_without_progress)["trusted_owner_sessions"] == 2
    assert allowed is True
    assert reason == "ready"


def test_retry_blocked_when_remediation_requirements_not_met():
    sessions = [_owner_session(str(i)) for i in range(8)]
    plan = build_remediation_plan(reason_codes=["insufficient_post_unlock_evidence"])

    allowed, reason, _signature = auto_training_should_start(
        settings=_settings(),
        profile=_profile(),
        runtime_state={},
        sessions=sessions,
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        remediation_plan=plan,
        now=1000.0,
    )

    assert allowed is False
    assert reason == "remediation_new_evidence_required"


def test_retry_blocked_while_passive_enrollment_active():
    plan = build_remediation_plan(reason_codes=["feature_quality_too_low"], current_new_evidence={"trusted_owner_sessions": 2})

    allowed, reason, _signature = auto_training_should_start(
        settings=_settings(),
        profile=_profile(count=10),
        runtime_state=_passive_runtime(),
        sessions=[_owner_session(str(i)) for i in range(10)],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="enrollment_active",
        remediation_plan=plan,
        now=1000.0,
    )

    assert allowed is False
    assert reason == "passive_auto_enrollment_active"


def test_passive_enrollment_blocked_while_training_active():
    allowed, reason = passive_collection_should_start(
        settings={"smart_auto_enrollment_enabled": True},
        profile={"production_ready": False},
        runtime_state={},
        sessions=[],
        consent_satisfied=True,
        authenticated=True,
        training_active=True,
    )

    assert allowed is False
    assert reason == "training_active"


def test_manual_training_requires_finalize_or_archive_active_passive_session():
    class Harness:
        _training_in_progress = False
        _runtime_state = _passive_runtime()
        _pending_logger_start = False
        _history_sync_pending = False
        _passive_auto_enrollment_finalizing = False

        def _active_state_for_current_user(self):
            return _passive_runtime()

        def _session_flow(self):
            return "enrollment_active"

    assert _training_start_block_reason(Harness()) == "passive_auto_enrollment_active"


def test_hard_negative_requirement_blocks_owner_only_retry():
    plan = build_remediation_plan(reason_codes=["confirmed_intruder_low_risk"])
    owner_only_sessions = [_owner_session(str(i)) for i in range(8)] + [
        _owner_session(
            "owner-only-new",
            auto_enrollment=True,
            collection_source="passive_auto_enrollment",
            targeted_collection_action="collect_higher_quality_owner_sessions",
        )
    ]

    allowed_owner_only, owner_reason, _ = auto_training_should_start(
        settings=_settings(),
        profile=_profile(count=9),
        runtime_state={},
        sessions=owner_only_sessions,
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        remediation_plan=plan,
        now=1000.0,
    )
    assert allowed_owner_only is False
    assert owner_reason == "remediation_new_evidence_required"

    hard_negative_sessions = owner_only_sessions + [
        _owner_session(
            "hard-negative-1",
            keyboard=0,
            mouse=0,
            auto_enrollment=True,
            collection_source="passive_auto_enrollment",
            targeted_collection_action="hard_negative_remediation_required",
            evidence_source="hard_negative_remediation",
            trust_level="hard_negative",
            excluded_from_positive_training=True,
            training_counts_toward_minimum=False,
            capture_event_count=PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS,
        )
    ]
    allowed_hard_negative, reason_hard_negative, _ = auto_training_should_start(
        settings=_settings(),
        profile=_profile(count=9),
        runtime_state={},
        sessions=hard_negative_sessions,
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        remediation_plan=plan,
        now=1000.0,
    )
    assert remediation_evidence_progress_from_sessions(hard_negative_sessions, plan)["hard_negative_events"] == 1
    assert allowed_hard_negative is True
    assert reason_hard_negative == "ready"


def test_runtime_failure_remains_non_retryable_by_data_collection():
    plan = build_remediation_plan(reason_codes=["runtime_bundle_invalid"], current_new_evidence={"trusted_owner_sessions": 99})

    allowed, reason, _signature = auto_training_should_start(
        settings=_settings(),
        profile=_profile(count=99),
        runtime_state={},
        sessions=[_owner_session(str(i)) for i in range(8)],
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        remediation_plan=plan,
        now=1000.0,
    )

    assert allowed is False
    assert reason == "remediation_runtime_fix_required"


def _run() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = []
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - direct runner prints failing test names.
            failures.append(f"{test.__name__}: {type(exc).__name__}: {exc}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"{len(tests)} remediation retry idempotency hardening tests passed", flush=True)
    import os
    os._exit(0)


if __name__ == "__main__":
    _run()
