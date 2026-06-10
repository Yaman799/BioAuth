from __future__ import annotations

import json
import os
import pickle
from pathlib import Path

import pytest


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


def _write_candidate_bundle(user_id: str) -> dict:
    from metadata_core.paths import _user_model_paths
    from security import atomic_write_bytes, atomic_write_text, save_metadata_hash, save_model_hash

    candidate = _user_model_paths(user_id)
    Path(candidate["base"]).mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(candidate["model"], pickle.dumps({"classic": "model"}))
    save_model_hash(candidate["model"])
    atomic_write_text(candidate["metadata"], json.dumps({**_shadow_meta(), "bundle_role": "candidate"}))
    save_metadata_hash(candidate["metadata"])
    return candidate


def test_demo_classic_02_activation_disabled_does_nothing(monkeypatch):
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", raising=False)

    from metadata_core.demo_classic_runtime_activation import activate_existing_candidate_runtime_for_demo

    result = activate_existing_candidate_runtime_for_demo("demo_user")

    assert result["ok"] is False
    assert result["activated"] is False
    assert result["reason"] == "demo_classic_protected_disabled"


def test_demo_classic_02_candidate_copied_to_production_and_pointer_written(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    monkeypatch.setattr("paths.models_dir", lambda: str(tmp_path / "models"))

    from metadata_core.demo_classic_runtime_activation import activate_existing_candidate_runtime_for_demo
    from metadata_core.paths import _active_runtime_pointer_path, _user_production_paths

    safe = "demo_user"
    _write_candidate_bundle(safe)

    result = activate_existing_candidate_runtime_for_demo(safe)

    production = _user_production_paths(safe)
    pointer_path = Path(_active_runtime_pointer_path(safe))
    published = json.loads(Path(production["metadata"]).read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["activated"] is True
    assert result["reason"] == "demo_classic_runtime_activated"
    assert Path(production["model"]).exists()
    assert pointer_path.exists()
    assert published["bundle_role"] == "production"
    assert published["model_status"] == "approved_for_production"
    assert published["demo_classic_protected"] is True
    assert published["production_approval_bypassed_for_demo"] is True
    assert published["runtime_publish_source"] == "demo_classic_existing_candidate_activation"
    assert published["runtime_requires_production_approval"] is False
    assert result["pointer"]["source"] == "demo_classic_protected"


def test_demo_classic_02_activation_reuses_valid_pointer(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    monkeypatch.setattr("paths.models_dir", lambda: str(tmp_path / "models"))

    from metadata_core.demo_classic_runtime_activation import activate_existing_candidate_runtime_for_demo

    _write_candidate_bundle("demo_user")

    first = activate_existing_candidate_runtime_for_demo("demo_user")
    second = activate_existing_candidate_runtime_for_demo("demo_user")

    assert first["ok"] is True
    assert first["activated"] is True
    assert second["ok"] is True
    assert second["activated"] is False
    assert second["reason"] == "active_runtime_already_valid"


class DummyBridge:
    def __init__(self, profile: dict):
        self._current_user = {"user_id": "owner"}
        self._profile = profile
        self.statuses: list[tuple[str, str]] = []
        self.debug_events: list[tuple[str, str, dict, str]] = []
        self.started_processes: list[tuple[str, list[str]]] = []
        self._pending_monitor_start = False
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


def test_demo_classic_02_start_protected_calls_activation_before_spawn(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    import bridge.session_runtime_helpers as runtime_helpers

    calls = []

    def fake_activation(bridge):
        calls.append("activation")
        return {
            "ok": True,
            "activated": True,
            "reason": "demo_classic_runtime_activated",
            "active_runtime_pointer_path": "active_runtime_pointer.json",
            "runtime_publish_source": "demo_classic_existing_candidate_activation",
        }

    monkeypatch.setattr(runtime_helpers, "_ensure_demo_classic_runtime_pointer", fake_activation)
    bridge = DummyBridge({"ready": True, "production_ready": False, "candidate_model_status": "approved_for_shadow"})

    assert runtime_helpers.start_protected_session(bridge, trigger_refresh=False) is True
    assert calls == ["activation"]
    assert bridge.started_processes != []
    assert any(event == "demo_classic_protected_bypassed_production_gate" for _, event, _, _ in bridge.debug_events)


def test_demo_classic_02_activation_failure_blocks_monitor_spawn(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    import bridge.session_runtime_helpers as runtime_helpers

    monkeypatch.setattr(
        runtime_helpers,
        "_ensure_demo_classic_runtime_pointer",
        lambda bridge: {"ok": False, "activated": False, "reason": "candidate_model_missing"},
    )
    bridge = DummyBridge({"ready": True, "production_ready": False, "candidate_model_status": "approved_for_shadow"})

    assert runtime_helpers.start_protected_session(bridge, trigger_refresh=False) is False
    assert bridge.started_processes == []
    assert bridge.statuses[-1] == (
        "Protection runtime activation failed before monitoring: candidate_model_missing",
        "danger",
    )
    assert any(event == "demo_classic_runtime_activation_failed" for _, event, _, _ in bridge.debug_events)


class DummyTrainingBridge:
    def __init__(self):
        self._current_user = {"user_id": "owner"}
        self._profile = {"training_can_start": True}
        self._training_in_progress = False
        self._runtime_state = {}
        self._running_processes = {}
        self._pending_monitor_start = False
        self._protected_session_stopping = False
        self._pending_shadow_evidence_monitor_start = False

    def _session_flow(self):
        return "idle"

    def _active_state_for_current_user(self):
        return {}


def test_demo_classic_02_training_gate_allows_train_without_hybrid_when_enrollment_ready(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    import bridge.session_training_helpers as training_helpers

    monkeypatch.setattr(
        training_helpers,
        "latest_hybrid_direct_test_summary",
        lambda bridge: {"passed": False, "reason_code": "hybrid_test_missing"},
    )

    gate = training_helpers.training_gate_status(DummyTrainingBridge())

    assert gate["can_train"] is True
    assert gate["reason_codes"] == ["demo_classic_training_gate"]
    assert gate["demo_classic_protected"] is True
    assert gate["training_sample_source"] == "normal_enrollment_archives_only"


def test_demo_classic_02_training_gate_does_not_bypass_missing_enrollment(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    import bridge.session_training_helpers as training_helpers

    bridge = DummyTrainingBridge()
    bridge._profile = {"training_can_start": False, "training_block_reason": "missing_enrollment_data"}

    gate = training_helpers.training_gate_status(bridge)

    assert gate["can_train"] is False
    assert gate["reason_code"] == "missing_enrollment_data"


def test_demo_classic_02_non_demo_training_gate_unchanged(monkeypatch):
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", raising=False)
    import bridge.session_training_helpers as training_helpers

    monkeypatch.setattr(
        training_helpers,
        "latest_hybrid_direct_test_summary",
        lambda bridge: {"passed": False, "reason_code": "hybrid_test_missing"},
    )

    gate = training_helpers.training_gate_status(DummyTrainingBridge())

    assert gate["can_train"] is False
    assert gate["reason_code"] == "hybrid_test_missing"
