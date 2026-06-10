"""Extracted implementation section for `monitor_core/common.py`."""
from __future__ import annotations
import json
import logging
import os
import time
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Optional

def _facade():
    return import_module("monitor")

def _safe_json_write(path: str, data: Any) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    facade = _facade()
    facade.atomic_write_bytes(path, payload)

def _allow_plaintext_monitor_log_fallback() -> bool:
    return os.environ.get("BIOAUTH_ALLOW_PLAINTEXT_MONITOR_LOG", "").strip() == "1"

def _load_log_entries() -> List[Dict[str, Any]]:
    facade = _facade()
    if not os.path.exists(facade.LOG_FILE):
        return []
    try:
        raw = Path(facade.LOG_FILE).read_bytes()
        if not raw:
            return []
        cipher = facade.get_cipher()
        try:
            decoded = cipher.decrypt(raw).decode("utf-8")
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            if not _allow_plaintext_monitor_log_fallback():
                LOGGER.warning("Rejected undecryptable monitor log %s without explicit plaintext fallback: %s", facade.LOG_FILE, exc)
                return []
            LOGGER.warning("Using explicit plaintext fallback for legacy monitor log %s: %s", facade.LOG_FILE, exc)
            decoded = raw.decode("utf-8")
        data = json.loads(decoded)
        return data if isinstance(data, list) else []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        LOGGER.warning("Failed loading monitor log entries from %s: %s", facade.LOG_FILE, exc)
        return []

def _save_log_entries(entries: List[Dict[str, Any]]) -> None:
    facade = _facade()
    payload = json.dumps(entries[-500:], ensure_ascii=False, indent=2).encode("utf-8")
    encrypted = facade.get_cipher().encrypt(payload)
    facade.atomic_write_bytes(facade.LOG_FILE, encrypted)

def _log_entries_cache() -> List[Dict[str, Any]]:
    facade = _facade()
    if facade._LOG_CACHE is None:
        facade._LOG_CACHE = facade._load_log_entries()
    return facade._LOG_CACHE

def append_log(entry: Dict[str, Any]) -> None:
    facade = _facade()
    with facade._LOG_LOCK:
        log = facade._log_entries_cache()
        log.append(entry)
        if len(log) > 500:
            del log[:-500]
        facade._save_log_entries(log)

def _normalize_state_label(label: Optional[str]) -> Optional[str]:
    if label is None:
        return None
    v = str(label).strip().lower()
    if v in ("legit", "legitimate", "accepted"):
        return "legit"
    if v == "suspicious":
        return "suspicious"
    if v == "intruder":
        return "intruder"
    if v in ("", "pending", "unknown", "rejected", "interrupted"):
        return None
    return None

def _decision_bucket(label: Optional[str]) -> Optional[str]:
    decision = _normalize_state_label(label)
    if decision == "legit":
        return "authorized"
    if decision in ("suspicious", "intruder"):
        return "rejected"
    return None

def _same_session(state: Dict[str, Any], session_id: Optional[str]) -> bool:
    if not isinstance(state, dict):
        return False
    if not session_id:
        return True
    state_session = state.get("session_id")
    if state_session in (None, ""):
        return True
    return str(state_session) == str(session_id)

def _intruder_hold_active(state: Dict[str, Any], session_id: Optional[str]) -> bool:
    if not isinstance(state, dict) or not _same_session(state, session_id):
        return False
    if str(state.get("session_kind") or "").strip().lower() == SHADOW_EVIDENCE_SESSION_KIND or _shadow_evidence_mode():
        return False
    # Commercial-Core-22I:
    # Resume-pending forced-stop states are intentionally inactive.  They must
    # not keep the monitor process in the intruder hold loop forever, otherwise
    # the backend cannot observe a clean, expected monitor exit and start a fresh
    # protected session after Windows unlock.
    if not bool(state.get("active", True)):
        return False
    final_decision = str(state.get("final_decision") or state.get("archive_label") or state.get("decision") or "").strip().lower()
    return bool(
        state.get("forced_stop")
        or state.get("app_locked")
        or state.get("monitor_holding")
        or state.get("restriction_active")
        or final_decision == "intruder"
    )

