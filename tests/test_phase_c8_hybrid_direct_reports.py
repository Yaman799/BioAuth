from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from hybrid_candidates.offline_runner import write_offline_hybrid_direct_reports
from hybrid_candidates.registry import list_candidates
from hybrid_candidates.reports import HYBRID_DIRECT_REPORT_SCHEMA_VERSION, generate_hybrid_direct_reports
from hybrid_candidates.schema import CandidateResult


def _result(candidate_id: str, group: str, risk: float | None, decision: str, *, available: bool = True, reason: str = "ok", latency_ms: float = 2.0, can_vote: bool = True) -> dict[str, Any]:
    return CandidateResult(
        id=candidate_id,
        display_name=candidate_id.replace("_", " ").title(),
        group=group,
        available=available,
        trained_artifact_loaded=available,
        risk=risk if available else None,
        decision=decision if available else "unavailable",
        can_vote=can_vote if available else False,
        can_lock_alone=False,
        reason=reason,
        latency_ms=latency_ms,
        artifact_id="sha256:test" if available else "",
        threshold_source="test_threshold" if available else "not_available",
        errors=[],
    ).to_dict()


def _synthetic_records() -> list[dict[str, Any]]:
    return [
        {
            "session_id": "owner-1",
            "label": "owner",
            "candidate_results": [
                _result("classic_isolation_forest", "classic", 0.12, "genuine", latency_ms=1.0),
                _result("keyboard_type2branch", "keyboard", 0.20, "genuine", latency_ms=10.0),
                _result("mouse_resnet_gru", "mouse", None, "unavailable", available=False, reason="missing_trained_artifact"),
            ],
            "keyboard_events": [{"key": "must_not_be_written"}],
            "mouse_events": [{"x": 1, "y": 2}],
        },
        {
            "session_id": "intruder-1",
            "label": "intruder",
            "candidate_results": [
                _result("classic_isolation_forest", "classic", 0.91, "intruder", latency_ms=2.0),
                _result("keyboard_typeformer", "keyboard", 0.82, "intruder", latency_ms=12.0),
                _result("mouse_resnet_gru", "mouse", None, "unavailable", available=False, reason="missing_trained_artifact"),
            ],
        },
        {
            "session_id": "unknown-1",
            "label": "unknown",
            "candidate_results": [
                _result("classic_isolation_forest", "classic", 0.77, "intruder", latency_ms=3.0),
                _result("keyboard_siamese_triplet", "keyboard", 0.70, "intruder", latency_ms=13.0),
            ],
        },
    ]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_c8_generates_all_requested_report_files(tmp_path: Path) -> None:
    result = generate_hybrid_direct_reports(_synthetic_records(), tmp_path / "reports" / "hybrid_direct")
    assert result["schema_version"] == HYBRID_DIRECT_REPORT_SCHEMA_VERSION
    assert result["report_only"] is True
    assert result["promotion_performed"] is False
    assert result["benchmark_selection_performed"] is False
    assert result["can_influence_device"] is False
    assert result["trigger_face_confirmation"] is False

    expected_names = {
        "candidate_results.jsonl",
        "candidate_metrics.json",
        "model_comparison.csv",
        "group_vote_comparison.csv",
        "fusion_report.json",
        "thresholds.json",
        "threshold_diagnostics.csv",
        "dataset_diagnostics.json",
        "latency_report.csv",
        "hybrid_direct_summary.md",
        "candidate_ranking.json",
        "candidate_ranking.csv",
        "launch_recommendation_diagnostics.md",
        "fusion_retraining_diagnostics.json",
    }
    paths = {Path(path) for path in result["report_paths"].values()}
    assert {path.name for path in paths} == expected_names
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)


def test_c8_model_comparison_has_every_registry_candidate_and_unavailable_reasons(tmp_path: Path) -> None:
    result = generate_hybrid_direct_reports(_synthetic_records(), tmp_path)
    rows = _read_csv(Path(result["report_paths"]["model_comparison"]))
    assert len(rows) == len(list_candidates())
    by_id = {row["candidate_id"]: row for row in rows}
    assert set(by_id) == {candidate.id for candidate in list_candidates()}

    isolation = by_id["classic_isolation_forest"]
    assert isolation["metrics_available"] == "True"
    assert isolation["metric_sample_count"] == "2"
    assert isolation["genuine_count"] == "1"
    assert isolation["intruder_count"] == "1"
    assert isolation["auc"] not in {"", "None"}
    assert isolation["eer_threshold"] not in {"", "None"}
    assert isolation["best_threshold"] not in {"", "None"}

    mouse = by_id["mouse_resnet_gru"]
    assert mouse["unavailable_count"] == "2"
    assert mouse["missing_artifact_count"] == "2"
    assert "missing_trained_artifact" in mouse["unavailable_reasons"]

    future_only = by_id["fusion_calibrated_stacking"]
    assert future_only["result_count"] == "0"
    assert future_only["metrics_available"] == "False"
    assert future_only["metrics_reason"] in {"empty_or_mismatched_inputs", "insufficient_labeled_samples"}
    assert future_only["can_lock_alone"] == "False"


