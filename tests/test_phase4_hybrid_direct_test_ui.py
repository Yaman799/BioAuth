from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Signal:
    def __init__(self):
        self.count = 0
    def emit(self, *args, **kwargs):
        self.count += 1

class _Completed:
    returncode = 0
    stdout = "monitor ok"
    stderr = ""

class _FakeFacade:
    BASE_DIR = str(ROOT)
    MONITOR_SCRIPT = "monitor.py"
    os = __import__("os")
    time = __import__("time")
    class subprocess:
        PIPE = object()
        class TimeoutExpired(Exception): pass
        calls = []
        @staticmethod
        def run(command, **kwargs):
            _FakeFacade.subprocess.calls.append((list(command), dict(kwargs)))
            env = kwargs.get("env") or {}
            report_path = env.get("BIOAUTH_HYBRID_TEST_REPORT_PATH")
            assert report_path
            Path(report_path).parent.mkdir(parents=True, exist_ok=True)
            Path(report_path).write_text(json.dumps({
                "passed": True,
                "timestamp": "2026-05-07T00:00:00Z",
                "user": "alice",
                "profile": "alice",
                "reason_codes": ["hybrid_direct_monitor_prediction_completed", "device_influence_disabled"],
                "monitor": {"runtime_mode": "hybrid_direct_test", "source": "hybrid_direct_test_monitor", "process_identity": "hybrid_direct_test_monitor_user_alice", "uses_shadow_monitor": False, "uses_production_monitor_executable": True, "test_only": True, "device_influence_allowed": False},
                "safety": {"device_lock_allowed": False, "protected_sessions_unlock_allowed": False, "production_pointer_write_allowed": False, "production_approval_allowed": False, "production_promotion_allowed": False},
                "result": {"status": "ok", "decision": "legit", "latency_ms": 1.0},
            }), encoding="utf-8")
            return _Completed()
    @staticmethod
    def _spawn_command(worker, *args):
        return ["python", "monitor.py", *args]

class _HybridApp:
    def __init__(self):
        self._current_user = {"user_id": "alice"}
        self._profile = {"production_ready": True}
        self._runtime_state = {}
        self._training_in_progress = False
        self._pending_logger_start = False
        self._pending_monitor_start = False
        self._pending_shadow_evidence_monitor_start = False
        self._running_processes = {}
        self._hybrid_direct_state = {}
        self._hybrid_direct_test_running = False
        self._latest_hybrid_direct_test_result = {}
        self.hybridDirectChanged = _Signal()
        self.controlsChanged = _Signal()
        self.statuses = []
        self.refreshes = []
    def _safe_user(self): return "alice"
    def _session_flow(self): return "idle"
    def _shadow_logger_process_key(self): return "shadow_logger_user_alice"
    def _shadow_monitor_process_key(self): return "shadow_monitor_user_alice"
    def _debug_trace(self, *args, **kwargs): return None
    def _set_status(self, message, tone): self.statuses.append((message, tone))
    def requestRefresh(self, reason, force=False): self.refreshes.append((reason, force))

def _qml_button_block(source: str, object_name: str) -> str:
    marker = f'objectName: "{object_name}"'
    start = source.index(marker)
    brace_start = source.rfind("AppButton", 0, start)
    next_button = source.find("AppButton", start + len(marker))
    return source[brace_start: next_button if next_button != -1 else len(source)]

def test_hybrid_direct_button_uses_backend_owned_slot_and_state():
    qml = (ROOT / "qml" / "pages" / "HybridDirectTestPage.qml").read_text(encoding="utf-8")
    block = _qml_button_block(qml, "hybridDirectRunDecisionButton")
    assert "enabled: backend.canRunHybridDirectTest" in block
    assert "onClicked: backend.runHybridDirectTest()" in block
    assert "backend.hybridDirectTestRunning" in block
    assert "productionReady" not in block
    assert "protectedSessionsAvailable" not in block

def test_backend_exposes_hybrid_direct_properties_and_slot():
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    mixin = (ROOT / "bridge" / "session_mixin.py").read_text(encoding="utf-8")
    assert re.search(r"@Property\(bool, notify=hybridDirectChanged\)\s+def canRunHybridDirectTest", desktop)
    assert re.search(r"@Property\(bool, notify=hybridDirectChanged\)\s+def hybridDirectTestRunning", desktop)
    assert re.search(r"@Property\(\"QVariantMap\", notify=hybridDirectChanged\)\s+def latestHybridDirectTestResult", desktop)
    assert re.search(r"@Slot\(result=\"QVariantMap\"\)\s+def runHybridDirectTest", mixin)

