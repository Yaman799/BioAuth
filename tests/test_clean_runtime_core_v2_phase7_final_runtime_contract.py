from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

from bioauth_runtime import runtime_boundary
from bioauth_runtime.monitor_worker import decision_engine, face_gate, lock_controller
from bioauth_runtime.supervisor import resume_controller, stop_controller
from bridge import refresh_runtime_helpers, session_runtime_helpers


class _Signal:
    def emit(self):
        pass


class _Facade:
    LOGGER_SCRIPT = "logger.py"
    MONITOR_SCRIPT = "monitor.py"
    LOGGER_START_GRACE_SEC = 3.0
    MONITOR_START_GRACE_SEC = 3.0

    def __init__(self, tmp_path):
        import time
        import uuid

        self.time = time
        self.uuid = uuid
        self.state = {}
        self.stop_requests: list[str] = []
        self.cleared: list[tuple[str, str]] = []
        self.locked = False

    def write_session_state(self, state):
        self.state = dict(state or {})
        return True

    def read_session_state(self, default=None):
        return dict(self.state or (default or {}))

    def request_stop(self, name):
        self.stop_requests.append(str(name))

    def clear_stop(self, name):
        self.cleared.append(("stop", str(name)))

    def invalidate_session_discovery_cache(self):
        self.cleared.append(("discovery", ""))

    def is_current_session_locked(self):
        return self.locked


class _Legacy:
    def __init__(self, facade):
        self.facade = facade
        self.refreshes: list[tuple[str, bool]] = []

    def _facade(self):
        return self.facade

    def _request_refresh(self, bridge, reason, force):
        self.refreshes.append((reason, force))

    def stop_live_candidate_observer(self, *args, **kwargs):
        return True

    def worker_failure_detail(self, bridge, key, fallback):
        return fallback, {}


class _Bridge:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._runtime_state = {}
        self._running_processes = {}
        self._last_auto_resume_attempt_at = 0.0
        self._auto_resume_inflight = False
        self._pending_logger_start = False
        self._pending_monitor_start = False
        self._active_live_session_dir = None
        self._last_alert_signature = "x"
        self.statuses: list[tuple[str, str]] = []
        self.onboardingChanged = _Signal()

    def _logger_key(self):
        return "logger_user_alice"

    def _logger_process_key(self):
        return "logger_user_alice"

    def _set_status(self, msg, tone):
        self.statuses.append((msg, tone))

    def _t(self, key, **kwargs):
        return key

    def _clear_pending_logger_start(self):
        self._pending_logger_start = False

    def _clear_pending_monitor_start(self):
        self._pending_monitor_start = False

    def _update_refresh_timer(self, force=False):
        self.refresh_force = bool(force)


def _patch_legacy(monkeypatch, tmp_path):
    facade = _Facade(tmp_path)
    legacy = _Legacy(facade)
    monkeypatch.setattr(stop_controller, "_legacy", lambda: legacy)
    monkeypatch.setattr(resume_controller, "_legacy", lambda: legacy)
    return facade, legacy


def test_root_entrypoints_import_and_worker_wrappers_are_thin():
    for name in ("desktop_app", "logger", "monitor", "model_training", "model_inference", "paths", "security", "app_settings"):
        importlib.import_module(name)
    logger_source = Path("logger.py").read_text(encoding="utf-8")
    monitor_source = Path("monitor.py").read_text(encoding="utf-8")
    assert "bioauth_runtime.logger_worker.main" in logger_source
    assert "bioauth_runtime.monitor_worker.main" in monitor_source
    for source in (logger_source, monitor_source):
        assert "keyboard.Listener" not in source
        assert "lock_current_session" not in source
        assert "predict_from_session_details" not in source


