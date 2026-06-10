from __future__ import annotations

import contextlib
import json

import pytest

import metadata_core.production_evidence_pipeline as evidence_pipeline
import metadata_core.runtime as runtime
import shadow_core.promotion as shadow_promotion


@contextlib.contextmanager
def _null_context(*_args, **_kwargs):
    yield


def test_shadow_promotion_is_evidence_only_and_does_not_touch_production(monkeypatch):
    events: list[tuple[str, dict]] = []

    class ForbiddenShadowFacade:
        def load_model(self, *_args, **_kwargs):  # pragma: no cover - should never be reached
            raise AssertionError("shadow artifacts must not be loaded for production promotion")

        def copy_verified_temp(self, *_args, **_kwargs):  # pragma: no cover - should never be reached
            raise AssertionError("shadow artifacts must not be copied into production")

    monkeypatch.setattr(shadow_promotion, "_shadow_facade", lambda: ForbiddenShadowFacade())
    monkeypatch.setattr(shadow_promotion, "user_model_lifecycle_lock", lambda _user_id: _null_context())
    monkeypatch.setattr(shadow_promotion, "_shadow_lock", lambda _user_id: _null_context())
    monkeypatch.setattr(
        shadow_promotion,
        "_read_shadow_state",
        lambda _user_id: {
            "phase": "ready",
            "promote_suggested": True,
            "candidate_sessions": ["s1", "s2", "s3", "s4", "s5"],
            "eval_deltas": [1, 2, 3, 4, 5],
            "total_eval_count": 5,
            "avg_delta": 9.5,
        },
    )
    monkeypatch.setattr(shadow_promotion, "SHADOW_EVAL_SESSIONS", 5)
    monkeypatch.setattr(shadow_promotion, "SHADOW_MIN_SESSIONS", 5)
    monkeypatch.setattr(
        shadow_promotion,
        "log_shadow_event",
        lambda _user_id, event_type, **fields: events.append((event_type, fields)),
    )

    result = shadow_promotion.promote_shadow_model("alice")

    assert result["ok"] is False
    assert result["message_key"] == "shadow_promotion_evidence_only"
    assert result["evidence_only"] is True
    assert result["promotion_effect"] == "shadow_only"
    assert result["changed"] is False
    assert result["active_runtime_pointer_written"] is False
    assert result["protectedSessionsAvailable"] is False
    assert result["production_state_changed"] is False
    assert len(events) == 1
    assert events[0][0] == "promotion_blocked"
    assert events[0][1]["reason"] == "shadow_promotion_evidence_only"
    assert events[0][1]["promotion_effect"] == "shadow_only"


def test_active_runtime_pointer_rejects_shadow_or_candidate_sources(monkeypatch, tmp_path):
    model_root = tmp_path / "models" / "user_alice"
    pointer_path = model_root / "active_runtime_pointer.json"
    monkeypatch.setattr(runtime, "_user_model_dir", lambda _user_id: str(model_root))
    monkeypatch.setattr(runtime, "_active_runtime_pointer_path", lambda _user_id: str(pointer_path))

    for source in ("shadow_promotion", "shadow_evidence_monitor", "candidate_validation", "diagnostic_evidence"):
        with pytest.raises(ValueError, match="active_runtime_pointer_requires_explicit_production_source"):
            runtime.write_active_runtime_pointer("alice", {"base": str(model_root / "candidate")}, source=source)

    assert not pointer_path.exists()


def test_active_runtime_pointer_requires_valid_production_bundle(monkeypatch, tmp_path):
    model_root = tmp_path / "models" / "user_alice"
    pointer_path = model_root / "active_runtime_pointer.json"
    production_base = model_root / "production_bundle"
    bundle_paths = {
        "base": str(production_base),
        "model": str(production_base / "model.pkl"),
        "classifier": str(production_base / "classifier.pkl"),
        "metadata": str(production_base / "metadata.json"),
        "evaluation_report": str(production_base / "evaluation_report.json"),
        "evaluation_summary": str(production_base / "evaluation_summary.md"),
    }
    monkeypatch.setattr(runtime, "_user_model_dir", lambda _user_id: str(model_root))
    monkeypatch.setattr(runtime, "_active_runtime_pointer_path", lambda _user_id: str(pointer_path))
    monkeypatch.setattr(runtime, "sign_runtime_pointer_payload", lambda _payload: "test-integrity")
    monkeypatch.setattr(runtime, "clear_runtime_model_cache", lambda _user_id=None: None)
    monkeypatch.setattr(
        runtime,
        "validate_runtime_bundle_for_activation",
        lambda _paths: {
            "ok": True,
            "reason": "ok",
            "metadata": {"bundle_role": "production", "model_status": "approved_for_production"},
            "paths": _paths,
            "artifact_identity": {
                "bundle_base": str(production_base),
                "model_sha256": "sha256:model",
                "metadata_sha256": "sha256:metadata",
            },
        },
    )

    payload = runtime.write_active_runtime_pointer("alice", bundle_paths, source="safe_auto_promotion")

    assert payload["source"] == "safe_auto_promotion"
    assert payload["production_artifact_identity"]["model_sha256"] == "sha256:model"
    assert pointer_path.exists()
    persisted = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert persisted["production_artifact_identity"]["metadata_sha256"] == "sha256:metadata"
    assert persisted["_integrity"] == "test-integrity"


def test_active_runtime_pointer_fails_closed_for_invalid_production_bundle(monkeypatch, tmp_path):
    model_root = tmp_path / "models" / "user_alice"
    pointer_path = model_root / "active_runtime_pointer.json"
    monkeypatch.setattr(runtime, "_user_model_dir", lambda _user_id: str(model_root))
    monkeypatch.setattr(runtime, "_active_runtime_pointer_path", lambda _user_id: str(pointer_path))
    monkeypatch.setattr(
        runtime,
        "validate_runtime_bundle_for_activation",
        lambda _paths: {"ok": False, "reason": "bundle_role_not_production"},
    )

    with pytest.raises(ValueError, match="active_runtime_pointer_requires_production_bundle:bundle_role_not_production"):
        runtime.write_active_runtime_pointer("alice", {"base": str(model_root / "shadow_bundle")}, source="safe_auto_promotion")

    assert not pointer_path.exists()


def test_shadow_runtime_monitor_evidence_is_logged_as_shadow_only(monkeypatch):
    captured: list[dict] = []

    def fake_append(_user_id, record, **_kwargs):
        payload = record.to_dict()
        captured.append(payload)
        return payload

    monkeypatch.setattr(evidence_pipeline, "append_evidence_record", fake_append)

    result = evidence_pipeline.append_runtime_monitor_evidence_record(
        user_id="alice",
        state={
            "runtime_mode": "shadow_evidence",
            "session_kind": "shadow_evidence",
            "evidence_source": "shadow_evidence_monitor",
            "model_decision": "intruder",
            "avg_risk": 95,
            "candidate_would_lock_if_production": True,
            "runtime_quality_ok_windows": 5,
            "runtime_low_quality_windows": 0,
            "runtime_lock_safety_reasons": [],
        },
        runtime={
            "metadata": {
                "candidate_artifact_digest": "sha256:candidate",
                "runtime_schema_version": "runtime-v1",
            },
            "paths": {},
        },
        prediction={"final": "intruder"},
    )

    assert result is captured[0]
    assert result["source"] == "shadow_evidence_monitor"
    assert result["candidate_artifact_digest"] == "sha256:candidate"
    assert result["candidate_would_lock_if_production"] is True
    assert "shadow_evidence_lock_suppressed" in result["reason_codes"]
    assert "baseline_decision_missing" in result["reason_codes"]
