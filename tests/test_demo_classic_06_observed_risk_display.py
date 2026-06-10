from __future__ import annotations

from bridge.runtime_labels import extract_observed_risk, runtime_policy_display_fields
from bridge.refresh_dashboard_helpers import status_for_dashboard
from bridge.i18n import translate_string


class _DummyBridge:
    def _t(self, key: str, **kwargs):
        return translate_string("en", key, **kwargs)


def test_observed_risk_extracted_from_last_window_diag_display_only():
    state = {
        "active": True,
        "status": "insufficient_evidence",
        "decision": "pending",
        "runtime_last_window_diag": {
            "risk": 93.0,
            "reason_codes": ["severe_risk", "transition_window"],
            "quality_ok": False,
            "quality_lock_ok": False,
        },
    }

    observed = extract_observed_risk(state)

    assert observed["observed_risk"] == 93.0
    assert observed["observed_risk_source"] == "runtime_last_window_diag.risk"
    assert observed["observed_risk_display_only"] is True
    assert observed["observed_risk_decision_qualified"] is False
    assert observed["observed_risk_quality_ok"] is False
    assert observed["observed_risk_quality_lock_ok"] is False


def test_observed_risk_extracted_from_top_risky_windows_max():
    state = {
        "active": True,
        "status": "insufficient_evidence",
        "decision": "pending",
        "runtime_last_window_diag": {},
        "runtime_top_risky_windows": [
            {"risk": 54},
            {"risk": 93},
            {"risk": 72},
        ],
    }

    observed = extract_observed_risk(state)

    assert observed["observed_risk"] == 93.0
    assert observed["observed_risk_source"] == "runtime_top_risky_windows.max"
    assert observed["observed_risk_display_only"] is True


def test_pending_runtime_display_shows_observed_risk_without_decision_risk():
    display = runtime_policy_display_fields(
        {
            "active": True,
            "session_kind": "protected",
            "status": "insufficient_evidence",
            "decision": "pending",
            "runtime_window_count": 1,
            "runtime_quality_lock_ok_windows": 0,
            "runtime_last_window_diag": {
                "risk": 92,
                "reason_codes": ["severe_risk", "insufficient_evidence"],
                "quality_lock_ok": False,
            },
        },
        flow="protected_active",
        active=True,
        monitor_ready=True,
        monitor_heartbeat_fresh=True,
        capture_fresh=True,
    )

    assert display["risk_display_mode"] == "observed_risk_pending"
    assert display["decision_risk"] is None
    assert display["observed_risk"] == 92.0
    assert "Decision Risk --" in display["runtimeDisplayText"]
    assert "Observed 92" in display["runtimeDisplayText"]
    assert display["observed_risk_display_only"] is True


def test_status_message_uses_observed_risk_when_awaiting_evidence():
    message, tone = status_for_dashboard(
        _DummyBridge(),
        {},
        {
            "active": True,
            "flow": "protected_active",
            "awaitingEvidence": True,
            "activeText": "Collecting evidence",
            "decisionLabel": "Pending",
            "decisionText": "pending",
            "runtimeDisplayText": "Collecting evidence · Pending · Decision Risk -- · Observed 92",
            "observedRiskAvailable": True,
            "observedRiskText": "92",
        },
    )

    assert tone == "warn"
    assert "Decision Risk --" in message
    assert "Observed 92" in message


def test_decision_risk_still_wins_over_observed_risk():
    display = runtime_policy_display_fields(
        {
            "active": True,
            "session_kind": "protected",
            "status": "ok",
            "decision": "suspicious",
            "risk": 86,
            "avg_risk": 86.5,
            "runtime_window_count": 3,
            "runtime_quality_lock_ok_windows": 3,
            "runtime_last_window_diag": {"risk": 93, "quality_lock_ok": True},
        },
        flow="protected_active",
        active=True,
        monitor_ready=True,
        monitor_heartbeat_fresh=True,
        capture_fresh=True,
    )

    assert display["risk_display_mode"] == "decision_risk"
    assert display["decision_risk"] == 86.0
    assert "Observed 93" not in display["runtimeDisplayText"]


def test_no_observed_risk_keeps_placeholder_status_line():
    message, tone = status_for_dashboard(
        _DummyBridge(),
        {},
        {
            "active": True,
            "flow": "protected_active",
            "activeText": "Live protected",
            "decisionLabel": "Pending",
            "decisionText": "pending",
            "riskText": "--",
            "avgRiskText": "--",
            "riskDisplayMode": "no_risk_available",
        },
    )

    assert tone == "info"
    assert "Risk --" in message
    assert "Avg --" in message


def test_observed_risk_does_not_request_lock_or_change_decision():
    state = {
        "active": True,
        "status": "insufficient_evidence",
        "decision": "pending",
        "runtime_locking_allowed": False,
        "runtime_last_window_diag": {
            "risk": 99,
            "quality_lock_ok": False,
            "reason_codes": ["insufficient_evidence"],
        },
    }

    display = runtime_policy_display_fields(
        state,
        flow="protected_active",
        active=True,
        monitor_ready=True,
        monitor_heartbeat_fresh=True,
        capture_fresh=True,
    )

    assert display["observed_risk"] == 99.0
    assert display["observed_risk_display_only"] is True
    assert display["canLockNow"] is False
    assert state["decision"] == "pending"
    assert "protected_action_requested" not in display
