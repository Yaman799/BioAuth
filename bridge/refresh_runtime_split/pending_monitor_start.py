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

def _recover_passive_finalization(self, phase_ms: Dict[str, int]) -> bool:
    if _commercial_runtime_fenced(self):
        return False
    facade = _facade()
    started = facade.time.time()
    recovered = False
    recovery = getattr(self, "_recover_stale_passive_auto_enrollment_finalization", None)
    if callable(recovery):
        recovered = bool(recovery(source="refresh"))
    _mark_phase(facade, phase_ms, "passive_finalization_recovery_ms", started)
    return recovered

def _run_auto_promotion(self, dashboard_visible: bool, recovered: bool, phase_ms: Dict[str, int]) -> bool:
    if _commercial_runtime_fenced(self):
        return False
    facade = _facade()
    started = facade.time.time()
    promoted = False
    auto_promotion = getattr(self, "_maybe_auto_promote_production", None)
    if callable(auto_promotion) and not recovered:
        promoted = bool(auto_promotion())
    _mark_phase(facade, phase_ms, "auto_promotion_ms", started)
    if promoted and dashboard_visible:
        started = facade.time.time()
        self._update_dashboard()
        _mark_phase(facade, phase_ms, "dashboard_after_auto_promotion_ms", started)
    return promoted

def _run_noncommercial_bootstrap(self, dashboard_visible: bool, recovered: bool, phase_ms: Dict[str, int]) -> Dict[str, bool]:
    if _commercial_runtime_fenced(self):
        return {"finalized": False, "shadow_started": False, "trained": False, "passive_started": False}
    finalized = _run_passive_finalizer(self, dashboard_visible, recovered, phase_ms)
    shadow_started = _run_shadow_evidence_bootstrap(self, finalized, recovered, phase_ms)
    trained = _run_auto_training(self, shadow_started, finalized, recovered, phase_ms)
    passive_started = _run_passive_auto_enrollment(self, finalized, shadow_started, trained, recovered, phase_ms)
    return {"finalized": finalized, "shadow_started": shadow_started, "trained": trained, "passive_started": passive_started}

def _run_passive_finalizer(self, dashboard_visible: bool, recovered: bool, phase_ms: Dict[str, int]) -> bool:
    if _commercial_runtime_fenced(self):
        return False
    facade = _facade()
    started = facade.time.time()
    finalizer = getattr(self, "_maybe_finalize_passive_auto_enrollment", None)
    finalized = bool(finalizer()) if callable(finalizer) and not recovered else False
    _mark_phase(facade, phase_ms, "passive_auto_finalizer_ms", started)
    if finalized and dashboard_visible:
        started = facade.time.time()
        self._update_dashboard()
        _mark_phase(facade, phase_ms, "dashboard_after_passive_finalizer_ms", started)
    return finalized

def _run_shadow_evidence_bootstrap(self, finalized: bool, recovered: bool, phase_ms: Dict[str, int]) -> bool:
    if _commercial_runtime_fenced(self):
        return False
    facade = _facade()
    started = facade.time.time()
    bootstrap = getattr(self, "_maybe_start_shadow_evidence_monitor", None)
    started_shadow = bool(bootstrap()) if callable(bootstrap) and not finalized and not recovered else False
    _mark_phase(facade, phase_ms, "shadow_evidence_bootstrap_ms", started)
    return started_shadow

def _run_auto_training(self, shadow_started: bool, finalized: bool, recovered: bool, phase_ms: Dict[str, int]) -> bool:
    if _commercial_runtime_fenced(self):
        return False
    facade = _facade()
    started = facade.time.time()
    auto_training = getattr(self, "_maybe_start_auto_training", None)
    allowed = not shadow_started and not finalized and not recovered
    trained = bool(auto_training()) if callable(auto_training) and allowed else False
    _mark_phase(facade, phase_ms, "auto_training_ms", started)
    return trained

def _run_passive_auto_enrollment(
    self,
    finalized: bool,
    shadow_started: bool,
    trained: bool,
    recovered: bool,
    phase_ms: Dict[str, int],
) -> bool:
    if _commercial_runtime_fenced(self):
        return False
    facade = _facade()
    started = facade.time.time()
    allowed = not finalized and not shadow_started and not trained and not recovered
    passive_started = _process_helpers.maybe_start_passive_auto_enrollment(self) if allowed else False
    _mark_phase(facade, phase_ms, "passive_auto_enrollment_ms", started)
    return bool(passive_started)

def _run_noncommercial_shadow_session(self, recovered: bool, flags: Dict[str, bool], phase_ms: Dict[str, int]) -> None:
    if _commercial_runtime_fenced(self):
        return
    facade = _facade()
    started = facade.time.time()
    if not recovered and not any(flags.values()):
        self._maybe_process_shadow_session()
    _mark_phase(facade, phase_ms, "shadow_session_ms", started)
    started = facade.time.time()
    self._maybe_process_shadow_backlog()
    _mark_phase(facade, phase_ms, "shadow_backlog_ms", started)

def _refresh_noncommercial_shadow_status(self, phase_ms: Dict[str, int]) -> None:
    if _commercial_runtime_fenced(self):
        return
    facade = _facade()
    started = facade.time.time()
    shadow_status = self._consume_shadow_status_result()
    if self._should_refresh_shadow_status():
        queued = self._queue_shadow_status_refresh(self._current_user["user_id"])
        if not queued and shadow_status is None:
            shadow_status = facade.get_shadow_status(self._current_user["user_id"])
            self._last_shadow_status_refresh_at = facade.time.time()
    if shadow_status is None:
        shadow_status = dict(self._shadow_status) if isinstance(getattr(self, "_shadow_status", None), dict) else {"phase": "collecting", "ready": False, "suggestion_pending": False}
    self._check_shadow_suggestion(shadow_status)
    self._refresh_shadow_status(shadow_status)
    _mark_phase(facade, phase_ms, "shadow_status_ms", started)

def _mark_phase(facade: Any, phase_ms: Dict[str, int], name: str, started_at: float) -> None:
    phase_ms[name] = int(round((facade.time.time() - started_at) * 1000.0))
