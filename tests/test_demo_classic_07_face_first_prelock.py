from __future__ import annotations

from collections import deque

import app_settings
import identity_confirmation
import monitor_core.incident as incident


class _FaceService:
    def __init__(self, *, enrolled: bool = True, verified: bool = True) -> None:
        self.enrolled = enrolled
        self.verified = verified
        self.calls: list[tuple[str, str]] = []

    def status(self, user_id: str):
        self.calls.append(("status", user_id))
        return {"status": "enrolled" if self.enrolled else "not_enrolled", "enrolled": self.enrolled}

    def confirm_before_lock(self, user_id: str, frame=None):
        self.calls.append(("confirm_before_lock", user_id))
        return {"status": "verified" if self.verified else "not_verified", "verified": self.verified}


def _production_face_consent_settings(**extra):
    payload = {
        "build_profile": "production",
        "enable_face_confirmation": False,
        "face_confirmation_enabled": False,
        **app_settings.build_face_template_consent_fields(True),
    }
    payload.update(extra)
    return app_settings._coerce_settings_payload(payload)


def test_demo_classic_embedded_production_allows_face_env_override(monkeypatch):
    monkeypatch.setenv("BIOAUTH_BUILD_PROFILE", "production")
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED_EMBEDDED", "1")
    monkeypatch.setenv("BIOAUTH_ENABLE_FACE_CONFIRMATION_DEV", "1")
    monkeypatch.setenv("BIOAUTH_ENABLE_FACE_ENROLLMENT_DEV", "1")

    settings = app_settings._coerce_settings_payload({"build_profile": "production"})

    assert settings["enable_face_confirmation"] is False
    assert app_settings.feature_flag_enabled(settings, "enable_face_confirmation") is True
    assert app_settings.feature_flag_enabled(settings, "enable_face_enrollment") is True


def test_normal_production_still_ignores_face_env_override(monkeypatch):
    monkeypatch.setenv("BIOAUTH_BUILD_PROFILE", "production")
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", raising=False)
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED_EMBEDDED", raising=False)
    monkeypatch.setenv("BIOAUTH_ENABLE_FACE_CONFIRMATION_DEV", "1")

    settings = app_settings._coerce_settings_payload({"build_profile": "production"})

    assert app_settings.feature_flag_enabled(settings, "enable_face_confirmation") is False


def test_demo_classic_prelock_enables_face_preference_in_memory_only(monkeypatch):
    monkeypatch.setenv("BIOAUTH_BUILD_PROFILE", "production")
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED_EMBEDDED", "1")
    monkeypatch.setenv("BIOAUTH_ENABLE_FACE_CONFIRMATION_DEV", "1")
    service = _FaceService(enrolled=True, verified=True)
    captured: dict[str, object] = {}

    class Facade:
        EXPECTED_USER_SLUG = "owner"

        @staticmethod
        def load_settings():
            return _production_face_consent_settings()

        @staticmethod
        def demo_classic_protected_enabled():
            return True

        @staticmethod
        def build_default_identity_confirmation_service():
            return service

        @staticmethod
        def confirm_identity_before_lock(user_id, **kwargs):
            captured["settings"] = dict(kwargs.get("settings") or {})
            return identity_confirmation.confirm_identity_before_lock(user_id, **kwargs)

    monkeypatch.setattr(incident, "_facade", lambda: Facade, raising=False)

    result = incident._pre_lock_face_confirmation(session_id="s1", risk=96, avg_risk=92.0, ml=1)

    assert result["status"] == "verified_owner"
    assert result["lock_suppressed"] is True
    assert result["face_confirmation_demo_prelock_override"] is True
    assert captured["settings"]["face_confirmation_enabled"] is True
    assert service.calls == [("status", "owner"), ("confirm_before_lock", "owner")]


def test_demo_classic_prelock_does_not_open_face_without_consent(monkeypatch):
    monkeypatch.setenv("BIOAUTH_BUILD_PROFILE", "production")
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED_EMBEDDED", "1")
    monkeypatch.setenv("BIOAUTH_ENABLE_FACE_CONFIRMATION_DEV", "1")
    service = _FaceService(enrolled=True, verified=True)

    class Facade:
        EXPECTED_USER_SLUG = "owner"

        @staticmethod
        def load_settings():
            return app_settings._coerce_settings_payload({"build_profile": "production"})

        @staticmethod
        def demo_classic_protected_enabled():
            return True

        @staticmethod
        def build_default_identity_confirmation_service():
            return service

        @staticmethod
        def confirm_identity_before_lock(user_id, **kwargs):
            return identity_confirmation.confirm_identity_before_lock(user_id, **kwargs)

    monkeypatch.setattr(incident, "_facade", lambda: Facade, raising=False)

    result = incident._pre_lock_face_confirmation(session_id="s1", risk=96, avg_risk=92.0, ml=1)

    assert result["status"] in {"disabled", "consent_required"}
    assert result["lock_suppressed"] is False
    assert result["face_confirmation_demo_prelock_override"] is False
    assert service.calls == []


def test_demo_classic_override_reports_face_first_required(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    import monitor

    result = monitor._resolve_runtime_escalation(
        model_decision="suspicious",
        recent_decisions=deque(["suspicious", "suspicious", "suspicious"]),
        recent_risks=deque([90.0, 95.0, 97.0]),
        risk=98,
        avg_risk=95.0,
        ml=1,
        elapsed=30.0,
        warnings=3,
        config=monitor.resolve_runtime_escalation_config(None, None),
        locking_allowed=False,
        locking_reason="lock_suppressed_by_calibration_immature",
        quality_lock_ok_windows=3,
    )

    assert result["confirmed_intruder"] is True
    assert result["protected_action_requested"] is True
    assert result["face_confirmation_required_before_lock"] is True
    assert result["protected_action_phase"] == "pre_lock_face_confirmation_required"
    assert result["final_action"] == "pre_lock_face_confirmation_required"
