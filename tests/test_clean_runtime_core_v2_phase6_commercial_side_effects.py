from __future__ import annotations

import inspect
from pathlib import Path

from bioauth_runtime import runtime_boundary
from bridge import refresh_runtime_helpers


class _ProtectedApp:
    def __init__(self) -> None:
        self._current_user = {"user_id": "alice"}
        self._runtime_state = {"session_kind": "protected", "active": True, "status": "protected_active", "source": "supervisor"}
        self.calls: list[str] = []

    def _session_flow(self, state):
        return "protected_active"

    def _update_dashboard(self):
        self.calls.append("dashboard")

    def _handle_state_alerts(self):
        self.calls.append("alerts")

    def _maybe_resume_protection_after_unlock(self, state):
        self.calls.append("resume")
        return False

    def _maybe_auto_promote_production(self):
        self.calls.append("auto_promotion")
        return True

    def _maybe_finalize_passive_auto_enrollment(self):
        self.calls.append("passive_auto_finalizer")
        return True

    def _maybe_start_shadow_evidence_monitor(self):
        self.calls.append("shadow_evidence_bootstrap")
        return True

    def _maybe_start_auto_training(self):
        self.calls.append("auto_training")
        return True

    def _maybe_process_shadow_session(self):
        self.calls.append("shadow_session")

    def _maybe_process_shadow_backlog(self):
        self.calls.append("shadow_backlog")

    def _recover_stale_passive_auto_enrollment_finalization(self, *, source="refresh"):
        self.calls.append("passive_finalization_recovery")
        return True

    def _consume_shadow_status_result(self):
        self.calls.append("shadow_status_consume")
        return None

    def _should_refresh_shadow_status(self):
        self.calls.append("shadow_status_should_refresh")
        return True

    def _queue_shadow_status_refresh(self, user_id):
        self.calls.append("shadow_status_queue")
        return True

    def _check_shadow_suggestion(self, status):
        self.calls.append("shadow_status_suggestion")

    def _refresh_shadow_status(self, status=None, *, force=False):
        self.calls.append("shadow_status_refresh")


def test_runtime_boundary_identifies_commercial_protected_states():
    protected_states = [
        {"session_kind": "protected", "active": True, "status": "starting"},
        {"session_kind": "protected", "active": False, "status": "resume_pending"},
        {"session_kind": "protected", "active": False, "status": "protected_forced_stop"},
        {"runtime_mode": "protected", "runtime_status": "verifying_return"},
    ]
    for state in protected_states:
        assert runtime_boundary.is_commercial_protected_runtime(state) is True
        assert runtime_boundary.side_effects_allowed_for_refresh(state) is False
    assert runtime_boundary.side_effects_allowed_for_refresh({"session_kind": "enrollment", "active": True}) is True


def test_commercial_refresh_side_effect_group_returns_without_forbidden_jobs():
    app = _ProtectedApp()
    phase_ms: dict[str, int] = {}

    refresh_runtime_helpers._run_non_commercial_refresh_side_effects(app, dashboard_visible=True, phase_ms=phase_ms)

    for forbidden in (
        "auto_training",
        "auto_promotion",
        "shadow_backlog",
        "shadow_evidence_bootstrap",
        "shadow_session",
        "shadow_status_consume",
        "shadow_status_should_refresh",
        "shadow_status_queue",
        "shadow_status_refresh",
        "passive_auto_finalizer",
        "passive_finalization_recovery",
    ):
        assert forbidden not in app.calls


def test_commercial_refresh_individual_side_effect_helpers_are_guarded():
    app = _ProtectedApp()
    phase_ms: dict[str, int] = {}

    assert refresh_runtime_helpers._recover_passive_finalization(app, phase_ms) is False
    assert refresh_runtime_helpers._run_auto_promotion(app, True, False, phase_ms) is False
    assert refresh_runtime_helpers._run_noncommercial_bootstrap(app, True, False, phase_ms) == {
        "finalized": False,
        "shadow_started": False,
        "trained": False,
        "passive_started": False,
    }
    assert refresh_runtime_helpers._run_passive_finalizer(app, True, False, phase_ms) is False
    assert refresh_runtime_helpers._run_shadow_evidence_bootstrap(app, False, False, phase_ms) is False
    assert refresh_runtime_helpers._run_auto_training(app, False, False, False, phase_ms) is False
    assert refresh_runtime_helpers._run_passive_auto_enrollment(app, False, False, False, False, phase_ms) is False
    refresh_runtime_helpers._run_noncommercial_shadow_session(app, False, {}, phase_ms)
    refresh_runtime_helpers._refresh_noncommercial_shadow_status(app, phase_ms)

    assert app.calls == []


def test_refresh_perform_remains_lifecycle_display_oriented():
    source = inspect.getsource(refresh_runtime_helpers._perform_refresh_now)
    for forbidden in (
        "_maybe_finish_pending_logger_start(",
        "_maybe_finish_pending_monitor_start(",
        "check_worker_pair_liveness(",
        "_cleanup_processes(",
        "_start_process(",
        "request_stop(",
        "recover_stale_protected_flow_without_workers(",
        "stop_current_session(",
    ):
        assert forbidden not in source