def test_can_run_hybrid_direct_test_blocks_unsafe_states():
    import bridge.session_runtime_helpers as helpers
    app = _HybridApp()
    assert helpers.can_run_hybrid_direct_test(app) is True
    app._current_user = None
    assert "no_authenticated_user" in helpers.hybrid_direct_test_blockers(app)
    app = _HybridApp(); app._session_flow = lambda: "shadow_evidence_active"
    assert any(code.startswith("incompatible_runtime_flow:shadow_evidence_active") for code in helpers.hybrid_direct_test_blockers(app))
    app = _HybridApp(); app._running_processes = {"shadow_monitor_user_alice": types.SimpleNamespace(poll=lambda: None)}
    assert "shadow_collection_active" in helpers.hybrid_direct_test_blockers(app)
    app = _HybridApp(); app._profile = {"production_ready": False}
    assert helpers.can_run_hybrid_direct_test(app) is True
    assert "production_model_not_ready" not in helpers.hybrid_direct_test_blockers(app)
    assert "production_model_not_ready" in helpers.hybrid_direct_monitor_smoke_test_blockers(app)

def test_run_hybrid_direct_test_uses_offline_replay_runner_and_safe_state(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as helpers
    _FakeFacade.subprocess.calls = []
    monkeypatch.setattr(helpers, "_facade", lambda: _FakeFacade)
    monkeypatch.setattr(helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "hybrid_direct_test_report.json"))
    monkeypatch.setattr(helpers, "_hybrid_direct_replay_sessions_root", lambda: str(tmp_path / "sessions"))

    def fake_runner(**kwargs):
        assert kwargs["sessions_root"] == str(tmp_path / "sessions")
        return {
            "status": "completed",
            "source": "user_replay_sessions",
            "session_count": 1,
            "sessions_discovered": 1,
            "sessions_evaluated": 1,
            "labeled_session_count": 1,
            "unlabeled_session_count": 0,
            "candidate_count": 1,
            "candidate_result_rows": 1,
            "available_candidate_count": 0,
            "unavailable_candidate_count": 1,
            "missing_artifact_count": 1,
            "report_paths": {"summary": str(tmp_path / "hybrid_direct_summary.md")},
            "warnings": [],
            "errors": [],
            "candidate_algorithms_executed": True,
            "training_performed": False,
            "production_selection_performed": False,
            "benchmark_selection_performed": False,
            "can_lock": False,
            "can_lock_alone": False,
            "can_influence_device": False,
            "trigger_face_confirmation": False,
            "runtime_authoritative": False,
        }

    monkeypatch.setattr("hybrid_candidates.offline_runner.run_offline_candidate_replay", fake_runner)
    app = _HybridApp()
    result = helpers.run_hybrid_direct_test(app)
    assert result["passed"] is True
    assert result["mode"] == "offline_candidate_replay"
    assert result["source"] == "user_replay_sessions"
    assert result["safety"]["device_lock_allowed"] is False
    assert result["safety"]["protected_sessions_unlock_allowed"] is False
    assert result["safety"]["face_confirmation_allowed"] is False
    assert result["safety"]["face_confirmation_trigger_allowed"] is False
    assert result["safety"]["production_pointer_write_allowed"] is False
    assert result["safety"]["production_approval_allowed"] is False
    assert result["safety"]["production_promotion_allowed"] is False
    assert result["offline_replay"]["candidate_algorithms_executed"] is True
    assert result["offline_replay"]["can_influence_device"] is False
    assert result["offline_replay"]["trigger_face_confirmation"] is False
    assert _FakeFacade.subprocess.calls == []
    assert app._hybrid_direct_test_running is False


def test_hybrid_direct_monitor_smoke_test_keeps_legacy_safe_env(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as helpers
    _FakeFacade.subprocess.calls = []
    monkeypatch.setattr(helpers, "_facade", lambda: _FakeFacade)
    monkeypatch.setattr(helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "hybrid_direct_monitor_smoke_report.json"))
    app = _HybridApp()
    result = helpers.run_hybrid_direct_monitor_smoke_test(app)
    assert result["passed"] is True
    assert result["monitor"]["runtime_mode"] == "hybrid_direct_test"
    assert result["monitor"]["uses_shadow_monitor"] is False
    assert result["monitor"]["uses_production_monitor_executable"] is True
    assert result["safety"]["device_lock_allowed"] is False
    assert result["safety"]["protected_sessions_unlock_allowed"] is False
    assert result["safety"]["face_confirmation_allowed"] is False
    assert result["safety"]["face_confirmation_trigger_allowed"] is False
    assert result["safety"]["production_pointer_write_allowed"] is False
    assert result["safety"]["production_approval_allowed"] is False
    assert result["safety"]["production_promotion_allowed"] is False
    command, kwargs = _FakeFacade.subprocess.calls[0]
    assert "monitor.py" in command
    assert not any("shadow_monitor_user" in str(item) for item in command)
    env = kwargs["env"]
    assert env["BIOAUTH_RUNTIME_MODE"] == "hybrid_direct_test"
    assert env["BIOAUTH_HYBRID_TEST_ONLY"] == "1"
    assert env["BIOAUTH_DEVICE_INFLUENCE_ALLOWED"] == "0"
    assert app._hybrid_direct_test_running is False

