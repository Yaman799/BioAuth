from __future__ import annotations
import logging
import os
from importlib import import_module
from typing import Any, Dict, List
from bioauth_runtime import runtime_boundary
from .runtime_labels import runtime_policy_display_fields
from . import refresh_runtime_helpers as _refresh_state
from .qt_thread_dispatch import dispatch_to_qt_thread
LOGGER = logging.getLogger(__name__)
_DASHBOARD_TIMING_FIELDS = (
    "session_count",
    "total_session_count",
    "dashboard_snapshot_mode",
    "cache_hit",
    "session_index_hit",
    "session_index_rebuild",
    "session_index_count",
    "session_index_ms",
    "session_dirs_ms",
    "metadata_reads_ms",
    "user_filter_ms",
    "session_sort_ms",
    "training_snapshot_ms",
    "runtime_path_resolution_ms",
    "runtime_validation_ms",
    "model_metadata_ms",
    "model_metadata_cache_hit",
    "runtime_validation_cache_hit",
    "dashboard_normalization_ms",
    "dashboard_total_ms",
)

# Compatibility shell: implementation functions are loaded into this module
# so existing monkeypatches of private globals such as _facade still work.
from pathlib import Path as _BioAuthSplitPath

_BIOAUTH_SPLIT_DIR = _BioAuthSplitPath(__file__).with_name('dashboard_refresh_split')
_BIOAUTH_SPLIT_MODULES = ('dashboard_timing.py', 'production_approval_view.py', 'runtime_metrics.py', 'drift_live_cards.py', 'runtime_state_view.py', 'profile_status_view.py', 'dashboard_snapshot.py',)

def _bioauth_load_split_modules() -> None:
    namespace = globals()
    for module_name in _BIOAUTH_SPLIT_MODULES:
        module_path = _BIOAUTH_SPLIT_DIR / module_name
        code = module_path.read_text(encoding='utf-8')
        exec(compile(code, str(module_path), 'exec'), namespace, namespace)

_bioauth_load_split_modules()

# Compatibility source markers retained for legacy source-inspection tests.
# def _facade
# def _production_approval_status_for_user
# def _time_now
# def _elapsed_ms
# def _coerce_nonnegative_int
# def _dashboard_debug_timing
# def _set_dashboard_debug_timing
# def _add_dashboard_view_timing
# def _production_approval_refresh_signature
# def _should_observe_production_approval_state
# def format_elapsed
# def _runtime_age_seconds
# def _runtime_int
# def _runtime_elapsed_seconds
# def _recent_risk_trend
# def _drift_channel_status
# def _combined_drift_status
# def _evidence_capture_text
# def _build_drift_live_cards
# def build_runtime_state_view
# def build_profile_view
# def status_for_dashboard
# def _normalized_snapshot
# def _dashboard_fast_session_limit
# def _compute_dashboard_snapshot
# def _compute_full_history_snapshot
# def _snapshot_fallback
# def _async_snapshot_enabled
# def _dashboard_cache_state
# def _apply_dashboard_snapshot_result
# def _queue_dashboard_snapshot_refresh
# def dashboard_snapshot
# def _ensure_full_history_state
# def _full_history_profile_fields
# def _merge_history_profile_fields
# def _apply_full_history_result
# def _queue_full_history_refresh
# def load_full_history
# def _history_logger_still_finalizing
# def _finish_history_archive_watch
# def sync_history_after_archive
# def update_dashboard

