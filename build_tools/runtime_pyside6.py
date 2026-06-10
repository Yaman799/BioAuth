from __future__ import annotations

import os
import sys
from pathlib import Path


def _add_dir(path: Path) -> None:
    if not path.exists():
        return
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(path))
        except OSError:
            pass


if getattr(sys, "frozen", False):
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    base = Path(__file__).resolve().parent.parent

pyside_root = base / "PySide6"
plugins_dir = pyside_root / "plugins"
qml_dir = pyside_root / "qml"
translations_dir = pyside_root / "translations"

os.environ.setdefault("QT_PLUGIN_PATH", str(plugins_dir))
os.environ.setdefault("QML2_IMPORT_PATH", str(qml_dir))
os.environ.setdefault("QML_IMPORT_PATH", str(qml_dir))
os.environ.setdefault("QT_TRANSLATIONS_PATH", str(translations_dir))
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

path_parts = [str(base), str(pyside_root), str(plugins_dir), str(qml_dir), os.environ.get("PATH", "")]
os.environ["PATH"] = os.pathsep.join([p for p in path_parts if p])

for candidate in (base, pyside_root, plugins_dir, qml_dir):
    _add_dir(candidate)
