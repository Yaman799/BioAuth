"""CLI and environment config for the logger worker."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from utils.identity import slugify_username

SHADOW_EVIDENCE_SESSION_KIND = "shadow_evidence"


@dataclass(frozen=True)
class LoggerWorkerConfig:
    legacy: bool
    user_id: str | None
    safe_user: str | None
    session_label: str
    session_kind: str
    control_name: str
    session_id: str
    run_id: str
    live_session_dir: str

    def to_legacy_args(self) -> dict[str, object]:
        return {
            "legacy": self.legacy,
            "user_id": self.user_id,
            "safe_user": self.safe_user,
            "session_label": self.session_label,
            "session_kind": self.session_kind,
            "control_name": self.control_name,
        }


def parse_logger_config(argv: Sequence[str] | None = None) -> LoggerWorkerConfig:
    args = list(argv or [])
    arg1 = args[0].strip() if len(args) > 0 else "legit"
    arg2 = args[1].strip().lower() if len(args) > 1 else None
    session_id = _env_or_uuid("BIOAUTH_SESSION_ID")
    run_id = _env_or_uuid("BIOAUTH_RUN_ID")
    live_dir = _live_session_dir_from_env()

    if arg1.lower() in {"legit", "intruder"} and arg2 is None:
        return LoggerWorkerConfig(
            legacy=True,
            user_id=None,
            safe_user=None,
            session_label=arg1.lower(),
            session_kind="legacy",
            control_name=f"logger_{arg1.lower()}",
            session_id=session_id,
            run_id=run_id,
            live_session_dir=live_dir,
        )

    user_id = arg1
    safe_user = slugify_username(user_id) or "user"
    session_kind = arg2 or "active"
    if session_kind == SHADOW_EVIDENCE_SESSION_KIND:
        control_name = f"shadow_logger_user_{safe_user}"
    else:
        control_name = f"logger_user_{safe_user}"
    return LoggerWorkerConfig(
        legacy=False,
        user_id=user_id,
        safe_user=safe_user,
        session_label=safe_user,
        session_kind=session_kind,
        control_name=control_name,
        session_id=session_id,
        run_id=run_id,
        live_session_dir=live_dir,
    )


def _env_or_uuid(name: str) -> str:
    return str(os.environ.get(name) or "").strip() or uuid.uuid4().hex


def _live_session_dir_from_env() -> str:
    value = str(os.environ.get("BIOAUTH_LIVE_SESSION_DIR") or "").strip()
    return str(Path(value)) if value else ""
