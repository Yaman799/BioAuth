from __future__ import annotations

import logging
import os
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict

from app_passcode import build_passcode_record, is_passcode_configured, validate_passcode_value, verify_passcode_record
from app_settings import (
    PRIVACY_POLICY_VERSION,
    build_evidence_consent_fields,
    build_face_template_consent_fields,
    build_privacy_consent_fields,
    feature_flag_enabled,
    has_current_face_template_consent,
    normalize_interface_mode,
)
from deep_runtime import (
    deep_runtime_fallback_reason_text,
    deep_runtime_is_fallback,
    normalize_benchmark_record,
    normalize_deep_runtime_fallback_reason,
    normalize_deep_runtime_mode,
    resolve_deep_runtime_state,
    run_local_device_benchmark,
)
from license_manager import activate_license_code, import_license_file
from release_profile import current_build_profile, current_package_profile

from .shared import (
    THEMES,
    STRINGS,
    WELCOME_POLICY_VERSION,
    normalize_sensitivity_preset,
    ABOUT_US_PATH,
    QDesktopServices,
    QUrl,
    QTimer,
    Slot,
    complete_user_onboarding,
    is_startup_enabled,
    play_button_sound,
    save_settings_async,
    set_startup_enabled,
    translate_string,
)

save_settings = save_settings_async

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - exercised in the real Qt runtime
    from PySide6.QtCore import QCoreApplication as _FaceQtCoreApplication
    from PySide6.QtCore import QObject as _FaceQtQObject
    from PySide6.QtCore import QRunnable as _FaceQtRunnable
    from PySide6.QtCore import QThreadPool as _FaceQtThreadPool
    from PySide6.QtCore import Signal as _FaceQtSignal
except Exception:  # pragma: no cover - import stubs used by unit tests may omit these classes
    _FaceQtCoreApplication = None
    _FaceQtQObject = None
    _FaceQtRunnable = None
    _FaceQtThreadPool = None
    _FaceQtSignal = None

if _FaceQtQObject is not None and _FaceQtRunnable is not None and _FaceQtSignal is not None:
    class _FaceOperationSignals(_FaceQtQObject):
        finished = _FaceQtSignal(object)


    class _FaceOperationWorker(_FaceQtRunnable):
        def __init__(self, task):
            super().__init__()
            self.task = task
            self.signals = _FaceOperationSignals()

        def run(self) -> None:
            try:
                payload = dict(self.task() or {})
            except Exception as exc:
                payload = {
                    "status": "failed",
                    "ok": False,
                    "reason": str(exc or "failed"),
                    "rawImagesStored": False,
                    "lockIntegrationEnabled": False,
                }
            self.signals.finished.emit(payload)
else:
    _FaceOperationSignals = None
    _FaceOperationWorker = None

FACE_ENROLLMENT_DEFAULT_FRAME_COUNT = 7
FACE_ENROLLMENT_MIN_FRAME_COUNT = 3
FACE_ENROLLMENT_MAX_FRAME_COUNT = 7
FACE_VERIFICATION_DEFAULT_FRAME_COUNT = 5
FACE_VERIFICATION_MIN_FRAME_COUNT = 1
FACE_VERIFICATION_MAX_FRAME_COUNT = 5
BACKEND_FACE_CAMERA_MIN_INDEX = 0
BACKEND_FACE_CAMERA_MAX_INDEX = 4
FACE_MODEL_FAILURE_STATUSES = {"models_missing", "detector_model_missing", "recognizer_model_missing", "face_models_missing", "face_models_invalid", "model_invalid"}
FACE_QUALITY_FAILURE_STATUS_BY_REASON = {
    "no_face": "no_face_detected",
    "multiple_faces": "multiple_faces_detected",
    "low_quality_face": "poor_quality",
    "low_quality_face_too_small": "poor_quality",
    "invalid_frame": "poor_quality",
    "invalid_frame_values": "poor_quality",
    "invalid_face_detection": "poor_quality",
    "empty_embedding": "poor_quality",
    "zero_embedding": "poor_quality",
    "non_finite_embedding": "poor_quality",
    "invalid_face_geometry": "poor_quality",
}

FACE_CAMERA_UNAVAILABLE_STATUSES = {
    "camera_unavailable",
    "opencv_unavailable",
    "camera_provider_unavailable",
    "camera_capture_exception",
    "device_open_failed",
    "permission_or_device_open_failure",
    "permission_denied",
    "no_frame_captured",
    "capture_timeout",
}
FACE_CAMERA_READY_STATUSES = {"camera_ready", "captured", "available"}
PHASE_FEATURE_FLAG_KEYS = (
    "enable_user_shell",
    "enable_manual_model_switch",
    "enable_face_confirmation",
    "enable_face_enrollment",
    "enable_shadow_feedback_from_face",
    "enable_release_autoupdate",
    "enable_startup_protected_sessions_after_build",
)
FACE_AVAILABILITY_TO_STATUS = {
    "ready": "enrolled",
    "feature_disabled": "feature_disabled",
    "models_missing": "models_missing",
    "detector_model_missing": "detector_model_missing",
    "recognizer_model_missing": "recognizer_model_missing",
    "model_missing": "models_missing",
    "model_invalid": "face_models_invalid",
    "camera_unavailable": "camera_unavailable",
    "not_checked": "not_checked",
    "checking_camera": "checking_camera",
    "consent_required": "consent_required",
    "template_missing": "not_enrolled",
    "disabled": "disabled",
    "signed_out": "signed_out",
}
FACE_CAMERA_AVAILABILITY_TTL_SEC = 2.0


def _request_refresh(self, reason: str, force: bool = False) -> None:
    request = getattr(self, "requestRefresh", None)
    if callable(request):
        request(reason, force)
        return
    legacy = getattr(self, "refreshNow", None)
    if callable(legacy):
        legacy()


