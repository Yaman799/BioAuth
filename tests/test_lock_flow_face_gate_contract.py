from __future__ import annotations

import time

import pytest

import app_settings
import bridge.refresh_runtime_helpers as refresh_runtime_helpers
import bridge.session_mixin as session_mixin
import bridge.session_runtime_helpers as session_runtime_helpers
import identity_confirmation
import monitor_core.incident as incident


def _enabled_settings(**extra):
    payload = app_settings._coerce_settings_payload({
        "enable_face_confirmation": True,
        "face_confirmation_enabled": True,
        **app_settings.build_face_template_consent_fields(True),
    })
    payload.update(extra)
    return payload


class _SignalNoArgs:
    def __init__(self):
        self.count = 0

    def emit(self):
        self.count += 1


class _SignalPayload:
    def __init__(self):
        self.payloads: list[dict] = []

    def emit(self, payload):
        self.payloads.append(dict(payload or {}))


class _IncidentFacade:
    EXPECTED_USER_SLUG = "owner"

    def __init__(self, face_result: dict):
        self.face_result = dict(face_result)
        self.lock_calls = 0
        self.capture_calls = 0
        self.stop_calls = 0
        self.false_positive_calls = 0
        self.state: dict = {
            "active": True,
            "session_kind": "protected",
            "session_id": "s1",
            "decision": "intruder",
            "user_id": "owner",
        }
        self.state_writes: list[dict] = []
        self.logs: list[dict] = []

    def _pre_lock_face_confirmation(self, **kwargs):
        return dict(self.face_result)

    def _record_face_confirmed_false_positive(self, **kwargs):
        self.false_positive_calls += 1
        return incident._record_face_confirmed_false_positive(**kwargs)

    def _capture_intruder_evidence(self, **kwargs):
        self.capture_calls += 1
        return {"enabled": True, "status": "success", "saved_file_count": 1, "payload": {"status": "pending"}}

    def _lock_app_state(self, **kwargs):
        self.lock_calls += 1
        self._write_monitor_state(
            decision="intruder",
            extra={
                "app_locked": True,
                "screen_locked": True,
                "windowsLockAttempted": True,
                "windowsLockSucceeded": True,
                "protected_action_requested": True,
                "final_action": self.state.get("final_action") or "lock_required_face_failed_closed",
            },
        )

    def _stop_logger_for_context(self):
        self.stop_calls += 1

    def read_session_state(self, default=None):
        return dict(self.state)

    def write_session_state(self, state):
        self.state = dict(state or {})
        self.state_writes.append(dict(self.state))

    def _write_monitor_state(self, decision=None, extra=None):
        updated = dict(self.state)
        if decision is not None:
            updated["decision"] = decision
        updated.update(dict(extra or {}))
        self.write_session_state(updated)

    def append_log(self, payload):
        self.logs.append(dict(payload or {}))

    def update_incident_record(self, *args, **kwargs):
        return {"status": "screen_locked"}


def _run_incident(monkeypatch, face_result: dict) -> _IncidentFacade:
    facade = _IncidentFacade(face_result)
    monkeypatch.setattr(incident, "_facade", lambda: facade)
    incident._lock_and_stop_for_intruder("s1", risk=96, avg_risk=92.4, ml=1, ts="2026-05-31 20:00:00")
    return facade


def test_confirmed_intruder_verified_owner_suppresses_lock(monkeypatch):
    facade = _run_incident(
        monkeypatch,
        {"attempted": True, "status": "verified_owner", "verified": True, "lock_suppressed": True, "verified_owner_after_anomaly": True},
    )

    assert facade.lock_calls == 0
    assert facade.capture_calls == 0
    assert facade.false_positive_calls == 1
    assert facade.state["protected_action_phase"] == "face_verified_lock_suppressed"
    assert facade.state["face_pre_lock_status"] == "verified_owner"
    assert facade.state["final_action"] == "continue_after_owner_face_verified"
    assert facade.state["screen_locked"] is False
    assert facade.state["face_confirmation_lock_suppressed"] is True


@pytest.mark.parametrize(
    "status,fallback",
    [
        ("camera_unavailable", "camera_permission_or_device_open_failure"),
        ("no_face_detected", "no_face"),
        ("not_verified", "different_face"),
        ("timeout", "pre_lock_face_timeout"),
    ],
)
def test_confirmed_intruder_face_failures_fail_closed_and_lock(monkeypatch, status, fallback):
    facade = _run_incident(
        monkeypatch,
        {"attempted": True, "status": status, "fallback_reason": fallback, "lock_suppressed": False, "verified_owner_after_anomaly": False},
    )

    assert facade.lock_calls == 1
    assert facade.capture_calls == 1
    assert facade.false_positive_calls == 0
    assert facade.state["protected_action_phase"] == "face_failed_closed_locking"
    assert facade.state["face_pre_lock_status"] == status
    assert facade.state["face_pre_lock_fallback_reason"] == fallback
    assert facade.state["final_action"] == "lock_required_face_failed_closed"
    assert facade.state["screen_locked"] is True


