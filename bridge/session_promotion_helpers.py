from __future__ import annotations

from importlib import import_module
from typing import Any, Dict



def _facade():
    return import_module("bridge.session_mixin")


def _request_refresh(self, reason: str, force: bool = False) -> None:
    request = getattr(self, "requestRefresh", None)
    if callable(request):
        request(reason, force)
        return
    legacy = getattr(self, "refreshNow", None)
    if callable(legacy):
        legacy()


def _runtime_flow(self) -> str:
    flow_fn = getattr(self, "_session_flow", None)
    if callable(flow_fn):
        try:
            return str(flow_fn() or "idle")
        except Exception:
            return "unknown"
    return "idle"


def maybe_auto_promote_production(self) -> bool:
    """Publish a production-approved candidate through the existing runtime gate."""

    if not getattr(self, "_current_user", None):
        return False
    user_id = str((getattr(self, "_current_user", {}) or {}).get("user_id", "") or "")
    if not user_id:
        return False
    if bool(getattr(self, "_training_in_progress", False)) or bool(getattr(self, "_auto_training_job_active", False)):
        self._last_auto_promotion_decision_reason = "training_active"
        return False
    progress = getattr(self, "_training_progress", {}) if isinstance(getattr(self, "_training_progress", None), dict) else {}
    if bool(progress.get("active")) or str(progress.get("stage_key") or "") == "training_stage_evaluating_model":
        self._last_auto_promotion_decision_reason = "evaluation_pending"
        return False
    profile = getattr(self, "_profile", {}) if isinstance(getattr(self, "_profile", None), dict) else {}
    production = profile.get("production_approval_state") if isinstance(profile, dict) else {}
    production = production if isinstance(production, dict) else {}
    flow = _runtime_flow(self)
    try:
        from metadata_core.auto_promotion import safe_auto_promote_production_bundle

        result = safe_auto_promote_production_bundle(
            user_id,
            settings=getattr(self, "_app_settings", {}) if isinstance(getattr(self, "_app_settings", None), dict) else {},
            candidate_metadata=None,
            runtime_validation={"ok": bool(production.get("protectedSessionsAvailable")), "reason": str(production.get("runtimeValidationReason") or "")},
            authenticated=True,
            training_active=bool(getattr(self, "_training_in_progress", False)),
            session_flow=flow,
            app_locked=bool(getattr(self, "_app_passcode_locked", False)),
        )
    except Exception as exc:
        result = {"ok": False, "changed": False, "reason": f"auto_promotion_error:{exc}", "protectedSessionsAvailable": False}
    if not isinstance(result, dict):
        result = {"ok": False, "changed": False, "reason": "invalid_result", "protectedSessionsAvailable": False}
    self._auto_promotion_last_result = dict(result)
    self._last_auto_promotion_decision_reason = str(result.get("reason") or "")
    signal = getattr(self, "modelReadinessChanged", None)
    if signal is not None and hasattr(signal, "emit"):
        signal.emit()
    profile_signal = getattr(self, "profileChanged", None)
    if profile_signal is not None and hasattr(profile_signal, "emit"):
        profile_signal.emit()
    if bool(result.get("ok")) and bool(result.get("changed")):
        invalidate = getattr(self, "_invalidate_dashboard_snapshot_cache", None)
        if callable(invalidate):
            invalidate()
        set_status = getattr(self, "_set_status", None)
        if callable(set_status):
            set_status("Protected Sessions are ready. Your model passed production approval and the runtime bundle is active.", "success")
        _request_refresh(self, "auto_promotion:promoted", True)
        return True
    return False


__all__ = ["maybe_auto_promote_production"]
