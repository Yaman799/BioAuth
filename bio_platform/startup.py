from __future__ import annotations

import os
from pathlib import Path
from typing import Final

try:
    import winreg
except Exception:  # pragma: no cover - exercised indirectly on non-Windows
    winreg = None  # type: ignore[assignment]

RUN_KEY: Final[str] = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME: Final[str] = "BioAuthDesktop"
LEGACY_RUN_VALUE_NAMES: Final[tuple[str, ...]] = ("BioAuth",)


def _windows_gui_executable() -> Path:
    import sys

    executable = Path(sys.executable).resolve()
    if executable.name.lower() == "python.exe":
        candidate = executable.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return executable


def _startup_command() -> str:
    import sys

    executable = _windows_gui_executable()
    script = Path(__file__).resolve().parent.parent / "desktop_app.py"
    if getattr(sys, "frozen", False):
        command = f'"{executable}" --background'
    else:
        command = f'"{executable}" "{script}" --background'
    try:
        from bioauth_runtime.desktop_relaunch_guard import record_desktop_launch_path

        record_desktop_launch_path(
            project_root=str(Path(__file__).resolve().parent.parent),
            launch_path="bio_platform.startup:_startup_command",
            command=command,
            selected_executable=str(executable),
            before_qt=False,
        )
    except Exception:
        pass
    return command


def _delete_run_value_if_exists(key, name: str) -> None:
    try:
        winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def _read_run_value(key, name: str) -> str:
    try:
        value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value or "").strip()


def _windows_set_startup_enabled(enabled: bool) -> bool:
    if winreg is None:
        return False
    desired = _startup_command()
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, desired)
                for legacy_name in LEGACY_RUN_VALUE_NAMES:
                    if legacy_name != RUN_VALUE_NAME:
                        _delete_run_value_if_exists(key, legacy_name)
            else:
                _delete_run_value_if_exists(key, RUN_VALUE_NAME)
                for legacy_name in LEGACY_RUN_VALUE_NAMES:
                    _delete_run_value_if_exists(key, legacy_name)
        return _windows_is_startup_enabled() == bool(enabled)
    except OSError:
        return False


def _windows_is_startup_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            for name in (RUN_VALUE_NAME, *LEGACY_RUN_VALUE_NAMES):
                if _read_run_value(key, name):
                    return True
            return False
    except OSError:
        return False


def set_startup_enabled(enabled: bool) -> bool:
    """Toggle run-on-startup for the current platform.

    The production implementation is Windows-only for now. Other platforms safely
    return ``False`` so callers can preserve UI state without pretending support.
    """
    if os.name != "nt":
        return False
    return _windows_set_startup_enabled(bool(enabled))


def is_startup_enabled() -> bool:
    if os.name != "nt":
        return False
    return _windows_is_startup_enabled()
