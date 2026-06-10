from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metadata_core.auto_enrollment import (
    PASSIVE_COLLECTION_SOURCE,
    metadata_tags_from_environment,
    passive_collection_env,
    passive_collection_should_start,
    remediation_metadata_from_plan,
    remediation_session_counts_as_success,
)
from metadata_core.passive_quality import PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS
from metadata_core.remediation_loop import (
    RemediationAction,
    RemediationFailureKind,
    build_remediation_plan,
)


def _settings() -> dict:
    return {"smart_auto_enrollment_enabled": True}


def _safe_profile() -> dict:
    return {
        "production_ready": False,
        "session_count": 15,
        "minimum_session_count": 8,
        "recommended_session_count": 15,
    }


def _safe_start(plan: object, **overrides: object) -> tuple[bool, str]:
    payload = {
        "settings": _settings(),
        "profile": _safe_profile(),
        "runtime_state": {},
        "sessions": [],
        "consent_satisfied": True,
        "authenticated": True,
        "training_active": False,
        "evaluation_active": False,
        "app_locked": False,
        "remediation_plan": plan,
    }
    payload.update(overrides)
    return passive_collection_should_start(**payload)


def test_data_remediable_failure_allows_targeted_auto_enrollment():
    plan = build_remediation_plan(reason_codes=["insufficient_post_unlock_evidence"], source_gate="production_evidence_gate_v2")

    allowed, reason = _safe_start(plan)

    assert allowed is True
    assert reason == "ready"
    assert plan.failure_kind == RemediationFailureKind.DATA_REMEDIABLE
    assert plan.action == RemediationAction.COLLECT_POST_UNLOCK_TRUSTED_WINDOWS
    assert plan.starts_collection is False


def test_runtime_failure_blocks_auto_enrollment_refill():
    plan = build_remediation_plan(reason_codes=["runtime_bundle_invalid"], source_gate="production_approval")

    allowed, reason = _safe_start(plan)

    assert allowed is False
    assert reason == "remediation_runtime_fix_required"


def test_training_active_blocks_remediation_collection():
    plan = build_remediation_plan(reason_codes=["feature_quality_too_low"])

    allowed, reason = _safe_start(plan, training_active=True)

    assert allowed is False
    assert reason == "training_active"


def test_evaluation_active_blocks_remediation_collection():
    plan = build_remediation_plan(reason_codes=["unknown_rate_too_high"])

    allowed, reason = _safe_start(plan, evaluation_active=True)

    assert allowed is False
    assert reason == "evaluation_active"


def test_confirmed_intruder_low_risk_does_not_start_owner_positive_enrollment():
    plan = build_remediation_plan(reason_codes=["confirmed_intruder_low_risk"], source_gate="production_evidence_gate_v2")

    allowed, reason = _safe_start(plan)
    tags = remediation_metadata_from_plan(plan, remediation_plan_id="plan-intruder-1")

    assert allowed is True
    assert reason == "ready"
    assert tags["targeted_collection_action"] == "hard_negative_remediation_required"
    assert tags["trust_level"] == "hard_negative"
    assert tags["excluded_from_positive_training"] is True
    assert tags["training_counts_toward_minimum"] is False
    assert remediation_session_counts_as_success(
        {
            **tags,
            "auto_enrollment": True,
            "collection_source": PASSIVE_COLLECTION_SOURCE,
            "session_kind": "enrollment",
            "metadata_trusted": True,
            "bucket": "accepted",
            "capture_event_count": PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS,
        },
        plan,
    ) is False


def test_remediation_session_metadata_tags_written():
    plan = build_remediation_plan(reason_codes=["insufficient_model_agreement"], source_gate="production_evidence_gate_v2")

    env = passive_collection_env(plan, remediation_plan_id="plan-123")
    tags = metadata_tags_from_environment(env, keyboard_rows=250, mouse_rows=10000)

    assert tags["auto_enrollment"] is True
    assert tags["collection_source"] == PASSIVE_COLLECTION_SOURCE
    assert tags["remediation_collection"] is True
    assert tags["remediation_plan_id"] == "plan-123"
    assert tags["targeted_collection_action"] == "collect_more_shadow_comparison_windows"
    assert tags["evidence_source"] == "remediation_refill"
    assert tags["trust_level"] == "trusted_owner_candidate"
    assert "keyboard_events" not in str(tags)
    assert "mouse_events" not in str(tags)
    assert "feature_vector" not in str(tags)


def test_low_quality_remediation_session_not_counted_as_success():
    plan = build_remediation_plan(reason_codes=["feature_quality_too_low"])
    tags = remediation_metadata_from_plan(plan, remediation_plan_id="plan-quality")
    low_quality_session = {
        **tags,
        "auto_enrollment": True,
        "collection_source": PASSIVE_COLLECTION_SOURCE,
        "session_kind": "enrollment",
        "metadata_trusted": True,
        "bucket": "accepted",
        "keyboard_event_count": 1,
        "mouse_event_count": 1,
        "capture_event_count": 2,
    }
    high_quality_session = {
        **low_quality_session,
        "keyboard_event_count": 0,
        "mouse_event_count": 0,
        "capture_event_count": PASSIVE_TRUSTED_MIN_CAPTURE_EVENTS,
    }

    assert remediation_session_counts_as_success(low_quality_session, plan) is False
    assert remediation_session_counts_as_success(high_quality_session, plan) is True


def test_auto_enrollment_still_does_not_decide_production_readiness():
    plan = build_remediation_plan(reason_codes=["unknown_rate_too_high"])

    allowed, reason = _safe_start(plan)
    tags = remediation_metadata_from_plan(plan, remediation_plan_id="plan-diverse")

    assert allowed is True
    assert reason == "ready"
    assert "production_ready" not in tags
    assert "productionReady" not in tags
    assert "protectedSessionsAvailable" not in tags
    assert plan.starts_training is False
    assert plan.starts_collection is False


def _run() -> None:
    tests = [
        test_data_remediable_failure_allows_targeted_auto_enrollment,
        test_runtime_failure_blocks_auto_enrollment_refill,
        test_training_active_blocks_remediation_collection,
        test_evaluation_active_blocks_remediation_collection,
        test_confirmed_intruder_low_risk_does_not_start_owner_positive_enrollment,
        test_remediation_session_metadata_tags_written,
        test_low_quality_remediation_session_not_counted_as_success,
        test_auto_enrollment_still_does_not_decide_production_readiness,
    ]
    failures = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures.append(f"{test.__name__}: {exc}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"{len(tests)} remediation auto-enrollment targeted-refill tests passed")


if __name__ == "__main__":
    _run()
