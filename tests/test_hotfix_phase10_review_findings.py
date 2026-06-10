from __future__ import annotations

import ast
import importlib
import json
import logging
from pathlib import Path

import app_settings
import bio_platform.secrets as secret_backend
import bridge.refresh_runtime_helpers as refresh_runtime_helpers
import control
import paths
import security
from safety_gate_policy import build_safety_gate_report

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SAFETY_DATAS_ENTRY = ("reports/safety", "reports/safety")
DEVELOPER_DIRECT_KEYS = (
    "developer_direct_test_enabled",
    "developer_direct_consent_enabled",
)


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _function_node(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def _existing_datas_pairs_from_spec() -> list[tuple[str, str]]:
    tree = ast.parse((ROOT / "BioAuth.spec").read_text(encoding="utf-8"), filename="BioAuth.spec")
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "_existing_datas":
            continue
        for arg in node.args:
            if (
                isinstance(arg, ast.Tuple)
                and len(arg.elts) == 2
                and all(isinstance(elt, ast.Constant) and isinstance(elt.value, str) for elt in arg.elts)
            ):
                pairs.append((arg.elts[0].value, arg.elts[1].value))
    return pairs


def _valid_rollback_snapshot() -> dict[str, object]:
    return {
        "version": "classic-rollback-snapshot-v1",
        "created_at": "2026-05-04T20:53:49Z",
        "rollback_target": "classic_only",
        "developer_direct_enabled": False,
        "hybrid_can_influence_device": False,
    }


def _configure_control_storage(tmp_path: Path, monkeypatch) -> Path:
    control_dir = tmp_path / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    session_file = control_dir / "session_state.json"
    monkeypatch.setattr(control, "CONTROL_DIR", str(control_dir))
    monkeypatch.setattr(control, "SESSION_STATE_FILE", str(session_file))
    control.clear_session_state()
    return session_file


def test_h1_packaged_reports_safety_datas_entry_is_present_and_core_datas_preserved() -> None:
    pairs = set(_existing_datas_pairs_from_spec())

    for required_entry in {
        ("qml", "qml"),
        ("config", "config"),
        ("model_runtime", "model_runtime"),
        ("docs", "docs"),
        REQUIRED_SAFETY_DATAS_ENTRY,
    }:
        assert required_entry in pairs


def test_h2_write_session_state_preserves_original_dump_exception_without_double_close(monkeypatch, tmp_path) -> None:
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

    src = _source("control.py")
    function = _function_node(ast.parse(src), "write_session_state")
    segment = ast.get_source_segment(src, function) or ""
    assert "fd_owned = fd" in segment
    assert "fd = -1" in segment
    assert "os.fdopen(fd_owned" in segment


def test_h2_rollback_snapshot_rejects_empty_json_and_accepts_valid_content(tmp_path) -> None:
    invalid_snapshot = tmp_path / "invalid_rollback.json"
    invalid_snapshot.write_text("{}", encoding="utf-8")

    invalid_report = build_safety_gate_report({}, {}, rollback_snapshot_path=invalid_snapshot)
    assert invalid_report["rollback_snapshot_exists"] is False
    assert invalid_report["gate_results"]["rollback_snapshot_exists"]["passed"] is False

    valid_snapshot = tmp_path / "valid_rollback.json"
    valid_snapshot.write_text(json.dumps(_valid_rollback_snapshot()), encoding="utf-8")

    valid_report = build_safety_gate_report({}, {}, rollback_snapshot_path=valid_snapshot)
    assert valid_report["rollback_snapshot_exists"] is True
    assert valid_report["gate_results"]["rollback_snapshot_exists"]["passed"] is True


def test_h3_refresh_safety_gate_report_logs_warning_instead_of_silent_pass() -> None:
    src = _source("desktop_app.py")
    function = _function_node(ast.parse(src), "_refresh_safety_gate_report")
    segment = ast.get_source_segment(src, function) or ""

    assert "Safety gate report refresh could not update hybrid direct state" in segment
    assert "_LOGGER.warning" in segment
    assert "exc_info=True" in segment
    assert "except Exception:" in segment
    assert "except Exception:\n            pass" not in segment


def test_h3_developer_direct_settings_persist_across_restart_simulation(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    model_dir = tmp_path / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    with monkeypatch.context() as scoped:
        scoped.setattr(secret_backend, "keyring", None)
        scoped.setattr(security, "MODELS_DIR", str(model_dir))
        scoped.setattr(security, "KEY_FILE", str(model_dir / "secret.key"))
        scoped.setattr(security, "KEY_FILE_DPAPI", str(model_dir / "secret.key.dpapi"))
        security.reset_security_caches()
        scoped.setattr(paths, "data_dir", lambda: str(tmp_path))
        scoped.setattr(paths, "settings_file", lambda: str(settings_path))

        module = importlib.reload(app_settings)
        saved_default = module.save_settings_async({"theme": "light"})
        assert saved_default["developer_direct_test_enabled"] is False
        assert saved_default["developer_direct_consent_enabled"] is False

        saved_explicit = module.save_settings_async(
            {
                "developer_direct_test_enabled": True,
                "developer_direct_consent_enabled": True,
            }
        )
        assert saved_explicit["developer_direct_test_enabled"] is True
        assert saved_explicit["developer_direct_consent_enabled"] is True

        module = importlib.reload(app_settings)
        loaded = module.load_settings()
        assert loaded["developer_direct_test_enabled"] is True
        assert loaded["developer_direct_consent_enabled"] is True

    importlib.reload(app_settings)


def test_h3_refresh_runtime_helpers_logs_deep_runtime_exception_without_secret_message(caplog) -> None:
    class DummyBridge:
        _current_user = {"user_id": "user-1"}
        _runtime_state = {}

        def _active_state_for_current_user(self):
            return {"active": True}

        def _build_runtime_state_view(self, state):
            return {"runtime_metadata": {"available": True}}

        def _refresh_deep_runtime_state(self):
            raise RuntimeError("raw-token-value-should-not-be-in-message")

    caplog.set_level(logging.WARNING, logger="bridge.refresh_runtime_helpers")

    refresh_runtime_helpers.update_runtime_background_state(DummyBridge())

    messages = [record.getMessage() for record in caplog.records]
    assert any("Deep runtime state refresh failed during background runtime update" in message for message in messages)
    assert all("raw-token-value" not in message for message in messages)
    assert any(record.exc_info for record in caplog.records)


def test_qml_safety_gate_state_remains_backend_owned_and_display_only() -> None:
    suspicious_patterns = (
        "rollback_snapshot_exists =",
        "build_safety_gate_report(",
        "developer_direct_enabled =",
        "hybrid_can_influence_device =",
        "rollback_target =",
        "schema_version =",
        "safetyGatePassed =",
    )
    offenders: list[str] = []
    for qml_file in sorted((ROOT / "qml").rglob("*.qml")):
        text = qml_file.read_text(encoding="utf-8")
        for pattern in suspicious_patterns:
            if pattern in text:
                offenders.append(f"{qml_file.relative_to(ROOT)} contains {pattern!r}")

    assert offenders == []