def test_supervisor_is_the_commercial_lifecycle_owner():
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "protection_session_controller.start_protection" in source
    assert "stop_controller.stop_protection" in source
    assert "resume_controller.maybe_resume_after_unlock" in source
    assert "bioauth_runtime/supervisor" not in source  # imported as package/module, not path strings
    for fn in (session_runtime_helpers.start_protected_session, session_runtime_helpers.stop_production_monitor):
        body = inspect.getsource(fn).split('"""')[-1]
        assert "_start_process(" not in body
        assert "_terminate_process_key(" not in body


def test_refresh_has_no_worker_lifecycle_or_recovery_calls():
    source = inspect.getsource(refresh_runtime_helpers._perform_refresh_now)
    forbidden = (
        "_maybe_finish_pending_logger_start(",
        "_maybe_finish_pending_monitor_start(",
        "check_worker_pair_liveness(",
        "_cleanup_processes(",
        "_start_process(",
        "request_stop(",
        "recover_stale_protected_flow_without_workers(",
        "stop_current_session(",
    )
    for token in forbidden:
        assert token not in source


def test_commercial_runtime_boundary_blocks_all_protected_statuses():
    statuses = ("protected_starting", "protected_active", "verifying_return", "resume_pending", "protected_forced_stop")
    for status in statuses:
        state = {"session_kind": "protected", "status": status, "active": status == "protected_active"}
        assert runtime_boundary.is_commercial_protected_runtime(state) is True
        assert runtime_boundary.side_effects_allowed_for_refresh(state) is False


def test_decision_face_and_lock_contracts_hold_for_final_runtime():
    decision = decision_engine.build_runtime_decision_payload({
        "risk": 92.0,
        "decision": "intruder",
        "status": "monitoring",
        "fresh_window": True,
        "runtime_prediction_ready": True,
    })
    assert decision["high_risk_evidence"] is True
    assert decision["face_required"] is True
    owner = face_gate.map_face_result({"status": "verified_owner", "verified": True, "lock_suppressed": True})
    assert owner["should_lock"] is False
    assert owner["final_action"] == "continue_after_owner_face_verified"
    camera = face_gate.map_face_result({"status": "camera_unavailable"})
    assert camera["should_lock"] is True
    assert camera["lock_reason"] == "camera_unavailable"


def test_lock_controller_writes_resume_pending_fields_and_post_lock_flags():
    result = lock_controller.request_windows_lock(
        session_id="s1",
        risk=99,
        avg_risk=97.5,
        ml=1,
        lock_reason="camera_unavailable",
        previous_state={"session_id": "s1"},
        lock_workstation_result=lambda: {"lockAttempted": True, "lockSucceeded": True, "windowsLockAttempted": True, "windowsLockSucceeded": True},
    )
    payload = result["payload"]
    assert payload["status"] == "resume_pending"
    assert payload["forced_stop"] is True
    assert payload["auto_resume_pending"] is True
    assert payload["resume_after_unlock"] is True
    assert payload["postLockConfirmationPending"] is True
    assert payload["postLockConfirmationPromptAfterUnlock"] is True
    assert payload["lock_reason"] == "camera_unavailable"


