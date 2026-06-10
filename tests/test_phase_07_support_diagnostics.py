from __future__ import annotations

import json
from pathlib import Path

import pytest

from support_bundle import assert_support_bundle_safe, build_health_diagnostics, bundle_payload, write_support_bundle


def test_phase_07_support_bundle_includes_health_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOAUTH_LOCALAPPDATA", str(tmp_path))
    runtime_state = {"status": "monitoring", "runtime_ready": True, "runtime_diagnostic_code": "ok"}

    payload = bundle_payload(user_id="owner", runtime_state=runtime_state)

    assert payload["schema_version"] >= 2
    assert payload["privacy_boundary"]["contains_raw_input_events"] is False
    diagnostics = payload["support_diagnostics"]
    assert diagnostics["policy_version"] == "commercial-core-07-support-diagnostics-v1"
    assert isinstance(diagnostics["checks"], list)
    assert {check["id"] for check in diagnostics["checks"]} >= {
        "session_state_lock",
        "session_state_file",
        "runtime_summary",
        "shadow_mode",
        "bioauth_processes",
    }
    assert_support_bundle_safe(payload)


def test_phase_07_support_bundle_redacts_sensitive_extra(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOAUTH_LOCALAPPDATA", str(tmp_path))
    payload = bundle_payload(
        user_id="owner",
        runtime_state={"status": "idle", "face_confirmation": {"template_digest": "secret", "embedding": [1, 2, 3]}},
        extra={"command": "tool --access_token=abc --password=hunter2", "safe": True},
    )

    encoded = json.dumps(payload, sort_keys=True).lower()
    assert "hunter2" not in encoded
    assert "access_token=abc" not in encoded
    assert "template_digest" not in encoded
    assert "embedding" not in encoded
    assert_support_bundle_safe(payload)


def test_phase_07_write_support_bundle_persists_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOAUTH_LOCALAPPDATA", str(tmp_path))

    path = write_support_bundle(user_id="owner", runtime_state={"status": "idle"})

    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "support_diagnostics" in data
    assert data["support_diagnostics"]["policy_version"] == "commercial-core-07-support-diagnostics-v1"
    assert_support_bundle_safe(data)


def test_phase_07_health_diagnostics_shadow_without_user_is_non_blocking(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOAUTH_LOCALAPPDATA", str(tmp_path))

    diagnostics = build_health_diagnostics(user_id=None, runtime_state={})

    assert diagnostics["overall_status"] in {"ok", "warn"}
    shadow = diagnostics["shadow"]
    assert shadow["available"] is False
    assert shadow["reason"] == "no_user_id"
    shadow_check = next(check for check in diagnostics["checks"] if check["id"] == "shadow_mode")
    assert shadow_check["status"] == "ok"