def test_full_pre_lock_face_timeout_covers_service_factory_before_lock():
    def slow_service_factory():
        time.sleep(0.3)
        raise AssertionError("should time out before surfacing factory failure")

    result = identity_confirmation.confirm_identity_before_lock(
        "owner",
        settings=_enabled_settings(),
        service_factory=slow_service_factory,
        timeout_sec=0.05,
    )

    assert result["attempted"] is True
    assert result["status"] == "timeout"
    assert result["fallback_reason"] == "pre_lock_face_timeout"
    assert result["lock_suppressed"] is False
    assert result["verified_owner_after_anomaly"] is False
    assert result["raw_images_stored"] is False


def test_protected_warning_does_not_emit_pre_lock_feedback_prompt():
    class Bridge:
        def __init__(self):
            self.warningFeedbackPromptRequested = _SignalPayload()
            self._last_feedback_prompt_signature = ""
            self._runtime_state = {
                "session_id": "s1",
                "decision": "suspicious",
                "risk": 90,
                "feedback_prompt": {"pending": True, "kind": "warning_feedback", "token": "t1"},
            }

    bridge = Bridge()
    refresh_runtime_helpers.maybe_emit_feedback_prompt(bridge)

    assert bridge.warningFeedbackPromptRequested.payloads == []


def test_post_lock_confirmation_is_the_only_feedback_prompt_emitted():
    class Bridge:
        def __init__(self):
            self.warningFeedbackPromptRequested = _SignalPayload()
            self._last_feedback_prompt_signature = ""
            self._runtime_state = {
                "session_id": "s1",
                "decision": "intruder",
                "risk": 98,
                "postLockConfirmationPending": True,
                "postLockConfirmationPromptAfterUnlock": True,
                "postLockConfirmationEventId": "event-1",
                "postLockConfirmationReason": "confirmed_intruder",
                "feedback_prompt": {"pending": True, "kind": "post_lock_confirmation", "token": "t2"},
            }

    bridge = Bridge()
    refresh_runtime_helpers.maybe_emit_feedback_prompt(bridge)

    assert len(bridge.warningFeedbackPromptRequested.payloads) == 1
    assert bridge.warningFeedbackPromptRequested.payloads[0]["kind"] == "post_lock_confirmation"


def test_submit_warning_feedback_confirmed_intruder_is_audit_only_before_post_lock(monkeypatch):
    saved_states: list[dict] = []
    enforcement_calls: list[dict] = []

    class Bridge(session_mixin.SessionMixin):
        def __init__(self):
            self._current_user = {"user_id": "owner"}
            self.runtimeStateChanged = _SignalNoArgs()
            self.statuses: list[tuple[str, str]] = []

        def _active_state_for_current_user(self):
            return {
                "active": True,
                "session_kind": "protected",
                "session_id": "s1",
                "decision": "suspicious",
                "risk": 91,
                "feedback_prompt": {"pending": True, "kind": "warning_feedback", "token": "t1"},
            }

        def _set_status(self, message, tone):
            self.statuses.append((message, tone))

        def _t(self, key, **kwargs):
            return key

        def _maybe_process_shadow_backlog(self):
            return None

    def fake_record_warning_feedback(**kwargs):
        return {"label": "confirmed_intruder", "timestamp": "2026-05-31 20:00:00"}

    def fake_enforce(self, **kwargs):
        enforcement_calls.append(dict(kwargs))
        return {"ok": True, "state": dict(kwargs.get("state") or {})}

    monkeypatch.setattr(session_mixin, "record_warning_feedback", fake_record_warning_feedback)
    monkeypatch.setattr(session_mixin, "write_session_state", lambda state: saved_states.append(dict(state or {})))
    monkeypatch.setattr(session_runtime_helpers, "enforce_confirmed_intruder_event", fake_enforce)

    Bridge().submitWarningFeedback("confirmed_intruder")

    assert enforcement_calls == []
    assert saved_states[-1]["confirmedIntruderFeedbackDidTriggerLock"] is False
    assert saved_states[-1]["feedbackDidRequestProtectedAction"] is False
    assert saved_states[-1]["demo_classic_manual_intruder_feedback_lock"] is False


def test_qml_feedback_dialog_is_guarded_to_post_lock_only():
    source = open("qml/Main.qml", encoding="utf-8").read()
    assert 'prompt.kind !== "post_lock_confirmation"' in source
    assert 'backend.tr("post_lock_confirmation_body")' in source
    assert 'backend.tr("feedback_prompt_body")' not in source
