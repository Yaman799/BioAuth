from __future__ import annotations

import json
from pathlib import Path

import control


def _configure_control_storage(tmp_path: Path, monkeypatch) -> Path:
    control_dir = tmp_path / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    session_file = control_dir / "session_state.json"
    monkeypatch.setattr(control, "CONTROL_DIR", str(control_dir))
    monkeypatch.setattr(control, "SESSION_STATE_FILE", str(session_file))
    control.clear_session_state()
    return session_file


def test_read_session_state_reports_malformed_json(monkeypatch, tmp_path) -> None:
    session_file = _configure_control_storage(tmp_path, monkeypatch)
    session_file.write_text("{bad-json", encoding="utf-8")

    result = control.read_session_state(default={})
    diagnostics = control.session_state_diagnostics()

    assert result == {}
    assert diagnostics["last_issue"] == "malformed_json"


def test_read_session_state_reports_tampering(monkeypatch, tmp_path) -> None:
    session_file = _configure_control_storage(tmp_path, monkeypatch)
    control.write_session_state({"active": True, "user_id": "alice"})
    payload = json.loads(session_file.read_text(encoding="utf-8"))
    payload["active"] = False
    session_file.write_text(json.dumps(payload), encoding="utf-8")

    result = control.read_session_state(default={})
    diagnostics = control.session_state_diagnostics()

    assert result == {}
    assert diagnostics["last_issue"] == "integrity_failed"


def test_read_session_state_reports_unsigned_partial_recovery(monkeypatch, tmp_path) -> None:
    session_file = _configure_control_storage(tmp_path, monkeypatch)
    session_file.write_text(json.dumps({"active": True, "user_id": "alice"}), encoding="utf-8")

    result = control.read_session_state(default={})
    diagnostics = control.session_state_diagnostics()

    assert result == {}
    assert diagnostics["last_issue"] == "unsigned_payload"


def test_valid_session_state_clears_previous_diagnostic(monkeypatch, tmp_path) -> None:
    _configure_control_storage(tmp_path, monkeypatch)
    control.write_session_state({"active": True, "user_id": "alice"})
    first = control.read_session_state(default={})
    diagnostics = control.session_state_diagnostics()

    assert first["active"] is True
    assert diagnostics["last_issue"] is None

def test_write_session_state_preserves_original_dump_exception(monkeypatch, tmp_path) -> None:
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

