from __future__ import annotations
import json
import logging
import os
import re
import signal
import threading
import time
from collections import deque
from importlib import import_module
from typing import Any, Dict, List, Optional
from release_runtime import startup_protected_session_decision, write_release_runtime_event
LOGGER = logging.getLogger(__name__)
_INDEPENDENT_SHADOW_EVIDENCE_MONITOR_ENV = "BIOAUTH_ENABLE_SHADOW_EVIDENCE_MONITOR"
_TERMINAL_SESSION_STATES = frozenset({"stopped", "idle", "ended", "complete", "completed"})
_TERMINAL_RUNTIME_STATUSES = frozenset({"stopped", "idle", "ended", "complete", "completed"})
_PROTECTED_STALE_FLOW_RECOVERY_HEARTBEAT_GRACE_SEC = 12.0
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.IGNORECASE | re.DOTALL),
    re.compile(r"BIOAUTH-LIC-v1\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)(passphrase|password|private[_ -]?key|signing[_ -]?secret)\s*[:=]\s*\S+"),
]
_WORKER_TAIL_LIMIT = 12
_WORKER_LINE_LIMIT = 700
PASSIVE_FINALIZATION_RECOVERY_GRACE_SECONDS = 15.0
PASSIVE_FINALIZATION_RECOVERY_MAX_SECONDS = 60.0
PASSIVE_FINALIZATION_ALREADY_LOG_INTERVAL_SECONDS = 15.0
SHADOW_EVIDENCE_SESSION_KIND = "shadow_evidence"
SHADOW_EVIDENCE_SOURCE = "shadow_evidence_monitor"
SHADOW_PENDING_LOGGER_SESSION_KINDS = frozenset({SHADOW_EVIDENCE_SESSION_KIND, "shadow"})
SHADOW_EVIDENCE_BOOTSTRAP_COOLDOWN_SECONDS = 20.0
HYBRID_DIRECT_TEST_SESSION_KIND = "hybrid_direct_test"
HYBRID_DIRECT_TEST_SOURCE = "hybrid_direct_test_monitor"
HYBRID_DIRECT_TEST_TIMEOUT_SECONDS = 45.0
HYBRID_DIRECT_TEST_MAX_AGE_SECONDS = 24 * 60 * 60
HYBRID_DIRECT_TEST_FALSE_SAFETY_KEYS = (
    "lock_allowed",
    "device_lock_allowed",
    "protected_sessions_unlock_allowed",
    "face_confirmation_allowed",
    "face_confirmation_trigger_allowed",
    "production_pointer_write_allowed",
    "production_approval_allowed",
    "production_promotion_allowed",
    "raw_behavioral_data_included",
)

# Compatibility shell: implementation functions are loaded into this module
# so existing monkeypatches of private globals such as _facade still work.
from pathlib import Path as _BioAuthSplitPath

_BIOAUTH_SPLIT_DIR = _BioAuthSplitPath(__file__).with_name('session_runtime_split')
_BIOAUTH_SPLIT_MODULES = ('demo_classic_runtime.py', 'worker_heartbeat_merge.py', 'flow_state.py', 'shadow_cleanup.py', 'worker_diagnostics.py', 'worker_process_launch.py', 'hybrid_direct_contracts.py', 'hybrid_direct_reports.py', 'live_session_eval.py', 'candidate_observer.py', 'hybrid_test_runner.py', 'runtime_process_state.py', 'tracked_process_cleanup.py', 'terminal_state.py', 'protected_stop.py', 'orphaned_state.py', 'runtime_enforcement_inputs.py', 'post_lock_confirmation.py', 'runtime_enforcement.py', 'session_flow.py', 'autostart.py', 'passive_finalization.py', 'passive_enrollment.py', 'production_shadow_state.py', 'shadow_monitor_lifecycle.py',)

def _bioauth_load_split_modules() -> None:
    namespace = globals()
    for module_name in _BIOAUTH_SPLIT_MODULES:
        module_path = _BIOAUTH_SPLIT_DIR / module_name
        code = module_path.read_text(encoding='utf-8')
        exec(compile(code, str(module_path), 'exec'), namespace, namespace)

_bioauth_load_split_modules()