def test_worker_lifecycle_public_wrappers_delegate_to_supervisor():
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "protection_session_controller.start_protection" in source
    assert "stop_controller.stop_protection" in source
    assert "resume_controller.maybe_resume_after_unlock" in source
    start_src = inspect.getsource(__import__("bridge.session_runtime_helpers", fromlist=["start_protected_session"]).start_protected_session)
    implementation = start_src.split('"""')[-1]
    assert "_start_process(" not in implementation


def test_commercial_start_path_does_not_call_demo_or_dev_runtime_activation():
    source = Path("bioauth_runtime/supervisor/protection_session_controller.py").read_text(encoding="utf-8")
    for forbidden in (
        "_ensure_demo_classic_runtime_pointer",
        "demo_classic_runtime_activation",
        "dev_production_ready_simulation",
        "auto_training",
        "auto_promotion",
        "shadow_backlog",
        "passive_auto_enrollment",
    ):
        assert forbidden not in source


def test_monitor_commercial_runtime_side_effects_are_explicitly_gated():
    source = Path("src/bioauth/runtime/monitor_impl.py").read_text(encoding="utf-8")
    assert "runtime_boundary.runtime_shadow_tap_enabled()" in source
    assert "def _demo_classic_runtime_overrides_enabled" in source
    assert "if demo_lock_override and _demo_classic_runtime_overrides_enabled():" in source
    assert "if _demo_classic_runtime_overrides_enabled():" in source
    assert "feedback_needed = False" in source
    assert "unknown_route" not in source


def test_demo_and_dev_features_are_default_disabled(monkeypatch):
    for name in (
        "BIOAUTH_BUILD_PROFILE",
        "BIOAUTH_BUILD_PROFILE_DEV",
        "BIOAUTH_DEMO_CLASSIC_PROTECTED",
        "BIOAUTH_ENABLE_DEMO_FEATURES",
        "BIOAUTH_DEV_ENABLE_RUNTIME_SHADOW_TAP",
    ):
        monkeypatch.delenv(name, raising=False)
    assert runtime_boundary.dev_features_enabled() is False
    assert runtime_boundary.demo_features_enabled() is False
    assert runtime_boundary.runtime_shadow_tap_enabled() is False


def test_demo_and_shadow_flags_require_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", "1")
    assert runtime_boundary.demo_features_enabled() is True
    monkeypatch.setenv("BIOAUTH_BUILD_PROFILE_DEV", "1")
    monkeypatch.setenv("BIOAUTH_DEV_ENABLE_RUNTIME_SHADOW_TAP", "1")
    assert runtime_boundary.runtime_shadow_tap_enabled() is True


def test_pre_lock_feedback_buttons_remain_disabled_but_post_lock_allowed():
    monitor_source = Path("src/bioauth/runtime/monitor_impl.py").read_text(encoding="utf-8")
    qml_source = Path("qml/Main.qml").read_text(encoding="utf-8")
    assert "feedback_needed = False" in monitor_source
    assert 'prompt.kind !== "post_lock_confirmation"' in qml_source
    lock_source = Path("bioauth_runtime/monitor_worker/lock_controller.py").read_text(encoding="utf-8")
    assert "postLockConfirmationPending" in lock_source
    assert "postLockConfirmationPromptAfterUnlock" in lock_source


def test_bridge_ui_does_not_overwrite_authoritative_decision_fields():
    source = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    for token in (
        'merged["raw_model_risk"] =',
        'merged["observed_model_risk"] =',
        'merged["action_risk"] =',
        'merged["display_risk"] =',
        'merged["decision_risk"] =',
        'merged["risk_level"] =',
        'merged["runtime_status"] =',
        'merged["runtime_decision"] =',
        'merged["final_action"] =',
        'merged["lock_reason"] =',
    ):
        assert token not in source


def test_high_risk_face_lock_path_still_references_phase5_modules():
    incident_source = Path("monitor_core/incident.py").read_text(encoding="utf-8")
    assert "face_gate.confirm_before_lock" in incident_source
    assert "face_gate.map_face_result" in incident_source
    assert "lock_controller.request_windows_lock" in incident_source


def test_production_approval_observe_is_fenced_during_protected_runtime():
    from bridge import refresh_dashboard_helpers

    class App:
        _runtime_state = {"session_kind": "protected", "active": True, "status": "protected_active"}
        _training_in_progress = False
        _pending_monitor_start = False
        _pending_logger_start = False

        def _session_flow(self, state):
            return "protected_active"

    assert refresh_dashboard_helpers._should_observe_production_approval_state(App(), {"production_approval_state": {"status": "approved"}}) is False


def test_root_entrypoints_still_importable():
    import desktop_app  # noqa: F401
    import logger  # noqa: F401
    import monitor  # noqa: F401
    import model_inference  # noqa: F401
    import model_training  # noqa: F401
    import paths  # noqa: F401
    import security  # noqa: F401
    import app_settings  # noqa: F401
