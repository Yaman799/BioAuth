from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

from .pyside_bootstrap import bootstrap_pyside6_windows

bootstrap_pyside6_windows()

try:  # pragma: no cover - real desktop runtime path
    from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
    from PySide6.QtGui import QDesktopServices, QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
except ModuleNotFoundError as _pyside_exc:  # pragma: no cover - validation/import-only environments
    _PYSIDE6_IMPORT_ERROR = _pyside_exc

    class _MissingQtRuntime:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError(
                "PySide6 is required to launch the BioAuth desktop UI. "
                "Install runtime dependencies with `python -m pip install -r requirements.txt`."
            ) from _PYSIDE6_IMPORT_ERROR

    class _ImportOnlyQObject:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__()

    class _ImportOnlySignal:
        def connect(self, *args: Any, **kwargs: Any) -> None:
            return None

        def emit(self, *args: Any, **kwargs: Any) -> None:
            return None

    def Signal(*args: Any, **kwargs: Any) -> _ImportOnlySignal:  # type: ignore[override]
        return _ImportOnlySignal()

    def Slot(*args: Any, **kwargs: Any):  # type: ignore[override]
        def _decorator(func: Any) -> Any:
            return func

        return _decorator

    def Property(*args: Any, **kwargs: Any):  # type: ignore[override]
        def _decorator(func: Any) -> property:
            return property(func)

        return _decorator

    class QUrl:  # type: ignore[override]
        def __init__(self, value: str = "") -> None:
            self.value = str(value or "")

        @staticmethod
        def fromLocalFile(path: str) -> "QUrl":
            return QUrl(str(path or ""))

    class QDesktopServices:  # type: ignore[override]
        @staticmethod
        def openUrl(url: Any) -> bool:
            return False

    QObject = _ImportOnlyQObject  # type: ignore[assignment]
    QApplication = _MissingQtRuntime  # type: ignore[assignment]
    QIcon = _MissingQtRuntime  # type: ignore[assignment]
    QMenu = _MissingQtRuntime  # type: ignore[assignment]
    QQmlApplicationEngine = _MissingQtRuntime  # type: ignore[assignment]
    QSystemTrayIcon = _MissingQtRuntime  # type: ignore[assignment]
    QTimer = _MissingQtRuntime  # type: ignore[assignment]

from app_settings import load_settings, save_settings, save_settings_async
from auth import (
    build_local_session_state,
    change_password,
    complete_user_onboarding,
    create_user,
    delete_user_account,
    generate_password_recovery_code,
    lookup_username_hint_by_email,
    reset_password_with_recovery,
    reveal_username_by_email,
    restore_local_session,
    verify_password_reset_recovery,
    slugify_username,
    user_requires_onboarding,
    verify_user,
)
from bio_platform.lock_screen import is_current_session_locked
from bioauth_model.scoring import RISK_SENSITIVITY_PRESETS, normalize_sensitivity_preset
from control import (
    clear_session_state,
    clear_stop,
    clear_worker_heartbeat,
    prepare_session_state_for_new_runtime,
    current_boot_marker,
    current_boot_time_epoch,
    read_session_state,
    read_worker_heartbeat,
    quarantine_session_state,
    request_stop,
    write_session_state,
    write_worker_heartbeat,
)
from model_metadata import (
    build_fast_user_dashboard_snapshot,
    build_user_dashboard_snapshot,
    delete_user_data,
    invalidate_session_discovery_cache,
    read_session_metadata,
    remove_session_from_index,
    update_session_index_for_path,
    reset_user_profile,
    summarize_user_sessions,
    user_profile_status,
)
from paths import sessions_dir
from persistent_login import clear_persistent_login, remember_user, restore_remembered_user
from startup_manager import is_startup_enabled, set_startup_enabled
from ui_notifications import show_taskbar_notification
from ui_sounds import play_button_sound

from .i18n import (
    QLocale_name,
    STRINGS,
    THEMES,
    WELCOME_POLICY_VERSION,
    translate_backend_result,
    translate_string,
)
from .runtime_labels import (
    runtime_decision_key,
    runtime_policy_display_fields,
    runtime_status_awaits_evidence,
    runtime_status_detail_key,
    runtime_status_is_technical_failure,
    runtime_status_key,
)
from .worker_helpers import BASE_DIR, LOGGER_SCRIPT, MONITOR_SCRIPT, _run_worker_if_requested, _spawn_command


def train_user_model(*args, **kwargs):
    """Lazy-load training stack only when model training is requested."""
    from model_training import train_user_model as _train_user_model

    return _train_user_model(*args, **kwargs)


def _shadow_model_callable(name: str):
    from shadow_model import __dict__ as _shadow_exports

    return _shadow_exports[name]


def cleanup_old_backups(*args, **kwargs):
    return _shadow_model_callable("cleanup_old_backups")(*args, **kwargs)


def dismiss_shadow_suggestion(*args, **kwargs):
    return _shadow_model_callable("dismiss_shadow_suggestion")(*args, **kwargs)


def evaluate_shadow_vs_main(*args, **kwargs):
    return _shadow_model_callable("evaluate_shadow_vs_main")(*args, **kwargs)


