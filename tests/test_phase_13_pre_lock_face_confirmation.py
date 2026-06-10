from __future__ import annotations

import time
from pathlib import Path

import pytest

import app_settings
import identity_confirmation
from identity_confirmation import confirm_identity_before_lock
import monitor_core.incident as incident


def _enabled_settings(**extra):
    payload = app_settings._coerce_settings_payload({
        "enable_face_confirmation": True,
        "face_confirmation_enabled": True,
        **app_settings.build_face_template_consent_fields(True),
    })
    payload.update(extra)
    return payload


class FakeService:
    def __init__(self, *, enrolled=True, result=None, exc=None, delay=0.0):
        self.enrolled = enrolled
        self.result = result if result is not None else {"status": "verified", "verified": True}
        self.exc = exc
        self.delay = delay
        self.calls = []

    def status(self, user_id):
        self.calls.append(("status", user_id))
        return {"status": "enrolled" if self.enrolled else "not_enrolled", "enrolled": self.enrolled}

    def confirm_before_lock(self, user_id, frame=None):
        self.calls.append(("confirm_before_lock", user_id))
        if self.delay:
            time.sleep(self.delay)
        if self.exc:
            raise self.exc
        return dict(self.result)


def test_disabled_or_not_enrolled_pre_lock_face_confirmation_does_not_attempt_verification():
    disabled = app_settings._coerce_settings_payload({})
    service = FakeService()
    result = confirm_identity_before_lock("owner", settings=disabled, service=service)
    assert result["attempted"] is False
    assert result["lock_suppressed"] is False
    assert result["fallback_reason"] == "feature_disabled"
    assert service.calls == []

    service = FakeService(enrolled=False)
    result = confirm_identity_before_lock("owner", settings=_enabled_settings(), service=service)
    assert result["attempted"] is True
    assert result["status"] == "not_enrolled"
    assert result["lock_suppressed"] is False
    assert service.calls == [("status", "owner")]


def test_verified_owner_suppresses_lock_but_never_direct_production_training():
    result = confirm_identity_before_lock("owner", settings=_enabled_settings(), service=FakeService(result={"status": "verified", "verified": True}))
    assert result["attempted"] is True
    assert result["status"] == "verified_owner"
    assert result["lock_suppressed"] is True
    assert result["verified_owner_after_anomaly"] is True
    assert result["eligible_for_shadow_evidence"] is True
    assert result["eligible_for_direct_production_training"] is False
    for forbidden in ("embedding", "template_digest", "frame", "image", "source_frame_paths"):
        assert forbidden not in result


@pytest.mark.parametrize("service, expected", [
    (FakeService(result={"status": "not_verified", "verified": False}), "not_verified"),
    (FakeService(result={"status": "camera_unavailable", "verified": False}), "camera_unavailable"),
    (FakeService(exc=RuntimeError("camera exploded with raw frame bytes")), "exception"),
])
def test_failed_unavailable_or_exception_face_confirmation_continues_existing_response(service, expected):
    result = confirm_identity_before_lock("owner", settings=_enabled_settings(), service=service, timeout_sec=0.5)
    assert result["attempted"] is True
    assert result["lock_suppressed"] is False
    assert result["status"] == expected
    assert result["eligible_for_direct_production_training"] is False


def test_timeout_face_confirmation_continues_existing_response():
    result = confirm_identity_before_lock("owner", settings=_enabled_settings(), service=FakeService(delay=0.4), timeout_sec=0.05)
    assert result["attempted"] is True
    assert result["status"] == "timeout"
    assert result["lock_suppressed"] is False
    assert result["fallback_reason"] == "pre_lock_face_timeout"


