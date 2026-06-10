from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "qml"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_developer_appshell_navigation_sections_are_declared() -> None:
    text = _read("qml/AppShell.qml")
    for title in [
        "Overview",
        "Live Session",
        "Hybrid Direct Test",
        "Profile & Training",
        "Model Evaluation",
        "Sessions & Data",
        "Drift Lab",
        "Settings",
    ]:
        assert title in text
    assert "HybridDirectTestPage { rootWindow: shell }" in text
    assert "ModelEvaluationPage { rootWindow: shell }" in text
    assert "navSelection === 7" in text


def test_phase_3_placeholder_pages_exist_and_are_display_only() -> None:
    for rel, object_name in [
        ("qml/pages/HybridDirectTestPage.qml", "hybridDirectTestPage"),
        ("qml/pages/ModelEvaluationPage.qml", "modelEvaluationPage"),
    ]:
        path = ROOT / rel
        assert path.exists(), f"missing placeholder page: {rel}"
        text = path.read_text(encoding="utf-8")
        assert f'objectName: "{object_name}"' in text
        if rel == "qml/pages/HybridDirectTestPage.qml":
            assert "backend.hybridDirectState" in text
            assert "backend.hybridDirectCandidateGroups" in text
            stripped = text
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
            assert "onClicked: backend.runHybridDirectTest()" in text
        else:
            assert "Display-only page for Phase 3" in text
            assert "backend." not in text.replace("backend.theme", "")
            assert "onClicked:" not in text
        assert "Timer {" not in text


def test_phase_3_qml_does_not_add_local_readiness_or_approval_computation() -> None:
    qml_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in QML.rglob("*.qml"))
    forbidden = (
        r"function\s+\w*productionReady\w*\s*\(",
        r"\b(?:var|let|const|property\s+bool)\s+productionReady\b",
        r"^\s*productionReady\s*:",
        r"\bproductionReady\s*=(?!=)",
        r"function\s+\w*protectedSessionsAvailable\w*\s*\(",
        r"\b(?:var|let|const|property\s+bool)\s+protectedSessionsAvailable\b",
        r"^\s*protectedSessionsAvailable\s*:",
        r"\bprotectedSessionsAvailable\s*=(?!=)",
    )
    for pattern in forbidden:
        assert re.search(pattern, qml_text, flags=re.MULTILINE) is None
