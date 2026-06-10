"""MonitorContext — explicit dependency container for monitor_core functions.

Replaces the _facade() = import_module("monitor") anti-pattern.

Previously, monitor_core/incident.py and monitor_core/escalation.py called back
into the monitor module via _facade().  This made them untestable without
importing the full monitor_impl.py with all its module-level side effects.

MonitorContext holds the same dependencies explicitly so:
  1. Tests can inject mocks/stubs without importing monitor.
  2. The dependency graph is visible in function signatures.
  3. monitor_impl.py creates a context from itself; tests create one from stubs.

Backward compatibility: the existing _facade() functions still work for callers
that haven't migrated.  Use make_context_from_monitor_module() to wrap the live
monitor module for production use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class MonitorContext:
    """All dependencies that monitor_core/incident.py needs from monitor_impl.py.

    Fields map 1-to-1 to the attributes/functions accessed through _facade()
    in the old code.  None values make the dependency explicitly optional.
    """

    # ── Session state I/O ────────────────────────────────────────────────────
    write_monitor_state: Callable[..., None] = field(default=lambda **kw: None)
    read_session_state: Callable[..., Dict[str, Any]] = field(default=lambda **kw: {})

    # ── Monitor identity ─────────────────────────────────────────────────────
    expected_user_slug: str = ""

    # ── Settings ─────────────────────────────────────────────────────────────
    load_settings: Callable[[], Dict[str, Any]] = field(default=lambda: {})

    # ── Lock + face ──────────────────────────────────────────────────────────
    lock_workstation_result: Callable[[], Dict[str, Any]] = field(default=lambda: {"lockSucceeded": False})
    pre_lock_face_confirmation: Optional[Callable[..., Dict[str, Any]]] = None

    # ── Incident evidence ────────────────────────────────────────────────────
    capture_incident_evidence: Optional[Callable[..., Dict[str, Any]]] = None
    update_incident_record: Optional[Callable[..., Optional[Dict[str, Any]]]] = None

    # ── Logging ──────────────────────────────────────────────────────────────
    append_log: Callable[[Dict[str, Any]], None] = field(default=lambda entry: None)

    # ── Camera / face confirmation ───────────────────────────────────────────
    build_default_camera_provider: Optional[Callable[..., Any]] = None

    # ── Shadow evidence (optional) ───────────────────────────────────────────
    append_shadow_evidence: Optional[Callable[..., None]] = None

    # ── Stop logger ──────────────────────────────────────────────────────────
    stop_logger_for_context: Optional[Callable[[], None]] = None

    # ── Record false positive (face confirmed owner) ─────────────────────────
    record_face_confirmed_false_positive: Optional[Callable[..., None]] = None


def make_context_from_monitor_module(monitor_module: Any) -> MonitorContext:
    """Wrap a live monitor module as a MonitorContext for production use.

    Call this from monitor_impl.py to pass an explicit context to incident
    functions instead of using _facade().
    """
    def _get(attr: str, default: Any = None) -> Any:
        return getattr(monitor_module, attr, default)

    return MonitorContext(
        write_monitor_state=_get("_write_monitor_state", lambda **kw: None),
        read_session_state=_get("read_session_state", lambda **kw: {}),
        expected_user_slug=str(_get("EXPECTED_USER_SLUG") or ""),
        load_settings=_get("load_settings", lambda: {}),
        lock_workstation_result=_get("_lock_workstation_result", lambda: {"lockSucceeded": False}),
        pre_lock_face_confirmation=_get("_pre_lock_face_confirmation"),
        capture_incident_evidence=_get("_capture_intruder_evidence"),
        update_incident_record=_get("update_incident_record"),
        append_log=_get("append_log", lambda entry: None),
        build_default_camera_provider=_get("build_default_camera_provider"),
        append_shadow_evidence=None,
        stop_logger_for_context=_get("_stop_logger_for_context"),
        record_face_confirmed_false_positive=_get("_record_face_confirmed_false_positive"),
    )


def build_test_context(**overrides: Any) -> MonitorContext:
    """Create a MonitorContext suitable for unit testing.

    All fields default to no-ops so tests only need to override what they test.

    Example::

        ctx = build_test_context(
            read_session_state=lambda **kw: {"app_locked": True},
            expected_user_slug="alice",
        )
        result = _lock_app_state("sess-001", 90, 85.0, 90, ctx=ctx)
        assert ctx_calls["lock_attempted"] == 0  # idempotency guard fired
    """
    defaults = MonitorContext()
    for key, value in overrides.items():
        if hasattr(defaults, key):
            setattr(defaults, key, value)
    return defaults
