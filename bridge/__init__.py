"""Bridge package public mixin exports.

Keep package import lightweight: importing ``bridge.refresh_mixin`` or helper
modules should not eagerly import every desktop mixin. That eager import pattern
made focused pytest collection fragile because a test importing one bridge
submodule also loaded unrelated PySide/desktop surfaces.
"""
from __future__ import annotations

from typing import Any

__all__ = ["AuthMixin", "SessionMixin", "SettingsMixin", "RefreshMixin"]


def __getattr__(name: str) -> Any:
    if name == "AuthMixin":
        from .auth_mixin import AuthMixin
        return AuthMixin
    if name == "SessionMixin":
        from .session_mixin import SessionMixin
        return SessionMixin
    if name == "SettingsMixin":
        from .settings_mixin import SettingsMixin
        return SettingsMixin
    if name == "RefreshMixin":
        from .refresh_mixin import RefreshMixin
        return RefreshMixin
    raise AttributeError(f"module 'bridge' has no attribute {name!r}")