# Compatibility source markers retained for legacy source-inspection tests.
# def _demo_classic_protected_enabled
# def _env_flag_enabled
# def _independent_shadow_evidence_monitor_enabled
# def _demo_classic_candidate_or_runtime_artifact_exists
# def _ensure_demo_classic_runtime_pointer
# def _demo_classic_apply_profile_overlay
# def _demo_classic_forced_intruder_resume_pending
# def _demo_classic_post_unlock_resume_overlay
# def _request_refresh
# def _facade
# def _user_runtime
# def _heartbeat_age_sec
# def _worker_heartbeat_matches
# def _is_terminal_protected_state
# def _heartbeat_is_fresh
# def _has_current_tracked_process_alive
# def _protected_state_is_stale_without_workers
# def recover_stale_protected_flow_without_workers
# def _read_matching_worker_heartbeat
# def merge_worker_heartbeats_into_state
# def _effective_production_ready
# def _developer_production_ready_simulation_active
# def _current_safe_user
# def _call_shadow_identity_helper
# def _shadow_logger_process_key
# def _shadow_monitor_process_key
# def _shadow_logger_stop_control_name
# def _shadow_monitor_stop_control_name
# def _clear_shadow_stop_controls
# def _request_shadow_stop_controls
# def _state_is_shadow_evidence
# def _pending_logger_kind
# def _shadow_logger_start_pending
# def _normal_logger_start_pending
# def _normal_logger_process_key
# def _normal_logger_process_running
# def _is_shadow_runtime_process_running
# def _has_stale_shadow_state
# def _clear_stale_shadow_state_if_safe
# def _normal_user_session_flow
# def _normal_enrollment_logger_flow
# def _normal_enrollment_logger_stop_available
# def _production_monitor_flow
# def _protected_session_stop_available
# def _shadow_session_flow
# def _request_hidden_shadow_cleanup_for_normal_action
# def _safe_worker_line
# def _worker_diag_map
# def _ensure_worker_diag
# def _append_worker_output
# def _start_worker_output_reader
# def _record_worker_start
# def record_completed_process
# def worker_diagnostics_snapshot
# def worker_failure_detail
# def start_process
# def _hybrid_direct_test_report_path
# def _hybrid_direct_test_process_key
# def _hybrid_direct_replay_sessions_root
# def hybrid_direct_test_blockers
# def hybrid_direct_monitor_smoke_test_blockers
# def can_run_hybrid_direct_test
# def _hybrid_removed_from_commercial_flow_payload
# def _hybrid_training_not_required_summary
# def _hybrid_direct_test_result_payload
# def _read_hybrid_direct_test_report
# def _write_backend_hybrid_direct_test_report
# def _normalize_hybrid_direct_test_report_safety
# def latest_hybrid_direct_test_report
# def _parse_hybrid_direct_timestamp
# def validate_hybrid_direct_test_evidence
# def _hybrid_result_status_message
# def _hybrid_direct_reports_dir
# def _hybrid_live_session_eval_reports_dir
# def _hybrid_live_session_eval_result_payload
# def _update_hybrid_direct_state_from_live_eval
# def run_latest_live_session_eval
# def latest_hybrid_live_session_eval_result
# def latest_hybrid_live_session_eval_report_state
# def _hybrid_live_candidate_observer_reports_dir
# def _observer_state_with_safety
# def _store_live_candidate_observer_state
# def live_candidate_observer_state
# def start_live_candidate_observer
# def stop_live_candidate_observer
# def _hybrid_direct_offline_reason_codes
# def _update_hybrid_direct_state_from_offline_summary
# def run_hybrid_direct_test
# def run_hybrid_direct_monitor_smoke_test
# def _safe_float
# def _valid_epoch
# def _state_pid
# def _state_pid_for
# def _pid_is_running
# def _terminate_pid_best_effort
# def _logger_stop_name_from_state
# def runtime_state_is_orphaned
# def _tracked_session_processes
# def _has_tracked_running_session_process
# def _terminate_tracked_session_processes
# def _request_stop_for_current_session
# def _debug_runtime_event
# def _emit_runtime_and_control_changes
# def _terminate_process_key
# def _terminal_protected_session_state
# def _write_terminal_live_session_marker
# def finalize_protected_session_stop
# def _clear_runtime_after_terminal_stop
# def _terminal_failure_without_worker
# def force_clear_orphaned_runtime_state
# def clear_stale_runtime_state
# def stop_stale_monitor
# def _safe_int
# def _safe_number
# def _lock_current_session_result_for_enforcement
# def _lock_result_fields
# def _load_settings_for_enforcement
# def _capture_incident_evidence_for_enforcement
# def _update_incident_record_for_enforcement
# def _intruder_enforcement_id
# def _intruder_enforcement_already_applied
# def _incident_notice
# def _lock_status_for_incident
# def _post_lock_event_id
# def _post_lock_confirmation_fields
# def _make_post_lock_feedback_prompt
# def _carry_post_lock_confirmation_for_resume
# def classify_post_lock_confirmation
# def enforce_confirmed_intruder_event
# def session_flow
# def maybe_autostart_protection
# def _is_passive_auto_enrollment_state
# def _session_logger_process_alive
# def _passive_stop_or_finalize_already_requested
# def _passive_finalization_epoch
# def _passive_finalization_started_at
# def _passive_finalization_elapsed_seconds
# def _history_or_archive_pending_recent
# def detect_stale_passive_finalization
# def _safe_recovery_timestamp
# def _write_passive_recovery_metadata_marker
# def _emit_passive_recovery_signals
# def recover_stale_passive_auto_enrollment_finalization
# def _debug_skip_duplicate_passive_finalization
# def maybe_start_passive_auto_enrollment
# def stop_passive_auto_enrollment_if_active
# def maybe_finalize_passive_auto_enrollment
# def _profile_production_approval_state
# def _shadow_evidence_candidate_status
# def _process_is_alive
# def _shadow_evidence_logger_running
# def _shadow_evidence_monitor_running
# def _production_monitor_process_running
# def _protected_or_unrelated_monitor_running
# def _restore_shadow_evidence_pending_context
# def _mark_shadow_evidence_monitor_collecting
# def _shadow_evidence_block_reason
# def start_shadow_evidence_monitor
# def maybe_start_shadow_evidence_monitor
# def _shadow_evidence_retry_handoff_block_reason
# def _mark_shadow_evidence_stopped_for_retry
# def request_shadow_evidence_stop_for_retry
# def maybe_mark_shadow_evidence_stopped_for_retry
# def stop_shadow_evidence_monitor
# def start_enrollment
# def start_protected_session
# def stop_enrollment_logger
# def shutdown_runtime_workers
# def stop_current_session
# def stop_production_monitor
# def maybe_resume_protection_after_unlock
# protection_session_controller.start_protection
# stop_controller.stop_protection
# resume_controller.maybe_resume_after_unlock
# worker_heartbeat_single_writer
# clear_worker_heartbeat("logger")
# clear_worker_heartbeat("monitor")
# "source": "bridge"
# "worker_heartbeat_single_writer": True

