from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

from hybrid_candidates.artifact_resolver import build_candidate_bundle_artifact_resolver
from hybrid_candidates.ranking import (
    FUSION_ARTIFACT_FILENAMES,
    LEARNED_FUSION_CANDIDATE_IDS,
    P2C_FUSION_RETRAINING_SCHEMA_VERSION,
    P2C_RANKING_SCHEMA_VERSION,
    build_fusion_retraining_diagnostics,
)
from hybrid_candidates.registry import list_candidates
from hybrid_candidates.reports import generate_hybrid_direct_reports
from hybrid_candidates.schema import CandidateResult


def _candidate_result(candidate_id: str, group: str, risk: float | None, *, available: bool = True, reason: str = "test") -> dict[str, Any]:
    return CandidateResult(
        id=candidate_id,
        display_name=candidate_id.replace("_", " ").title(),
        group=group,
        available=bool(available),
        trained_artifact_loaded=bool(available),
        risk=None if not available else float(risk if risk is not None else 0.0),
        decision="unavailable" if not available else ("intruder" if float(risk or 0.0) >= 0.5 else "genuine"),
        can_vote=False,
        can_lock_alone=False,
        reason=reason,
        latency_ms=3.0,
        artifact_id="sha256:test" if available else "",
        threshold_source="test_threshold" if available else "not_available",
        errors=(),
    ).to_dict()


def _records_for_ranking(*, collapsed: bool = False, include_unavailable_keyboard: bool = False) -> list[dict[str, Any]]:
    non_fusion = [candidate for candidate in list_candidates() if candidate.group != "fusion"]
    records: list[dict[str, Any]] = []
    for idx in range(12):
        results = []
        for candidate in non_fusion:
            if include_unavailable_keyboard and candidate.id == "keyboard_typeformer":
                results.append(_candidate_result(candidate.id, candidate.group, None, available=False, reason="missing_trained_artifact"))
                continue
            risk = 0.42 if collapsed and candidate.id == "classic_lof" else 0.08 + ((idx % 4) * 0.01)
            results.append(_candidate_result(candidate.id, candidate.group, risk))
        results.extend(
            [
                _candidate_result("fusion_rule_based", "fusion", 0.2),
                _candidate_result("fusion_logistic_stacking", "fusion", None, available=False, reason="missing_trained_artifact"),
                _candidate_result("fusion_calibrated_stacking", "fusion", None, available=False, reason="missing_trained_artifact"),
            ]
        )
        records.append({"session_id": f"owner-{idx}", "label": "owner", "replay_eligible": True, "candidate_results": results})
    for idx in range(12):
        results = []
        for candidate in non_fusion:
            if include_unavailable_keyboard and candidate.id == "keyboard_typeformer":
                results.append(_candidate_result(candidate.id, candidate.group, None, available=False, reason="missing_trained_artifact"))
                continue
            risk = 0.42 if collapsed and candidate.id == "classic_lof" else 0.82 + ((idx % 4) * 0.01)
            results.append(_candidate_result(candidate.id, candidate.group, risk))
        results.extend(
            [
                _candidate_result("fusion_rule_based", "fusion", 0.85),
                _candidate_result("fusion_logistic_stacking", "fusion", None, available=False, reason="missing_trained_artifact"),
                _candidate_result("fusion_calibrated_stacking", "fusion", None, available=False, reason="missing_trained_artifact"),
            ]
        )
        records.append({"session_id": f"intruder-{idx}", "label": "intruder", "replay_eligible": True, "candidate_results": results})
    return records