def test_auto_resume_starts_one_fresh_session_after_old_workers_stop(monkeypatch, tmp_path):
    _patch_legacy(monkeypatch, tmp_path)
    bridge = _Bridge()
    state = {"session_kind": "protected", "active": False, "status": "resume_pending", "forced_stop": True, "protected_action_requested": True, "final_action": "windows_locked", "lock_reason": "camera_unavailable", "auto_resume_pending": True, "resume_after_unlock": True, "lock_controller_handoff": True}
    starts: list[dict] = []
    monkeypatch.setattr(resume_controller.worker_processes, "stop_pair", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(resume_controller.worker_processes, "process_alive", lambda *args, **kwargs: False)
    monkeypatch.setattr(resume_controller.protection_session_controller, "start_protection", lambda bridge, **kwargs: starts.append(kwargs) or True)
    assert resume_controller.maybe_resume_after_unlock(bridge, state) is True
    assert resume_controller.maybe_resume_after_unlock(bridge, state) is False
    assert starts == [{"auto_resume": True, "trigger_refresh": False}]


def test_stop_and_app_shutdown_cleanup_use_supervisor_pair_stop(monkeypatch, tmp_path):
    facade, _legacy = _patch_legacy(monkeypatch, tmp_path)
    bridge = _Bridge()
    calls: list[dict] = []
    monkeypatch.setattr(stop_controller.worker_processes, "stop_pair", lambda bridge, **kwargs: calls.append(kwargs) or {"monitor": {}, "logger": {}})
    result = stop_controller.stop_protection(bridge, reason="user_requested", silent=True)
    assert result["ok"] is True
    assert facade.state["active"] is False
    assert facade.state["monitor_ready"] is False
    assert facade.state["logger_ready"] is False
    stop_controller.shutdown_workers(bridge, reason="app_shutdown", wait_timeout=0.4)
    assert [call["reason"] for call in calls] == ["user_requested", "app_shutdown"]


def test_feedback_and_bridge_decision_authority_are_preserved():
    monitor_source = Path("src/bioauth/runtime/monitor_impl.py").read_text(encoding="utf-8")
    qml_source = Path("qml/Main.qml").read_text(encoding="utf-8")
    bridge_source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "feedback_needed = False" in monitor_source
    assert 'prompt.kind !== "post_lock_confirmation"' in qml_source
    for field in ("raw_model_risk", "observed_model_risk", "action_risk", "display_risk", "decision_risk", "final_action", "lock_reason"):
        assert f'merged["{field}"] =' not in bridge_source


def test_stale_heartbeat_temp_cleanup_and_permission_errors_are_nonfatal(monkeypatch, tmp_path, caplog):
    from bioauth_runtime.logger_worker import heartbeat as logger_hb
    from bioauth_runtime.monitor_worker import heartbeat as monitor_hb

    hb_dir = tmp_path / "worker_heartbeats"
    hb_dir.mkdir()
    (hb_dir / "logger_heartbeat.json.1.tmp").write_text("{}", encoding="utf-8")
    (hb_dir / "monitor_heartbeat.json.1.tmp").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(logger_hb, "worker_heartbeat_path", lambda _kind: str(hb_dir / "logger_heartbeat.json"))
    monkeypatch.setattr(monitor_hb, "worker_heartbeat_path", lambda _kind: str(hb_dir / "monitor_heartbeat.json"))
    assert logger_hb.clean_stale_logger_temp_heartbeats() == 1
    assert monitor_hb.clean_stale_monitor_temp_heartbeats() == 1
    monkeypatch.setattr(logger_hb.os, "replace", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr(monitor_hb.os, "replace", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("locked")))
    logger_hb._last_permission_warning_at = 0.0
    monitor_hb._last_permission_warning_at = 0.0
    assert logger_hb.write_logger_heartbeat_payload({"session_id": "s1"}) is False
    assert monitor_hb.write_monitor_heartbeat_payload({"session_id": "s1"}) is False
    assert "will retry" in caplog.text


def test_final_runtime_required_payload_can_be_published_to_summary(monkeypatch, tmp_path):
    from bioauth_runtime.monitor_worker import runtime_summary_writer

    monkeypatch.setattr(runtime_summary_writer, "CONTROL_DIR", str(tmp_path))
    payload = decision_engine.build_runtime_decision_payload({
        "decision_risk": 88,
        "runtime_decision": "intruder",
        "fresh_window": True,
        "runtime_prediction_ready": True,
        "final_action": "windows_locked",
        "lock_reason": "camera_unavailable",
    })
    assert runtime_summary_writer.write_runtime_summary_payload(payload) is True
    written = json.loads((tmp_path / "runtime_summary.json").read_text(encoding="utf-8"))
    assert written == payload
    assert written["final_action"] == "windows_locked"
    assert written["lock_reason"] == "camera_unavailable"
