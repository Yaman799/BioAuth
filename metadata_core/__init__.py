"""Compatibility facade for the stable metadata/runtime API."""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "ACTIVE_RUNTIME_POINTER_FILE",
    "ACTIVE_WINDOW_SCALES",
    "CANDIDATE_BUNDLE_DIRNAME",
    "CLASSIFIER_FILE",
    "CONTEXT_ROUTER_MIN_CONFIDENCE",
    "CONTEXT_ROUTING_VERSION",
    "FEATURE_SCHEMA_VERSION",
    "FEATURE_WINDOW_STRATEGY",
    "KB_HEADER",
    "LIVE_SESSION_DIR",
    "MAX_ENROLLMENT_TRAINING_SESSIONS",
    "MAX_PREDICT_WINDOWS",
    "MAX_REFERENCE_NEGATIVE_SESSIONS",
    "MAX_TRAIN_WINDOWS_PER_SESSION",
    "METADATA_FILE",
    "MIN_CONTEXT_POSITIVE_SESSION_SUPPORT",
    "MIN_CONTEXT_POSITIVE_WINDOW_SAMPLES",
    "MIN_NEGATIVE_WINDOW_SAMPLES",
    "MIN_POSITIVE_WINDOW_SAMPLES",
    "MIN_REQUIRED_ENROLLMENT_SESSIONS",
    "MIN_WINDOW_EVENTS",
    "MODEL_FILE",
    "MODELS_DIR",
    "MS_HEADER",
    "PREDICT_WINDOW_STEP_SECONDS",
    "PRODUCTION_BUNDLE_DIRNAME",
    "RECOMMENDED_ENROLLMENT_SESSIONS",
    "ROUTER_CONTEXTS",
    "RUNTIME_POINTER_SCHEMA_VERSION",
    "RUNTIME_SCHEMA_POLICY_VERSION",
    "SESSIONS_DIR",
    "SHADOW_BACKUP_DAYS",
    "SHADOW_DISCARD_THRESHOLD",
    "SHADOW_EVAL_SESSIONS",
    "SHADOW_LOCK_STALE_SECONDS",
    "SHADOW_MAX_SESSIONS",
    "SHADOW_MIN_SESSIONS",
    "SHADOW_PROMOTE_THRESHOLD",
    "WINDOW_SECONDS",
    "WINDOW_STEP_SECONDS",
    "build_user_dashboard_snapshot",
    "clear_runtime_model_cache",
    "canonical_runtime_pointer_json",
    "delete_user_data",
    "index_entry_to_metadata",
    "invalidate_session_discovery_cache",
    "list_session_dirs",
    "list_session_index_entries",
    "rebuild_metadata_database_from_files",
    "metadata_database_privacy_statement",
    "metadata_database_summary",
    "initialize_metadata_database",
    "load_session_index",
    "read_session_metadata",
    "rebuild_session_index",
    "remove_session_from_index",
    "update_session_index_for_path",
    "reset_user_profile",
    "resolve_active_runtime_paths",
    "resolve_active_runtime_paths_with_validation",
    "runtime_feature_schema_compatible",
    "runtime_feature_schema_mismatch_reason",
    "sign_runtime_pointer_payload",
    "summarize_user_sessions",
    "user_model_lifecycle_lock",
    "user_profile_status",
    "validate_runtime_bundle_for_activation",
    "verify_runtime_pointer_payload",
    "write_active_runtime_pointer",
]

_CONSTANT_EXPORTS = {
    name for name in __all__ if name.isupper()
}
_PATH_EXPORTS = {
    "_active_runtime_pointer_path",
    "_bundle_paths",
    "_user_candidate_bundle_dir",
    "_user_model_dir",
    "_user_model_paths",
    "_user_production_bundle_dir",
    "_user_production_paths",
}
_RUNTIME_EXPORTS = {
    "canonical_runtime_pointer_json",
    "clear_runtime_model_cache",
    "load_model_metadata_cached",
    "resolve_active_runtime_paths",
    "resolve_active_runtime_paths_with_validation",
    "runtime_feature_schema_compatible",
    "runtime_feature_schema_mismatch_reason",
    "sign_runtime_pointer_payload",
    "validate_runtime_bundle_for_activation",
    "verify_runtime_pointer_payload",
    "write_active_runtime_pointer",
}
_SESSION_EXPORTS = {
    "index_entry_to_metadata",
    "invalidate_session_discovery_cache",
    "list_session_dirs",
    "list_session_index_entries",
    "load_session_index",
    "read_session_metadata",
    "rebuild_session_index",
    "remove_session_from_index",
    "update_session_index_for_path",
}
_METADATA_DB_EXPORTS = {
    "initialize_metadata_database": "initialize_database",
    "metadata_database_summary": "database_summary",
    "metadata_database_privacy_statement": "privacy_statement",
    "rebuild_metadata_database_from_files": "rebuild_from_files",
}
_HELPER_EXPORTS = {
    "_append_jsonl",
    "_format_timestamp",
    "_now_timestamp",
    "_parse_timestamp_value",
    "_read_text_file",
    "_unique_existing_paths",
}
_SHADOW_EXPORTS = {
    "_backup_model_dir",
    "_shadow_lock_path",
    "_shadow_model_dir",
    "_shadow_model_paths",
    "_shadow_state_defaults",
    "_shadow_state_path",
}
_DASHBOARD_EXPORTS = {
    "_build_training_snapshot",
    "_collect_negative_sessions_for_user",
    "_describe_training_block",
    "_is_accepted_session",
    "_session_bucket",
    "_session_quality_ok",
    "_session_sort_key",
    "_training_session_view_defaults",
    "_user_session_paths",
    "_user_session_records",
}


def __getattr__(name: str) -> Any:
    if name not in __all__ and name not in _PATH_EXPORTS and name not in _HELPER_EXPORTS and name not in _SHADOW_EXPORTS and name not in _DASHBOARD_EXPORTS and name not in _METADATA_DB_EXPORTS:
        raise AttributeError(name)
    if name in _CONSTANT_EXPORTS:
        module_name = "metadata_core.constants"
    elif name in _PATH_EXPORTS:
        module_name = "metadata_core.paths"
    elif name in _RUNTIME_EXPORTS:
        module_name = "metadata_core.runtime"
    elif name in _SESSION_EXPORTS:
        module_name = "metadata_core.sessions"
    elif name in _METADATA_DB_EXPORTS:
        module_name = "metadata_core.metadata_db"
        name = _METADATA_DB_EXPORTS[name]
    elif name in _HELPER_EXPORTS:
        module_name = "metadata_core.helpers"
    elif name in _SHADOW_EXPORTS:
        module_name = "metadata_core.shadow"
    elif name in _DASHBOARD_EXPORTS:
        module_name = "metadata_core.dashboard"
    else:
        module_name = "model_metadata"
    module = importlib.import_module(module_name)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | _PATH_EXPORTS | _HELPER_EXPORTS | _SHADOW_EXPORTS | _DASHBOARD_EXPORTS | set(_METADATA_DB_EXPORTS))
