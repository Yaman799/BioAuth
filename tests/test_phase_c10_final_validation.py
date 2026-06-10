from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hybrid_candidates.adapters import (
    DEEP_SEQUENCE_ADAPTER_IDS,
    KEYBOARD_ADVANCED_ADAPTER_IDS,
    ONE_CLASS_DEEP_ADAPTER_IDS,
    evaluate_advanced_keyboard_candidate,
    evaluate_deep_sequence_candidate,
    evaluate_one_class_deep_candidate,
)
from hybrid_candidates.fusion import evaluate_logistic_stacking
from hybrid_candidates.group_voting import build_group_votes, build_offline_group_voting_report
from hybrid_candidates.registry import list_candidates, validate_candidate_result
from hybrid_candidates.reports import HybridDirectRunRecord, generate_hybrid_direct_reports
from hybrid_candidates.schema import CandidateResult
from hybrid_candidates.ui_state import build_candidate_group_display_state, build_latest_report_status

ROOT = Path(__file__).resolve().parents[1]
QML_PAGE = ROOT / "qml" / "pages" / "HybridDirectTestPage.qml"
SESSION_RUNTIME_HELPERS = ROOT / "bridge" / "session_runtime_helpers.py"
DESKTOP_APP = ROOT / "desktop_app.py"


def _candidate(candidate_id: str, group: str, risk: float, decision: str) -> dict[str, Any]:
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
        reason="synthetic_offline_validation",
        latency_ms=3.5,
        artifact_id="sha256:c10-synthetic",
        threshold_source="synthetic_offline_threshold",
        errors=(),
    ).to_dict()


def test_c10_all_registered_candidates_are_offline_safe_and_non_locking() -> None:
    candidates = list_candidates()
    assert len(candidates) >= 24
    for candidate in candidates:
        payload = candidate.to_dict()
        assert payload["can_lock_alone"] is False
        assert payload["live_allowed"] is False
        assert tuple(payload["allowed_modes"]) in {(), ("offline", "hybrid_direct_test")}
        assert "live" not in payload["allowed_modes"]


def test_c10_missing_artifacts_and_untrained_deep_candidates_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.deep_sequence.optional_dependency_available", lambda name: True)
    monkeypatch.setattr("hybrid_candidates.adapters.one_class_deep.optional_dependency_available", lambda name: True)
    monkeypatch.setattr("hybrid_candidates.adapters.keyboard_advanced.optional_dependency_available", lambda name: True)

    results: list[dict[str, Any]] = []
    results.extend(evaluate_deep_sequence_candidate(candidate_id, [[0.1], [0.2], [0.3]]) for candidate_id in DEEP_SEQUENCE_ADAPTER_IDS)
    results.extend(evaluate_one_class_deep_candidate(candidate_id, [[0.1], [0.2], [0.3]]) for candidate_id in ONE_CLASS_DEEP_ADAPTER_IDS)
    results.extend(evaluate_advanced_keyboard_candidate(candidate_id, [[0.1], [0.2], [0.3], [0.4], [0.5], [0.6], [0.7], [0.8]]) for candidate_id in KEYBOARD_ADVANCED_ADAPTER_IDS)

    assert results
    for result in results:
        assert validate_candidate_result(result)["ok"] is True
        assert result["available"] is False
        assert result["trained_artifact_loaded"] is False
        assert result["risk"] is None
        assert result["decision"] == "unavailable"
        assert result["can_vote"] is False
        assert result["can_lock_alone"] is False
        assert result["reason"] == "missing_trained_artifact"


def test_c10_group_voting_counts_modality_groups_not_same_group_candidates() -> None:
    results = [
        _candidate("keyboard_bigru_cnn_attention", "keyboard", 0.91, "intruder"),
        _candidate("keyboard_type2branch", "keyboard", 0.89, "intruder"),
        _candidate("keyboard_typeformer", "keyboard", 0.87, "intruder"),
        _candidate("classic_isolation_forest", "classic", 0.18, "genuine"),
    ]
    votes = build_group_votes(results)
    active_votes = [vote for vote in votes if vote["can_vote"]]
    assert [vote["group"] for vote in active_votes] == ["classic", "keyboard"]
    keyboard = next(vote for vote in active_votes if vote["group"] == "keyboard")
    assert keyboard["decision"] == "intruder"
    assert set(keyboard["candidate_ids"]) == {"keyboard_bigru_cnn_attention", "keyboard_type2branch", "keyboard_typeformer"}
    report = build_offline_group_voting_report(results)
    assert report["summary"]["intruder_group_count"] == 1
    assert report["offline_fusion"]["offline_state"] == "amber"
    assert report["offline_fusion"]["can_lock"] is False
    assert report["offline_fusion"]["can_influence_device"] is False
    assert report["offline_fusion"]["trigger_face_confirmation"] is False


def test_c10_learned_fusion_is_artifact_gated_and_report_only() -> None:
    result = evaluate_logistic_stacking([
        _candidate("classic_isolation_forest", "classic", 0.88, "intruder"),
        _candidate("keyboard_type2branch", "keyboard", 0.86, "intruder"),
    ])
    assert validate_candidate_result(result)["ok"] is True
    assert result["available"] is False
    assert result["decision"] == "unavailable"
    assert result["risk"] is None
    assert result["can_vote"] is False
    assert result["can_lock_alone"] is False
    assert result["reason"] == "missing_trained_artifact"


