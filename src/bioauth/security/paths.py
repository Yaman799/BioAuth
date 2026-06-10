from __future__ import annotations

import os
import sys
from typing import Optional


APP_NAME = "BioAuth"


def _source_project_root() -> str:
    """Return the historical source-tree root used before the src/ split.

    The old root-level paths.py returned the repository directory for
    non-frozen runs because __file__ lived at the project root.  After moving
    the implementation under src/bioauth/security, scan upward for the stable
    desktop entrypoint and fall back to the implementation directory only if the
    source tree marker is unavailable.
    """
    current = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.exists(os.path.join(current, "desktop_app.py")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.dirname(os.path.abspath(__file__))
        current = parent


def runtime_base_dir() -> str:
    if getattr(sys, "frozen", False):
        bundle_dir = getattr(sys, "_MEIPASS", "")
        if bundle_dir:
            return bundle_dir
        return os.path.dirname(sys.executable)
    return _source_project_root()


def _windows_known_folder(env_key: str) -> Optional[str]:
    value = os.environ.get(env_key)
    if value and os.path.isdir(value):
        return value
    return None


def app_data_dir() -> str:
    """
    Per-user writable data directory.
    - Windows: %LOCALAPPDATA%\\BioAuth (preferred), else %APPDATA%\\BioAuth
    - Others: ~/.local/share/BioAuth
    """
    if os.name == "nt":
        base = _windows_known_folder("LOCALAPPDATA") or _windows_known_folder("APPDATA")
        if base:
            d = os.path.join(base, APP_NAME)
            os.makedirs(d, exist_ok=True)
            return d

    home = os.path.expanduser("~")
    d = os.path.join(home, ".local", "share", APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def data_dir() -> str:
    d = os.path.join(app_data_dir(), "data")
    os.makedirs(d, exist_ok=True)
    return d


def models_dir() -> str:
    d = os.path.join(app_data_dir(), "models")
    os.makedirs(d, exist_ok=True)
    return d


def sessions_dir() -> str:
    d = os.path.join(data_dir(), "sessions")
    os.makedirs(d, exist_ok=True)
    return d


def live_session_dir() -> str:
    override = os.environ.get("BIOAUTH_LIVE_SESSION_DIR", "").strip()
    if override:
        override_abs = os.path.abspath(override)
        allowed_base = os.path.abspath(app_data_dir())
        if not override_abs.startswith(allowed_base + os.sep) and override_abs != allowed_base:
            raise ValueError(
                f"BIOAUTH_LIVE_SESSION_DIR must be within {allowed_base}, got: {override_abs}"
            )
        os.makedirs(override_abs, exist_ok=True)
        return override_abs
    d = os.path.join(data_dir(), "live_session")
    os.makedirs(d, exist_ok=True)
    return d




def evidence_dir() -> str:
    d = os.path.join(data_dir(), "evidence")
    os.makedirs(d, exist_ok=True)
    return d

def control_dir() -> str:
    d = os.path.join(data_dir(), "control")
    os.makedirs(d, exist_ok=True)
    return d


def settings_file() -> str:
    return os.path.join(data_dir(), "settings.json")


def users_file() -> str:
    return os.path.join(data_dir(), "users.json")


def lockouts_file() -> str:
    return os.path.join(data_dir(), "lockouts.json")


def account_creation_limits_file() -> str:
    return os.path.join(data_dir(), "account_creation_limits.json")


def remembered_login_file() -> str:
    return os.path.join(data_dir(), "remembered_login.json")


def monitor_log_file() -> str:
    return os.path.join(data_dir(), "monitor_log.json.enc")


def metadata_db_file() -> str:
    """Local SQLite metadata/index database path.

    The database is for metadata-only dashboard/audit indexes. Sensitive raw
    logs, secrets, passwords, model payloads, and biometric templates remain in
    the existing encrypted file/model stores.
    """
    return os.path.join(data_dir(), "metadata_index.sqlite3")
