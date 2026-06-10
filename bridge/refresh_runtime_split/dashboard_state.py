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

def emit_controls_changed(self, *, runtime_changed: bool = False, profile_changed: bool = False, controls_changed: bool = True) -> None:
    if runtime_changed:
        self.runtimeStateChanged.emit()
    if profile_changed:
        self.profileChanged.emit()
    effective_signal = getattr(self, "effectiveProductionReadyChanged", None)
    if effective_signal is not None and hasattr(effective_signal, "emit"):
        effective_signal.emit()
    if profile_changed:
        signal = getattr(self, "autoEnrollmentChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        readiness_signal = getattr(self, "modelReadinessChanged", None)
        if readiness_signal is not None and hasattr(readiness_signal, "emit"):
            readiness_signal.emit()
    if controls_changed:
        self.controlsChanged.emit()

def emit_all(self) -> None:
    self.authenticatedChanged.emit()
    self.currentUserChanged.emit()
    self.profileChanged.emit()
    self.sessionsChanged.emit()
    auto_enrollment_signal = getattr(self, "autoEnrollmentChanged", None)
    if auto_enrollment_signal is not None and hasattr(auto_enrollment_signal, "emit"):
        auto_enrollment_signal.emit()
    readiness_signal = getattr(self, "modelReadinessChanged", None)
    if readiness_signal is not None and hasattr(readiness_signal, "emit"):
        readiness_signal.emit()
    self.runtimeStateChanged.emit()
    self.statusChanged.emit()
    self.controlsChanged.emit()
    self.onboardingChanged.emit()
    self.shadowChanged.emit()
    effective_signal = getattr(self, "effectiveProductionReadyChanged", None)
    if effective_signal is not None and hasattr(effective_signal, "emit"):
        effective_signal.emit()
    deep_runtime_signal = getattr(self, "deepRuntimeChanged", None)
    if deep_runtime_signal is not None and hasattr(deep_runtime_signal, "emit"):
        deep_runtime_signal.emit()
    dashboard_signal = getattr(self, "dashboardStateChanged", None)
    if dashboard_signal is not None and hasattr(dashboard_signal, "emit"):
        dashboard_signal.emit()
    passcode_signal = getattr(self, "appPasscodeChanged", None)
    if passcode_signal is not None and hasattr(passcode_signal, "emit"):
        passcode_signal.emit()
    hybrid_direct_signal = getattr(self, "hybridDirectChanged", None)
    if hybrid_direct_signal is not None and hasattr(hybrid_direct_signal, "emit"):
        hybrid_direct_signal.emit()

def desired_refresh_interval_ms(self) -> int:
    facade = _facade()
    if bool(getattr(self, "_background", False)) and not self._current_user:
        return facade.REFRESH_BACKGROUND_MS
    if not self._current_user:
        return facade.REFRESH_IDLE_AUTH_MS
    state = self._runtime_state if isinstance(getattr(self, "_runtime_state", None), dict) else {}
    flow = self._session_flow(state)
    if (
        getattr(self, "_pending_logger_start", False)
        or self._pending_monitor_start
        or bool(getattr(self, "_boot_autostart_pending", False))
        or bool(getattr(self, "_training_in_progress", False))
        or bool(getattr(self, "_shadow_worker_running", False))
        or bool(getattr(self, "_dashboard_full_history_refresh_inflight", False))
        or flow != "idle"
    ):
        return facade.REFRESH_ACTIVE_MS
    if bool(getattr(self, "_history_sync_pending", False)):
        hard_deadline = float(getattr(self, "_history_sync_hard_deadline", 0.0) or getattr(self, "_history_sync_deadline", 0.0) or 0.0)
        if hard_deadline and facade.time.time() < hard_deadline:
            return self.HISTORY_POST_STOP_REFRESH_MS
        self._history_sync_pending = False
        self._history_sync_deadline = 0.0
        self._history_sync_hard_deadline = 0.0
        self._history_sync_status = "archive_unavailable"
        self._history_sync_warning = "history_archive_unavailable"
    if bool(getattr(self, "_background", False)):
        return facade.REFRESH_BACKGROUND_MS
    return facade.REFRESH_IDLE_SIGNED_MS

def update_refresh_timer(self, *, force: bool = False) -> None:
    if not is_qt_main_thread(self):
        dispatch_to_qt_thread(
            self,
            lambda: update_refresh_timer(self, force=force),
            target_action="update_refresh_timer",
        )
        return
    facade = _facade()
    timer = getattr(self, "_timer", None)
    if timer is None:
        return
    desired = int(self._desired_refresh_interval_ms())
    if not force:
        try:
            if int(timer.interval()) == desired:
                return
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    try:
        timer.setInterval(desired)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        facade.LOGGER.warning("Failed updating refresh timer interval to %s ms", desired)

def invalidate_dashboard_snapshot_cache(self) -> None:
    self._dashboard_snapshot_cache = {}
    self._dashboard_snapshot_user = ""
    self._dashboard_snapshot_cached_at = 0.0
    if hasattr(self, "_dashboard_snapshot_result_lock"):
        with self._dashboard_snapshot_result_lock:
            self._dashboard_snapshot_result = None
            self._dashboard_snapshot_result_user = ""
            self._dashboard_snapshot_result_error = ""
            self._dashboard_snapshot_result_completed_at = 0.0
    self._dashboard_snapshot_refresh_inflight = False
    self._dashboard_snapshot_refresh_user = ""
    self._dashboard_snapshot_refresh_force = False
    self._dashboard_snapshot_refresh_requested_at = 0.0
    self._dashboard_snapshot_refresh_generation = int(getattr(self, "_dashboard_snapshot_refresh_generation", 0) or 0) + 1
    self._dashboard_snapshot_result_generation = 0
    self._dashboard_snapshot_applied_generation = 0
    if hasattr(self, "_dashboard_full_history_result_lock"):
        with self._dashboard_full_history_result_lock:
            self._dashboard_full_history_result = None
            self._dashboard_full_history_result_user = ""
            self._dashboard_full_history_result_error = ""
            self._dashboard_full_history_result_completed_at = 0.0
            self._dashboard_full_history_result_generation = 0
    if hasattr(self, "_dashboard_full_history_cache"):
        self._dashboard_full_history_cache = {}
        self._dashboard_full_history_user = ""
        self._dashboard_full_history_cached_at = 0.0
        self._dashboard_full_history_loading = False
        self._dashboard_full_history_refresh_inflight = False
        self._dashboard_full_history_refresh_user = ""
        self._dashboard_full_history_generation = int(getattr(self, "_dashboard_full_history_generation", 0) or 0) + 1
        self._dashboard_full_history_applied_generation = 0
    self._last_dashboard_snapshot_timing = {}
    set_dashboard_state(self, loading=False, updating=False, stale=False)

def dashboard_snapshot_ttl_sec(self) -> float:
    if bool(getattr(self, "_history_sync_pending", False)):
        return 0.0
    if bool(getattr(self, "_background", False)) and not self._current_user:
        return self.DASHBOARD_SNAPSHOT_BACKGROUND_SEC
    if bool(getattr(self, "_training_in_progress", False)):
        return 12.0
    state = self._runtime_state if isinstance(getattr(self, "_runtime_state", None), dict) else {}
    flow = self._session_flow(state)
    if bool(getattr(self, "_pending_logger_start", False)) or bool(getattr(self, "_pending_monitor_start", False)) or bool(getattr(self, "_shadow_worker_running", False)) or flow != "idle":
        return self.DASHBOARD_SNAPSHOT_ACTIVE_SEC
    if bool(getattr(self, "_background", False)):
        return self.DASHBOARD_SNAPSHOT_BACKGROUND_SEC
    return self.DASHBOARD_SNAPSHOT_IDLE_SEC


def _state_number(state: Dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        try:
            value = state.get(key)
            if value is None or value == "":
                continue
            return float(value)
        except Exception:
            continue
    return float(default)


def _protected_warning_alert_suppressed(self: Any, state: Dict[str, Any], signature: str) -> bool:
    """Keep protected-warning states in the dashboard without external popups.

    Hotfix 7W: warning/suspicious states can refresh every second while the
    monitor waits for follow-up evidence.  Spawning a Windows PowerShell tray
    notification for those states creates noisy popups and measurable UI work.
    Only the final protected_forced_stop path may emit a blocking UI dialog.
    """
    self._last_alert_signature = signature
    self._last_alert_at = time.time()
    self._last_soft_warning_alert_suppressed_at = self._last_alert_at
    self._last_soft_warning_alert_code = str(state.get("alert_code") or "").strip().lower()
    return True

def maybe_emit_feedback_prompt(self) -> None:
    state = self._runtime_state if isinstance(getattr(self, "_runtime_state", None), dict) else {}
    prompt = state.get("feedback_prompt") if isinstance(state.get("feedback_prompt"), dict) else {}
    if not prompt or not bool(prompt.get("pending")):
        return

    # LOCK-FACE-01: product warning feedback is audit-only and must never be a
    # pre-lock decision gate.  The only modal prompt allowed through this signal
    # is the post-lock classification prompt after a real lock/unlock cycle.
    if str(prompt.get("kind") or "").strip() != "post_lock_confirmation":
        return
    if not (bool(state.get("postLockConfirmationPending")) and bool(state.get("postLockConfirmationPromptAfterUnlock"))):
        return

    # ── Incident-level dedup (Phase 4) ────────────────────────────────────────
    # Use the stable postLockConfirmationEventId as the primary dedup key.
    # Falls back to (session_id, token) for older state that predates Phase 4.
    # The _last_feedback_prompt_signature is an in-memory guard that prevents
    # the 1-second refresh loop from re-emitting for the same incident within
    # a single app session.  postLockConfirmationAnswered=True is the
    # persistent guard (it lives in session_state) that survives refresh cycles.
    if bool(state.get("postLockConfirmationAnswered")):
        return

    event_id = str(state.get("postLockConfirmationEventId") or "").strip()
    token = str(prompt.get("token") or prompt.get("event_id") or "").strip()
    session_id = str(prompt.get("session_id") or state.get("postLockConfirmationEventSessionId") or state.get("session_id") or "").strip()

    # Primary dedup: stable event-id from session_state
    if event_id and event_id == str(getattr(self, "_last_feedback_prompt_signature", "") or ""):
        return
    # Fallback dedup: (session_id, token) for legacy state
    fallback_sig = f"{session_id}:{token}:post_lock_confirmation"
    if not event_id and fallback_sig == str(getattr(self, "_last_feedback_prompt_signature", "") or ""):
        return

    # Record the emitted signature before firing — the signal handler may
    # close the dialog synchronously so we must be idempotent by the time
    # the handler runs.
    self._last_feedback_prompt_signature = event_id or fallback_sig
    signal = getattr(self, "warningFeedbackPromptRequested", None)
    if signal is not None and hasattr(signal, "emit"):
        payload = dict(prompt)
        payload["kind"] = "post_lock_confirmation"
        payload.setdefault("session_id", session_id)
        payload.setdefault("event_id", event_id)
        payload.setdefault("decision_reason_code", state.get("postLockConfirmationReason") or state.get("runtime_diagnostic_code") or "")
        payload.setdefault("decision", state.get("decision") or "")
        payload.setdefault("risk", int(state.get("postLockConfirmationRisk") or state.get("risk") or 0))
        signal.emit(payload)

def handle_state_alerts(self) -> None:
    facade = _facade()
    if not self._current_user or not self._runtime_state:
        return
    flow = self._session_flow(self._runtime_state)
    session_id = self._runtime_state.get("session_id") or ""
    decision = str(self._runtime_state.get("decision") or "").lower()
    alert_code = str(self._runtime_state.get("alert_code") or "")
    diag = str(self._runtime_state.get("runtime_diag_code") or self._runtime_state.get("runtime_diagnostic_code") or self._runtime_state.get("decision_reason_code") or "")
    risk_bucket = int(max(
        _state_number(self._runtime_state, "decision_risk", "risk", "display_risk", "action_risk"),
        _state_number(self._runtime_state, "avg_risk", "average_risk", "rolling_avg_risk", "risk_avg"),
    ) // 10) * 10
    signature = f"{session_id}:{decision}:{alert_code}:{diag}:{risk_bucket}:{flow}"
    if signature == self._last_alert_signature and time.time() - float(getattr(self, "_last_alert_at", 0.0) or 0.0) < 30.0:
        return
    if flow == "protected_warning":
        # Hotfix 7W: protected_warning is a dashboard status only.  Do not
        # spawn PowerShell tray notifications or modal dialogs for suspicious
        # warnings; confirmed lock handling remains in protected_forced_stop.
        _protected_warning_alert_suppressed(self, self._runtime_state, signature)
        maybe_emit_feedback_prompt(self)
        return
    elif flow == "protected_forced_stop":
        self._last_alert_signature = signature
        self._last_alert_at = time.time()
        title_key = str(self._runtime_state.get("alert_title_key") or "alert_lock_title")
        default_message_key = "alert_screen_lock_msg" if self._runtime_state.get("screen_locked") else "alert_lock_msg"
        message_key = str(self._runtime_state.get("alert_message_key") or default_message_key)
        self.dialogMessage.emit(self._t(title_key), self._t(message_key), "error")
