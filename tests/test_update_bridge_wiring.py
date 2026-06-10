from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_update_bridge_methods_and_qml_wiring_exist() -> None:
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    mixin = (ROOT / "bridge" / "update_mixin.py").read_text(encoding="utf-8")
    qml = (ROOT / "qml" / "pages" / "settings" / "SettingsGeneralTab.qml").read_text(encoding="utf-8")

    assert "updateStateChanged = Signal()" in desktop
    assert "def updateState" in desktop
    assert "def appVersion" in desktop
    assert "def checkForUpdates" in mixin
    assert "def downloadAvailableUpdate" in mixin
    assert "def openDownloadedUpdateInstaller" in mixin
    assert "backend.checkForUpdates()" in qml
    assert "backend.downloadAvailableUpdate()" in qml
    assert "backend.openDownloadedUpdateInstaller()" in qml
    assert "Current version" in qml