def _shadow_evidence_mode() -> bool:
    return (
        os.environ.get("BIOAUTH_RUNTIME_MODE", "").strip().lower() == SHADOW_EVIDENCE_SESSION_KIND
        or os.environ.get("BIOAUTH_SHADOW_EVIDENCE_ONLY", "").strip() == "1"
    )



def _is_resume_pending_lock_handoff_state(state: Dict[str, Any]) -> bool:
    if not isinstance(state, dict) or not state:
        return False
    status_values = {
        str(state.get("status") or "").strip().lower(),
        str(state.get("runtime_status") or "").strip().lower(),
    }
    explicit = bool(state.get("lock_controller_handoff") or state.get("lock_handoff_id"))
    resume_pending = bool(state.get("auto_resume_pending") or state.get("resume_after_unlock"))
    forced_lock = bool(state.get("forced_stop") or state.get("app_locked") or state.get("screen_locked"))
    expected_exit = bool(state.get("forced_stop_expected_monitor_exit") or state.get("monitor_exit_expected"))
    return (
        not bool(state.get("active"))
        and ("resume_pending" in status_values or resume_pending)
        and (explicit or expected_exit or (resume_pending and forced_lock))
    )


def _extra_is_lock_handoff(extra: Any) -> bool:
    if not isinstance(extra, dict):
        return False
    return bool(
        extra.get("lock_controller_handoff")
        or extra.get("lock_handoff_id")
        or extra.get("auto_resume_pending")
        or extra.get("resume_after_unlock")
        or str(extra.get("status") or extra.get("runtime_status") or "").strip().lower() == "resume_pending"
    )


def _preserve_resume_pending_lock_handoff(state: Dict[str, Any], decision: Optional[str], extra: Any, previous_seq: int) -> Dict[str, Any]:
    preserved = dict(state)
    if isinstance(extra, dict):
        # Only merge safe diagnostics. Do not let normal runtime evidence revive the
        # protected session after the lock controller has handed off to resume.
        for key in (
            "monitor_exit_reason",
            "monitor_exit_reason_text",
            "monitor_exit_detail",
            "monitor_exit_recorded_at",
            "runtime_diagnostics",
        ):
            if key in extra:
                preserved[key] = extra.get(key)
    now = time.time()
    preserved.update({
        "active": False,
        "status": "resume_pending",
        "runtime_status": "resume_pending",
        "decision": _normalize_state_label(decision) or preserved.get("decision") or "intruder",
        "final_decision": preserved.get("final_decision") or "intruder",
        "archive_label": preserved.get("archive_label") or "intruder",
        "final_bucket": preserved.get("final_bucket") or "rejected",
        "forced_stop": True,
        "app_locked": bool(preserved.get("app_locked") or preserved.get("screen_locked") or preserved.get("lockAttempted") or preserved.get("windowsLockAttempted")),
        "protected_action_requested": True,
        "auto_resume_pending": True,
        "resume_after_unlock": True,
        "forced_stop_expected_monitor_exit": True,
        "monitor_exit_expected": True,
        "monitor_ready": False,
        "monitor_failed": False,
        "technical_failure": False,
        "risk_engine_stopped": False,
        "monitor_pid": os.getpid(),
        "monitor_heartbeat_at": now,
        "monitor_heartbeat_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "runtime_telemetry_seq": previous_seq + 1,
        "runtime_telemetry_source": "monitor",
        "updated_at": now,
        "lock_handoff_preserved_after_monitor_write": True,
    })
    preserved.setdefault("resume_reason", "intruder_lock")
    preserved.setdefault("stop_reason", "monitor_intruder")
    preserved.setdefault("source", "monitor")
    preserved.setdefault("mode", "monitored")
    return preserved