def test_run_hybrid_direct_test_does_not_require_production_ready(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as helpers
    _FakeFacade.subprocess.calls = []
    monkeypatch.setattr(helpers, "_facade", lambda: _FakeFacade)
    monkeypatch.setattr(helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "no_data_report.json"))
    monkeypatch.setattr(helpers, "_hybrid_direct_reports_dir", lambda: str(tmp_path / "hybrid_direct_reports"))
    monkeypatch.setattr(helpers, "_hybrid_direct_replay_sessions_root", lambda: str(tmp_path / "empty_sessions"))
    app = _HybridApp(); app._profile = {"production_ready": False}
    result = helpers.run_hybrid_direct_test(app)
    assert result["passed"] is True
    assert result["status"] == "no_eligible_sessions"
    assert "production_model_not_ready" not in result["reason_codes"]
    assert result["safety"]["device_lock_allowed"] is False
    assert result["safety"]["production_promotion_allowed"] is False
    assert _FakeFacade.subprocess.calls == []
    assert Path(result["report_path"]).exists()


def test_run_hybrid_direct_test_blocked_writes_result_without_spawning(monkeypatch, tmp_path):
    import bridge.session_runtime_helpers as helpers
    _FakeFacade.subprocess.calls = []
    monkeypatch.setattr(helpers, "_facade", lambda: _FakeFacade)
    monkeypatch.setattr(helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "blocked_report.json"))
    app = _HybridApp(); app._current_user = None
    result = helpers.run_hybrid_direct_test(app)
    assert result["passed"] is False
    assert "no_authenticated_user" in result["reason_codes"]
    assert _FakeFacade.subprocess.calls == []
    assert Path(result["report_path"]).exists()

def test_monitor_hybrid_direct_test_mode_is_safe_and_not_shadow():
    source = (ROOT / "src" / "bioauth" / "runtime" / "monitor_impl.py").read_text(encoding="utf-8")
    assert 'HYBRID_DIRECT_TEST_MODE = RUNTIME_MODE == "hybrid_direct_test"' in source
    assert 'BIOAUTH_HYBRID_TEST_ONLY' in source
    assert 'BIOAUTH_DEVICE_INFLUENCE_ALLOWED' in source
    assert 'HYBRID_DIRECT_TEST_SOURCE = "hybrid_direct_test_monitor"' in source
    assert '"device_lock_allowed": False' in source
    assert '"protected_sessions_unlock_allowed": False' in source
    assert '"face_confirmation_allowed": False' in source
    assert '"face_confirmation_trigger_allowed": False' in source
    assert '"production_pointer_write_allowed": False' in source
    assert '"production_promotion_allowed": False' in source
    hybrid_block = source[source.index('def _run_hybrid_direct_test_once'):source.index('def _request_shutdown')]
    assert 'lock_current_session' not in hybrid_block
    assert 'write_session_state' not in hybrid_block
    assert 'shadow_monitor_user_' not in hybrid_block

def test_phase1_phase2_phase3_invariants_remain():
    overview = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    assert 'objectName: "overviewStartEnrollmentLoggerButton"' in overview
    assert 'enabled: backend.canStartEnrollmentLogger' in overview
    assert 'onClicked: backend.startEnrollment()' in overview
    stop_block = overview[overview.index('objectName: "overviewStopMonitorButton"'):]
    assert 'enabled: backend.canStopProductionMonitor' in stop_block
    assert 'onClicked: backend.stopProductionMonitor(false)' in stop_block
    assert 'backend.stopCurrentSession(false)' not in stop_block.split('AppButton', 1)[0]
    monitor = (ROOT / "src" / "bioauth" / "runtime" / "monitor_impl.py").read_text(encoding="utf-8")
    assert 'shadow_evidence_report_only_monitor' in monitor
    assert 'production_pointer_write_allowed' in monitor
