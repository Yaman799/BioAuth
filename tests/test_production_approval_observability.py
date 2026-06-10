from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metadata_core.production_approval import (
    production_approval_observability_payload,
    production_approval_observability_signature,
    production_approval_status_for_user,
)


def test_structured_log_payload_includes_reason_code_without_raw_biometric_data() -> None:
    state = {
        "status": "pending",
        "phase": "shadow_validation",
        "candidate_status": "approved_for_shadow",
        "reason_code": "insufficient_shadow_windows",
        "protected_sessions_available": False,
        "windows_collected": 170,
        "windows_required": 600,
        "progress_percent": 28,
        "far": 0.021,
        "frr": 0.18,
        "next_action": "continue_using_device_normally",
        "raw_keyboard_events": ["k", "e", "y"],
        "mouse_events": [{"x": 1, "y": 2}],
        "keystrokes": "secret typing data",
    }
    payload = production_approval_observability_payload(state)
    assert payload == {
        "status": "pending",
        "phase": "shadow_validation",
        "candidate_status": "approved_for_shadow",
        "reason_code": "insufficient_shadow_windows",
        "protected_sessions_available": False,
        "windows_collected": 170,
        "windows_required": 600,
        "progress_percent": 28,
        "far": 0.021,
        "frr": 0.18,
        "next_action": "continue_using_device_normally",
    }
    forbidden = " ".join(payload.keys()).lower()
    for raw_name in ("raw_keyboard", "mouse_events", "keystrokes", "key_events", "cursor_path"):
        assert raw_name not in forbidden


def test_status_for_shadow_only_explains_pending_without_claiming_production_ready() -> None:
    message, tone = production_approval_status_for_user({
        "status": "pending",
        "candidate_status": "approved_for_shadow",
        "reason_code": "insufficient_shadow_windows",
        "protected_sessions_available": False,
        "windows_collected": 170,
        "windows_required": 600,
    })
    assert tone == "warn"
    assert "approved for shadow validation only" in message
    assert "170/600" in message
    assert "Protected Sessions remain unavailable" in message
    assert "Production approval is pending" in message
    assert "Production ready" not in message
    assert "Protected Sessions are available" not in message


def test_status_for_offline_rejected_includes_rejection_reason() -> None:
    message, tone = production_approval_status_for_user({
        "status": "blocked",
        "candidate_status": "rejected",
        "reason_code": "frr_too_high",
        "protected_sessions_available": False,
        "far": 0.02,
        "frr": 0.42,
    })
    assert tone == "warn"
    assert "rejected by offline approval checks" in message
    assert "frr_too_high" in message
    assert "Collect more high-quality sessions" in message


def test_production_ready_status_only_when_backend_protected_sessions_available() -> None:
    blocked_message, blocked_tone = production_approval_status_for_user({
        "status": "pending",
        "reason_code": "production_ready",
        "productionReady": True,
        "protected_sessions_available": False,
    })
    assert blocked_tone != "success"
    assert "Protected Sessions are available" not in blocked_message

    ready_message, ready_tone = production_approval_status_for_user({
        "status": "approved",
        "reason_code": "production_ready",
        "productionReady": True,
        "protected_sessions_available": True,
    })
    assert ready_tone == "success"
    assert "Protected Sessions are available" in ready_message


def test_auto_promotion_block_reason_is_surfaced_when_safe() -> None:
    message, tone = production_approval_status_for_user({
        "status": "blocked",
        "reason_code": "auto_promotion_disabled",
        "reason_text": "Production approval passed, but automatic promotion is disabled.",
        "protected_sessions_available": False,
    })
    assert tone == "warn"
    assert "Production approval is blocked" in message
    assert "automatic promotion is disabled" in message
    assert "Protected Sessions remain unavailable" in message


def test_missing_shadow_metrics_do_not_crash_observability_or_status() -> None:
    state = {
        "status": "pending",
        "candidateStatus": "approved_for_shadow",
        "reasonCode": "shadow_validation_not_started",
        "protectedSessionsAvailable": False,
    }
    payload = production_approval_observability_payload(state)
    assert payload["windows_collected"] is None
    assert payload["windows_required"] is None
    message, tone = production_approval_status_for_user(state)
    assert tone == "warn"
    assert "Shadow validation is pending" in message


def test_identical_observability_payloads_have_same_rate_limit_signature() -> None:
    state = {
        "status": "pending",
        "phase": "shadow_validation",
        "candidate_status": "approved_for_shadow",
        "reason_code": "approved_for_shadow_only",
        "protected_sessions_available": False,
    }
    first = production_approval_observability_signature(state)
    second = production_approval_observability_signature(dict(reversed(list(state.items()))))
    changed = production_approval_observability_signature({**state, "reason_code": "insufficient_shadow_windows"})
    assert first == second
    assert changed != first


def test_desktop_logging_path_is_rate_limited_and_uses_structured_payload() -> None:
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    assert "_maybe_log_production_approval_state" in desktop
    assert "production_approval_observability_payload" in desktop
    assert "production_approval_observability_signature" in desktop
    assert "_last_production_approval_log_signature" in desktop
    assert "60.0" in desktop
    assert "Production approval state refreshed" in desktop
    forbidden = "raw_keyboard_events mouse_events keystrokes rawMouse rawKeyboard".split()
    logging_block = desktop[desktop.index("def _maybe_log_production_approval_state"):desktop.index("def _observe_production_approval_state")]
    for token in forbidden:
        assert token not in logging_block


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("8 focused production approval observability tests passed", flush=True)
