from __future__ import annotations

import json
import os
import pickle
from pathlib import Path
from types import SimpleNamespace

import pytest

from app_settings import demo_classic_protected_enabled
from metadata_core.production_approval import build_production_approval_state


def _shadow_meta() -> dict:
    return {
        "model_status": "approved_for_shadow",
        "approval_reason": "shadow validation only",
        "artifact_digest": "sha256:candidate",
        "runtime_schema_version": "runtime-schema-v1",
        "feature_schema_version": "sequence-multiscale-v1",
        "feature_window_strategy": "multi_scale_sequence_concatenated_per_anchor",
        "active_window_scales": [6.0, 12.0],
        "policy_metrics": {"far": 0.01, "frr": 0.02},
    }


def _candidate_paths(tmp_path: Path, meta: dict | None = None) -> dict:
    base = tmp_path / "candidate_bundle"
    base.mkdir(parents=True, exist_ok=True)
    paths = {
        "base": str(base),
        "model": str(base / "model.pkl"),
        "classifier": str(base / "classifier.pkl"),
        "metadata": str(base / "metadata.json"),
        "evaluation_report": str(base / "evaluation_report.json"),
        "evaluation_summary": str(base / "evaluation_summary.md"),
    }
    if meta is not None:
        Path(paths["metadata"]).write_text(json.dumps(meta), encoding="utf-8")
    return paths


def test_demo_flag_disabled_preserves_original_production_approval_gate(monkeypatch, tmp_path):
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", raising=False)
    meta = _shadow_meta()
    state = build_production_approval_state(
        candidate_paths=_candidate_paths(tmp_path, meta),
        candidate_metadata=meta,
        runtime_validation={"ok": False, "reason": "runtime_pointer_missing", "metadata": meta},
        runtime_paths={},
    )

    assert demo_classic_protected_enabled() is False
    assert state["modelStatus"] == "approved_for_shadow"
    assert state["productionReady"] is False
    assert state["protectedSessionsAvailable"] is False
    assert state["reason_code"] != "demo_classic_protected"
    assert not state.get("demo_classic_protected", False)


def test_demo_flag_enabled_opens_protected_sessions_for_shadow_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    meta = _shadow_meta()
    state = build_production_approval_state(
        candidate_paths=_candidate_paths(tmp_path, meta),
        candidate_metadata=meta,
        runtime_validation={"ok": False, "reason": "runtime_pointer_missing", "metadata": meta},
        runtime_paths={},
    )

    assert state["modelStatus"] == "approved_for_shadow"
    assert state["productionReady"] is True
    assert state["protectedSessionsAvailable"] is True
    assert state["protected_sessions_available"] is True
    assert state["reason_code"] == "demo_classic_protected"
    assert state["ready_notification_state"] == "ready"
    assert state["demo_classic_protected"] is True
    assert state["production_approval_bypassed_for_demo"] is True
    assert state["demo_classic_protected_bypassed_production_gate"] is True


