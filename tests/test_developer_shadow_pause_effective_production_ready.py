from __future__ import annotations

from pathlib import Path

from app_settings import _coerce_settings_payload
from metadata_core.developer_readiness import build_effective_production_ready_state
from bridge import session_runtime_helpers

ROOT = Path(__file__).resolve().parents[1]


def _state(*, profile_ready=False, shadow_paused=False, forced=False, interface_mode="developer"):
    return build_effective_production_ready_state(
        settings={"interface_mode": interface_mode},
        profile={"production_ready": profile_ready},
        shadow_paused=shadow_paused,
        developer_forced=forced,
    )


def test_shadow_pause_developer_override_makes_effective_ready_without_real_metadata():
    state = _state(profile_ready=False, shadow_paused=True, forced=True)
    assert state["effectiveProductionReady"] is True
    assert state["devProductionReadySimulation"] is True
    assert state["realProductionReady"] is False
    assert state["reason"] == "developer_shadow_pause_simulation"


def test_resume_or_user_mode_disables_effective_readiness_when_real_ready_false():
    assert _state(profile_ready=False, shadow_paused=False, forced=True)["effectiveProductionReady"] is False
    assert _state(profile_ready=False, shadow_paused=True, forced=False)["effectiveProductionReady"] is False
    user_state = _state(profile_ready=False, shadow_paused=True, forced=True, interface_mode="user")
    assert user_state["effectiveProductionReady"] is False
    assert user_state["reason"] == "blocked_developer_mode_disabled"


def test_real_production_ready_still_wins_without_simulation():
    state = _state(profile_ready=True, shadow_paused=False, forced=False)
    assert state["effectiveProductionReady"] is True
    assert state["devProductionReadySimulation"] is False
    assert state["realProductionReady"] is True
    assert state["reason"] == "real_production_ready"


def test_settings_default_and_coercion_keep_developer_override_fail_closed():
    defaults = _coerce_settings_payload({})
    assert defaults["shadow_automation_paused"] is False
    assert defaults["developer_forced_production_ready"] is False
    coerced = _coerce_settings_payload({"shadow_automation_paused": "yes", "developer_forced_production_ready": "1"})
    assert coerced["shadow_automation_paused"] is True
    assert coerced["developer_forced_production_ready"] is True


class _DummyBridge:
    _current_user = {"user_id": "alice"}
    _training_in_progress = False
    _pending_logger_start = False
    _pending_monitor_start = False
    _pending_shadow_evidence_monitor_start = False
    _running_processes = {}
    _profile = {"production_ready": False}

    def __init__(self, effective: bool):
        self._effective = effective

    def _session_flow(self):
        return "idle"

    def _effective_production_ready(self):
        return self._effective


def test_hybrid_direct_monitor_smoke_uses_effective_readiness_for_developer_runtime_flow():
    allowed = session_runtime_helpers.hybrid_direct_monitor_smoke_test_blockers(_DummyBridge(True))
    blocked = session_runtime_helpers.hybrid_direct_monitor_smoke_test_blockers(_DummyBridge(False))
    assert "production_model_not_ready" not in allowed
    assert "production_model_not_ready" in blocked


def test_report_only_hybrid_direct_test_remains_decoupled_from_production_readiness():
    blocked = session_runtime_helpers.hybrid_direct_test_blockers(_DummyBridge(False))
    assert "production_model_not_ready" not in blocked


def test_shadow_pause_slot_mirrors_developer_override_and_never_writes_real_production_metadata():
    settings_mixin = (ROOT / "bridge" / "settings_mixin.py").read_text(encoding="utf-8")
    session_runtime = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    assert "self._developer_forced_production_ready = requested" in settings_mixin
    assert "developer_forced_production_ready=requested" in settings_mixin
    assert 'profile.get("production_ready")' in session_runtime
    assert 'profile_payload.get("production_ready")' in desktop
    assert "dev_production_ready_simulation_ignored_for_protected_session_gate" in session_runtime
    changed_sources = "\n".join([settings_mixin, session_runtime, desktop])
    assert '["production_ready"] = True' not in changed_sources
    assert "['production_ready'] = True" not in changed_sources
    assert 'approval_status = "approved_for_production"' not in changed_sources
    assert "approval_status = 'approved_for_production'" not in changed_sources


class _ProtectedStartBridge:
    _current_user = {"user_id": "alice"}
    _profile = {"production_ready": False}

    def __init__(self):
        self.statuses = []

    def _has_current_user_welcome_consent(self):
        return True

    def _effective_production_ready(self):
        return True

    def _developer_production_ready_simulation_active(self):
        return True

    def _set_status(self, message, tone):
        self.statuses.append((message, tone))

    def _t(self, key):
        return key


def test_developer_effective_readiness_does_not_unlock_protected_sessions(monkeypatch):
    class _Facade:
        @staticmethod
        def user_profile_status(_user_id):
            return {"production_ready": False}

    monkeypatch.setattr(session_runtime_helpers, "_facade", lambda: _Facade)
    bridge = _ProtectedStartBridge()
    assert session_runtime_helpers.start_protected_session(bridge) is False
    assert bridge.statuses == [("profile_not_runtime_ready", "warn")]


def test_settings_qml_displays_backend_owned_effective_state_without_local_production_ready_assignment():
    qml = (ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml").read_text(encoding="utf-8")
    assert "backend.effectiveProductionReadyState" in qml
    assert "backend.effectiveProductionReadyLabel" in qml
    assert "backend.effectiveProductionReady === true" in qml
    assert "function productionReady" not in qml
    assert "productionReady:" not in qml