class SettingsMixin:
    def _about_us_body(self) -> str:
        path = Path(ABOUT_US_PATH)
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            raw = ""
        profile_note = f"\n\nBuild profile: {current_build_profile()} / Package profile: {current_package_profile()}"
        if not raw:
            return self._status_text("about_us_fallback") + profile_note
        return raw + profile_note

    def _status_text(self, key: str, **kwargs: Any) -> str:
        translator = getattr(self, "_t", None)
        if callable(translator):
            return translator(key, **kwargs)
        return translate_string(getattr(self, "_language", "en"), key, **kwargs)

    def _emit_privacy_center_changed(self) -> None:
        signal = getattr(self, "privacyCenterChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()

    def _emit_auto_enrollment_changed(self) -> None:
        signal = getattr(self, "autoEnrollmentChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()


    def _settings_payload(self, **changes: Any) -> Dict[str, Any]:
        current_settings = getattr(self, "_app_settings", {})
        current_settings = current_settings if isinstance(current_settings, dict) else {}
        payload = {
            "theme": self._theme,
            "language": self._language,
            "run_on_startup": self._run_on_startup,
            "interface_mode": normalize_interface_mode(getattr(self, "_interface_mode", "developer")),
            "risk_sensitivity": getattr(self, "_risk_sensitivity", "conservative"),
            "mute_button_sounds": bool(getattr(self, "_mute_button_sounds", True)),
            "remember_login_enabled": bool(getattr(self, "_remember_login_enabled", False)),
            "privacy_policy_version": PRIVACY_POLICY_VERSION,
            "incident_evidence_enabled": bool(getattr(self, "_incident_evidence_enabled", False)),
            "incident_evidence_consent_granted": bool(getattr(self, "_incident_evidence_consent_granted", False)),
            "incident_evidence_consent_policy_version": str(getattr(self, "_incident_evidence_consent_policy_version", "") or ""),
            "incident_evidence_consent_timestamp": str(getattr(self, "_incident_evidence_consent_timestamp", "") or ""),
            "incident_evidence_capture_screenshot": bool(getattr(self, "_incident_evidence_capture_screenshot", False)),
            "incident_evidence_capture_webcam": bool(getattr(self, "_incident_evidence_capture_webcam", False)),
            "incident_evidence_retention_days": int(getattr(self, "_incident_evidence_retention_days", 30) or 30),
            "face_confirmation_enabled": bool(getattr(self, "_face_confirmation_enabled", False)),
            "backend_face_camera_index": self._get_backend_face_camera_index_value(),
            "face_enrollment_frame_count": self._face_enrollment_capture_count(current_settings),
            "face_template_consent_granted": bool(getattr(self, "_face_template_consent_granted", False)),
            "face_template_consent_policy_version": str(getattr(self, "_face_template_consent_policy_version", "") or ""),
            "face_template_consent_timestamp": str(getattr(self, "_face_template_consent_timestamp", "") or ""),
            "smart_auto_enrollment_enabled": bool(getattr(self, "_smart_auto_enrollment_enabled", False)),
            "auto_train_when_ready_enabled": bool(getattr(self, "_auto_train_when_ready_enabled", False)),
            "auto_promote_when_production_safe_enabled": bool(getattr(self, "_auto_promote_when_production_safe_enabled", False)),
            "shadow_automation_paused": bool(getattr(self, "_shadow_automation_paused", False)),
            "developer_forced_production_ready": bool(getattr(self, "_developer_forced_production_ready", False)),
            "app_passcode_enabled": bool(getattr(self, "_app_passcode_enabled", False)),
            "app_passcode_timeout_sec": int(getattr(self, "_app_passcode_timeout_sec", 60) or 60),
            "app_passcode_record": getattr(self, "_app_passcode_record", {}) if isinstance(getattr(self, "_app_passcode_record", {}), dict) else {},
            "deep_runtime_mode": normalize_deep_runtime_mode(getattr(self, "_deep_runtime_mode", "auto"), default="auto"),
            "deep_runtime_manual_override": bool(getattr(self, "_deep_runtime_manual_override", False)),
            "developer_direct_test_enabled": bool(getattr(self, "_developer_direct_test_enabled", False)),
            "developer_direct_consent_enabled": bool(getattr(self, "_developer_direct_consent_enabled", False)),
            "deep_runtime_benchmark": normalize_benchmark_record(getattr(self, "_deep_runtime_benchmark", {})),
            "build_profile": current_build_profile(),
            "package_profile": current_package_profile(),
        }
        for feature_key in PHASE_FEATURE_FLAG_KEYS:
            payload[feature_key] = bool(current_settings.get(feature_key, False))
        payload.update(changes)
        return payload


    def _sanitize_app_passcode_timeout(self, seconds: Any) -> int:
        try:
            value = int(seconds or 60)
        except (TypeError, ValueError):
            value = 60
        allowed = (30, 60, 120, 300)
        return min(allowed, key=lambda candidate: abs(candidate - value))

    def _finish_onboarding_dialog(self) -> None:
        self._onboarding_visible = False
        self._onboarding_mode = "consent"
        self._pending_onboarding_do_not_show_again = False
        self._pending_onboarding_tour_skipped = False
        self.onboardingChanged.emit()

    def _show_performance_onboarding_step(self, *, do_not_show_again: bool = False, skipped: bool = False) -> None:
        self._onboarding_visible = True
        self._onboarding_mode = "performance"
        self._pending_onboarding_do_not_show_again = bool(do_not_show_again)
        self._pending_onboarding_tour_skipped = bool(skipped)
        self.onboardingChanged.emit()

    def _maybe_prompt_passcode_setup_after_onboarding(self) -> None:
        if bool(getattr(self, "_pending_new_account_passcode_prompt", False)) and not is_passcode_configured(getattr(self, "_app_passcode_record", {})):
            self._passcode_setup_prompt_visible = True
            self._pending_new_account_passcode_prompt = False
            prompt_signal = getattr(self, "passcodeSetupPromptChanged", None)
            if prompt_signal is not None and hasattr(prompt_signal, "emit"):
                prompt_signal.emit()
        else:
            self._pending_new_account_passcode_prompt = False

    def _sanitize_incident_retention_days(self, days: Any) -> int:
        try:
            value = int(days or 30)
        except (TypeError, ValueError):
            value = 30
        allowed = (7, 14, 30, 90)
        return min(allowed, key=lambda candidate: abs(candidate - value))

    def _delete_current_user_evidence(self) -> None:
        if not self._current_user:
            return
        from evidence_capture import delete_evidence_for_user

        delete_evidence_for_user(str(self._current_user.get("user_id") or ""))

    def _local_data_action_block_reason(self) -> str:
        blocked = self._destructive_action_block_reason(for_delete=False)
        if blocked:
            return blocked
        if bool(getattr(self, "_training_in_progress", False)):
            return "Local data operations are unavailable while training is running."
        if bool(getattr(self, "_pending_monitor_start", False)) or bool(getattr(self, "_pending_logger_start", False)) or bool(getattr(self, "_pending_shadow_evidence_monitor_start", False)):
            return "Local data operations are unavailable while a session is starting."
        if bool(getattr(self, "canStop", False)):
            return "Stop the current session before changing local backup or restore data."
        try:
            if str(self._normal_enrollment_logger_flow()) == "enrollment_active":
                return "Stop learning before changing local backup or restore data."
        except Exception:
            pass
        try:
            if str(self._normal_user_session_flow()).startswith("protected"):
                return "Stop protection before changing local backup or restore data."
        except Exception:
            pass
        try:
            if bool(self._production_monitor_process_running()):
                return "Stop protection before changing local backup or restore data."
        except Exception:
            pass
        server = getattr(self, "_companion_api_server", None)
        if server is not None and bool(getattr(server, "running", False)):
            return "Stop Companion mobile pairing before changing local backup or restore data."
        return ""

    def _complete_local_data_operation(self, result: Dict[str, Any], *, reason: str) -> Dict[str, Any]:
        if bool(result.get("ok")):
            invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
            if callable(invalidate):
                invalidate()
            self._emit_privacy_center_changed()
            _request_refresh(self, reason, True)
        self._set_status(str(result.get("message") or result.get("reason") or reason), "success" if result.get("ok") else "warn")
        return dict(result)

    @Slot(str, result="QVariantMap")
    def exportEncryptedBackup(self, path: str) -> Dict[str, Any]:
        blocked = self._local_data_action_block_reason()
        if blocked:
            return self._complete_local_data_operation({"ok": False, "reason": "operation_blocked", "message": blocked}, reason="settings:export_encrypted_backup")
        from local_data_backup import export_encrypted_backup

        return self._complete_local_data_operation(export_encrypted_backup(str(path or "")), reason="settings:export_encrypted_backup")

    @Slot(str, result="QVariantMap")
    def inspectEncryptedBackup(self, path: str) -> Dict[str, Any]:
        from local_data_backup import inspect_encrypted_backup

        return dict(inspect_encrypted_backup(str(path or "")))

    @Slot(str, str, result="QVariantMap")
    def importEncryptedBackup(self, path: str, confirmation: str) -> Dict[str, Any]:
        blocked = self._local_data_action_block_reason()
        if blocked:
            return self._complete_local_data_operation({"ok": False, "reason": "operation_blocked", "message": blocked}, reason="settings:import_encrypted_backup")
        expected = "RESTORE LOCAL BACKUP"
        if str(confirmation or "").strip() != expected:
            return self._complete_local_data_operation({"ok": False, "reason": "confirmation_required", "message": f"Type {expected!r} to restore local backup."}, reason="settings:import_encrypted_backup")
        from local_data_backup import restore_encrypted_backup

        return self._complete_local_data_operation(restore_encrypted_backup(str(path or "")), reason="settings:import_encrypted_backup")

    @Slot(str, result="QVariantMap")
    def resetCurrentProfileData(self, confirmation: str) -> Dict[str, Any]:
        if not self._current_user:
            return {"ok": False, "reason": "user_required", "message": "Sign in before resetting the profile."}
        blocked = self._local_data_action_block_reason()
        if blocked:
            return self._complete_local_data_operation({"ok": False, "reason": "operation_blocked", "message": blocked}, reason="settings:reset_current_profile")
        from local_data_backup import reset_current_profile

        user_id = str(self._current_user.get("user_id") or "")
        result = reset_current_profile(user_id, confirmation=str(confirmation or ""), delete_sessions=False)
        if bool(result.get("ok")):
            self._reset_shadow_runtime_flags()
        return self._complete_local_data_operation(result, reason="settings:reset_current_profile")

    @Slot(str, result="QVariantMap")
    def deleteAllLocalBioAuthData(self, confirmation: str) -> Dict[str, Any]:
        blocked = self._local_data_action_block_reason()
        if blocked:
            return self._complete_local_data_operation({"ok": False, "reason": "operation_blocked", "message": blocked}, reason="settings:delete_all_local_data")
        from local_data_backup import DELETE_ALL_CONFIRMATION, delete_all_local_data

        if str(confirmation or "").strip() != DELETE_ALL_CONFIRMATION:
            return self._complete_local_data_operation({"ok": False, "reason": "confirmation_required", "message": f"Type {DELETE_ALL_CONFIRMATION!r} to delete local BioAuth data."}, reason="settings:delete_all_local_data")
        result = delete_all_local_data(confirmation=confirmation)
        if bool(result.get("ok")):
            self._current_user = None
            self._profile = {}
            self._sessions = []
            self._reset_shadow_runtime_flags()
            try:
                self.currentUserChanged.emit()
                self.profileChanged.emit()
                self.sessionsChanged.emit()
            except Exception:
                pass
        return self._complete_local_data_operation(result, reason="settings:delete_all_local_data")

    @Slot(result="QVariantMap")
    def localBackupFormatSummary(self) -> Dict[str, Any]:
        from local_data_backup import backup_format_summary

        return dict(backup_format_summary())

    @Slot()
    def deleteIncidentEvidence(self) -> None:
        if not self._current_user:
            return
        self._delete_current_user_evidence()
        self._set_status(self._status_text("incident_evidence_deleted_msg"), "success")
        self._emit_privacy_center_changed()

    @Slot()
    def deleteMyData(self) -> None:
        if not self._current_user:
            return
        blocked_reason = self._destructive_action_block_reason(for_delete=False)
        if blocked_reason:
            self._set_status(blocked_reason, "warn")
            return
        from evidence_capture import delete_evidence_for_user
        from model_metadata import delete_user_data, invalidate_session_discovery_cache

        user_id = str(self._current_user.get("user_id") or "")
        result = delete_user_data(user_id)
        delete_evidence_for_user(user_id)
        invalidate_session_discovery_cache()
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        self._reset_shadow_runtime_flags()
        self._set_status(self._status_text("delete_my_data_done"), "success" if result.get("ok", True) else "warn")
        self._emit_privacy_center_changed()
        _request_refresh(self, "settings:delete_my_data", True)


    @Slot(str, result="QVariantMap")
    def activateLicense(self, code: str) -> Dict[str, Any]:
        try:
            result = activate_license_code(str(code or ""))
        except Exception:
            result = {"ok": False, "message": "Invalid license code.", "state": "invalid_basic", "licenseStatus": {}}
        refresh = getattr(self, "_refresh_license_status", None)
        if callable(refresh):
            refresh()
        self._set_status(str(result.get("message") or "Invalid license code."), "success" if result.get("ok") else "warn")
        self._emit_privacy_center_changed()
        return dict(result)

    @Slot(str, result="QVariantMap")
    def importLicenseFile(self, path: str) -> Dict[str, Any]:
        try:
            result = import_license_file(str(path or ""))
        except Exception:
            result = {"ok": False, "message": "License import failed.", "state": "invalid_basic", "licenseStatus": {}}
        refresh = getattr(self, "_refresh_license_status", None)
        if callable(refresh):
            refresh()
        self._set_status(str(result.get("message") or "License import failed."), "success" if result.get("ok") else "warn")
        self._emit_privacy_center_changed()
        return dict(result)

    @Slot()
    def refreshLicenseStatus(self) -> None:
        refresh = getattr(self, "_refresh_license_status", None)
        if callable(refresh):
            refresh()
        self._set_status(self._status_text("license_status_refreshed"), "info")
        self._emit_privacy_center_changed()

    @Slot()
    def exportSupportBundle(self) -> None:
        from support_bundle import write_support_bundle

        user_id = ""
        if self._current_user:
            user_id = str(self._current_user.get("user_id") or "")
        runtime_state = getattr(self, "_runtime_state", {}) if isinstance(getattr(self, "_runtime_state", {}), dict) else {}
        try:
            path = write_support_bundle(user_id=user_id or None, runtime_state=runtime_state)
            self._support_bundle_path = str(path)
            signal = getattr(self, "supportBundleChanged", None)
            if signal is not None and hasattr(signal, "emit"):
                signal.emit()
            self._set_status(self._status_text("support_bundle_created", path=str(path)), "success")
            self._emit_privacy_center_changed()
        except Exception as exc:
            self._set_status(self._status_text("support_bundle_failed", error=str(exc)), "warn")

    @Slot(bool)
    def setIncidentEvidenceEnabled(self, enabled: bool) -> None:
        requested = bool(enabled)
        current = bool(getattr(self, "_incident_evidence_enabled", False))
        consent_changes = build_evidence_consent_fields(True) if requested else {}
        if requested:
            self._incident_evidence_consent_granted = True
            self._incident_evidence_consent_policy_version = str(consent_changes.get("incident_evidence_consent_policy_version") or "")
            self._incident_evidence_consent_timestamp = str(consent_changes.get("incident_evidence_consent_timestamp") or "")
        if requested == current and not requested:
            return
        self._incident_evidence_enabled = requested
        self._app_settings = save_settings(
            self._settings_payload(
                incident_evidence_enabled=requested,
                **consent_changes,
            )
        )
        signal = getattr(self, "incidentEvidenceChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        state_key = "incident_evidence_enabled_msg" if requested else "incident_evidence_disabled_msg"
        self._set_status(self._status_text(state_key), "info")
        self._emit_privacy_center_changed()

    @Slot(bool)
    def setIncidentEvidenceCaptureScreenshot(self, enabled: bool) -> None:
        requested = bool(enabled)
        if requested == bool(getattr(self, "_incident_evidence_capture_screenshot", False)):
            return
        self._incident_evidence_capture_screenshot = requested
        self._app_settings = save_settings(self._settings_payload(incident_evidence_capture_screenshot=requested))
        signal = getattr(self, "incidentEvidenceChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        self._set_status(self._status_text("incident_evidence_capture_updated"), "info")
        self._emit_privacy_center_changed()

    @Slot(bool)
    def setIncidentEvidenceCaptureWebcam(self, enabled: bool) -> None:
        requested = bool(enabled)
        if requested == bool(getattr(self, "_incident_evidence_capture_webcam", False)):
            return
        self._incident_evidence_capture_webcam = requested
        self._app_settings = save_settings(self._settings_payload(incident_evidence_capture_webcam=requested))
        signal = getattr(self, "incidentEvidenceChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        self._set_status(self._status_text("incident_evidence_capture_updated"), "info")
        self._emit_privacy_center_changed()

    @Slot(int)
    def setIncidentEvidenceRetentionDays(self, days: int) -> None:
        value = self._sanitize_incident_retention_days(days)
        if value == int(getattr(self, "_incident_evidence_retention_days", 30) or 30):
            return
        self._incident_evidence_retention_days = value
        self._app_settings = save_settings(self._settings_payload(incident_evidence_retention_days=value))
        signal = getattr(self, "incidentEvidenceChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        self._set_status(self._status_text("incident_evidence_retention_saved", days=value), "info")
        self._emit_privacy_center_changed()

    def _emit_app_passcode_changed(self) -> None:
        signal = getattr(self, "appPasscodeChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()

    def _verify_current_app_passcode_for_sensitive_change(self, current_code: str) -> bool:
        existing = getattr(self, "_app_passcode_record", {})
        if not is_passcode_configured(existing):
            self._set_status(self._status_text("app_passcode_not_set"), "warn")
            self._emit_app_passcode_changed()
            return False
        if not verify_passcode_record(existing, current_code):
            self._set_status(self._status_text("app_passcode_invalid_current"), "danger")
            self._emit_app_passcode_changed()
            return False
        return True

    @Slot(bool)
    def setAppPasscodeEnabled(self, enabled: bool) -> None:
        requested = bool(enabled)
        current = bool(getattr(self, "_app_passcode_enabled", False))
        if requested == current:
            return
        if not requested:
            self._set_status(self._status_text("app_passcode_disable_requires_current"), "danger")
            self._emit_app_passcode_changed()
            return
        if not is_passcode_configured(getattr(self, "_app_passcode_record", {})):
            self._set_status(self._status_text("app_passcode_set_first"), "warn")
            self._emit_app_passcode_changed()
            return
        self._app_passcode_enabled = True
        self._app_settings = save_settings(self._settings_payload(app_passcode_enabled=True))
        self._emit_app_passcode_changed()
        self._set_status(self._status_text("app_passcode_enabled_msg"), "info")

    @Slot(str, result=bool)
    def disableAppPasscode(self, current_code: str) -> bool:
        if not bool(getattr(self, "_app_passcode_enabled", False)):
            self._emit_app_passcode_changed()
            return True
        if not self._verify_current_app_passcode_for_sensitive_change(current_code):
            return False
        self._app_passcode_enabled = False
        reset_runtime = getattr(self, "_reset_app_passcode_runtime", None)
        if callable(reset_runtime):
            reset_runtime(unlock_only=True)
        self._app_settings = save_settings(self._settings_payload(app_passcode_enabled=False))
        self._emit_app_passcode_changed()
        self._set_status(self._status_text("app_passcode_disabled_msg"), "info")
        return True

    @Slot(int)
    def setAppPasscodeTimeoutSec(self, seconds: int) -> None:
        value = self._sanitize_app_passcode_timeout(seconds)
        if value == int(getattr(self, "_app_passcode_timeout_sec", 60) or 60):
            return
        self._app_passcode_timeout_sec = value
        self._app_settings = save_settings(self._settings_payload(app_passcode_timeout_sec=value))
        self.appPasscodeChanged.emit()
        self._set_status(self._status_text("app_passcode_timeout_saved", seconds=value), "info")

    @Slot(str, str, str)
    def updateAppPasscode(self, current_code: str, new_code: str, confirm_code: str) -> None:
        existing = getattr(self, "_app_passcode_record", {})
        configured = is_passcode_configured(existing)
        if configured and not verify_passcode_record(existing, current_code):
            self._set_status(self._status_text("app_passcode_invalid_current"), "danger")
            return
        valid, error_key = validate_passcode_value(new_code)
        if not valid:
            self._set_status(self._status_text(error_key), "danger")
            return
        if str(new_code or "") != str(confirm_code or ""):
            self._set_status(self._status_text("app_passcode_mismatch"), "danger")
            return
        self._app_passcode_record = build_passcode_record(new_code)
        self._app_passcode_enabled = True
        self._app_settings = save_settings(
            self._settings_payload(
                app_passcode_enabled=True,
                app_passcode_record=self._app_passcode_record,
            )
        )
        reset_runtime = getattr(self, "_reset_app_passcode_runtime", None)
        if callable(reset_runtime):
            reset_runtime(unlock_only=True)
        self.appPasscodeChanged.emit()
        if getattr(self, "_passcode_setup_prompt_visible", False):
            self._passcode_setup_prompt_visible = False
            prompt_signal = getattr(self, "passcodeSetupPromptChanged", None)
            if prompt_signal is not None and hasattr(prompt_signal, "emit"):
                prompt_signal.emit()
        state_key = "app_passcode_updated" if configured else "app_passcode_created"
        self._set_status(self._status_text(state_key), "success")

    @Slot(str, result=bool)
    def clearAppPasscode(self, current_code: str) -> bool:
        if not self._verify_current_app_passcode_for_sensitive_change(current_code):
            return False
        self._app_passcode_record = {}
        self._app_passcode_enabled = False
        self._app_settings = save_settings(
            self._settings_payload(
                app_passcode_enabled=False,
                app_passcode_record={},
            )
        )
        reset_runtime = getattr(self, "_reset_app_passcode_runtime", None)
        if callable(reset_runtime):
            reset_runtime(unlock_only=True)
        self._emit_app_passcode_changed()
        self._set_status(self._status_text("app_passcode_cleared"), "success")
        return True

    @Slot(str)
    def unlockAppPasscode(self, passcode: str) -> None:
        remaining_fn = getattr(self, "_remaining_app_passcode_cooldown", None)
        update_cooldown = getattr(self, "_sync_app_passcode_cooldown", None)
        if callable(remaining_fn) and int(remaining_fn()) > 0:
            if callable(update_cooldown):
                update_cooldown()
            self._app_passcode_message = self._status_text("app_passcode_unlock_cooldown", seconds=int(remaining_fn()))
            self.appPasscodeChanged.emit()
            return
        if not verify_passcode_record(getattr(self, "_app_passcode_record", {}), passcode):
            self._app_passcode_failed_attempts = int(getattr(self, "_app_passcode_failed_attempts", 0) or 0) + 1
            if self._app_passcode_failed_attempts >= 5:
                self._app_passcode_failed_attempts = 0
                self._app_passcode_cooldown_until = time.time() + 30.0
                if callable(update_cooldown):
                    update_cooldown(force_emit=True)
                self._app_passcode_message = self._status_text("app_passcode_unlock_cooldown", seconds=int(remaining_fn() if callable(remaining_fn) else 30))
            else:
                self._app_passcode_message = self._status_text("app_passcode_unlock_failed")
            self.appPasscodeChanged.emit()
            return
        self._app_passcode_failed_attempts = 0
        self._app_passcode_cooldown_until = 0.0
        self._app_passcode_message = ""
        reset_runtime = getattr(self, "_reset_app_passcode_runtime", None)
        if callable(reset_runtime):
            reset_runtime(unlock_only=True)
        touch = getattr(self, "_record_ui_activity", None)
        if callable(touch):
            touch()
        if callable(update_cooldown):
            update_cooldown(force_emit=True)
        self.appPasscodeChanged.emit()
        self._set_status(self._status_text("app_passcode_unlock_success"), "success")

    def _welcome_state_store(self) -> Dict[str, Any]:
        data = (self._app_settings or {}).get("user_welcome_ack", {})
        return data if isinstance(data, dict) else {}

    def _current_user_welcome_state(self) -> Dict[str, Any]:
        if not self._current_user:
            return {}
        data = self._welcome_state_store().get(self._safe_user(), {})
        return data if isinstance(data, dict) else {}

    def _has_current_user_welcome_consent(self) -> bool:
        state = self._current_user_welcome_state()
        return bool(state.get("policy_accepted")) and bool(state.get("plan_ack")) and str(state.get("policy_version", "")).strip() == WELCOME_POLICY_VERSION

    def _save_current_user_welcome_state(self, **changes: Any) -> None:
        if not self._current_user:
            return
        store = self._welcome_state_store()
        safe_user = self._safe_user()
        entry = store.get(safe_user, {})
        if not isinstance(entry, dict):
            entry = {}
        entry.update(changes)
        entry["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        store[safe_user] = entry
        self._app_settings = save_settings(self._settings_payload(user_welcome_ack=store))

    @Slot(bool, bool, bool)
    def saveOnboarding(self, policy_accepted: bool, plan_ack: bool, start_enrollment_after: bool) -> None:
        if not policy_accepted or not plan_ack:
            self._set_status(self._t("policy_required"), "warn")
            return
        self._save_current_user_welcome_state(
            policy_accepted=True,
            plan_ack=True,
            policy_version=WELCOME_POLICY_VERSION,
            privacy_policy_version=PRIVACY_POLICY_VERSION,
        )
        self._app_settings = save_settings(self._settings_payload(**build_privacy_consent_fields()))
        self._finish_onboarding_dialog()
        self._maybe_prompt_passcode_setup_after_onboarding()
        self._emit_privacy_center_changed()
        if start_enrollment_after:
            self.startEnrollment()

    @Slot()
    def dismissOnboarding(self) -> None:
        self._finish_onboarding_dialog()

    @Slot()
    def dismissPasscodeSetupPrompt(self) -> None:
        if getattr(self, "_passcode_setup_prompt_visible", False):
            self._passcode_setup_prompt_visible = False
            self.passcodeSetupPromptChanged.emit()

    @Slot(bool)
    def completeNewUserOnboarding(self, do_not_show_again: bool) -> None:
        if not self._current_user:
            return
        updated_user = complete_user_onboarding(self._current_user["user_id"], do_not_show_again=bool(do_not_show_again), skipped=False)
        if isinstance(updated_user, dict):
            self._current_user = updated_user
            user_signal = getattr(self, "currentUserChanged", None)
            if user_signal is not None and hasattr(user_signal, "emit"):
                user_signal.emit()
        self._finish_onboarding_dialog()
        self._maybe_prompt_passcode_setup_after_onboarding()
        self._set_status(self._status_text("onboarding_completed_msg"), "success")

    @Slot(bool)
    def continueNewUserOnboardingToPerformance(self, do_not_show_again: bool) -> None:
        if not self._current_user:
            return
        self._show_performance_onboarding_step(do_not_show_again=bool(do_not_show_again), skipped=False)

    @Slot()
    def completePerformanceSetupOnboarding(self) -> None:
        if not self._current_user:
            return
        updated_user = complete_user_onboarding(
            self._current_user["user_id"],
            do_not_show_again=bool(getattr(self, "_pending_onboarding_do_not_show_again", False)),
            skipped=bool(getattr(self, "_pending_onboarding_tour_skipped", False)),
        )
        if isinstance(updated_user, dict):
            self._current_user = updated_user
            user_signal = getattr(self, "currentUserChanged", None)
            if user_signal is not None and hasattr(user_signal, "emit"):
                user_signal.emit()
        self._finish_onboarding_dialog()
        self._maybe_prompt_passcode_setup_after_onboarding()
        self._set_status(self._status_text("onboarding_completed_msg"), "success")

    @Slot()
    def skipNewUserOnboarding(self) -> None:
        if not self._current_user:
            return
        self._show_performance_onboarding_step(do_not_show_again=False, skipped=True)
        self._set_status(self._status_text("onboarding_skipped_msg"), "info")


    def _current_face_user_id(self) -> str:
        current_user = getattr(self, "_current_user", None)
        if isinstance(current_user, dict):
            return str(current_user.get("user_id") or current_user.get("username") or current_user.get("email") or "").strip()
        return ""

    def _face_service(self):
        return self._face_runtime_service()

    def _face_runtime_service(self):
        factory = getattr(self, "_identity_confirmation_service_factory", None)
        if callable(factory):
            return factory()
        from identity_confirmation import build_default_identity_confirmation_service

        return build_default_identity_confirmation_service()

    def _face_enrollment_service(self):
        return self._face_runtime_service()

    def _coerce_backend_face_camera_index(self, value: Any) -> int:
        try:
            index = int(value)
        except (TypeError, ValueError):
            index = 0
        return max(BACKEND_FACE_CAMERA_MIN_INDEX, min(BACKEND_FACE_CAMERA_MAX_INDEX, index))

    def _get_backend_face_camera_index_value(self) -> int:
        settings = getattr(self, "_app_settings", {}) if isinstance(getattr(self, "_app_settings", {}), dict) else {}
        if "backend_face_camera_index" in settings:
            raw_value = settings.get("backend_face_camera_index", 0)
        else:
            instance_values = getattr(self, "__dict__", {}) if isinstance(getattr(self, "__dict__", {}), dict) else {}
            raw_value = instance_values.get("_backend_face_camera_index_value", instance_values.get("_backend_face_camera_index", 0))
        if callable(raw_value):
            raw_value = raw_value()
        return self._coerce_backend_face_camera_index(raw_value)

    def _backend_face_camera_index(self) -> int:
        return self._get_backend_face_camera_index_value()

    def _face_camera_provider(self):
        factory = getattr(self, "_face_camera_provider_factory", None)
        if callable(factory):
            return factory()
        from face_camera_provider import build_default_camera_provider

        return build_default_camera_provider(device_index=self._get_backend_face_camera_index_value())

    def _face_enrollment_capture_count(self, settings: Dict[str, Any]) -> int:
        try:
            requested = int((settings or {}).get("face_enrollment_frame_count", FACE_ENROLLMENT_DEFAULT_FRAME_COUNT) or FACE_ENROLLMENT_DEFAULT_FRAME_COUNT)
        except (TypeError, ValueError):
            requested = FACE_ENROLLMENT_DEFAULT_FRAME_COUNT
        return max(FACE_ENROLLMENT_MIN_FRAME_COUNT, min(FACE_ENROLLMENT_MAX_FRAME_COUNT, requested))

    def _face_verification_capture_count(self, settings: Dict[str, Any]) -> int:
        try:
            requested = int((settings or {}).get("face_verification_frame_count", FACE_VERIFICATION_DEFAULT_FRAME_COUNT) or FACE_VERIFICATION_DEFAULT_FRAME_COUNT)
        except (TypeError, ValueError):
            requested = FACE_VERIFICATION_DEFAULT_FRAME_COUNT
        return max(FACE_VERIFICATION_MIN_FRAME_COUNT, min(FACE_VERIFICATION_MAX_FRAME_COUNT, requested))

    def _face_model_readiness_state(self) -> Dict[str, Any]:
        # Tests and alternate backends can inject a complete service factory.  The
        # real app path below remains model-file validated before capture.
        if callable(getattr(self, "_identity_confirmation_service_factory", None)):
            return {"ok": True, "status": "models_ready", "reason": "models_ready"}
        try:
            from face_biometrics import (
                FACE_DETECTOR_MODEL_MISSING,
                FACE_MODELS_INVALID,
                FACE_MODELS_MISSING,
                FACE_MODELS_READY,
                FACE_RECOGNIZER_MODEL_MISSING,
                LEGACY_FACE_MODELS_CONFIGURED,
                LEGACY_FACE_MODELS_MISSING,
                validate_face_model_config,
            )

            status = dict(validate_face_model_config() or {})
        except Exception:
            return {"ok": False, "status": "face_models_invalid", "reason": "model_invalid"}
        model_status = str(status.get("status") or "face_models_invalid").strip().lower()
        missing_reasons = {
            FACE_MODELS_MISSING,
            FACE_DETECTOR_MODEL_MISSING,
            FACE_RECOGNIZER_MODEL_MISSING,
            LEGACY_FACE_MODELS_MISSING,
        }
        if bool(status.get("ok", False)):
            return {"ok": True, "status": FACE_MODELS_READY if model_status in {FACE_MODELS_READY, LEGACY_FACE_MODELS_CONFIGURED} else model_status, "reason": FACE_MODELS_READY}
        if model_status in missing_reasons:
            if model_status == LEGACY_FACE_MODELS_MISSING:
                model_status = FACE_MODELS_MISSING
            return {"ok": False, "status": model_status, "reason": model_status}
        if model_status == FACE_MODELS_INVALID:
            return {"ok": False, "status": model_status, "reason": "model_invalid"}
        return {"ok": False, "status": model_status or "face_models_invalid", "reason": "model_invalid"}

    def _face_camera_readiness_state(self, *, check: bool) -> Dict[str, Any]:
        backend_camera_index = self._get_backend_face_camera_index_value()
        now = time.monotonic()
        cached = getattr(self, "_face_camera_availability_cache", None)
        if isinstance(cached, dict):
            try:
                age = now - float(cached.get("checked_at", 0.0) or 0.0)
            except Exception:
                age = 999999.0
            if age <= FACE_CAMERA_AVAILABILITY_TTL_SEC or not check:
                state = dict(cached.get("state") or {})
                state.setdefault("backend_camera_index", backend_camera_index)
                return state
        if not check:
            return {
                "ok": False,
                "status": "not_checked",
                "reason": "not_checked",
                "backend_camera_index": backend_camera_index,
                "camera_unavailable": False,
            }
        start = time.monotonic()
        result: Dict[str, Any]
        try:
            provider = self._face_camera_provider()
            if provider is None:
                result = {"ok": False, "status": "camera_unavailable", "reason": "camera_provider_unavailable", "backend_camera_index": backend_camera_index, "camera_unavailable": True}
            elif hasattr(provider, "availability_status"):
                try:
                    availability = provider.availability_status(read_first_frame=True)
                except TypeError:
                    availability = provider.availability_status()
                if hasattr(availability, "to_safe_dict"):
                    safe = dict(availability.to_safe_dict() or {})
                else:
                    safe = {
                        "ok": bool(getattr(availability, "ok", False)),
                        "status": str(getattr(availability, "status", "camera_unavailable") or "camera_unavailable"),
                        "reason": str(getattr(availability, "reason", "camera_unavailable") or "camera_unavailable"),
                        "frame_count": int(getattr(availability, "frame_count", 0) or 0),
                    }
                camera_status = str(safe.get("status") or "camera_unavailable").strip().lower()
                camera_ok = bool(safe.get("ok", False)) and camera_status not in FACE_CAMERA_UNAVAILABLE_STATUSES
                result = {
                    "ok": camera_ok,
                    "status": camera_status if camera_status else ("camera_ready" if camera_ok else "camera_unavailable"),
                    "reason": "ready" if camera_ok else str(safe.get("reason") or camera_status or "camera_unavailable").strip().lower(),
                    **self._face_safe_camera_diagnostics(safe),
                }
            else:
                result = {"ok": True, "status": "camera_ready", "reason": "ready", "backend_camera_index": backend_camera_index}
        except Exception:
            result = {"ok": False, "status": "camera_unavailable", "reason": "camera_provider_unavailable", "backend_camera_index": backend_camera_index, "camera_unavailable": True}
        result.setdefault("backend_camera_index", backend_camera_index)
        result.setdefault("elapsed_ms", int((time.monotonic() - start) * 1000))
        self._face_camera_availability_cache = {"checked_at": now, "state": dict(result)}
        LOGGER.info("face_camera_check_finished %s", {k: v for k, v in result.items() if k not in {"frame", "frames", "image", "images"}})
        return dict(result)

    def _face_safe_camera_diagnostics(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        diagnostics: Dict[str, Any] = {}
        diagnostics["backend_camera_index"] = self._coerce_backend_face_camera_index(payload.get("backend_camera_index", self._get_backend_face_camera_index_value()))
        for key in ("camera_opened", "camera_unavailable", "frame_read_ok", "first_frame_ok", "cv2_import_ok"):
            if key in payload:
                diagnostics[key] = bool(payload.get(key, False))
        for key in ("warmup_frames_read", "capture_attempts", "elapsed_ms", "camera_open_elapsed_ms", "first_frame_elapsed_ms", "selected_index", "working_index"):
            if key in payload:
                try:
                    diagnostics[key] = max(0, int(payload.get(key, 0) or 0))
                except (TypeError, ValueError):
                    diagnostics[key] = 0
        for key in ("backend", "backend_name", "backend_tried", "failure_reason"):
            if key in payload and payload.get(key) is not None:
                diagnostics[key] = str(payload.get(key))[:96]
        if "frame_shape" in payload:
            shape = payload.get("frame_shape") or ()
            if isinstance(shape, (list, tuple)):
                try:
                    diagnostics["frame_shape"] = tuple(int(part) for part in shape)
                except (TypeError, ValueError):
                    diagnostics["frame_shape"] = ()
        return diagnostics

    def _face_availability_reason(self, *, feature_enabled: bool, model_ready: bool, model_reason: str, consent_granted: bool, camera_ready: bool, camera_reason: str, signed_in: bool, template_enrolled: bool | None = None, preference_enabled: bool | None = None) -> str:
        if not signed_in:
            return "signed_out"
        if not feature_enabled:
            return "feature_disabled"
        if not model_ready:
            if model_reason in {"models_missing", "detector_model_missing", "recognizer_model_missing", "model_missing", "face_models_missing"}:
                return "models_missing" if model_reason in {"model_missing", "face_models_missing"} else model_reason
            return "model_invalid"
        if not consent_granted:
            return "consent_required"
        if template_enrolled is not None and not template_enrolled:
            return "template_missing"
        if preference_enabled is not None and not preference_enabled:
            return "disabled"
        if not camera_ready:
            return "not_checked" if camera_reason == "not_checked" else "camera_unavailable"
        return "ready"

    def _face_status_from_availability_reason(self, reason: str) -> str:
        return FACE_AVAILABILITY_TO_STATUS.get(str(reason or "").strip().lower(), "failed")

    def _face_backend_failure_result(self, exc: Exception) -> Dict[str, Any]:
        reason = str(exc or "failed").strip().lower() or "failed"
        status = reason if reason in FACE_MODEL_FAILURE_STATUSES else "camera_unavailable" if reason in {"opencv_unavailable", "face_engine_unavailable", "opencv_face_api_unavailable"} else "failed"
        return {"status": status, "ok": False, "reason": reason, "rawImagesStored": False}

    def _face_capture_failure_result(self, capture: Any) -> Dict[str, Any]:
        if hasattr(capture, "to_safe_dict"):
            safe = dict(capture.to_safe_dict() or {})
        else:
            safe = {
                "status": str(getattr(capture, "status", "camera_unavailable") or "camera_unavailable"),
                "reason": str(getattr(capture, "reason", "camera_unavailable") or "camera_unavailable"),
                "frame_count": int(getattr(capture, "frame_count", 0) or 0),
            }
        capture_status = str(safe.get("status") or "camera_unavailable")
        capture_reason = str(safe.get("reason") or capture_status)
        result = {
            "status": "camera_unavailable",
            "ok": False,
            "reason": capture_reason,
            "captureStatus": capture_status,
            "frameCount": int(safe.get("frame_count") or 0),
            **self._face_safe_camera_diagnostics(safe),
            "rawImagesStored": False,
        }
        if capture_status in {"camera_unavailable", "device_open_failed", "permission_or_device_open_failure", "permission_denied"} or capture_reason in {"camera_unavailable", "device_open_failed", "permission_or_device_open_failure", "permission_denied"}:
            result["detailKey"] = "face_detail_backend_capture_open_failed"
        return result

    def _normalize_face_enrollment_result(self, result: Dict[str, Any], *, capture_status: str = "", frame_count: int = 0, capture_diagnostics: Dict[str, Any] | None = None) -> Dict[str, Any]:
        safe = dict(result or {})
        for forbidden in ("embedding", "frame", "frames", "image", "images", "source_frame_paths"):
            safe.pop(forbidden, None)
        status = str(safe.get("status") or "failed").strip().lower() or "failed"
        reason = str(safe.get("reason") or status).strip().lower()
        if status == "camera_unavailable" and reason in FACE_MODEL_FAILURE_STATUSES:
            status = reason
        elif status == "quality_rejected" and reason in FACE_QUALITY_FAILURE_STATUS_BY_REASON:
            status = FACE_QUALITY_FAILURE_STATUS_BY_REASON[reason]
        safe["status"] = status
        safe.setdefault("ok", False)
        safe.setdefault("reason", reason)
        safe.setdefault("captureStatus", capture_status)
        safe.setdefault("frameCount", int(frame_count))
        safe.update(self._face_safe_camera_diagnostics(capture_diagnostics or {}))
        if bool(safe.get("ok", False)) and status in {"enrolled", "enrollment_success"}:
            safe.setdefault("enrollmentStatus", "enrollment_success")
            safe.setdefault("operationDisplayStatus", "enrollment_success")
        elif not bool(safe.get("ok", False)):
            safe.setdefault("enrollmentStatus", "enrollment_failed")
        safe.setdefault("rawImagesStored", False)
        return safe

    def _normalize_face_verification_result(self, result: Dict[str, Any], *, capture_status: str = "", frame_count: int = 0, capture_diagnostics: Dict[str, Any] | None = None) -> Dict[str, Any]:
        safe = dict(result or {})
        for forbidden in ("embedding", "template_digest", "frame", "frames", "image", "images", "source_frame_paths", "score", "threshold", "quality_score"):
            safe.pop(forbidden, None)
        status = str(safe.get("status") or "failed").strip().lower() or "failed"
        reason = str(safe.get("reason") or status).strip().lower()
        if status == "camera_unavailable" and reason in FACE_MODEL_FAILURE_STATUSES:
            status = reason
        elif status == "quality_rejected" and reason in FACE_QUALITY_FAILURE_STATUS_BY_REASON:
            status = FACE_QUALITY_FAILURE_STATUS_BY_REASON[reason]
        if status == "failed":
            status = "verification_failed"
        verified = bool(safe.get("verified", False)) and status in {"verified", "verified_owner"}
        safe["status"] = status
        safe["verified"] = verified
        safe.setdefault("ok", verified)
        safe.setdefault("reason", reason)
        safe.setdefault("captureStatus", capture_status)
        safe.setdefault("frameCount", int(frame_count))
        safe.update(self._face_safe_camera_diagnostics(capture_diagnostics or {}))
        if verified:
            safe.setdefault("verificationStatus", "verified")
            safe.setdefault("operationDisplayStatus", "verified")
        elif status == "not_verified":
            safe.setdefault("verificationStatus", "not_verified")
            safe.setdefault("operationDisplayStatus", "not_verified")
        elif status == "verification_failed":
            safe.setdefault("verificationStatus", "verification_failed")
            safe.setdefault("operationDisplayStatus", "verification_failed")
        else:
            safe.setdefault("verificationStatus", "not_verified")
        safe["rawImagesStored"] = False
        safe["lockIntegrationEnabled"] = False
        safe["lock_integration_enabled"] = False
        return safe

    def _face_status_for_current_user(self) -> Dict[str, Any]:
        user_id = self._current_face_user_id()
        if not user_id:
            return {"status": "signed_out", "enrolled": False, "ok": False}
        try:
            from face_template_store import FaceTemplateStore

            status = FaceTemplateStore().status(user_id)
            return dict(status) if isinstance(status, dict) else {"status": "unavailable", "enrolled": False, "ok": False}
        except Exception as exc:
            return {"status": "error", "enrolled": False, "ok": False, "reason": str(exc)}

    def _face_state_text_key(self, status: str) -> str:
        mapping = {
            "enrolled": "face_status_enrolled", "not_enrolled": "face_status_not_enrolled",
            "signed_out": "face_status_signed_out", "camera_unavailable": "face_status_camera_unavailable",
            "models_missing": "face_status_model_missing", "detector_model_missing": "face_status_detector_model_missing",
            "recognizer_model_missing": "face_status_recognizer_model_missing",
            "face_models_missing": "face_status_model_missing", "face_models_invalid": "face_status_model_invalid",
            "consent_required": "face_status_consent_required", "quality_rejected": "face_status_quality_rejected",
            "no_face_detected": "face_status_no_face_detected", "multiple_faces_detected": "face_status_multiple_faces_detected",
            "poor_quality": "face_status_poor_quality",
            "enrollment_started": "face_status_enrollment_started",
            "checking_camera": "face_status_checking_camera",
            "camera_ready": "face_camera_ready_backend_owned",
            "not_checked": "face_camera_not_checked",
            "capturing": "face_status_capturing",
            "operation_in_progress": "face_status_operation_in_progress",
            "enrollment_success": "face_status_enrollment_success",
            "enrollment_failed": "face_status_enrollment_failed",
            "verified": "face_status_verification_succeeded", "verified_owner": "face_status_verification_succeeded",
            "not_verified": "face_status_verification_failed",
            "verification_failed": "face_status_verification_failed",
            "consent_granted": "face_consent_recorded", "enabled": "face_confirmation_enabled",
            "face_feature_enabled": "face_feature_enabled", "face_feature_disabled": "face_feature_disabled",
            "feature_disabled": "face_feature_unavailable",
            "unavailable": "face_feature_unavailable",
            "deleted": "face_status_deleted", "failed": "face_status_failed", "error": "face_status_failed",
            "disabled": "face_confirmation_disabled",
        }
        return mapping.get(str(status or "").strip().lower(), "face_status_not_enrolled")

    def _face_availability_display(self, reason: str) -> Dict[str, Any]:
        """Return privacy-safe, backend-owned display text for one face action gate."""

        normalized = str(reason or "").strip().lower() or "feature_disabled"
        status = self._face_status_from_availability_reason(normalized)
        return {
            "reason": normalized,
            "status": status,
            "text": self._status_text(self._face_state_text_key(status)),
            "detail": self._status_text(self._face_status_detail_key(status, reason=normalized)),
            "tone": self._face_status_tone(status, ok=(normalized == "ready")),
        }

    def _face_status_detail_key(self, status: str, *, reason: str = "", capture_status: str = "") -> str:
        normalized_status = str(status or "").strip().lower()
        normalized_reason = str(reason or "").strip().lower()
        normalized_capture = str(capture_status or "").strip().lower()
        capture_or_reason = normalized_capture or normalized_reason
        if normalized_status == "camera_unavailable":
            if capture_or_reason in {"device_open_failed", "permission_or_device_open_failure", "permission_denied"}:
                return "face_detail_permission_device_failure"
            if capture_or_reason in {"opencv_unavailable", "camera_provider_unavailable", "camera_capture_exception"}:
                return "face_detail_camera_unavailable"
            if capture_or_reason in {"no_frame_captured", "capture_timeout"}:
                return "face_detail_camera_no_frame"
            return "face_detail_camera_unavailable"
        mapping = {
            "models_missing": "face_detail_model_missing",
            "detector_model_missing": "face_detail_detector_model_missing",
            "recognizer_model_missing": "face_detail_recognizer_model_missing",
            "face_models_missing": "face_detail_model_missing",
            "face_models_invalid": "face_detail_model_invalid",
            "no_face_detected": "face_detail_no_face_detected",
            "multiple_faces_detected": "face_detail_multiple_faces_detected",
            "poor_quality": "face_detail_poor_quality",
            "enrollment_started": "face_detail_enrollment_started",
            "checking_camera": "face_detail_checking_camera",
            "camera_ready": "face_camera_backend_owned_detail",
            "not_checked": "face_detail_camera_not_checked",
            "capturing": "face_detail_capturing",
            "operation_in_progress": "face_detail_capturing",
            "enrollment_success": "face_detail_enrollment_complete",
            "enrollment_failed": "face_detail_failed_safe",
            "quality_rejected": "face_detail_quality_rejected",
            "enrolled": "face_detail_enrollment_complete",
            "verified": "face_detail_verification_succeeded",
            "verified_owner": "face_detail_verification_succeeded",
            "not_verified": "face_detail_verification_failed",
            "verification_failed": "face_detail_verification_failed",
            "not_enrolled": "face_detail_not_enrolled",
            "consent_required": "face_detail_consent_required",
            "disabled": "face_detail_disabled",
            "signed_out": "face_detail_signed_out",
            "feature_disabled": "face_detail_feature_unavailable",
            "unavailable": "face_detail_feature_unavailable",
            "failed": "face_detail_failed_safe",
            "error": "face_detail_failed_safe",
            "deleted": "face_detail_template_deleted",
            "enabled": "face_detail_enabled",
            "consent_granted": "face_detail_consent_recorded",
            "face_feature_enabled": "face_detail_feature_enabled",
            "face_feature_disabled": "face_detail_feature_disabled",
        }
        return mapping.get(normalized_status, "face_detail_idle")

    def _face_status_tone(self, status: str, *, ok: bool = False, enrolled: bool = False) -> str:
        normalized = str(status or "").strip().lower()
        if normalized in {"verified", "verified_owner", "enrolled", "enrollment_success", "consent_granted", "enabled", "deleted", "face_feature_enabled"} and bool(ok or enrolled):
            return "success"
        if normalized in {"idle", "not_enrolled", "disabled", "signed_out", "enrollment_started", "checking_camera", "not_checked", "camera_ready", "capturing"}:
            return "neutral"
        return "warn"

    def _face_camera_status_text_key(self, camera_status: str, *, consent_granted: bool = False) -> str:
        normalized = str(camera_status or "").strip().lower()
        if normalized in {"not_checked", "waiting_for_consent"}:
            return "face_camera_not_checked"
        if normalized in {"checking_camera"}:
            return "face_status_checking_camera"
        if normalized in {"device_open_failed", "permission_or_device_open_failure", "permission_denied"}:
            return "face_camera_permission_device_failure"
        if normalized in {"no_frame_captured", "capture_timeout"}:
            return "face_camera_no_frame"
        if normalized in {"camera_unavailable", "opencv_unavailable", "camera_provider_unavailable", "camera_capture_exception"}:
            return "face_status_camera_unavailable"
        if normalized in {"captured", "camera_ready", "available"}:
            return "face_camera_captured" if normalized == "captured" else "face_camera_ready_backend_owned"
        if consent_granted:
            return "face_camera_ready_backend_owned"
        return "face_camera_waiting_for_consent"

    def _build_face_confirmation_state(self) -> Dict[str, Any]:
        settings = getattr(self, "_app_settings", {}) if isinstance(getattr(self, "_app_settings", {}), dict) else {}
        signed_in = bool(self._current_face_user_id())
        enrollment_feature = feature_flag_enabled(settings, "enable_face_enrollment")
        confirmation_feature = feature_flag_enabled(settings, "enable_face_confirmation")
        consent_granted = bool(has_current_face_template_consent(settings))
        enabled_preference = bool(getattr(self, "_face_confirmation_enabled", False) or settings.get("face_confirmation_enabled", False))
        status = self._face_status_for_current_user()
        operation = getattr(self, "_face_confirmation_operation_state", {})
        operation = dict(operation) if isinstance(operation, dict) else {"status": "idle", "ok": True}
        enrolled = bool(status.get("enrolled", False))

        model_state = self._face_model_readiness_state() if bool(enrollment_feature or confirmation_feature) else {"ok": False, "status": "not_checked", "reason": "feature_disabled"}
        model_ready = bool(model_state.get("ok", False))
        model_reason = str(model_state.get("reason") or "model_invalid").strip().lower()

        # Camera availability is cached only. QML state reads must never open the
        # camera or import/load face recognition runtime objects. Explicit user
        # actions such as Check Camera, enrollment, or Test Face Confirmation own
        # any camera access.
        enrollment_pre_camera_reason = self._face_availability_reason(
            feature_enabled=bool(enrollment_feature),
            model_ready=model_ready,
            model_reason=model_reason,
            consent_granted=consent_granted,
            camera_ready=True,
            camera_reason="ready",
            signed_in=signed_in,
        )
        confirmation_pre_camera_reason = self._face_availability_reason(
            feature_enabled=bool(confirmation_feature),
            model_ready=model_ready,
            model_reason=model_reason,
            consent_granted=consent_granted,
            camera_ready=True,
            camera_reason="ready",
            signed_in=signed_in,
            template_enrolled=enrolled,
            preference_enabled=enabled_preference,
        )
        camera_state = self._face_camera_readiness_state(check=False)
        camera_ready = bool(camera_state.get("ok", False))
        camera_reason = str(camera_state.get("reason") or camera_state.get("status") or "not_checked").strip().lower()
        camera_status = str(camera_state.get("status") or "not_checked").strip().lower()

        enrollment_reason = self._face_availability_reason(
            feature_enabled=bool(enrollment_feature),
            model_ready=model_ready,
            model_reason=model_reason,
            consent_granted=consent_granted,
            camera_ready=camera_ready,
            camera_reason=camera_reason,
            signed_in=signed_in,
        )
        confirmation_reason = self._face_availability_reason(
            feature_enabled=bool(confirmation_feature),
            model_ready=model_ready,
            model_reason=model_reason,
            consent_granted=consent_granted,
            camera_ready=camera_ready,
            camera_reason=camera_reason,
            signed_in=signed_in,
            template_enrolled=enrolled,
            preference_enabled=enabled_preference,
        )
        operation_status = str(operation.get("status") or "").strip().lower()
        operation_display_status = str(operation.get("operationDisplayStatus") or "").strip().lower()
        if not operation_display_status and bool(operation.get("ok", False)) and operation_status == "enrolled":
            operation_display_status = "enrollment_success"
        if operation_display_status:
            current_status = operation_display_status
        elif operation_status and operation_status != "idle":
            current_status = operation_status
        elif confirmation_feature:
            current_status = self._face_status_from_availability_reason(confirmation_reason)
        elif enrollment_feature:
            current_status = self._face_status_from_availability_reason(enrollment_reason)
        else:
            current_status = "feature_disabled"
        capture_status = str(operation.get("captureStatus") or "")
        reason = str(operation.get("reason") or "")
        backend_camera_index = self._get_backend_face_camera_index_value()
        status_text = self._status_text(self._face_state_text_key(current_status))
        operation_detail_key = str(operation.get("detailKey") or "").strip()
        status_detail = self._status_text(operation_detail_key) if operation_detail_key else self._status_text(self._face_status_detail_key(current_status, reason=reason, capture_status=capture_status))
        effective_camera_status = capture_status or (camera_status if camera_status != "not_checked" else ("waiting_for_consent" if not consent_granted else "camera_ready" if camera_ready else "not_checked"))
        camera_available = bool(camera_ready) and effective_camera_status not in FACE_CAMERA_UNAVAILABLE_STATUSES
        status_tone = self._face_status_tone(current_status, ok=bool(operation.get("ok", False)) or confirmation_reason == "ready" or enrollment_reason == "ready", enrolled=enrolled)
        enrollment_display = self._face_availability_display(enrollment_reason)
        confirmation_display = self._face_availability_display(confirmation_reason)
        return {
            "available": bool(enrollment_pre_camera_reason == "ready" or confirmation_pre_camera_reason == "ready"),
            "enrollmentFeatureEnabled": bool(enrollment_feature),
            "confirmationFeatureEnabled": bool(confirmation_feature),
            "faceEnrollmentFeatureEnabled": bool(enrollment_feature),
            "faceConfirmationFeatureEnabled": bool(confirmation_feature),
            "faceBuildProfileGateEnabled": bool(enrollment_feature or confirmation_feature),
            "enabled": bool(enabled_preference and confirmation_feature),
            "enabledPreference": enabled_preference,
            "consentGranted": consent_granted,
            "faceConsentGranted": consent_granted,
            "enrolled": enrolled,
            "faceTemplateEnrolled": enrolled,
            "status": str(status.get("status") or "not_enrolled"),
            "operationStatus": current_status,
            "operationReason": str(reason or confirmation_reason or enrollment_reason),
            "operationKind": str(operation.get("operationKind") or ""),
            "faceOperationInFlight": bool(operation.get("faceOperationInFlight", operation.get("operationInFlight", False))),
            "operationInFlight": bool(operation.get("faceOperationInFlight", operation.get("operationInFlight", False))),
            "statusText": status_text,
            "statusDetail": status_detail,
            "statusTone": status_tone,
            "canGrantConsent": bool(signed_in),
            "canEnable": bool(confirmation_pre_camera_reason in {"ready", "disabled"}),
            "canCheckCamera": bool(enrollment_pre_camera_reason == "ready" or confirmation_pre_camera_reason == "ready"),
            "canEnroll": bool(enrollment_pre_camera_reason == "ready"),
            "canTest": bool(confirmation_pre_camera_reason == "ready"),
            "canDelete": bool(enrolled),
            "faceEnrollmentAvailable": bool(enrollment_pre_camera_reason == "ready"),
            "faceConfirmationAvailable": bool(confirmation_pre_camera_reason == "ready"),
            "faceEnrollmentUnavailableReason": str(enrollment_reason),
            "faceConfirmationUnavailableReason": str(confirmation_reason),
            "faceEnrollmentPreCameraReason": str(enrollment_pre_camera_reason),
            "faceConfirmationPreCameraReason": str(confirmation_pre_camera_reason),
            "faceEnrollmentStatusText": str(enrollment_display.get("text") or ""),
            "faceEnrollmentStatusDetail": str(enrollment_display.get("detail") or ""),
            "faceEnrollmentStatusTone": str(enrollment_display.get("tone") or "neutral"),
            "faceConfirmationStatusText": str(confirmation_display.get("text") or ""),
            "faceConfirmationStatusDetail": str(confirmation_display.get("detail") or ""),
            "faceConfirmationStatusTone": str(confirmation_display.get("tone") or "neutral"),
            "faceModelReady": bool(model_ready),
            "faceModelStatus": str(model_state.get("status") or "not_checked"),
            "faceModelReason": str(model_reason),
            "faceCameraAvailable": camera_available,
            "cameraAvailable": camera_available,
            "cameraStatus": effective_camera_status,
            "faceCameraStatus": effective_camera_status,
            "cameraStatusText": self._status_text(self._face_camera_status_text_key(effective_camera_status, consent_granted=consent_granted)),
            "cameraStatusDetail": self._status_text("face_camera_backend_owned_detail"),
            "backendFaceCameraIndex": backend_camera_index,
            "backendCameraIndex": backend_camera_index,
            "faceCameraIndex": backend_camera_index,
            "backendCameraIndexMin": BACKEND_FACE_CAMERA_MIN_INDEX,
            "backendCameraIndexMax": BACKEND_FACE_CAMERA_MAX_INDEX,
            "cameraDiagnostics": self._face_safe_camera_diagnostics({**dict(camera_state or {}), **dict(operation or {})}),
            "needsReEnrollment": str(status.get("status") or "") in {"error", "needs_reenrollment"},
            "lastResult": operation,
            "rawImagesStored": False,
            "lockIntegrationEnabled": False,
            "message": status_text,
            "detailMessage": status_detail,
        }

    def _set_face_confirmation_cached_state(self, state: Dict[str, Any] | None = None, *, emit: bool = False) -> Dict[str, Any]:
        if state is None:
            state = self._build_face_confirmation_state()
        cached = dict(state or {})
        cached.setdefault("rawImagesStored", False)
        cached.setdefault("lockIntegrationEnabled", False)
        self._face_confirmation_cached_state = cached
        if emit:
            signal = getattr(self, "faceConfirmationChanged", None)
            if signal is not None and hasattr(signal, "emit"):
                signal.emit()
        return dict(cached)

    def _refresh_face_confirmation_state(self, reason: str = "refresh", *, check_camera: bool = False, async_camera: bool = False) -> Dict[str, Any]:
        if async_camera or check_camera:
            return self.requestFaceCameraCheck()
        return self._set_face_confirmation_cached_state(self._build_face_confirmation_state(), emit=True)

    def _emit_face_confirmation_changed(self) -> None:
        try:
            self._set_face_confirmation_cached_state(self._build_face_confirmation_state(), emit=False)
        except Exception:
            cached = getattr(self, "_face_confirmation_cached_state", None)
            if not isinstance(cached, dict):
                self._face_confirmation_cached_state = {"status": "unavailable", "available": False, "cameraStatus": "not_checked", "cameraAvailable": False, "rawImagesStored": False, "lockIntegrationEnabled": False}
        signal = getattr(self, "faceConfirmationChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()

    def _set_face_status_message(self, message: str, tone: str = "info") -> bool:
        previous = bool(getattr(self, "_face_status_update_allowed", False))
        self._face_status_update_allowed = True
        try:
            return bool(self._set_status(message, tone))
        finally:
            self._face_status_update_allowed = previous

    def _set_face_operation_state(self, payload: Dict[str, Any]) -> None:
        safe_payload = dict(payload or {})
        for forbidden in ("embedding", "template_digest", "frame", "frames", "image", "images", "source_frame_paths", "score", "threshold", "quality_score"):
            safe_payload.pop(forbidden, None)
        safe_payload.setdefault("rawImagesStored", False)
        safe_payload.setdefault("lockIntegrationEnabled", False)
        normalized_status = str(safe_payload.get("status") or "").strip().lower()
        in_flight = bool(safe_payload.get("faceOperationInFlight", safe_payload.get("operationInFlight", normalized_status in {"checking_camera", "capturing", "enrollment_started", "verification_started", "operation_in_progress"})))
        safe_payload["faceOperationInFlight"] = in_flight
        safe_payload["operationInFlight"] = in_flight
        self._face_confirmation_operation_state = safe_payload
        self._emit_face_confirmation_changed()


    def _set_face_feature_flag(self, key: str, enabled: bool) -> Dict[str, Any]:
        if key not in {"enable_face_enrollment", "enable_face_confirmation"}:
            result = {"status": "failed", "ok": False, "reason": "unknown_feature", "rawImagesStored": False, "lockIntegrationEnabled": False}
            self._set_face_operation_state(result)
            return result
        requested = bool(enabled)
        changes: Dict[str, Any] = {key: requested}
        if key == "enable_face_confirmation" and not requested:
            # Disabling the backend feature also clears the pre-lock preference.
            # This is fail-closed and prevents a stale preference from silently
            # reactivating when the feature is toggled back on later.
            changes["face_confirmation_enabled"] = False
            self._face_confirmation_enabled = False
        self._app_settings = save_settings(self._settings_payload(**changes))
        feature_name = "face_enrollment" if key == "enable_face_enrollment" else "face_confirmation"
        status = "face_feature_enabled" if requested else "face_feature_disabled"
        result = {
            "status": status,
            "ok": True,
            "reason": "ready" if requested else "feature_disabled",
            "feature": feature_name,
            "enabled": requested,
            "rawImagesStored": False,
            "lockIntegrationEnabled": False,
        }
        self._set_face_operation_state(result)
        self._set_status(
            self._status_text(
                "face_enrollment_feature_enabled" if key == "enable_face_enrollment" and requested else
                "face_enrollment_feature_disabled" if key == "enable_face_enrollment" else
                "face_confirmation_feature_enabled" if requested else
                "face_confirmation_feature_disabled"
            ),
            "info",
        )
        return dict(result)

    @Slot(bool, result="QVariantMap")
    def setFaceEnrollmentFeatureEnabled(self, enabled: bool) -> Dict[str, Any]:
        return self._set_face_feature_flag("enable_face_enrollment", bool(enabled))

    @Slot(bool, result="QVariantMap")
    def setFaceConfirmationFeatureEnabled(self, enabled: bool) -> Dict[str, Any]:
        return self._set_face_feature_flag("enable_face_confirmation", bool(enabled))

    @Slot(int, result="QVariantMap")
    def setBackendFaceCameraIndex(self, index: int) -> Dict[str, Any]:
        selected = self._coerce_backend_face_camera_index(index)
        current = self._get_backend_face_camera_index_value()
        self._backend_face_camera_index_value = selected
        self.__dict__.pop("_backend_face_camera_index", None)
        if selected != current:
            self._app_settings = save_settings(self._settings_payload(backend_face_camera_index=selected))
            self._face_camera_availability_cache = None
        result = {
            "status": "backend_camera_index_saved",
            "ok": True,
            "reason": "backend_camera_index_saved",
            "backend_camera_index": selected,
            "cameraStatus": "not_checked",
            "cameraAvailable": False,
            "rawImagesStored": False,
            "lockIntegrationEnabled": False,
        }
        self._set_face_operation_state(result)
        self._set_status(self._status_text("face_backend_camera_index_saved", index=selected), "info")
        self._emit_face_confirmation_changed()
        return dict(result)

    @Slot(int, result="QVariantMap")
    def setFaceCameraIndex(self, index: int) -> Dict[str, Any]:
        return self.setBackendFaceCameraIndex(index)

    @Slot(result="QVariantMap")
    def refreshFaceConfirmationState(self) -> Dict[str, Any]:
        """Refresh backend-owned face readiness without capturing or persisting images."""

        self._face_confirmation_operation_state = {
            "status": "idle",
            "ok": True,
            "reason": "refresh",
            "rawImagesStored": False,
            "lockIntegrationEnabled": False,
        }
        state = self._set_face_confirmation_cached_state(self._build_face_confirmation_state(), emit=True)
        try:
            self._set_status(str(state.get("statusText") or self._status_text("face_page_status_title")), str(state.get("statusTone") or "info"))
        except Exception:
            pass
        return dict(state)

    @Slot(result="QVariantMap")
    def prepareFaceBackendCapture(self) -> Dict[str, Any]:
        """Invalidate stale backend camera availability before an explicit capture request."""

        return self._refresh_face_confirmation_state("prepare_face_backend_capture", check_camera=False)

    @Slot(result="QVariantMap")
    def requestFaceCameraCheck(self) -> Dict[str, Any]:
        """Explicit, async camera readiness check. Never called from QML state reads."""

        if bool(getattr(self, "_face_operation_inflight", False)):
            result = {
                "status": "operation_in_progress",
                "ok": False,
                "reason": "operation_in_progress",
                "operationKind": "camera_check",
                "faceOperationInFlight": True,
                "operationInFlight": True,
                "rawImagesStored": False,
                "lockIntegrationEnabled": False,
            }
            self._set_face_operation_state(result)
            self._set_face_status_message(self._status_text("face_status_operation_in_progress"), "info")
            return dict(result)
        backend_camera_index = self._get_backend_face_camera_index_value()
        started = {
            "status": "checking_camera",
            "ok": False,
            "reason": "checking_camera",
            "operationKind": "camera_check",
            "operationDisplayStatus": "checking_camera",
            "backend_camera_index": backend_camera_index,
            "faceOperationInFlight": True,
            "operationInFlight": True,
            "rawImagesStored": False,
            "lockIntegrationEnabled": False,
        }
        LOGGER.info("face_camera_check_started %s", {"selected_camera_index": backend_camera_index})
        return self._start_face_operation(
            kind="camera_check",
            started=started,
            task=lambda: self._run_face_camera_check(backend_camera_index=backend_camera_index),
        )

    @Slot(result="QVariantMap")
    def checkFaceCamera(self) -> Dict[str, Any]:
        return self.requestFaceCameraCheck()

    def _run_face_camera_check(self, *, backend_camera_index: int) -> Dict[str, Any]:
        start = time.monotonic()
        result = self._face_camera_readiness_state(check=True)
        result.update({
            "operationKind": "camera_check",
            "operationDisplayStatus": "camera_ready" if bool(result.get("ok")) else "camera_unavailable",
            "faceOperationInFlight": False,
            "operationInFlight": False,
            "rawImagesStored": False,
            "lockIntegrationEnabled": False,
            "elapsed_ms": int((time.monotonic() - start) * 1000),
            "selected_camera_index": int(backend_camera_index),
        })
        result["status"] = "camera_ready" if bool(result.get("ok")) else "camera_unavailable"
        result["reason"] = "ready" if bool(result.get("ok")) else str(result.get("reason") or "camera_unavailable")
        return result

    @Slot()
    def grantFaceTemplateConsent(self) -> None:
        if not self._current_face_user_id():
            self._set_face_operation_state({"status": "signed_out", "ok": False})
            self._set_status(self._status_text("face_status_signed_out"), "warn")
            return
        fields = build_face_template_consent_fields(True)
        self._face_template_consent_granted = bool(fields.get("face_template_consent_granted", False))
        self._face_template_consent_policy_version = str(fields.get("face_template_consent_policy_version", "") or "")
        self._face_template_consent_timestamp = str(fields.get("face_template_consent_timestamp", "") or "")
        self._app_settings = save_settings(self._settings_payload(**fields))
        self._set_face_operation_state({"status": "consent_granted", "ok": True})
        self._set_status(self._status_text("face_consent_granted"), "info")

    def _face_async_operations_enabled(self) -> bool:
        if str(os.environ.get("BIOAUTH_FACE_OPERATIONS_SYNC", "")).strip().lower() in {"1", "true", "yes", "on"}:
            return False
        if _FaceOperationWorker is None or _FaceQtThreadPool is None or _FaceQtCoreApplication is None:
            return False
        try:
            return _FaceQtCoreApplication.instance() is not None
        except Exception:
            return False

    def _face_operation_started_result(self, *, kind: str, status: str = "capturing", requested_count: int = 0) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": status,
            "ok": False,
            "reason": status,
            "operationKind": str(kind or "face"),
            "faceOperationInFlight": True,
            "operationInFlight": True,
            "operationDisplayStatus": status,
            "backend_camera_index": self._get_backend_face_camera_index_value(),
            "rawImagesStored": False,
            "lockIntegrationEnabled": False,
        }
        if requested_count:
            result["requestedFrameCount"] = int(requested_count)
        return result

    def _finish_face_operation(self, result: Dict[str, Any]) -> Dict[str, Any]:
        self._face_operation_inflight = False
        returned = dict(result or {})
        state_payload = dict(returned)
        state_payload.setdefault("ok", False)
        state_payload.setdefault("rawImagesStored", False)
        state_payload.setdefault("lockIntegrationEnabled", False)
        state_payload["faceOperationInFlight"] = False
        state_payload["operationInFlight"] = False
        self._set_face_operation_state(state_payload)
        self._set_face_status_message(self._status_text(self._face_state_text_key(str(state_payload.get("status") or "failed"))), "success" if state_payload.get("ok") else "warn")
        return returned

    def _start_face_operation(self, *, kind: str, started: Dict[str, Any], task) -> Dict[str, Any]:
        if bool(getattr(self, "_face_operation_inflight", False)):
            result = {
                "status": "operation_in_progress",
                "ok": False,
                "reason": "operation_in_progress",
                "operationKind": str(kind or "face"),
                "faceOperationInFlight": True,
                "operationInFlight": True,
                "rawImagesStored": False,
                "lockIntegrationEnabled": False,
            }
            self._set_face_operation_state(result)
            self._set_face_status_message(self._status_text("face_status_operation_in_progress"), "info")
            return dict(result)
        started_payload = dict(started or {})
        started_payload.setdefault("operationKind", str(kind or "face"))
        started_payload["faceOperationInFlight"] = True
        started_payload["operationInFlight"] = True
        started_payload.setdefault("rawImagesStored", False)
        started_payload.setdefault("lockIntegrationEnabled", False)
        self._face_operation_inflight = True
        self._set_face_operation_state(started_payload)
        self._set_face_status_message(self._status_text(self._face_state_text_key(str(started_payload.get("status") or "capturing"))), "info")
        if not self._face_async_operations_enabled():
            try:
                result = dict(task() or {})
            except Exception as exc:
                result = {"status": "failed", "ok": False, "reason": str(exc or "failed"), "rawImagesStored": False, "lockIntegrationEnabled": False}
            self._face_operation_inflight = False
            return self._finish_face_operation(result)
        worker = _FaceOperationWorker(task)
        workers = getattr(self, "_face_operation_workers", None)
        if not isinstance(workers, list):
            workers = []
            self._face_operation_workers = workers
        workers.append(worker)

        def _on_finished(payload, worker_ref=worker):
            try:
                active_workers = getattr(self, "_face_operation_workers", [])
                if isinstance(active_workers, list) and worker_ref in active_workers:
                    active_workers.remove(worker_ref)
            except Exception:
                pass
            self._face_operation_inflight = False
            self._finish_face_operation(dict(payload or {}))

        worker.signals.finished.connect(_on_finished)
        _FaceQtThreadPool.globalInstance().start(worker)
        return dict(started_payload)

    def _run_face_enrollment_capture(self, *, user_id: str, requested_count: int) -> Dict[str, Any]:
        try:
            service = self._face_enrollment_service()
        except Exception as exc:
            return self._face_backend_failure_result(exc)
        try:
            capture = self._face_camera_provider().capture_enrollment_frames(requested_count)
            frame_count = int(getattr(capture, "frame_count", 0) or len(getattr(capture, "frames", ()) or ()))
            capture_status = str(getattr(capture, "status", "") or "")
            capture_safe = dict(capture.to_safe_dict() or {}) if hasattr(capture, "to_safe_dict") else {}
            if not bool(getattr(capture, "ok", False)) or frame_count < requested_count:
                return self._face_capture_failure_result(capture)
            frames = tuple(getattr(capture, "frames", ()) or ())
            enroll_method = getattr(service, "enroll")
            try:
                enrollment_payload = enroll_method(user_id, frames, consent_granted=True, min_samples=requested_count)
            except TypeError:
                enrollment_payload = enroll_method(user_id, frames, consent_granted=True)
            return self._normalize_face_enrollment_result(
                enrollment_payload,
                capture_status=capture_status,
                frame_count=frame_count,
                capture_diagnostics=capture_safe,
            )
        except Exception as exc:
            return {"status": "failed", "ok": False, "reason": str(exc), "enrollmentStatus": "enrollment_failed", "rawImagesStored": False}

    def _verify_captured_face_frames(self, service: Any, user_id: str, frames: tuple[Any, ...]) -> Dict[str, Any]:
        if hasattr(service, "test_verification_frames"):
            return dict(service.test_verification_frames(user_id, frames) or {})
        first_not_verified: Dict[str, Any] | None = None
        quality_reasons: list[str] = []
        usable_frame_count = 0
        for frame in frames:
            result = dict(service.test_verification(user_id, frame) or {})
            status = str(result.get("status") or "").strip().lower()
            reason = str(result.get("reason") or status).strip().lower()
            if bool(result.get("verified", False)) or status in {"verified", "verified_owner"}:
                result.setdefault("verification_frame_count", len(frames))
                result.setdefault("usable_frame_count", usable_frame_count + 1)
                return result
            if status == "multiple_faces_detected" or reason == "multiple_faces":
                return {"status": "multiple_faces_detected", "ok": False, "verified": False, "reason": "multiple_faces", "verification_frame_count": len(frames), "usable_frame_count": usable_frame_count}
            if status == "not_verified":
                usable_frame_count += 1
                if first_not_verified is None:
                    first_not_verified = dict(result)
                continue
            if status in {"quality_rejected", "no_face_detected", "poor_quality"} or reason:
                quality_reasons.append(reason or status)
        if first_not_verified is not None:
            first_not_verified.setdefault("verification_frame_count", len(frames))
            first_not_verified.setdefault("usable_frame_count", usable_frame_count)
            return first_not_verified
        reason_set = {str(reason or "").strip().lower() for reason in quality_reasons if str(reason or "").strip()}
        if reason_set and reason_set <= {"no_face", "no_face_detected"}:
            status, reason = "no_face_detected", "no_face"
        elif "multiple_faces" in reason_set or "multiple_faces_detected" in reason_set:
            status, reason = "multiple_faces_detected", "multiple_faces"
        elif reason_set:
            status, reason = "poor_quality", "poor_quality"
        else:
            status, reason = "verification_failed", "verification_failed"
        return {"status": status, "ok": False, "verified": False, "reason": reason, "verification_frame_count": len(frames), "usable_frame_count": usable_frame_count}

    def _run_face_verification_capture(self, *, user_id: str, requested_count: int | None = None) -> Dict[str, Any]:
        total_start = time.monotonic()
        timings: Dict[str, int] = {}
        try:
            service_start = time.monotonic()
            service = self._face_enrollment_service()
            timings["face_service_build_elapsed_ms"] = int((time.monotonic() - service_start) * 1000)
        except Exception as exc:
            result = self._face_backend_failure_result(exc)
            timings["total_elapsed_ms"] = int((time.monotonic() - total_start) * 1000)
            result.update({"verified": False, "lockIntegrationEnabled": False, "timingDiagnostics": dict(timings)})
            LOGGER.info("face_verification_timing %s", {"result": result.get("status"), **timings})
            return result
        try:
            template_status = dict(service.status(user_id) or {}) if hasattr(service, "status") else {}
            if hasattr(service, "status") and not bool(template_status.get("enrolled", False)):
                timings["total_elapsed_ms"] = int((time.monotonic() - total_start) * 1000)
                return {"status": str(template_status.get("status") or "not_enrolled"), "ok": False, "verified": False, "rawImagesStored": False, "lockIntegrationEnabled": False, "timingDiagnostics": dict(timings)}
            provider = self._face_camera_provider()
            safe_requested_count = max(FACE_VERIFICATION_MIN_FRAME_COUNT, min(FACE_VERIFICATION_MAX_FRAME_COUNT, int(requested_count or FACE_VERIFICATION_DEFAULT_FRAME_COUNT)))
            capture_start = time.monotonic()
            if hasattr(provider, "capture_verification_frames"):
                capture = provider.capture_verification_frames(safe_requested_count)
            else:
                capture = provider.capture_verification_frame()
            timings["sample_capture_elapsed_ms"] = int((time.monotonic() - capture_start) * 1000)
            frames = tuple(getattr(capture, "frames", ()) or ())
            frame_count = int(getattr(capture, "frame_count", 0) or len(frames))
            capture_status = str(getattr(capture, "status", "") or "")
            capture_safe = dict(capture.to_safe_dict() or {}) if hasattr(capture, "to_safe_dict") else {}
            if not frames:
                frame = getattr(capture, "frame", None)
                if frame is not None:
                    frames = (frame,)
                    frame_count = 1
            if not bool(getattr(capture, "ok", False)) or frame_count < 1 or not frames:
                result = self._face_capture_failure_result(capture)
                timings["total_elapsed_ms"] = int((time.monotonic() - total_start) * 1000)
                result.update({"verified": False, "lockIntegrationEnabled": False, "timingDiagnostics": dict(timings)})
                LOGGER.info("face_verification_timing %s", {"result": result.get("status"), **timings, **self._face_safe_camera_diagnostics(capture_safe)})
                return result
            verify_start = time.monotonic()
            verification = self._verify_captured_face_frames(service, user_id, frames)
            timings["verification_elapsed_ms"] = int((time.monotonic() - verify_start) * 1000)
            timings["total_elapsed_ms"] = int((time.monotonic() - total_start) * 1000)
            result = self._normalize_face_verification_result(
                verification,
                capture_status=capture_status,
                frame_count=frame_count,
                capture_diagnostics=capture_safe,
            )
            result["timingDiagnostics"] = dict(timings)
            LOGGER.info("face_verification_timing %s", {"result": result.get("status"), **timings, **self._face_safe_camera_diagnostics(capture_safe)})
            return result
        except Exception:
            timings["total_elapsed_ms"] = int((time.monotonic() - total_start) * 1000)
            LOGGER.info("face_verification_timing %s", {"result": "verification_failed", **timings})
            return {"status": "verification_failed", "ok": False, "verified": False, "reason": "verification_failed", "verificationStatus": "verification_failed", "rawImagesStored": False, "lockIntegrationEnabled": False, "timingDiagnostics": dict(timings)}

    @Slot(bool)
    def setFaceConfirmationEnabled(self, enabled: bool) -> None:
        requested = bool(enabled)
        settings = getattr(self, "_app_settings", {}) if isinstance(getattr(self, "_app_settings", {}), dict) else {}
        if requested:
            state = self._build_face_confirmation_state()
            reason = str(state.get("faceConfirmationPreCameraReason") or state.get("faceConfirmationUnavailableReason") or "feature_disabled")
            if reason not in {"ready", "disabled"}:
                status = self._face_status_from_availability_reason(reason)
                result = {"status": status, "ok": False, "reason": reason}
                self._set_face_operation_state(result)
                self._set_status(self._status_text(self._face_state_text_key(status)), "warn")
                return
        if requested and not feature_flag_enabled(settings, "enable_face_confirmation"):
            self._set_face_operation_state({"status": "feature_disabled", "ok": False, "reason": "feature_disabled"})
            self._set_status(self._status_text("face_feature_unavailable"), "info")
            return
        if requested and not has_current_face_template_consent(settings):
            self._set_face_operation_state({"status": "consent_required", "ok": False, "reason": "consent_required"})
            self._set_status(self._status_text("face_status_consent_required"), "warn")
            return
        self._face_confirmation_enabled = requested
        self._app_settings = save_settings(self._settings_payload(face_confirmation_enabled=requested))
        self._set_face_operation_state({"status": "enabled" if requested else "disabled", "ok": True})
        self._set_status(self._status_text("face_confirmation_enabled" if requested else "face_confirmation_disabled"), "info")

    @Slot(result="QVariantMap")
    def enrollFaceTemplate(self) -> Dict[str, Any]:
        user_id = self._current_face_user_id()
        settings = getattr(self, "_app_settings", {}) if isinstance(getattr(self, "_app_settings", {}), dict) else {}
        if not user_id:
            return self._finish_face_operation({"status": "signed_out", "ok": False, "rawImagesStored": False})
        if not feature_flag_enabled(settings, "enable_face_enrollment"):
            return self._finish_face_operation({"status": "feature_disabled", "ok": False, "reason": "feature_disabled", "rawImagesStored": False})
        model_state = self._face_model_readiness_state()
        if not bool(model_state.get("ok", False)):
            return self._finish_face_operation({
                "status": str(model_state.get("status") or "face_models_invalid"),
                "ok": False,
                "reason": str(model_state.get("reason") or "model_invalid"),
                "rawImagesStored": False,
            })
        if not has_current_face_template_consent(settings):
            return self._finish_face_operation({"status": "consent_required", "ok": False})
        requested_count = self._face_enrollment_capture_count(settings)
        started = self._face_operation_started_result(kind="enrollment", status="capturing", requested_count=requested_count)
        return self._start_face_operation(
            kind="enrollment",
            started=started,
            task=lambda: self._run_face_enrollment_capture(user_id=user_id, requested_count=requested_count),
        )

    @Slot(result="QVariantMap")
    def testFaceConfirmation(self) -> Dict[str, Any]:
        user_id = self._current_face_user_id()
        settings = getattr(self, "_app_settings", {}) if isinstance(getattr(self, "_app_settings", {}), dict) else {}
        enabled_preference = bool(getattr(self, "_face_confirmation_enabled", False) or settings.get("face_confirmation_enabled", False))
        if not user_id:
            return self._finish_face_operation({"status": "signed_out", "ok": False, "verified": False, "rawImagesStored": False, "lockIntegrationEnabled": False})
        if not feature_flag_enabled(settings, "enable_face_confirmation"):
            return self._finish_face_operation({"status": "feature_disabled", "ok": False, "verified": False, "reason": "feature_disabled", "rawImagesStored": False, "lockIntegrationEnabled": False})
        model_state = self._face_model_readiness_state()
        if not bool(model_state.get("ok", False)):
            return self._finish_face_operation({
                "status": str(model_state.get("status") or "face_models_invalid"),
                "ok": False,
                "verified": False,
                "reason": str(model_state.get("reason") or "model_invalid"),
                "rawImagesStored": False,
                "lockIntegrationEnabled": False,
            })
        if not enabled_preference:
            return self._finish_face_operation({"status": "disabled", "ok": False, "verified": False, "reason": "disabled", "rawImagesStored": False, "lockIntegrationEnabled": False})
        if not has_current_face_template_consent(settings):
            return self._finish_face_operation({"status": "consent_required", "ok": False, "verified": False, "reason": "consent_required", "rawImagesStored": False, "lockIntegrationEnabled": False})
        requested_count = self._face_verification_capture_count(settings)
        started = self._face_operation_started_result(kind="verification", status="capturing", requested_count=requested_count)
        started.update({"verified": False, "lockIntegrationEnabled": False})
        return self._start_face_operation(
            kind="verification",
            started=started,
            task=lambda: self._run_face_verification_capture(user_id=user_id, requested_count=requested_count),
        )

    @Slot(result="QVariantMap")
    def deleteFaceTemplate(self) -> Dict[str, Any]:
        user_id = self._current_face_user_id()
        if not user_id:
            result = {"status": "signed_out", "ok": False, "deleted": False}
        else:
            try:
                result = self._face_service().delete_template(user_id)
            except Exception as exc:
                result = {"status": "failed", "ok": False, "deleted": False, "reason": str(exc)}
        if bool(result.get("deleted", False)):
            self._face_confirmation_enabled = False
            self._app_settings = save_settings(self._settings_payload(face_confirmation_enabled=False))
        self._set_face_operation_state(result)
        self._set_status(self._status_text(self._face_state_text_key(str(result.get("status") or "failed"))), "success" if result.get("ok") else "warn")
        return dict(result)

    @Slot()
    def openAboutUs(self) -> None:
        self.dialogMessage.emit(self._status_text("about_us_title"), self._about_us_body(), "info")

    @Slot()
    def openPrivacyPolicy(self) -> None:
        path = Path(self.privacyPolicyPath)
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            webbrowser.open("about:blank")


    @Slot(str)
    def setInterfaceMode(self, mode: str) -> None:
        requested = normalize_interface_mode(mode)
        current = normalize_interface_mode(getattr(self, "_interface_mode", "developer"))

        # The visible Developer/User UI selector is an explicit backend-owned
        # action.  UserShell still fails closed by default because
        # resolve_ui_mode() requires enable_user_shell, but this slot is the
        # safe place that can grant that display-only feature flag for the
        # authenticated user's deliberate selection.  This does not start or
        # stop protection, does not unlock protected sessions, and does not
        # alter runtime/model policy.
        changes: Dict[str, Any] = {"interface_mode": requested}
        if requested == "user":
            changes["enable_user_shell"] = True
        elif requested == "developer":
            changes["enable_user_shell"] = False

        self._interface_mode = requested
        self._app_settings = save_settings(self._settings_payload(**changes))
        signal = getattr(self, "uiModeChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        resolved_mode = getattr(self, "uiMode", "developer")
        if requested == "user" and resolved_mode != "user":
            self._set_status(self._status_text("ui_mode_user_unavailable"), "info")
        elif requested != current or resolved_mode == requested:
            self._set_status(self._status_text("ui_mode_changed", mode=self._status_text(f"ui_mode_{requested}")), "info")

    @Slot(str)
    def setThemeMode(self, mode: str) -> None:
        mode = str(mode or "").strip().lower()
        if mode not in THEMES:
            return
        self._theme = mode
        self._app_settings = save_settings(self._settings_payload(theme=mode))
        self.themeChanged.emit()

    @Slot(str)
    def setLanguageCode(self, lang: str) -> None:
        lang = str(lang or "").strip().lower()
        if lang not in STRINGS:
            return
        self._language = lang
        self._app_settings = save_settings(self._settings_payload(language=lang))
        self.languageChanged.emit()
        self.themeChanged.emit()
        QTimer.singleShot(0, self.refreshNow)
        self.onboardingChanged.emit()

    @Slot(bool)
    def setStartupEnabled(self, enabled: bool) -> None:
        requested = bool(enabled)
        actual = self._run_on_startup
        try:
            ok = bool(set_startup_enabled(requested))
            actual = requested if ok else bool(is_startup_enabled())
        except Exception:
            actual = bool(is_startup_enabled())
        self._run_on_startup = actual

        remember_changed = False
        if actual and not bool(getattr(self, "_remember_login_enabled", False)):
            self._remember_login_enabled = True
            remember_changed = True
            remember_current = getattr(self, "_remember_current_user", None)
            if callable(remember_current):
                remember_current()

        self._app_settings = save_settings(
            self._settings_payload(
                run_on_startup=self._run_on_startup,
                remember_login_enabled=bool(getattr(self, "_remember_login_enabled", False)),
            )
        )
        self.startupChanged.emit()
        if remember_changed:
            remember_signal = getattr(self, "rememberLoginChanged", None)
            if remember_signal is not None and hasattr(remember_signal, "emit"):
                remember_signal.emit()
        if actual != requested:
            self._set_status(self._status_text("startup_setting_change_failed"), "warn")

    @Slot(str)
    def playButtonSound(self, role: str = "neutral") -> None:
        if bool(getattr(self, "_mute_button_sounds", True)):
            return
        try:
            play_button_sound(role)
        except Exception:
            pass

    @Slot(bool)
    def setSmartAutoEnrollmentEnabled(self, enabled: bool) -> None:
        requested = bool(enabled)
        if requested == bool(getattr(self, "_smart_auto_enrollment_enabled", False)):
            return
        self._smart_auto_enrollment_enabled = requested
        self._app_settings = save_settings(self._settings_payload(smart_auto_enrollment_enabled=requested))
        if not requested:
            stop_passive = getattr(self, "_stop_passive_auto_enrollment_if_active", None)
            if callable(stop_passive):
                stop_passive(reason="setting_disabled")
        self._emit_auto_enrollment_changed()
        self._emit_privacy_center_changed()
        self._set_status(
            "Smart Auto Enrollment enabled. BioAuth will collect natural enrollment sessions only after consent and when safe." if requested else "Smart Auto Enrollment disabled. Passive collection stopped if it was active.",
            "info",
        )

    @Slot(bool)
    def setAutoTrainWhenReadyEnabled(self, enabled: bool) -> None:
        requested = bool(enabled)
        if requested == bool(getattr(self, "_auto_train_when_ready_enabled", False)):
            return
        self._auto_train_when_ready_enabled = requested
        self._app_settings = save_settings(self._settings_payload(auto_train_when_ready_enabled=requested))
        self._emit_auto_enrollment_changed()
        readiness_signal = getattr(self, "modelReadinessChanged", None)
        if readiness_signal is not None and hasattr(readiness_signal, "emit"):
            readiness_signal.emit()
        if requested:
            _request_refresh(self, "settings:auto_training_enabled", True)
        self._set_status(
            "Auto-train when ready enabled. BioAuth will reuse the existing training path after consent and readiness checks pass." if requested else "Auto-train when ready disabled.",
            "info",
        )

    @Slot(bool)
    def setAutoPromoteWhenProductionSafeEnabled(self, enabled: bool) -> None:
        requested = bool(enabled)
        if requested == bool(getattr(self, "_auto_promote_when_production_safe_enabled", False)):
            return
        self._auto_promote_when_production_safe_enabled = requested
        self._app_settings = save_settings(self._settings_payload(auto_promote_when_production_safe_enabled=requested))
        self._emit_auto_enrollment_changed()
        readiness_signal = getattr(self, "modelReadinessChanged", None)
        if readiness_signal is not None and hasattr(readiness_signal, "emit"):
            readiness_signal.emit()
        if requested:
            _request_refresh(self, "settings:auto_promotion_enabled", True)
        self._set_status(
            "Auto-promote when production-safe enabled. Promotion still requires approved_for_production and runtime validation." if requested else "Auto-promote when production-safe disabled.",
            "info",
        )

    @Slot(str)
    def setRiskSensitivityPreset(self, preset: str) -> None:
        normalized = normalize_sensitivity_preset(preset)
        if normalized == getattr(self, "_risk_sensitivity", "conservative"):
            return
        self._risk_sensitivity = normalized
        self._app_settings = save_settings(self._settings_payload(risk_sensitivity=normalized))
        self.riskSensitivityChanged.emit()
        preset_label = self._status_text(f"risk_preset_{normalized}")
        self._set_status(self._status_text("risk_sensitivity_set", preset=preset_label), "info")


    @Slot(bool)
    def setRememberLoginEnabled(self, enabled: bool) -> None:
        requested = bool(enabled)
        if requested == bool(getattr(self, "_remember_login_enabled", False)):
            return
        self._remember_login_enabled = requested
        self._app_settings = save_settings(self._settings_payload(remember_login_enabled=requested))
        self.rememberLoginChanged.emit()
        if requested and getattr(self, "_current_user", None):
            self._remember_current_user()
        else:
            self._clear_remembered_user()
        state_key = "remember_login_enabled_msg" if requested else "remember_login_disabled_msg"
        self._set_status(self._status_text(state_key), "info")

    @Slot(bool)
    def setButtonSoundsMuted(self, muted: bool) -> None:
        requested = bool(muted)
        if requested == bool(getattr(self, "_mute_button_sounds", True)):
            return
        self._mute_button_sounds = requested
        self._app_settings = save_settings(self._settings_payload(mute_button_sounds=requested))
        self.buttonSoundsMutedChanged.emit()
        state_key = "button_sounds_muted" if requested else "button_sounds_enabled"
        self._set_status(self._status_text(state_key), "info")

    def _emit_deep_runtime_changed(self) -> None:
        signal = getattr(self, "deepRuntimeChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()

    def _emit_shadow_automation_changed(self) -> None:
        signal = getattr(self, "shadowAutomationChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        shadow_signal = getattr(self, "shadowChanged", None)
        if shadow_signal is not None and hasattr(shadow_signal, "emit"):
            shadow_signal.emit()
        readiness_signal = getattr(self, "modelReadinessChanged", None)
        if readiness_signal is not None and hasattr(readiness_signal, "emit"):
            readiness_signal.emit()
        controls_signal = getattr(self, "controlsChanged", None)
        if controls_signal is not None and hasattr(controls_signal, "emit"):
            controls_signal.emit()
        effective_signal = getattr(self, "effectiveProductionReadyChanged", None)
        if effective_signal is not None and hasattr(effective_signal, "emit"):
            effective_signal.emit()

    @Slot(bool)
    def setShadowAutomationPaused(self, paused: bool) -> None:
        requested = bool(paused)
        if requested == bool(getattr(self, "_shadow_automation_paused", False)) and requested == bool(getattr(self, "_developer_forced_production_ready", False)):
            return
        self._shadow_automation_paused = requested
        self._developer_forced_production_ready = requested
        if requested:
            self._pending_shadow_suggestion = False
            self._pending_shadow_avg_delta = 0.0
            self._shadow_suggestion_dismissed = True
            self._last_shadow_backlog_scan_at = 0.0
            self._last_shadow_evidence_monitor_block_reason = "developer_shadow_paused"
            stop_shadow = getattr(self, "_stop_shadow_evidence_monitor", None)
            if callable(stop_shadow):
                try:
                    stop_shadow(reason="developer_shadow_paused")
                except Exception:
                    pass
            clear_shadow = getattr(self, "_clear_pending_shadow_evidence_monitor_start", None)
            if callable(clear_shadow):
                clear_shadow()
            self._set_status("Shadow automation paused. Developer Mode is simulating production-ready for classic/hybrid monitor testing without changing real production metadata.", "info")
        else:
            self._last_shadow_evidence_monitor_block_reason = ""
            self._set_status("Shadow automation resumed. Developer production-ready simulation is disabled; real production gates apply again.", "info")
        status_map = dict(getattr(self, "_shadow_status", {}) if isinstance(getattr(self, "_shadow_status", None), dict) else {})
        status_map["automation_paused"] = requested
        status_map["shadow_automation_paused"] = requested
        if requested:
            status_map["pause_reason"] = "developer_shadow_paused"
        else:
            status_map.pop("pause_reason", None)
        self._shadow_status = status_map or {"phase": "collecting", "ready": False, "suggestion_pending": False, "automation_paused": requested}
        self._app_settings = save_settings(self._settings_payload(shadow_automation_paused=requested, developer_forced_production_ready=requested))
        self._emit_shadow_automation_changed()
        _request_refresh(self, "settings:shadow_automation_paused" if requested else "settings:shadow_automation_resumed", True)

    def _refresh_deep_runtime_state(self) -> bool:
        previous = dict(getattr(self, "_deep_runtime_state", {}) or {})
        settings_payload = self._settings_payload()
        runtime_meta = getattr(self, "_runtime_state", {}) if isinstance(getattr(self, "_runtime_state", None), dict) else {}
        runtime_metadata = runtime_meta.get("runtime_metadata") if isinstance(runtime_meta.get("runtime_metadata"), dict) else None
        state = resolve_deep_runtime_state(settings_payload, runtime_metadata=runtime_metadata)
        fallback_reason = normalize_deep_runtime_fallback_reason(state.get("fallback_reason"))
        state["fallback_reason"] = fallback_reason
        state["fallbackReason"] = fallback_reason
        state["fallback_reason_text"] = deep_runtime_fallback_reason_text(fallback_reason)
        state["fallbackReasonText"] = state["fallback_reason_text"]
        state["is_fallback"] = deep_runtime_is_fallback(fallback_reason)
        state["isFallback"] = state["is_fallback"]
        self._deep_runtime_mode = state.get("requested_mode", "auto")
        self._deep_runtime_manual_override = bool(state.get("manual_override", False))
        self._deep_runtime_benchmark = normalize_benchmark_record(settings_payload.get("deep_runtime_benchmark"))
        self._deep_runtime_state = state
        return state != previous

    @Slot(str)
    def setDeepRuntimeMode(self, mode: str) -> None:
        normalized = normalize_deep_runtime_mode(mode, default="auto")
        manual_override = normalized != "auto"
        if normalized == getattr(self, "_deep_runtime_mode", "auto") and manual_override == bool(getattr(self, "_deep_runtime_manual_override", False)):
            return
        self._deep_runtime_mode = normalized
        self._deep_runtime_manual_override = manual_override
        self._app_settings = save_settings(self._settings_payload(deep_runtime_mode=normalized, deep_runtime_manual_override=manual_override))
        self._refresh_deep_runtime_state()
        self._emit_deep_runtime_changed()
        self._set_status(f"Deep runtime mode set to {normalized}.", "info")

    @Slot(bool)
    def setDeepRuntimeManualOverride(self, enabled: bool) -> None:
        requested = bool(enabled)
        if requested == bool(getattr(self, "_deep_runtime_manual_override", False)):
            return
        self._deep_runtime_manual_override = requested
        if not requested and getattr(self, "_deep_runtime_mode", "auto") != "auto":
            self._deep_runtime_mode = "auto"
        self._app_settings = save_settings(self._settings_payload(
            deep_runtime_mode=getattr(self, "_deep_runtime_mode", "auto"),
            deep_runtime_manual_override=requested,
        ))
        self._refresh_deep_runtime_state()
        self._emit_deep_runtime_changed()
        self._set_status("Deep runtime manual override updated.", "info")

    @Slot(result="QVariantMap")
    def runDeepRuntimeBenchmark(self) -> Dict[str, Any]:
        result = run_local_device_benchmark()
        self._deep_runtime_benchmark = normalize_benchmark_record(result)
        self._app_settings = save_settings(self._settings_payload(deep_runtime_benchmark=self._deep_runtime_benchmark))
        self._refresh_deep_runtime_state()
        self._emit_deep_runtime_changed()
        self._set_status(f"Device benchmark finished: recommended {self._deep_runtime_state.get('recommended_mode', 'classic')}.", "info")
        return dict(self._deep_runtime_state)

    @Slot()
    def clearDeepRuntimeBenchmark(self) -> None:
        self._deep_runtime_benchmark = normalize_benchmark_record({})
        self._app_settings = save_settings(self._settings_payload(deep_runtime_benchmark=self._deep_runtime_benchmark))
        self._refresh_deep_runtime_state()
        self._emit_deep_runtime_changed()
        self._set_status("Device benchmark profile cleared.", "info")
