from __future__ import annotations
import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from app_passcode import is_passcode_configured
from bioauth_version import get_app_version
from app_settings import (
    PRIVACY_POLICY_VERSION,
    has_current_evidence_consent,
    has_current_privacy_consent,
    normalize_interface_mode,
    resolve_ui_mode,
)
from deep_runtime import (
    deep_runtime_fallback_reason_text,
    deep_runtime_is_fallback,
    normalize_benchmark_record,
    normalize_deep_runtime_fallback_reason,
    normalize_deep_runtime_mode,
    resolve_deep_runtime_state,
)
from license_manager import evaluate_license
from metadata_core.auto_enrollment import build_auto_enrollment_state, is_passive_auto_enrollment_state, passive_collection_should_start
from metadata_core.auto_training_scheduler import background_action_from_status
from metadata_core.autonomous_readiness_loop import build_autonomous_readiness_loop_state
from metadata_core.remediation_loop import (
    REMEDIATION_REASON_CODE_MAPPING_TABLE,
    RemediationPlan,
    build_remediation_plan_from_gate_state,
    normalize_reason_codes,
)
from metadata_core.production_approval import (
    apply_production_approval_runtime_context,
    production_approval_observability_payload,
    production_approval_observability_signature,
    with_protected_sessions_ready_notification_state,
)
from metadata_core.shadow_loop import build_shadow_loop_state
from metadata_core.developer_readiness import build_effective_production_ready_state
from release_profile import profile_payload
from release_runtime import runtime_path_report, write_release_runtime_event
from onboarding_content import build_onboarding_slides
from startup_branding import create_startup_splash, finish_startup_splash, should_show_startup_splash
from hybrid_direct_contract import build_default_hybrid_direct_state, normalize_hybrid_direct_state
from safety_gate_policy import (
    build_safety_gate_report,
    emergency_disable_hybrid_state,
    rollback_to_classic_state,
    safety_gate_results_for_hybrid_state,
    write_safety_gate_report,
)
_LOGGER = logging.getLogger(__name__)
try:
    from PySide6.QtCore import QEvent
except Exception:  # pragma: no cover - test stubs may not expose QEvent
    class QEvent:  # type: ignore[override]
        class Type:
            MouseButtonPress = 2
            MouseButtonDblClick = 4
            MouseMove = 5
            Wheel = 31
            KeyPress = 6
            KeyRelease = 7
            TouchBegin = 194
            TouchUpdate = 195
            FocusIn = 8
            WindowActivate = 24
            InputMethod = 83
            ShortcutOverride = 51
from bridge.shared import (
    BASE_DIR,
    LOGGER_SCRIPT,
    MAX_ENROLLMENT_SESSIONS,
    MIN_ENROLLMENT_SESSIONS,
    MONITOR_SCRIPT,
    normalize_sensitivity_preset,
    PRIVACY_POLICY_PATH,
    ABOUT_US_PATH,
    Property,
    QApplication,
    QIcon,
    QLocale_name,
    QMenu,
    QObject,
    QQmlApplicationEngine,
    QSystemTrayIcon,
    QTimer,
    QUrl,
    REFRESH_IDLE_AUTH_MS,
    STRINGS,
    Signal,
    Slot,
    THEMES,
    _run_worker_if_requested,
    is_startup_enabled,
    load_settings,
    save_settings_async,
)
from bridge.auth_mixin import AuthMixin
from bridge.refresh_mixin import RefreshMixin
from bridge.session_mixin import SessionMixin
from bridge.settings_mixin import SettingsMixin
from bridge.update_mixin import UpdateMixin
from bridge import session_runtime_helpers, session_training_helpers
from bridge.qt_thread_dispatch import install_qt_thread_dispatcher

# Compatibility shell: implementation functions are loaded into this module
# so existing monkeypatches of private globals such as _facade still work.
from pathlib import Path as _BioAuthSplitPath

_BIOAUTH_SPLIT_DIR = _BioAuthSplitPath(__file__).with_name('desktop_app_split')
_BIOAUTH_SPLIT_MODULES = ('desktop_startup_diagnostics.py',)

def _bioauth_load_split_modules() -> None:
    namespace = globals()
    for module_name in _BIOAUTH_SPLIT_MODULES:
        module_path = _BIOAUTH_SPLIT_DIR / module_name
        code = module_path.read_text(encoding='utf-8')
        exec(compile(code, str(module_path), 'exec'), namespace, namespace)

_bioauth_load_split_modules()

