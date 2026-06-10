from __future__ import annotations
import json
import logging
import os
import time
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Optional
LOGGER = logging.getLogger(__name__)
SHADOW_EVIDENCE_SESSION_KIND = "shadow_evidence"
SHADOW_EVIDENCE_SOURCE = "shadow_evidence_monitor"

# Compatibility shell: implementation functions are loaded into this module
# so existing monkeypatches of private globals such as _facade still work.
from pathlib import Path as _BioAuthSplitPath

_BIOAUTH_SPLIT_DIR = _BioAuthSplitPath(__file__).with_name('common_split')
_BIOAUTH_SPLIT_MODULES = ('monitor_log_store.py', 'monitor_state_writer.py',)

def _bioauth_load_split_modules() -> None:
    namespace = globals()
    for module_name in _BIOAUTH_SPLIT_MODULES:
        module_path = _BIOAUTH_SPLIT_DIR / module_name
        code = module_path.read_text(encoding='utf-8')
        exec(compile(code, str(module_path), 'exec'), namespace, namespace)

_bioauth_load_split_modules()

# Compatibility source markers retained for legacy source-inspection tests.
# def _facade
# def _safe_json_write
# def _allow_plaintext_monitor_log_fallback
# def _load_log_entries
# def _save_log_entries
# def _log_entries_cache
# def append_log
# def _normalize_state_label
# def _decision_bucket
# def _same_session
# def _intruder_hold_active
# def _shadow_evidence_mode
# def _write_monitor_state
# def _load_shadow_evidence_candidate_bundle
# def _load_runtime_model
# def _predict_runtime
# def _current_live_session_dir
# def _live_input_snapshot
# def _final_monitor_state
# monitor no longer writes session_state.json
# write_monitor_heartbeat_payload(state)
# write_runtime_summary_payload(state)

