from __future__ import annotations

import re
from pathlib import Path

from hybrid_candidates.reports import HybridDirectRunRecord, generate_hybrid_direct_reports
from hybrid_candidates.schema import CandidateResult
from hybrid_candidates.ui_state import (
    build_candidate_group_display_state,
    build_group_vote_display_state,
    build_latest_report_status,
)

ROOT = Path(__file__).resolve().parents[1]
QML_PAGE = ROOT / "qml" / "pages" / "HybridDirectTestPage.qml"
DESKTOP_APP = ROOT / "desktop_app.py"


def _candidate(candidate_id: str, group: str, risk: float, decision: str) -> dict:
    return CandidateResult(
        id=candidate_id,
        display_name=candidate_id.replace("_", " ").title(),
        group=group,
        available=True,
        trained_artifact_loaded=True,
        risk=risk,
        decision=decision,
        can_vote=True,
        can_lock_alone=False,
        reason="ok",
        latency_ms=12.5,
        artifact_id="synthetic-artifact",
        threshold_source="synthetic_offline_threshold",
        errors=(),
    ).to_dict()


def test_backend_ui_state_exposes_all_candidate_groups_without_report(tmp_path: Path) -> None:
    groups = build_candidate_group_display_state(tmp_path)
    titles = {group["title"] for group in groups}
    assert "Classic Candidates" in titles
    assert "Keyboard Candidates" in titles
    assert "Mouse Candidates" in titles
    assert "One-Class Deep Candidates" in titles
    assert "Combined Candidates" in titles
    assert "Fusion Candidates" in titles
    assert sum(group["candidate_count"] for group in groups) >= 24
    assert all(group["can_lock_alone"] is False for group in groups)
    assert all(group["can_influence_device"] is False for group in groups)
    assert any(candidate["reason"] == "no_report_generated" for group in groups for candidate in group["candidates"])


def test_backend_ui_state_reads_latest_report_metrics_without_qml_computation(tmp_path: Path) -> None:
    records = [
        HybridDirectRunRecord(
            session_id="owner-1",
            label="owner",
            candidate_results=(
                _candidate("keyboard_bigru_cnn_attention", "keyboard", 0.20, "genuine"),
                _candidate("keyboard_typeformer", "keyboard", 0.22, "genuine"),
                _candidate("mouse_resnet_gru", "mouse", 0.30, "genuine"),
            ),
        ),
        HybridDirectRunRecord(
            session_id="intruder-1",
            label="intruder",
            candidate_results=(
                _candidate("keyboard_bigru_cnn_attention", "keyboard", 0.90, "intruder"),
                _candidate("keyboard_typeformer", "keyboard", 0.88, "intruder"),
                _candidate("mouse_resnet_gru", "mouse", 0.91, "intruder"),
            ),
        ),
    ]
    summary = generate_hybrid_direct_reports(records, output_dir=tmp_path)
    assert summary["promotion_performed"] is False
    assert summary["benchmark_selection_performed"] is False

    status = build_latest_report_status(tmp_path)
    assert status["available"] is True
    assert status["can_influence_device"] is False
    assert status["trigger_face_confirmation"] is False
    assert status["runtime_authoritative"] is False
    assert status["model_rows"] >= 24

    groups = build_candidate_group_display_state(tmp_path)
    keyboard = next(group for group in groups if group["group"] == "keyboard")
    keyboard_rows = {candidate["id"]: candidate for candidate in keyboard["candidates"]}
    assert keyboard_rows["keyboard_bigru_cnn_attention"]["metrics_available"] is True
    assert keyboard_rows["keyboard_bigru_cnn_attention"]["auc"] is not None
    assert keyboard_rows["keyboard_bigru_cnn_attention"]["can_lock_alone"] is False
    assert keyboard_rows["keyboard_typeformer"]["can_lock_alone"] is False

    votes = build_group_vote_display_state(tmp_path)
    keyboard_votes = [vote for vote in votes if vote["group"] == "keyboard"]
    assert keyboard_votes, "backend report must expose keyboard group votes"
    assert all(vote["can_lock_alone"] is False for vote in votes)
    assert all(vote["can_influence_device"] is False for vote in votes)


def test_qml_displays_backend_owned_candidate_and_report_state_only() -> None:
    page = QML_PAGE.read_text(encoding="utf-8")
    required = [
        "backend.hybridDirectCandidateGroups",
        "backend.hybridDirectGroupVotes",
        "backend.latestHybridDirectReportState",
        "Candidate groups and results",
        "Group Votes",
        "Latest Reports",
        "No report generated yet",
        "Open Latest Report",
        "Export CSV",
        "Clear Test Results",
        "Enable Developer Direct Live Mode",
        "onClicked: backend.runHybridDirectTest()",
        "onClicked: backend.openLatestHybridDirectReport()",
        "onClicked: backend.exportHybridDirectCsv()",
        "onClicked: backend.clearHybridDirectTestResults()",
    ]
    for token in required:
        assert token in page

    forbidden = [
        r"function\s+\w*(auc|eer|far|frr|metric|groupVote|fusion)\w*\s*\(",
        r"AUC\s*=",
        r"EER\s*=",
        r"FAR\s*=",
        r"FRR\s*=",
        r"faceConfirmation\s*\(",
        r"LockWorkStation",
        r"candidatePayload\.risk\s*[><]=",
        r"votePayload\.risk\s*[><]=",
    ]
    for pattern in forbidden:
        assert re.search(pattern, page, flags=re.IGNORECASE) is None


def test_developer_live_mode_remains_disabled_and_separate_from_offline_run() -> None:
    page = QML_PAGE.read_text(encoding="utf-8")
    enable_block = re.search(r'objectName:\s+"hybridDirectEnableButton"[^\n]+', page)
    assert enable_block, "Developer Direct Live Mode button must remain present"
    assert "Enable Developer Direct Live Mode" in enable_block.group(0)
    assert "enabled: false" in enable_block.group(0)
    assert "Run Hybrid Direct Test never enables it" in page
    assert "enabled: backend.canRunHybridDirectTest" in page
    assert "Developer Direct Live Mode is separate and remains gated off" in page


def test_desktop_bridge_exposes_backend_owned_ui_state_and_report_slots() -> None:
    desktop = DESKTOP_APP.read_text(encoding="utf-8")
    assert re.search(r'@Property\("QVariantList", notify=hybridDirectChanged\)\s+def hybridDirectCandidateGroups', desktop)
    assert re.search(r'@Property\("QVariantList", notify=hybridDirectChanged\)\s+def hybridDirectGroupVotes', desktop)
    assert re.search(r'@Property\("QVariantMap", notify=hybridDirectChanged\)\s+def latestHybridDirectReportState', desktop)
    assert re.search(r'@Slot\(result="QVariantMap"\)\s+def openLatestHybridDirectReport', desktop)
    assert re.search(r'@Slot\(result="QVariantMap"\)\s+def exportHybridDirectCsv', desktop)
    assert re.search(r'@Slot\(result="QVariantMap"\)\s+def clearHybridDirectTestResults', desktop)
    assert '"deleted_files": False' in desktop
    assert '"report_files_preserved": True' in desktop
    assert '"can_influence_device": False' in desktop
    assert '"trigger_face_confirmation": False' in desktop
