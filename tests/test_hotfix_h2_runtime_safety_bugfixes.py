from __future__ import annotations

import json
from pathlib import Path

import control
from safety_gate_policy import build_safety_gate_report


def _configure_control_storage(tmp_path: Path, monkeypatch) -> Path:
    control_dir = tmp_path / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    session_file = control_dir / "session_state.json"
    monkeypatch.setattr(control, "CONTROL_DIR", str(control_dir))
    monkeypatch.setattr(control, "SESSION_STATE_FILE", str(session_file))
    control.clear_session_state()
    return session_file


def _valid_rollback_snapshot() -> dict:
    return {
        "version": "classic-rollback-snapshot-v1",
        "created_at": "2026-05-04T20:53:49Z",
        "rollback_target": "classic_only",
        "developer_direct_enabled": False,
        "hybrid_can_influence_device": False,
    }


def test_write_session_state_dump_failure_preserves_original_exception(monkeypatch, tmp_path) -> None:
    _configure_control_storage(tmp_path, monkeypatch)

    def raise_primary_dump_failure(*args, **kwargs):
        raise RuntimeError("primary json dump failure")

    monkeypatch.setattr(control.json, "dump", raise_primary_dump_failure)

    assert control.write_session_state({"active": True, "user_id": "alice"}) is False
    diagnostics = control.session_state_diagnostics()

    assert diagnostics["last_issue"] == "session_state_write_failed"
    assert "primary json dump failure" in diagnostics["detail"]
    assert "Bad file descriptor" not in diagnostics["detail"]
    assert "EBADF" not in diagnostics["detail"]


def test_rollback_snapshot_rejects_empty_json_object(tmp_path) -> None:
    snapshot = tmp_path / "rollback.json"
    snapshot.write_text("{}", encoding="utf-8")

    report = build_safety_gate_report({}, {}, rollback_snapshot_path=snapshot)

    assert report["rollback_snapshot_exists"] is False
    assert report["gate_results"]["rollback_snapshot_exists"]["passed"] is False


def test_rollback_snapshot_rejects_unsafe_enabled_flags(tmp_path) -> None:
    payload = _valid_rollback_snapshot()
    payload["developer_direct_enabled"] = True
    snapshot = tmp_path / "rollback.json"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")

    report = build_safety_gate_report({}, {}, rollback_snapshot_path=snapshot)

    assert report["rollback_snapshot_exists"] is False
    assert report["gate_results"]["rollback_snapshot_exists"]["passed"] is False


def test_rollback_snapshot_accepts_valid_content(tmp_path) -> None:
    snapshot = tmp_path / "rollback.json"
    snapshot.write_text(json.dumps(_valid_rollback_snapshot()), encoding="utf-8")

    report = build_safety_gate_report({}, {}, rollback_snapshot_path=snapshot)

    assert report["rollback_snapshot_exists"] is True
    assert report["gate_results"]["rollback_snapshot_exists"]["passed"] is True


def test_existing_phase_10_snapshot_schema_is_explicitly_supported(tmp_path) -> None:
    snapshot = tmp_path / "rollback.json"
    snapshot.write_text(
        json.dumps(
            {
                "version": "classic-rollback-snapshot-v1",
                "created_at": "2026-05-04T20:53:49Z",
                "target_mode": "classic_only",
                "developer_direct_enabled": False,
                "can_influence_device": False,
            }
        ),
        encoding="utf-8",
    )

    report = build_safety_gate_report({}, {}, rollback_snapshot_path=snapshot)

    assert report["rollback_snapshot_exists"] is True
    assert report["gate_results"]["rollback_snapshot_exists"]["passed"] is True
