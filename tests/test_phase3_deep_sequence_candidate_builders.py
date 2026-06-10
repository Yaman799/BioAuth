from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from hybrid_candidates.adapters.deep_sequence import evaluate_deep_sequence_candidate
from hybrid_candidates.artifact_resolver import build_candidate_bundle_artifact_resolver
from hybrid_candidates.registry import validate_candidate_result
from training_core import candidate_artifact_builders as builders
from training_core.candidate_artifact_builders import (
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    DEEP_SEQUENCE_CANDIDATE_ARTIFACT_FILENAMES,
    DEEP_SEQUENCE_CANDIDATE_IDS,
    build_deep_sequence_candidate_artifacts,
)


def _torch_available() -> bool:
    return importlib.util.find_spec("torch") is not None


def _phase3_samples(*, include_intruder: bool = True, windows_per_session: int = 8) -> tuple[list[dict[str, float | str]], list[int], list[str], list[str]]:
    rng = np.random.default_rng(20260518)
    rows: list[dict[str, float | str]] = []
    labels: list[int] = []
    sources: list[str] = []
    session_specs = [("owner-a", 0, 0.0), ("owner-b", 0, 0.2)]
    if include_intruder:
        session_specs.extend([("intruder-a", 1, 2.0), ("intruder-b", 1, 2.2)])
    for source, label, offset in session_specs:
        for window_idx in range(windows_per_session):
            rows.append(
                {
                    "sequence_window_index": float(window_idx),
                    "window_start_offset": float(window_idx),
                    "dx": float(rng.normal(loc=offset + 0.1, scale=0.25)),
                    "dy": float(rng.normal(loc=-offset - 0.1, scale=0.25)),
                    "distance": float(abs(rng.normal(loc=1.0 + offset, scale=0.15))),
                    "velocity": float(abs(rng.normal(loc=0.8 + offset, scale=0.15))),
                    "acceleration": float(rng.normal(loc=offset * 0.2, scale=0.1)),
                    "angle_change": float(rng.normal(loc=offset * 0.1, scale=0.1)),
                    "click_state": float((window_idx + label) % 2),
                    "scroll_delta": float((window_idx % 3) - 1),
                    "drag_state": float(window_idx % 4 == 0),
                    "key_hold_mean": float(abs(rng.normal(loc=0.18 + (label * 0.2), scale=0.03))),
                    "key_hold_std": float(abs(rng.normal(loc=0.03 + (label * 0.01), scale=0.01))),
                    "flight_mean": float(abs(rng.normal(loc=0.12 + (label * 0.15), scale=0.03))),
                    "flight_std": float(abs(rng.normal(loc=0.02 + (label * 0.01), scale=0.01))),
                    "keys_per_second": float(abs(rng.normal(loc=4.0 - (label * 1.0), scale=0.25))),
                    "backspace_rate": float(abs(rng.normal(loc=0.05 + (label * 0.05), scale=0.01))),
                    "typing_burst_rate": float(abs(rng.normal(loc=1.2 - (label * 0.3), scale=0.1))),
                    "digraph_latency_mean": float(abs(rng.normal(loc=0.2 + (label * 0.2), scale=0.03))),
                    "raw_text": "never-store-this",
                    "key": "A",
                    "password": "not-a-feature",
                }
            )
            labels.append(label)
            sources.append(source)
    feature_names = [name for name in rows[0].keys() if name not in {"sequence_window_index", "window_start_offset"}]
    return rows, labels, sources, feature_names


