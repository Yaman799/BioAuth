"""Extracted implementation section for `bridge/refresh_runtime_helpers.py`."""
from __future__ import annotations
from importlib import import_module
import logging
import re
import time
from typing import Any, Dict, Optional
from bridge import session_runtime_helpers as _process_helpers
from bridge.shared import read_session_state
from bridge.qt_thread_dispatch import dispatch_to_qt_thread, is_qt_main_thread
from bioauth_runtime import runtime_boundary

def _debug_refresh_request(self, message: str, *, reason: str, coalesced: bool, followup: bool = False, level: str = "debug") -> None:
    debug = getattr(self, "_debug_trace", None)
    if not callable(debug):
        return
    debug(
        "refresh",
        message,
        payload={
            "refresh_reason": _safe_refresh_reason(reason),
            "refresh_coalesced": bool(coalesced),
            "refresh_inflight": bool(getattr(self, "_refresh_inflight", False)),
            "refresh_followup_scheduled": bool(followup or getattr(self, "_refresh_followup_scheduled", False)),
        },
        level=level,
    )

def _run_debounced_refresh(self) -> None:
    _ensure_refresh_request_state(self)
    reason = _safe_refresh_reason(getattr(self, "_refresh_debounce_reason", "") or "debounced")
    force = bool(getattr(self, "_refresh_debounce_force", False))
    self._refresh_debounce_pending = False
    self._refresh_debounce_reason = ""
    self._refresh_debounce_force = False
    request_refresh(self, reason=reason, force=force, _from_debounce=True)

def request_refresh(self, reason: str = "manual", force: bool = False, *, _from_debounce: bool = False) -> None:
    safe_reason = _safe_refresh_reason(reason)
    if not is_qt_main_thread(self):
        dispatch_to_qt_thread(
            self,
            lambda: request_refresh(self, reason=safe_reason, force=force, _from_debounce=_from_debounce),
            target_action="request_refresh",
        )
        return
    facade = _facade()
    _ensure_refresh_request_state(self)

    if bool(getattr(self, "_refresh_inflight", False)):
        self._refresh_requested = True
        self._refresh_requested_force = bool(getattr(self, "_refresh_requested_force", False) or force)
        self._refresh_requested_reason = _merge_refresh_reason(getattr(self, "_refresh_requested_reason", ""), safe_reason)
        self._refresh_followup_scheduled = True
        _debug_refresh_request(self, "refresh request coalesced while active", reason=self._refresh_requested_reason, coalesced=True, followup=True)
        return

    critical = _is_critical_refresh(safe_reason, bool(force))
    if not critical and not _from_debounce:
        if bool(getattr(self, "_refresh_debounce_pending", False)):
            self._refresh_debounce_reason = _merge_refresh_reason(getattr(self, "_refresh_debounce_reason", ""), safe_reason)
            self._refresh_debounce_force = bool(getattr(self, "_refresh_debounce_force", False) or force)
            _debug_refresh_request(self, "refresh request coalesced in debounce window", reason=self._refresh_debounce_reason, coalesced=True)
            return
        self._refresh_debounce_pending = True
        self._refresh_debounce_reason = safe_reason
        self._refresh_debounce_force = bool(force)
        debounce_ms = int(getattr(self, "REFRESH_REQUEST_DEBOUNCE_MS", 35) or 0)
        qtimer = getattr(facade, "QTimer", None)
        single_shot = getattr(qtimer, "singleShot", None) if qtimer is not None else None
        if callable(single_shot) and debounce_ms > 0:
            single_shot(debounce_ms, lambda: _run_debounced_refresh(self))
            return
        _run_debounced_refresh(self)
        return

    _perform_refresh_now(self, reason=safe_reason, force=bool(force), coalesced=bool(_from_debounce))

def refresh_now(self) -> None:
    request_refresh(self, reason="refreshNow", force=True)

def update_runtime_background_state(self) -> None:
    """Refresh backend/runtime-only state without dashboard snapshot or QML signals.

    The main refresh timer must continue while the window is hidden because
    logger/monitor readiness, passive enrollment finalization, shadow processing,
    alerts, and resume-after-unlock logic depend on a fresh runtime view. This
    helper intentionally avoids profile/session/dashboard snapshot work and does
    not emit display-only signals.
    """
    if not getattr(self, "_current_user", None):
        if isinstance(getattr(self, "_runtime_state", None), dict) and self._runtime_state:
            self._runtime_state = {}
        return
    state = self._active_state_for_current_user()
    runtime_view = self._build_runtime_state_view(state if isinstance(state, dict) else {})
    runtime_changed = runtime_view != (self._runtime_state if isinstance(getattr(self, "_runtime_state", None), dict) else {})
    if runtime_changed:
        self._runtime_state = runtime_view
        refresh_deep_runtime = getattr(self, "_refresh_deep_runtime_state", None)
        if callable(refresh_deep_runtime):
            try:
                refresh_deep_runtime()
            except Exception:
                _LOGGER.warning("Deep runtime state refresh failed during background runtime update; preserving previous runtime state.", exc_info=True)

def _commercial_runtime_fenced(self) -> bool:
    state = getattr(self, "_runtime_state", {})
    state = state if isinstance(state, dict) else {}
    try:
        flow = str(self._session_flow(state) or "")
    except Exception:
        flow = ""
    return runtime_boundary.is_commercial_protected_runtime(state, flow=flow)

