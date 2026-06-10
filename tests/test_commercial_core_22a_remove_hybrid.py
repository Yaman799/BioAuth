from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Signal:
    def __init__(self):
        self.count = 0

    def emit(self, *args, **kwargs):
        self.count += 1


class _App:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._profile = {"training_can_start": True, "production_ready": False}
        self._runtime_state = {}
        self._training_in_progress = False
        self._history_sync_pending = False
        self._pending_logger_start = False
        self._pending_monitor_start = False
        self._pending_shadow_evidence_monitor_start = False
        self._passive_auto_enrollment_finalizing = False
        self._protected_session_stopping = False
        self._running_processes = {}
        self._latest_hybrid_direct_test_result = {}
        self._hybrid_direct_test_running = False
        self.hybridDirectChanged = _Signal()
        self.controlsChanged = _Signal()
        self.statuses = []

    def _safe_user(self):
        return "alice"

    def _session_flow(self):
        return "idle"

    def _normal_user_session_flow(self):
        return "idle"

    def _active_state_for_current_user(self):
        return dict(self._runtime_state)

    def _logger_process_key(self):
        return "logger_user_alice"

    def _set_status(self, message, tone):
        self.statuses.append((message, tone))

    def _t(self, key, **kwargs):
        return key


def test_training_gate_no_longer_requires_hybrid_report(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers

    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "missing.json"))
    app = _App()

    status = training_helpers.training_gate_status(app)

    assert status["can_train"] is True
    assert status["training_sample_source"] == "normal_enrollment_archives_only"
    assert status["hybrid"]["passed"] is True
    assert status["hybrid"]["reason_code"] == "hybrid_test_not_required"
    assert status["hybrid"]["hybrid_removed_from_commercial_flow"] is True
    assert status["hybrid"]["hybrid_required_for_training"] is False


def test_hybrid_validation_is_not_required_for_commercial_training(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers

    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "missing.json"))
    app = _App()

    result = runtime_helpers.validate_hybrid_direct_test_evidence(app)

    assert result["ok"] is True
    assert result["reason_code"] == "hybrid_test_not_required"
    assert result["summary"]["passed"] is True
    assert result["summary"]["hybrid_required_for_training"] is False


def test_hybrid_run_slot_returns_removed_stub(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers

    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "hybrid.json"))
    app = _App()

    result = runtime_helpers.run_hybrid_direct_test(app)

    assert result["ok"] is False
    assert result["status"] == "removed"
    assert result["reason_code"] == "hybrid_direct_removed_from_commercial_flow"
    assert result["can_influence_device"] is False
    assert result["production_promotion_allowed"] is False
    assert app._hybrid_direct_test_running is False
    assert app.hybridDirectChanged.count >= 1


def test_commercial_navigation_hides_hybrid_page():
    app_shell = (ROOT / "qml" / "AppShell.qml").read_text(encoding="utf-8")
    overview = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    settings = (ROOT / "qml" / "pages" / "settings" / "SettingsSecurityTab.qml").read_text(encoding="utf-8")

    assert "HybridDirectTestPage" not in app_shell
    assert "hybridDirectLoaded" not in app_shell
    assert 'trx("Hybrid Direct Test", "Hybrid Direct Test")' not in app_shell
    assert "overviewOpenDirectTestButton" not in overview
    assert "overviewEmergencyDisableHybridButton" not in overview
    assert "Hybrid Direct Test" not in overview
    assert "emergencyDisableHybridButton" in settings
    assert "visible: false" in settings
