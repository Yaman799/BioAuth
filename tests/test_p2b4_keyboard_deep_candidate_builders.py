from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from hybrid_candidates.adapters import evaluate_advanced_keyboard_candidate, evaluate_deep_sequence_candidate
from hybrid_candidates.artifact_resolver import build_candidate_bundle_artifact_resolver
from hybrid_candidates.offline_runner import run_offline_candidate_replay
from hybrid_candidates.registry import validate_candidate_result
from metadata_core.constants import KB_HEADER, MS_HEADER
from security import compact_chunks, write_encrypted
from training_core import candidate_artifact_builders as builders
from training_core.candidate_artifact_builders import (
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    KEYBOARD_DEEP_CANDIDATE_ARTIFACT_FILENAMES,
    KEYBOARD_DEEP_CANDIDATE_IDS,
    build_keyboard_deep_candidate_artifacts,
)


def _keyboard_samples(session_count: int = 2, windows_per_session: int = 12) -> tuple[list[dict[str, Any]], list[int], list[str], list[str]]:
    rng = np.random.default_rng(20260514)
    rows: list[dict[str, Any]] = []
    labels: list[int] = []
    sources: list[str] = []
    for session_idx in range(session_count):
        for window_idx in range(windows_per_session):
            rows.append(
                {
                    "sequence_window_index": float(window_idx),
                    "window_start_offset": float(window_idx),
                    "key_hold_mean": float(abs(rng.normal(loc=0.18 + 0.01 * session_idx, scale=0.03))),
                    "key_hold_std": float(abs(rng.normal(loc=0.03, scale=0.005))),
                    "flight_mean": float(abs(rng.normal(loc=0.13, scale=0.02))),
                    "flight_std": float(abs(rng.normal(loc=0.025, scale=0.006))),
                    "keys_per_second": float(abs(rng.normal(loc=4.0, scale=0.25))),
                    "backspace_rate": float(abs(rng.normal(loc=0.05, scale=0.008))),
                    "typing_burst_rate": float(abs(rng.normal(loc=1.2, scale=0.15))),
                    "digraph_latency_mean": float(abs(rng.normal(loc=0.2, scale=0.03))),
                    # Raw-text-like fields intentionally present in source samples;
                    # the builder must not persist these names or values.
                    "raw_text": "NEVER_STORE_THIS_SECRET_TEXT",
                    "typed_text": "owner password phrase should not persist",
                    "key": "A",
                }
            )
            labels.append(0)
            sources.append(f"owner-{session_idx}")
    feature_names = [
        "key_hold_mean",
        "key_hold_std",
        "flight_mean",
        "flight_std",
        "keys_per_second",
        "backspace_rate",
        "typing_burst_rate",
        "digraph_latency_mean",
        "raw_text",
        "typed_text",
        "key",
    ]
    return rows, labels, sources, feature_names


