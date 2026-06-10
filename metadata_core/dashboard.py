"""Dashboard, session summary, and training-readiness helpers."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from utils.identity import slugify_username
from metadata_core.constants import (
    MAX_ENROLLMENT_TRAINING_SESSIONS,
    MAX_REFERENCE_NEGATIVE_SESSIONS,
    MIN_REQUIRED_ENROLLMENT_SESSIONS,
    MIN_WINDOW_EVENTS,
    RECOMMENDED_ENROLLMENT_SESSIONS,
    WINDOW_SECONDS,
)
from metadata_core.helpers import _format_timestamp, _parse_timestamp_value
from metadata_core.model_readiness import build_model_readiness_state
from metadata_core.paths import _active_runtime_pointer_path, _user_model_dir, _user_model_paths
from metadata_core.passive_quality import (
    enrollment_session_counts_toward_trusted_minimum,
    session_meets_passive_trusted_minimum_floor_if_needed,
)
from metadata_core.production_approval import build_production_approval_state
from metadata_core.remediation_loop import (
    RemediationPlan,
    build_remediation_plan_from_gate_state,
    remediation_evidence_progress_from_summary,
)
from metadata_core.auto_training_scheduler import (
    remediation_evidence_progress_from_sessions,
    remediation_retry_block_reason,
)
from metadata_core.runtime import load_model_metadata_cached, resolve_active_runtime_paths, resolve_active_runtime_paths_with_validation, validate_runtime_bundle_for_activation
from metadata_core.production_bootstrap import last_good_production_overlay, maybe_bootstrap_initial_production_runtime
from metadata_core.sessions import index_entry_to_metadata, list_session_dirs, list_session_index_entries, read_session_metadata
from runtime_policy import maturity_progress_summary, normalize_calibration_maturity

DEFAULT_DASHBOARD_SESSION_LIMIT = 10
LOGGER = logging.getLogger(__name__)


def _now_perf() -> float:
    return time.perf_counter()


def _elapsed_ms(started_at: float) -> int:
    try:
        return max(0, int(round((_now_perf() - float(started_at)) * 1000.0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return int(default)
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _timing_add(timing: Optional[Dict[str, Any]], key: str, elapsed_ms: int) -> None:
    if not isinstance(timing, dict):
        return
    try:
        timing[key] = int(timing.get(key, 0) or 0) + max(0, int(elapsed_ms))
    except (TypeError, ValueError, OverflowError):
        timing[key] = max(0, int(elapsed_ms or 0))


def _timing_set(timing: Optional[Dict[str, Any]], key: str, value: Any) -> None:
    if isinstance(timing, dict):
        timing[key] = value


def _session_bucket(path: str, meta: Optional[Dict[str, Any]] = None) -> str:
    data = meta if isinstance(meta, dict) else {}

    training_eligible = data.get("training_eligible")
    if training_eligible is True:
        return "accepted"

    bucket = str(data.get("bucket") or data.get("archive_group") or "").strip().lower()
    if bucket in {"accepted", "authorized", "legit"}:
        return "accepted"
    if bucket in {"rejected", "unauthorized", "intruder", "suspicious"}:
        return "rejected"

    decision = str(data.get("final_decision") or data.get("archive_label") or data.get("label") or "").strip().lower()
    if decision in {"legit", "legitimate", "accepted"}:
        return "accepted"
    if decision in {"intruder", "suspicious", "rejected", "unauthorized", "interrupted"}:
        return "rejected"

    sep = "\\"
    norm = path.replace("/", sep).lower()
    if f"{sep}accepted{sep}" in norm or f"{sep}authorized{sep}" in norm:
        return "accepted"
    if f"{sep}rejected{sep}" in norm or f"{sep}unauthorized{sep}" in norm:
        return "rejected"
    return "rejected"


def _is_accepted_session(path: str, meta: Optional[Dict[str, Any]] = None) -> bool:
    return _session_bucket(path, meta) == "accepted"


def _session_quality_ok(meta: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(meta, dict):
        return False
    total_rows = int(meta.get("keyboard_rows", 0) or 0) + int(meta.get("mouse_rows", 0) or 0)
    duration = float(meta.get("duration_seconds", 0) or 0)
    return total_rows >= MIN_WINDOW_EVENTS and duration >= max(6.0, WINDOW_SECONDS / 2.0)


def _training_session_view_defaults() -> Dict[str, Any]:
    return {
        "training_visibility": "not_applicable",
        "training_status_tone": "neutral",
        "training_counts_toward_minimum": False,
        "training_selected": False,
        "training_quality_score": None,
        "training_quality_tier": "",
        "training_selection_reason": "",
        "training_block_reason": "",
        "training_reason_detail": "",
    }


def _describe_training_block(
    meta: Dict[str, Any],
    *,
    accepted: bool,
    trusted: bool,
    training_eligible: bool,
    quality_ok: bool,
    passive_floor_ok: bool = True,
) -> tuple[str, str]:
    if not accepted:
        decision = str(meta.get("final_decision") or meta.get("archive_label") or "unknown").strip().lower()
        if decision in {"intruder", "suspicious", "interrupted"}:
            return "session_not_accepted", "Only legitimate archived sessions can be used for profile training."
        return "session_not_accepted", "This archived session is outside the accepted training bucket."
    if not trusted:
        detail = str(meta.get("metadata_diagnostic") or "").strip()
        return "metadata_not_trusted", detail or "This session is ignored for training because its metadata integrity could not be verified."
    if not training_eligible:
        total_rows = int(meta.get("keyboard_rows", 0) or 0) + int(meta.get("mouse_rows", 0) or 0)
        stop_reason = str(meta.get("stop_reason") or "").strip().lower()
        if total_rows <= 0:
            return "session_without_behavior_data", "This session does not contain enough recorded behavior data to train on."
        if stop_reason and stop_reason != "control_stop":
            return "session_not_completed_normally", "Only enrollment sessions that ended normally count toward the training minimum."
        return "session_not_training_eligible", "This session is archived, but it is not marked as training-eligible."
    if not quality_ok:
        return "session_quality_baseline_not_met", "This session is too short or too inactive to count toward training readiness."
    if not passive_floor_ok:
        return "passive_candidate_below_quality_floor", "Passive candidate archived, but it needs more evidence before it can count toward the trusted enrollment minimum."
    return "", ""


_SESSION_READINESS_AUDIT_SCHEMA_VERSION = "commercial-core-22b-session-readiness-audit-v1"
_SESSION_AUDIT_MAX_RECORDS = 80


def _safe_session_audit_id(path: str) -> str:
    try:
        return os.path.basename(os.path.abspath(str(path or "")))[:96]
    except Exception:
        return ""


def _increment_reason(counter: Dict[str, int], reason: str) -> None:
    key = str(reason or "accepted").strip() or "accepted"
    counter[key] = int(counter.get(key, 0) or 0) + 1


def _session_readiness_audit_from_records(
    user_id: str,
    user_records: List[Tuple[str, Dict[str, Any]]],
    *,
    selected_paths: Optional[set[str]] = None,
    limit: int = _SESSION_AUDIT_MAX_RECORDS,
) -> Dict[str, Any]:
    """Return privacy-safe reasons why local sessions do or do not train.

    This audit is diagnostic-only. It never reads raw behavior logs; it only
    explains the already-loaded session metadata used by dashboard/training
    readiness.  It is intentionally explicit because otherwise users can see
    history rows while the training gate still says that zero trusted enrollment
    sessions are available.
    """

    selected_paths = selected_paths or set()
    safe_user = slugify_username(str(user_id or ""))
    reason_counts: Dict[str, int] = {}
    kind_counts: Dict[str, int] = {}
    accepted_enrollment = 0
    trusted_enrollment = 0
    training_eligible_enrollment = 0
    quality_ok_enrollment = 0
    counts_toward_minimum = 0
    selected_for_training = 0
    records: List[Dict[str, Any]] = []

    for path, meta_source in list(user_records or []):
        meta = dict(meta_source or {})
        resolved = os.path.abspath(str(path or ""))
        session_kind = str(meta.get("session_kind") or "unknown").strip().lower() or "unknown"
        kind_counts[session_kind] = int(kind_counts.get(session_kind, 0) or 0) + 1
        accepted = _is_accepted_session(resolved, meta)
        trusted = bool(meta.get("metadata_trusted"))
        training_eligible = bool(meta.get("training_eligible"))
        quality_ok = _session_quality_ok(meta)
        passive_floor_ok = session_meets_passive_trusted_minimum_floor_if_needed(meta)
        reason_code, reason_detail = _describe_training_block(
            meta,
            accepted=accepted,
            trusted=trusted,
            training_eligible=training_eligible,
            quality_ok=quality_ok,
            passive_floor_ok=passive_floor_ok,
        )
        counts = False
        if session_kind == "enrollment":
            if accepted:
                accepted_enrollment += 1
            if trusted:
                trusted_enrollment += 1
            if training_eligible:
                training_eligible_enrollment += 1
            if quality_ok:
                quality_ok_enrollment += 1
            counts = enrollment_session_counts_toward_trusted_minimum(
                meta,
                accepted=accepted,
                trusted=trusted,
                training_eligible=training_eligible,
                quality_ok=quality_ok,
            )
            if counts:
                counts_toward_minimum += 1
                reason_code = "accepted_for_training_minimum"
                reason_detail = "Counts toward the trusted enrollment minimum."
        elif session_kind == "protected":
            reason_code = reason_code or ("supplemental_protected_candidate" if accepted and trusted and quality_ok else "protected_not_training_minimum")
            reason_detail = reason_detail or "Protected sessions never count toward the enrollment minimum."
        elif session_kind == "shadow_evidence":
            reason_code = "shadow_evidence_excluded"
            reason_detail = "Shadow evidence sessions are never owner-positive training sessions."
        else:
            reason_code = reason_code or "unsupported_session_kind"
            reason_detail = reason_detail or "Only enrollment sessions count toward initial training readiness."

        selected = resolved in selected_paths
        if selected:
            selected_for_training += 1
        _increment_reason(reason_counts, reason_code or "accepted")

        if len(records) < max(0, int(limit or _SESSION_AUDIT_MAX_RECORDS)):
            meta_user = slugify_username(str(meta.get("user_id") or "")) if meta.get("user_id") else ""
            records.append({
                "session_id": _safe_session_audit_id(resolved),
                "session_kind": session_kind,
                "user_match": bool((not meta_user) or meta_user == safe_user),
                "accepted_bucket": bool(accepted),
                "metadata_trusted": bool(trusted),
                "training_eligible": bool(training_eligible),
                "quality_ok": bool(quality_ok),
                "passive_floor_ok": bool(passive_floor_ok),
                "counts_toward_minimum": bool(counts),
                "selected_for_training": bool(selected),
                "reject_reason": "" if counts else str(reason_code or ""),
                "reason_detail": str(reason_detail or "")[:240],
                "input_event_count": max(0, _safe_int(meta.get("keyboard_rows")) + _safe_int(meta.get("mouse_rows"))),
                "duration_seconds": max(0.0, float(meta.get("duration_seconds", 0) or 0.0)),
                "stop_reason": str(meta.get("stop_reason") or "")[:96],
            })

    minimum = int(MIN_REQUIRED_ENROLLMENT_SESSIONS)
    deficit = max(0, minimum - int(counts_toward_minimum))
    if counts_toward_minimum >= minimum:
        primary_blocker = ""
    elif not user_records:
        primary_blocker = "no_sessions_found"
    elif accepted_enrollment <= 0:
        primary_blocker = "no_accepted_enrollment_sessions"
    elif trusted_enrollment <= 0:
        primary_blocker = "no_trusted_enrollment_sessions"
    elif training_eligible_enrollment <= 0:
        primary_blocker = "no_training_eligible_enrollment_sessions"
    elif quality_ok_enrollment <= 0:
        primary_blocker = "no_quality_ok_enrollment_sessions"
    else:
        primary_blocker = "need_more_trusted_sessions"

    return {
        "schema_version": _SESSION_READINESS_AUDIT_SCHEMA_VERSION,
        "user_id": safe_user,
        "minimum_required_enrollment_sessions": minimum,
        "total_session_records": len(user_records or []),
        "accepted_enrollment_sessions": accepted_enrollment,
        "trusted_enrollment_sessions": trusted_enrollment,
        "training_eligible_enrollment_sessions": training_eligible_enrollment,
        "quality_ok_enrollment_sessions": quality_ok_enrollment,
        "counts_toward_training_minimum": counts_toward_minimum,
        "selected_for_training_count": selected_for_training,
        "training_deficit": deficit,
        "training_can_start": counts_toward_minimum >= minimum,
        "primary_blocker": primary_blocker,
        "session_kind_counts": kind_counts,
        "rejection_reason_counts": reason_counts,
        "records_sampled": len(records),
        "records_truncated": len(user_records or []) > len(records),
        "records": records,
    }


def build_session_readiness_audit(
    user_id: str,
    *,
    session_detail_limit: int = _SESSION_AUDIT_MAX_RECORDS,
    list_session_dirs_fn=list_session_dirs,
    read_session_metadata_fn=read_session_metadata,
    list_session_index_entries_fn=list_session_index_entries,
    use_session_index: bool = True,
    timing_collector: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    safe = slugify_username(user_id)
    records = _user_session_records(
        safe,
        list_session_dirs_fn=list_session_dirs_fn,
        read_session_metadata_fn=read_session_metadata_fn,
        list_session_index_entries_fn=list_session_index_entries_fn,
        use_session_index=use_session_index,
        timing_collector=timing_collector,
    )
    return _session_readiness_audit_from_records(
        safe,
        records,
        selected_paths=set(),
        limit=session_detail_limit,
    )


def _build_training_snapshot(
    user_id: str,
    sessions: List[Dict[str, Any]],
    user_records: List[Tuple[str, Dict[str, Any]]],
    *,
    include_selection_details: bool = True,
) -> Dict[str, Any]:
    """Build training readiness from all records while annotating visible rows only."""
    session_lookup: Dict[str, Dict[str, Any]] = {}
    for item in sessions:
        defaults = _training_session_view_defaults()
        for key, value in defaults.items():
            item.setdefault(key, value)
        if item.get("path"):
            session_lookup[os.path.abspath(str(item["path"]))] = item

    accepted_enrollment_count = 0
    trusted_enrollment_count = 0
    candidate_entries: List[Tuple[str, Dict[str, Any]]] = []
    protected_candidates: List[Tuple[str, Dict[str, Any]]] = []
    kind_by_path: Dict[str, str] = {}

    for path, meta in user_records:
        resolved = os.path.abspath(path)
        item = session_lookup.get(resolved)
        accepted = _is_accepted_session(resolved, meta)
        trusted = bool(meta.get("metadata_trusted"))
        training_eligible = bool(meta.get("training_eligible"))
        quality_ok = _session_quality_ok(meta)
        passive_floor_ok = session_meets_passive_trusted_minimum_floor_if_needed(meta)
        session_kind = str(meta.get("session_kind") or "unknown").strip().lower()
        kind_by_path[resolved] = session_kind

        if accepted and session_kind == "enrollment":
            accepted_enrollment_count += 1

        reason_code, reason_detail = _describe_training_block(
            meta,
            accepted=accepted,
            trusted=trusted,
            training_eligible=training_eligible,
            quality_ok=quality_ok,
            passive_floor_ok=passive_floor_ok,
        )

        if session_kind == "enrollment":
            counts_toward_minimum = enrollment_session_counts_toward_trusted_minimum(
                meta,
                accepted=accepted,
                trusted=trusted,
                training_eligible=training_eligible,
                quality_ok=quality_ok,
            )
            if counts_toward_minimum:
                trusted_enrollment_count += 1
                candidate_entries.append((resolved, meta))
            if item is not None:
                item["training_counts_toward_minimum"] = counts_toward_minimum
                if counts_toward_minimum:
                    item["training_visibility"] = "counts_toward_minimum"
                    item["training_status_tone"] = "details"
                    item["training_reason_detail"] = "Counts toward the trusted enrollment minimum."
                else:
                    item["training_visibility"] = "blocked"
                    item["training_status_tone"] = "warn"
                    item["training_block_reason"] = reason_code
                    item["training_reason_detail"] = reason_detail
        elif session_kind == "protected":
            if accepted and trusted and quality_ok:
                protected_candidates.append((resolved, meta))
                candidate_entries.append((resolved, meta))
                if item is not None:
                    item["training_visibility"] = "supplemental_candidate"
                    item["training_status_tone"] = "info"
                    item["training_reason_detail"] = "This protected session may be used as supplemental positive evidence after enrollment training is ready."
            elif item is not None:
                item["training_visibility"] = "blocked"
                item["training_status_tone"] = "neutral" if not accepted else "warn"
                item["training_block_reason"] = reason_code or ("protected_session_quality_low" if accepted and trusted else "protected_session_not_eligible")
                if reason_detail:
                    item["training_reason_detail"] = reason_detail
                elif accepted and trusted:
                    item["training_reason_detail"] = "Protected sessions must have enough duration and activity before they can be used as supplemental evidence."
                else:
                    item["training_reason_detail"] = "This protected session is not eligible to support profile training."
        elif item is not None:
            item["training_visibility"] = "blocked"
            item["training_status_tone"] = "neutral"
            item["training_block_reason"] = "unsupported_session_kind"
            item["training_reason_detail"] = "Only enrollment sessions count toward the minimum, and only protected sessions can be added as supplemental positives."

    selection_summary: Optional[Dict[str, Any]] = None
    selected_enrollment_count = 0
    selected_protected_count = 0
    if include_selection_details and candidate_entries:
        try:
            from training_core.selection import build_training_selection

            selection_summary = build_training_selection(
                candidate_entries,
                [],
                max_enrollment_sessions=MAX_ENROLLMENT_TRAINING_SESSIONS,
                max_negative_sessions=0,
            )
        except Exception:
            LOGGER.warning("Training session selection summary failed; dashboard will continue without selection details.", exc_info=True)
            selection_summary = None

    selected_paths: set[str] = set()
    if selection_summary is not None:
        included_by_path: Dict[str, Dict[str, Any]] = {}
        excluded_by_path: Dict[str, Dict[str, Any]] = {}
        for entry in list(selection_summary.get("included_sessions") or []):
            session_path = os.path.abspath(str(entry.get("session_path") or "").strip())
            if not session_path:
                continue
            included_by_path[session_path] = dict(entry)
            selected_paths.add(session_path)
            if kind_by_path.get(session_path) == "enrollment":
                selected_enrollment_count += 1
            else:
                selected_protected_count += 1
        for entry in list(selection_summary.get("excluded_sessions") or []):
            session_path = os.path.abspath(str(entry.get("session_path") or "").strip())
            if session_path:
                excluded_by_path[session_path] = dict(entry)

        for session_path, entry in included_by_path.items():
            item = session_lookup.get(session_path)
            if item is None:
                continue
            item["training_selected"] = True
            item["training_quality_score"] = entry.get("quality_score")
            item["training_quality_tier"] = entry.get("quality_tier") or ""
            item["training_selection_reason"] = str(entry.get("selection_reason") or "")
            item["training_block_reason"] = ""
            item["training_reason_detail"] = str(entry.get("selection_reason") or item.get("training_reason_detail") or "")
            if str(item.get("session_kind") or "").strip().lower() == "enrollment":
                item["training_visibility"] = "selected"
                item["training_status_tone"] = "success"
            else:
                item["training_visibility"] = "supplemental_selected"
                item["training_status_tone"] = "info"
        for session_path, entry in excluded_by_path.items():
            item = session_lookup.get(session_path)
            if item is None:
                continue
            item["training_quality_score"] = entry.get("quality_score")
            item["training_quality_tier"] = entry.get("quality_tier") or ""
            item["training_selection_reason"] = str(entry.get("selection_reason") or "")
            item["training_block_reason"] = str(entry.get("exclusion_reason") or item.get("training_block_reason") or "")
            item["training_reason_detail"] = str(entry.get("selection_reason") or item.get("training_reason_detail") or "")
            if str(item.get("session_kind") or "").strip().lower() == "enrollment":
                item["training_visibility"] = "counts_toward_minimum" if item.get("training_counts_toward_minimum") else "blocked"
                item["training_status_tone"] = "warn" if entry.get("exclusion_reason") == "quality_score_below_floor" else "details"
            else:
                item["training_visibility"] = "supplemental_excluded"
                item["training_status_tone"] = "warn" if entry.get("exclusion_reason") == "quality_score_below_floor" else "neutral"

    session_readiness_audit = _session_readiness_audit_from_records(
        user_id,
        user_records,
        selected_paths=selected_paths,
        limit=_SESSION_AUDIT_MAX_RECORDS,
    )

    training_can_start = False
    training_block_reason = ""
    training_block_detail = ""
    if trusted_enrollment_count < MIN_REQUIRED_ENROLLMENT_SESSIONS:
        training_block_reason = "need_more_trusted_sessions"
        training_block_detail = "Only archived sessions with verified metadata integrity count toward the training minimum."
    elif selection_summary is not None and not list(selection_summary.get("positive_sessions") or []):
        training_block_reason = "need_higher_quality_sessions"
        training_block_detail = "The trusted sessions currently available are too low-quality or too repetitive after the quality/diversity gate."
    else:
        training_can_start = trusted_enrollment_count >= MIN_REQUIRED_ENROLLMENT_SESSIONS

    return {
        "session_count": trusted_enrollment_count,
        "saved_session_count": accepted_enrollment_count,
        "trusted_session_count": trusted_enrollment_count,
        "untrusted_session_count": max(0, accepted_enrollment_count - trusted_enrollment_count),
        "training_can_start": training_can_start,
        "training_block_reason": training_block_reason,
        "training_block_detail": training_block_detail,
        "training_selected_enrollment_count": selected_enrollment_count,
        "training_selected_protected_count": selected_protected_count,
        "training_selection": selection_summary or {},
        "session_readiness_audit": session_readiness_audit,
        "sessionReadinessAudit": session_readiness_audit,
    }


def _user_session_paths(
    user_id: str,
    *,
    list_session_dirs_fn=list_session_dirs,
    read_session_metadata_fn=read_session_metadata,
) -> List[str]:
    safe = slugify_username(user_id)
    result = []
    for session_path in list_session_dirs_fn():
        meta = read_session_metadata_fn(session_path) or {}
        meta_user = slugify_username(str(meta.get("user_id") or "")) if meta.get("user_id") else None
        name = os.path.basename(session_path)
        if meta_user == safe or name.startswith(f"{safe}_"):
            result.append(session_path)
    return result


def _collect_negative_sessions_for_user(
    user_id: str,
    *,
    list_session_dirs_fn=list_session_dirs,
    read_session_metadata_fn=read_session_metadata,
) -> List[str]:
    safe = slugify_username(user_id)
    negatives: List[str] = []
    for session_path in list_session_dirs_fn():
        meta = read_session_metadata_fn(session_path) or {}
        meta_user = slugify_username(str(meta.get("user_id") or "")) if meta.get("user_id") else None
        if meta_user == safe:
            continue
        if not _is_accepted_session(session_path, meta):
            continue
        if not _session_quality_ok(meta):
            continue
        negatives.append(session_path)
    negatives.sort(key=os.path.getmtime)
    return negatives[-MAX_REFERENCE_NEGATIVE_SESSIONS:]


def _session_sort_key(path: str, meta: Optional[Dict[str, Any]]) -> Tuple[float, str]:
    data = meta if isinstance(meta, dict) else {}
    parsed = _parse_timestamp_value(data.get("created_at") or data.get("started_at") or data.get("started_at_text"))
    if parsed is None:
        try:
            parsed = float(os.path.getmtime(path))
        except OSError:
            parsed = 0.0
    return parsed, os.path.basename(path)


def _user_session_records(
    user_id: str,
    *,
    list_session_dirs_fn=list_session_dirs,
    read_session_metadata_fn=read_session_metadata,
    list_session_index_entries_fn=list_session_index_entries,
    use_session_index: bool = True,
    timing_collector: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    safe = slugify_username(user_id)
    records: List[Tuple[str, Dict[str, Any]]] = []

    can_use_index = bool(
        use_session_index
        and list_session_dirs_fn is list_session_dirs
        and read_session_metadata_fn is read_session_metadata
        and callable(list_session_index_entries_fn)
    )
    if can_use_index:
        started = _now_perf()
        try:
            entries = list(list_session_index_entries_fn(timing_collector=timing_collector) or [])
        except TypeError:
            entries = list(list_session_index_entries_fn() or [])
        except Exception:
            LOGGER.warning("Dashboard session index read failed; falling back to direct session discovery.", exc_info=True)
            entries = []
            can_use_index = False
        if can_use_index:
            _timing_add(timing_collector, "session_dirs_ms", _elapsed_ms(started))
            _timing_set(timing_collector, "session_count", len(entries))
            started = _now_perf()
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                session_path = str(entry.get("path") or "")
                if not session_path:
                    continue
                meta = index_entry_to_metadata(entry)
                meta_user = slugify_username(str(meta.get("user_id") or "")) if meta.get("user_id") else None
                name = os.path.basename(session_path)
                if meta_user == safe or name.startswith(f"{safe}_"):
                    records.append((session_path, meta))
            _timing_add(timing_collector, "user_filter_ms", _elapsed_ms(started))
            _timing_add(timing_collector, "metadata_reads_ms", 0)
            _timing_set(timing_collector, "user_session_count", len(records))
            return records

    started = _now_perf()
    session_paths = list(list_session_dirs_fn() or [])
    _timing_add(timing_collector, "session_dirs_ms", _elapsed_ms(started))
    _timing_set(timing_collector, "session_count", len(session_paths))

    metadata_reads_ms = 0
    user_filter_ms = 0
    for session_path in session_paths:
        started = _now_perf()
        meta = read_session_metadata_fn(session_path) or {}
        metadata_reads_ms += _elapsed_ms(started)

        started = _now_perf()
        meta_user = slugify_username(str(meta.get("user_id") or "")) if meta.get("user_id") else None
        name = os.path.basename(session_path)
        if meta_user == safe or name.startswith(f"{safe}_"):
            records.append((session_path, meta))
        user_filter_ms += _elapsed_ms(started)

    _timing_add(timing_collector, "metadata_reads_ms", metadata_reads_ms)
    _timing_add(timing_collector, "user_filter_ms", user_filter_ms)
    _timing_set(timing_collector, "user_session_count", len(records))
    return records



def _session_view_base_from_meta(path: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Return aggregate, QML-safe session fields from metadata.

    This helper is intentionally free of training-row default materialization so
    fast dashboard snapshots can build strategy/remediation summaries for the
    full history without constructing every visible row payload. It reads only
    persisted aggregate metadata and never raw keyboard/mouse samples.
    """

    bucket = _session_bucket(path, meta)
    created_at = meta.get("created_at") or _format_timestamp(_session_sort_key(path, meta)[0]) or ""
    return {
        "path": path,
        "session_id": meta.get("session_id") or os.path.basename(path),
        "created_at": created_at,
        "session_kind": meta.get("session_kind", "unknown"),
        "decision": meta.get("final_decision", meta.get("archive_label", "unknown")),
        "bucket": bucket,
        "duration_seconds": int(meta.get("duration_seconds", 0) or 0),
        "keyboard_rows": int(meta.get("keyboard_rows", 0) or 0),
        "mouse_rows": int(meta.get("mouse_rows", 0) or 0),
        "metadata_trusted": bool(meta.get("metadata_trusted")),
        "metadata_integrity": meta.get("metadata_integrity", "unknown"),
        "auto_enrollment": bool(meta.get("auto_enrollment")),
        "collection_source": str(meta.get("collection_source") or ""),
        "time_of_day_bucket": str(meta.get("time_of_day_bucket") or ""),
        "input_coverage": str(meta.get("input_coverage") or ""),
        "training_counts_toward_minimum": bool(meta.get("training_counts_toward_minimum", False)),
        "targeted_collection_action": str(meta.get("targeted_collection_action") or ""),
        "evidence_source": str(meta.get("evidence_source") or ""),
        "trust_level": str(meta.get("trust_level") or ""),
        "excluded_from_positive_training": bool(meta.get("excluded_from_positive_training", False)),
        "post_unlock_trusted_window": bool(meta.get("post_unlock_trusted_window", False)),
        "shadow_comparison_window": bool(meta.get("shadow_comparison_window", False)),
    }


