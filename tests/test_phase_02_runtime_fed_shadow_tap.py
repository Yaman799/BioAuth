from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _production_runtime() -> dict:
    return {
        "metadata": {
            "artifact_digest": "sha256:production",
            "runtime_schema_version": "runtime-schema-v1",
            "feature_schema_version": "feature-schema-v1",
        },
        "paths": {"model": ""},
    }


def _production_prediction(final: str = "legit", risk: int = 12) -> dict:
    return {
        "final": final,
        "risk": risk,
        "raw": 0.12,
        "status": "ok",
        "window_count": 3,
    }


def _production_state() -> dict:
    return {
        "session_id": "session-1",
        "session_kind": "protected",
        "user_id": "alice",
        "runtime_quality_ok_windows": 3,
        "runtime_low_quality_windows": 0,
        "runtime_lock_safety_reasons": [],
        "runtime_telemetry_seq": "window-1",
    }


def test_runtime_fed_shadow_tap_writes_privacy_safe_shadow_ledger(monkeypatch, tmp_path):
    import metadata_core.runtime_shadow_tap as tap
    import model_inference

    tap.clear_runtime_shadow_tap_cache()
    ledger = tmp_path / "shadow_evidence.jsonl"
    monkeypatch.setattr(tap, "shadow_evidence_ledger_path", lambda user_id: str(ledger))
    monkeypatch.setattr(
        tap,
        "_load_shadow_candidate_bundle",
        lambda user_id: (
            {
                "model": object(),
                "metadata": {
                    "model_status": "approved_for_shadow",
                    "candidate_artifact_digest": "sha256:candidate",
                    "runtime_schema_version": "runtime-schema-v1",
                },
                "classifier": None,
                "metadata_file": "candidate_metadata.json",
                "classifier_file": None,
                "paths": {"model": "candidate_model.pkl", "metadata": "candidate_metadata.json"},
                "candidate_artifact_digest": "sha256:candidate",
                "runtime_schema_version": "runtime-schema-v1",
            },
            {"ok": True, "reason": "candidate_loaded"},
        ),
    )
    monkeypatch.setattr(
        model_inference,
        "predict_from_session_details",
        lambda *args, **kwargs: {"final": "intruder", "risk": 91, "raw": 0.91, "status": "ok", "window_count": 3},
    )

    result = tap.run_runtime_fed_shadow_tap(
        user_id="alice",
        session_path="live-session",
        production_state=_production_state(),
        production_runtime=_production_runtime(),
        production_prediction=_production_prediction(),
    )

    assert result["ok"] is True
    assert result["status"] == "recorded"
    assert ledger.exists()
    record = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert record["source"] == "runtime_shadow_evidence"
    assert record["candidate_artifact_digest"] == "sha256:candidate"
    assert record["baseline_artifact_digest"] == "sha256:production"
    assert record["baseline_decision"] == "trusted"
    assert record["candidate_would_lock_if_production"] is True
    assert "shadow_evidence_lock_suppressed" in record["reason_codes"]
    forbidden = {"raw_keyboard", "keyboard_events", "raw_mouse", "mouse_events", "feature_vector", "feature_vectors"}
    assert not any(key in record for key in forbidden)


def test_runtime_fed_shadow_tap_skips_without_candidate(monkeypatch, tmp_path):
    import metadata_core.runtime_shadow_tap as tap

    tap.clear_runtime_shadow_tap_cache()
    ledger = tmp_path / "shadow_evidence.jsonl"
    monkeypatch.setattr(tap, "shadow_evidence_ledger_path", lambda user_id: str(ledger))
    monkeypatch.setattr(tap, "_load_shadow_candidate_bundle", lambda user_id: (None, {"ok": False, "reason": "candidate_model_missing"}))

    result = tap.run_runtime_fed_shadow_tap(
        user_id="alice",
        production_state=_production_state(),
        production_runtime=_production_runtime(),
        production_prediction=_production_prediction(),
    )

    assert result["ok"] is False
    assert result["status"] == "skipped"
    assert result["reason"] == "candidate_model_missing"
    assert not ledger.exists()


def test_runtime_fed_shadow_tap_failure_is_non_raising(monkeypatch):
    import metadata_core.runtime_shadow_tap as tap

    tap.clear_runtime_shadow_tap_cache()

    def boom(user_id: str):
        raise RuntimeError("candidate loader exploded")

    monkeypatch.setattr(tap, "_load_shadow_candidate_bundle", boom)
    result = tap.run_runtime_fed_shadow_tap(
        user_id="alice",
        production_state=_production_state(),
        production_runtime=_production_runtime(),
        production_prediction=_production_prediction(),
    )
    assert result["ok"] is False
    assert result["status"] == "failed"
    assert "candidate loader exploded" in result["reason"]


def test_submit_runtime_fed_shadow_tap_sync_for_tests(monkeypatch, tmp_path):
    import metadata_core.runtime_shadow_tap as tap
    import model_inference

    tap.clear_runtime_shadow_tap_cache()
    monkeypatch.setenv("BIOAUTH_RUNTIME_SHADOW_TAP_SYNC_FOR_TESTS", "1")
    ledger = tmp_path / "shadow_evidence.jsonl"
    monkeypatch.setattr(tap, "shadow_evidence_ledger_path", lambda user_id: str(ledger))
    monkeypatch.setattr(
        tap,
        "_load_shadow_candidate_bundle",
        lambda user_id: (
            {
                "model": object(),
                "metadata": {"model_status": "approved_for_shadow", "candidate_artifact_digest": "sha256:candidate"},
                "classifier": None,
                "metadata_file": "candidate_metadata.json",
                "classifier_file": None,
                "paths": {"model": "candidate_model.pkl"},
                "candidate_artifact_digest": "sha256:candidate",
                "runtime_schema_version": "runtime-schema-v1",
            },
            {"ok": True},
        ),
    )
    monkeypatch.setattr(model_inference, "predict_from_session_details", lambda *a, **k: {"final": "legit", "risk": 10, "raw": 0.1, "status": "ok"})

    result = tap.submit_runtime_fed_shadow_tap(
        user_id="alice",
        production_state=_production_state(),
        production_runtime=_production_runtime(),
        production_prediction=_production_prediction(),
    )

    assert result["accepted"] is True
    assert result["status"] == "recorded"
    assert ledger.exists()


def test_monitor_impl_submits_runtime_fed_shadow_tap_after_production_evidence():
    source = (ROOT / "src" / "bioauth" / "runtime" / "monitor_impl.py").read_text(encoding="utf-8")
    assert "submit_runtime_fed_shadow_tap" in source
    assert "runtime_fed_shadow_tap_submitted" in source
    assert "if not _shadow_evidence_mode():" in source
    assert "Runtime-fed shadow evaluation is report-only" in source