def _metadata_for_bundle(bundle_dir: Path, build: dict[str, object], feature_names: list[str]) -> Path:
    path = bundle_dir / "metadata.json"
    path.write_text(
        json.dumps(
            {
                "feature_names": feature_names,
                "feature_schema_version": "test-keyboard-feature-schema-v1",
                "candidate_artifact_manifest": build["manifest"],
                "candidate_artifacts": build["candidate_artifacts"],
                "artifacts": {"candidate_artifacts_manifest": build["manifest_path"]},
                "report_only": True,
                "can_lock_alone": False,
                "can_influence_device": False,
                "runtime_authoritative": False,
                "trigger_face_confirmation": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _contains_forbidden_text(value: Any) -> bool:
    if isinstance(value, str):
        lower = value.lower()
        return "never_store_this_secret_text" in lower or "owner password phrase" in lower or lower in {"raw_text", "typed_text", "key"}
    if isinstance(value, dict):
        return any(_contains_forbidden_text(k) or _contains_forbidden_text(v) for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_forbidden_text(item) for item in value)
    return False


def _write_session(root: Path, name: str, *, row_count: int = 60) -> Path:
    session = root / name
    session.mkdir(parents=True, exist_ok=True)
    (session / "metadata.json").write_text(
        json.dumps(
            {
                "session_id": name,
                "archive_label": "legit",
                "final_decision": "legit",
                "bucket": "authorized",
                "training_eligible": True,
                "keyboard_rows": row_count,
                "mouse_rows": row_count,
                "created_at": "2026-05-11 20:00:00",
            }
        ),
        encoding="utf-8",
    )
    keyboard_rows = [[chr(97 + (idx % 5)), "press" if idx % 2 == 0 else "release", round(idx * 0.12, 3)] for idx in range(row_count)]
    mouse_rows = [[idx % 200, (idx * 3) % 180, "move", round(idx * 0.12, 3)] for idx in range(row_count)]
    keyboard_path = session / "keyboard_log.csv"
    mouse_path = session / "mouse_log.csv"
    write_encrypted(str(keyboard_path), keyboard_rows, KB_HEADER)
    compact_chunks(str(keyboard_path), KB_HEADER)
    write_encrypted(str(mouse_path), mouse_rows, MS_HEADER)
    compact_chunks(str(mouse_path), MS_HEADER)
    return session


def _candidate_rows(path: str | Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_p2b4_keyboard_builders_create_privacy_safe_torch_artifacts(tmp_path: Path) -> None:
    samples, labels, sources, feature_names = _keyboard_samples()
    build = build_keyboard_deep_candidate_artifacts(
        model_dir=tmp_path,
        samples=samples,
        labels=labels,
        sample_sources=sources,
        feature_names=feature_names,
        feature_schema_version="test-keyboard-feature-schema-v1",
        sequence_length=8,
        max_epochs=1,
    )

    assert set(build["candidate_artifacts"]) == set(KEYBOARD_DEEP_CANDIDATE_IDS)
    assert build["status_counts"]["trained"] == len(KEYBOARD_DEEP_CANDIDATE_IDS)
    assert build["manifest"]["privacy"]["stores_raw_text"] is False
    assert not _contains_forbidden_text(build["manifest"])
    for candidate_id, entry in build["candidate_artifacts"].items():
        assert entry["status"] == "trained"
        assert entry["artifact_schema"] == CANDIDATE_ARTIFACT_SCHEMA_VERSION
        assert entry["reason"] == "ok"
        assert entry["artifact_path"] == KEYBOARD_DEEP_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]
        assert (tmp_path / str(entry["artifact_path"])).is_file()
        assert entry["artifact_serialization"] == "torch_state_dict"
        assert entry["privacy"]["stores_raw_text"] is False
        assert "raw_text" not in entry["feature_names"]
        assert "typed_text" not in entry["feature_names"]
        assert "key" not in entry["feature_names"]
        assert not _contains_forbidden_text(entry)
        assert entry["can_lock_alone"] is False
        assert entry["can_influence_device"] is False
        assert entry["runtime_authoritative"] is False
        assert entry["trigger_face_confirmation"] is False


def test_p2b4_dependency_missing_writes_skipped_rows_without_artifacts(tmp_path: Path, monkeypatch) -> None:
    samples, labels, sources, feature_names = _keyboard_samples()
    monkeypatch.setattr(builders, "_dependency_available", lambda module_name: False if module_name == "torch" else True)
    build = build_keyboard_deep_candidate_artifacts(
        model_dir=tmp_path,
        samples=samples,
        labels=labels,
        sample_sources=sources,
        feature_names=feature_names,
        sequence_length=8,
    )

    assert build["status_counts"]["trained"] == 0
    assert build["status_counts"]["skipped"] == len(KEYBOARD_DEEP_CANDIDATE_IDS)
    for candidate_id, entry in build["candidate_artifacts"].items():
        assert entry["status"] == "skipped"
        assert entry["reason"] == "dependency_missing"
        assert entry["artifact_path"] is None
        assert not (tmp_path / KEYBOARD_DEEP_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]).exists()
        assert entry["can_lock_alone"] is False


def test_p2b4_insufficient_keyboard_data_records_precise_skipped_reasons(tmp_path: Path) -> None:
    samples, labels, sources, feature_names = _keyboard_samples(session_count=1, windows_per_session=3)
    build = build_keyboard_deep_candidate_artifacts(
        model_dir=tmp_path,
        samples=samples,
        labels=labels,
        sample_sources=sources,
        feature_names=feature_names,
        sequence_length=8,
    )

    assert build["status_counts"]["trained"] == 0
    for candidate_id, entry in build["candidate_artifacts"].items():
        assert entry["status"] == "skipped"
        assert entry["reason"] in {"insufficient_keyboard_windows", "insufficient_free_text_data", "missing_reference_template"}
        assert entry["artifact_path"] is None
        assert entry["can_lock_alone"] is False


def test_p2b4_resolver_maps_keyboard_artifacts_and_adapters_score(tmp_path: Path) -> None:
    samples, labels, sources, feature_names = _keyboard_samples()
    build = build_keyboard_deep_candidate_artifacts(
        model_dir=tmp_path,
        samples=samples,
        labels=labels,
        sample_sources=sources,
        feature_names=feature_names,
        sequence_length=8,
        max_epochs=1,
    )
    metadata_path = _metadata_for_bundle(tmp_path, build, feature_names)
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=tmp_path, metadata_path=metadata_path)

    for candidate_id in KEYBOARD_DEEP_CANDIDATE_IDS:
        spec = resolver(candidate_id, None, {})
        assert Path(spec["artifact_path"]).name == KEYBOARD_DEEP_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]
        assert spec["metadata"]["artifact_builder_status"] == "trained"
        assert spec["metadata"]["artifact_builder_reason"] == "ok"
        assert spec["metadata"]["can_lock_alone"] is False
        feature_count = len(spec["metadata"]["feature_names"])
        sequence_length = int(spec["metadata"]["sequence_length"])
        sequence = np.asarray([[[0.1 + 0.01 * idx for idx in range(feature_count)] for _ in range(sequence_length)]], dtype=float)
        if candidate_id == "keyboard_bigru_cnn_attention":
            result = evaluate_deep_sequence_candidate(candidate_id, sequence, **spec)
        else:
            result = evaluate_advanced_keyboard_candidate(candidate_id, sequence, **spec)
        assert validate_candidate_result(result)["ok"] is True
        assert result["available"] is True
        assert result["reason"] != "missing_trained_artifact"
        assert result["trained_artifact_loaded"] is True
        assert result["can_lock_alone"] is False
        assert result["can_vote"] is False


