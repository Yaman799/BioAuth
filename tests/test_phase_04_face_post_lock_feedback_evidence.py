from __future__ import annotations

import json
from pathlib import Path

import metadata_core.production_evidence_pipeline as pipe
from shadow_core.background_contracts import shadow_evidence_ledger_path, shadow_eval_report_path
from bridge import session_runtime_helpers


def _set_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))


def test_pre_lock_face_confirmation_writes_shadow_ledger_by_default(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)

    record = pipe.append_pre_lock_face_confirmation_shadow_evidence_record(
        user_id="owner",
        session_id="face-session-1",
        risk=96,
        avg_risk=90.5,
        state={
            "candidate_artifact_digest": "sha256:candidate",
            "runtime_schema_version": "runtime-v1",
            "model_version": "prod-v1",
            "decision": "intruder",
        },
        face_result={"status": "verified_owner", "embedding": [1, 2, 3], "source_frame_paths": ["raw.png"]},
        timestamp="2026-06-06 10:00:00",
    )

    assert record["source"] == pipe.PRE_LOCK_FACE_CONFIRMATION_EVIDENCE_SOURCE
    assert record["shadow_ledger_schema_version"] == pipe.SHADOW_EVIDENCE_LEDGER_SCHEMA_VERSION
    assert record["false_positive_candidate"] is True
    assert record["verified_owner_after_anomaly"] is True
    assert record["eligible_for_direct_production_training"] is False
    assert record["production_training_allowed"] is False
    assert record["production_model_pointer_changed"] is False
    assert Path(shadow_evidence_ledger_path("owner")).exists()
    assert not Path(pipe.evidence_ledger_path("owner")).exists()

    encoded = Path(shadow_evidence_ledger_path("owner")).read_text(encoding="utf-8").lower()
    assert "embedding" not in encoded
    assert "source_frame_paths" not in encoded
    assert Path(shadow_eval_report_path("owner")).exists()


def test_post_lock_verified_legit_feedback_writes_false_positive_shadow_evidence(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    state = {
        "user_id": "owner",
        "session_id": "s1",
        "postLockConfirmationEventId": "post-lock:event:s1",
        "postLockConfirmationEventSessionId": "s1",
        "postLockConfirmationRisk": 94,
        "postLockConfirmationAvgRisk": 92.2,
        "candidate_artifact_digest": "sha256:candidate",
        "runtime_schema_version": "runtime-v1",
        "decision": "intruder",
        "face_confirmation": {"status": "verified_owner", "embedding": [4, 5, 6]},
    }

    record = pipe.append_post_lock_feedback_shadow_evidence_record(
        user_id="owner",
        state=state,
        label="verified_legit_after_warning",
        feedback_record={"timestamp": "2026-06-06 11:00:00", "label": "verified_legit_after_warning"},
    )

    assert record["source"] == pipe.POST_LOCK_FEEDBACK_EVIDENCE_SOURCE
    assert record["shadow_ledger_schema_version"] == pipe.SHADOW_EVIDENCE_LEDGER_SCHEMA_VERSION
    assert record["is_post_unlock_window"] is True
    assert record["false_positive_candidate"] is True
    assert record["verified_owner_after_anomaly"] is True
    assert record["is_confirmed_intruder_window"] is False
    assert record["eligible_for_direct_production_training"] is False
    assert record["production_training_allowed"] is False
    assert record["production_decision_changed"] is False
    assert record["production_threshold_changed"] is False
    assert record["production_model_pointer_changed"] is False
    assert not Path(pipe.evidence_ledger_path("owner")).exists()

    validation = pipe.validate_shadow_evidence_ledger("owner")
    assert validation["ok"] is True
    report = json.loads(Path(shadow_eval_report_path("owner")).read_text(encoding="utf-8"))
    assert report["post_lock_feedback_count"] == 1
    assert report["post_lock_false_positive_feedback_count"] == 1


def test_post_lock_confirmed_intruder_feedback_writes_confirmed_intruder_shadow_evidence(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)

    record = pipe.append_post_lock_feedback_shadow_evidence_record(
        user_id="owner",
        state={
            "session_id": "s2",
            "postLockConfirmationEventId": "post-lock:event:s2",
            "candidate_artifact_digest": "sha256:candidate",
            "runtime_schema_version": "runtime-v1",
            "risk": 98,
            "avg_risk": 97,
            "decision": "intruder",
        },
        label="confirmed_intruder",
        feedback_record={"timestamp": "2026-06-06 11:10:00", "label": "confirmed_intruder"},
    )

    assert record["source"] == pipe.POST_LOCK_FEEDBACK_EVIDENCE_SOURCE
    assert record["is_post_unlock_window"] is True
    assert record["is_confirmed_intruder_window"] is True
    assert record["false_positive_candidate"] is False
    assert record["verified_owner_after_anomaly"] is False
    assert record["production_training_allowed"] is False

    report = json.loads(Path(shadow_eval_report_path("owner")).read_text(encoding="utf-8"))
    assert report["post_lock_feedback_count"] == 1
    assert report["post_lock_confirmed_intruder_feedback_count"] == 1
    assert report["confirmed_intruder_count"] == 1


def test_classify_post_lock_confirmation_records_shadow_evidence_without_blocking_state(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    writes = []

    class FakeFacade:
        time = __import__("time")

        @staticmethod
        def write_session_state(state):
            writes.append(dict(state))

    monkeypatch.setattr(session_runtime_helpers, "_facade", lambda: FakeFacade, raising=False)

    class App:
        _current_user = {"user_id": "owner"}
        _runtime_state = {}

        def _active_state_for_current_user(self):
            return {}

    state = {
        "user_id": "owner",
        "session_id": "s3",
        "postLockConfirmationPending": True,
        "postLockConfirmationEventId": "post-lock:event:s3",
        "postLockConfirmationEventSessionId": "s3",
        "postLockConfirmationRisk": 91,
        "postLockConfirmationAvgRisk": 90,
        "candidate_artifact_digest": "sha256:candidate",
        "runtime_schema_version": "runtime-v1",
        "feedback_prompt": {"kind": "post_lock_confirmation", "event_id": "post-lock:event:s3", "session_id": "s3"},
    }

    result = session_runtime_helpers.classify_post_lock_confirmation(
        App(),
        state=state,
        label="verified_legit_after_warning",
        feedback_record={"timestamp": "2026-06-06 11:20:00", "label": "verified_legit_after_warning"},
    )

    assert result["ok"] is True
    updated = result["state"]
    assert updated["postLockShadowEvidenceRecorded"] is True
    assert updated["postLockShadowEvidenceSource"] == pipe.POST_LOCK_FEEDBACK_EVIDENCE_SOURCE
    assert updated["production_threshold_changed"] is False if "production_threshold_changed" in updated else True
    assert writes and writes[-1]["postLockShadowEvidenceRecorded"] is True
    records = pipe.read_evidence_records("owner", ledger_path=shadow_evidence_ledger_path("owner"))
    assert len(records) == 1
    assert records[0]["source"] == pipe.POST_LOCK_FEEDBACK_EVIDENCE_SOURCE
    assert records[0]["false_positive_candidate"] is True
