from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def bootstrap_pyside6_windows() -> None:
    if os.name != "nt":
        return
    try:
        spec = importlib.util.find_spec("PySide6")
        if not spec or not spec.submodule_search_locations:
            return
        pyside_dir = Path(list(spec.submodule_search_locations)[0]).resolve()
        qml_dir = pyside_dir / "qml"
        plugins_dir = pyside_dir / "plugins"

        os.environ.setdefault("QML2_IMPORT_PATH", str(qml_dir))
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugins_dir))
        os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

        path_parts = [str(pyside_dir), str(plugins_dir), str(qml_dir), os.environ.get("PATH", "")]
        os.environ["PATH"] = os.pathsep.join([p for p in path_parts if p])

        if hasattr(os, "add_dll_directory"):
            for candidate in (pyside_dir, plugins_dir, qml_dir):
                if candidate.exists():
                    try:
                        os.add_dll_directory(str(candidate))
                    except OSError:
                        pass
    except Exception:
        pass


__all__ = ["bootstrap_pyside6_windows"]
