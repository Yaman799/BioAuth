"""Backward-compatible wrapper around the platform startup abstraction."""

from __future__ import annotations

from bio_platform.startup import is_startup_enabled, set_startup_enabled

__all__ = ["is_startup_enabled", "set_startup_enabled"]
