from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Signal:
    def __init__(self):
        self.count = 0
    def emit(self, *args, **kwargs):
        self.count += 1


class _GateApp:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._profile = {"training_can_start": True}
        self._sessions = []
        self._runtime_state = {}
        self._training_in_progress = False
        self._history_sync_pending = False
        self._pending_logger_start = False
        self._pending_monitor_start = False
        self._pending_shadow_evidence_monitor_start = False
        self._passive_auto_enrollment_finalizing = False
        self._running_processes = {}
        self._latest_hybrid_direct_test_result = {}
        self._hybrid_direct_test_max_age_seconds = 24 * 60 * 60
        self.controlsChanged = _Signal()
        self.hybridDirectChanged = _Signal()
        self.statuses = []
    def _safe_user(self): return "alice"
    def _session_flow(self): return "idle"
    def _active_state_for_current_user(self): return dict(self._runtime_state)
    def _logger_process_key(self): return "logger_user_alice"
    def _set_status(self, message, tone): self.statuses.append((message, tone))
    def _t(self, key, **kwargs): return key


def _write_report(path: Path, *, passed: bool = True, user: str = "alice", profile: str = "alice", timestamp: str | None = None, reason_codes: list[str] | None = None) -> dict:
    payload = {
        "passed": passed,
        "timestamp": timestamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user": user,
        "profile": profile,
        "reason_codes": list(reason_codes or (["hybrid_direct_monitor_prediction_completed"] if passed else ["hybrid_direct_monitor_prediction_not_ready"])),
        "monitor": {
            "runtime_mode": "hybrid_direct_test",
            "source": "hybrid_direct_test_monitor",
            "process_key": "hybrid_direct_test_monitor_user_alice",
            "uses_shadow_monitor": False,
            "uses_production_monitor_executable": True,
            "test_only": True,
            "device_influence_allowed": False,
        },
        "safety": {
            "lock_allowed": False,
            "device_lock_allowed": False,
            "protected_sessions_unlock_allowed": False,
            "production_pointer_write_allowed": False,
            "production_approval_allowed": False,
            "production_promotion_allowed": False,
            "raw_behavioral_data_included": False,
        },
        "report_path": str(path),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_training_allowed_when_no_hybrid_direct_test_result(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers
    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "missing.json"))
    app = _GateApp()
    status = training_helpers.training_gate_status(app)
    assert status["can_train"] is True
    assert status["hybrid"]["passed"] is True
    assert status["hybrid"]["reason_code"] == "hybrid_test_not_required"


def test_training_allowed_when_legacy_hybrid_direct_test_failed(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers
    report_path = tmp_path / "hybrid_direct_test_report_alice.json"
    _write_report(report_path, passed=False)
    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(report_path))
    app = _GateApp()
    status = training_helpers.training_gate_status(app)
    assert status["can_train"] is True
    assert status["hybrid"]["reason_code"] == "hybrid_test_not_required"


def test_training_ignores_legacy_hybrid_direct_test_stale_or_wrong_user(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers
    stale = tmp_path / "stale.json"
    _write_report(stale, timestamp="2000-01-01T00:00:00Z")
    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(stale))
    app = _GateApp()
    status = training_helpers.training_gate_status(app)
    assert status["can_train"] is True
    assert status["hybrid"]["reason_code"] == "hybrid_test_not_required"

    wrong = tmp_path / "wrong.json"
    _write_report(wrong, user="mallory", profile="mallory")
    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(wrong))
    app = _GateApp()
    status = training_helpers.training_gate_status(app)
    assert status["can_train"] is True
    assert status["hybrid"]["reason_code"] == "hybrid_test_not_required"


def test_training_allowed_with_enrollment_ready_and_passed_hybrid_test(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers
    report_path = tmp_path / "passed.json"
    _write_report(report_path, passed=True)
    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(report_path))
    app = _GateApp()
    status = training_helpers.training_gate_status(app)
    assert status["can_train"] is True
    assert status["training_sample_source"] == "normal_enrollment_archives_only"
    summary = training_helpers.latest_hybrid_direct_test_summary(app)
    assert summary["passed"] is True
    assert summary["shadow_evidence_training_allowed"] is False
    assert summary["hybrid_report_training_allowed"] is False


def test_training_blocked_without_enough_normal_enrollment_data(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    import bridge.session_training_helpers as training_helpers
    report_path = tmp_path / "passed.json"
    _write_report(report_path, passed=True)
    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(report_path))
    app = _GateApp()
    app._profile = {"training_can_start": False, "training_block_reason": "missing_enrollment_data"}
    status = training_helpers.training_gate_status(app)
    assert status["can_train"] is False
    assert status["reason_code"] == "missing_enrollment_data"