def _patch_monitor_common(monkeypatch, face_result):
    calls = {"capture": 0, "lock": 0, "stop": 0, "states": [], "logs": []}

    class FakeFacade:
        EXPECTED_USER_SLUG = "owner"

        @staticmethod
        def load_settings():
            return _enabled_settings()

        @staticmethod
        def confirm_identity_before_lock(user_id, **kwargs):
            return dict(face_result)

        @staticmethod
        def read_session_state(default=None):
            return {"session_id": "s1", "decision": "intruder", "user_id": "owner"}

        @staticmethod
        def _write_monitor_state(decision=None, extra=None):
            calls["states"].append({"decision": decision, "extra": dict(extra or {})})

        @staticmethod
        def append_log(payload):
            calls["logs"].append(dict(payload))

        @staticmethod
        def _pre_lock_face_confirmation(**kwargs):
            return dict(face_result)

        @staticmethod
        def _record_face_confirmed_false_positive(**kwargs):
            return incident._record_face_confirmed_false_positive(**kwargs)

        @staticmethod
        def _capture_intruder_evidence(**kwargs):
            calls["capture"] += 1
            return {"enabled": False, "status": "disabled"}

        @staticmethod
        def _lock_app_state(**kwargs):
            calls["lock"] += 1

        @staticmethod
        def update_incident_record(*args, **kwargs):
            return None

        @staticmethod
        def _stop_logger_for_context():
            calls["stop"] += 1

    monkeypatch.setattr(incident, "_facade", lambda: FakeFacade, raising=False)
    return calls


def test_existing_lock_path_calls_face_confirmation_and_verified_owner_suppresses_lock(monkeypatch):
    calls = _patch_monitor_common(monkeypatch, {
        "attempted": True,
        "method": "local_face_confirmation",
        "status": "verified_owner",
        "lock_suppressed": True,
        "fallback_reason": "",
        "elapsed_ms": 12.0,
        "verified_owner_after_anomaly": True,
        "eligible_for_shadow_evidence": True,
        "eligible_for_direct_production_training": False,
        "raw_images_stored": False,
    })

    incident._lock_and_stop_for_intruder(session_id="s1", risk=99, avg_risk=88.5, ml=1, ts="10:00:00")

    assert calls["capture"] == 0
    assert calls["lock"] == 0
    assert calls["stop"] == 0
    assert calls["states"]
    extra = calls["states"][-1]["extra"]
    assert extra["face_confirmation_lock_suppressed"] is True
    assert extra["false_positive_candidate"] is True
    assert extra["eligible_for_shadow_evidence"] is True
    assert extra["eligible_for_direct_production_training"] is False
    assert extra["incident_evidence_status"] == "skipped_face_confirmed_owner"


def test_failed_face_confirmation_keeps_existing_lock_and_evidence_path(monkeypatch):
    calls = _patch_monitor_common(monkeypatch, {
        "attempted": True,
        "method": "local_face_confirmation",
        "status": "camera_unavailable",
        "lock_suppressed": False,
        "fallback_reason": "camera_unavailable",
        "elapsed_ms": 3.0,
        "verified_owner_after_anomaly": False,
        "eligible_for_shadow_evidence": False,
        "eligible_for_direct_production_training": False,
        "raw_images_stored": False,
    })

    incident._lock_and_stop_for_intruder(session_id="s1", risk=99, avg_risk=88.5, ml=1, ts="10:00:00")

    assert calls["capture"] == 1
    assert calls["lock"] == 1
    assert calls["stop"] == 1


def test_suspicious_does_not_import_or_call_face_confirmation_directly():
    escalation_source = Path("monitor_core/escalation.py").read_text(encoding="utf-8")
    assert "confirm_identity_before_lock" not in escalation_source
    assert "identity_confirmation" not in escalation_source
    monitor_source = Path("src/bioauth/runtime/monitor_impl.py").read_text(encoding="utf-8")
    assert "confirm_identity_before_lock" in monitor_source
    assert "confirmed_intruder and not _shadow_evidence_mode()" in monitor_source


def test_raw_face_image_tokens_are_not_written_to_monitor_logs_or_state_source():
    combined = "\n".join(Path(path).read_text(encoding="utf-8").lower() for path in ["src/bioauth/runtime/monitor_impl.py", "monitor_core/incident.py"])
    forbidden = ["raw face image", "raw_image_path", "webcam_frame"]
    for token in forbidden:
        assert token not in combined
    assert "eligible_for_direct_production_training" in combined
