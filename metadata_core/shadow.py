"""Shadow-model path and state helpers."""

from __future__ import annotations

import os
from typing import Any, Dict

from metadata_core.paths import _user_model_dir


def _shadow_model_dir(user_id: str) -> str:
    return os.path.join(_user_model_dir(user_id), "shadow")


def _shadow_model_paths(user_id: str) -> Dict[str, str]:
    base = _shadow_model_dir(user_id)
    return {
        "base": base,
        "model": os.path.join(base, "model.pkl"),
        "classifier": os.path.join(base, "classifier.pkl"),
        "metadata": os.path.join(base, "metadata.json"),
        "state": os.path.join(base, "shadow_state.json"),
        "eval_log": os.path.join(base, "eval_log.json"),
        "events_log": os.path.join(base, "shadow_events.jsonl"),
        "audit_log": os.path.join(base, "audit_log.jsonl"),
        "lock": os.path.join(base, ".shadow.lock"),
    }


def _backup_model_dir(user_id: str) -> str:
    return _user_model_dir(user_id)


def _shadow_state_defaults() -> Dict[str, Any]:
    return {
        "phase": "collecting",
        "candidate_sessions": [],
        "eval_deltas": [],
        "total_eval_count": 0,
        "shadow_trained_at": None,
        "last_eval_at": None,
        "promote_suggested": False,
        "avg_delta": 0.0,
        "suggestion_snoozed_until_total_eval_count": 0,
        "suggestion_last_dismissed_at": None,
        "last_processed_session_id": "",
        "last_processed_archive_path": "",
    }


def _shadow_state_path(user_id: str) -> str:
    return _shadow_model_paths(user_id)["state"]


def _shadow_lock_path(user_id: str) -> str:
    return _shadow_model_paths(user_id)["lock"]
