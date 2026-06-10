from __future__ import annotations

from pathlib import Path

import pytest

from bioauth_runtime.monitor_worker import face_gate, lock_controller
import monitor_core.incident as incident


@pytest.mark.parametrize(
    "raw,expected_status,should_lock,lock_reason",
    [
        ({"status": "verified_owner", "verified": True, "lock_suppressed": True, "verified_owner_after_anomaly": True}, "owner_verified", False, ""),
        ({"status": "camera_unavailable", "fallback_reason": "camera_permission_or_device_open_failure"}, "camera_unavailable", True, "camera_unavailable"),
        ({"status": "failed", "fallback_reason": "camera_backend_failed"}, "camera_failure", True, "camera_failure"),
        ({"status": "no_face_detected", "fallback_reason": "no_face"}, "no_face", True, "no_face"),
        ({"status": "not_verified", "fallback_reason": "different_face"}, "other_face", True, "other_face"),
        ({"status": "refused"}, "refused", True, "face_confirmation_refused"),
        ({"status": "timeout", "fallback_reason": "pre_lock_face_timeout"}, "timeout", True, "face_confirmation_timeout"),
        ({"status": "exception", "fallback_reason": "backend_exception"}, "error", True, "face_confirmation_error"),
    ],
)
def test_face_gate_required_status_mappings(raw, expected_status, should_lock, lock_reason):
    result = face_gate.map_face_result(raw)

    assert result["status"] == expected_status
    assert result["should_lock"] is should_lock
    assert result["lock_reason"] == lock_reason
    if expected_status == "owner_verified":
        assert result["final_action"] == "continue_after_owner_face_verified"


def test_face_gate_does_not_call_windows_lock_or_stop_workers(monkeypatch):
    calls: list[str] = []

    def fake_confirmation(user_id, **kwargs):
        calls.append(user_id)
        return {"status": "verified_owner", "lock_suppressed": True, "verified_owner_after_anomaly": True}

    result = face_gate.confirm_before_lock(user_id="owner", settings={}, confirmation_func=fake_confirmation)

    assert result["should_lock"] is False
    assert calls == ["owner"]
    source = Path("bioauth_runtime/monitor_worker/face_gate.py").read_text(encoding="utf-8")
    assert "lock_current_session" not in source
    assert "request_stop" not in source


def test_lock_controller_calls_lock_adapter_and_sets_resume_pending():
    calls = {"lock": 0, "writes": []}

    def fake_lock():
        calls["lock"] += 1
        return {"lockAttempted": True, "lockSucceeded": True, "windowsLockAttempted": True, "windowsLockSucceeded": True}

    def fake_write(**kwargs):
        calls["writes"].append(dict(kwargs))

    result = lock_controller.request_windows_lock(
        session_id="s1",
        risk=96,
        avg_risk=92.4,
        ml=1,
        lock_reason="camera_unavailable",
        previous_state={"session_id": "s1", "runtime_confirmation_rule": "confirmed_intruder"},
        lock_workstation_result=fake_lock,
        write_monitor_state=fake_write,
    )

    payload = result["payload"]
    assert calls["lock"] == 1
    assert calls["writes"][0]["decision"] == "intruder"
    assert payload["lock_reason"] == "camera_unavailable"
    assert payload["final_action"] == "windows_locked"
    assert payload["face_required"] is True
    assert payload["high_risk_evidence"] is True
    assert payload["postLockConfirmationPending"] is True
    assert payload["postLockConfirmationPromptAfterUnlock"] is True
    assert payload["auto_resume_pending"] is True
    assert payload["resume_after_unlock"] is True


def test_lock_controller_does_not_import_face_recognition():
    source = Path("bioauth_runtime/monitor_worker/lock_controller.py").read_text(encoding="utf-8")
    for token in ("identity_confirmation", "face_biometrics", "face_template_store", "confirm_identity_before_lock"):
        assert token not in source


