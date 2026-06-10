from __future__ import annotations

import re
from pathlib import Path

import bridge.refresh_runtime_helpers as runtime_helpers

ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = ROOT / "qml"

MAIN_DASHBOARD_QML = (
    QML_ROOT / "AppShell.qml",
    QML_ROOT / "pages" / "OverviewPage.qml",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _all_qml_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in QML_ROOT.rglob("*.qml"))


def test_main_dashboard_does_not_render_last_refresh_label() -> None:
    combined = "\n".join(_read(path) for path in MAIN_DASHBOARD_QML)
    forbidden_visible_labels = (
        "Last refresh",
        "Last refreshed",
        "آخر تحديث",
    )
    for label in forbidden_visible_labels:
        assert label not in combined
    assert "lastRefreshDurationMs" not in combined


def test_live_telemetry_panel_does_not_render_last_refresh_label_if_it_was_visible_there() -> None:
    panel = _read(QML_ROOT / "components" / "LiveTelemetryPanel.qml")
    assert "Last refresh" not in panel
    assert "Last refreshed" not in panel
    assert "lastRefreshDurationMs" not in panel
    assert "lastRefreshCompletedAt" not in panel


def test_backend_refresh_payload_still_contains_refresh_metadata_if_preexisting() -> None:
    class Bridge:
        pass

    bridge = Bridge()
    runtime_helpers.set_dashboard_state(
        bridge,
        last_refresh_duration_ms=321,
        last_refresh_reason="runtime:timer",
        last_refresh_error="snapshot failed",
        completed_at=1234.5,
    )

    state = runtime_helpers.dashboard_state_payload(bridge)

    assert state["lastRefreshDurationMs"] == 321
    assert state["lastRefreshReason"] == "runtime:timer"
    assert state["lastRefreshError"] == "snapshot failed"
    assert state["lastRefreshCompletedAt"] == 1234.5


def test_refresh_logs_still_include_refresh_timing() -> None:
    refresh_helpers = _read(ROOT / "bridge" / "refresh_runtime_helpers.py")
    desktop = _read(ROOT / "desktop_app.py")

    assert "Slow refresh cycle completed" in refresh_helpers
    assert "dashboard_ms" in refresh_helpers
    assert "refresh_reason" in refresh_helpers
    assert "last_refresh_duration_ms=elapsed_ms" in refresh_helpers
    assert "refresh_interval_ms" in desktop


def test_qml_does_not_add_local_refresh_timer() -> None:
    app_shell = _read(QML_ROOT / "AppShell.qml")
    overview = _read(QML_ROOT / "pages" / "OverviewPage.qml")
    live_panel = _read(QML_ROOT / "components" / "LiveTelemetryPanel.qml")
    main_dashboard = "\n".join((app_shell, overview, live_panel))

    assert "Timer {" not in app_shell
    assert not re.search(r"Timer\s*\{[^}]*lastRefresh", main_dashboard, flags=re.DOTALL)
    assert not re.search(r"lastRefresh(DurationMs|CompletedAt)", main_dashboard)


def test_qml_does_not_compute_production_readiness() -> None:
    qml = _all_qml_text()
    forbidden = (
        r"function\s+\w*productionReady\w*\s*\(",
        r"\b(?:var|let|const|property\s+bool)\s+productionReady\b",
        r"^\s*productionReady\s*:",
        r"\bproductionReady\s*=(?!=)",
    )
    for pattern in forbidden:
        assert re.search(pattern, qml, flags=re.MULTILINE) is None


def test_qml_does_not_compute_protected_sessions_available() -> None:
    qml = _all_qml_text()
    forbidden = (
        r"function\s+\w*protectedSessionsAvailable\w*\s*\(",
        r"\b(?:var|let|const|property\s+bool)\s+protectedSessionsAvailable\b",
        r"^\s*protectedSessionsAvailable\s*:",
        r"\bprotectedSessionsAvailable\s*=(?!=)",
    )
    for pattern in forbidden:
        assert re.search(pattern, qml, flags=re.MULTILINE) is None


def test_qml_does_not_compute_retry_eligibility() -> None:
    qml = _all_qml_text()
    forbidden = (
        r"function\s+\w*retryEligibility\w*\s*\(",
        r"\b(?:var|let|const)\s+retryEligibility\b",
        r"^\s*retryEligibility\s*:",
        r"\bretryEligibility\s*=(?!=)",
    )
    for pattern in forbidden:
        assert re.search(pattern, qml, flags=re.MULTILINE) is None


def test_qml_does_not_compute_remediation_progress() -> None:
    qml = _all_qml_text()
    forbidden = (
        r"function\s+\w*remediationProgress\w*\s*\(",
        r"\b(?:var|let|const)\s+remediationProgress\b",
        r"^\s*remediationProgress\s*:",
        r"\bremediationProgress\s*=(?!=)",
    )
    for pattern in forbidden:
        assert re.search(pattern, qml, flags=re.MULTILINE) is None


def test_shadow_evidence_status_display_still_present_outside_overview() -> None:
    overview = _read(QML_ROOT / "pages" / "OverviewPage.qml")
    live_panel = _read(QML_ROOT / "components" / "LiveTelemetryPanel.qml")
    profile = _read(QML_ROOT / "pages" / "ProfilePage.qml")

    assert "shadow evidence" not in overview.lower()
    assert "Background validation" in live_panel
    assert "shadowLoop" in live_panel
    assert "Shadow phase" in profile


def test_production_approval_display_still_present_outside_overview() -> None:
    overview = _read(QML_ROOT / "pages" / "OverviewPage.qml")
    live_panel = _read(QML_ROOT / "components" / "LiveTelemetryPanel.qml")
    settings_performance = _read(QML_ROOT / "pages" / "settings" / "SettingsPerformanceTab.qml")

    assert "Production approval" not in overview
    assert "Production approval" in live_panel
    assert "Model status" in settings_performance
    assert "productionApproval" in live_panel
    assert "productionApproval" in settings_performance


def test_remediation_progress_display_still_present() -> None:
    live_panel = _read(QML_ROOT / "components" / "LiveTelemetryPanel.qml")
    assert "Remediation" in live_panel
    assert "Remediation progress" in live_panel
    assert "Retry eligibility" in live_panel
    assert "countsText" in live_panel