def get_shadow_status(*args, **kwargs):
    return _shadow_model_callable("get_shadow_status")(*args, **kwargs)


def list_shadow_backlog_sessions(*args, **kwargs):
    return _shadow_model_callable("list_shadow_backlog_sessions")(*args, **kwargs)


def log_shadow_event(*args, **kwargs):
    return _shadow_model_callable("log_shadow_event")(*args, **kwargs)


def promote_shadow_model(*args, **kwargs):
    return _shadow_model_callable("promote_shadow_model")(*args, **kwargs)


def register_legit_session_for_shadow(*args, **kwargs):
    return _shadow_model_callable("register_legit_session_for_shadow")(*args, **kwargs)


def train_shadow_model(*args, **kwargs):
    return _shadow_model_callable("train_shadow_model")(*args, **kwargs)


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.5, float(os.environ.get(name, default)))
    except (TypeError, ValueError, OverflowError):
        return float(default)


PRIVACY_POLICY_PATH = os.path.join(BASE_DIR, "PRIVACY_POLICY.md")
ABOUT_US_PATH = os.path.join(BASE_DIR, "docs", "ABOUT_US.md")
REFRESH_ACTIVE_MS = 1000
REFRESH_IDLE_SIGNED_MS = 10000
REFRESH_IDLE_AUTH_MS = 30000
REFRESH_BACKGROUND_MS = 60000
REFRESH_MS = REFRESH_ACTIVE_MS
LOGGER_START_GRACE_SEC = max(12.0, _env_float("BIOAUTH_LOGGER_START_GRACE_SEC", 12.0))
MONITOR_START_GRACE_SEC = max(6.0, _env_float("BIOAUTH_MONITOR_START_GRACE_SEC", 6.0))
MIN_ENROLLMENT_SESSIONS = 8
MAX_ENROLLMENT_SESSIONS = 15


__all__ = [
    "ABOUT_US_PATH",
    "BASE_DIR",
    "LOGGER_SCRIPT",
    "MAX_ENROLLMENT_SESSIONS",
    "MIN_ENROLLMENT_SESSIONS",
    "MONITOR_SCRIPT",
    "LOGGER_START_GRACE_SEC",
    "MONITOR_START_GRACE_SEC",
    "PRIVACY_POLICY_PATH",
    "Property",
    "QApplication",
    "QDesktopServices",
    "QIcon",
    "QLocale_name",
    "QMenu",
    "QObject",
    "QQmlApplicationEngine",
    "QSystemTrayIcon",
    "QTimer",
    "QUrl",
    "quarantine_session_state",
    "REFRESH_ACTIVE_MS",
    "REFRESH_BACKGROUND_MS",
    "REFRESH_IDLE_AUTH_MS",
    "REFRESH_IDLE_SIGNED_MS",
    "REFRESH_MS",
    "STRINGS",
    "Signal",
    "Slot",
    "THEMES",
    "WELCOME_POLICY_VERSION",
    "_run_worker_if_requested",
    "_spawn_command",
    "build_local_session_state",
    "change_password",
    "complete_user_onboarding",
    "build_fast_user_dashboard_snapshot",
    "build_user_dashboard_snapshot",
    "cleanup_old_backups",
    "clear_persistent_login",
    "clear_session_state",
    "clear_stop",
    "prepare_session_state_for_new_runtime",
    "create_user",
    "current_boot_marker",
    "current_boot_time_epoch",
    "delete_user_account",
    "delete_user_data",
    "generate_password_recovery_code",
    "dismiss_shadow_suggestion",
    "evaluate_shadow_vs_main",
    "get_shadow_status",
    "invalidate_session_discovery_cache",
    "remove_session_from_index",
    "update_session_index_for_path",
    "is_current_session_locked",
    "is_startup_enabled",
    "list_shadow_backlog_sessions",
    "load_settings",
    "log_shadow_event",
    "lookup_username_hint_by_email",
    "reset_password_with_recovery",
    "reveal_username_by_email",
    "normalize_sensitivity_preset",
    "play_button_sound",
    "promote_shadow_model",
    "read_session_metadata",
    "read_session_state",
    "register_legit_session_for_shadow",
    "remember_user",
    "request_stop",
    "restore_local_session",
    "restore_remembered_user",
    "verify_password_reset_recovery",
    "runtime_decision_key",
    "runtime_policy_display_fields",
    "runtime_status_awaits_evidence",
    "runtime_status_detail_key",
    "runtime_status_is_technical_failure",
    "runtime_status_key",
    "RISK_SENSITIVITY_PRESETS",
    "save_settings",
    "save_settings_async",
    "sessions_dir",
    "set_startup_enabled",
    "show_taskbar_notification",
    "slugify_username",
    "summarize_user_sessions",
    "train_shadow_model",
    "train_user_model",
    "user_requires_onboarding",
    "translate_backend_result",
    "translate_string",
    "user_profile_status",
    "verify_user",
    "clear_worker_heartbeat",
    "read_worker_heartbeat",
    "write_worker_heartbeat",
    "write_session_state",
]
