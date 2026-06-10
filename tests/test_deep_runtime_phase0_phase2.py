from __future__ import annotations

import importlib
from pathlib import Path

import app_settings
import bio_platform.secrets as secret_backend
import paths
import security
from deep_runtime import (
    build_deep_runtime_metadata_contract,
    normalize_benchmark_record,
    resolve_deep_runtime_state,
    run_local_device_benchmark,
    supported_deep_runtime_modes,
)
from metadata_core.runtime import runtime_deep_contract_state


def _configure_settings_storage(tmp_path: Path, monkeypatch) -> Path:
    settings_path = tmp_path / "settings.json"
    model_dir = tmp_path / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(secret_backend, "keyring", None)
    monkeypatch.setattr(security, "MODELS_DIR", str(model_dir))
    monkeypatch.setattr(security, "KEY_FILE", str(model_dir / "secret.key"))
    monkeypatch.setattr(security, "KEY_FILE_DPAPI", str(model_dir / "secret.key.dpapi"))
    security.reset_security_caches()
    monkeypatch.setattr(app_settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_settings, "SETTINGS_FILE", str(settings_path))
    with app_settings._SETTINGS_LOCK:
        app_settings._SETTINGS_CACHE = None
    return settings_path


def test_coerce_settings_payload_backfills_deep_runtime_defaults() -> None:
    payload = app_settings._coerce_settings_payload({"deep_runtime_mode": "HYBRID ACCELERATED"})

    assert payload["deep_runtime_mode"] == "hybrid_accelerated"
    assert payload["deep_runtime_manual_override"] is False
    assert payload["deep_runtime_benchmark"]["status"] == "not_run"
    assert payload["deep_runtime_benchmark"]["recommended_mode"] == "classic"


def test_save_settings_persists_deep_runtime_benchmark(monkeypatch, tmp_path) -> None:
    _configure_settings_storage(tmp_path, monkeypatch)
    benchmark = run_local_device_benchmark(sequence_length=4, feature_dim=32, benchmark_passes=3)

    saved = app_settings.save_settings(
        {
            "deep_runtime_mode": "hybrid",
            "deep_runtime_manual_override": True,
            "deep_runtime_benchmark": benchmark,
        }
    )

    assert saved["deep_runtime_mode"] == "hybrid"
    assert saved["deep_runtime_manual_override"] is True
    assert saved["deep_runtime_benchmark"]["status"] == "ok"
    assert saved["deep_runtime_benchmark"]["recommended_mode"] in supported_deep_runtime_modes()


def test_run_local_device_benchmark_returns_recommendation_shape() -> None:
    result = run_local_device_benchmark(sequence_length=4, feature_dim=24, benchmark_passes=3)

    assert result["status"] == "ok"
    assert result["recommended_mode"] in supported_deep_runtime_modes()
    assert result["effective_mode"] == "classic"
    assert result["fallback_reason"] == "deep_runtime_not_available_yet"
    assert result["latency"]["p95_ms"] >= 0.0
    assert isinstance(result["backend_inventory"]["available_backends"], list)


def test_resolve_deep_runtime_state_falls_back_to_classic_until_deep_artifact_exists() -> None:
    benchmark = normalize_benchmark_record({"status": "ok", "recommended_mode": "hybrid", "recommended_backend": "classic"})
    state = resolve_deep_runtime_state(
        {
            "deep_runtime_mode": "hybrid",
            "deep_runtime_manual_override": True,
            "deep_runtime_benchmark": benchmark,
        },
        runtime_metadata={"deep_runtime": build_deep_runtime_metadata_contract()},
    )

    assert state["desired_mode"] == "hybrid"
    assert state["effective_mode"] == "classic"
    assert state["fallback_reason"] == "deep_runtime_not_available_yet"


def test_resolve_deep_runtime_state_supports_future_hybrid_path_when_contract_ready() -> None:
    contract = build_deep_runtime_metadata_contract()
    contract["deep_sequence_runtime_enabled"] = True
    contract["sequence_model"]["enabled"] = True
    contract["sequence_model"]["artifact"] = "sequence_model.onnx"
    benchmark = normalize_benchmark_record({"status": "ok", "recommended_mode": "hybrid", "recommended_backend": "classic"})

    state = resolve_deep_runtime_state(
        {
            "deep_runtime_mode": "auto",
            "deep_runtime_manual_override": False,
            "deep_runtime_benchmark": benchmark,
        },
        runtime_metadata={"deep_runtime": contract},
    )

    assert state["recommended_mode"] == "hybrid"
    assert state["effective_mode"] == "hybrid"
    assert state["fallback_reason"] == "ok"


def test_runtime_deep_contract_state_backfills_legacy_metadata() -> None:
    contract = runtime_deep_contract_state({"feature_schema_version": "sequence-multiscale-v1"})

    assert contract["contract_version"] == "deep-runtime-v1"
    assert contract["sequence_model"]["enabled"] is False
    assert contract["fallback_mode"] == "classic"


def test_deep_runtime_settings_survive_reload(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "settings.json"

    with monkeypatch.context() as scoped:
        model_dir = tmp_path / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        scoped.setattr(secret_backend, "keyring", None)
        scoped.setattr(security, "MODELS_DIR", str(model_dir))
        scoped.setattr(security, "KEY_FILE", str(model_dir / "secret.key"))
        scoped.setattr(security, "KEY_FILE_DPAPI", str(model_dir / "secret.key.dpapi"))
        security.reset_security_caches()
        scoped.setattr(paths, "data_dir", lambda: str(tmp_path))
        scoped.setattr(paths, "settings_file", lambda: str(settings_path))
        module = importlib.reload(app_settings)
        module.save_settings(
            {
                "deep_runtime_mode": "auto",
                "deep_runtime_manual_override": False,
                "deep_runtime_benchmark": {"status": "ok", "recommended_mode": "hybrid"},
            }
        )
        module = importlib.reload(app_settings)
        loaded = module.load_settings()
        assert loaded["deep_runtime_mode"] == "auto"
        assert loaded["deep_runtime_benchmark"]["recommended_mode"] == "hybrid"

    importlib.reload(app_settings)