def test_c10_reports_exclude_unknown_labels_from_metrics_and_never_promote(tmp_path: Path) -> None:
    records = [
        HybridDirectRunRecord(session_id="owner-1", label="owner", candidate_results=(_candidate("classic_isolation_forest", "classic", 0.12, "genuine"),)),
        HybridDirectRunRecord(session_id="intruder-1", label="intruder", candidate_results=(_candidate("classic_isolation_forest", "classic", 0.91, "intruder"),)),
        HybridDirectRunRecord(session_id="unknown-1", label="unknown", candidate_results=(_candidate("classic_isolation_forest", "classic", 0.50, "suspicious"),)),
    ]
    summary = generate_hybrid_direct_reports(records, output_dir=tmp_path)
    assert summary["session_count"] == 3
    summary_text = (tmp_path / "hybrid_direct_summary.md").read_text(encoding="utf-8")
    assert "Metric-eligible labeled sessions: 2" in summary_text
    assert "Diagnostics-only sessions: 1" in summary_text
    assert summary["promotion_performed"] is False
    assert summary["benchmark_selection_performed"] is False
    assert summary["can_influence_device"] is False
    assert summary["trigger_face_confirmation"] is False
    assert (tmp_path / "candidate_results.jsonl").exists()
    assert (tmp_path / "model_comparison.csv").exists()
    assert (tmp_path / "hybrid_direct_summary.md").exists()
    assert "raw_keyboard" not in summary_text.lower()
    assert "raw_mouse" not in summary_text.lower()


def test_c10_ui_state_is_backend_owned_and_report_only(tmp_path: Path) -> None:
    status = build_latest_report_status(tmp_path)
    assert status["available"] is False
    assert status["message"] == "No report generated yet."
    assert status["report_only"] is True
    assert status["promotion_performed"] is False
    assert status["benchmark_selection_performed"] is False
    assert status["can_influence_device"] is False
    assert status["trigger_face_confirmation"] is False
    assert status["runtime_authoritative"] is False
    assert status["can_lock"] is False
    assert status["can_lock_alone"] is False

    groups = build_candidate_group_display_state(tmp_path)
    assert groups
    assert all(group["can_lock_alone"] is False for group in groups)
    assert all(group["can_influence_device"] is False for group in groups)
    assert all(candidate["runtime_authoritative"] is False for group in groups for candidate in group["candidates"])


def test_c10_qml_does_not_compute_metrics_fusion_group_votes_or_readiness() -> None:
    page = QML_PAGE.read_text(encoding="utf-8")
    assert "backend.hybridDirectCandidateGroups" in page
    assert "backend.hybridDirectGroupVotes" in page
    assert "backend.latestHybridDirectReportState" in page
    assert "onClicked: backend.runHybridDirectTest()" in page
    assert "Enable Developer Direct Live Mode" in page
    assert "enabled: false" in page

    forbidden_patterns = [
        r"function\s+\w*(auc|eer|far|frr|metric|groupVote|fusion|readiness|safety)\w*\s*\(",
        r"candidatePayload\.risk\s*[><=]",
        r"votePayload\.risk\s*[><=]",
        r"faceConfirmation\s*\(",
        r"LockWorkStation",
        r"triggerFaceConfirmation",
        r"approveProduction",
        r"promotion_performed\s*:\s*true",
    ]
    for pattern in forbidden_patterns:
        assert re.search(pattern, page, flags=re.IGNORECASE) is None


def test_c10_hybrid_direct_test_runtime_contract_is_offline_only() -> None:
    helper = SESSION_RUNTIME_HELPERS.read_text(encoding="utf-8")
    desktop = DESKTOP_APP.read_text(encoding="utf-8")
    required = [
        '"BIOAUTH_HYBRID_TEST_ONLY": "1"',
        '"BIOAUTH_DEVICE_INFLUENCE_ALLOWED": "0"',
        '"lock_allowed": False',
        '"device_lock_allowed": False',
        '"face_confirmation_allowed": False',
        '"face_confirmation_trigger_allowed": False',
        '"production_promotion_allowed": False',
        '"raw_behavioral_data_included": False',
        '"device_influence_allowed": False',
        '"hybrid_direct_test_only"',
        '"device_influence_disabled"',
        '"face_confirmation_disabled"',
    ]
    for token in required:
        assert token in helper
    assert "def runHybridDirectTest" in (ROOT / "bridge" / "session_mixin.py").read_text(encoding="utf-8")
    assert '"deleted_files": False' in desktop
    assert '"report_files_preserved": True' in desktop


def test_c10_developer_direct_live_mode_remains_separate_and_gated_off_by_default() -> None:
    page = QML_PAGE.read_text(encoding="utf-8")
    live_area = re.search(r"Developer Direct Live Mode.*?Run Hybrid Direct Test", page, flags=re.DOTALL)
    assert live_area is not None
    assert "Live mode is separate and safety-gated" in page
    assert "Run Hybrid Direct Test never enables it" in page
    assert "enabled: false" in page
    assert "Face Confirmation before lock" in page