def _read_json_path(path: Any) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _published_lock_handoff_state(current_state: Dict[str, Any]) -> Dict[str, Any]:
    """Return the latest monitor-published lock handoff for this session.

    The monitor is the single writer for runtime heartbeat/summary data.  After
    a Windows lock request, session_state.json can still contain the older
    active protected state until the bridge merges the heartbeat.  A following
    monitor tick must therefore preserve the previous monitor heartbeat/summary
    lock handoff instead of publishing active=True again.
    """
    session_id = str((current_state or {}).get("session_id") or "").strip()
    candidates = []
    try:
        from control import worker_heartbeat_path, CONTROL_DIR
        candidates.append(_read_json_path(worker_heartbeat_path("monitor")))
        candidates.append(_read_json_path(Path(CONTROL_DIR) / "runtime_summary.json"))
    except Exception:
        return {}
    for payload in candidates:
        if not isinstance(payload, dict) or not payload:
            continue
        if session_id and str(payload.get("session_id") or "").strip() not in {"", session_id}:
            continue
        if _is_resume_pending_lock_handoff_state(payload) or _extra_is_lock_handoff(payload):
            return dict(payload)
    return {}

def _write_monitor_state(decision: Optional[str] = None, extra=None):
    facade = _facade()
    current = facade.read_session_state(default={})
    state = dict(current) if isinstance(current, dict) else {}
    previous_seq = int(state.get("runtime_telemetry_seq") or 0) if str(state.get("runtime_telemetry_seq") or "").isdigit() else 0
    published_handoff = _published_lock_handoff_state(state)
    if published_handoff and not _extra_is_lock_handoff(extra):
        source_seq = int(published_handoff.get("runtime_telemetry_seq") or previous_seq) if str(published_handoff.get("runtime_telemetry_seq") or "").isdigit() else previous_seq
        preserved = _preserve_resume_pending_lock_handoff(published_handoff, decision, extra, source_seq)
        preserved["lock_handoff_preserved_from_previous_monitor_publish"] = True
        preserved.setdefault("session_id", state.get("session_id"))
        preserved.setdefault("run_id", state.get("run_id"))
        preserved.setdefault("user_id", state.get("user_id"))
        preserved.setdefault("session_kind", state.get("session_kind", "protected"))
        from bioauth_runtime.monitor_worker.decision_engine import merge_runtime_decision_payload
        from bioauth_runtime.monitor_worker.heartbeat import write_monitor_heartbeat_payload
        from bioauth_runtime.monitor_worker.runtime_summary_writer import write_runtime_summary_payload

        preserved = merge_runtime_decision_payload(preserved)
        write_monitor_heartbeat_payload(preserved)
        write_runtime_summary_payload(preserved)
        return
    if _is_resume_pending_lock_handoff_state(state) and not _extra_is_lock_handoff(extra):
        preserved = _preserve_resume_pending_lock_handoff(state, decision, extra, previous_seq)
        from bioauth_runtime.monitor_worker.decision_engine import merge_runtime_decision_payload
        from bioauth_runtime.monitor_worker.heartbeat import write_monitor_heartbeat_payload
        from bioauth_runtime.monitor_worker.runtime_summary_writer import write_runtime_summary_payload

        preserved = merge_runtime_decision_payload(preserved)
        write_monitor_heartbeat_payload(preserved)
        write_runtime_summary_payload(preserved)
        return
    shadow_mode = _shadow_evidence_mode() or str(state.get("session_kind") or "").strip().lower() == SHADOW_EVIDENCE_SESSION_KIND
    state.update(
        {
            "mode": SHADOW_EVIDENCE_SESSION_KIND if shadow_mode else "monitored",
            "active": True,
            "source": SHADOW_EVIDENCE_SOURCE if shadow_mode else "monitor",
            "evidence_source": SHADOW_EVIDENCE_SOURCE if shadow_mode else state.get("evidence_source"),
            "runtime_mode": SHADOW_EVIDENCE_SESSION_KIND if shadow_mode else state.get("runtime_mode"),
            "decision": facade._normalize_state_label(decision),
            "expected_user": facade.EXPECTED_USER_SLUG,
        }
    )
    if shadow_mode:
        state.update({
            "session_kind": SHADOW_EVIDENCE_SESSION_KIND,
            "trust_level": "shadow_runtime",
            "excluded_from_positive_training": True,
            "training_counts_toward_minimum": False,
            "metadata_trusted": False,
            "app_locked": False,
            "screen_locked": False,
            "forced_stop": False,
            "monitor_holding": False,
            "restriction_active": False,
        })
    if extra and isinstance(extra, dict):
        state.update(extra)

    now = time.time()
    state.update(
        {
            "monitor_pid": os.getpid(),
            "monitor_heartbeat_at": now,
            "monitor_heartbeat_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "runtime_telemetry_seq": previous_seq + 1,
            "runtime_telemetry_source": "monitor",
            "updated_at": now,
        }
    )
    state.setdefault("updated_at_text", time.strftime("%H:%M:%S", time.localtime(now)))

    if state.get("decision") is None and state.get("active"):
        state["decision"] = "pending"
    if state.get("decision") == "pending" and not state.get("active"):
        state["decision"] = None
    # Commercial-Core-22M/Phase4: monitor no longer writes session_state.json.
    # It publishes one authoritative runtime decision payload to worker heartbeat
    # and runtime_summary.json; the bridge/coordinator only displays/merges it.
    from bioauth_runtime.monitor_worker.decision_engine import merge_runtime_decision_payload
    from bioauth_runtime.monitor_worker.heartbeat import write_monitor_heartbeat_payload
    from bioauth_runtime.monitor_worker.runtime_summary_writer import write_runtime_summary_payload

    state = merge_runtime_decision_payload(state)
    write_monitor_heartbeat_payload(state)
    write_runtime_summary_payload(state)

