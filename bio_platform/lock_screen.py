from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes


def _base_lock_result() -> dict:
    return {
        "lockRequested": True,
        "lockAttempted": False,
        "lockSucceeded": False,
        "lockErrorKind": "",
        "lockUnavailableReason": "",
        "windowsLockRequested": True,
        "windowsLockAttempted": False,
        "windowsLockSucceeded": False,
        "windowsLockErrorKind": "",
        "windowsLockUnavailableReason": "",
    }


def lock_current_session_result() -> dict:
    """Attempt a workstation lock and return safe diagnostic fields.

    Windows is the supported production path. Development platforms keep the
    historical best-effort local lock behavior while clearly marking Windows lock
    fields as unavailable so the UI never claims a Windows lock succeeded there.
    """
    result = _base_lock_result()
    try:
        if os.name == "nt":
            result["lockAttempted"] = True
            result["windowsLockAttempted"] = True
            try:
                succeeded = bool(ctypes.windll.user32.LockWorkStation())
            except Exception as exc:
                result["lockErrorKind"] = type(exc).__name__
                result["windowsLockErrorKind"] = type(exc).__name__
                return result
            result["lockSucceeded"] = succeeded
            result["windowsLockSucceeded"] = succeeded
            if not succeeded:
                result["lockErrorKind"] = "lock_workstation_returned_false"
                result["windowsLockErrorKind"] = "lock_workstation_returned_false"
            return result

        result["windowsLockUnavailableReason"] = "unsupported_platform"
        if sys.platform == "darwin":
            commands = [
                ["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession", "-suspend"],
                ["pmset", "displaysleepnow"],
            ]
        else:
            commands = [
                ["loginctl", "lock-session"],
                ["gnome-screensaver-command", "-l"],
                ["xdg-screensaver", "lock"],
                ["dm-tool", "lock"],
            ]
        attempted_any = False
        last_error = ""
        for cmd in commands:
            try:
                attempted_any = True
                completed = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if completed.returncode == 0:
                    result["lockAttempted"] = True
                    result["lockSucceeded"] = True
                    return result
                last_error = f"command_returned_{completed.returncode}"
            except Exception as exc:
                last_error = type(exc).__name__
                continue
        result["lockAttempted"] = attempted_any
        result["lockErrorKind"] = last_error or "no_supported_lock_command"
        result["lockUnavailableReason"] = "desktop_lock_command_failed" if attempted_any else "no_supported_lock_command"
        return result
    except Exception as exc:
        result["lockErrorKind"] = type(exc).__name__
        if os.name == "nt":
            result["windowsLockErrorKind"] = type(exc).__name__
        return result


def lock_current_session() -> bool:
    """Lock the current workstation if supported by the host OS."""
    return bool(lock_current_session_result().get("lockSucceeded"))


def is_current_session_locked() -> bool:
    """Best-effort workstation lock detection.

    Windows is the supported production path. Other platforms return False so the
    caller can continue with normal app behavior instead of getting stuck in a
    permanent locked state.
    """
    try:
        if os.name != "nt":
            return False

        user32 = ctypes.windll.user32
        DESKTOP_SWITCHDESKTOP = 0x0100
        UOI_NAME = 2

        hdesk = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if not hdesk:
            return False
        try:
            needed = wintypes.DWORD(0)
            user32.GetUserObjectInformationW(hdesk, UOI_NAME, None, 0, ctypes.byref(needed))
            if not needed.value:
                return False
            wchar_count = max(2, int(needed.value // ctypes.sizeof(ctypes.c_wchar)) + 1)
            buffer = (ctypes.c_wchar * wchar_count)()
            if not user32.GetUserObjectInformationW(hdesk, UOI_NAME, buffer, needed.value, ctypes.byref(needed)):
                return False
            desktop_name = str(buffer.value or "").strip().lower()
            return bool(desktop_name and desktop_name != "default")
        finally:
            try:
                user32.CloseDesktop(hdesk)
            except Exception:
                pass
    except Exception:
        return False