def _session_view_from_meta(path: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    item = _session_view_base_from_meta(path, meta)
    for key, value in _training_session_view_defaults().items():
        item.setdefault(key, value)
    return item


def _bounded_session_records(
    user_records: List[Tuple[str, Dict[str, Any]]],
    *,
    session_detail_limit: Optional[int] = None,
    timing_collector: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    started = _now_perf()
    sorted_records = sorted(
        list(user_records or []),
        key=lambda entry: _session_sort_key(entry[0], entry[1]),
        reverse=True,
    )
    _timing_add(timing_collector, "session_sort_ms", _elapsed_ms(started))
    if session_detail_limit is None:
        return sorted_records
    try:
        limit = max(0, int(session_detail_limit))
    except (TypeError, ValueError, OverflowError):
        limit = DEFAULT_DASHBOARD_SESSION_LIMIT
    return sorted_records[:limit]


_SAFE_EVIDENCE_SECTIONS = (
    "model_agreement",
    "post_unlock_evidence",
    "confirmed_intruder_evidence",
    "runtime_safety",
)


def _safe_scalar(value: Any, default: Any = "") -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return default if value is None else value
    return default


def _safe_reason_codes(value: Any) -> List[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = []
    result: List[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _safe_number_map(value: Any) -> Dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    result: Dict[str, Any] = {}
    for key, raw in source.items():
        key_text = str(key or "").strip()
        if not key_text:
            continue
        # Only aggregate counters/rates/booleans are allowed in dashboard evidence.
        if isinstance(raw, bool):
            result[key_text] = bool(raw)
        elif isinstance(raw, int):
            result[key_text] = int(raw)
        elif isinstance(raw, float):
            result[key_text] = float(raw)
        elif raw in (None, ""):
            result[key_text] = 0
    return result


def _production_evidence_dashboard_state(production_approval_state: Mapping[str, Any] | None) -> Dict[str, Any]:
    source = production_approval_state if isinstance(production_approval_state, Mapping) else {}
    summary = source.get("productionEvidenceSummary") or source.get("production_evidence_summary") or {}
    summary = summary if isinstance(summary, Mapping) else {}
    status = str(
        summary.get("status")
        or source.get("productionEvidenceStatus")
        or source.get("production_evidence_status")
        or "partial"
    ).strip().lower() or "partial"
    promotion_effect = str(
        summary.get("promotion_effect")
        or source.get("productionEvidencePromotionEffect")
        or source.get("production_evidence_promotion_effect")
        or "shadow_only"
    ).strip().lower() or "shadow_only"
    reason_codes = _safe_reason_codes(
        summary.get("reason_codes")
        or source.get("productionEvidenceReasonCodes")
        or source.get("production_evidence_reason_codes")
    )
    if not reason_codes and status == "pass":
        reason_codes = ["production_evidence_passed"]
    elif not reason_codes:
        reason_codes = ["production_evidence_partial"]
    payload: Dict[str, Any] = {
        "status": status,
        "promotion_effect": promotion_effect,
        "reason_codes": reason_codes,
        "candidate_artifact_digest": str(
            summary.get("candidate_artifact_digest")
            or source.get("productionEvidenceCandidateDigest")
            or source.get("production_evidence_candidate_digest")
            or ""
        ),
    }
    for section in _SAFE_EVIDENCE_SECTIONS:
        payload[section] = _safe_number_map(summary.get(section))
    return payload



def _merge_remediation_counts(*sources: Mapping[str, Any] | None) -> Dict[str, int]:
    merged: Dict[str, int] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key, value in source.items():
            text = str(key or "").strip()
            if not text:
                continue
            merged[text] = max(merged.get(text, 0), max(0, _safe_int(value)))
    return merged


def _cap_remediation_counts_for_display(counts: Mapping[str, Any] | None, required: Mapping[str, Any] | None) -> Dict[str, int]:
    """Return dashboard progress counters without overstating completed requirements.

    Ledger summaries may contain hundreds of valid aggregate windows. The UI
    should display requirement progress such as 5/5, not imply that raw
    windows_collected alone decides readiness. Raw ledger counts remain available
    separately under ``ledger_new_evidence`` for backend signatures/diagnostics.
    """

    source = counts if isinstance(counts, Mapping) else {}
    requirements = required if isinstance(required, Mapping) else {}
    result: Dict[str, int] = {}
    for key, value in source.items():
        text = str(key or "").strip()
        if not text:
            continue
        current = max(0, _safe_int(value))
        needed = max(0, _safe_int(requirements.get(text))) if text in requirements else 0
        result[text] = min(current, needed) if needed > 0 else current
    return result


_EVIDENCE_REMEDIATION_REASON_CODES = {
    "insufficient_model_agreement",
    "insufficient_model_agreement_data",
    "insufficient_shadow_windows",
    "baseline_decision_missing",
    "insufficient_post_unlock_evidence",
    "feature_quality_too_low",
    "unknown_rate_too_high",
    "simulated_false_lock_detected",
    "post_unlock_false_lock_detected",
    "confirmed_intruder_low_risk",
}


def _remediation_source_for_dashboard(
    production_approval_state: Mapping[str, Any] | None,
    evidence_gate_state: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    """Choose the display-only remediation source without weakening gates.

    Production approval remains backend-owned and unchanged. When the Production
    Evidence Gate has privacy-safe evidence deficits, the dashboard remediation
    card should explain the evidence plan instead of being overshadowed by the
    separate runtime-publication blocker. If no evidence-specific remediation is
    present, fall back to the full production-approval state so runtime/schema
    blockers still fail closed.
    """

    evidence_source = evidence_gate_state if isinstance(evidence_gate_state, Mapping) else {}
    evidence_reason_codes = _safe_reason_codes(evidence_source.get("reason_codes"))
    if any(code in _EVIDENCE_REMEDIATION_REASON_CODES for code in evidence_reason_codes):
        production_source = production_approval_state if isinstance(production_approval_state, Mapping) else {}
        summary = production_source.get("productionEvidenceSummary") or production_source.get("production_evidence_summary") or {}
        return {
            "reason_codes": evidence_reason_codes,
            "source_gate": "production_evidence",
            "candidate_artifact_digest": evidence_source.get("candidate_artifact_digest")
            or production_source.get("productionEvidenceCandidateDigest")
            or production_source.get("production_evidence_candidate_digest")
            or production_source.get("candidateArtifactDigest")
            or production_source.get("candidate_artifact_digest")
            or "",
            "evidence_report_digest": evidence_source.get("evaluation_report_digest")
            or production_source.get("evidenceReportDigest")
            or production_source.get("evidence_report_digest")
            or "",
            "productionEvidenceSummary": summary if isinstance(summary, Mapping) else {},
        }
    return production_approval_state


def _remediation_dashboard_state(
    production_approval_state: Mapping[str, Any] | None,
    sessions: Iterable[Mapping[str, Any]] | None,
) -> Dict[str, Any]:
    source = production_approval_state if isinstance(production_approval_state, Mapping) else {}
    plan = build_remediation_plan_from_gate_state(source)
    evidence_summary = source.get("productionEvidenceSummary") or source.get("production_evidence_summary") or {}
    session_progress = remediation_evidence_progress_from_sessions(sessions or [], plan)
    ledger_progress = remediation_evidence_progress_from_summary(evidence_summary, plan)
    progress = _merge_remediation_counts(session_progress, ledger_progress)
    plan_payload = dict(plan.to_dict())
    if progress:
        updated = dict(plan_payload)
        updated["current_new_evidence"] = progress
        plan = RemediationPlan.from_dict(updated)
        plan_payload = dict(plan.to_dict())
    required = {str(k): max(0, _safe_int(v)) for k, v in dict(plan_payload.get("required_new_evidence") or {}).items()}
    current_raw = {str(k): max(0, _safe_int(v)) for k, v in dict(plan_payload.get("current_new_evidence") or {}).items()}
    current = _cap_remediation_counts_for_display(current_raw, required)
    block_reason = remediation_retry_block_reason(plan, current)
    plan_payload.update(
        {
            "required_counts": required,
            "current_counts": current,
            "requiredCounts": dict(required),
            "currentCounts": dict(current),
            "required_new_evidence": required,
            "current_new_evidence": current,
            "requiredNewEvidence": dict(required),
            "currentNewEvidence": dict(current),
            "ledger_new_evidence": dict(ledger_progress),
            "ledgerNewEvidence": dict(ledger_progress),
            "session_new_evidence": dict(session_progress),
            "sessionNewEvidence": dict(session_progress),
            "progress_sources": [source for source, values in (("sessions", session_progress), ("shadow_evidence_ledger", ledger_progress)) if values],
            "progressSources": [source for source, values in (("sessions", session_progress), ("shadow_evidence_ledger", ledger_progress)) if values],
            "retry_allowed": bool(plan.retry_allowed),
            "retryAllowed": bool(plan.retry_allowed),
            "retry_block_reason": str(block_reason or ""),
            "retryBlockReason": str(block_reason or ""),
            "remediation_next_action": str(plan_payload.get("next_action") or plan_payload.get("action") or ""),
            "remediationNextAction": str(plan_payload.get("next_action") or plan_payload.get("action") or ""),
            "starts_collection": False,
            "startsCollection": False,
            "starts_training": False,
            "startsTraining": False,
        }
    )
    return plan_payload


def build_user_dashboard_snapshot(
    user_id: str,
    *,
    include_training_selection_details: bool = True,
    session_detail_limit: Optional[int] = None,
    list_session_dirs_fn=list_session_dirs,
    read_session_metadata_fn=read_session_metadata,
    list_session_index_entries_fn=list_session_index_entries,
    use_session_index: bool = True,
    resolve_active_runtime_paths_fn=resolve_active_runtime_paths,
    validate_runtime_bundle_for_activation_fn=validate_runtime_bundle_for_activation,
    resolve_active_runtime_paths_with_validation_fn=None,
    load_model_metadata_fn=load_model_metadata_cached,
    active_runtime_pointer_path_fn=_active_runtime_pointer_path,
    user_model_paths_fn=_user_model_paths,
    user_model_dir_fn=_user_model_dir,
    timing_collector: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    dashboard_started = _now_perf()
    safe = slugify_username(user_id)
    paths = user_model_paths_fn(safe)
    protected_sessions = 0
    user_records = _user_session_records(
        safe,
        list_session_dirs_fn=list_session_dirs_fn,
        read_session_metadata_fn=read_session_metadata_fn,
        list_session_index_entries_fn=list_session_index_entries_fn,
        use_session_index=use_session_index,
        timing_collector=timing_collector,
    )
    visible_records = _bounded_session_records(
        user_records,
        session_detail_limit=session_detail_limit,
        timing_collector=timing_collector,
    )
    sessions: List[Dict[str, Any]] = [_session_view_from_meta(path, meta) for path, meta in visible_records]
    strategy_sessions: List[Dict[str, Any]] = [_session_view_base_from_meta(path, meta) for path, meta in user_records]

    for path, meta in user_records:
        if not _is_accepted_session(path, meta):
            continue
        session_kind = str(meta.get("session_kind", "")).strip().lower()
        if session_kind == "protected" and _session_quality_ok(meta):
            protected_sessions += 1

    started = _now_perf()
    training_snapshot = _build_training_snapshot(
        safe,
        sessions,
        user_records,
        include_selection_details=bool(include_training_selection_details),
    )
    _timing_add(timing_collector, "training_snapshot_ms", _elapsed_ms(started))

    trained_at = None
    trained_meta: Dict[str, Any] = {}
    started = _now_perf()
    if os.path.exists(paths["metadata"]):
        trained_at = _format_timestamp(os.path.getmtime(paths["metadata"]))
        try:
            try:
                trained_meta = load_model_metadata_fn(paths["metadata"], timing_collector=timing_collector) or {}
            except TypeError:
                trained_meta = load_model_metadata_fn(paths["metadata"]) or {}
        except Exception:
            LOGGER.warning("Dashboard model metadata load failed; continuing with empty model metadata.", exc_info=True)
            trained_meta = {}
    _timing_add(timing_collector, "model_metadata_ms", _elapsed_ms(started))

    pointer_present = os.path.exists(active_runtime_pointer_path_fn(safe))
    bootstrap_state: Dict[str, Any] = {}
    # Commercial-Core-22E: if this is the user's first trained candidate and no
    # active production pointer is valid yet, publish an initial production-shaped
    # runtime bundle from the trained candidate.  Later shadow-only candidates do
    # not replace an existing last-good production runtime.
    if not pointer_present and trained_meta and os.path.exists(paths.get("model", "")) and os.path.exists(paths.get("metadata", "")):
        started = _now_perf()
        try:
            bootstrap_state = maybe_bootstrap_initial_production_runtime(
                safe,
                candidate_paths=paths,
                candidate_metadata=trained_meta,
            )
        except Exception:
            LOGGER.warning("Initial production bootstrap failed; continuing with normal dashboard state.", exc_info=True)
            bootstrap_state = {"ok": False, "changed": False, "reason": "initial_production_bootstrap_exception"}
        _timing_add(timing_collector, "initial_production_bootstrap_ms", _elapsed_ms(started))
        if bool(bootstrap_state.get("ok")):
            pointer_present = os.path.exists(active_runtime_pointer_path_fn(safe))
    runtime_validation: Dict[str, Any]
    if callable(resolve_active_runtime_paths_with_validation_fn):
        started = _now_perf()
        try:
            runtime_paths, runtime_validation = resolve_active_runtime_paths_with_validation_fn(safe, timing_collector=timing_collector)
        except TypeError:
            runtime_paths, runtime_validation = resolve_active_runtime_paths_with_validation_fn(safe)
        _timing_add(timing_collector, "runtime_path_resolution_ms", _elapsed_ms(started))
    else:
        started = _now_perf()
        try:
            runtime_paths = resolve_active_runtime_paths_fn(safe, timing_collector=timing_collector)
        except TypeError:
            runtime_paths = resolve_active_runtime_paths_fn(safe)
        _timing_add(timing_collector, "runtime_path_resolution_ms", _elapsed_ms(started))

        started = _now_perf()
        if runtime_paths:
            try:
                runtime_validation = validate_runtime_bundle_for_activation_fn(runtime_paths, timing_collector=timing_collector)
            except TypeError:
                runtime_validation = validate_runtime_bundle_for_activation_fn(runtime_paths)
        else:
            runtime_validation = {"ok": False, "reason": ("runtime_pointer_invalid" if pointer_present else "runtime_pointer_missing"), "metadata": None}
        _timing_add(timing_collector, "runtime_validation_ms", _elapsed_ms(started))
    if callable(resolve_active_runtime_paths_with_validation_fn):
        # ``runtime_path_resolution_ms`` includes pointer resolution and the single
        # validation call for this optimized path; expose a bounded validation field
        # for existing logs without double-validating the bundle.
        _timing_add(timing_collector, "runtime_validation_ms", 0)
    runtime_meta = runtime_validation.get("metadata") if isinstance(runtime_validation.get("metadata"), dict) else trained_meta
    production_approval_state = build_production_approval_state(
        candidate_paths=paths,
        candidate_metadata=trained_meta,
        runtime_validation=runtime_validation,
        runtime_paths=runtime_paths if isinstance(runtime_paths, dict) else {},
        user_id=safe,
    )
    if bool(runtime_validation.get("ok")):
        overlay = last_good_production_overlay(safe)
        if overlay:
            production_approval_state.update({
                "productionReady": True,
                "production_ready": True,
                "protectedSessionsAvailable": True,
                "protected_sessions_available": True,
                "reason_code": "last_good_production_runtime_valid",
                "reasonCode": "last_good_production_runtime_valid",
                "status": "approved",
                "phase": "production_ready",
                "last_good_production_available": True,
                "lastGoodProductionAvailable": True,
                "last_good_production_source": overlay.get("last_good_production_source"),
                "lastGoodProductionSource": overlay.get("lastGoodProductionSource"),
            })
    if bootstrap_state:
        production_approval_state["initial_production_bootstrap"] = dict(bootstrap_state)
        production_approval_state["initialProductionBootstrap"] = dict(bootstrap_state)
    evidence_gate_state = _production_evidence_dashboard_state(production_approval_state)
    remediation_source = _remediation_source_for_dashboard(production_approval_state, evidence_gate_state)
    remediation_state = _remediation_dashboard_state(remediation_source, strategy_sessions)
    calibration_maturity = normalize_calibration_maturity(runtime_meta if isinstance(runtime_meta, dict) else {})
    maturity_summary = maturity_progress_summary(calibration_maturity)

    history_total = len(user_records)
    history_visible = len(sessions)
    history_is_partial = bool(session_detail_limit is not None and history_visible < history_total)
    profile = {
        "ready": os.path.exists(paths["model"]) and os.path.exists(paths["metadata"]),
        "production_ready": bool(production_approval_state.get("protectedSessionsAvailable") or (isinstance(runtime_validation, dict) and runtime_validation.get("ok"))),
        "production_ready_reason": str(production_approval_state.get("reason_code") or runtime_validation.get("reason") or "runtime_pointer_missing"),
        "active_runtime_pointer_present": pointer_present,
        "active_runtime_source": os.path.relpath(runtime_paths["base"], user_model_dir_fn(safe)) if runtime_paths else None,
        "initial_production_bootstrap": dict(bootstrap_state),
        "initialProductionBootstrap": dict(bootstrap_state),
        "last_good_production_available": bool(isinstance(runtime_validation, dict) and runtime_validation.get("ok")),
        "lastGoodProductionAvailable": bool(isinstance(runtime_validation, dict) and runtime_validation.get("ok")),
        "session_count": int(training_snapshot.get("session_count", 0) or 0),
        "saved_session_count": int(training_snapshot.get("saved_session_count", 0) or 0),
        "trusted_session_count": int(training_snapshot.get("trusted_session_count", 0) or 0),
        "untrusted_session_count": int(training_snapshot.get("untrusted_session_count", 0) or 0),
        "minimum_session_count": MIN_REQUIRED_ENROLLMENT_SESSIONS,
        "recommended_session_count": RECOMMENDED_ENROLLMENT_SESSIONS,
        "max_training_session_count": MAX_ENROLLMENT_TRAINING_SESSIONS,
        "supplemental_protected_count": protected_sessions,
        "training_can_start": bool(training_snapshot.get("training_can_start")),
        "training_block_reason": str(training_snapshot.get("training_block_reason") or ""),
        "training_block_detail": str(training_snapshot.get("training_block_detail") or ""),
        "training_selected_enrollment_count": int(training_snapshot.get("training_selected_enrollment_count", 0) or 0),
        "training_selected_protected_count": int(training_snapshot.get("training_selected_protected_count", 0) or 0),
        "session_readiness_audit": training_snapshot.get("session_readiness_audit") or {},
        "sessionReadinessAudit": training_snapshot.get("sessionReadinessAudit") or training_snapshot.get("session_readiness_audit") or {},
        "session_readiness_primary_blocker": str((training_snapshot.get("session_readiness_audit") or {}).get("primary_blocker") or ""),
        "sessionReadinessPrimaryBlocker": str((training_snapshot.get("session_readiness_audit") or {}).get("primary_blocker") or ""),
        "trained_at": trained_at,
        "candidate_model_status": str(trained_meta.get("model_status") or "").strip().lower(),
        "candidate_approval_reason": str(trained_meta.get("approval_reason") or "").strip(),
        "candidate_bundle_role": str(trained_meta.get("bundle_role") or "").strip().lower(),
        "production_approval_state": production_approval_state,
        "production_evidence_dashboard_state": evidence_gate_state,
        "evidence_gate_state": evidence_gate_state,
        "evidence_gate_status": evidence_gate_state.get("status", "partial"),
        "evidence_promotion_effect": evidence_gate_state.get("promotion_effect", "shadow_only"),
        "evidence_reason_codes": list(evidence_gate_state.get("reason_codes") or []),
        "remediation_state": remediation_state,
        "remediation_status": str(remediation_state.get("status") or "planned"),
        "remediation_next_action": str(remediation_state.get("next_action") or remediation_state.get("action") or ""),
        "remediation_required_counts": dict(remediation_state.get("required_counts") or remediation_state.get("required_new_evidence") or {}),
        "remediation_current_counts": dict(remediation_state.get("current_counts") or remediation_state.get("current_new_evidence") or {}),
        "retry_allowed": bool(remediation_state.get("retry_allowed", False)),
        "calibration_maturity": calibration_maturity,
        "calibration_mature": bool(calibration_maturity.get("mature")),
        "runtime_lock_allowed": bool(calibration_maturity.get("lock_allowed")),
        "progressive_protection_phase": str(calibration_maturity.get("progressive_phase") or ""),
        "lock_readiness": maturity_summary,
        "dashboard_snapshot_mode": "fast" if history_is_partial else "full",
        "history_loading": False,
        "history_loaded": not history_is_partial,
        "history_is_partial": history_is_partial,
        "history_session_count": history_total,
        "history_visible_session_count": history_visible,
        "history_status": "partial" if history_is_partial else "loaded",
    }
    profile["model_readiness_state"] = build_model_readiness_state(
        profile=profile,
        production_approval=production_approval_state,
        sessions=strategy_sessions,
    )
    _timing_set(timing_collector, "session_count", history_visible)
    _timing_set(timing_collector, "total_session_count", history_total)
    _timing_set(timing_collector, "dashboard_snapshot_mode", profile["dashboard_snapshot_mode"])
    _timing_add(timing_collector, "dashboard_total_ms", _elapsed_ms(dashboard_started))
    return {"profile": profile, "sessions": sessions}


def build_fast_user_dashboard_snapshot(user_id: str, *, session_detail_limit: int = DEFAULT_DASHBOARD_SESSION_LIMIT, **kwargs) -> Dict[str, Any]:
    kwargs.setdefault("include_training_selection_details", False)
    kwargs.setdefault("session_detail_limit", session_detail_limit)
    return build_user_dashboard_snapshot(user_id, **kwargs)


def summarize_user_sessions(user_id: str, **kwargs) -> List[Dict[str, Any]]:
    kwargs.setdefault("session_detail_limit", None)
    snapshot = build_user_dashboard_snapshot(user_id, **kwargs)
    return [dict(item) for item in snapshot["sessions"]]


def user_profile_status(user_id: str, **kwargs) -> Dict[str, Any]:
    kwargs.setdefault("session_detail_limit", None)
    snapshot = build_user_dashboard_snapshot(user_id, **kwargs)
    return dict(snapshot["profile"])
