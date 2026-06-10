from __future__ import annotations

from pathlib import Path

import importlib

import pytest

import model_runtime.bundles as bundles
import metadata_core.paths as runtime_paths


class _DummyModel:
    pass


def _candidate_paths(tmp_path: Path) -> dict[str, str]:
    base = tmp_path / "models" / "user_alice" / "candidate_bundle"
    base.mkdir(parents=True)
    paths = {
        "base": str(base),
        "model": str(base / "model.pkl"),
        "classifier": str(base / "classifier.pkl"),
        "metadata": str(base / "metadata.json"),
        "sequence_model": str(base / "sequence_model.pt"),
        "evaluation_report": str(base / "evaluation_report.json"),
        "evaluation_summary": str(base / "evaluation_summary.md"),
    }
    Path(paths["model"]).write_bytes(b"model")
    Path(paths["metadata"]).write_text("{}", encoding="utf-8")
    return paths


def _shadow_meta(**overrides):
    meta = {
        "bundle_role": "candidate",
        "model_status": "approved_for_shadow",
        "candidate_status": "approved_for_shadow",
        "feature_schema_version": bundles.runtime_feature_schema_mismatch_reason.__globals__["FEATURE_SCHEMA_VERSION"],
        "feature_window_strategy": bundles.runtime_feature_schema_mismatch_reason.__globals__["FEATURE_WINDOW_STRATEGY"],
        "active_window_scales": list(bundles.runtime_feature_schema_mismatch_reason.__globals__["ACTIVE_WINDOW_SCALES"]),
    }
    meta.update(overrides)
    return meta


def _enable_dev_fallback_env(monkeypatch):
    monkeypatch.setenv("BIOAUTH_DEV_PRODUCTION_READY_SIMULATION", "1")
    monkeypatch.setenv("BIOAUTH_ALLOW_SHADOW_CANDIDATE_RUNTIME_FALLBACK", "1")
    monkeypatch.setenv("BIOAUTH_RUNTIME_BUNDLE_SOURCE", "developer_shadow_candidate")


def _patch_candidate_paths(monkeypatch, paths: dict[str, str]) -> None:
    # Some older readiness tests reload metadata_core.paths during collection.
    # Patch both this module's imported object and the currently registered
    # module so model_runtime.bundles' import-inside-function sees the same
    # candidate bundle paths.
    current_paths = importlib.import_module("metadata_core.paths")
    monkeypatch.setattr(runtime_paths, "_user_model_paths", lambda _user: paths)
    monkeypatch.setattr(current_paths, "_user_model_paths", lambda _user: paths)


def test_runtime_load_uses_shadow_candidate_fallback_when_dev_simulation_active(monkeypatch, tmp_path):
    paths = _candidate_paths(tmp_path)
    _enable_dev_fallback_env(monkeypatch)
    monkeypatch.setattr(bundles, "resolve_active_runtime_paths_with_validation", lambda _user: (None, {"ok": False, "reason": "runtime_pointer_missing"}))
    _patch_candidate_paths(monkeypatch, paths)
    monkeypatch.setattr(bundles, "load_metadata", lambda _path: _shadow_meta())
    monkeypatch.setattr(bundles, "load_model", lambda _path: _DummyModel())
    monkeypatch.setattr(bundles, "load_classifier", lambda _path: None)

    bundle = bundles._load_user_runtime_bundle("alice")

    assert isinstance(bundle, dict)
    assert isinstance(bundle["model"], _DummyModel)
    assert bundle["dev_runtime_bundle_fallback"] is True
    assert bundle["runtime_bundle_source"] == "developer_shadow_candidate"
    assert bundle["metadata"]["model_status"] == "approved_for_shadow"
    assert bundle["metadata"]["production_ready_effective"] is True


def test_runtime_pointer_missing_still_blocks_when_dev_fallback_env_disabled(monkeypatch, tmp_path):
    paths = _candidate_paths(tmp_path)
    monkeypatch.delenv("BIOAUTH_DEV_PRODUCTION_READY_SIMULATION", raising=False)
    monkeypatch.delenv("BIOAUTH_ALLOW_SHADOW_CANDIDATE_RUNTIME_FALLBACK", raising=False)
    monkeypatch.delenv("BIOAUTH_RUNTIME_BUNDLE_SOURCE", raising=False)
    monkeypatch.setattr(bundles, "resolve_active_runtime_paths_with_validation", lambda _user: (None, {"ok": False, "reason": "runtime_pointer_missing"}))
    _patch_candidate_paths(monkeypatch, paths)

    assert bundles._load_user_runtime_bundle("alice") is None


def test_runtime_fallback_rejects_non_shadow_approved_candidate(monkeypatch, tmp_path):
    paths = _candidate_paths(tmp_path)
    _enable_dev_fallback_env(monkeypatch)
    monkeypatch.setattr(bundles, "resolve_active_runtime_paths_with_validation", lambda _user: (None, {"ok": False, "reason": "runtime_pointer_missing"}))
    _patch_candidate_paths(monkeypatch, paths)
    monkeypatch.setattr(bundles, "load_metadata", lambda _path: _shadow_meta(model_status="training_complete", candidate_status="training_complete"))

    assert bundles._load_user_runtime_bundle("alice") is None


def test_real_production_pointer_resolution_is_unchanged(monkeypatch, tmp_path):
    base = tmp_path / "models" / "user_alice" / "production_bundle"
    base.mkdir(parents=True)
    production_paths = {
        "base": str(base),
        "model": str(base / "model.pkl"),
        "classifier": str(base / "classifier.pkl"),
        "metadata": str(base / "metadata.json"),
    }
    Path(production_paths["model"]).write_bytes(b"model")
    Path(production_paths["metadata"]).write_text("{}", encoding="utf-8")
    production_meta = _shadow_meta(bundle_role="production", model_status="approved_for_production", candidate_status="approved_for_production")
    monkeypatch.setattr(
        bundles,
        "resolve_active_runtime_paths_with_validation",
        lambda _user: (production_paths, {"ok": True, "reason": "ok", "metadata": production_meta}),
    )
    monkeypatch.setattr(bundles, "load_model", lambda _path: _DummyModel())
    monkeypatch.setattr(bundles, "load_classifier", lambda _path: None)

    bundle = bundles._load_user_runtime_bundle("alice")

    assert isinstance(bundle, dict)
    assert isinstance(bundle["model"], _DummyModel)
    assert "dev_runtime_bundle_fallback" not in bundle
    assert bundle["metadata"]["bundle_role"] == "production"


def test_session_process_env_adds_dev_runtime_fallback_markers_only_when_simulation_active():
    source = Path("bridge/session_mixin.py").read_text(encoding="utf-8")
    assert "_developer_production_ready_simulation_active" in source
    assert "BIOAUTH_DEV_PRODUCTION_READY_SIMULATION" in source
    assert "BIOAUTH_ALLOW_SHADOW_CANDIDATE_RUNTIME_FALLBACK" in source
    assert "BIOAUTH_RUNTIME_BUNDLE_SOURCE" in source
    assert "developer_shadow_candidate" in source
    assert "_pending_passive_auto_enrollment" in source


def test_static_safety_no_production_pointer_write_for_dev_fallback():
    source = Path("model_runtime/bundles.py").read_text(encoding="utf-8")
    fallback_block = source[
        source.index("def _validate_shadow_candidate_runtime_bundle") : source.index("def _resolve_context_bundle_path")
    ]
    assert "write_active_runtime_pointer" not in fallback_block
    assert "approved_for_production" not in fallback_block
    assert 'production_ready"] = True' not in source
    assert "production_ready'] = True" not in source
