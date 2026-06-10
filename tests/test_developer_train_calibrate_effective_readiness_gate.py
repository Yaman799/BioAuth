from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _AliveProcess:
    def poll(self):
        return None


class _ExitedProcess:
    def poll(self):
        return 0


class _Signal:
    def __init__(self):
        self.count = 0

    def emit(self, *args, **kwargs):
        self.count += 1


class _DevTrainingApp:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._profile = {
            "training_can_start": True,
            "candidate_model_status": "approved_for_shadow",
            "production_ready": False,
        }
        self._sessions = []
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
        self._hybrid_direct_test_max_age_seconds = 24 * 60 * 60
        self._shadow_automation_paused = True
        self._developer_forced_production_ready = True
        self.controlsChanged = _Signal()
        self.hybridDirectChanged = _Signal()
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

    def _effective_production_ready(self):
        return True

    def _developer_production_ready_simulation_active(self):
        return True

    def _effective_production_ready_state(self):
        return {
            "effectiveProductionReady": True,
            "effective_production_ready": True,
            "devProductionReadySimulation": True,
            "dev_production_ready_simulation": True,
            "shadowPaused": True,
            "shadow_paused": True,
        }


def test_developer_effective_readiness_allows_train_without_hybrid_report_after_stop(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers

    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "missing.json"))
    app = _DevTrainingApp()

    status = training_helpers.training_gate_status(app)

    assert status["can_train"] is True
    assert status["training_sample_source"] == "normal_enrollment_archives_only"
    assert status["hybrid"]["passed"] is True
    assert status["hybrid"]["reason_code"] == "hybrid_test_not_required"
    assert status["hybrid"]["hybrid_removed_from_commercial_flow"] is True
    assert status["hybrid"]["hybrid_required_for_training"] is False


def test_train_calibrate_blocks_while_monitor_process_is_alive(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers

    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "missing.json"))
    app = _DevTrainingApp()
    app._running_processes["monitor"] = _AliveProcess()

    status = training_helpers.training_gate_status(app)

    assert status["can_train"] is False
    assert status["reason_code"] == "monitor_process_active"
    assert status["runtime_reason_code"] == "monitor_process_active"


def test_train_calibrate_blocks_while_protected_logger_is_alive(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers

    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "missing.json"))
    app = _DevTrainingApp()
    app._running_processes["logger_user_alice"] = _AliveProcess()

    status = training_helpers.training_gate_status(app)

    assert status["can_train"] is False
    assert status["reason_code"] == "active_session_running"
    assert status["runtime_reason_code"] == "logger_process_active"


def test_train_calibrate_blocks_while_monitor_start_or_stop_is_pending(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers

    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "missing.json"))
    app = _DevTrainingApp()
    app._pending_monitor_start = True
    assert training_helpers.training_gate_status(app)["reason_code"] == "pending_monitor_start"

    app = _DevTrainingApp()
    app._protected_session_stopping = True
    assert training_helpers.training_gate_status(app)["reason_code"] == "protected_session_stopping"


def test_train_calibrate_no_longer_depends_on_shadow_candidate_after_hybrid_removal(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers

    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "missing.json"))
    app = _DevTrainingApp()
    app._profile["candidate_model_status"] = ""

    status = training_helpers.training_gate_status(app)

    assert status["can_train"] is True
    assert status["hybrid"]["reason_code"] == "hybrid_test_not_required"


def test_train_calibrate_qml_remains_backend_owned() -> None:
    qml = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    marker = 'objectName: "overviewTrainCalibrateButton"'
    start = qml.index(marker)
    block = qml[qml.rfind("AppButton", 0, start): qml.find("AppButton", start + len(marker))]
    assert "enabled: backend.canTrain" in block
    assert "debugLabel: backend.trainingBlockedReason" in block
    assert "onClicked: backend.trainProfile()" in block
    for forbidden in ("effectiveProductionReady", "latestHybridDirectTestSummary", "production_ready", "runtime_decision"):
        assert forbidden not in block


def test_desktop_exposes_train_calibrate_reason_properties() -> None:
    desktop = (ROOT / "src" / "bioauth" / "app" / "desktop_app_impl.py").read_text(encoding="utf-8")
    assert re.search(r"@Property\(\"QVariantList\", notify=controlsChanged\)\s+def trainCalibrateReasonCodes", desktop)
    assert re.search(r"@Property\(str, notify=controlsChanged\)\s+def trainCalibrateStatusLabel", desktop)
    assert re.search(r"@Property\(str, notify=controlsChanged\)\s+def trainCalibrateDisabledReason", desktop)