def test_c8_unlabeled_sessions_are_diagnostics_only_not_metric_samples(tmp_path: Path) -> None:
    result = generate_hybrid_direct_reports(_synthetic_records(), tmp_path)
    rows = _read_csv(Path(result["report_paths"]["model_comparison"]))
    isolation = {row["candidate_id"]: row for row in rows}["classic_isolation_forest"]
    assert isolation["result_count"] == "3"
    assert isolation["metric_sample_count"] == "2"
    assert isolation["unlabeled_diagnostic_count"] == "1"

    jsonl = Path(result["report_paths"]["candidate_results"]).read_text(encoding="utf-8").splitlines()
    unknown_rows = [json.loads(line) for line in jsonl if json.loads(line)["session_id"] == "unknown-1"]
    assert unknown_rows
    assert all(row["label_status"] == "diagnostic_only" for row in unknown_rows)


def test_c8_insufficient_samples_never_fabricate_metrics(tmp_path: Path) -> None:
    owner_only_records = [
        {
            "session_id": "owner-only",
            "label": "owner",
            "candidate_results": [_result("classic_isolation_forest", "classic", 0.1, "genuine")],
        }
    ]
    result = generate_hybrid_direct_reports(owner_only_records, tmp_path)
    rows = _read_csv(Path(result["report_paths"]["model_comparison"]))
    isolation = {row["candidate_id"]: row for row in rows}["classic_isolation_forest"]
    assert isolation["metrics_available"] == "False"
    assert isolation["metrics_reason"] == "insufficient_intruder_test_data"
    assert isolation["auc"] in {"", "None"}
    assert isolation["eer"] in {"", "None"}
    assert isolation["far"] in {"", "None"}
    assert isolation["frr"] in {"", "None"}


def test_c8_group_and_fusion_reports_are_offline_report_only(tmp_path: Path) -> None:
    result = generate_hybrid_direct_reports(_synthetic_records(), tmp_path)
    group_rows = _read_csv(Path(result["report_paths"]["group_vote_comparison"]))
    assert group_rows
    assert all(row["can_lock_alone"] == "False" for row in group_rows)
    assert all(row["can_influence_device"] == "False" for row in group_rows)
    assert all(row["trigger_face_confirmation"] == "False" for row in group_rows)
    states = {row["offline_state"] for row in group_rows}
    assert "face_would_be_required" in states

    fusion = json.loads(Path(result["report_paths"]["fusion_report"]).read_text(encoding="utf-8"))
    assert fusion["report_only"] is True
    assert fusion["can_lock"] is False
    assert fusion["can_influence_device"] is False
    assert fusion["trigger_face_confirmation"] is False
    assert fusion["promotion_performed"] is False
    assert fusion["benchmark_selection_performed"] is False
    assert fusion["truth_table"][2]["offline_state"] == "face_would_be_required"


def test_c8_reports_exclude_raw_behavioral_payloads_even_if_input_contains_them(tmp_path: Path) -> None:
    result = generate_hybrid_direct_reports(_synthetic_records(), tmp_path)
    combined = "\n".join(Path(path).read_text(encoding="utf-8") for path in result["report_paths"].values())
    forbidden = [
        "must_not_be_written",
        "keyboard_events",
        "mouse_events",
        "raw_behavioral_data",
        "keystrokes",
        "mouse_points",
    ]
    for token in forbidden:
        assert token not in combined


def test_c8_offline_runner_facade_does_not_execute_or_promote_candidates(tmp_path: Path) -> None:
    result = write_offline_hybrid_direct_reports(_synthetic_records(), tmp_path)
    assert result["runner_schema_version"] == "hybrid-direct-offline-runner-v2"
    assert result["candidate_algorithms_executed"] is False
    assert result["production_selection_performed"] is False
    assert result["can_influence_device"] is False
    assert result["trigger_face_confirmation"] is False
    assert Path(result["report_paths"]["thresholds"]).exists()
