from __future__ import annotations

import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_worker_bootstrap_module_exports_startup_contract() -> None:
    module = importlib.import_module("worker_bootstrap")
    assert hasattr(module, "worker_python_executable")
    assert hasattr(module, "spawn_command")
    assert hasattr(module, "run_worker_if_requested")


def test_worker_helpers_imports_without_missing_worker_bootstrap() -> None:
    module = importlib.import_module("bridge.worker_helpers")
    assert module.BASE_DIR
    assert module.LOGGER_SCRIPT.endswith("logger.py")
    assert module.MONITOR_SCRIPT.endswith("monitor.py")
    assert callable(module._spawn_command)
    assert callable(module._run_worker_if_requested)


def test_spawn_command_uses_source_worker_scripts_when_not_frozen() -> None:
    module = importlib.import_module("worker_bootstrap")
    command = module.spawn_command(
        "--worker-logger",
        "C:/BioAuth/logger.py",
        "C:/BioAuth/monitor.py",
        lambda path: False,
        "--user",
        "alice",
    )
    assert command[-3:] == ["C:/BioAuth/logger.py", "--user", "alice"]


def test_spawn_command_uses_worker_flag_for_frozen_runtime() -> None:
    module = importlib.import_module("worker_bootstrap")
    old_frozen = getattr(sys, "frozen", None)
    old_executable = sys.executable
    sys.frozen = True  # type: ignore[attr-defined]
    sys.executable = "C:/BioAuth/BioAuth.exe"
    try:
        command = module.spawn_command(
            "--worker-monitor",
            "C:/BioAuth/logger.py",
            "C:/BioAuth/monitor.py",
            lambda path: False,
            "--session",
            "s1",
        )
        assert command == ["C:/BioAuth/BioAuth.exe", "--worker-monitor", "--session", "s1"]
    finally:
        sys.executable = old_executable
        if old_frozen is None:
            try:
                delattr(sys, "frozen")
            except AttributeError:
                pass
        else:
            sys.frozen = old_frozen  # type: ignore[attr-defined]


def test_worker_bootstrap_does_not_reference_raw_behavioral_payload_fields() -> None:
    source = (ROOT / "worker_bootstrap.py").read_text(encoding="utf-8").lower()
    for forbidden in ["keystroke", "mouse_events", "keyboard_events", "raw_key", "raw_mouse"]:
        assert forbidden not in source


if __name__ == "__main__":
    test_worker_bootstrap_module_exports_startup_contract()
    test_worker_helpers_imports_without_missing_worker_bootstrap()
    test_spawn_command_uses_source_worker_scripts_when_not_frozen()
    test_spawn_command_uses_worker_flag_for_frozen_runtime()
    test_worker_bootstrap_does_not_reference_raw_behavioral_payload_fields()
    print("5 focused worker bootstrap import contract tests passed", flush=True)
