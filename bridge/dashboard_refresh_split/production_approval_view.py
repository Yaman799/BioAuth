"""Extracted implementation section for `bridge/refresh_dashboard_helpers.py`."""
from __future__ import annotations
import logging
import os
from importlib import import_module
from typing import Any, Dict, List
from bioauth_runtime import runtime_boundary
from bridge.runtime_labels import runtime_policy_display_fields
from bridge import refresh_runtime_helpers as _refresh_state
from bridge.qt_thread_dispatch import dispatch_to_qt_thread

def _build_drift_live_cards(
    state: Dict[str, Any],
    *,
    active: bool,
    technical_failure: bool,
    awaiting_evidence: bool,
    telemetry_fresh: bool,
    capture_fresh: bool,
    keyboard_event_count: int,
    mouse_event_count: int,
    risk_text: str,
    avg_risk_text: str,
    runtime_policy_display: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Build honest Drift Lab cards from monitor/runtime fields only.

    This intentionally does not synthesize keyboard/mouse drift percentages.
    Per-channel cards expose capture and diagnostic readiness until the backend
    emits channel-specific drift scores. The combined card may render a trend
    only from monitor-published ``runtime_recent_risks``.
    """

    window_count = _runtime_int(state.get("runtime_window_count"), 0)
    quality_ok_windows = _runtime_int(state.get("runtime_quality_ok_windows"), 0)
    recent_risks = _recent_risk_trend(state.get("runtime_recent_risks"))
    summary_text = str(state.get("runtime_window_diag_summary") or "").strip()
    last_window = state.get("runtime_last_window_diag") if isinstance(state.get("runtime_last_window_diag"), dict) else {}
    last_reasons = list((last_window or {}).get("reason_codes") or [])
    reason_text = ", ".join(str(item) for item in last_reasons[:3]) if last_reasons else "No window-specific reason codes emitted yet."
    quality_text = f"Quality windows: {quality_ok_windows}/{window_count}" if window_count > 0 else "No monitor windows have been published yet."
    runtime_policy_display = runtime_policy_display if isinstance(runtime_policy_display, dict) else {}
    display_phase = str(runtime_policy_display.get("runtimeDisplayPhase") or "")
    policy_text = str(runtime_policy_display.get("escalationPolicyText") or runtime_policy_display.get("lockSuppressionReasonText") or runtime_policy_display.get("evidenceWaitingReasonText") or "").strip()

    keyboard_status, keyboard_tone = _drift_channel_status(
        active=active,
        technical_failure=technical_failure,
        awaiting_evidence=awaiting_evidence,
        telemetry_fresh=telemetry_fresh,
        capture_fresh=capture_fresh,
        event_count=keyboard_event_count,
    )
    mouse_status, mouse_tone = _drift_channel_status(
        active=active,
        technical_failure=technical_failure,
        awaiting_evidence=awaiting_evidence,
        telemetry_fresh=telemetry_fresh,
        capture_fresh=capture_fresh,
        event_count=mouse_event_count,
    )
    combined_status, combined_tone = _combined_drift_status(
        active=active,
        technical_failure=technical_failure,
        awaiting_evidence=awaiting_evidence,
        telemetry_fresh=telemetry_fresh,
        window_count=window_count,
        quality_ok_windows=quality_ok_windows,
    )

    if display_phase == "suspicious_lock_delayed":
        combined_status, combined_tone = "Suspicious · lock delayed", "warn"
    elif display_phase == "suspicious_warning":
        combined_status, combined_tone = "Suspicious · warning", "warn"
    elif display_phase == "waiting_for_settled_evidence":
        combined_status, combined_tone = "Waiting for settled evidence", "warn"
    elif display_phase == "post_resume_verification":
        combined_status, combined_tone = "Verifying return", "warn"
    elif display_phase == "lock_confirmed":
        combined_status, combined_tone = "Lock confirmed", "danger"

    combined_confidence_available = bool(active and not technical_failure and not awaiting_evidence and window_count > 0 and quality_ok_windows > 0)
    combined_today = (
        f"Risk {risk_text}; average {avg_risk_text}; {quality_text}."
        if combined_confidence_available
        else f"{quality_text} Risk is withheld until monitor evidence is ready."
    )

    return [
        {
            "kind": "keyboard",
            "title": "Keyboard drift",
            "statusText": keyboard_status,
            "statusTone": keyboard_tone,
            "confidenceAvailable": False,
            "confidenceText": "Keyboard-specific confidence is not emitted by the backend yet.",
            "trend": [],
            "trendSource": "not_emitted",
            "trendUnavailableText": "No keyboard-specific trend is emitted by the backend yet.",
            "todayText": _evidence_capture_text("Keyboard", keyboard_event_count, active, capture_fresh),
            "baselineText": "Baseline readiness comes from the trusted BioAuth profile. No keyboard-specific baseline drift score is emitted yet.",
            "explainabilityText": "Uses live keyboard capture counters and monitor readiness only; no keyboard drift score is synthesized.",
            "whyText": "This card stays unavailable or capture-only until real keyboard-specific drift diagnostics are published.",
        },
        {
            "kind": "mouse",
            "title": "Mouse drift",
            "statusText": mouse_status,
            "statusTone": mouse_tone,
            "confidenceAvailable": False,
            "confidenceText": "Mouse-specific confidence is not emitted by the backend yet.",
            "trend": [],
            "trendSource": "not_emitted",
            "trendUnavailableText": "No mouse-specific trend is emitted by the backend yet.",
            "todayText": _evidence_capture_text("Mouse", mouse_event_count, active, capture_fresh),
            "baselineText": "Baseline readiness comes from the trusted BioAuth profile. No mouse-specific baseline drift score is emitted yet.",
            "explainabilityText": "Uses live mouse capture counters and monitor readiness only; no mouse drift score is synthesized.",
            "whyText": "This card stays unavailable or capture-only until real mouse-specific drift diagnostics are published.",
        },
        {
            "kind": "combined",
            "title": "Combined drift",
            "statusText": combined_status,
            "statusTone": combined_tone,
            "confidenceAvailable": combined_confidence_available,
            "confidenceText": quality_text if combined_confidence_available else "Not enough monitor evidence for confidence yet.",
            "trend": recent_risks,
            "trendSource": "runtime_recent_risks" if recent_risks else "unavailable",
            "trendUnavailableText": "A combined trend appears only after the monitor publishes at least two recent risk samples.",
            "todayText": combined_today,
            "baselineText": "Baseline readiness comes from the trusted BioAuth profile; combined drift evidence is interpreted only when monitor windows are available.",
            "explainabilityText": policy_text or (summary_text if summary_text and summary_text != "none" else reason_text),
            "whyText": policy_text or "This card uses monitor window counts, quality windows, and recent risk samples from runtimeState.",
        },
    ]