class _IncidentFacade:
    EXPECTED_USER_SLUG = "owner"

    def __init__(self, face_result: dict):
        self.face_result = dict(face_result)
        self.lock_calls = 0
        self.capture_calls = 0
        self.stop_calls = 0
        self.false_positive_calls = 0
        self.state = {"session_id": "s1", "active": True, "decision": "intruder", "session_kind": "protected"}
        self.logs: list[dict] = []

    def _pre_lock_face_confirmation(self, **kwargs):
        return dict(self.face_result)

    def _record_face_confirmed_false_positive(self, **kwargs):
        self.false_positive_calls += 1
        return incident._record_face_confirmed_false_positive(**kwargs)

    def _capture_intruder_evidence(self, **kwargs):
        self.capture_calls += 1
        return {"enabled": False, "status": "disabled", "saved_file_count": 0}

    def _lock_app_state(self, **kwargs):
        self.lock_calls += 1
        self._write_monitor_state(
            decision="intruder",
            extra={
                "app_locked": True,
                "screen_locked": True,
                "final_action": "windows_locked",
                "lock_reason": kwargs.get("lock_reason"),
                "postLockConfirmationPending": True,
                "postLockConfirmationPromptAfterUnlock": True,
                "auto_resume_pending": True,
                "resume_after_unlock": True,
            },
        )

    def _stop_logger_for_context(self):
        self.stop_calls += 1

    def read_session_state(self, default=None):
        return dict(self.state)

    def _write_monitor_state(self, decision=None, extra=None):
        if decision is not None:
            self.state["decision"] = decision
        self.state.update(dict(extra or {}))

    def append_log(self, payload):
        self.logs.append(dict(payload or {}))

    def update_incident_record(self, *args, **kwargs):
        return None


def _run_incident(monkeypatch, face_result: dict) -> _IncidentFacade:
    facade = _IncidentFacade(face_result)
    monkeypatch.setattr(incident, "_facade", lambda: facade)
    incident._lock_and_stop_for_intruder("s1", risk=97, avg_risk=93.0, ml=1, ts="now")
    return facade


def test_high_risk_calls_face_gate_before_lock_and_owner_suppresses(monkeypatch):
    facade = _run_incident(
        monkeypatch,
        {"status": "verified_owner", "verified": True, "lock_suppressed": True, "verified_owner_after_anomaly": True},
    )

    assert facade.false_positive_calls == 1
    assert facade.lock_calls == 0
    assert facade.capture_calls == 0
    assert facade.state["final_action"] == "continue_after_owner_face_verified"
    assert facade.state["screen_locked"] is False


@pytest.mark.parametrize(
    "face_result,reason",
    [
        ({"status": "camera_unavailable", "fallback_reason": "camera_unavailable"}, "camera_unavailable"),
        ({"status": "no_face_detected", "fallback_reason": "no_face"}, "no_face"),
        ({"status": "not_verified", "fallback_reason": "different_face"}, "other_face"),
        ({"status": "refused"}, "face_confirmation_refused"),
        ({"status": "timeout", "fallback_reason": "pre_lock_face_timeout"}, "face_confirmation_timeout"),
    ],
)
def test_face_failure_variants_trigger_lock(monkeypatch, face_result, reason):
    facade = _run_incident(monkeypatch, face_result)

    assert facade.false_positive_calls == 0
    assert facade.capture_calls == 1
    assert facade.lock_calls == 1
    assert facade.stop_calls == 1
    assert facade.state["final_action"] == "windows_locked"
    assert facade.state["lock_reason"] == reason
    assert facade.state["postLockConfirmationPending"] is True
    assert facade.state["postLockConfirmationPromptAfterUnlock"] is True


def test_monitor_runtime_no_longer_creates_pre_lock_feedback_prompt():
    source = Path("src/bioauth/runtime/monitor_impl.py").read_text(encoding="utf-8")
    assert "feedback_needed = False" in source
    assert '"kind": "warning_feedback"' not in source


def test_qml_buttons_guarded_to_post_lock_only():
    source = Path("qml/Main.qml").read_text(encoding="utf-8")
    assert 'prompt.kind !== "post_lock_confirmation"' in source
    assert 'backend.tr("post_lock_confirmation_body")' in source


def test_bridge_does_not_overwrite_final_action_or_lock_reason():
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    assert 'merged["final_action"] =' not in source
    assert 'merged["lock_reason"] =' not in source


def test_commercial_face_lock_modules_do_not_import_dev_side_effects():
    combined = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ["bioauth_runtime/monitor_worker/face_gate.py", "bioauth_runtime/monitor_worker/lock_controller.py"]
    )
    for token in ("auto_training", "auto_promotion", "shadow_backlog", "shadow_evidence_bootstrap", "demo_classic", "dev_production_ready"):
        assert token not in combined
