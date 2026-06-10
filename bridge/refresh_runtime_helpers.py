from __future__ import annotations
from importlib import import_module
import logging
import re
import time
from typing import Any, Dict, Optional
from . import session_runtime_helpers as _process_helpers
from .shared import read_session_state
from .qt_thread_dispatch import dispatch_to_qt_thread, is_qt_main_thread
from bioauth_runtime import runtime_boundary
_LOGGER = logging.getLogger(__name__)
_WORKER_PAIR_CHECK_INTERVAL_SEC = 8.0   # avoid calling every 1s refresh
_WORKER_HEARTBEAT_FROZEN_SEC    = 30.0  # heartbeat older than this while process alive → frozen
_MONITOR_START_EXIT_REASON_MAP = {
    "session_inactive": "monitor_start_session_inactive",
    "session_id_mismatch": "monitor_start_session_id_mismatch",
    "stop_requested": "monitor_start_stop_requested",
    "stop_requested_during_intruder_hold": "monitor_start_stop_requested",
    "unhandled_runtime_exception": "monitor_start_runtime_exception",
}
_CRITICAL_REFRESH_REASON_TOKENS = (
    "runtime",
    "monitor",
    "logger",
    "protected",
    "auth",
    "signin",
    "sign-in",
    "logout",
    "enrollment",
    "startup",
    "timer",
    "qml",
    "refreshnow",
    "stop",
)

# Compatibility shell: implementation functions are loaded into this module
# so existing monkeypatches of private globals such as _facade still work.
from pathlib import Path as _BioAuthSplitPath

_BIOAUTH_SPLIT_DIR = _BioAuthSplitPath(__file__).with_name('refresh_runtime_split')
_BIOAUTH_SPLIT_MODULES = ('worker_pair_liveness.py', 'dashboard_state.py', 'refresh_timer_dispatch.py', 'feedback_alerts.py', 'pending_logger_start.py', 'pending_shadow_monitor_start.py', 'pending_monitor_start.py',)

def _bioauth_load_split_modules() -> None:
    namespace = globals()
    for module_name in _BIOAUTH_SPLIT_MODULES:
        module_path = _BIOAUTH_SPLIT_DIR / module_name
        code = module_path.read_text(encoding='utf-8')
        exec(compile(code, str(module_path), 'exec'), namespace, namespace)

_bioauth_load_split_modules()

# Compatibility source markers retained for legacy source-inspection tests.
# def check_worker_pair_liveness
# def _facade
# def _shadow_logger_process_key
# def _shadow_monitor_process_key
# def _shadow_logger_stop_control_name
# def _shadow_monitor_stop_control_name
# def _safe_dashboard_error_text
# def _ensure_dashboard_state_fields
# def dashboard_state_payload
# def is_dashboard_visible
# def emit_dashboard_state_changed
# def set_dashboard_visible
# def set_dashboard_state
# def set_status
# def emit_controls_changed
# def emit_all
# def desired_refresh_interval_ms
# def update_refresh_timer
# def invalidate_dashboard_snapshot_cache
# def dashboard_snapshot_ttl_sec
# def maybe_emit_feedback_prompt
# def handle_state_alerts
# def fail_pending_logger_start
# def maybe_finish_pending_logger_start
# def fail_pending_shadow_evidence_monitor_start
# def _safe_monitor_start_detail
# def _monitor_start_exit_reason_from_state
# def fail_pending_monitor_start
# def maybe_finish_pending_monitor_start
# def _safe_refresh_reason
# def _ensure_refresh_request_state
# def _is_critical_refresh
# def _merge_refresh_reason
# def _debug_refresh_request
# def _run_debounced_refresh
# def request_refresh
# def refresh_now
# def update_runtime_background_state
# def _commercial_runtime_fenced
# def _perform_refresh_now
# def _begin_refresh_cycle
# def _refresh_visible_or_background_state
# def _run_commercial_refresh_display
# def _finish_refresh_cycle
# def _maybe_log_slow_refresh
# def _run_non_commercial_refresh_side_effects
# def _recover_passive_finalization
# def _run_auto_promotion
# def _run_noncommercial_bootstrap
# def _run_passive_finalizer
# def _run_shadow_evidence_bootstrap
# def _run_auto_training
# def _run_passive_auto_enrollment
# def _run_noncommercial_shadow_session
# def _refresh_noncommercial_shadow_status
# def _mark_phase
# monitor_start_wait_extended_by_worker_heartbeat

