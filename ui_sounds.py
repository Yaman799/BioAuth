from __future__ import annotations

import os
from typing import Literal

SoundRole = Literal["neutral", "success", "warning", "error", "toggle", "start", "stop"]

# Startup-safe compatibility module for bridge.shared.
# Button sounds are optional UI feedback. Playback failure must never prevent
# BioAuth from opening, especially in source-tree or packaged Windows startup.
_WIN_SOUND_ALIAS = {
    "neutral": "SystemAsterisk",
    "toggle": "SystemAsterisk",
    "start": "SystemAsterisk",
    "success": "SystemExclamation",
    "warning": "SystemExclamation",
    "stop": "SystemExclamation",
    "error": "SystemHand",
}


def _normalize_role(role: str | None) -> SoundRole:
    value = str(role or "neutral").strip().lower().replace("-", "_")
    if value in _WIN_SOUND_ALIAS:
        return value  # type: ignore[return-value]
    return "neutral"


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _sound_enabled_by_env() -> bool:
    return _env_flag_enabled("BIOAUTH_ENABLE_UI_SOUNDS")


def play_button_sound(role: str | None = "neutral") -> bool:
    """Play optional UI feedback only when explicitly enabled for development.

    ``bridge.shared`` imports this root-level module during desktop startup.
    Sound feedback is opt-in and non-blocking: normal product runs stay silent
    by default and never request Windows alias sounds such as SystemAsterisk,
    SystemExclamation, or SystemHand unless ``BIOAUTH_ENABLE_UI_SOUNDS`` is set.
    """
    if not _sound_enabled_by_env():
        return False
    if _env_flag_enabled("BIOAUTH_DISABLE_UI_SOUNDS"):
        return False
    if os.name != "nt":
        return False
    try:
        import winsound  # type: ignore[import-not-found]

        alias = _WIN_SOUND_ALIAS.get(_normalize_role(role), _WIN_SOUND_ALIAS["neutral"])
        winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
        return True
    except (ImportError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False


__all__ = ["SoundRole", "play_button_sound"]