def test_training_uses_normal_enrollment_archives_only_and_excludes_shadow_hybrid_and_intruder():
    from feedback_loop import production_positive_training_allowed
    pipeline = (ROOT / "training_core" / "pipeline.py").read_text(encoding="utf-8")
    scan_block = pipeline[pipeline.index("def _scan_positive_training_candidates"):pipeline.index("def _evaluate_and_publish_candidate")]
    assert 'session_kind == "enrollment"' in scan_block
    assert 'elif session_kind == "protected"' not in scan_block
    assert production_positive_training_allowed({"session_kind": "enrollment", "metadata_trusted": True, "collection_source": "shadow_evidence"}) is False
    assert production_positive_training_allowed({"session_kind": "enrollment", "metadata_trusted": True, "source": "shadow_evidence_monitor"}) is False
    assert production_positive_training_allowed({"session_kind": "enrollment", "metadata_trusted": True, "source": "hybrid_direct_test_monitor"}) is False
    assert production_positive_training_allowed({"session_kind": "enrollment", "metadata_trusted": True, "confirmed_intruder": True}) is False


def test_qml_train_calibrate_uses_backend_gate_only():
    qml = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    marker = 'objectName: "overviewTrainCalibrateButton"'
    start = qml.index(marker)
    block = qml[qml.rfind("AppButton", 0, start): qml.find("AppButton", start + len(marker))]
    assert "enabled: backend.canTrain" in block
    assert "debugLabel: backend.trainingBlockedReason" in block
    assert "onClicked: backend.trainProfile()" in block
    for forbidden in ("productionReady", "protectedSessionsAvailable", "latestHybridDirectTestResult.passed", "training_can_start"):
        assert forbidden not in block
    desktop = (ROOT / "src" / "bioauth" / "app" / "desktop_app_impl.py").read_text(encoding="utf-8")
    assert re.search(r"@Property\(bool, notify=controlsChanged\)\s+def canTrain", desktop)
    assert re.search(r"@Property\(bool, notify=controlsChanged\)\s+def canCalibrate", desktop)
    assert re.search(r"@Property\(str, notify=controlsChanged\)\s+def trainingBlockedReason", desktop)


def test_hybrid_test_evidence_cannot_unlock_or_promote(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as runtime_helpers
    report_path = tmp_path / "passed.json"
    _write_report(report_path, passed=True)
    monkeypatch.setattr(runtime_helpers, "_hybrid_direct_test_report_path", lambda self: str(report_path))
    app = _GateApp()
    validated = runtime_helpers.validate_hybrid_direct_test_evidence(app)
    assert validated["ok"] is True
    report = validated["report"]
    assert report["safety"]["protected_sessions_unlock_allowed"] is False
    assert report["safety"]["production_pointer_write_allowed"] is False
    assert report["safety"]["production_approval_allowed"] is False
    assert report["safety"]["production_promotion_allowed"] is False
    helper_source = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    validation_block = helper_source[helper_source.index("def validate_hybrid_direct_test_evidence"):helper_source.index("def _hybrid_result_status_message")]
    for forbidden in ("write_active_runtime_pointer", "promote", "unlockProtected", "startProtected"):
        assert forbidden not in validation_block


def test_phase1_to_phase4_regression_contracts_remain_static():
    overview = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    assert 'objectName: "overviewStartEnrollmentLoggerButton"' in overview
    assert 'enabled: backend.canStartEnrollmentLogger' in overview
    assert 'onClicked: backend.startEnrollment()' in overview
    stop_block = overview[overview.index('objectName: "overviewStopMonitorButton"'):]
    assert 'enabled: backend.canStopProductionMonitor' in stop_block.split('AppButton', 1)[0]
    assert 'onClicked: backend.stopProductionMonitor(false)' in stop_block.split('AppButton', 1)[0]
    hybrid = (ROOT / "qml" / "pages" / "HybridDirectTestPage.qml").read_text(encoding="utf-8")
    assert 'enabled: backend.canRunHybridDirectTest' in hybrid  # legacy page file remains unmounted from commercial navigation
    assert 'onClicked: backend.runHybridDirectTest()' in hybrid  # legacy page file remains as an unmounted compatibility surface
    runtime = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    assert 'def _shadow_monitor_process_key' in runtime
    assert 'def _hybrid_direct_test_process_key' in runtime
