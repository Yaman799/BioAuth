"""CLI and environment config for the monitor worker."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from utils.identity import slugify_username


@dataclass(frozen=True)
class MonitorWorkerConfig:
    user_id: str | None
    safe_user: str | None
    live_session_dir: str
    session_id: str
    runtime_mode: str
    control_name: str


def parse_monitor_config(argv: Sequence[str] | None = None) -> MonitorWorkerConfig:
    args = list(argv or [])
    user_id = args[0].strip() if args else None
    safe_user = slugify_username(user_id or "") or None
    runtime_mode = str(os.environ.get("BIOAUTH_RUNTIME_MODE") or "").strip().lower()
    session_id = str(os.environ.get("BIOAUTH_SESSION_ID") or "").strip()
    live_dir = _live_session_dir_from_env()
    control_name = _control_name(runtime_mode=runtime_mode, safe_user=safe_user, user_id=user_id)
    return MonitorWorkerConfig(
        user_id=user_id,
        safe_user=safe_user,
        live_session_dir=live_dir,
        session_id=session_id,
        runtime_mode=runtime_mode,
        control_name=control_name,
    )


def _live_session_dir_from_env() -> str:
    value = str(os.environ.get("BIOAUTH_LIVE_SESSION_DIR") or "").strip()
    return str(Path(value)) if value else ""


def _control_name(*, runtime_mode: str, safe_user: str | None, user_id: str | None) -> str:
    if runtime_mode == "shadow_evidence" or os.environ.get("BIOAUTH_SHADOW_EVIDENCE_ONLY", "").strip() == "1":
        return f"shadow_monitor_user_{safe_user or 'user'}"
    if runtime_mode == "hybrid_direct_test" or os.environ.get("BIOAUTH_HYBRID_TEST_ONLY", "").strip() == "1":
        return f"hybrid_direct_test_monitor_user_{safe_user or 'user'}"
    return "monitor"
