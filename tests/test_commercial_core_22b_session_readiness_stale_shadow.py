from __future__ import annotations

from pathlib import Path

from metadata_core.dashboard import build_user_dashboard_snapshot, build_session_readiness_audit
from bridge import session_runtime_helpers as runtime_helpers
from support_bundle import build_health_diagnostics


def _meta(user: str, *, kind: str = "enrollment", accepted: bool = True, trusted: bool = True, eligible: bool = True, rows: int = 260, duration: float = 20.0, stop_reason: str = "control_stop"):
    return {
        "user_id": user,
        "session_kind": kind,
        "final_decision": "legit" if accepted else "intruder",
        "metadata_trusted": trusted,
        "training_eligible": eligible,
        "keyboard_rows": rows // 2,
        "mouse_rows": rows // 2,
        "duration_seconds": duration,
        "stop_reason": stop_reason,
    }


def test_session_readiness_audit_explains_rejected_and_accepted_sessions(tmp_path: Path) -> None:
    records = []
    for idx in range(8):
        path = tmp_path / f"yaman_enroll_{idx}"
        path.mkdir()
        records.append((str(path), _meta("yaman")))
    rejected = tmp_path / "yaman_shadow_0"
    rejected.mkdir()
    records.append((str(rejected), _meta("yaman", kind="shadow_evidence", accepted=True)))
    low = tmp_path / "yaman_low_quality"
    low.mkdir()
    records.append((str(low), _meta("yaman", rows=2, duration=1.0)))

    def list_dirs():
        return [path for path, _ in records]

    def read_meta(path: str):
        return dict(dict(records)[path])

    snapshot = build_user_dashboard_snapshot(
        "yaman",
        list_session_dirs_fn=list_dirs,
        read_session_metadata_fn=read_meta,
        list_session_index_entries_fn=lambda: [],
        use_session_index=False,
        session_detail_limit=None,
    )
    profile = snapshot["profile"]
    audit = profile["session_readiness_audit"]
    assert audit["training_can_start"] is True
    assert profile["session_readiness_primary_blocker"] == ""
    assert audit["counts_toward_training_minimum"] == 8
    assert audit["rejection_reason_counts"]["shadow_evidence_excluded"] == 1
    assert audit["rejection_reason_counts"]["session_quality_baseline_not_met"] == 1

    direct = build_session_readiness_audit(
        "yaman",
        list_session_dirs_fn=list_dirs,
        read_session_metadata_fn=read_meta,
        list_session_index_entries_fn=lambda: [],
        use_session_index=False,
    )
    assert direct["records_sampled"] == 10
    assert direct["minimum_required_enrollment_sessions"] == 8


class _DummyShadowBridge:
    def __init__(self):
        self._current_user = {"user_id": "yaman"}
        self._runtime_state = {
            "active": True,
            "session_kind": "shadow_evidence",
            "status": "shadow_evidence",
            "monitor_ready": True,
        }
        self._pending_shadow_evidence_monitor_start = False
        self._pending_logger_start = False
        self._pending_logger_session_kind = ""
        self._running_processes = {}
        self.cleared = False

    def _active_state_for_current_user(self):
        return dict(self._runtime_state)


def test_stale_shadow_state_resolves_to_idle_when_no_shadow_process(monkeypatch) -> None:
    bridge = _DummyShadowBridge()

    def fake_clear_session_state():
        bridge.cleared = True

    monkeypatch.setattr(runtime_helpers._facade(), "clear_session_state", fake_clear_session_state)
    monkeypatch.setattr(runtime_helpers._facade(), "invalidate_session_discovery_cache", lambda: None)

    flow = runtime_helpers.session_flow(bridge, bridge._runtime_state)
    assert flow == "idle"
    assert bridge.cleared is True
    assert bridge._runtime_state == {}


def test_support_diagnostics_include_session_readiness(monkeypatch) -> None:
    monkeypatch.setattr(
        "metadata_core.dashboard.build_session_readiness_audit",
        lambda user_id, session_detail_limit=40: {
            "schema_version": "commercial-core-22b-session-readiness-audit-v1",
            "minimum_required_enrollment_sessions": 8,
            "total_session_records": 2,
            "accepted_enrollment_sessions": 1,
            "trusted_enrollment_sessions": 1,
            "training_eligible_enrollment_sessions": 1,
            "quality_ok_enrollment_sessions": 1,
            "counts_toward_training_minimum": 1,
            "training_deficit": 7,
            "training_can_start": False,
            "primary_blocker": "need_more_trusted_sessions",
            "session_kind_counts": {"enrollment": 1, "shadow_evidence": 1},
            "rejection_reason_counts": {"accepted_for_training_minimum": 1, "shadow_evidence_excluded": 1},
            "records_truncated": False,
            "records": [{"session_id": "s1", "session_kind": "enrollment", "reject_reason": ""}],
        },
    )
    diagnostics = build_health_diagnostics(user_id="yaman", runtime_state={"status": "idle"})
    readiness = diagnostics["session_readiness"]
    assert readiness["available"] is True
    assert readiness["primary_blocker"] == "need_more_trusted_sessions"
    assert any(check["id"] == "session_readiness" for check in diagnostics["checks"])
