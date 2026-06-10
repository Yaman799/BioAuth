"""Filesystem path helpers for model metadata/runtime bundles."""

from __future__ import annotations

import os
from typing import Dict

from utils.identity import slugify_username

from metadata_core.constants import ACTIVE_RUNTIME_POINTER_FILE, CANDIDATE_BUNDLE_DIRNAME, DEEP_SEQUENCE_ARTIFACT_FILENAME, PRODUCTION_BUNDLE_DIRNAME
import paths


def _user_model_dir(user_id: str) -> str:
    safe = slugify_username(user_id)
    return os.path.join(paths.models_dir(), f"user_{safe}")


def _bundle_paths(base: str) -> Dict[str, str]:
    return {
        "base": base,
        "model": os.path.join(base, "model.pkl"),
        "classifier": os.path.join(base, "classifier.pkl"),
        "metadata": os.path.join(base, "metadata.json"),
        "sequence_model": os.path.join(base, DEEP_SEQUENCE_ARTIFACT_FILENAME),
        "evaluation_report": os.path.join(base, "evaluation_report.json"),
        "evaluation_summary": os.path.join(base, "evaluation_summary.md"),
    }


def _user_candidate_bundle_dir(user_id: str) -> str:
    return os.path.join(_user_model_dir(user_id), CANDIDATE_BUNDLE_DIRNAME)


def _user_production_bundle_dir(user_id: str) -> str:
    return os.path.join(_user_model_dir(user_id), PRODUCTION_BUNDLE_DIRNAME)


def _user_model_paths(user_id: str) -> Dict[str, str]:
    return _bundle_paths(_user_candidate_bundle_dir(user_id))


def _user_production_paths(user_id: str) -> Dict[str, str]:
    return _bundle_paths(_user_production_bundle_dir(user_id))


def _active_runtime_pointer_path(user_id: str) -> str:
    return os.path.join(_user_model_dir(user_id), ACTIVE_RUNTIME_POINTER_FILE)


__all__ = [
    "_active_runtime_pointer_path",
    "_bundle_paths",
    "_user_candidate_bundle_dir",
    "_user_model_dir",
    "_user_model_paths",
    "_user_production_bundle_dir",
    "_user_production_paths",
]
