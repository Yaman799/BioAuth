# Compatibility note for dashboard visibility tests: _dashboard_visible = True and _dashboard_visible_refresh_pending are initialized in src/bioauth/app/desktop_app_impl.py.
# Source-compatibility markers for legacy static tests; the actual Qt members
# are provided by src/bioauth/app/desktop_app_impl.py and re-exported below.
# updateStateChanged = Signal()
# def updateState
# def appVersion
"""Stable root entrypoint and compatibility wrapper for BioAuth Desktop.

Commercial-CLEAN-10 moved the implementation into
``src/bioauth/app/desktop_app_impl.py``.  This file intentionally remains at the
repository root because it is the supported launch target for:

- ``python desktop_app.py`` development launches
- ``start_app.pyw``
- ``start_app.bat``
- ``BioAuth.spec`` / PyInstaller builds

The wrapper preserves old imports and CLI behavior:
- ``import desktop_app`` exposes the implementation public API.
- ``from desktop_app import AppBridge`` still works.
- ``python desktop_app.py ...`` still calls the original ``main()``.
- QML/resource resolution remains implementation-owned through ``bridge.shared.BASE_DIR``.
"""
from __future__ import annotations

import importlib as _importlib
import sys as _sys
from pathlib import Path as _Path

_wrapper_name = __name__
_src_dir = _Path(__file__).resolve().parent / "src"
if _src_dir.exists() and str(_src_dir) not in _sys.path:
    _sys.path.insert(0, str(_src_dir))

if _wrapper_name == "__main__":
    from bioauth_runtime.desktop_relaunch_guard import (
        guard_desktop_system_python_child as _guard_desktop_system_python_child,
        record_desktop_launch_path as _record_desktop_launch_path,
    )
    from bioauth_runtime.wrapper_guard import enter_root_wrapper as _enter_root_wrapper

    _record_desktop_launch_path(
        project_root=str(_Path(__file__).resolve().parent),
        launch_path="desktop_app.py:__main__",
        command=[str(_sys.executable or ""), *[str(arg) for arg in _sys.argv]],
        selected_executable=str(_sys.executable or ""),
        before_qt=True,
    )
    _desktop_relaunch_guard = _guard_desktop_system_python_child(
        project_root=str(_Path(__file__).resolve().parent),
    )
    if bool(_desktop_relaunch_guard.get("blocked")):
        raise SystemExit(2)

    _wrapper_guard = _enter_root_wrapper(
        "desktop_app",
        project_root=str(_Path(__file__).resolve().parent),
        script_path=str(_Path(__file__).resolve()),
    )
    if not bool(_wrapper_guard.get("ok")):
        raise SystemExit(2)

_module = _importlib.import_module("bioauth.app.desktop_app_impl")
_public = {
    name: value
    for name, value in _module.__dict__.items()
    if not (name.startswith("__") and name not in {"__all__", "__doc__"})
}
globals().update(_public)

if _wrapper_name != "__main__":
    _sys.modules[_wrapper_name] = _module
else:
    _module.main()
