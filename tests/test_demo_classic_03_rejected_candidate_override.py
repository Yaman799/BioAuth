from __future__ import annotations

import json
import os
import pickle
from pathlib import Path


def _rejected_meta(status: str = "rejected") -> dict:
    return {
        "model_status": status,
        "candidate_status": status,
        "reason_code": "offline_approval_rejected",
        "approval_reason": "offline approval rejected for demo fixture",
        "artifact_digest": "sha256:rejected-candidate",
        "runtime_schema_version": "runtime-schema-v1",
        "feature_schema_version": "sequence-multiscale-v1",
        "feature_window_strategy": "multi_scale_sequence_concatenated_per_anchor",
        "active_window_scales": [6.0, 12.0],
        "policy_metrics": {"far": 0.05, "frr": 0.15},
        "production_evidence_summary": {
            "status": "fail",
            "reason_codes": ["offline_approval_rejected"],
            "far": 0.05,
            "frr": 0.15,
        },
    }


def _write_candidate_bundle(user_id: str, meta: dict | None = None) -> dict:
    from metadata_core.paths import _user_model_paths
    from security import atomic_write_bytes, atomic_write_text, save_metadata_hash, save_model_hash

    candidate = _user_model_paths(user_id)
    Path(candidate["base"]).mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(candidate["model"], pickle.dumps({"classic": "model"}))
    save_model_hash(candidate["model"])
    atomic_write_text(candidate["metadata"], json.dumps(meta or _rejected_meta(), ensure_ascii=False))
    save_metadata_hash(candidate["metadata"])
    return candidate


def test_demo_classic_03_disabled_rejected_candidate_remains_blocked(monkeypatch, tmp_path):
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", raising=False)
    monkeypatch.setattr("paths.models_dir", lambda: str(tmp_path / "models"))

    from metadata_core.demo_classic_runtime_activation import activate_existing_candidate_runtime_for_demo
    from metadata_core.paths import _active_runtime_pointer_path

    _write_candidate_bundle("demo_user")
    result = activate_existing_candidate_runtime_for_demo("demo_user")

    assert result["ok"] is False
    assert result["activated"] is False
    assert result["reason"] == "demo_classic_protected_disabled"
    assert not Path(_active_runtime_pointer_path("demo_user")).exists()


