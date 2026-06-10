from __future__ import annotations

import base64
import os
import shutil
import subprocess
from typing import Literal

NotificationLevel = Literal["info", "warning", "error"]

_ICON_NAME = {
    "info": "Information",
    "warning": "Warning",
    "error": "Error",
}

_TOOLTIP_ICON = {
    "info": "Info",
    "warning": "Warning",
    "error": "Error",
}


def _ps_quote(value: str) -> str:
    text = str(value or "")
    return "'" + text.replace("'", "''") + "'"


def _powershell_executable() -> str | None:
    for candidate in ("powershell", "pwsh"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _build_balloon_script(title: str, message: str, *, timeout_ms: int, level: NotificationLevel) -> str:
    icon_name = _ICON_NAME.get(level, "Information")
    tooltip_icon = _TOOLTIP_ICON.get(level, "Info")
    title = str(title or "").strip()[:80] or "BioAuth"
    message = str(message or "").strip()[:240] or "BioAuth notification"
    hold_ms = max(2200, int(timeout_ms) + 1600)
    return f"""
Add-Type -AssemblyName System.Windows.Forms | Out-Null
Add-Type -AssemblyName System.Drawing | Out-Null
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::{icon_name}
$notify.Visible = $true
$notify.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::{tooltip_icon}
$notify.BalloonTipTitle = {_ps_quote(title)}
$notify.BalloonTipText = {_ps_quote(message)}
$notify.ShowBalloonTip({int(timeout_ms)})
Start-Sleep -Milliseconds {hold_ms}
$notify.Dispose()
""".strip()


def show_notification(title: str, message: str, *, timeout_ms: int = 5000, level: NotificationLevel = "info") -> bool:
    """Show a non-intrusive taskbar balloon on Windows.

    Other platforms currently return ``False`` rather than pretending delivery.
    """
    if os.name != "nt":
        return False
    ps = _powershell_executable()
    if not ps:
        return False
    try:
        script = _build_balloon_script(title, message, timeout_ms=timeout_ms, level=level)
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = None
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
            startupinfo.wShowWindow = 0
        subprocess.Popen(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        return True
    except Exception:
        return False