def test_p2b4_advanced_adapter_rejects_incomplete_schema_precisely(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.keyboard_advanced.optional_dependency_available", lambda name: True)
    result = evaluate_advanced_keyboard_candidate(
        "keyboard_type2branch",
        np.zeros((1, 4, 2), dtype=float),
        artifact={"state_dict": {"nonempty": 1}, "threshold": 0.5, "training_metadata": {"ok": True}, "reference_embedding": [0.0]},
        metadata={"artifact_id": "fixture"},
    )
    assert validate_candidate_result(result)["ok"] is True
    assert result["available"] is False
    assert result["reason"] == "missing_artifact_schema"
    assert result["can_lock_alone"] is False


def test_p2b4_hybrid_direct_run_uses_valid_keyboard_artifacts(tmp_path: Path, monkeypatch) -> None:
    samples, labels, sources, feature_names = _keyboard_samples()
    bundle_dir = tmp_path / "candidate_bundle"
    build = build_keyboard_deep_candidate_artifacts(
        model_dir=bundle_dir,
        samples=samples,
        labels=labels,
        sample_sources=sources,
        feature_names=feature_names,
        sequence_length=8,
        max_epochs=1,
    )
    metadata_path = _metadata_for_bundle(bundle_dir, build, feature_names)
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=bundle_dir, metadata_path=metadata_path)
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root / "authorized", "owner-session")
    owner_samples = [dict(sample) for sample in samples[:14]]

    monkeypatch.setattr("hybrid_candidates.offline_runner._extract_training_window_features", lambda session: (owner_samples, []))
    monkeypatch.setattr("hybrid_candidates.offline_runner._extract_raw_window_features_for_sequence", lambda session: (owner_samples, []))

    summary = run_offline_candidate_replay(
        selected_candidates=list(KEYBOARD_DEEP_CANDIDATE_IDS),
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        artifact_resolver=resolver,
        max_sessions=1,
    )
    rows = _candidate_rows(summary["report_paths"]["candidate_results"])
    by_id = {str(row["candidate_id"]): row for row in rows}

    assert set(by_id) == set(KEYBOARD_DEEP_CANDIDATE_IDS)
    assert summary["training_performed"] is False
    assert summary["can_lock_alone"] is False
    for candidate_id, row in by_id.items():
        assert row["available"] is True
        assert row["reason"] in {"p2b4_keyboard_bigru_torch_state_dict", "p2b4_keyboard_deep_torch_state_dict"}
        assert row["trained_artifact_loaded"] is True
        assert row["can_vote"] is False
        assert row["can_lock_alone"] is False
        assert row["can_influence_device"] is False
        assert row["runtime_authoritative"] is False
        assert row["trigger_face_confirmation"] is False