def test_demo_classic_03_enabled_rejected_candidate_activates(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    monkeypatch.setattr("paths.models_dir", lambda: str(tmp_path / "models"))

    from metadata_core.demo_classic_runtime_activation import activate_existing_candidate_runtime_for_demo
    from metadata_core.paths import _active_runtime_pointer_path, _user_production_paths
    from metadata_core.runtime import validate_runtime_bundle_for_activation

    _write_candidate_bundle("demo_user")
    result = activate_existing_candidate_runtime_for_demo("demo_user")

    production = _user_production_paths("demo_user")
    published = json.loads(Path(production["metadata"]).read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["activated"] is True
    assert result["reason"] == "demo_classic_runtime_activated"
    assert result["demo_rejected_candidate_override"] is True
    assert result["runtime_publish_source"] == "demo_classic_rejected_candidate_override"
    assert Path(production["model"]).exists()
    assert Path(_active_runtime_pointer_path("demo_user")).exists()
    assert published["bundle_role"] == "production"
    assert published["model_status"] == "approved_for_production"
    assert published["demo_classic_protected"] is True
    assert published["demo_rejected_candidate_override"] is True
    assert published["production_approval_bypassed_for_demo"] is True
    assert published["runtime_publish_source"] == "demo_classic_rejected_candidate_override"
    assert published["original_model_status_before_demo_publish"] == "rejected"
    assert validate_runtime_bundle_for_activation(production)["ok"] is True


def test_demo_classic_03_offline_rejection_reason_status_activates(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    monkeypatch.setattr("paths.models_dir", lambda: str(tmp_path / "models"))

    from metadata_core.demo_classic_runtime_activation import activate_existing_candidate_runtime_for_demo
    from metadata_core.paths import _user_production_paths

    meta = _rejected_meta("offline_approval_rejected")
    _write_candidate_bundle("demo_user", meta)
    result = activate_existing_candidate_runtime_for_demo("demo_user")
    published = json.loads(Path(_user_production_paths("demo_user")["metadata"]).read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["demo_rejected_candidate_override"] is True
    assert result["candidate_status"] == "offline_approval_rejected"
    assert published["runtime_publish_source_candidate_status"] == "offline_approval_rejected"


def test_demo_classic_03_rejected_candidate_still_requires_valid_model(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    monkeypatch.setattr("paths.models_dir", lambda: str(tmp_path / "models"))

    from metadata_core.demo_classic_runtime_activation import activate_existing_candidate_runtime_for_demo
    from metadata_core.paths import _active_runtime_pointer_path, _user_model_paths
    from security import atomic_write_text, save_metadata_hash

    candidate = _user_model_paths("demo_user")
    Path(candidate["base"]).mkdir(parents=True, exist_ok=True)
    atomic_write_text(candidate["metadata"], json.dumps(_rejected_meta()))
    save_metadata_hash(candidate["metadata"])

    result = activate_existing_candidate_runtime_for_demo("demo_user")

    assert result["ok"] is False
    assert result["reason"] == "candidate_model_missing"
    assert not Path(_active_runtime_pointer_path("demo_user")).exists()


def test_demo_classic_03_dashboard_override_for_rejected_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")

    from metadata_core.production_approval import build_production_approval_state

    candidate_paths = tmp_path / "candidate_bundle"
    candidate_paths.mkdir()
    metadata_path = candidate_paths / "metadata.json"
    metadata_path.write_text(json.dumps(_rejected_meta()), encoding="utf-8")
    state = build_production_approval_state(
        candidate_paths={
            "base": str(candidate_paths),
            "model": str(candidate_paths / "model.pkl"),
            "metadata": str(metadata_path),
            "evaluation_report": str(candidate_paths / "evaluation_report.json"),
            "evaluation_summary": str(candidate_paths / "evaluation_summary.md"),
        },
        candidate_metadata=_rejected_meta(),
        runtime_validation={"ok": False, "reason": "runtime_pointer_missing", "metadata": _rejected_meta()},
        runtime_paths={},
    )

    assert state["protected_sessions_available"] is True
    assert state["production_ready"] is True
    assert state["ready_notification_state"] == "ready"
    assert state["reason_code"] == "demo_classic_rejected_candidate_override"
    assert state["status"] == "demo_ready"
    assert state["candidate_status"] == "demo_ready"
    assert state["demo_classic_protected"] is True
    assert state["demo_rejected_candidate_override"] is True
    assert state["production_approval_bypassed_for_demo"] is True
    assert state["runtime_publish_source"] == "demo_classic_rejected_candidate_override"
    assert "offline_approval_rejected" in state["production_evidence_summary"]["reason_codes"]


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


def test_demo_classic_03_start_protected_allows_rejected_candidate_after_activation(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    import bridge.session_runtime_helpers as runtime_helpers

    monkeypatch.setattr(
        runtime_helpers,
        "_ensure_demo_classic_runtime_pointer",
        lambda bridge: {
            "ok": True,
            "activated": True,
            "reason": "demo_classic_runtime_activated",
            "runtime_publish_source": "demo_classic_rejected_candidate_override",
            "demo_rejected_candidate_override": True,
            "active_runtime_pointer_path": "active_runtime_pointer.json",
        },
    )

    bridge = DummyBridge({"ready": True, "production_ready": False, "candidate_model_status": "rejected"})

    assert runtime_helpers.start_protected_session(bridge, trigger_refresh=False) is True
    assert bridge.started_processes != []
    assert any(
        event == "demo_classic_protected_bypassed_production_gate"
        and payload.get("demo_rejected_candidate_override") is True
        for _, event, payload, _ in bridge.debug_events
    )
    assert not any("runtime_pointer_missing" in str(payload) for _, _, payload, _ in bridge.debug_events)
