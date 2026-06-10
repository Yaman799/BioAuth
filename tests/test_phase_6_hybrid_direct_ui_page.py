from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML_PAGE = ROOT / "qml" / "pages" / "HybridDirectTestPage.qml"
APP_SHELL = ROOT / "qml" / "AppShell.qml"


def _page() -> str:
    return QML_PAGE.read_text(encoding="utf-8")


def test_hybrid_direct_page_is_registered_and_reads_backend_contract() -> None:
    app_shell = APP_SHELL.read_text(encoding="utf-8")
    page = _page()
    assert "HybridDirectTestPage { rootWindow: shell }" in app_shell
    assert 'objectName: "hybridDirectTestPage"' in page
    assert "readonly property var hybridState: backend.hybridDirectState || ({})" in page
    assert "readonly property var safetyGates: hybridState.safety_gate_results || ({})" in page
    assert "readonly property var candidateGroups: backend.hybridDirectCandidateGroups || []" in page
    assert "readonly property var groupVotes: backend.hybridDirectGroupVotes || []" in page
    assert "readonly property var latestReportState: backend.latestHybridDirectReportState || ({})" in page


def test_hybrid_direct_page_displays_required_contract_sections() -> None:
    page = _page()
    required_labels = [
        "Classic Layer",
        "Keyboard Verifier",
        "Mouse Verifier",
        "Backend combined_risk payload",
        "Fusion State",
        "Agreement count",
        "Divergence reason",
        "Final decision",
        "Safety gate status",
        "Latency",
        "Errors",
        "No single model can lock",
        "Developer Direct Live Mode remains OFF by default",
        "Run Hybrid Direct Test is a test/replay/offline-style monitor evaluation",
        "no lock, no Face Confirmation, and no device influence",
        "QML does not decide pass/fail",
        "Candidate groups and results",
        "Classic Candidates",
        "Keyboard Candidates",
        "Mouse Candidates",
        "One-Class Deep Candidates",
        "Combined Candidates",
        "Fusion Candidates",
        "Group Votes",
        "Latest Reports",
        "No report generated yet",
        "Open Latest Report",
        "Export CSV",
        "Clear Test Results",
        "Enable Developer Direct Live Mode",
    ]
    for label in required_labels:
        assert label in page


def test_hybrid_direct_controls_are_backend_wired_but_live_controls_remain_disabled() -> None:
    page = _page()
    for object_name in (
        "hybridDirectEnableButton",
        "hybridDirectDisableButton",
    ):
        pattern = rf'objectName:\s+"{re.escape(object_name)}";[^\n]+enabled:\s+false'
        assert re.search(pattern, page), f"{object_name} must be present and disabled"

    assert 'objectName: "hybridDirectRunDecisionButton"' in page
    assert "enabled: backend.canRunHybridDirectTest" in page
    assert "debugLabel: backend.hybridDirectTestUnavailableReason" in page
    assert "backend.hybridDirectTestRunning" in page
    assert "onClicked: backend.runHybridDirectTest()" in page

    assert 'objectName: "hybridDirectOpenLatestReportButton"' in page
    assert "onClicked: backend.openLatestHybridDirectReport()" in page
    assert 'objectName: "hybridDirectExportLogButton"' in page
    assert "onClicked: backend.exportHybridDirectCsv()" in page
    assert 'objectName: "hybridDirectClearTestResultsButton"' in page
    assert "onClicked: backend.clearHybridDirectTestResults()" in page

    # Offline report actions may return paths or clear in-memory display state,
    # but must stay separate from Developer Direct Live enable/disable behavior.
    assert "backend.enable" not in page
    assert "backend.disable" not in page
    assert "Developer Direct Live Mode is separate and remains gated off" in page


def test_hybrid_direct_page_has_no_fake_scores_or_local_fusion_logic() -> None:
    page = _page()
    forbidden = [
        r"fake",
        r"demo score",
        r"mock score",
        r"score:\s*0\.[0-9]+",
        r"risk:\s*0\.[0-9]+",
        r"function\s+\w*fusion\w*\(",
        r"function\s+\w*readiness\w*\(",
        r"computeFusion",
        r"Green\s*/\s*Amber\s*/\s*Red\s*\?",
        r"final_action\s*=",
    ]
    for pattern in forbidden:
        assert re.search(pattern, page, flags=re.IGNORECASE) is None


def test_hybrid_direct_page_does_not_call_backend_except_owned_state_theme_and_test_slot() -> None:
    page = _page()
    stripped = page
    for allowed in (
        "backend.theme",
        "backend.hybridDirectState",
        "backend.latestHybridDirectTestResult",
        "backend.hybridDirectCandidateGroups",
        "backend.hybridDirectGroupVotes",
        "backend.latestHybridDirectReportState",
        "backend.latestHybridLiveSessionEvalResult",
        "backend.latestHybridLiveSessionEvalReportState",
        "backend.liveCandidateObserverState",
        "backend.canRunHybridDirectTest",
        "backend.hybridDirectTestRunning",
        "backend.hybridDirectTestUnavailableReason",
        "backend.runHybridDirectTest()",
        "backend.evaluateLatestHybridLiveSession()",
        "backend.openLatestHybridDirectReport()",
        "backend.openLatestHybridLiveSessionEvalReport()",
        "backend.exportHybridDirectCsv()",
        "backend.clearHybridDirectTestResults()",
    ):
        stripped = stripped.replace(allowed, "")
    assert "backend." not in stripped
    assert "Timer {" not in page


def test_hybrid_direct_page_avoids_local_readiness_and_approval_state() -> None:
    page = _page()
    forbidden = (
        r"function\s+\w*productionReady\w*\s*\(",
        r"\b(?:var|let|const|property\s+bool)\s+productionReady\b",
        r"^\s*productionReady\s*:",
        r"function\s+\w*protectedSessionsAvailable\w*\s*\(",
        r"\b(?:var|let|const|property\s+bool)\s+protectedSessionsAvailable\b",
        r"^\s*protectedSessionsAvailable\s*:",
        r"function\s+\w*modelReady\w*\s*\(",
        r"\b(?:var|let|const|property\s+bool)\s+modelReady\b",
        r"approvalPassed\s*:",
        r"function\s+\w*readiness\w*\s*\(",
    )
    for pattern in forbidden:
        assert re.search(pattern, page, flags=re.MULTILINE | re.IGNORECASE) is None
