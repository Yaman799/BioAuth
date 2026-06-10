from __future__ import annotations

from pathlib import Path


def test_debug_snapshot_exposes_commercial_core_22d_diagnostics_contract() -> None:
    source = Path("src/bioauth/app/desktop_app_impl.py").read_text(encoding="utf-8")
    assert "debug_panel_schema_version" in source
    assert "commercial-core-22d-debug-panel-v1" in source
    assert "debug_health" in source
    assert "debug_production_approval" in source
    assert "debug_shadow" in source
    assert "debug_profile_summary" in source
    assert "BIOAUTH_ENABLE_SHADOW_EVIDENCE_MONITOR" in source
    assert "BIOAUTH_HYBRID_TEST_ONLY" in source
    assert "build_health_diagnostics" in source


def test_debug_panel_renders_required_diagnostic_sections() -> None:
    source = Path("debug_tools.py").read_text(encoding="utf-8")
    required_sections = [
        "[Startup / Environment]",
        "[Session State / Locks]",
        "[Training Readiness]",
        "[Protection / Monitor Readiness]",
        "[Production Approval / Promotion Gate]",
        "[Shadow Diagnostics]",
        "[Hybrid Removal Status]",
        "[Runtime / Fusion / Face Feedback]",
        "[Performance / Refresh]",
        "[Status]",
    ]
    for section in required_sections:
        assert section in source


def test_debug_panel_has_operator_buttons_for_summary_and_folders() -> None:
    source = Path("debug_tools.py").read_text(encoding="utf-8")
    assert "Copy summary" in source
    assert "Open logs folder" in source
    assert "Open control folder" in source
    assert "_copy_summary" in source
    assert "_open_control_folder" in source


def test_debug_diagnostics_are_cached_to_avoid_refresh_stalls() -> None:
    source = Path("src/bioauth/app/desktop_app_impl.py").read_text(encoding="utf-8")
    assert "_debug_health_diagnostics_cache" in source
    assert "_debug_health_diagnostics_cache_at" in source
    assert ">= 12.0" in source
    assert "BIOAUTH_DEBUG_PANEL_FULL_DIAGNOSTICS" in source