def _perform_refresh_now(self, *, reason: str = "manual", force: bool = False, coalesced: bool = False) -> None:
    facade = _facade()
    _ensure_refresh_request_state(self)
    safe_reason = _safe_refresh_reason(reason)
    _begin_refresh_cycle(self, safe_reason, coalesced)
    debug = getattr(self, "_debug_trace", None)
    started_at = facade.time.time()
    phase_ms: Dict[str, int] = {}
    refresh_error = ""
    try:
        dashboard_visible = is_dashboard_visible(self)
        if self._current_user:
            _refresh_visible_or_background_state(self, dashboard_visible, phase_ms)
            if _commercial_runtime_fenced(self):
                _run_commercial_refresh_display(self, dashboard_visible, phase_ms)
            else:
                _run_non_commercial_refresh_side_effects(self, dashboard_visible, phase_ms)
        else:
            started = facade.time.time()
            self._refresh_shadow_status()
            _mark_phase(facade, phase_ms, "shadow_status_ms", started)
    except Exception as exc:
        refresh_error = _safe_dashboard_error_text(exc)
        if callable(debug):
            debug("refresh", "refreshNow failed", payload={"error": refresh_error, "refresh_reason": safe_reason}, level="error")
        raise
    finally:
        _finish_refresh_cycle(self, started_at, safe_reason, refresh_error, phase_ms, coalesced)

def _begin_refresh_cycle(self, safe_reason: str, coalesced: bool) -> None:
    self._refresh_inflight = True
    self._refresh_active_reason = safe_reason
    self._refresh_active_coalesced = bool(coalesced)
    self._refresh_followup_scheduled = False

def _refresh_visible_or_background_state(self, dashboard_visible: bool, phase_ms: Dict[str, int]) -> None:
    facade = _facade()
    started = facade.time.time()
    if dashboard_visible:
        self._update_dashboard()
        _mark_phase(facade, phase_ms, "dashboard_ms", started)
        return
    update_runtime_background_state(self)
    _mark_phase(facade, phase_ms, "runtime_background_state_ms", started)

def _run_commercial_refresh_display(self, dashboard_visible: bool, phase_ms: Dict[str, int]) -> None:
    facade = _facade()
    started = facade.time.time()
    self._handle_state_alerts()
    _mark_phase(facade, phase_ms, "alerts_ms", started)
    started = facade.time.time()
    # Hotfix 7W: auto-resume may be scheduled from here, but dashboard refresh
    # must not synchronously rebuild after spawning workers. The resume worker
    # requests a fresh update when the new session is ready, which avoids a
    # visible MainThread freeze after repeated lock/unlock cycles.
    self._maybe_resume_protection_after_unlock(self._runtime_state)
    _mark_phase(facade, phase_ms, "resume_ms", started)

def _finish_refresh_cycle(
    self,
    started_at: float,
    safe_reason: str,
    refresh_error: str,
    phase_ms: Dict[str, int],
    coalesced: bool,
) -> None:
    facade = _facade()
    self._update_refresh_timer()
    elapsed_ms = int(round((facade.time.time() - started_at) * 1000.0))
    set_dashboard_state(
        self,
        last_refresh_duration_ms=elapsed_ms,
        last_refresh_reason=safe_reason,
        last_refresh_error=refresh_error if refresh_error else None,
        completed_at=facade.time.time(),
    )
    followup_requested = bool(getattr(self, "_refresh_requested", False))
    _maybe_log_slow_refresh(self, elapsed_ms, safe_reason, phase_ms, coalesced, followup_requested)
    self._refresh_inflight = False
    self._refresh_active_reason = ""
    self._refresh_active_coalesced = False
    if followup_requested:
        self._refresh_requested = False
        self._refresh_requested_force = False
        self._refresh_requested_reason = ""
        request_refresh(self, reason="followup", force=True)

def _maybe_log_slow_refresh(
    self,
    elapsed_ms: int,
    safe_reason: str,
    phase_ms: Dict[str, int],
    coalesced: bool,
    followup_requested: bool,
) -> None:
    debug = getattr(self, "_debug_trace", None)
    if not callable(debug) or elapsed_ms < 200:
        return
    state = self._runtime_state if isinstance(getattr(self, "_runtime_state", None), dict) else {}
    payload = {
        "elapsed_ms": elapsed_ms,
        "flow": self._session_flow(state),
        "training": bool(getattr(self, "_training_in_progress", False)),
        "status": str(getattr(self, "_status_message", "") or ""),
        "refresh_reason": safe_reason,
        "refresh_coalesced": bool(coalesced or followup_requested),
        "refresh_inflight": True,
        "refresh_followup_scheduled": followup_requested,
        "dashboard_visible": bool(is_dashboard_visible(self)),
        "commercial_runtime_fenced": _commercial_runtime_fenced(self),
        "phase_ms": dict(phase_ms),
    }
    timing = getattr(self, "_last_dashboard_snapshot_timing", {})
    if isinstance(timing, dict):
        payload.update(timing)
    debug("refresh", "Slow refresh cycle completed", payload=payload, level="warn")

def _run_non_commercial_refresh_side_effects(self, dashboard_visible: bool, phase_ms: Dict[str, int]) -> None:
    if _commercial_runtime_fenced(self):
        return
    facade = _facade()
    recovered = _recover_passive_finalization(self, phase_ms)
    promoted = _run_auto_promotion(self, dashboard_visible, recovered, phase_ms)
    started = facade.time.time()
    protection_started = self._maybe_autostart_protection()
    _mark_phase(facade, phase_ms, "autostart_ms", started)
    if protection_started:
        return
    flags = _run_noncommercial_bootstrap(self, dashboard_visible, recovered, phase_ms)
    _run_noncommercial_shadow_session(self, recovered, flags, phase_ms)
    _refresh_noncommercial_shadow_status(self, phase_ms)
    started = facade.time.time()
    self._handle_state_alerts()
    _mark_phase(facade, phase_ms, "alerts_ms", started)
