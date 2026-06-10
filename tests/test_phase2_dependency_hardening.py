from __future__ import annotations

import importlib
import re
from pathlib import Path

import numpy as np

from hybrid_candidates.adapters.base import candidate_unavailable
from hybrid_candidates.adapters.supervised import evaluate_xgboost
from hybrid_candidates.registry import validate_candidate_result
from training_core import candidate_artifact_builders as builders
from training_core.candidate_artifact_builders import build_optional_supervised_candidate_artifacts
from utils.dependency_probe import (
    DEPENDENCY_MISSING,
    candidate_dependency_status,
    normalize_unavailable_reason_category,
    probe_dependency,
)


def test_dependency_probe_reports_missing_without_raising() -> None:
    status = probe_dependency("bioauth_definitely_missing_optional_package_20260518", require_import=True)

    assert status.available is False
    assert status.reason == DEPENDENCY_MISSING
    payload = status.to_dict()
    assert payload["module_name"] == "bioauth_definitely_missing_optional_package_20260518"
    assert payload["import_checked"] is False


def test_candidate_unavailable_adds_structured_dependency_metadata() -> None:
    result = candidate_unavailable("supervised_xgboost", "dependency_missing")

    assert validate_candidate_result(result)["ok"] is True
    assert result["available"] is False
    assert result["reason"] == "dependency_missing"
    assert result["dependency_missing"] is True
    assert result["unavailable_reason_category"] == "dependency_missing"
    assert result["structured_reason"] == {"reason": "dependency_missing", "category": "dependency_missing"}
    assert result["can_lock_alone"] is False
    assert result["can_vote"] is False


def test_reason_category_normalization_for_expected_candidate_failures() -> None:
    assert normalize_unavailable_reason_category("dependency_import_failed") == "dependency_missing"
    assert normalize_unavailable_reason_category("insufficient_sequence_windows") == "insufficient_data"
    assert normalize_unavailable_reason_category("missing_trained_artifact") == "missing_artifact"
    assert normalize_unavailable_reason_category("missing_artifact_schema") == "missing_artifact_schema"
    assert normalize_unavailable_reason_category("unsupported_environment:python") == "unsupported_environment"


def test_optional_supervised_import_failure_becomes_skipped_dependency_missing(monkeypatch, tmp_path: Path) -> None:
    real_import_module = importlib.import_module

    def fake_import_module(name: str, *args, **kwargs):
        if name == "xgboost":
            raise RuntimeError("simulated broken optional xgboost install")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(builders.importlib, "import_module", fake_import_module)
    x_owner = np.random.default_rng(42).normal(size=(12, 4))
    x_intruder = np.random.default_rng(43).normal(loc=2.0, size=(3, 4))

    build = build_optional_supervised_candidate_artifacts(
        model_dir=tmp_path,
        X_pos=x_owner,
        X_neg=x_intruder,
        feature_names=["a", "b", "c", "d"],
        dependency_resolver=lambda candidate_id: builders.resolve_optional_supervised_dependency(candidate_id)
        if candidate_id == "supervised_xgboost"
        else builders.OptionalSupervisedDependencySpec(
            candidate_id=candidate_id,
            dependency_name=candidate_id.replace("supervised_", ""),
            model_family=candidate_id.replace("supervised_", ""),
            estimator_class=None,
            dependency_version=None,
            available=False,
            dependency_status="dependency_missing",
        ),
    )

    row = build["candidate_artifacts"]["supervised_xgboost"]
    assert row["status"] == "skipped"
    assert row["reason"] == "dependency_missing"
    assert row["dependency_available"] is False
    assert row["dependency_status"] in {"dependency_missing", "dependency_import_failed"}
    assert row["artifact_path"] is None
    assert row["can_lock_alone"] is False


def test_adapter_with_missing_optional_supervised_dependency_reports_metadata(monkeypatch) -> None:
    monkeypatch.setattr("hybrid_candidates.adapters.supervised.optional_dependency_available", lambda name: False)

    result = evaluate_xgboost({"a": 1.0}, metadata={"feature_names": ["a"]})

    assert validate_candidate_result(result)["ok"] is True
    assert result["available"] is False
    assert result["reason"] == "dependency_missing"
    assert result["dependency_missing"] is True
    assert result["unavailable_reason_category"] == "dependency_missing"
    assert result["can_lock_alone"] is False
    assert result["can_vote"] is False


def test_desktop_import_surface_does_not_directly_import_optional_candidate_libraries() -> None:
    checked = [Path("desktop_app.py"), Path("app_settings.py"), Path("deep_runtime.py")]
    pattern = re.compile(r"^\s*(?:import|from)\s+(torch|xgboost|lightgbm|catboost)\b", re.MULTILINE)

    for path in checked:
        assert not pattern.search(path.read_text(encoding="utf-8")), f"{path} imports optional candidate dependency at module import time"


def test_candidate_dependency_status_is_structured_for_deep_candidates() -> None:
    payload = candidate_dependency_status("keyboard_bigru_cnn_attention")

    assert payload["candidate_id"] == "keyboard_bigru_cnn_attention"
    assert payload["dependencies"]
    assert payload["dependencies"][0]["module_name"] == "torch"
    assert payload["reason"] in {"ok", "dependency_missing"}