def test_demo_mode_publishes_candidate_runtime_bundle(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    monkeypatch.setattr("paths.models_dir", lambda: str(tmp_path / "models"))

    import model_training
    import artifact_integrity
    from metadata_core.paths import _user_model_paths, _user_production_paths
    from artifact_integrity import load_metadata
    from security import atomic_write_bytes, atomic_write_text, save_metadata_hash, save_model_hash

    monkeypatch.setattr(artifact_integrity, "load_model", lambda model_file=None: {"loaded": True})
    monkeypatch.setattr(artifact_integrity, "load_classifier", lambda classifier_file=None: None)
    monkeypatch.setattr(artifact_integrity, "load_metadata", lambda metadata_file=None: json.loads(Path(metadata_file).read_text(encoding="utf-8")))

    safe = "demo_user"
    candidate = _user_model_paths(safe)
    Path(candidate["base"]).mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(candidate["model"], pickle.dumps({"classic": "model"}))
    save_model_hash(candidate["model"])
    atomic_write_text(candidate["metadata"], json.dumps({**_shadow_meta(), "bundle_role": "candidate"}))
    save_metadata_hash(candidate["metadata"])

    ok = model_training._publish_initial_production_bundle_if_approved(
        safe,
        candidate,
        {"model_status": "approved_for_shadow", "rollout_status": "shadow_validation", "rollout_details": {}},
    )

    assert ok is True
    published = json.loads(Path(_user_production_paths(safe)["metadata"]).read_text(encoding="utf-8"))
    assert published["bundle_role"] == "production"
    assert published["model_status"] == "approved_for_production"
    assert published["demo_classic_protected"] is True
    assert published["production_approval_bypassed_for_demo"] is True
    assert published["runtime_publish_source"] == "demo_classic_protected"
    assert published["runtime_requires_production_approval"] is False
    assert published["production_ready"] is True
    assert published["protected_sessions_available"] is True


def test_non_demo_publish_gate_still_blocks_shadow_candidate(monkeypatch, tmp_path):
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", raising=False)
    monkeypatch.setattr("paths.models_dir", lambda: str(tmp_path / "models"))

    import model_training
    from metadata_core.paths import _user_model_paths, _user_production_paths
    from security import atomic_write_bytes, atomic_write_text, save_metadata_hash, save_model_hash

    safe = "demo_user"
    candidate = _user_model_paths(safe)
    Path(candidate["base"]).mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(candidate["model"], pickle.dumps({"classic": "model"}))
    save_model_hash(candidate["model"])
    atomic_write_text(candidate["metadata"], json.dumps({**_shadow_meta(), "bundle_role": "candidate"}))
    save_metadata_hash(candidate["metadata"])

    ok = model_training._publish_initial_production_bundle_if_approved(
        safe,
        candidate,
        {"model_status": "approved_for_shadow"},
    )

    assert ok is False
    assert not Path(_user_production_paths(safe)["metadata"]).exists()


class DummyBridge:
    def __init__(self, profile: dict):
        self._current_user = {"user_id": "owner"}
        self._profile = profile
        self.statuses: list[tuple[str, str]] = []
        self.debug_events: list[tuple[str, str, dict, str]] = []
        self.started_processes: list[tuple[str, list[str]]] = []
        self._pending_monitor_start = False
        self._last_shadow_evidence_monitor_block_reason = "developer_shadow_paused"
        self._last_shadow_evidence_monitor_skipped_reason = ""
        self._last_process_start_error = ""
        self._monitor_start_deadline = 0
        self._monitor_launch_attempted = False
        self._monitor_start_failed = False
        self._active_live_session_dir = None
        self._last_alert_signature = None
        self._pending_logger_session_id = ""
        self._pending_logger_run_id = ""
        self._pending_monitor_user_id = ""
        self._language = "en"

    def _debug_trace(self, category, event, payload=None, level="info"):
        self.debug_events.append((category, event, dict(payload or {}), level))

    def _has_current_user_welcome_consent(self):
        return True

    def _set_status(self, message, tone):
        self.statuses.append((message, tone))

    def _t(self, key, **kwargs):
        return key

    def _safe_user(self):
        return "owner"

    def _active_state_for_current_user(self):
        return {}

    def _stop_stale_monitor(self):
        return True

    def _clear_history_archive_watch(self):
        return None

    def _new_live_session_dir(self):
        return "live-session"

    def _start_process(self, key, command, extra_env=None):
        self.started_processes.append((key, command))
        return True

    def _logger_key(self):
        return "logger_user_owner"

    def _logger_process_key(self):
        return "logger_user_owner"

    def _session_process_env(self):
        return dict(os.environ)

    def _update_refresh_timer(self, force=False):
        return None

    def requestRefresh(self, reason, force=False):
        return None

    def _clear_pending_shadow_evidence_monitor_start(self):
        self._pending_shadow_evidence_monitor_start = False


def test_start_monitor_blocked_when_demo_flag_disabled(monkeypatch):
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", raising=False)
    import bridge.session_runtime_helpers as runtime_helpers

    bridge = DummyBridge({"ready": True, "production_ready": False, "candidate_model_status": "approved_for_shadow"})
    assert runtime_helpers.start_protected_session(bridge, trigger_refresh=False) is False
    assert bridge.started_processes == []
    assert bridge.statuses[-1] == ("profile_not_runtime_ready", "warn")


def test_start_monitor_allowed_when_demo_flag_enabled(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    import bridge.session_runtime_helpers as runtime_helpers

    monkeypatch.setattr(
        runtime_helpers,
        "_ensure_demo_classic_runtime_pointer",
        lambda bridge: {
            "ok": True,
            "activated": True,
            "reason": "demo_classic_runtime_activated",
            "active_runtime_pointer_path": "active_runtime_pointer.json",
            "runtime_publish_source": "demo_classic_existing_candidate_activation",
        },
    )
    bridge = DummyBridge({"ready": True, "production_ready": False, "candidate_model_status": "approved_for_shadow"})
    assert runtime_helpers.start_protected_session(bridge, trigger_refresh=False) is True
    assert bridge._pending_monitor_start is True
    assert bridge._profile["production_ready"] is True
    assert bridge._profile["protected_sessions_available"] is True
    assert bridge._profile["reason_code"] == "demo_classic_protected"
    assert any(event == "demo_classic_protected_bypassed_production_gate" for _, event, _, _ in bridge.debug_events)


def test_demo_mode_does_not_require_shadow_evidence_monitor(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "yes")
    import bridge.session_runtime_helpers as runtime_helpers

    bridge = DummyBridge({"ready": True, "production_ready": False, "candidate_model_status": "approved_for_shadow"})
    assert runtime_helpers.start_shadow_evidence_monitor(bridge) is False
    assert bridge._last_shadow_evidence_monitor_block_reason == ""
    assert bridge._last_shadow_evidence_monitor_skipped_reason == "demo_classic_protected_uses_direct_monitor"
    assert any(event == "shadow_evidence_monitor_skipped" for _, event, _, _ in bridge.debug_events)


class DummyIncidentFacade:
    EXPECTED_USER_SLUG = "owner"

    def __init__(self, face_result: dict):
        self.face_result = face_result
        self.false_positive_recorded = False
        self.locked = False
        self.captured = False
        self.stopped = False
        self.logs: list[dict] = []
        self.state_writes: list[dict] = []

    def _pre_lock_face_confirmation(self, **kwargs):
        return dict(self.face_result)

    def _record_face_confirmed_false_positive(self, **kwargs):
        self.false_positive_recorded = True

    def _capture_intruder_evidence(self, **kwargs):
        self.captured = True
        return {"enabled": False, "status": "disabled", "saved_file_count": 0}

    def _lock_app_state(self, **kwargs):
        self.locked = True

    def read_session_state(self, default=None):
        return {}

    def _write_monitor_state(self, decision=None, extra=None):
        self.state_writes.append(dict(extra or {}))

    def _stop_logger_for_context(self):
        self.stopped = True

    def append_log(self, payload):
        self.logs.append(dict(payload))


def test_face_verified_keeps_monitoring_instead_of_lock(monkeypatch):
    import monitor_core.incident as incident

    facade = DummyIncidentFacade({"attempted": True, "status": "verified_owner", "lock_suppressed": True, "verified_owner_after_anomaly": True})
    monkeypatch.setattr(incident, "_facade", lambda: facade)
    incident._lock_and_stop_for_intruder("s1", risk=95, avg_risk=91.0, ml=1, ts="now")

    assert facade.false_positive_recorded is True
    assert facade.locked is False
    assert facade.captured is False


@pytest.mark.parametrize("status", ["camera_unavailable", "no_face_detected", "timeout", "not_verified", "failed"])
def test_face_failure_or_unavailable_requests_protected_action(monkeypatch, status):
    import monitor_core.incident as incident

    facade = DummyIncidentFacade({"attempted": True, "status": status, "lock_suppressed": False, "verified_owner_after_anomaly": False})
    monkeypatch.setattr(incident, "_facade", lambda: facade)
    incident._lock_and_stop_for_intruder("s1", risk=95, avg_risk=91.0, ml=1, ts="now")

    assert facade.false_positive_recorded is False
    assert facade.captured is True
    assert facade.locked is True
    assert facade.stopped is True
    assert facade.logs[-1]["status"] == "locked"