def test_p2c_ranking_reports_include_all_candidates_and_are_report_only(tmp_path: Path) -> None:
    summary = generate_hybrid_direct_reports(_records_for_ranking(), output_dir=tmp_path, source="p2c_test")
    paths = {key: Path(value) for key, value in summary["report_paths"].items()}
    for key in ["candidate_ranking", "candidate_ranking_csv", "launch_recommendation_diagnostics", "fusion_retraining_diagnostics"]:
        assert paths[key].exists(), key
    ranking = json.loads(paths["candidate_ranking"].read_text(encoding="utf-8"))
    assert ranking["schema_version"] == P2C_RANKING_SCHEMA_VERSION
    assert ranking["candidate_count"] == len(list_candidates()) == 24
    assert ranking["report_only"] is True
    assert ranking["production_selection_performed"] is False
    assert ranking["promotion_performed"] is False
    assert ranking["runtime_authoritative"] is False
    assert {row["candidate_id"] for row in ranking["candidates"]} == {candidate.id for candidate in list_candidates()}
    assert all(row["can_lock_alone"] is False for row in ranking["candidates"])
    assert "Diagnostic-only candidate ranking" in paths["launch_recommendation_diagnostics"].read_text(encoding="utf-8")


def test_p2c_collapsed_and_unavailable_candidates_are_flagged_not_hidden(tmp_path: Path) -> None:
    summary = generate_hybrid_direct_reports(
        _records_for_ranking(collapsed=True, include_unavailable_keyboard=True),
        output_dir=tmp_path,
        source="p2c_test",
    )
    ranking = json.loads(Path(summary["report_paths"]["candidate_ranking"]).read_text(encoding="utf-8"))
    by_id = {row["candidate_id"]: row for row in ranking["candidates"]}
    assert by_id["classic_lof"]["risk_collapse_warning"] is True
    assert by_id["classic_lof"]["recommendation"] == "weak_or_collapsed"
    assert by_id["keyboard_typeformer"]["available_count"] == 0
    assert by_id["keyboard_typeformer"]["recommendation"] == "unavailable_missing_artifact"
    assert "keyboard_typeformer" in by_id


def test_p2c_fusion_retraining_trains_or_skips_with_clear_status(tmp_path: Path) -> None:
    diagnostics = build_fusion_retraining_diagnostics(_records_for_ranking(), tmp_path)
    assert diagnostics["schema_version"] == P2C_FUSION_RETRAINING_SCHEMA_VERSION
    assert diagnostics["report_only"] is True
    assert diagnostics["production_selection_performed"] is False
    for candidate_id in LEARNED_FUSION_CANDIDATE_IDS:
        entry = diagnostics["candidate_artifacts"][candidate_id]
        assert entry["status"] in {"trained", "skipped"}
        assert entry["reason"]
        assert entry["can_lock_alone"] is False
        if entry["status"] == "trained":
            assert (tmp_path / entry["artifact_path"]).exists()
            assert entry["artifact_schema"].startswith("bioauth-diagnostic-fusion-artifact")


def test_p2c_fusion_retraining_insufficient_intruders_skips(tmp_path: Path) -> None:
    records = _records_for_ranking()[:12]
    diagnostics = build_fusion_retraining_diagnostics(records, tmp_path)
    for entry in diagnostics["candidate_artifacts"].values():
        assert entry["status"] == "skipped"
        assert entry["reason"] == "insufficient_intruder_samples"
        assert entry["artifact_path"] is None


def test_p2c_resolver_maps_diagnostic_fusion_artifacts_when_manifest_exists(tmp_path: Path) -> None:
    diagnostics = build_fusion_retraining_diagnostics(_records_for_ranking(), tmp_path)
    trained = {cid: entry for cid, entry in diagnostics["candidate_artifacts"].items() if entry["status"] == "trained"}
    if not trained:
        return
    metadata = {
        "candidate_artifacts": trained,
        "candidate_artifact_manifest": {"candidates": trained},
        "artifacts": {"candidate_artifacts_manifest": "candidate_artifacts_manifest.json"},
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (tmp_path / "candidate_artifacts_manifest.json").write_text(json.dumps({"candidates": trained}), encoding="utf-8")
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=tmp_path, metadata_path=tmp_path / "metadata.json")
    for candidate_id, entry in trained.items():
        spec = resolver(candidate_id, None, {})
        assert spec["metadata"]["artifact_builder_status"] == "trained"
        assert spec["metadata"]["hybrid_direct_artifact_adapter"] == "p2c_diagnostic_fusion_stacking_pickle"
        assert spec["artifact"].metadata()["candidate_id"] == candidate_id
        assert Path(entry["artifact_path"]).name == FUSION_ARTIFACT_FILENAMES[candidate_id]
