from __future__ import annotations

import ast
import importlib
import logging
from pathlib import Path

import app_settings
import bio_platform.secrets as secret_backend
import bridge.refresh_runtime_helpers as refresh_runtime_helpers
import paths
import security

ROOT = Path(__file__).resolve().parents[1]
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


def _dict_literal_keys_in_function(path: str, function_name: str) -> set[str]:
    tree = ast.parse(_source(path))
    function = _function_node(tree, function_name)
    keys: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
    return keys


def test_developer_direct_defaults_are_backfilled_fail_closed() -> None:
    migrated = app_settings._coerce_settings_payload({})

    for key in DEVELOPER_DIRECT_KEYS:
        assert app_settings.DEFAULT_SETTINGS[key] is False
        assert migrated[key] is False

    malformed = app_settings._coerce_settings_payload(
        {
            "developer_direct_test_enabled": "not-a-bool",
            "developer_direct_consent_enabled": {"enabled": True},
        }
    )
    assert malformed["developer_direct_test_enabled"] is False
    assert malformed["developer_direct_consent_enabled"] is False


def test_developer_direct_defaults_persist_across_restart_simulation(tmp_path, monkeypatch) -> None:
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
        saved = module.save_settings_async({"theme": "light"})
        assert saved["developer_direct_test_enabled"] is False
        assert saved["developer_direct_consent_enabled"] is False

        module = importlib.reload(app_settings)
        loaded = module.load_settings()
        assert loaded["theme"] == "light"
        assert loaded["developer_direct_test_enabled"] is False
        assert loaded["developer_direct_consent_enabled"] is False

    importlib.reload(app_settings)


def test_settings_payload_includes_developer_direct_instance_attributes() -> None:
    payload_keys = _dict_literal_keys_in_function("bridge/settings_mixin.py", "_settings_payload")
    assert set(DEVELOPER_DIRECT_KEYS).issubset(payload_keys)

    src = _source("bridge/settings_mixin.py")
    assert 'getattr(self, "_developer_direct_test_enabled", False)' in src
    assert 'getattr(self, "_developer_direct_consent_enabled", False)' in src


def test_desktop_initializes_developer_direct_attributes_from_settings_defaults() -> None:
    src = _source("desktop_app.py")
    assert 'self._developer_direct_test_enabled = bool(self._app_settings.get("developer_direct_test_enabled", False))' in src
    assert 'self._developer_direct_consent_enabled = bool(self._app_settings.get("developer_direct_consent_enabled", False))' in src


def test_emergency_disable_and_rollback_update_memory_and_persist_developer_direct_off() -> None:
    src = _source("desktop_app.py")
    for function_name in ("emergencyDisableHybrid", "rollbackToClassic"):
        tree = ast.parse(src)
        function = _function_node(tree, function_name)
        segment = ast.get_source_segment(src, function) or ""
        assert "self._developer_direct_test_enabled = False" in segment
        assert "self._developer_direct_consent_enabled = False" in segment
        assert "developer_direct_test_enabled=False" in segment
        assert "developer_direct_consent_enabled=False" in segment


def test_refresh_safety_gate_report_logs_unexpected_merge_failures_without_silent_pass() -> None:
    src = _source("desktop_app.py")
    tree = ast.parse(src)
    function = _function_node(tree, "_refresh_safety_gate_report")

    handlers = [node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler)]
    assert handlers, "_refresh_safety_gate_report should preserve exception handling"

    target_handler = None
    for handler in handlers:
        segment = ast.get_source_segment(src, handler) or ""
        if "Safety gate report refresh could not update hybrid direct state" in segment:
            target_handler = handler
            assert "exc_info=True" in segment
            assert "_LOGGER.warning" in segment
            assert "pass" not in segment
            break
    assert target_handler is not None, "targeted safety refresh exception handler must log safely"


def test_background_deep_runtime_refresh_exception_is_logged_without_secret_message(caplog) -> None:
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
