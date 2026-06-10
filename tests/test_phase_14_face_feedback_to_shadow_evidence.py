from __future__ import annotations

import json
from pathlib import Path

import feedback_loop
import metadata_core.production_evidence_pipeline as pipeline
import metadata_core.maintenance as maintenance
import monitor_core.incident as incident
from evaluation_core.production_evidence import ProductionEvidencePromotionEffect, ProductionEvidenceStatus
from metadata_core.paths import _active_runtime_pointer_path
from support_bundle import bundle_payload
from shadow_core.background_contracts import shadow_evidence_ledger_path


def _set_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))


def test_verified_owner_event_writes_shadow_evidence_only(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    before_pointer = Path(_active_runtime_pointer_path("owner"))
    before_pointer.parent.mkdir(parents=True, exist_ok=True)
    before_pointer.write_text("production-v1", encoding="utf-8")
    before_pointer_bytes = before_pointer.read_bytes()
    record = pipeline.append_pre_lock_face_confirmation_shadow_evidence_record(
        user_id="owner",
        session_id="session-123",
        risk=99,
        avg_risk=91.2,
        state={"session_id": "session-123", "candidate_artifact_digest": "sha256:prod-digest", "model_version": "prod-v1", "runtime_schema_version": "runtime-v1", "decision": "intruder", "model_decision": "intruder", "runtime_diagnostic_code": "lock_confirmed"},
        face_result={"status": "verified_owner", "verified_owner_after_anomaly": True},
        timestamp="2026-05-04 12:00:00",
    )
    assert record["source"] == "pre_lock_face_confirmation"
    assert record["false_positive_candidate"] is True
    assert record["verified_owner_after_anomaly"] is True
    assert record["eligible_for_shadow_evidence"] is True
    assert record["eligible_for_direct_production_training"] is False
    assert record["production_training_allowed"] is False
    assert record["excluded_from_positive_training"] is True
    assert record["production_decision_changed"] is False
    assert record["production_threshold_changed"] is False
    assert record["production_model_pointer_changed"] is False
    assert record["protected_sessions_unlocked"] is False
    assert record["face_confirmation_status"] == "verified_owner"
    assert record["candidate_artifact_digest"] == "sha256:prod-digest"
    assert record["production_model_version"] == "prod-v1"
    assert record["runtime_schema_version"] == "runtime-v1"
    assert before_pointer.read_bytes() == before_pointer_bytes
    records = pipeline.read_evidence_records("owner", ledger_path=shadow_evidence_ledger_path("owner"))
    assert len(records) == 1
    assert records[0]["window_id"] == "session-123"


def test_face_event_remains_shadow_only_and_does_not_bypass_gates(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    pipeline.append_pre_lock_face_confirmation_shadow_evidence_record(user_id="owner", session_id="session-456", risk=98, avg_risk=94, state={"candidate_artifact_digest": "sha256:candidate", "runtime_schema_version": "runtime-v1"}, face_result={"status": "verified_owner"})
    report = pipeline.build_production_evidence_report_for_user("owner", candidate_artifact_digest="sha256:candidate", runtime_schema_version="runtime-v1")
    assert report.gate.status is not ProductionEvidenceStatus.PASS
    assert report.gate.promotion_effect is not ProductionEvidencePromotionEffect.PRODUCTION_ELIGIBLE
    assert report.gate.allows_production_eligibility is False
    summary = pipeline.load_shadow_evidence_summary_for_candidate("owner", candidate_artifact_digest="sha256:candidate", runtime_schema_version="runtime-v1")
    assert summary["records_total"] == 1
    assert summary["simulated_false_lock_count"] == 1
    assert summary["production_evidence"]["gate"]["promotion_effect"] != "production_eligible"


def test_face_event_is_not_owner_positive_training_or_auto_promotion_input(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    meta = {"session_kind": "protected", "session_id": "session-789", "metadata_trusted": True, "false_positive_candidate": True, "verified_owner_after_anomaly": True, "source": "pre_lock_face_confirmation"}
    assert feedback_loop.production_positive_training_allowed(meta, user_id="owner", session_path=str(tmp_path)) is False
    assert feedback_loop.shadow_feedback_allows_session(meta, user_id="owner", session_path=str(tmp_path)) is False


def test_monitor_phase13_hook_appends_shadow_evidence_without_lock_side_effects(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    calls = {"states": [], "logs": []}
    class FakeFacade:
        EXPECTED_USER_SLUG = "owner"
        @staticmethod
        def read_session_state(default=None):
            return {"session_id": "s1", "decision": "intruder", "user_id": "owner", "candidate_artifact_digest": "sha256:prod", "runtime_schema_version": "runtime-v1", "model_version": "prod-v1"}
        @staticmethod
        def _write_monitor_state(decision=None, extra=None):
            calls["states"].append({"decision": decision, "extra": dict(extra or {})})
        @staticmethod
        def append_log(payload):
            calls["logs"].append(dict(payload))
    monkeypatch.setattr(incident, "_facade", lambda: FakeFacade, raising=False)
    incident._record_face_confirmed_false_positive(session_id="s1", risk=99, avg_risk=88.5, ml=1, ts="10:00:00", face_result={"status": "verified_owner", "verified_owner_after_anomaly": True, "eligible_for_shadow_evidence": True, "eligible_for_direct_production_training": False, "raw_images_stored": False})
    assert calls["states"][-1]["extra"]["protected_sessions_unlocked"] is False
    assert calls["states"][-1]["extra"]["production_threshold_changed"] is False
    records = pipeline.read_evidence_records("owner", ledger_path=shadow_evidence_ledger_path("owner"))
    assert len(records) == 1
    assert records[0]["source"] == "pre_lock_face_confirmation"
    assert records[0]["false_positive_candidate"] is True


def test_privacy_delete_removes_face_shadow_evidence_ledger(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    pipeline.append_pre_lock_face_confirmation_shadow_evidence_record(user_id="owner", session_id="delete-me", risk=88, avg_risk=80, state={}, face_result={"status": "verified_owner"})
    ledger = Path(shadow_evidence_ledger_path("owner"))
    assert ledger.exists()
    result = maintenance.delete_user_data_impl("owner", lifecycle_lock_fn=lambda _user: _NullContext(), user_session_paths_fn=lambda _user: [], mark_profile_state_fn=lambda *_args: None)
    assert result["ok"] is True
    assert not ledger.exists()


class _NullContext:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


def test_support_bundle_excludes_raw_face_fields_from_extra(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    payload = bundle_payload(user_id="owner", runtime_state={"status": "face_confirmed_owner_lock_suppressed", "face_confirmation": {"status": "verified_owner", "embedding": [1, 2, 3], "template_digest": "secret"}, "raw_image_path": "/tmp/raw.png"}, extra={"safe_face_status": "verified_owner", "face_confirmation": {"status": "verified_owner", "embedding": [1, 2, 3], "template_digest": "secret"}, "source_frame_paths": ["/tmp/frame.png"]})
    encoded = json.dumps(payload, sort_keys=True).lower()
    assert "embedding" not in encoded
    assert "template_digest" not in encoded
    assert "source_frame_paths" not in encoded
    assert "raw_image_path" not in encoded
    assert payload["runtime_diagnostics"]["status"] == "face_confirmed_owner_lock_suppressed"