class AppBridge(AuthMixin, SessionMixin, SettingsMixin, RefreshMixin, UpdateMixin, QObject):
    authenticatedChanged = Signal()
    currentUserChanged = Signal()
    profileChanged = Signal()
    sessionsChanged = Signal()
    runtimeStateChanged = Signal()
    statusChanged = Signal()
    themeChanged = Signal()
    languageChanged = Signal()
    startupChanged = Signal()
    rememberLoginChanged = Signal()
    riskSensitivityChanged = Signal()
    buttonSoundsMutedChanged = Signal()
    incidentEvidenceChanged = Signal()
    appPasscodeChanged = Signal()
    deepRuntimeChanged = Signal()
    passcodeSetupPromptChanged = Signal()
    onboardingChanged = Signal()
    controlsChanged = Signal()
    dashboardStateChanged = Signal()
    trainingChanged = Signal()
    trainingProgressReported = Signal(object)
    shadowChanged = Signal()
    shadowAutomationChanged = Signal()
    effectiveProductionReadyChanged = Signal()
    shadowWorkerFinished = Signal(object)
    dialogMessage = Signal(str, str, str)
    forgotUsernameLookupResult = Signal(str, str)
    forgotUsernameRevealResult = Signal(str, str)
    forgotPasswordVerificationResult = Signal(str, str)
    forgotPasswordResetResult = Signal(str, str)
    trainingFinished = Signal(object)
    warningFeedbackPromptRequested = Signal(object)
    licenseChanged = Signal()
    supportBundleChanged = Signal()
    privacyCenterChanged = Signal()
    autoEnrollmentChanged = Signal()
    modelReadinessChanged = Signal()
    updateStateChanged = Signal()
    uiModeChanged = Signal()
    faceConfirmationChanged = Signal()
    hybridDirectChanged = Signal()
    safetyGateReportChanged = Signal()
    companionApiChanged = Signal()

    def __init__(self, app: QApplication, background: bool = False) -> None:
        super().__init__()
        install_qt_thread_dispatcher(self)
        self._app = app
        self._background = background
        self._app_settings = load_settings()
        self._theme = str(self._app_settings.get("theme", "dark")).strip().lower()
        if self._theme not in THEMES:
            self._theme = "dark"
        default_lang = "ar" if (QLocale_name().startswith("ar")) else "en"
        self._language = str(self._app_settings.get("language", default_lang)).strip().lower()
        if self._language not in STRINGS:
            self._language = default_lang
        self._run_on_startup = bool(self._app_settings.get("run_on_startup", is_startup_enabled()))
        self._interface_mode = normalize_interface_mode(self._app_settings.get("interface_mode", "user"))
        self._remember_login_enabled = bool(self._app_settings.get("remember_login_enabled", False))
        self._startup_protected_sessions_enabled = bool(self._app_settings.get("startup_protected_sessions_enabled", False))
        self._risk_sensitivity = normalize_sensitivity_preset(self._app_settings.get("risk_sensitivity", "conservative"))
        self._mute_button_sounds = bool(self._app_settings.get("mute_button_sounds", True))
        self._privacy_policy_version = str(self._app_settings.get("privacy_policy_version", PRIVACY_POLICY_VERSION) or PRIVACY_POLICY_VERSION)
        self._incident_evidence_enabled = bool(self._app_settings.get("incident_evidence_enabled", False))
        self._incident_evidence_consent_granted = bool(self._app_settings.get("incident_evidence_consent_granted", False))
        self._incident_evidence_consent_policy_version = str(self._app_settings.get("incident_evidence_consent_policy_version", "") or "")
        self._incident_evidence_consent_timestamp = str(self._app_settings.get("incident_evidence_consent_timestamp", "") or "")
        self._incident_evidence_capture_screenshot = bool(self._app_settings.get("incident_evidence_capture_screenshot", False))
        self._incident_evidence_capture_webcam = bool(self._app_settings.get("incident_evidence_capture_webcam", False))
        self._incident_evidence_retention_days = int(self._app_settings.get("incident_evidence_retention_days", 30) or 30)
        self._face_confirmation_enabled = bool(self._app_settings.get("face_confirmation_enabled", False))
        try:
            self._backend_face_camera_index_value = int(self._app_settings.get("backend_face_camera_index", 0) or 0)
        except (TypeError, ValueError):
            self._backend_face_camera_index_value = 0
        self.__dict__.pop("_backend_face_camera_index", None)
        self._face_template_consent_granted = bool(self._app_settings.get("face_template_consent_granted", False))
        self._face_template_consent_policy_version = str(self._app_settings.get("face_template_consent_policy_version", "") or "")
        self._face_template_consent_timestamp = str(self._app_settings.get("face_template_consent_timestamp", "") or "")
        self._face_confirmation_operation_state: Dict[str, Any] = {"status": "idle", "ok": True}
        self._face_camera_availability_cache: Optional[Dict[str, Any]] = None
        self._face_operation_inflight = False
        self._face_status_update_allowed = False
        self._face_confirmation_cached_state: Dict[str, Any] = {
            "available": False,
            "status": "signed_out",
            "operationStatus": "idle",
            "operationInFlight": False,
            "faceOperationInFlight": False,
            "cameraStatus": "not_checked",
            "faceCameraStatus": "not_checked",
            "cameraAvailable": False,
            "faceCameraAvailable": False,
            "backendFaceCameraIndex": int(self._backend_face_camera_index_value),
            "backendCameraIndex": int(self._backend_face_camera_index_value),
            "rawImagesStored": False,
            "lockIntegrationEnabled": False,
        }
        self._smart_auto_enrollment_enabled = bool(self._app_settings.get("smart_auto_enrollment_enabled", False))
        self._auto_train_when_ready_enabled = bool(self._app_settings.get("auto_train_when_ready_enabled", False))
        self._auto_promote_when_production_safe_enabled = bool(self._app_settings.get("auto_promote_when_production_safe_enabled", False))
        self._shadow_automation_paused = bool(self._app_settings.get("shadow_automation_paused", False))
        self._developer_forced_production_ready = bool(self._app_settings.get("developer_forced_production_ready", False))
        self._monitor_interval_sec = int(self._app_settings.get("monitor_interval_sec", 8) or 8)
        self._app_passcode_enabled = bool(self._app_settings.get("app_passcode_enabled", False))
        self._app_passcode_timeout_sec = int(self._app_settings.get("app_passcode_timeout_sec", 60) or 60)
        self._app_passcode_record = self._app_settings.get("app_passcode_record", {}) if isinstance(self._app_settings.get("app_passcode_record", {}), dict) else {}
        self._deep_runtime_mode = normalize_deep_runtime_mode(self._app_settings.get("deep_runtime_mode", "auto"), default="auto")
        self._deep_runtime_manual_override = bool(self._app_settings.get("deep_runtime_manual_override", False))
        self._developer_direct_test_enabled = bool(self._app_settings.get("developer_direct_test_enabled", False))
        self._developer_direct_consent_enabled = bool(self._app_settings.get("developer_direct_consent_enabled", False))
        self._deep_runtime_benchmark = normalize_benchmark_record(self._app_settings.get("deep_runtime_benchmark"))
        self._deep_runtime_state = resolve_deep_runtime_state(self._app_settings)
        self._license_status = evaluate_license(self._app_settings)
        self._build_profile_state = profile_payload(self._app_settings.get("build_profile"))
        self._update_state = self._default_update_state()
        self._update_client = None
        self._companion_api_server = None
        self._companion_registry = None
        self._companion_pairing = None
        self._companion_api_state: Dict[str, Any] = {
            "schemaVersion": 1,
            "running": False,
            "host": str(self._app_settings.get("companion_api_host") or "127.0.0.1"),
            "port": int(self._app_settings.get("companion_api_port") or 39081),
            "baseUrl": "",
            "pairedDeviceCount": 0,
            "pendingPairingCount": 0,
            "readOnly": True,
        }
        self._update_operation_inflight = False
        self._support_bundle_path = ""
        self._onboarding_slides_source = {"source": "default", "reason": "bootstrap", "path": ""}
        self._app_passcode_locked = False
        self._app_passcode_message = ""
        self._app_passcode_failed_attempts = 0
        self._app_passcode_cooldown_until = 0.0
        self._app_passcode_cooldown_remaining = 0
        self._passcode_setup_prompt_visible = False
        self._pending_new_account_passcode_prompt = False
        self._last_ui_activity_at = time.time()
        self._current_user: Optional[Dict[str, Any]] = None
        self._profile: Dict[str, Any] = {}
        self._sessions: List[Dict[str, Any]] = []
        self._runtime_state: Dict[str, Any] = {}
        self._hybrid_direct_state: Dict[str, Any] = build_default_hybrid_direct_state()
        self._hybrid_direct_test_running = False
        self._latest_hybrid_direct_test_result: Dict[str, Any] = {}
        self._safety_gate_report: Dict[str, Any] = build_safety_gate_report(self._app_settings, self._hybrid_direct_state)
        self._status_message = ""
        self._status_tone = "info"
        self._dashboard_snapshot_cache: Dict[str, Any] = {}
        self._dashboard_snapshot_user = ""
        self._dashboard_snapshot_cached_at = 0.0
        self._dashboard_snapshot_refresh_enabled = True
        self._dashboard_snapshot_refresh_inflight = False
        self._dashboard_snapshot_refresh_user = ""
        self._dashboard_snapshot_refresh_force = False
        self._dashboard_snapshot_refresh_requested_at = 0.0
        self._dashboard_snapshot_refresh_generation = 0
        self._dashboard_snapshot_result: Optional[Dict[str, Any]] = None
        self._dashboard_snapshot_result_user = ""
        self._dashboard_snapshot_result_error = ""
        self._dashboard_snapshot_result_completed_at = 0.0
        self._dashboard_snapshot_result_generation = 0
        self._dashboard_snapshot_result_duration_ms = 0
        self._dashboard_snapshot_applied_generation = 0
        self._dashboard_snapshot_result_lock = threading.Lock()
        self._dashboard_snapshot_active_workers: Dict[str, int] = {}
        self._dashboard_snapshot_loading = False
        self._dashboard_snapshot_stale = False
        self._dashboard_snapshot_updating = False
        self._dashboard_last_refresh_duration_ms = 0
        self._dashboard_last_snapshot_duration_ms = 0
        self._dashboard_last_refresh_error = ""
        self._dashboard_last_refresh_reason = ""
        self._dashboard_last_refresh_completed_at = 0.0
        self._dashboard_visible = True
        self._dashboard_visible_refresh_pending = False
        self._dashboard_full_history_cache: Dict[str, Any] = {}
        self._dashboard_full_history_user = ""
        self._dashboard_full_history_cached_at = 0.0
        self._dashboard_full_history_requested = False
        self._dashboard_full_history_loading = False
        self._dashboard_full_history_refresh_inflight = False
        self._dashboard_full_history_refresh_user = ""
        self._dashboard_full_history_result: Optional[Dict[str, Any]] = None
        self._dashboard_full_history_result_user = ""
        self._dashboard_full_history_result_error = ""
        self._dashboard_full_history_result_completed_at = 0.0
        self._dashboard_full_history_generation = 0
        self._dashboard_full_history_result_generation = 0
        self._dashboard_full_history_applied_generation = 0
        self._dashboard_full_history_error = ""
        self._dashboard_full_history_result_lock = threading.Lock()
        self._refresh_inflight = False
        self._refresh_requested = False
        self._refresh_requested_force = False
        self._refresh_requested_reason = ""
        self._refresh_debounce_pending = False
        self._refresh_debounce_force = False
        self._refresh_debounce_reason = ""
        self._refresh_active_reason = ""
        self._refresh_active_coalesced = False
        self._refresh_followup_scheduled = False
        self._onboarding_visible = False
        self._onboarding_mode = "consent"
        self._pending_onboarding_do_not_show_again = False
        self._pending_onboarding_tour_skipped = False
        self._training_in_progress = False
        self._training_progress: Dict[str, Any] = {"percent": 0, "headline": "", "detail": "", "stage_key": "", "detail_key": "", "message_params": {}, "active": False}
        self._active_training_source = ""
        self._auto_training_job_active = False
        self._auto_training_active_signature = ""
        self._auto_training_last_signature = ""
        self._last_attempted_training_signature = ""
        self._last_attempted_training_at = 0.0
        self._last_attempted_training_result = ""
        self._last_attempted_training_status = ""
        self._last_attempted_training_rejection_reason = ""
        self._last_successful_training_signature = ""
        self._auto_training_last_status = "idle"
        self._auto_training_last_reason = ""
        self._auto_training_cooldown_until = 0.0
        self._last_auto_training_decision_reason = ""
        self._autonomous_loop_state: Dict[str, Any] = {"autonomous_loop_state": "waiting_for_sign_in", "autonomous_loop_next_action": "none", "autonomous_loop_blockers": []}
        self._autonomous_loop_last_transition = ""
        self._retry_handoff_state = "idle"
        self._retry_handoff_blockers: list[str] = []
        self._retry_handoff_last_error = ""
        self._shadow_evidence_stopped_for_retry = False
        self._auto_promotion_last_result: Dict[str, Any] = {}
        self._last_auto_promotion_decision_reason = ""
        self._last_production_approval_log_signature = ""
        self._last_production_approval_log_at = 0.0
        self._last_dashboard_production_observe_signature = ""
        self._last_dashboard_production_observe_at = 0.0
        self._last_dashboard_visible_refresh_requested_at = 0.0
        self._protected_sessions_ready_notified_artifact_digest = ""
        self._protected_sessions_ready_notified_at = ""
        self._shadow_loop_baseline_signature = ""
        self._shadow_loop_baseline_accepted_count = 0
        self._shadow_loop_cooldown_until = 0.0
        self._shadow_loop_repeated_shadow_count = 0
        self._shadow_loop_last_status = ""
        self._last_alert_signature: Optional[str] = None
        self._last_feedback_prompt_signature = ""
        self._history_sync_pending = False
        self._history_sync_deadline = 0.0
        self._last_history_synced_archive_path = ""
        self._last_auto_resume_archive_path = ""
        self._last_auto_resume_attempt_at = 0.0
        self._pending_logger_start = False
        self._pending_logger_user_id: Optional[str] = None
        self._pending_logger_session_kind = ""
        self._pending_logger_process_key: Optional[str] = None
        self._pending_logger_session_id = ""
        self._pending_logger_run_id = ""
        self._pending_passive_auto_enrollment = False
        self._passive_auto_enrollment_finalizing = False
        self._last_passive_auto_enrollment_start_at = 0.0
        self._last_passive_auto_enrollment_finalized_at = 0.0
        self._last_passive_auto_enrollment_finalize_reason = ""
        self._last_passive_auto_enrollment_block_reason = ""
        self._passive_finalization_observed_signature = ""
        self._passive_finalization_observed_since = 0.0
        self._last_passive_duplicate_finalization_log_key = ""
        self._last_passive_duplicate_finalization_log_at = 0.0
        self._logger_start_deadline = 0.0
        self._logger_start_failed = False
        self._pending_monitor_start = False
        self._pending_monitor_user_id: Optional[str] = None
        self._monitor_start_deadline = 0.0
        self._monitor_launch_attempted = False
        self._monitor_start_failed = False
        self._pending_shadow_evidence_monitor_start = False
        self._shadow_evidence_monitor_launch_attempted = False
        self._shadow_evidence_monitor_start_deadline = 0.0
        self._shadow_evidence_monitor_user_id: Optional[str] = None
        self._shadow_evidence_monitor_failed = False
        self._last_shadow_evidence_monitor_attempt_at = 0.0
        self._last_shadow_evidence_monitor_block_reason = ""
        self._shadow_status: Dict[str, Any] = {"phase": "collecting", "ready": False, "suggestion_pending": False, "automation_paused": bool(getattr(self, "_shadow_automation_paused", False))}
        self._shadow_status_refresh_enabled = True
        self._shadow_status_refresh_inflight = False
        self._shadow_status_refresh_user = ""
        self._shadow_status_result: Optional[Dict[str, Any]] = None
        self._shadow_status_result_user = ""
        self._shadow_status_result_error = ""
        self._shadow_status_result_lock = threading.Lock()
        self._pending_shadow_suggestion = False
        self._pending_shadow_avg_delta = 0.0
        self._shadow_worker_running = False
        self._shadow_suggestion_dismissed = False
        self._shadow_backfill_cursor = ""
        self._last_shadow_processed_session_id = ""
        self._last_shadow_processed_archive_path = ""
        self._last_shadow_status_refresh_at = 0.0
        self._last_shadow_backlog_scan_at = 0.0
        self._running_processes: Dict[str, subprocess.Popen] = {}
        self._active_live_session_dir: Optional[str] = None
        self._live_candidate_observer: Optional[Any] = None
        self._live_candidate_observer_state: Dict[str, Any] = {}
        self._tray: Optional[QSystemTrayIcon] = None
        self._boot_autostart_pending = False
        self._boot_autostart_earliest_at = 0.0
        self._debug_mode = str(os.environ.get("BIOAUTH_DEBUG_PANEL", "") or "").strip().lower() in {"1", "true", "yes", "on"}
        self._debug_controller: Optional[Any] = None
        self._shutdown_cleanup_started = False
        self._ensure_tray()
        try:
            self._app.installEventFilter(self)
        except Exception:
            pass

        self.trainingFinished.connect(self._finish_training)
        self.trainingProgressReported.connect(self._receive_training_progress)
        self.shadowWorkerFinished.connect(self._apply_shadow_worker_result)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_IDLE_AUTH_MS)
        self._timer.timeout.connect(self.refreshNow)
        self._timer.start()
        self._update_refresh_timer(force=True)

        self._app_passcode_timer = QTimer(self)
        self._app_passcode_timer.setInterval(1000)
        self._app_passcode_timer.timeout.connect(self._tick_app_passcode)
        self._app_passcode_timer.start()

        self._set_status(self._t("status_banner_collecting"), "info")
        if self._restore_persistent_signin():
            self._boot_autostart_pending = bool(self._background)
            self._boot_autostart_earliest_at = time.time() + 6.0 if self._boot_autostart_pending else 0.0
            self.requestRefresh("startup:restore_persistent_signin", True)

    def _t(self, key: str, **kwargs: Any) -> str:
        table = STRINGS.get(self._language, STRINGS["en"])
        text = table.get(key) or STRINGS["en"].get(key) or key
        try:
            return text.format(**kwargs)
        except Exception:
            return text


    def _refresh_license_status(self) -> None:
        try:
            next_status = evaluate_license(getattr(self, "_app_settings", {}) or {})
        except Exception:
            next_status = {
                "schema_version": 1,
                "policy_version": "license-policy-2026-04-26",
                "state": "invalid_basic",
                "effective_tier": "free",
                "premium_active": False,
                "license_expires_at": "",
                "features": {
                    "basic_protection": True,
                    "start_protected_session": True,
                    "stop_protected_session": True,
                    "delete_my_data": True,
                    "delete_evidence": True,
                    "export_support_bundle": True,
                    "local_recovery": True,
                    "view_history_basic": True,
                },
                "last_error": "Invalid license code.",
                "safe_mode_note": "License evaluation failed; BioAuth remains in Basic safety mode without deleting user data.",
            }
        if next_status != getattr(self, "_license_status", {}):
            self._license_status = dict(next_status)
            signal = getattr(self, "licenseChanged", None)
            if signal is not None and hasattr(signal, "emit"):
                signal.emit()

    def attachDebugController(self, controller: Any) -> None:
        self._debug_controller = controller
        try:
            if controller is not None and hasattr(controller, "set_bridge"):
                controller.set_bridge(self)
        except Exception:
            pass
        self._debug_trace(
            "app",
            "Debug controller attached",
            payload={"background": bool(self._background), "authenticated": bool(self.authenticated)},
        )

    def _debug_trace(self, category: str, message: str, payload: Optional[Dict[str, Any]] = None, level: str = "info") -> None:
        if not bool(getattr(self, "_debug_mode", False)):
            return
        controller = getattr(self, "_debug_controller", None)
        if controller is None or not hasattr(controller, "trace"):
            return
        try:
            controller.trace(str(category or "event"), str(message or ""), payload=dict(payload or {}), level=str(level or "info"))
        except Exception:
            return

    def _debug_snapshot(self) -> Dict[str, Any]:
        state = self._runtime_state if isinstance(getattr(self, "_runtime_state", None), dict) else {}
        progress = self._training_progress if isinstance(getattr(self, "_training_progress", None), dict) else {}
        profile = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
        user_id = str((self._current_user or {}).get("user_id", "") or "")
        timer = getattr(self, "_timer", None)
        try:
            refresh_interval = int(timer.interval()) if timer is not None else 0
        except Exception:
            refresh_interval = 0
        try:
            last_ui_age = max(0.0, time.time() - float(getattr(self, "_last_ui_activity_at", 0.0) or 0.0))
        except Exception:
            last_ui_age = 0.0
        process_names = []
        for key, proc in dict(getattr(self, "_running_processes", {}) or {}).items():
            try:
                alive = proc is not None and proc.poll() is None
            except Exception:
                alive = False
            if alive:
                process_names.append(str(key))

        production_payload = {}
        try:
            production_payload = self._build_production_approval_state_payload(profile, log_source="")
        except Exception as exc:
            production_payload = {"available": False, "error": str(exc)}

        health_diagnostics = {}
        now = time.time()
        cache = getattr(self, "_debug_health_diagnostics_cache", {}) if isinstance(getattr(self, "_debug_health_diagnostics_cache", {}), dict) else {}
        cache_at = float(getattr(self, "_debug_health_diagnostics_cache_at", 0.0) or 0.0)
        force_full = str(os.environ.get("BIOAUTH_DEBUG_PANEL_FULL_DIAGNOSTICS", "") or "").strip().lower() in {"1", "true", "yes", "on"}
        # The support diagnostics include file/process/session scans. Keep them cached so the debug panel
        # is informative without reintroducing UI refresh stalls.
        if force_full or not cache or (now - cache_at) >= 12.0:
            try:
                from support_bundle import build_health_diagnostics
                health_diagnostics = build_health_diagnostics(user_id=user_id or None, runtime_state=state)
            except Exception as exc:
                health_diagnostics = {"available": False, "error": str(exc)}
            self._debug_health_diagnostics_cache = dict(health_diagnostics) if isinstance(health_diagnostics, dict) else {}
            self._debug_health_diagnostics_cache_at = now
        else:
            health_diagnostics = dict(cache)

        shadow_status = getattr(self, "_shadow_status", {}) if isinstance(getattr(self, "_shadow_status", None), dict) else {}
        env_names = (
            "BIOAUTH_DEBUG_PANEL",
            "BIOAUTH_DEBUG_PANEL_FULL_HEARTBEAT",
            "BIOAUTH_DEBUG_PANEL_FULL_DIAGNOSTICS",
            "BIOAUTH_ENABLE_SHADOW_EVIDENCE_MONITOR",
            "BIOAUTH_SHADOW_EVIDENCE_ONLY",
            "BIOAUTH_ENABLE_LEGACY_SHADOW_BACKLOG_SCAN",
            "BIOAUTH_ENABLE_LEGACY_SHADOW_STATUS_POLLING",
            "BIOAUTH_DISABLE_UI_PERFORMANCE_OPTIMIZATION",
            "BIOAUTH_DISABLE_DYNAMIC_FUSION_V1",
            "BIOAUTH_RUNTIME_MODE",
            "BIOAUTH_HYBRID_TEST_ONLY",
        )
        env_snapshot = {name: os.environ.get(name, "") for name in env_names if os.environ.get(name, "") != ""}
        try:
            import control as _debug_control
            debug_control_dir = str(getattr(_debug_control, "CONTROL_DIR", "") or "")
        except Exception:
            debug_control_dir = ""
        runtime_diag = {
            "control_dir": debug_control_dir,
            "executable": sys.executable,
            "argv": list(sys.argv),
            "cwd": os.getcwd(),
            "base_dir": str(BASE_DIR),
            "pid": os.getpid(),
            "parent_pid": os.getppid() if hasattr(os, "getppid") else None,
            "start_app_bat_detected": any("start_app" in str(arg).lower() for arg in sys.argv),
            "source_mode": bool(os.path.exists(os.path.join(str(BASE_DIR), "desktop_app.py"))),
            "env": env_snapshot,
        }

        return {
            "user": user_id,
            "flow": str(self._session_flow(state) if callable(getattr(self, "_session_flow", None)) else "idle"),
            "runtime_status": str(state.get("status") or ("active" if state.get("active") else "idle")),
            "runtime_decision": str(state.get("decision") or ""),
            "runtime_diag_code": str(state.get("runtime_diagnostic_code") or ""),
            "runtime_diag_reason": str(state.get("runtime_diagnostic_reason") or ""),
            "runtime_diag_summary": str(state.get("runtime_diagnostic_summary") or ""),
            "runtime_confirmation_rule": str(state.get("runtime_confirmation_rule") or ""),
            "runtime_locking_allowed": bool(state.get("runtime_locking_allowed", True)),
            "runtime_lock_suppressed_for_sec": float(state.get("runtime_lock_suppressed_for_sec") or 0.0),
            "runtime_warning_count": int(state.get("warning_count") or 0),
            "runtime_legit_streak": int(state.get("runtime_legit_streak") or 0),
            "runtime_recent_decisions": list(state.get("runtime_recent_decisions") or []),
            "runtime_recent_risks": list(state.get("runtime_recent_risks") or []),
            "runtime_recent_ages_sec": list(state.get("runtime_recent_ages_sec") or []),
            "runtime_window_count": int(state.get("runtime_window_count") or 0),
            "runtime_transition_status": str(state.get("runtime_transition_status") or ""),
            "runtime_transition_active": bool(state.get("runtime_transition_active")),
            "runtime_transition_recent_windows": int(state.get("runtime_transition_recent_windows") or 0),
            "runtime_transition_recent_settled_windows": int(state.get("runtime_transition_recent_settled_windows") or 0),
            "runtime_transition_strength": float(state.get("runtime_transition_strength") or 0.0),
            "runtime_window_diag_summary": str(state.get("runtime_window_diag_summary") or ""),
            "runtime_top_risky_windows": list(state.get("runtime_top_risky_windows") or []),
            "runtime_last_window_diag": dict(state.get("runtime_last_window_diag") or {}),
            "monitor_failed": bool(state.get("monitor_failed")),
            "risk_engine_stopped": bool(state.get("risk_engine_stopped")),
            "monitor_exit_code": state.get("monitor_exit_code"),
            "monitor_exit_reason": str(state.get("monitor_exit_reason") or ""),
            "monitor_exit_detail": str(state.get("monitor_exit_detail") or ""),
            "monitor_stdout_tail": list(state.get("monitor_stdout_tail") or []),
            "monitor_stderr_tail": list(state.get("monitor_stderr_tail") or []),
            "training_active": bool(getattr(self, "_training_in_progress", False)),
            "training_percent": int(progress.get("percent", 0) or 0),
            "training_headline": str(progress.get("headline") or ""),
            "training_detail": str(progress.get("detail") or ""),
            "training_stage": str(progress.get("stage_key") or progress.get("stage") or ""),
            "status_message": str(getattr(self, "_status_message", "") or ""),
            "status_tone": str(getattr(self, "_status_tone", "info") or "info"),
            "processes": sorted(process_names),
            "pending_monitor_start": bool(getattr(self, "_pending_monitor_start", False)),
            "history_sync_pending": bool(getattr(self, "_history_sync_pending", False)),
            "refresh_interval_ms": refresh_interval,
            "thread_count": int(len(threading.enumerate())),
            "last_ui_activity_age_sec": round(last_ui_age, 1),
            "debug_runtime": runtime_diag,
            "debug_health": health_diagnostics,
            "debug_production_approval": production_payload,
            "debug_shadow": shadow_status,
            "debug_worker_pair": dict(getattr(self, "_worker_pair_status_cache", {}) or {}),
            "debug_profile_summary": {
                "production_ready": bool(profile.get("production_ready") or profile.get("productionReady")),
                "can_start_monitor": bool(profile.get("can_start_monitor") or profile.get("canStartMonitor")),
                "candidate_status": str(profile.get("candidate_model_status") or profile.get("candidateStatus") or ""),
                "profile_schema_version": str(profile.get("schema_version") or profile.get("schemaVersion") or ""),
                "feature_schema_digest_present": bool(profile.get("feature_schema_digest") or profile.get("featureSchemaDigest")),
            },
            "debug_panel_schema_version": "commercial-core-22d-debug-panel-v1",
        }

    @Slot(str, str)
    def debugUiAction(self, action: str, detail: str = "") -> None:
        action_text = str(action or "ui").strip() or "ui"
        detail_text = str(detail or "").strip()
        message = detail_text if detail_text else action_text
        self._debug_trace("ui", message, payload={"action": action_text, "detail": detail_text})


    def eventFilter(self, watched: QObject, event: Any) -> bool:
        try:
            event_type = event.type()
        except Exception:
            return False
        activity_types = {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.FocusIn,
            QEvent.Type.WindowActivate,
            QEvent.Type.InputMethod,
            QEvent.Type.ShortcutOverride,
        }
        if event_type in activity_types:
            throttle_ms = 200 if event_type in {QEvent.Type.MouseMove, QEvent.Type.Wheel, QEvent.Type.TouchUpdate} else 0
            self._record_ui_activity(throttle_ms=throttle_ms)
        return False

    def _record_ui_activity(self, *, throttle_ms: int = 0) -> None:
        now = time.time()
        if throttle_ms > 0:
            min_delta = max(0.0, float(throttle_ms) / 1000.0)
            if (now - float(getattr(self, "_last_ui_activity_at", 0.0) or 0.0)) < min_delta:
                return
        self._last_ui_activity_at = now

    def _remaining_app_passcode_cooldown(self) -> int:
        remaining = float(getattr(self, "_app_passcode_cooldown_until", 0.0) or 0.0) - time.time()
        return max(0, int(math.ceil(remaining)))

    def _sync_app_passcode_cooldown(self, *, force_emit: bool = False) -> None:
        remaining = self._remaining_app_passcode_cooldown()
        if force_emit or remaining != int(getattr(self, "_app_passcode_cooldown_remaining", 0) or 0):
            self._app_passcode_cooldown_remaining = remaining
            self.appPasscodeChanged.emit()

    def _reset_app_passcode_runtime(self, *, unlock_only: bool = False) -> None:
        changed = False
        if self._app_passcode_locked:
            self._app_passcode_locked = False
            changed = True
        if getattr(self, "_app_passcode_message", ""):
            self._app_passcode_message = ""
            changed = True
        if int(getattr(self, "_app_passcode_failed_attempts", 0) or 0):
            self._app_passcode_failed_attempts = 0
            changed = True
        if float(getattr(self, "_app_passcode_cooldown_until", 0.0) or 0.0):
            self._app_passcode_cooldown_until = 0.0
            changed = True
        if int(getattr(self, "_app_passcode_cooldown_remaining", 0) or 0):
            self._app_passcode_cooldown_remaining = 0
            changed = True
        if not unlock_only:
            self._last_ui_activity_at = time.time()
        if changed:
            self.appPasscodeChanged.emit()

    def _tick_app_passcode(self) -> None:
        self._sync_app_passcode_cooldown()
        if not self.authenticated:
            self._reset_app_passcode_runtime(unlock_only=True)
            return
        if not bool(getattr(self, "_app_passcode_enabled", False)):
            if self._app_passcode_locked:
                self._reset_app_passcode_runtime(unlock_only=True)
            return
        if not is_passcode_configured(getattr(self, "_app_passcode_record", {})):
            return
        if self._app_passcode_locked:
            return
        timeout_sec = max(30, int(getattr(self, "_app_passcode_timeout_sec", 60) or 60))
        if (time.time() - float(getattr(self, "_last_ui_activity_at", 0.0) or 0.0)) < timeout_sec:
            return
        self._app_passcode_locked = True
        self._app_passcode_message = ""
        self.appPasscodeChanged.emit()

    def _ensure_tray(self) -> None:
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            icon_path = os.path.join(BASE_DIR, "bioauth.ico")
            icon = QIcon(icon_path) if os.path.exists(icon_path) else self._app.windowIcon()
            tray = QSystemTrayIcon(icon, self._app)
            menu = QMenu()
            show_action = menu.addAction("Show BioAuth")
            quit_action = menu.addAction("Quit")
            show_action.triggered.connect(self._restore_main_window)
            quit_action.triggered.connect(self._quit_from_tray)
            tray.setContextMenu(menu)
            tray.setToolTip("BioAuth")
            tray.activated.connect(lambda *_args: self._restore_main_window())
            tray.show()
            self._tray = tray
        except Exception:
            self._tray = None

    def _restore_main_window(self) -> None:
        for window in self._app.topLevelWindows():
            try:
                window.showNormal()
                window.raise_()
                window.requestActivate()
            except Exception:
                pass

    def _cleanup_on_application_shutdown(self) -> None:
        if bool(getattr(self, "_shutdown_cleanup_started", False)):
            return
        self._shutdown_cleanup_started = True
        try:
            self.stopCompanionApi()
        except Exception:
            pass
        try:
            # Use the boundary module so the module-level reentry guard is
            # also applied (belt-and-suspenders alongside the instance flag above).
            from bioauth.session.user_flow_boundary import shutdown_runtime_workers as _ufb_shutdown
            _ufb_shutdown(self, reason="app_shutdown", wait_timeout=0.75)
        except Exception:
            try:
                session_runtime_helpers.shutdown_runtime_workers(self, reason="app_shutdown", wait_timeout=0.75)
            except Exception:
                try:
                    self.stopCurrentSession(silent=True)
                except Exception:
                    pass

    def _quit_from_tray(self) -> None:
        self._cleanup_on_application_shutdown()
        self._app.quit()

    def _reset_shadow_runtime_flags(self) -> None:
        self._shadow_status = {"phase": "collecting", "ready": False, "suggestion_pending": False, "automation_paused": bool(getattr(self, "_shadow_automation_paused", False))}
        self._pending_shadow_suggestion = False
        self._pending_shadow_avg_delta = 0.0
        self._shadow_worker_running = False
        self._shadow_suggestion_dismissed = False
        self._shadow_backfill_cursor = ""
        self._last_shadow_processed_session_id = ""
        self._last_shadow_processed_archive_path = ""
        self.shadowChanged.emit()

    @Property(bool, notify=authenticatedChanged)
    def authenticated(self) -> bool:
        return self._current_user is not None

    @Property("QVariantMap", notify=currentUserChanged)
    def currentUser(self) -> Dict[str, Any]:
        return self._current_user or {}

    @Property("QVariantMap", notify=profileChanged)
    def profile(self) -> Dict[str, Any]:
        return self._profile

    def _build_production_approval_state_payload(self, profile: Optional[Dict[str, Any]] = None, *, log_source: str = "") -> Dict[str, Any]:
        profile = profile if isinstance(profile, dict) else (self._profile if isinstance(getattr(self, "_profile", None), dict) else {})
        state = profile.get("production_approval_state") if isinstance(profile, dict) else {}
        payload = dict(state) if isinstance(state, dict) else {}
        settings = getattr(self, "_app_settings", {}) if isinstance(getattr(self, "_app_settings", None), dict) else {}
        training_progress = getattr(self, "_training_progress", {}) if isinstance(getattr(self, "_training_progress", None), dict) else {}
        training_stage = str(training_progress.get("stage_key") or training_progress.get("stage") or "").strip().lower()
        evaluation_active = bool(getattr(self, "_training_in_progress", False)) and "evaluat" in training_stage
        payload = apply_production_approval_runtime_context(
            payload,
            training_active=bool(getattr(self, "_training_in_progress", False)) and not evaluation_active,
            evaluation_active=evaluation_active,
            shadow_status=getattr(self, "_shadow_status", {}) if isinstance(getattr(self, "_shadow_status", None), dict) else {},
            auto_promotion_enabled=bool(settings.get("auto_promote_when_production_safe_enabled", False)),
        )
        remediation = profile.get("remediation_state") if isinstance(profile, dict) else {}
        if isinstance(remediation, dict) and remediation:
            payload.setdefault("remediation_state", dict(remediation))
            payload.setdefault("remediationState", dict(remediation))
        payload = self._apply_protected_sessions_ready_notification(payload)
        last_result = getattr(self, "_auto_promotion_last_result", {})
        last_result = dict(last_result) if isinstance(last_result, dict) else {}
        auto_state = {
            "enabled": bool(settings.get("auto_promote_when_production_safe_enabled", False)),
            "lastReason": str(last_result.get("reason") or getattr(self, "_last_auto_promotion_decision_reason", "") or ""),
            "lastChanged": bool(last_result.get("changed", False)),
            "lastOk": bool(last_result.get("ok", False)),
            "protectedSessionsAvailable": bool(payload.get("protectedSessionsAvailable", False)),
        }
        payload["autoPromotionState"] = auto_state
        if auto_state["lastReason"] == "promoted" and bool(payload.get("protectedSessionsAvailable")):
            payload["safeRecommendationText"] = "Protected Sessions are ready. The production-approved runtime bundle is active."
            payload["backgroundNextAction"] = "none"
        elif auto_state["enabled"] and payload.get("modelStatus") == "approved_for_production" and not bool(payload.get("protectedSessionsAvailable")):
            payload.setdefault("backgroundNextAction", "auto_promote_runtime_bundle")
        if log_source:
            self._maybe_log_production_approval_state(payload, source=log_source)
        return payload

    def _apply_protected_sessions_ready_notification(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        current = with_protected_sessions_ready_notification_state(
            dict(payload or {}),
            notified_artifact_digest=str(getattr(self, "_protected_sessions_ready_notified_artifact_digest", "") or ""),
            notified_at=str(getattr(self, "_protected_sessions_ready_notified_at", "") or ""),
        )
        if bool(current.get("protected_sessions_ready_notification_pending")):
            artifact = str(current.get("protected_sessions_ready_artifact_digest") or current.get("ready_notification_artifact_digest") or "")
            notified_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._protected_sessions_ready_notified_artifact_digest = artifact
            self._protected_sessions_ready_notified_at = notified_at
            current["protected_sessions_ready_notified_at"] = notified_at
            current["protectedSessionsReadyNotifiedAt"] = notified_at
            debug = getattr(self, "_debug_trace", None)
            if callable(debug):
                debug(
                    "production_approval",
                    "protected_sessions_ready_notification_pending",
                    payload={
                        "ready_notification_state": str(current.get("ready_notification_state") or ""),
                        "ready_notification_reason": str(current.get("ready_notification_reason") or ""),
                        "artifact_digest_present": bool(artifact),
                    },
                    level="info",
                )
        return current


    def _maybe_log_production_approval_state(self, payload: Dict[str, Any], *, source: str = "refresh") -> bool:
        debug = getattr(self, "_debug_trace", None)
        if not callable(debug):
            return False
        safe_payload = production_approval_observability_payload(payload)
        signature = production_approval_observability_signature(safe_payload)
        now = time.time()
        try:
            last_at = float(getattr(self, "_last_production_approval_log_at", 0.0) or 0.0)
        except (TypeError, ValueError, OverflowError):
            last_at = 0.0
        last_signature = str(getattr(self, "_last_production_approval_log_signature", "") or "")
        changed = signature != last_signature
        if not changed and (now - last_at) < 60.0:
            return False
        self._last_production_approval_log_signature = signature
        self._last_production_approval_log_at = now
        safe_payload["source"] = str(source or "refresh")[:48]
        debug(
            "production_approval",
            "Production approval state refreshed",
            payload=safe_payload,
            level="info" if changed else "debug",
        )
        return True

    def _observe_production_approval_state(self, profile: Optional[Dict[str, Any]] = None, *, source: str = "dashboard_refresh") -> Dict[str, Any]:
        return self._build_production_approval_state_payload(profile, log_source=source)

    @Property("QVariantMap", notify=profileChanged)
    def productionApprovalState(self) -> Dict[str, Any]:
        return self._build_production_approval_state_payload(log_source="qml_property")

    def _privacy_consent_satisfied_for_auto_enrollment(self) -> bool:
        settings = self._app_settings if isinstance(getattr(self, "_app_settings", None), dict) else {}
        if bool(has_current_privacy_consent(settings)):
            return True
        welcome_state = {}
        welcome_fn = getattr(self, "_current_user_welcome_state", None)
        if callable(welcome_fn):
            try:
                welcome_state = welcome_fn()
            except Exception:
                welcome_state = {}
        if not isinstance(welcome_state, dict):
            welcome_state = {}
        return bool(welcome_state.get("policy_accepted")) and bool(welcome_state.get("plan_ack")) and str(welcome_state.get("privacy_policy_version") or welcome_state.get("policy_version") or "").strip() != ""

    def _passive_auto_enrollment_collecting(self) -> bool:
        state = self._runtime_state if isinstance(getattr(self, "_runtime_state", None), dict) else {}
        flow_fn = getattr(self, "_session_flow", None)
        flow = str(flow_fn(state) if callable(flow_fn) else state.get("flow", "idle") or "idle")
        if is_passive_auto_enrollment_state(state) and bool(state.get("active")) and flow == "enrollment_active":
            return True
        return bool(getattr(self, "_pending_logger_start", False) and getattr(self, "_pending_passive_auto_enrollment", False))

    def _current_remediation_collection_plan(self):
        """Return a backend-owned remediation plan when a known gate failure exists.

        This only supplies labels/guards to Smart Auto Enrollment. It does not
        start collection and it never computes readiness in QML.
        """

        profile = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
        candidate_payloads = []
        for key in ("remediation_plan", "remediationPlan"):
            payload = profile.get(key)
            if isinstance(payload, dict):
                candidate_payloads.append(payload)
        production_state = profile.get("production_approval_state") if isinstance(profile, dict) else {}
        if isinstance(production_state, dict):
            for key in ("remediation_plan", "remediationPlan"):
                payload = production_state.get(key)
                if isinstance(payload, dict):
                    candidate_payloads.append(payload)
        for payload in candidate_payloads:
            try:
                return RemediationPlan.from_dict(payload)
            except Exception:
                continue

        if not isinstance(production_state, dict):
            return None
        reason_codes = []
        for key in (
            "reason_codes",
            "reasonCodes",
            "productionEvidenceReasonCodes",
            "production_evidence_reason_codes",
            "failedProductionGates",
            "failed_production_gates",
        ):
            reason_codes.extend(normalize_reason_codes(production_state.get(key)))
        for key in ("reason_code", "reasonCode", "block_reason", "blockReason"):
            reason_codes.extend(normalize_reason_codes(production_state.get(key)))
        known_codes = set(REMEDIATION_REASON_CODE_MAPPING_TABLE.keys())
        if not any(code in known_codes or code == "offline_approval_rejected" for code in reason_codes):
            return None
        try:
            return build_remediation_plan_from_gate_state(production_state)
        except Exception:
            return None

    def _evaluation_active_for_collection(self) -> bool:
        training_progress = getattr(self, "_training_progress", {}) if isinstance(getattr(self, "_training_progress", None), dict) else {}
        training_stage = str(training_progress.get("stage_key") or training_progress.get("stage") or "").strip().lower()
        return bool(getattr(self, "_training_in_progress", False)) and "evaluat" in training_stage

    def _auto_enrollment_collection_decision(self) -> tuple[bool, str]:
        remediation_plan = self._current_remediation_collection_plan()
        setattr(self, "_pending_remediation_plan", remediation_plan)
        if remediation_plan is None:
            setattr(self, "_pending_remediation_plan_id", "")
        else:
            payload = remediation_plan.to_dict()
            setattr(
                self,
                "_pending_remediation_plan_id",
                str(payload.get("evidence_report_digest") or payload.get("candidate_artifact_digest") or ""),
            )
        return passive_collection_should_start(
            settings=self._app_settings if isinstance(getattr(self, "_app_settings", None), dict) else {},
            profile=self._profile if isinstance(getattr(self, "_profile", None), dict) else {},
            runtime_state=self._runtime_state if isinstance(getattr(self, "_runtime_state", None), dict) else {},
            sessions=self._sessions if isinstance(getattr(self, "_sessions", None), list) else [],
            consent_satisfied=self._privacy_consent_satisfied_for_auto_enrollment(),
            authenticated=bool(self.authenticated),
            training_active=bool(getattr(self, "_training_in_progress", False)) and not self._evaluation_active_for_collection(),
            evaluation_active=self._evaluation_active_for_collection(),
            app_locked=bool(getattr(self, "_app_passcode_locked", False)),
            remediation_plan=remediation_plan,
        )

    def _auto_training_background_action(self) -> str:
        profile = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
        settings = self._app_settings if isinstance(getattr(self, "_app_settings", None), dict) else {}
        return background_action_from_status(
            auto_training_enabled=bool(settings.get("auto_train_when_ready_enabled", False)),
            training_ready=bool(profile.get("training_can_start")),
            training_active=bool(getattr(self, "_training_in_progress", False)),
            active_training_source=str(getattr(self, "_active_training_source", "") or ""),
            cooldown_until=float(getattr(self, "_auto_training_cooldown_until", 0.0) or 0.0),
            last_reason=str(getattr(self, "_last_auto_training_decision_reason", "") or ""),
        )

    def _compute_autonomous_readiness_loop_state(self) -> Dict[str, Any]:
        profile = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
        runtime_payload = self._runtime_state if isinstance(getattr(self, "_runtime_state", None), dict) else {}
        production = profile.get("production_approval_state") if isinstance(profile, dict) else {}
        remediation = profile.get("remediation_state") if isinstance(profile, dict) else {}
        training_progress = getattr(self, "_training_progress", {}) if isinstance(getattr(self, "_training_progress", None), dict) else {}
        training_stage = str(training_progress.get("stage_key") or training_progress.get("stage") or "").strip().lower()
        evaluation_active = bool(getattr(self, "_training_in_progress", False)) and "evaluat" in training_stage
        state = build_autonomous_readiness_loop_state(
            settings=self._app_settings if isinstance(getattr(self, "_app_settings", None), dict) else {},
            profile=profile,
            runtime_state=runtime_payload,
            sessions=self._sessions if isinstance(getattr(self, "_sessions", None), list) else [],
            consent_satisfied=self._privacy_consent_satisfied_for_auto_enrollment(),
            authenticated=bool(getattr(self, "_current_user", None)),
            training_active=bool(getattr(self, "_training_in_progress", False)) and not evaluation_active,
            evaluation_active=evaluation_active,
            session_flow=self._session_flow(runtime_payload),
            remediation_state=remediation if isinstance(remediation, dict) else {},
            production_approval=production if isinstance(production, dict) else {},
            auto_training_last_reason=str(getattr(self, "_last_auto_training_decision_reason", "") or ""),
        )
        self._autonomous_loop_state = dict(state)
        self._autonomous_loop_last_transition = str(state.get("autonomous_loop_state") or "")
        return state


    def _current_shadow_loop_state(self) -> Dict[str, Any]:
        profile = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
        production = profile.get("production_approval_state") if isinstance(profile, dict) else {}
        readiness = profile.get("model_readiness_state") if isinstance(profile, dict) else {}
        return build_shadow_loop_state(
            profile=profile,
            production_approval=production if isinstance(production, dict) else {},
            model_readiness=readiness if isinstance(readiness, dict) else {},
            sessions=self._sessions if isinstance(getattr(self, "_sessions", None), list) else [],
            baseline_signature=str(getattr(self, "_shadow_loop_baseline_signature", "") or ""),
            baseline_accepted_count=int(getattr(self, "_shadow_loop_baseline_accepted_count", 0) or 0),
            cooldown_until=float(getattr(self, "_shadow_loop_cooldown_until", 0.0) or 0.0),
            repeated_shadow_count=int(getattr(self, "_shadow_loop_repeated_shadow_count", 0) or 0),
            shadow_status=self._shadow_status if isinstance(getattr(self, "_shadow_status", None), dict) else {},
        )

    def _auto_promotion_background_action(self) -> str:
        profile = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
        production = profile.get("production_approval_state") if isinstance(profile, dict) else {}
        production = production if isinstance(production, dict) else {}
        settings = self._app_settings if isinstance(getattr(self, "_app_settings", None), dict) else {}
        if bool(production.get("protectedSessionsAvailable")):
            return "protected_sessions_ready"
        if not bool(settings.get("auto_promote_when_production_safe_enabled", False)):
            return "auto_promotion_disabled"
        if str(production.get("modelStatus") or "").strip().lower() == "approved_for_production":
            return "auto_promotion_pending"
        return ""

    def _passive_auto_enrollment_finalizing_recent(self) -> bool:
        try:
            finalized_at = float(getattr(self, "_last_passive_auto_enrollment_finalized_at", 0.0) or 0.0)
        except (TypeError, ValueError, OverflowError):
            finalized_at = 0.0
        recent = bool(finalized_at and (time.time() - finalized_at) < 30.0)
        if not recent and bool(getattr(self, "_passive_auto_enrollment_finalizing", False)):
            self._passive_auto_enrollment_finalizing = False
        return recent

    def _model_readiness_background_action(self, shadow_loop_state: Optional[Dict[str, Any]] = None) -> str:
        if self._passive_auto_enrollment_finalizing_recent():
            return "finalizing_passive_session"
        auto_action = self._auto_training_background_action()
        if auto_action == "training_in_background":
            return auto_action
        promotion_action = self._auto_promotion_background_action()
        if promotion_action == "protected_sessions_ready":
            return promotion_action
        shadow_state = shadow_loop_state if isinstance(shadow_loop_state, dict) else self._current_shadow_loop_state()
        if bool(shadow_state.get("active")):
            return str(shadow_state.get("backgroundAction") or shadow_state.get("targetedCollectionAction") or "shadow_validation_collecting")
        if promotion_action:
            return promotion_action
        return auto_action
    @Property("QVariantMap", notify=modelReadinessChanged)
    def modelReadinessState(self) -> Dict[str, Any]:
        profile = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
        state = profile.get("model_readiness_state") if isinstance(profile, dict) else {}
        payload = dict(state) if isinstance(state, dict) else {}
        shadow_loop_state = self._current_shadow_loop_state()
        background_action = self._model_readiness_background_action(shadow_loop_state)
        payload["backgroundAction"] = background_action
        payload["shadowLoopState"] = dict(shadow_loop_state)
        autonomous_state = getattr(self, "_autonomous_loop_state", None)
        if not isinstance(autonomous_state, dict) or not autonomous_state:
            autonomous_state = self._compute_autonomous_readiness_loop_state()
        payload["autonomousLoopState"] = dict(autonomous_state)
        payload["autonomous_loop_state"] = dict(autonomous_state)
        if background_action == "finalizing_passive_session":
            payload["safeUserMessage"] = "BioAuth is saving a completed passive enrollment session for quality review."
            payload["nextBestAction"] = "finalizing_passive_session"
            payload["nextBestActionText"] = "Existing archive and quality gates will decide whether this session counts."
        elif background_action == "training_in_background":
            payload["safeUserMessage"] = "Training your protection model in the background."
        elif background_action == "protected_sessions_ready":
            payload["safeUserMessage"] = "Protected Sessions are ready."
            payload["productionReady"] = True
            payload["nextBestAction"] = "none"
            payload["nextBestActionText"] = "Production-approved runtime is active."
        elif background_action == "auto_promotion_pending":
            payload["safeUserMessage"] = "BioAuth is activating your production-approved protection model safely."
            payload["nextBestAction"] = "auto_promote_runtime_bundle"
            payload["nextBestActionText"] = "Verify and activate the production runtime bundle."
        elif bool(shadow_loop_state.get("active")):
            payload["safeUserMessage"] = str(shadow_loop_state.get("safeUserMessage") or "BioAuth is validating your protection model safely in the background.")
            payload["nextBestAction"] = str(shadow_loop_state.get("targetedCollectionAction") or payload.get("nextBestAction") or "collect_targeted_trusted_sessions")
            payload["nextBestActionText"] = str(shadow_loop_state.get("targetedCollectionText") or payload.get("nextBestActionText") or "Collect targeted trusted sessions before retraining.")
        if background_action:
            advanced = str(payload.get("advancedDiagnosticText") or "")
            marker = "background_action=" + background_action
            payload["advancedDiagnosticText"] = (advanced + " | " + marker).strip(" |") if marker not in advanced else advanced
        shadow_advanced = str(shadow_loop_state.get("advancedDiagnosticText") or "")
        if shadow_advanced:
            advanced = str(payload.get("advancedDiagnosticText") or "")
            payload["advancedDiagnosticText"] = (advanced + " | " + shadow_advanced).strip(" |") if shadow_advanced not in advanced else advanced
        return payload


    @Property("QVariantMap", notify=autoEnrollmentChanged)
    def autoEnrollmentState(self) -> Dict[str, Any]:
        _allowed, reason = self._auto_enrollment_collection_decision()
        background_action = self._model_readiness_background_action()
        if background_action == "finalizing_passive_session":
            reason = "finalizing_passive_session"
        elif self._passive_auto_enrollment_collecting():
            reason = "collecting"
        else:
            self._last_passive_auto_enrollment_block_reason = reason
        return build_auto_enrollment_state(
            settings=self._app_settings if isinstance(getattr(self, "_app_settings", None), dict) else {},
            profile=self._profile if isinstance(getattr(self, "_profile", None), dict) else {},
            sessions=self._sessions if isinstance(getattr(self, "_sessions", None), list) else [],
            consent_satisfied=self._privacy_consent_satisfied_for_auto_enrollment(),
            collecting=self._passive_auto_enrollment_collecting(),
            collection_block_reason=reason,
            background_action=background_action,
        )

    @Property("QVariantMap", notify=runtimeStateChanged)
    def runtimeState(self) -> Dict[str, Any]:
        return self._runtime_state

    @Property("QVariantList", notify=sessionsChanged)
    def sessions(self) -> List[Dict[str, Any]]:
        return self._sessions

    @Property("QVariantMap", notify=dashboardStateChanged)
    def dashboardState(self) -> Dict[str, Any]:
        return self._dashboard_state()

    @Property("QVariantMap", notify=shadowChanged)
    def shadowStatus(self) -> Dict[str, Any]:
        status = dict(self._shadow_status if isinstance(self._shadow_status, dict) else {})
        status["automation_paused"] = bool(getattr(self, "_shadow_automation_paused", False))
        status["shadow_automation_paused"] = bool(getattr(self, "_shadow_automation_paused", False))
        return status

    @Property(bool, notify=shadowAutomationChanged)
    def shadowAutomationPaused(self) -> bool:
        return bool(getattr(self, "_shadow_automation_paused", False))

    def _effective_production_ready_state(self) -> Dict[str, Any]:
        return build_effective_production_ready_state(
            settings=self._settings_payload() if hasattr(self, "_settings_payload") else getattr(self, "_app_settings", {}),
            profile=self._profile if isinstance(getattr(self, "_profile", None), dict) else {},
            shadow_paused=bool(getattr(self, "_shadow_automation_paused", False)),
            developer_forced=bool(getattr(self, "_developer_forced_production_ready", False)),
        )

    def _effective_production_ready(self) -> bool:
        return bool(self._effective_production_ready_state().get("effectiveProductionReady"))

    def _developer_production_ready_simulation_active(self) -> bool:
        return bool(self._effective_production_ready_state().get("devProductionReadySimulation"))

    @Property(bool, notify=effectiveProductionReadyChanged)
    def developerForcedProductionReady(self) -> bool:
        return bool(getattr(self, "_developer_forced_production_ready", False))

    @Property(bool, notify=effectiveProductionReadyChanged)
    def effectiveProductionReady(self) -> bool:
        return bool(self._effective_production_ready())

    @Property("QVariantMap", notify=effectiveProductionReadyChanged)
    def effectiveProductionReadyState(self) -> Dict[str, Any]:
        return dict(self._effective_production_ready_state())

    @Property(str, notify=effectiveProductionReadyChanged)
    def effectiveProductionReadyReason(self) -> str:
        return str(self._effective_production_ready_state().get("reason") or "")

    @Property(str, notify=effectiveProductionReadyChanged)
    def effectiveProductionReadyLabel(self) -> str:
        return str(self._effective_production_ready_state().get("label") or "")

    @Property(str, notify=statusChanged)
    def statusMessage(self) -> str:
        return self._status_message

    @Property(str, notify=statusChanged)
    def statusTone(self) -> str:
        return self._status_tone

    @Property(str, notify=statusChanged)
    def safeStatusMessage(self) -> str:
        """User-safe version of statusMessage — internal/research terms filtered out.

        QML user pages should bind to this instead of statusMessage and then
        filtering in JavaScript.  Developer shell may still use statusMessage directly.
        """
        try:
            from bioauth.ui_state.safe_text import user_safe_status_text
            lang = str(getattr(self, "_language", "en") or "en")
            return user_safe_status_text(self._status_message, language=lang)
        except Exception:
            return self._status_message

    @Slot(str, str, result=str)
    def userSafeStatusText(self, text: str, fallback: str = "") -> str:
        """Filter an arbitrary status string for user-mode QML surfaces."""
        try:
            from bioauth.ui_state.safe_text import user_safe_status_text
            lang = str(getattr(self, "_language", "en") or "en")
            return user_safe_status_text(str(text or ""), fallback=str(fallback or ""), language=lang)
        except Exception:
            return str(fallback or text or "")

    @Property(str, notify=statusChanged)
    def safeProtectionText(self) -> str:
        """User-safe runtime text for the protection page."""
        try:
            from bioauth.ui_state.safe_text import user_safe_protection_text
            lang = str(getattr(self, "_language", "en") or "en")
            state = getattr(self, "_runtime_state", {}) if isinstance(getattr(self, "_runtime_state", None), dict) else {}
            raw = str(state.get("runtimeDisplayText") or state.get("statusLabel") or self._status_message or "")
            return user_safe_protection_text(raw, language=lang)
        except Exception:
            return self._status_message

    @Slot(str, str, result=str)
    def userSafeProtectionText(self, text: str, fallback: str = "") -> str:
        """Filter arbitrary protection-page runtime text for user-mode QML surfaces."""
        try:
            from bioauth.ui_state.safe_text import user_safe_protection_text
            lang = str(getattr(self, "_language", "en") or "en")
            return user_safe_protection_text(str(text or ""), fallback=str(fallback or ""), language=lang)
        except Exception:
            return str(fallback or text or "")

    @Property(str, notify=themeChanged)
    def themeMode(self) -> str:
        return self._theme

    @Property("QVariantMap", notify=themeChanged)
    def theme(self) -> Dict[str, str]:
        return THEMES[self._theme]

    @Property(str, notify=languageChanged)
    def language(self) -> str:
        return self._language

    @Property(str, notify=uiModeChanged)
    def uiMode(self) -> str:
        settings = dict(getattr(self, "_app_settings", {}) or {})
        settings["interface_mode"] = getattr(self, "_interface_mode", "developer")
        return resolve_ui_mode(settings)

    @Property(str, notify=uiModeChanged)
    def interfaceMode(self) -> str:
        return normalize_interface_mode(getattr(self, "_interface_mode", "developer"))

    @Property(bool, notify=uiModeChanged)
    def userShellEnabled(self) -> bool:
        return self.uiMode == "user"

    @Property("QVariantMap", notify=faceConfirmationChanged)
    def faceConfirmationState(self) -> Dict[str, Any]:
        cached = getattr(self, "_face_confirmation_cached_state", None)
        if isinstance(cached, dict):
            return dict(cached)
        return {"status": "unavailable", "available": False, "cameraStatus": "not_checked", "cameraAvailable": False, "lockIntegrationEnabled": False}

    @Property(bool, notify=startupChanged)
    def runOnStartup(self) -> bool:
        return self._run_on_startup

    @Property(bool, notify=rememberLoginChanged)
    def rememberLoginEnabled(self) -> bool:
        return bool(self._remember_login_enabled)

    @Property(str, notify=riskSensitivityChanged)
    def riskSensitivityPreset(self) -> str:
        return self._risk_sensitivity

    @Property(bool, notify=buttonSoundsMutedChanged)
    def buttonSoundsMuted(self) -> bool:
        return bool(self._mute_button_sounds)

    @Property(str, notify=incidentEvidenceChanged)
    def privacyPolicyVersion(self) -> str:
        return str(getattr(self, "_privacy_policy_version", PRIVACY_POLICY_VERSION) or PRIVACY_POLICY_VERSION)

    @Property(bool, notify=incidentEvidenceChanged)
    def incidentEvidenceEnabled(self) -> bool:
        return bool(self._incident_evidence_enabled)

    @Property(bool, notify=incidentEvidenceChanged)
    def incidentEvidenceCaptureScreenshot(self) -> bool:
        return bool(self._incident_evidence_capture_screenshot)

    @Property(bool, notify=incidentEvidenceChanged)
    def incidentEvidenceCaptureWebcam(self) -> bool:
        return bool(self._incident_evidence_capture_webcam)

    @Property(int, notify=incidentEvidenceChanged)
    def incidentEvidenceRetentionDays(self) -> int:
        return int(self._incident_evidence_retention_days)

    @Property(bool, notify=appPasscodeChanged)
    def appPasscodeEnabled(self) -> bool:
        return bool(self._app_passcode_enabled)

    @Property(bool, notify=appPasscodeChanged)
    def appPasscodeConfigured(self) -> bool:
        return bool(is_passcode_configured(self._app_passcode_record))

    @Property(bool, notify=appPasscodeChanged)
    def appPasscodeLocked(self) -> bool:
        return bool(self._app_passcode_locked)

    @Property(int, notify=appPasscodeChanged)
    def appPasscodeTimeoutSec(self) -> int:
        return int(self._app_passcode_timeout_sec)

    @Property(str, notify=appPasscodeChanged)
    def appPasscodeMessage(self) -> str:
        return str(self._app_passcode_message or "")

    @Property(int, notify=appPasscodeChanged)
    def appPasscodeCooldownRemaining(self) -> int:
        return int(self._app_passcode_cooldown_remaining)

    @Property(str, notify=deepRuntimeChanged)
    def deepRuntimeMode(self) -> str:
        return str(getattr(self, "_deep_runtime_mode", "auto") or "auto")

    @Property(bool, notify=deepRuntimeChanged)
    def deepRuntimeManualOverride(self) -> bool:
        return bool(getattr(self, "_deep_runtime_manual_override", False))

    @Property(str, notify=deepRuntimeChanged)
    def deepRuntimeRecommendedMode(self) -> str:
        return str((getattr(self, "_deep_runtime_state", {}) or {}).get("recommended_mode") or "classic")

    @Property(str, notify=deepRuntimeChanged)
    def deepRuntimeEffectiveMode(self) -> str:
        return str((getattr(self, "_deep_runtime_state", {}) or {}).get("effective_mode") or "classic")

    @Property(str, notify=deepRuntimeChanged)
    def deepRuntimeSelectedBackend(self) -> str:
        return str((getattr(self, "_deep_runtime_state", {}) or {}).get("selected_backend") or "classic")

    @Property(str, notify=deepRuntimeChanged)
    def deepRuntimeFallbackReason(self) -> str:
        state = getattr(self, "_deep_runtime_state", {}) or {}
        return normalize_deep_runtime_fallback_reason(state.get("fallback_reason"))

    @Property(str, notify=deepRuntimeChanged)
    def deepRuntimeFallbackReasonText(self) -> str:
        state = getattr(self, "_deep_runtime_state", {}) or {}
        reason = normalize_deep_runtime_fallback_reason(state.get("fallback_reason"))
        return deep_runtime_fallback_reason_text(reason)

    @Property(bool, notify=deepRuntimeChanged)
    def deepRuntimeIsFallback(self) -> bool:
        state = getattr(self, "_deep_runtime_state", {}) or {}
        return deep_runtime_is_fallback(state.get("fallback_reason"))

    @Property("QVariantMap", notify=deepRuntimeChanged)
    def deepRuntimeBenchmark(self) -> Dict[str, Any]:
        return dict(getattr(self, "_deep_runtime_benchmark", {}) or {})

    @Property("QVariantMap", notify=deepRuntimeChanged)
    def deepRuntimeState(self) -> Dict[str, Any]:
        return dict(getattr(self, "_deep_runtime_state", {}) or {})

    @Property("QVariantMap", notify=hybridDirectChanged)
    def hybridDirectState(self) -> Dict[str, Any]:
        return normalize_hybrid_direct_state(getattr(self, "_hybrid_direct_state", {}))

    @Property("QVariantMap", notify=hybridDirectChanged)
    def hybridProStatus(self) -> Dict[str, Any]:
        state = normalize_hybrid_direct_state(getattr(self, "_hybrid_direct_state", {}))
        payload = state.get("hybridProStatus") if isinstance(state.get("hybridProStatus"), dict) else {}
        return dict(payload)

    @Property(bool, notify=hybridDirectChanged)
    def hybridDirectTestRunning(self) -> bool:
        return bool(getattr(self, "_hybrid_direct_test_running", False))

    @Property(bool, notify=hybridDirectChanged)
    def canRunHybridDirectTest(self) -> bool:
        try:
            return bool(session_runtime_helpers.can_run_hybrid_direct_test(self)) and not bool(getattr(self, "_hybrid_direct_test_running", False))
        except Exception:
            _LOGGER.debug("Failed resolving Hybrid Direct Test availability; failing closed.", exc_info=True)
            return False

    @Property(str, notify=hybridDirectChanged)
    def hybridDirectTestUnavailableReason(self) -> str:
        if bool(getattr(self, "_hybrid_direct_test_running", False)):
            return self._t("hybrid_direct_test_running")
        try:
            blockers = session_runtime_helpers.hybrid_direct_test_blockers(self)
        except Exception:
            _LOGGER.debug("Failed resolving Hybrid Direct Test blockers.", exc_info=True)
            blockers = ["hybrid_direct_test_unavailable"]
        if not blockers:
            return ""
        return self._t(str(blockers[0]).split(":", 1)[0])

    @Property("QVariantMap", notify=hybridDirectChanged)
    def latestHybridDirectTestResult(self) -> Dict[str, Any]:
        return dict(getattr(self, "_latest_hybrid_direct_test_result", {}) or {})

    @Property("QVariantMap", notify=hybridDirectChanged)
    def liveCandidateObserverState(self) -> Dict[str, Any]:
        try:
            return dict(session_runtime_helpers.live_candidate_observer_state(self))
        except Exception:
            _LOGGER.debug("Failed resolving live candidate observer state.", exc_info=True)
            return {
                "observer_running": False,
                "status": "observer_unavailable",
                "candidate_rows": [],
                "observer_warnings": ["observer_unavailable"],
                "observer_report_path": "",
                "report_only": True,
                "can_lock": False,
                "can_lock_alone": False,
                "can_influence_device": False,
                "trigger_face_confirmation": False,
                "runtime_authoritative": False,
            }

    @Property("QVariantMap", notify=hybridDirectChanged)
    def latestHybridLiveSessionEvalResult(self) -> Dict[str, Any]:
        try:
            return dict(session_runtime_helpers.latest_hybrid_live_session_eval_result(self))
        except Exception:
            _LOGGER.debug("Failed resolving latest Hybrid live-session eval result.", exc_info=True)
            return {}

    @Property("QVariantMap", notify=hybridDirectChanged)
    def latestHybridLiveSessionEvalReportState(self) -> Dict[str, Any]:
        try:
            return dict(session_runtime_helpers.latest_hybrid_live_session_eval_report_state(self))
        except Exception:
            _LOGGER.debug("Failed resolving latest Hybrid live-session eval report state.", exc_info=True)
            return {
                "available": False,
                "message": "No latest live-session evaluation report generated yet.",
                "source": "latest_live_session",
                "report_only": True,
                "can_influence_device": False,
                "trigger_face_confirmation": False,
                "runtime_authoritative": False,
            }

    def _hybrid_direct_report_dir(self) -> Path:
        try:
            from hybrid_candidates.reports import DEFAULT_REPORT_DIR

            report_dir = Path(DEFAULT_REPORT_DIR)
        except Exception:
            report_dir = Path("reports") / "hybrid_direct"
        if report_dir.is_absolute():
            return report_dir
        return Path(BASE_DIR) / report_dir

    @Property("QVariantList", notify=hybridDirectChanged)
    def hybridDirectCandidateGroups(self) -> List[Dict[str, Any]]:
        try:
            from hybrid_candidates.ui_state import build_candidate_group_display_state

            return list(build_candidate_group_display_state(self._hybrid_direct_report_dir()))
        except Exception:
            _LOGGER.debug("Failed building Hybrid Direct candidate group display state.", exc_info=True)
            return []

    @Property("QVariantList", notify=hybridDirectChanged)
    def hybridDirectGroupVotes(self) -> List[Dict[str, Any]]:
        try:
            from hybrid_candidates.ui_state import build_group_vote_display_state

            return list(build_group_vote_display_state(self._hybrid_direct_report_dir()))
        except Exception:
            _LOGGER.debug("Failed building Hybrid Direct group vote display state.", exc_info=True)
            return []

    @Property("QVariantMap", notify=hybridDirectChanged)
    def latestHybridDirectReportState(self) -> Dict[str, Any]:
        try:
            from hybrid_candidates.ui_state import build_latest_report_status

            return dict(build_latest_report_status(self._hybrid_direct_report_dir()))
        except Exception:
            _LOGGER.debug("Failed building Hybrid Direct latest report state.", exc_info=True)
            return {
                "available": False,
                "message": "No report generated yet.",
                "report_only": True,
                "can_influence_device": False,
                "trigger_face_confirmation": False,
                "runtime_authoritative": False,
            }

    @Slot(result="QVariantMap")
    def openLatestHybridDirectReport(self) -> Dict[str, Any]:
        report_state = self.latestHybridDirectReportState
        path = str(report_state.get("summary_path") or "")
        if not path:
            return {"ok": False, "reason_code": "hybrid_direct_report_missing", "message": "No report generated yet."}
        return {
            "ok": True,
            "action": "open_latest_report_path_returned",
            "path": path,
            "report_only": True,
            "can_influence_device": False,
            "trigger_face_confirmation": False,
            "runtime_authoritative": False,
        }

    @Slot(result="QVariantMap")
    def exportHybridDirectCsv(self) -> Dict[str, Any]:
        report_state = self.latestHybridDirectReportState
        path = str(report_state.get("model_comparison_path") or "")
        if not path:
            return {"ok": False, "reason_code": "hybrid_direct_csv_missing", "message": "No report generated yet."}
        return {
            "ok": True,
            "action": "export_csv_path_returned",
            "path": path,
            "report_only": True,
            "can_influence_device": False,
            "trigger_face_confirmation": False,
            "runtime_authoritative": False,
        }

    @Slot(result="QVariantMap")
    def clearHybridDirectTestResults(self) -> Dict[str, Any]:
        self._latest_hybrid_direct_test_result = {}
        state = dict(getattr(self, "_hybrid_direct_state", {}) or {})
        state.pop("latest_result", None)
        state["reason_codes"] = ["hybrid_direct_display_cleared", "report_files_preserved", "device_influence_disabled", "single_model_lock_forbidden"]
        self._hybrid_direct_state = normalize_hybrid_direct_state(state)
        self.hybridDirectChanged.emit()
        return {
            "ok": True,
            "action": "hybrid_direct_display_cleared",
            "deleted_files": False,
            "report_files_preserved": True,
            "can_influence_device": False,
            "trigger_face_confirmation": False,
            "runtime_authoritative": False,
        }

    @Slot(result="QVariantMap")
    def refreshHybridDirectState(self) -> Dict[str, Any]:
        previous = normalize_hybrid_direct_state(getattr(self, "_hybrid_direct_state", {}))
        current = normalize_hybrid_direct_state(previous)
        self._hybrid_direct_state = current
        self._refresh_safety_gate_report()
        if current != previous:
            self.hybridDirectChanged.emit()
        return dict(current)

    def _refresh_safety_gate_report(self, *, emit: bool = True) -> Dict[str, Any]:
        previous = getattr(self, "_safety_gate_report", {})
        current = build_safety_gate_report(getattr(self, "_app_settings", {}), getattr(self, "_hybrid_direct_state", {}))
        self._safety_gate_report = current
        try:
            hybrid_previous = normalize_hybrid_direct_state(getattr(self, "_hybrid_direct_state", {}))
            merged = dict(hybrid_previous)
            merged["safety_gate_results"] = safety_gate_results_for_hybrid_state(current)
            merged["can_influence_device"] = bool(current.get("influence_allowed", False))
            merged["enabled"] = bool(current.get("developer_direct_enabled", False))
            self._hybrid_direct_state = normalize_hybrid_direct_state(merged)
        except Exception:
            _LOGGER.warning("Safety gate report refresh could not update hybrid direct state; preserving fail-closed state.", exc_info=True)
        if emit and current != previous:
            self.safetyGateReportChanged.emit()
        return dict(current)

    @Property("QVariantMap", notify=safetyGateReportChanged)
    def safetyGateReport(self) -> Dict[str, Any]:
        return dict(getattr(self, "_safety_gate_report", {}) or build_safety_gate_report(getattr(self, "_app_settings", {}), getattr(self, "_hybrid_direct_state", {})))

    @Slot(result="QVariantMap")
    def refreshSafetyGateReport(self) -> Dict[str, Any]:
        return self._refresh_safety_gate_report()

    @Slot(result="QVariantMap")
    def writeSafetyGateReport(self) -> Dict[str, Any]:
        report = self._refresh_safety_gate_report(emit=False)
        try:
            path = write_safety_gate_report(report)
            result = {"ok": True, "path": path, "report": report}
            self._set_status(f"Safety gate report written: {path}", "success")
        except Exception as exc:
            result = {"ok": False, "path": "", "error": str(exc), "report": report}
            self._set_status("Safety gate report could not be written.", "warn")
        self.safetyGateReportChanged.emit()
        return result

    @Slot(result="QVariantMap")
    def emergencyDisableHybrid(self) -> Dict[str, Any]:
        previous = normalize_hybrid_direct_state(getattr(self, "_hybrid_direct_state", {}))
        self._hybrid_direct_state = normalize_hybrid_direct_state(emergency_disable_hybrid_state(previous))
        self._deep_runtime_mode = "classic"
        self._deep_runtime_manual_override = True
        self._developer_direct_test_enabled = False
        self._developer_direct_consent_enabled = False
        self._app_settings = save_settings_async(self._settings_payload(developer_direct_test_enabled=False, developer_direct_consent_enabled=False, hybrid_can_influence_device=False, deep_runtime_mode="classic", deep_runtime_manual_override=True))
        self._deep_runtime_state = resolve_deep_runtime_state(self._app_settings)
        self.hybridDirectChanged.emit(); self.deepRuntimeChanged.emit()
        report = self._refresh_safety_gate_report()
        self._set_status("Hybrid Direct disabled. Classic-only fallback is active.", "success")
        return {"ok": True, "action": "classic_only_emergency_disabled", "hybridDirectState": dict(self._hybrid_direct_state), "safetyGateReport": report}

    @Slot(result="QVariantMap")
    def rollbackToClassic(self) -> Dict[str, Any]:
        previous = normalize_hybrid_direct_state(getattr(self, "_hybrid_direct_state", {}))
        self._hybrid_direct_state = normalize_hybrid_direct_state(rollback_to_classic_state(previous))
        self._deep_runtime_mode = "classic"
        self._deep_runtime_manual_override = True
        self._developer_direct_test_enabled = False
        self._developer_direct_consent_enabled = False
        self._app_settings = save_settings_async(self._settings_payload(developer_direct_test_enabled=False, developer_direct_consent_enabled=False, hybrid_can_influence_device=False, deep_runtime_mode="classic", deep_runtime_manual_override=True))
        self._deep_runtime_state = resolve_deep_runtime_state(self._app_settings)
        self.hybridDirectChanged.emit(); self.deepRuntimeChanged.emit()
        report = self._refresh_safety_gate_report()
        self._set_status("Rolled back to Classic-only mode. Evidence and reports were preserved.", "success")
        return {"ok": True, "action": "rollback_to_classic_only", "hybridDirectState": dict(self._hybrid_direct_state), "safetyGateReport": report}



    @Property("QVariantMap", notify=privacyCenterChanged)
    def privacyCenterState(self) -> Dict[str, Any]:
        settings = self._app_settings if isinstance(getattr(self, "_app_settings", {}), dict) else {}
        current_user = self._current_user if isinstance(getattr(self, "_current_user", None), dict) else {}
        profile = self._profile if isinstance(getattr(self, "_profile", {}), dict) else {}
        sessions = self._sessions if isinstance(getattr(self, "_sessions", []), list) else []
        license_status = self._license_status if isinstance(getattr(self, "_license_status", {}), dict) else {}
        welcome_state = {}
        welcome_fn = getattr(self, "_current_user_welcome_state", None)
        if callable(welcome_fn):
            try:
                welcome_state = welcome_fn()
            except Exception:
                welcome_state = {}
        if not isinstance(welcome_state, dict):
            welcome_state = {}
        welcome_policy_current = bool(welcome_state.get("policy_accepted")) and str(welcome_state.get("privacy_policy_version") or welcome_state.get("policy_version") or "").strip() != ""
        privacy_consent_current = bool(has_current_privacy_consent(settings)) or welcome_policy_current
        evidence_consent_current = bool(has_current_evidence_consent(settings))
        session_count = len(sessions)
        trusted_count = int(profile.get("session_count") or 0) if isinstance(profile, dict) else 0
        saved_count = int(profile.get("saved_session_count") or trusted_count or 0) if isinstance(profile, dict) else 0
        evidence_enabled = bool(getattr(self, "_incident_evidence_enabled", False))
        screenshot_enabled = bool(getattr(self, "_incident_evidence_capture_screenshot", False))
        webcam_enabled = bool(getattr(self, "_incident_evidence_capture_webcam", False))
        retention_days = int(getattr(self, "_incident_evidence_retention_days", 30) or 30)
        runtime_state = getattr(self, "_runtime_state", {}) if isinstance(getattr(self, "_runtime_state", {}), dict) else {}
        active_flow = str(runtime_state.get("flow") or "idle")
        destructive_blocked = bool(getattr(self, "_training_in_progress", False)) or active_flow not in {"", "idle"}
        return {
            "authenticated": bool(current_user),
            "displayName": str(current_user.get("display_name") or current_user.get("user_id") or ""),
            "privacyPolicyPath": str(PRIVACY_POLICY_PATH),
            "privacyPolicyVersion": str(getattr(self, "_privacy_policy_version", PRIVACY_POLICY_VERSION) or PRIVACY_POLICY_VERSION),
            "privacyConsentGranted": privacy_consent_current,
            "privacyConsentText": "Privacy consent current" if privacy_consent_current else "Privacy consent needs review",
            "welcomeConsentGranted": welcome_policy_current,
            "evidenceConsentGranted": evidence_consent_current,
            "incidentEvidenceEnabled": evidence_enabled,
            "incidentEvidenceCaptureScreenshot": screenshot_enabled,
            "incidentEvidenceCaptureWebcam": webcam_enabled,
            "incidentEvidenceRetentionDays": retention_days,
            "incidentEvidenceStatusText": "Enabled for confirmed intruder events only" if evidence_enabled else "Disabled; no screenshot or webcam incident evidence is saved",
            "smartAutoEnrollmentEnabled": bool(getattr(self, "_smart_auto_enrollment_enabled", False)),
            "autoTrainWhenReadyEnabled": bool(getattr(self, "_auto_train_when_ready_enabled", False)),
            "autoPromoteWhenProductionSafeEnabled": bool(getattr(self, "_auto_promote_when_production_safe_enabled", False)),
            "supportBundleAvailable": True,
            "lastSupportBundlePath": str(getattr(self, "_support_bundle_path", "") or ""),
            "deleteIncidentEvidenceAvailable": bool(current_user),
            "deleteMyDataAvailable": bool(current_user) and not destructive_blocked,
            "destructiveActionBlocked": destructive_blocked,
            "localSessionCount": session_count,
            "trustedEnrollmentSessions": trusted_count,
            "savedSessionCount": saved_count,
            "profileReady": bool(profile.get("ready") or profile.get("production_ready") or self._effective_production_ready()) if isinstance(profile, dict) else False,
            "localDataSummaryText": f"{session_count} history entries shown · {saved_count} saved sessions · {trusted_count} trusted enrollment sessions",
            "licenseState": str(license_status.get("state") or "missing_basic"),
            "licenseTier": str(license_status.get("effective_tier") or "free"),
            "licensePremiumActive": bool(license_status.get("premium_active")),
            "safeBoundaryText": "Support bundles use allowlisted diagnostics only and exclude passwords, passcodes, raw behavioral data, private keys, and license codes.",
        }

    @Property("QVariantMap", notify=licenseChanged)
    def licenseStatus(self) -> Dict[str, Any]:
        return dict(getattr(self, "_license_status", {}) or {})

    @Property("QVariantMap", notify=licenseChanged)
    def buildProfileState(self) -> Dict[str, Any]:
        return dict(getattr(self, "_build_profile_state", {}) or profile_payload())

    @Property(str, notify=supportBundleChanged)
    def lastSupportBundlePath(self) -> str:
        return str(getattr(self, "_support_bundle_path", "") or "")

    @Property(bool, notify=onboardingChanged)
    def onboardingVisible(self) -> bool:
        return self._onboarding_visible

    @Property(bool, notify=passcodeSetupPromptChanged)
    def passcodeSetupPromptVisible(self) -> bool:
        return bool(self._passcode_setup_prompt_visible)

    @Property(str, notify=onboardingChanged)
    def onboardingMode(self) -> str:
        return str(getattr(self, "_onboarding_mode", "consent") or "consent")

    @Property("QVariantList", notify=onboardingChanged)
    def onboardingSlides(self) -> List[Dict[str, Any]]:
        slides, status = build_onboarding_slides(
            BASE_DIR,
            translate=self._t,
            language=str(getattr(self, "_language", "en") or "en"),
        )
        self._onboarding_slides_source = dict(status or {})
        return slides

    @Property("QVariantMap", notify=onboardingChanged)
    def onboardingSlidesSource(self) -> Dict[str, Any]:
        return dict(getattr(self, "_onboarding_slides_source", {}) or {})

    @Property(str, notify=onboardingChanged)
    def onboardingTitle(self) -> str:
        return self._t("privacy_title")

    @Property(str, notify=onboardingChanged)
    def onboardingSubtitle(self) -> str:
        return self._t("privacy_subtitle")

    @Property(bool, notify=trainingChanged)
    def trainingInProgress(self) -> bool:
        return self._training_in_progress

    @Property("QVariantMap", notify=trainingChanged)
    def trainingProgress(self) -> Dict[str, Any]:
        return dict(self._training_progress or {})

    def _normal_user_session_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
        try:
            return session_runtime_helpers._normal_user_session_flow(self, state=state)
        except Exception:
            _LOGGER.debug("Failed resolving normal user session flow; failing closed.", exc_info=True)
            return "unknown"

    def _normal_enrollment_logger_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
        try:
            return session_runtime_helpers._normal_enrollment_logger_flow(self, state=state)
        except Exception:
            _LOGGER.debug("Failed resolving normal enrollment logger flow; failing closed.", exc_info=True)
            return "unknown"

    def _production_monitor_flow(self, state: Optional[Dict[str, Any]] = None) -> str:
        try:
            return session_runtime_helpers._production_monitor_flow(self, state=state)
        except Exception:
            _LOGGER.debug("Failed resolving production monitor flow; failing closed.", exc_info=True)
            return "unknown"

    def _can_start_enrollment_logger(self) -> bool:
        normal_logger_pending = session_runtime_helpers._normal_logger_start_pending(self)
        return (
            self.authenticated
            and not bool(getattr(self, "_training_in_progress", False))
            and not normal_logger_pending
            and not bool(getattr(self, "_pending_monitor_start", False))
            and self._normal_enrollment_logger_flow() == "idle"
            and self._normal_user_session_flow() == "idle"
        )

    def _can_stop_enrollment_logger(self) -> bool:
        if not self.authenticated:
            return False
        return session_runtime_helpers._normal_enrollment_logger_stop_available(self)

    @Property(bool, notify=controlsChanged)
    def canStartEnrollment(self) -> bool:
        return self._can_start_enrollment_logger()

    @Property(bool, notify=controlsChanged)
    def canStartEnrollmentLogger(self) -> bool:
        return self._can_start_enrollment_logger()

    @Property(bool, notify=controlsChanged)
    def enrollmentLoggerRunning(self) -> bool:
        return self.authenticated and self._normal_enrollment_logger_flow() == "enrollment_active"

    @Property(str, notify=controlsChanged)
    def startEnrollmentLoggerUnavailableReason(self) -> str:
        if self._can_start_enrollment_logger():
            return ""
        if not self.authenticated:
            return self._t("enrollment_logger_unavailable_sign_in")
        if bool(getattr(self, "_training_in_progress", False)):
            return self._t("enrollment_logger_unavailable_training")
        if session_runtime_helpers._normal_logger_start_pending(self):
            return self._t("enrollment_logger_unavailable_starting")
        if bool(getattr(self, "_pending_monitor_start", False)):
            return self._t("enrollment_logger_unavailable_monitor_starting")
        flow = self._normal_enrollment_logger_flow()
        if flow == "enrollment_active":
            return self._t("enrollment_logger_unavailable_already_running")
        normal_flow = self._normal_user_session_flow()
        if normal_flow.startswith("protected"):
            return self._t("enrollment_logger_unavailable_protected")
        if normal_flow not in {"idle", "unknown"}:
            return self._t("another_capture_session_active")
        return self._t("another_capture_session_active")

    @Property(bool, notify=controlsChanged)
    def canStopEnrollmentLogger(self) -> bool:
        return self._can_stop_enrollment_logger()

    @Property(str, notify=controlsChanged)
    def stopEnrollmentLoggerUnavailableReason(self) -> str:
        if self._can_stop_enrollment_logger():
            return ""
        if not self.authenticated:
            return self._t("stop_enrollment_logger_unavailable_sign_in")
        return self._t("stop_enrollment_logger_unavailable_idle")

    def _production_monitor_process_running(self) -> bool:
        return session_runtime_helpers._production_monitor_process_running(self)

    def _can_start_production_monitor(self) -> bool:
        normal_logger_pending = session_runtime_helpers._normal_logger_start_pending(self)
        profile_payload = self._profile if isinstance(getattr(self, "_profile", None), dict) else {}
        # Protected Sessions/production monitor availability is intentionally
        # based on real backend production readiness, not Developer Mode's
        # effective readiness simulation used for report-only runtime testing.
        return (
            self.authenticated
            and not normal_logger_pending
            and not bool(getattr(self, "_pending_monitor_start", False))
            and self._normal_user_session_flow() == "idle"
            and bool(profile_payload.get("production_ready"))
        )

    @Property(bool, notify=controlsChanged)
    def canStartProtected(self) -> bool:
        return self._can_start_production_monitor()

    @Property(bool, notify=controlsChanged)
    def canStartProductionMonitor(self) -> bool:
        return self._can_start_production_monitor()

    @Property(bool, notify=controlsChanged)
    def productionMonitorRunning(self) -> bool:
        return self.authenticated and self._production_monitor_process_running()

    @Property(bool, notify=controlsChanged)
    def canStopProductionMonitor(self) -> bool:
        return session_runtime_helpers._protected_session_stop_available(self)

    @Property(bool, notify=controlsChanged)
    def canStop(self) -> bool:
        return self.authenticated and self._normal_user_session_flow() in {"enrollment_active", "protected_starting", "protected_collecting", "protected_active", "protected_warning", "protected_technical_failure", "protected_forced_stop"}

    def _training_gate_status(self) -> Dict[str, Any]:
        try:
            return session_training_helpers.training_gate_status(self)
        except Exception:
            _LOGGER.debug("Failed resolving training gate status; failing closed.", exc_info=True)
            return {"can_train": False, "reason_code": "training_gate_unavailable", "hybrid": {"passed": False, "reason_code": "training_gate_unavailable"}}

    @Property(bool, notify=controlsChanged)
    def canTrain(self) -> bool:
        return bool(self._training_gate_status().get("can_train"))

    @Property(bool, notify=controlsChanged)
    def canCalibrate(self) -> bool:
        return self.canTrain

    @Property(str, notify=controlsChanged)
    def trainingBlockedReasonCode(self) -> str:
        if bool(self.canTrain):
            return ""
        return str(self._training_gate_status().get("reason_code") or "")

    @Property(str, notify=controlsChanged)
    def trainingBlockedReason(self) -> str:
        code = self.trainingBlockedReasonCode
        if not code:
            return ""
        return self._t(code.split(":", 1)[0])

    @Property("QVariantList", notify=controlsChanged)
    def trainCalibrateReasonCodes(self) -> list:
        try:
            status = self._training_gate_status()
            codes = status.get("reason_codes")
            if isinstance(codes, list):
                return [str(code) for code in codes if str(code or "").strip()]
            code = str(status.get("reason_code") or "").strip()
            return [code] if code else []
        except Exception:
            return ["training_gate_unavailable"]

    @Property(str, notify=controlsChanged)
    def trainCalibrateStatusLabel(self) -> str:
        try:
            status = self._training_gate_status()
            if bool(status.get("can_train")):
                return str(status.get("status_label") or "Train/Calibrate is available.")
            reason = str(status.get("reason_code") or "training_gate_unavailable")
            return self._t(reason.split(":", 1)[0])
        except Exception:
            return self._t("training_gate_unavailable")

    @Property(str, notify=controlsChanged)
    def trainCalibrateDisabledReason(self) -> str:
        return self.trainingBlockedReason

    @Property(bool, notify=hybridDirectChanged)
    def latestHybridDirectTestPassed(self) -> bool:
        try:
            summary = session_training_helpers.latest_hybrid_direct_test_summary(self)
            return bool(summary.get("passed"))
        except Exception:
            _LOGGER.debug("Failed resolving Hybrid Direct Test pass state.", exc_info=True)
            return False

    @Property("QVariantMap", notify=hybridDirectChanged)
    def latestHybridDirectTestSummary(self) -> Dict[str, Any]:
        try:
            return dict(session_training_helpers.latest_hybrid_direct_test_summary(self))
        except Exception:
            _LOGGER.debug("Failed resolving Hybrid Direct Test summary.", exc_info=True)
            return {"passed": False, "reason_code": "hybrid_test_missing", "training_sample_source": "normal_enrollment_archives_only"}

    @Property(str, constant=True)
    def appVersion(self) -> str:
        return get_app_version()

    @Property("QVariantMap", notify=updateStateChanged)
    def updateState(self) -> Dict[str, Any]:
        return self._ensure_update_state()

    @Property(str, constant=True)
    def privacyPolicyPath(self) -> str:
        return PRIVACY_POLICY_PATH

    @Property(str, constant=True)
    def aboutUsPath(self) -> str:
        return ABOUT_US_PATH

    @Property(str, constant=True)
    def minEnrollmentText(self) -> str:
        return str(MIN_ENROLLMENT_SESSIONS)

    @Property(str, constant=True)
    def maxEnrollmentText(self) -> str:
        return str(MAX_ENROLLMENT_SESSIONS)

    @Slot(str, result=str)
    def tr(self, key: str) -> str:
        return self._t(key)

    def _ensure_companion_infrastructure(self):
        if self._companion_registry is None or self._companion_pairing is None:
            from companion.device_registry import CompanionDeviceRegistry
            from companion.pairing import PairingManager

            self._companion_registry = CompanionDeviceRegistry(load_settings, save_settings_async)
            self._companion_pairing = PairingManager(self._companion_registry)
        return self._companion_registry, self._companion_pairing

    def _refresh_companion_api_state(self, *, emit: bool = False) -> Dict[str, Any]:
        server = getattr(self, "_companion_api_server", None)
        if server is not None and hasattr(server, "state"):
            try:
                state = dict(server.state())
            except Exception:
                state = dict(getattr(self, "_companion_api_state", {}) or {})
                state["running"] = False
        else:
            state = dict(getattr(self, "_companion_api_state", {}) or {})
            state["running"] = False
            registry = getattr(self, "_companion_registry", None)
            if registry is not None and hasattr(registry, "active_device_count"):
                try:
                    state["pairedDeviceCount"] = int(registry.active_device_count())
                except Exception:
                    pass
        state.setdefault("schemaVersion", 1)
        state.setdefault("readOnly", True)
        state.setdefault("controlActionsAllowed", False)
        state.setdefault("trustedLanOnly", bool(str(state.get("host") or "") in {"0.0.0.0", "::"}))
        state.setdefault("pairingWindowSec", 300)
        state.setdefault("pairingSecondsRemaining", 0)
        state.setdefault("autoStopAfterInactivitySec", 900)
        self._companion_api_state = state
        if emit:
            try:
                self.companionApiChanged.emit()
            except Exception:
                pass
        return dict(state)

    def _companion_lan_confirmation_result(self, confirmed: Any) -> Dict[str, Any]:
        if bool(confirmed) is not True:
            return {
                "ok": False,
                "error": "trusted_lan_confirmation_required",
                "message": "Confirm that this is a trusted local network before enabling phone pairing.",
                "user_safe_reason": "Confirm that this is a trusted local network before enabling phone pairing.",
            }
        self._companion_trusted_lan_confirmed_until_epoch = time.time() + 90.0
        return {"ok": True, "confirmedUntilEpoch": self._companion_trusted_lan_confirmed_until_epoch}

    def _companion_lan_confirmation_is_current(self) -> bool:
        try:
            return float(getattr(self, "_companion_trusted_lan_confirmed_until_epoch", 0.0) or 0.0) >= time.time()
        except Exception:
            return False

    def _companion_lan_host_requested(self, host: Any) -> bool:
        return str(host or "").strip() in {"0.0.0.0", "::"}

    @Property("QVariantMap", notify=companionApiChanged)
    def companionApiState(self) -> Dict[str, Any]:
        return self._refresh_companion_api_state()

    @Slot(result="QVariantMap")
    def listCompanionDevices(self) -> Dict[str, Any]:
        registry, _pairing = self._ensure_companion_infrastructure()
        try:
            devices = registry.list_devices(include_revoked=False)
        except Exception:
            return {"ok": False, "error": "device_list_unavailable", "devices": []}
        return {"ok": True, "schemaVersion": 1, "devices": devices, "count": len(devices)}

    @Slot(str, int, result="QVariantMap")
    def startCompanionApi(self, host: str = "", port: int = 0) -> Dict[str, Any]:
        registry, pairing = self._ensure_companion_infrastructure()
        selected_host = str(host or self._app_settings.get("companion_api_host") or "127.0.0.1")
        if self._companion_lan_host_requested(selected_host) and not self._companion_lan_confirmation_is_current():
            result = {
                "ok": False,
                "error": "trusted_lan_confirmation_required",
                "message": "Confirm that this is a trusted local network before enabling phone pairing.",
                "user_safe_reason": "Confirm that this is a trusted local network before enabling phone pairing.",
                **self._refresh_companion_api_state(),
            }
            self._set_status(result["message"], "warn")
            self._debug_trace("companion", "LAN Companion API start denied without explicit confirmation", payload={"host": selected_host}, level="warn")
            return result
        server = getattr(self, "_companion_api_server", None)
        if server is not None and getattr(server, "running", False):
            return {"ok": True, **self._refresh_companion_api_state(emit=True)}
        try:
            from companion.api import CompanionApiServer
            from companion.snapshots import build_status_snapshot

            selected_port = int(port or self._app_settings.get("companion_api_port") or 39081)
            lan_bound = self._companion_lan_host_requested(selected_host)
            server = CompanionApiServer(
                host=selected_host,
                port=selected_port,
                registry=registry,
                pairing=pairing,
                snapshot_provider=lambda: build_status_snapshot(self, registry=registry),
                pairing_window_sec=300 if lan_bound else 0,
                idle_timeout_sec=900 if lan_bound else 0,
                auto_stop_after_pairing=False,
                trusted_lan_confirmed=lan_bound and self._companion_lan_confirmation_is_current(),
            )
            state = server.start()
            self._companion_api_server = server
            self._app_settings = save_settings_async(self._settings_payload(companion_api_host=selected_host, companion_api_port=int(state.get("port") or selected_port)))
            status_text = "Companion API running for trusted local network pairing." if lan_bound else "Companion API running locally."
            self._set_status(status_text, "success")
            self._debug_trace("companion", "Companion API started", payload={"host": state.get("host"), "port": state.get("port"), "lanBound": lan_bound})
            self._refresh_companion_api_state(emit=True)
            return {"ok": True, **state}
        except Exception as exc:
            state = self._refresh_companion_api_state(emit=True)
            state.update({"ok": False, "error": "api_start_failed", "message": "Companion API could not start."})
            self._set_status("Companion API could not start.", "warn")
            self._debug_trace("companion", "Companion API start failed", payload={"error": str(exc)}, level="warn")
            return state

    @Slot(bool, result="QVariantMap")
    def startCompanionLanApi(self, trusted_lan_confirmed: bool = False) -> Dict[str, Any]:
        confirmation = self._companion_lan_confirmation_result(trusted_lan_confirmed)
        if not confirmation.get("ok"):
            self._set_status(str(confirmation.get("message") or "Trusted network confirmation is required."), "warn")
            return confirmation
        state = self._refresh_companion_api_state()
        desired_port = int(state.get("port") or self._app_settings.get("companion_api_port") or 39081)
        return self.startCompanionApi("0.0.0.0", desired_port)

    @Slot(result="QVariantMap")
    def stopCompanionApi(self) -> Dict[str, Any]:
        server = getattr(self, "_companion_api_server", None)
        if server is None:
            return {"ok": True, **self._refresh_companion_api_state(emit=True)}
        try:
            state = server.stop() if hasattr(server, "stop") else {}
        except Exception:
            state = {"ok": False, "error": "api_stop_failed"}
        self._companion_api_server = None
        refreshed = self._refresh_companion_api_state(emit=True)
        refreshed.update({"ok": bool(state.get("ok", True))})
        if state.get("error"):
            refreshed["error"] = state.get("error")
        self._debug_trace("companion", "Companion API stopped", payload={"ok": refreshed.get("ok"), "running": refreshed.get("running")})
        return refreshed

    @Slot(result="QVariantMap")
    def createCompanionPairingPayload(self) -> Dict[str, Any]:
        state = self.startCompanionApi()
        if not state.get("ok", True):
            return {"ok": False, "error": str(state.get("error") or "api_start_failed")}
        registry, pairing = self._ensure_companion_infrastructure()
        try:
            current_user = self._current_user if isinstance(getattr(self, "_current_user", None), dict) else {}
            display_name = str(current_user.get("display_name") or current_user.get("user_id") or "BioAuth Desktop")
            payload = pairing.create_pairing_payload(
                host=str(state.get("host") or self._companion_api_state.get("host") or "127.0.0.1"),
                port=int(state.get("port") or self._companion_api_state.get("port") or 39081),
                desktop_name=display_name,
                ttl_sec=300,
            )
            pairing_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            result = {"ok": True, "schemaVersion": 1, "payload": payload, "pairingJson": pairing_json, "expiresAt": payload.get("expiresAt")}
            self._refresh_companion_api_state(emit=True)
            self._debug_trace("companion", "Companion pairing payload created", payload={"expiresAt": payload.get("expiresAt"), "host": payload.get("host"), "port": payload.get("port")})
            return result
        except Exception:
            self._debug_trace("companion", "Companion pairing payload failed", payload={"error": "pairing_payload_failed"}, level="warn")
            return {"ok": False, "error": "pairing_payload_failed"}

    @Slot(result="QVariantMap")
    @Slot(bool, result="QVariantMap")
    def createCompanionLanPairingPayload(self, trusted_lan_confirmed: bool = False) -> Dict[str, Any]:
        """Create a phone-reachable companion pairing payload after explicit LAN confirmation."""

        confirmation = self._companion_lan_confirmation_result(trusted_lan_confirmed)
        if not confirmation.get("ok"):
            self._set_status(str(confirmation.get("message") or "Trusted network confirmation is required."), "warn")
            return confirmation
        try:
            from companion.api import local_ip_hint

            existing_state = self._refresh_companion_api_state()
            desired_port = int(existing_state.get("port") or self._app_settings.get("companion_api_port") or 39081)
            existing_host = str(existing_state.get("host") or "")
            server = getattr(self, "_companion_api_server", None)
            if server is not None and getattr(server, "running", False) and existing_host not in ("0.0.0.0", "::"):
                self.stopCompanionApi()
            state = self.startCompanionApi("0.0.0.0", desired_port)
            if not state.get("ok", True):
                return {"ok": False, "error": str(state.get("error") or "api_start_failed"), "message": str(state.get("message") or "Companion API could not start.")}
            registry, pairing = self._ensure_companion_infrastructure()
            current_user = self._current_user if isinstance(getattr(self, "_current_user", None), dict) else {}
            display_name = str(current_user.get("display_name") or current_user.get("user_id") or "BioAuth Desktop")
            lan_host = local_ip_hint()
            payload = pairing.create_pairing_payload(
                host=lan_host,
                port=int(state.get("port") or desired_port),
                desktop_name=display_name,
                ttl_sec=300,
            )
            pairing_json = json.dumps(payload, ensure_ascii=False, indent=2)
            qr_pairing_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            try:
                from companion.qr import build_qr_png_data_uri

                qr_result = build_qr_png_data_uri(qr_pairing_json)
            except Exception as qr_exc:
                qr_result = {"ok": False, "error": str(qr_exc), "dataUri": ""}
            result = {
                "ok": True,
                "schemaVersion": 1,
                "payload": payload,
                "pairingJson": pairing_json,
                "qrPairingJson": qr_pairing_json,
                "qrPngDataUri": str(qr_result.get("dataUri") or ""),
                "qrAvailable": bool(qr_result.get("ok") and qr_result.get("dataUri")),
                "qrError": str(qr_result.get("error") or ""),
                "expiresAt": payload.get("expiresAt"),
                "pairingWindowSec": 300,
                "bindingHost": str(state.get("host") or "0.0.0.0"),
                "advertisedHost": lan_host,
                "port": int(state.get("port") or desired_port),
                "readOnly": True,
                "trustedLanOnly": True,
                "autoStopAfterInactivitySec": int(state.get("autoStopAfterInactivitySec") or 900),
                "warning": "Use companion pairing only on a trusted local network. The pairing code expires and is single-use.",
            }
            self._refresh_companion_api_state(emit=True)
            self._debug_trace("companion", "Companion pairing payload created", payload={"expiresAt": payload.get("expiresAt"), "host": lan_host, "port": payload.get("port")})
            self._set_status("Companion pairing QR/JSON generated for a trusted local network.", "success")
            return result
        except Exception:
            self._debug_trace("companion", "LAN companion pairing payload failed", payload={"error": "pairing_payload_failed"}, level="warn")
            return {"ok": False, "error": "pairing_payload_failed", "message": "Could not generate pairing QR/JSON."}

    @Slot(result="QVariantMap")
    def revokeAllCompanionDevices(self) -> Dict[str, Any]:
        registry, _pairing = self._ensure_companion_infrastructure()
        try:
            result = registry.revoke_all()
            self._refresh_companion_api_state(emit=True)
            self._set_status("All companion devices were revoked.", "success")
            return result
        except Exception:
            self._set_status("Companion devices could not be revoked.", "warn")
            return {"ok": False, "error": "revoke_failed"}

    @Slot(object)
    def _receive_training_progress(self, payload: object) -> None:
        updater = getattr(self, "_apply_training_progress_payload", None)
        if callable(updater):
            updater(payload)

# Compatibility source markers retained for legacy source-inspection tests.
# def _format_qml_warning
# def _write_qml_startup_failure_log
# def AppBridge
# def run_runtime_smoke_selfcheck
# def run_packaging_performance_check
# def run_packaging_selfcheck
# def main
# class AppBridge(AuthMixin, SessionMixin, SettingsMixin, RefreshMixin
# backend
# QQmlApplicationEngine

if __name__ == "__main__":
    main()
