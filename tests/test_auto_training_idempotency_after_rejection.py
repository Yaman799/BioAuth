from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metadata_core import training_attempts
from metadata_core.auto_training_scheduler import auto_training_should_start, training_readiness_signature
from metadata_core.passive_quality import PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS


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


def _session(session_id: str, *, passive: bool = False, keyboard: int = PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS, mouse: int = 1) -> dict:
    payload = {
        "session_id": session_id,
        "session_kind": "enrollment",
        "training_counts_toward_minimum": True,
        "metadata_trusted": True,
        "bucket": "accepted",
        "keyboard_rows": int(keyboard),
        "mouse_rows": int(mouse),
    }
    if passive:
        payload["auto_enrollment"] = True
        payload["collection_source"] = "passive_auto_enrollment"
    return payload


def test_rejected_training_attempt_is_persisted_for_signature() -> None:
    sessions = [_session(str(i)) for i in range(8)]
    signature = training_readiness_signature(user_id="alice", profile=_profile(), sessions=sessions)
    with tempfile.TemporaryDirectory() as tmpdir:
        original_user_model_dir = training_attempts._user_model_dir
        training_attempts._user_model_dir = lambda user_id: str(Path(tmpdir) / f"user_{user_id}")
        try:
            state = training_attempts.record_training_attempt(
                user_id="alice",
                signature=signature,
                result="rejected",
                status="rejected",
                rejection_reason="offline_approval_failed",
                source="auto",
                attempted_at=123.0,
            )
            loaded = training_attempts.load_training_attempt_state("alice")
        finally:
            training_attempts._user_model_dir = original_user_model_dir
    assert state["last_attempted_training_signature"] == signature
    assert loaded["last_attempted_training_signature"] == signature
    assert loaded["last_attempted_training_result"] == "rejected"
    assert loaded["last_attempted_training_rejection_reason"] == "offline_approval_failed"


def test_auto_training_does_not_retry_same_rejected_signature() -> None:
    sessions = [_session(str(i)) for i in range(8)]
    signature = training_readiness_signature(user_id="alice", profile=_profile(), sessions=sessions)
    allowed, reason, current_signature = auto_training_should_start(
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
        last_attempted_training_result="rejected",
        last_attempted_training_status="rejected",
        now=200.0,
    )
    assert current_signature == signature
    assert allowed is False
    assert reason == "already_attempted_current_training_data"


def test_shadow_only_and_failed_offline_attempts_are_idempotent_for_auto_training() -> None:
    sessions = [_session(str(i)) for i in range(8)]
    signature = training_readiness_signature(user_id="alice", profile=_profile(), sessions=sessions)
    for result in ("shadow_only", "approved_for_shadow", "failed_offline_approval", "training_failed"):
        allowed, reason, _sig = auto_training_should_start(
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
            last_attempted_training_result=result,
            last_attempted_training_status=result,
            now=200.0,
        )
        assert allowed is False
        assert reason == "already_attempted_current_training_data"


def test_new_quality_accepted_session_changes_signature_and_allows_auto_training() -> None:
    sessions = [_session(str(i)) for i in range(8)]
    old_signature = training_readiness_signature(user_id="alice", profile=_profile(), sessions=sessions)
    changed_sessions = sessions + [_session("new-quality", passive=True, keyboard=PASSIVE_TRUSTED_MIN_KEYBOARD_EVENTS, mouse=1)]
    allowed, reason, new_signature = auto_training_should_start(
        settings=_settings(),
        profile=_profile(count=9),
        runtime_state={},
        sessions=changed_sessions,
        user_id="alice",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        last_attempted_signature=old_signature,
        last_attempted_training_result="rejected",
        last_attempted_training_status="rejected",
        now=200.0,
    )
    assert new_signature != old_signature
    assert allowed is True
    assert reason == "ready"


def test_tiny_passive_session_does_not_change_training_signature() -> None:
    sessions = [_session(str(i)) for i in range(8)]
    tiny = _session("tiny-passive", passive=True, keyboard=32, mouse=1658)
    base_signature = training_readiness_signature(user_id="alice", profile=_profile(), sessions=sessions)
    tiny_signature = training_readiness_signature(user_id="alice", profile=_profile(), sessions=sessions + [tiny])
    assert tiny_signature == base_signature


def test_manual_force_retry_can_bypass_attempt_idempotency_when_explicit() -> None:
    sessions = [_session(str(i)) for i in range(8)]
    signature = training_readiness_signature(user_id="alice", profile=_profile(), sessions=sessions)
    allowed, reason, _sig = auto_training_should_start(
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
        last_attempted_training_result="rejected",
        last_attempted_training_status="rejected",
        force_retry=True,
        now=200.0,
    )
    assert allowed is True
    assert reason == "ready"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("6 focused auto-training idempotency tests passed", flush=True)
    raise SystemExit(0)
