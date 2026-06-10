from __future__ import annotations

from typing import Any, Dict, Mapping

from app_settings import normalize_interface_mode


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return False


def build_effective_production_ready_state(
    *,
    settings: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    shadow_paused: bool,
    developer_forced: bool,
) -> Dict[str, Any]:
    """Return backend-owned effective readiness for Developer UI runtime tests.

    This helper deliberately never mutates profile/model metadata.  The real
    production-ready bit remains the value persisted by production approval.
    The developer override is only an effective runtime/test gate used while
    the app is in Developer UI and shadow automation is paused.
    """

    settings_payload = dict(settings or {})
    profile_payload = dict(profile or {})
    real_ready = _safe_bool(profile_payload.get("production_ready"))
    dev_mode = normalize_interface_mode(settings_payload.get("interface_mode", "developer")) == "developer"
    paused = _safe_bool(shadow_paused)
    forced = _safe_bool(developer_forced)
    simulation_active = bool((not real_ready) and dev_mode and paused and forced)
    effective = bool(real_ready or simulation_active)
    if real_ready:
        reason = "real_production_ready"
        label = "Production-ready: real production approval"
    elif simulation_active:
        reason = "developer_shadow_pause_simulation"
        label = "Production-ready: simulated by Developer Mode"
    elif not dev_mode:
        reason = "blocked_developer_mode_disabled"
        label = "Blocked: Developer Mode disabled"
    elif not paused:
        reason = "blocked_shadow_not_paused"
        label = "Blocked: shadow automation is running"
    elif not forced:
        reason = "blocked_developer_override_disabled"
        label = "Blocked: developer production-ready simulation is disabled"
    else:
        reason = "blocked_not_ready"
        label = "Blocked: model is not production-ready"
    return {
        "realProductionReady": real_ready,
        "real_production_ready": real_ready,
        "developerMode": dev_mode,
        "developer_mode": dev_mode,
        "shadowPaused": paused,
        "shadow_paused": paused,
        "developerForcedProductionReady": forced,
        "developer_forced_production_ready": forced,
        "effectiveProductionReady": effective,
        "effective_production_ready": effective,
        "devProductionReadySimulation": simulation_active,
        "dev_production_ready_simulation": simulation_active,
        "reason": reason,
        "reason_code": reason,
        "label": label,
        "statusLabel": label,
        "status_label": label,
    }