def _load_shadow_evidence_candidate_bundle(user_id: str) -> Dict[str, Any]:
    facade = _facade()
    try:
        from metadata_core.paths import _user_model_paths
        from metadata_core.runtime import runtime_deep_contract_state, runtime_feature_schema_mismatch_reason

        paths = _user_model_paths(user_id)
        metadata_file = str(paths.get("metadata") or "")
        model_file = str(paths.get("model") or "")
        classifier_file = str(paths.get("classifier") or "")
        if not metadata_file or not model_file or not os.path.exists(metadata_file) or not os.path.exists(model_file):
            return {
                "model": None,
                "metadata": {"shadow_evidence_blocked_reason": "candidate_artifact_missing"},
                "classifier": None,
                "metadata_file": metadata_file or None,
                "classifier_file": classifier_file or None,
                "paths": paths,
            }
        meta = facade.load_metadata(metadata_file) or {}
        status = str(meta.get("model_status") or meta.get("candidate_status") or "").strip().lower()
        if status != "approved_for_shadow":
            return {
                "model": None,
                "metadata": {**dict(meta), "shadow_evidence_blocked_reason": "candidate_not_approved_for_shadow"},
                "classifier": None,
                "metadata_file": metadata_file,
                "classifier_file": classifier_file or None,
                "paths": paths,
            }
        schema_reason = runtime_feature_schema_mismatch_reason(dict(meta))
        if schema_reason:
            return {
                "model": None,
                "metadata": {**dict(meta), "shadow_evidence_blocked_reason": schema_reason, "technical_failure": True},
                "classifier": None,
                "metadata_file": metadata_file,
                "classifier_file": classifier_file or None,
                "paths": paths,
            }
        model = facade.load_model(model_file)
        classifier = facade.load_classifier(classifier_file) if classifier_file and os.path.exists(classifier_file) else None
        return {
            "model": model,
            "metadata": meta,
            "classifier": classifier,
            "metadata_file": metadata_file,
            "classifier_file": classifier_file or None,
            "paths": paths,
            "deep_runtime": runtime_deep_contract_state(dict(meta or {})),
            "shadow_evidence_only": True,
        }
    except Exception as exc:
        LOGGER.warning("Shadow evidence candidate runtime load blocked for %s: %s", user_id, exc)
        return {
            "model": None,
            "metadata": {"shadow_evidence_blocked_reason": "candidate_runtime_load_failed", "technical_failure": True, "error": str(exc)},
            "classifier": None,
            "metadata_file": None,
            "classifier_file": None,
        }