def _metadata_for_bundle(bundle_dir: Path, build: dict[str, object], feature_names: list[str]) -> Path:
    path = bundle_dir / "metadata.json"
    path.write_text(
        json.dumps(
            {
                "feature_names": feature_names,
                "feature_schema_version": "phase3-test-feature-schema-v1",
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


@pytest.mark.skipif(not _torch_available(), reason="torch optional dependency is not installed")
def test_phase3_deep_sequence_builders_create_native_artifacts(tmp_path: Path) -> None:
    samples, labels, sources, feature_names = _phase3_samples()
    build = build_deep_sequence_candidate_artifacts(
        model_dir=tmp_path,
        samples=samples,
        labels=labels,
        sample_sources=sources,
        feature_names=feature_names,
        feature_schema_version="phase3-test-feature-schema-v1",
        sequence_length=4,
        max_epochs=1,
    )

    assert set(build["candidate_artifacts"]) == set(DEEP_SEQUENCE_CANDIDATE_IDS)
    assert build["status_counts"]["trained"] == len(DEEP_SEQUENCE_CANDIDATE_IDS)
    forbidden = {"raw_text", "typed_text", "plaintext", "key", "password"}
    for candidate_id, entry in build["candidate_artifacts"].items():
        assert entry["status"] == "trained"
        assert entry["reason"] == "ok"
        assert entry["artifact_schema"] == CANDIDATE_ARTIFACT_SCHEMA_VERSION
        assert entry["artifact_path"] == DEEP_SEQUENCE_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]
        assert (tmp_path / str(entry["artifact_path"])).is_file()
        assert entry["artifact_serialization"] == "torch_state_dict"
        assert entry["created_at"].endswith("Z")
        assert entry["training_summary"]["loss_history"]
        assert entry["privacy"]["stores_raw_text"] is False
        assert forbidden.isdisjoint(set(entry["feature_names"]))
        assert entry["can_lock_alone"] is False
        assert entry["can_influence_device"] is False
        assert entry["runtime_authoritative"] is False
        assert entry["trigger_face_confirmation"] is False
    assert build["candidate_artifacts"]["combined_cnn_lstm"]["intruder_sequence_count"] > 0


def test_phase3_deep_sequence_dependency_missing_is_structured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    samples, labels, sources, feature_names = _phase3_samples()
    monkeypatch.setattr(builders, "_dependency_available", lambda module_name: False if module_name == "torch" else True)
    build = build_deep_sequence_candidate_artifacts(
        model_dir=tmp_path,
        samples=samples,
        labels=labels,
        sample_sources=sources,
        feature_names=feature_names,
        sequence_length=4,
    )

    assert build["status_counts"]["trained"] == 0
    assert build["status_counts"]["skipped"] == len(DEEP_SEQUENCE_CANDIDATE_IDS)
    for candidate_id, entry in build["candidate_artifacts"].items():
        assert entry["status"] == "skipped"
        assert entry["reason"] == "dependency_missing"
        assert entry["artifact_path"] is None
        assert not (tmp_path / DEEP_SEQUENCE_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]).exists()
        assert entry["can_lock_alone"] is False


@pytest.mark.skipif(not _torch_available(), reason="torch optional dependency is not installed")
def test_phase3_combined_cnn_lstm_requires_intruder_sequences(tmp_path: Path) -> None:
    samples, labels, sources, feature_names = _phase3_samples(include_intruder=False)
    build = build_deep_sequence_candidate_artifacts(
        model_dir=tmp_path,
        samples=samples,
        labels=labels,
        sample_sources=sources,
        feature_names=feature_names,
        sequence_length=4,
        max_epochs=1,
    )

    mouse = build["candidate_artifacts"]["mouse_resnet_gru"]
    combined = build["candidate_artifacts"]["combined_cnn_lstm"]
    assert mouse["status"] == "trained"
    assert combined["status"] == "skipped"
    assert combined["reason"] == "insufficient_combined_windows"
    assert combined["requires_trusted_intruder_sequences"] is True
    assert combined["artifact_path"] is None


@pytest.mark.skipif(not _torch_available(), reason="torch optional dependency is not installed")
def test_phase3_resolver_maps_native_deep_sequence_artifacts_and_adapters_score(tmp_path: Path) -> None:
    samples, labels, sources, feature_names = _phase3_samples()
    build = build_deep_sequence_candidate_artifacts(
        model_dir=tmp_path,
        samples=samples,
        labels=labels,
        sample_sources=sources,
        feature_names=feature_names,
        feature_schema_version="phase3-test-feature-schema-v1",
        sequence_length=4,
        max_epochs=1,
    )
    metadata_path = _metadata_for_bundle(tmp_path, build, feature_names)
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=tmp_path, metadata_path=metadata_path)

    for candidate_id in DEEP_SEQUENCE_CANDIDATE_IDS:
        spec = resolver(candidate_id, None, {})
        assert Path(spec["artifact_path"]).name == DEEP_SEQUENCE_CANDIDATE_ARTIFACT_FILENAMES[candidate_id]
        assert spec["metadata"]["artifact_builder_status"] == "trained"
        assert spec["metadata"]["artifact_builder_reason"] == "ok"
        assert spec["metadata"]["can_lock_alone"] is False
        feature_count = int(spec["metadata"]["feature_count"])
        sequence_length = int(spec["metadata"]["sequence_length"])
        sequence = np.asarray([[[0.15 + (0.01 * f_idx) + (0.02 * t_idx) for f_idx in range(feature_count)] for t_idx in range(sequence_length)]], dtype=float)
        result = evaluate_deep_sequence_candidate(candidate_id, sequence, **spec)
        assert validate_candidate_result(result)["ok"] is True
        assert result["available"] is True
        assert result["reason"] != "missing_trained_artifact"
        assert result["can_vote"] is False
        assert result["can_lock_alone"] is False
        assert result["can_influence_device"] is False
        assert result["runtime_authoritative"] is False
        assert result["trigger_face_confirmation"] is False
