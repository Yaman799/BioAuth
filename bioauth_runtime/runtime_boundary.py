"""Commercial runtime boundary checks.

This module is intentionally narrow: it answers whether protected-runtime
side effects are allowed. It does not start/stop workers, touch UI state, or
run model/face/lock logic.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

_PROTECTED_FLOWS = {
    "protected_starting",
    "protected_active",
    "protected_resume_pending",
    "protected_forced_stop",
    "verifying_return",
    "resume_pending",
}

_PROTECTED_STATUSES = {
    "starting",
    "protected_starting",
    "protected_active",
    "verifying_return",
    "resume_pending",
    "protected_forced_stop",
    "forced_stop",
}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def is_commercial_protected_runtime(state: Mapping[str, Any] | None = None, *, flow: str = "") -> bool:
    """Return true while UserShell commercial protection owns the runtime."""
    data = state if isinstance(state, Mapping) else {}
    flow_text = _text(flow) or _text(data.get("flow") or data.get("session_flow"))
    status = _text(data.get("status") or data.get("runtime_status"))
    kind = _text(data.get("session_kind"))
    source = _text(data.get("source"))
    mode = _text(data.get("mode") or data.get("runtime_mode"))
    if flow_text in _PROTECTED_FLOWS or flow_text.startswith("protected"):
        return True
    if kind == "protected" and (bool(data.get("active")) or status in _PROTECTED_STATUSES):
        return True
    if kind == "protected" and source in {"supervisor", "monitor", "bridge"}:
        return True
    return mode == "protected" and status in _PROTECTED_STATUSES


def side_effects_allowed_for_refresh(state: Mapping[str, Any] | None = None, *, flow: str = "") -> bool:
    """Refresh may run non-commercial jobs only outside protected runtime."""
    return not is_commercial_protected_runtime(state, flow=flow)


def dev_features_enabled() -> bool:
    """Explicit opt-in gate for dev-only runtime behavior."""
    profile = _text(os.environ.get("BIOAUTH_BUILD_PROFILE"))
    return _truthy(os.environ.get("BIOAUTH_BUILD_PROFILE_DEV")) or profile in {"dev", "debug"}


def demo_features_enabled() -> bool:
    """Explicit opt-in gate for demo-only runtime behavior."""
    return _truthy(os.environ.get("BIOAUTH_DEMO_CLASSIC_PROTECTED")) or _truthy(
        os.environ.get("BIOAUTH_ENABLE_DEMO_FEATURES")
    )


def runtime_shadow_tap_enabled() -> bool:
    """Runtime-fed shadow tap is dev-only and disabled by default."""
    return dev_features_enabled() and _truthy(os.environ.get("BIOAUTH_DEV_ENABLE_RUNTIME_SHADOW_TAP"))
