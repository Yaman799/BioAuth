from __future__ import annotations

import os
from pathlib import Path

import pytest

from artifact_integrity import save_sequence_model_artifact
from deep_sequence import inference


class TrackingSequenceModel:
    instances: list["TrackingSequenceModel"] = []
    load_state_dict_calls = 0

    def __init__(self, *, feature_dim: int) -> None:
        self.feature_dim = int(feature_dim)
        self.marker = "unset"
        self.eval_calls = 0
        type(self).instances.append(self)

    def load_state_dict(self, state_dict):
        type(self).load_state_dict_calls += 1
        self.marker = str((state_dict or {}).get("marker") or "unset")
        return None

    def eval(self):
        self.eval_calls += 1
        return self

    def __call__(self, _tensor):
        import torch

        logits = {
            "low": -2.0,
            "high": 2.0,
            "old": -1.0,
            "new": 1.0,
        }
        return torch.tensor([float(logits.get(self.marker, 0.0))])


@pytest.fixture(autouse=True)
def clear_sequence_caches():
    inference._cached_sequence_payload.cache_clear()
    inference._cached_loaded_runtime_model.cache_clear()
    TrackingSequenceModel.instances.clear()
    TrackingSequenceModel.load_state_dict_calls = 0
    yield
    inference._cached_sequence_payload.cache_clear()
    inference._cached_loaded_runtime_model.cache_clear()
    TrackingSequenceModel.instances.clear()
    TrackingSequenceModel.load_state_dict_calls = 0


def _write_artifact(path: Path, *, marker: str, feature_dim: int = 2, sequence_length: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    save_sequence_model_artifact(
        str(path),
        {
            "model_family": "cnn_lstm",
            "state_dict": {"marker": marker},
            "model_config": {"feature_dim": feature_dim, "sequence_length": sequence_length},
            "feature_names": [f"f{i}" for i in range(1, feature_dim + 1)],
        },
    )


def _meta_for(artifact_path: Path) -> dict:
    return {
        "deep_runtime": {
            "deep_sequence_runtime_enabled": True,
            "runtime_shadow_only": True,
            "sequence_model": {"enabled": True, "artifact": str(artifact_path)},
        }
    }


def _runtime_state() -> dict:
    return {"desired_mode": "hybrid", "effective_mode": "shadow"}


def _window_samples() -> list[dict]:
    return [
        {"sequence_window_index": 0, "window_start_offset": 0.0, "f1": 1.0, "f2": 2.0},
        {"sequence_window_index": 1, "window_start_offset": 1.0, "f1": 3.0, "f2": 4.0},
    ]


def test_repeated_predictions_for_same_artifact_do_not_reload_state_dict(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(inference, "SequenceCnnLstm", TrackingSequenceModel)
    artifact = tmp_path / "runtime" / "sequence_model.pt"
    _write_artifact(artifact, marker="high")
    metadata_file = tmp_path / "runtime" / "metadata.json"

    first = inference.run_shadow_sequence_scoring(
        window_samples=_window_samples(), metadata_file=str(metadata_file), meta=_meta_for(artifact), runtime_state=_runtime_state()
    )
    second = inference.run_shadow_sequence_scoring(
        window_samples=_window_samples(), metadata_file=str(metadata_file), meta=_meta_for(artifact), runtime_state=_runtime_state()
    )

    assert first["used"] is True
    assert second["used"] is True
    assert TrackingSequenceModel.load_state_dict_calls == 1
    assert len(TrackingSequenceModel.instances) == 1
    assert TrackingSequenceModel.instances[0].eval_calls == 1


def test_artifacts_with_same_feature_dim_keep_separate_loaded_model_instances(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(inference, "SequenceCnnLstm", TrackingSequenceModel)
    artifact_low = tmp_path / "low" / "sequence_model.pt"
    artifact_high = tmp_path / "high" / "sequence_model.pt"
    _write_artifact(artifact_low, marker="low", feature_dim=2)
    _write_artifact(artifact_high, marker="high", feature_dim=2)

    low = inference.run_shadow_sequence_scoring(
        window_samples=_window_samples(), metadata_file=str(artifact_low.parent / "metadata.json"), meta=_meta_for(artifact_low), runtime_state=_runtime_state()
    )
    high = inference.run_shadow_sequence_scoring(
        window_samples=_window_samples(), metadata_file=str(artifact_high.parent / "metadata.json"), meta=_meta_for(artifact_high), runtime_state=_runtime_state()
    )

    assert low["used"] is True
    assert high["used"] is True
    assert low["probability"] != high["probability"]
    assert TrackingSequenceModel.load_state_dict_calls == 2
    assert len(TrackingSequenceModel.instances) == 2
    assert TrackingSequenceModel.instances[0] is not TrackingSequenceModel.instances[1]
    assert {model.marker for model in TrackingSequenceModel.instances} == {"low", "high"}


def test_artifact_identity_change_triggers_reload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(inference, "SequenceCnnLstm", TrackingSequenceModel)
    artifact = tmp_path / "runtime" / "sequence_model.pt"
    metadata_file = tmp_path / "runtime" / "metadata.json"
    _write_artifact(artifact, marker="old")

    old = inference.run_shadow_sequence_scoring(
        window_samples=_window_samples(), metadata_file=str(metadata_file), meta=_meta_for(artifact), runtime_state=_runtime_state()
    )
    old_mtime_ns = os.stat(artifact).st_mtime_ns

    _write_artifact(artifact, marker="new")
    new_mtime_ns = old_mtime_ns + 1_000_000_000
    os.utime(artifact, ns=(new_mtime_ns, new_mtime_ns))

    new = inference.run_shadow_sequence_scoring(
        window_samples=_window_samples(), metadata_file=str(metadata_file), meta=_meta_for(artifact), runtime_state=_runtime_state()
    )

    assert old["used"] is True
    assert new["used"] is True
    assert old["probability"] != new["probability"]
    assert TrackingSequenceModel.load_state_dict_calls == 2
    assert len(TrackingSequenceModel.instances) == 2
    assert [model.marker for model in TrackingSequenceModel.instances] == ["old", "new"]


def test_load_runtime_sequence_model_keeps_backward_compatible_payload_fields(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(inference, "SequenceCnnLstm", TrackingSequenceModel)
    artifact = tmp_path / "runtime" / "sequence_model.pt"
    _write_artifact(artifact, marker="high")

    first = inference.load_runtime_sequence_model(
        metadata_file=str(artifact.parent / "metadata.json"), meta=_meta_for(artifact), runtime_state=_runtime_state()
    )
    second = inference.load_runtime_sequence_model(
        metadata_file=str(artifact.parent / "metadata.json"), meta=_meta_for(artifact), runtime_state=_runtime_state()
    )

    assert first["available"] is True
    assert first["loaded"] is True
    assert first["backend"] == "pytorch_cpu"
    assert first["reason"] == "ok"
    assert first["payload"]["model_config"]["feature_dim"] == 2
    assert first["artifact_file"] == "sequence_model.pt"
    assert second["model"] is first["model"]
    assert TrackingSequenceModel.load_state_dict_calls == 1
