from __future__ import annotations

from .shared import (
    Slot,
    change_password,
    cleanup_old_backups,
    create_user,
    delete_user_account,
    delete_user_data,
    dismiss_shadow_suggestion,
    generate_password_recovery_code,
    lookup_username_hint_by_email,
    reset_password_with_recovery,
    reveal_username_by_email,
    promote_shadow_model,
    reset_user_profile,
    user_profile_status,
    verify_user,
    clear_persistent_login,
    remember_user,
    restore_remembered_user,
    translate_backend_result,
    user_requires_onboarding,
    verify_password_reset_recovery,
)


def _request_refresh(self, reason: str, force: bool = False) -> None:
    request = getattr(self, "requestRefresh", None)
    if callable(request):
        request(reason, force)
        return
    legacy = getattr(self, "refreshNow", None)
    if callable(legacy):
        legacy()


class AuthMixin:
    def _emit_recovery_code_dialog(self, code: str, *, title_key: str = "password_recovery_title", body_key: str = "password_recovery_dialog_body") -> None:
        formatted = str(code or "").strip()
        if not formatted:
            return
        dialog = getattr(self, "dialogMessage", None)
        if dialog is None or not hasattr(dialog, "emit"):
            return
        dialog.emit(self._t(title_key), self._t(body_key, code=formatted), "info")

    def _set_onboarding_state(self, visible: bool, mode: str = "consent") -> None:
        normalized_mode = str(mode or "consent").strip().lower()
        if normalized_mode not in {"tour", "performance", "consent"}:
            normalized_mode = "consent"
        changed = bool(getattr(self, "_onboarding_visible", False)) != bool(visible) or str(getattr(self, "_onboarding_mode", "consent") or "consent") != normalized_mode
        self._onboarding_visible = bool(visible)
        self._onboarding_mode = normalized_mode
        if changed:
            self.onboardingChanged.emit()

    def _show_new_user_onboarding_if_needed(self, user: dict | None) -> bool:
        if not isinstance(user, dict) or not user_requires_onboarding(user):
            self._set_onboarding_state(False, "consent")
            return False
        self._set_onboarding_state(True, "tour")
        return True

    def _remember_current_user(self) -> None:
        if not self._current_user:
            return
        if not bool(getattr(self, "_remember_login_enabled", False)):
            self._clear_remembered_user()
            return
        try:
            remember_user(self._current_user["user_id"])
        except OSError:
            pass

    def _clear_remembered_user(self) -> None:
        try:
            clear_persistent_login()
        except OSError:
            pass

    def _restore_persistent_signin(self) -> bool:
        if not bool(getattr(self, "_remember_login_enabled", False)):
            self._clear_remembered_user()
            return False
        try:
            user = restore_remembered_user()
        except (OSError, ValueError, TypeError):
            user = None
        if not user:
            return False
        self._current_user = user
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        self._reset_shadow_runtime_flags()
        cleanup_old_backups(self._current_user["user_id"])
        self._clear_stale_runtime_state()
        self._pending_new_account_passcode_prompt = False
        self._show_new_user_onboarding_if_needed(self._current_user)
        face_emit = getattr(self, "_emit_face_confirmation_changed", None)
        if callable(face_emit):
            face_emit()
        return True

    @Slot(str, str, str)
    @Slot(str, str, str, str)
    def createAccount(self, display_name: str, username: str, password: str, email: str = "") -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("auth", "createAccount requested", payload={"username": username.strip(), "display_name": display_name.strip(), "email_present": bool(email.strip())})
        result = create_user(username.strip(), password, display_name.strip(), email.strip(), require_email=True)
        if not result.get("ok"):
            self._set_status(translate_backend_result(getattr(self, "_language", "en"), result, default_message="Could not create account."), "danger")
            return
        self._current_user = result.get("user")
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        self._remember_current_user()
        self._reset_shadow_runtime_flags()
        self._clear_stale_runtime_state()
        self.currentUserChanged.emit()
        face_emit = getattr(self, "_emit_face_confirmation_changed", None)
        if callable(face_emit):
            face_emit()
        self.authenticatedChanged.emit()
        self._pending_new_account_passcode_prompt = True
        self._set_onboarding_state(True, "tour")
        reset_lock = getattr(self, "_reset_app_passcode_runtime", None)
        if callable(reset_lock):
            reset_lock()
        touch = getattr(self, "_record_ui_activity", None)
        if callable(touch):
            touch()
        self._set_status(self._t("account_created_msg"), "success")
        self._emit_recovery_code_dialog(result.get("recovery_code", ""))
        self._update_refresh_timer(force=True)
        _request_refresh(self, "auth:create_user", True)

    @Slot(str)
    def requestUsernameHint(self, email: str) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("auth", "requestUsernameHint requested", payload={"email_present": bool(str(email or "").strip())})
        result = lookup_username_hint_by_email(email.strip())
        payload = result if isinstance(result, dict) else {}
        message = translate_backend_result(getattr(self, "_language", "en"), payload, default_message="We couldn't generate a username hint.")
        message_key = str(payload.get("message_key") or "").strip()
        tone = "success" if payload.get("ok") else ("danger" if message_key in {"auth_username_hint_email_required", "auth_invalid_email"} else "info")
        feedback_signal = getattr(self, "forgotUsernameLookupResult", None)
        if feedback_signal is not None and hasattr(feedback_signal, "emit"):
            feedback_signal.emit(message, tone)
        self._set_status(message, tone)
        if payload.get("ok"):
            dialog = getattr(self, "dialogMessage", None)
            if dialog is not None and hasattr(dialog, "emit"):
                dialog.emit(self._t("forgot_username_title"), message, "info")


    @Slot(str, str)
    def requestUsernameReveal(self, email: str, password: str) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("auth", "requestUsernameReveal requested", payload={"email_present": bool(str(email or "").strip()), "password_present": bool(str(password or "").strip())})
        result = reveal_username_by_email(email.strip(), password)
        payload = result if isinstance(result, dict) else {}
        message = translate_backend_result(getattr(self, "_language", "en"), payload, default_message="We couldn't verify the account details.")
        message_key = str(payload.get("message_key") or "").strip()
        tone = "success" if payload.get("ok") else ("danger" if message_key in {"auth_username_hint_email_required", "auth_invalid_email", "auth_username_reveal_password_required", "auth_login_locked"} else "info")
        feedback_signal = getattr(self, "forgotUsernameRevealResult", None)
        if feedback_signal is not None and hasattr(feedback_signal, "emit"):
            feedback_signal.emit(message, tone)
        self._set_status(message, tone)
        if payload.get("ok"):
            dialog = getattr(self, "dialogMessage", None)
            if dialog is not None and hasattr(dialog, "emit"):
                dialog.emit(self._t("forgot_username_title"), message, "info")


    @Slot(str, str)
    def requestPasswordResetVerification(self, identifier: str, recovery_code: str) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("auth", "requestPasswordResetVerification requested", payload={"identifier_present": bool(str(identifier or "").strip()), "recovery_code_present": bool(str(recovery_code or "").strip())})
        result = verify_password_reset_recovery(identifier.strip(), recovery_code)
        payload = result if isinstance(result, dict) else {}
        message = translate_backend_result(getattr(self, "_language", "en"), payload, default_message="We couldn't verify the recovery details.")
        message_key = str(payload.get("message_key") or "").strip()
        tone = "success" if payload.get("ok") else ("danger" if message_key in {"auth_password_reset_identifier_required", "auth_password_reset_recovery_required", "auth_password_reset_identifier_invalid", "auth_password_reset_locked"} else "info")
        feedback_signal = getattr(self, "forgotPasswordVerificationResult", None)
        if feedback_signal is not None and hasattr(feedback_signal, "emit"):
            feedback_signal.emit(message, tone)
        self._set_status(message, tone)

    @Slot(str, str, str, str)
    def resetPasswordWithRecoveryCode(self, identifier: str, recovery_code: str, new_password: str, confirm_password: str) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("auth", "resetPasswordWithRecoveryCode requested", payload={"identifier_present": bool(str(identifier or "").strip()), "recovery_code_present": bool(str(recovery_code or "").strip()), "new_password_present": bool(str(new_password or "").strip()), "confirm_password_present": bool(str(confirm_password or "").strip())})
        if str(new_password or "") != str(confirm_password or ""):
            payload = {"ok": False, "message_key": "auth_password_reset_password_mismatch"}
        else:
            payload = reset_password_with_recovery(identifier.strip(), recovery_code, new_password)
        message = translate_backend_result(getattr(self, "_language", "en"), payload if isinstance(payload, dict) else {}, default_message="We couldn't reset the password.")
        message_key = str((payload or {}).get("message_key") or "").strip() if isinstance(payload, dict) else ""
        tone = "success" if isinstance(payload, dict) and payload.get("ok") else ("danger" if message_key in {"auth_password_reset_identifier_required", "auth_password_reset_recovery_required", "auth_password_reset_identifier_invalid", "auth_password_reset_password_mismatch", "auth_new_password_too_short", "auth_new_password_needs_letter_number", "auth_password_reset_locked"} else "info")
        feedback_signal = getattr(self, "forgotPasswordResetResult", None)
        if feedback_signal is not None and hasattr(feedback_signal, "emit"):
            feedback_signal.emit(message, tone)
        self._set_status(message, tone)
        if isinstance(payload, dict) and payload.get("ok"):
            self._clear_remembered_user()
            self._emit_recovery_code_dialog(payload.get("recovery_code", ""), title_key="forgot_password_title", body_key="forgot_password_success_dialog_body")

    @Slot(str, str)
    def signIn(self, username: str, password: str) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("auth", "signIn requested", payload={"username": username.strip()})
        result = verify_user(username.strip(), password)
        if not result.get("ok"):
            self._set_status(translate_backend_result(getattr(self, "_language", "en"), result, default_message="Sign in failed."), "danger")
            return
        self._current_user = result.get("user")
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        self._remember_current_user()
        self._reset_shadow_runtime_flags()
        cleanup_old_backups(self._current_user["user_id"])
        self._clear_stale_runtime_state()
        self.currentUserChanged.emit()
        face_emit = getattr(self, "_emit_face_confirmation_changed", None)
        if callable(face_emit):
            face_emit()
        self.authenticatedChanged.emit()
        reset_lock = getattr(self, "_reset_app_passcode_runtime", None)
        if callable(reset_lock):
            reset_lock()
        touch = getattr(self, "_record_ui_activity", None)
        if callable(touch):
            touch()
        self._set_status(self._t("signin_success"), "success")
        self._update_refresh_timer(force=True)
        _request_refresh(self, "auth:signin", True)
        self._pending_new_account_passcode_prompt = False
        self._show_new_user_onboarding_if_needed(self._current_user)

    @Slot()
    def logout(self) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("auth", "logout requested", payload={"user": str((self._current_user or {}).get("user_id", "") or "")})
        if self._current_user:
            self.stopCurrentSession(silent=True)
        self._clear_pending_monitor_start()
        self._clear_remembered_user()
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        self._current_user = None
        self._profile = {}
        self._sessions = []
        self._runtime_state = {}
        self._onboarding_visible = False
        self._onboarding_mode = "consent"
        self._pending_onboarding_do_not_show_again = False
        self._pending_onboarding_tour_skipped = False
        self._pending_new_account_passcode_prompt = False
        if getattr(self, "_passcode_setup_prompt_visible", False):
            self._passcode_setup_prompt_visible = False
            prompt_signal = getattr(self, "passcodeSetupPromptChanged", None)
            if prompt_signal is not None and hasattr(prompt_signal, "emit"):
                prompt_signal.emit()
        reset_lock = getattr(self, "_reset_app_passcode_runtime", None)
        if callable(reset_lock):
            reset_lock(unlock_only=True)
        self._reset_shadow_runtime_flags()
        self._last_alert_signature = None
        self._update_refresh_timer(force=True)
        face_emit = getattr(self, "_emit_face_confirmation_changed", None)
        if callable(face_emit):
            face_emit()
        self._emit_all()
        self._set_status("", "info")

    @Slot(str, str)
    def changePassword(self, current_password: str, new_password: str) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("auth", "changePassword requested", payload={"user": str((self._current_user or {}).get("user_id", "") or "")})
        if not self._current_user:
            return
        result = change_password(self._current_user["user_id"], current_password, new_password)
        tone = "success" if result.get("ok") else "danger"
        self._set_status(translate_backend_result(getattr(self, "_language", "en"), result, default_key="password_updated"), tone)
        if result.get("ok"):
            self._remember_current_user()
            self.dialogMessage.emit(self._t("settings"), self._t("password_updated"), "info")

    @Slot(str)
    def regeneratePasswordRecoveryCode(self, current_password: str) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("auth", "regeneratePasswordRecoveryCode requested", payload={"user": str((self._current_user or {}).get("user_id", "") or ""), "password_present": bool(str(current_password or "").strip())})
        if not self._current_user:
            return
        result = generate_password_recovery_code(self._current_user["user_id"], current_password)
        tone = "success" if result.get("ok") else ("danger" if str(result.get("message_key") or "") in {"auth_password_recovery_current_password_required", "auth_current_password_incorrect", "auth_account_not_found"} else "info")
        self._set_status(translate_backend_result(getattr(self, "_language", "en"), result, default_message="We couldn't prepare a recovery code."), tone)
        if result.get("ok"):
            user = result.get("user")
            if isinstance(user, dict):
                self._current_user = user
                self.currentUserChanged.emit()
            self._emit_recovery_code_dialog(result.get("recovery_code", ""))

    @Slot()
    def resetProfile(self) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("auth", "resetProfile requested", payload={"user": str((self._current_user or {}).get("user_id", "") or "")})
        if not self._current_user:
            return
        blocked_reason = self._destructive_action_block_reason(for_delete=False)
        if blocked_reason:
            self._set_status(blocked_reason, "warn")
            return
        result = reset_user_profile(self._current_user["user_id"], delete_sessions=False)
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        tone = "success" if result.get("ok") else "danger"
        self._reset_shadow_runtime_flags()
        self._set_status(translate_backend_result(getattr(self, "_language", "en"), result), tone)
        _request_refresh(self, "auth:reset_profile", False)

    @Slot()
    def promoteShadowModel(self) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("shadow", "promoteShadowModel requested", payload={"user": str((self._current_user or {}).get("user_id", "") or "")})
        if not self._current_user:
            return
        result = promote_shadow_model(self._current_user["user_id"])
        if result.get("ok"):
            self._pending_shadow_suggestion = False
            self._pending_shadow_avg_delta = 0.0
            self._shadow_suggestion_dismissed = False
            self._set_status(translate_backend_result(getattr(self, "_language", "en"), result, default_key="shadow_promoted"), "success")
        else:
            safe_shadow_only = bool(result.get("evidence_only") or result.get("shadowEvidenceOnly") or result.get("production_activation_blocked"))
            self._set_status(
                translate_backend_result(getattr(self, "_language", "en"), result, default_key="shadow_promotion_failed"),
                "info" if safe_shadow_only else "danger",
            )
        _request_refresh(self, "auth:promote_shadow_model", False)

    @Slot(str)
    def approveProductionModelSwitch(self, candidateDigest: str) -> None:
        debug = getattr(self, "_debug_trace", None)
        user_id = str((self._current_user or {}).get("user_id", "") or "") if self._current_user else ""
        digest = str(candidateDigest or "").strip()
        if callable(debug):
            debug("production_approval", "approveProductionModelSwitch requested", payload={"user": user_id, "candidate_digest_present": bool(digest)})
        if not self._current_user:
            return
        try:
            from metadata_core.auto_promotion import approve_production_model_switch

            result = approve_production_model_switch(
                user_id,
                digest,
                user_approved=True,
                approval_reason="user_approved_model_switch",
                approved_by=user_id,
            )
        except Exception as exc:
            result = {"ok": False, "changed": False, "reason": f"user_approved_switch_failed_safe:{exc}", "protectedSessionsAvailable": False}
        if bool(result.get("ok")) and bool(result.get("changed")):
            self._set_status(translate_backend_result(getattr(self, "_language", "en"), result, default_key="user_model_switch_activated"), "success")
            invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
            if callable(invalidate):
                invalidate()
        else:
            self._set_status(translate_backend_result(getattr(self, "_language", "en"), result, default_key="user_model_switch_failed"), "warn")
        signal = getattr(self, "modelReadinessChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        profile_signal = getattr(self, "profileChanged", None)
        if profile_signal is not None and hasattr(profile_signal, "emit"):
            profile_signal.emit()
        _request_refresh(self, "auth:approve_production_model_switch", True)

    @Slot()
    def requestUserApproveModelUpdate(self) -> None:
        if not self._current_user:
            self._set_status(self._t("user_action_unavailable"), "warn")
            return
        build_state = getattr(self, "_build_production_approval_state_payload", None)
        state = build_state(log_source="user_model_update_request") if callable(build_state) else {}
        pending = bool(state.get("productionReadyPendingUserApproval") or state.get("production_ready_pending_user_approval"))
        digest = str(state.get("candidateDigest") or state.get("candidate_digest") or "").strip()
        if not pending or not digest:
            self._set_status(self._t("user_model_update_unavailable_tooltip"), "warn")
            return
        self.approveProductionModelSwitch(digest)

    @Slot()
    def dismissShadowSuggestion(self) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("shadow", "dismissShadowSuggestion requested")
        self._pending_shadow_suggestion = False
        self._pending_shadow_avg_delta = 0.0
        self._shadow_suggestion_dismissed = True
        if self._current_user:
            dismiss_shadow_suggestion(self._current_user["user_id"], additional_evals=5)
        self._refresh_shadow_status()

    @Slot(str)
    def deleteAccount(self, password: str) -> None:
        debug = getattr(self, "_debug_trace", None)
        if callable(debug):
            debug("auth", "deleteAccount requested", payload={"user": str((self._current_user or {}).get("user_id", "") or "")}, level="warn")
        if not self._current_user:
            return
        blocked_reason = self._destructive_action_block_reason(for_delete=True)
        if blocked_reason:
            self._set_status(blocked_reason, "warn")
            return
        result = delete_user_account(self._current_user["user_id"], password)
        if not result.get("ok"):
            self._set_status(translate_backend_result(getattr(self, "_language", "en"), result), "danger")
            return
        user_id = self._current_user["user_id"]
        self._clear_remembered_user()
        delete_user_data(user_id)
        try:
            from evidence_capture import delete_evidence_for_user

            delete_evidence_for_user(user_id)
        except Exception:
            pass
        self.logout()
