from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


class FixtureProbabilityClassifier:
    """Tiny pickle-safe classifier used only by encrypted-session fixtures."""

    def __init__(self) -> None:
        self.classes_ = None
        self.positive_probability_ = 0.5

    def fit(self, X: Any, y: Any) -> "FixtureProbabilityClassifier":
        import numpy as np

        labels = np.asarray(y, dtype=int)
        self.classes_ = np.asarray([0, 1], dtype=int)
        if labels.size:
            self.positive_probability_ = float(np.mean(labels == 1))
        return self

    def predict_proba(self, X: Any):
        import numpy as np

        row_count = int(getattr(X, "shape", [len(X) if X is not None else 0])[0])
        p_intruder = min(0.99, max(0.01, float(self.positive_probability_)))
        probs = np.empty((row_count, 2), dtype=float)
        probs[:, 1] = p_intruder
        probs[:, 0] = 1.0 - p_intruder
        return probs

    def predict(self, X: Any):
        import numpy as np

        row_count = int(getattr(X, "shape", [len(X) if X is not None else 0])[0])
        return np.full(row_count, 1 if self.positive_probability_ >= 0.5 else 0, dtype=int)


def isolate_encrypted_session_runtime(tmp_path: Path, monkeypatch: Any) -> dict[str, Path]:
    """Route encrypted-session tests to per-test data, model, and key paths.

    The helper keeps the real Fernet/HMAC production code in use, but makes the
    key file deterministic for the current pytest temp directory and clears any
    memoized cipher that may have been created before a module reload.
    """

    import paths
    from bio_platform import secrets as secret_backend

    data_root = tmp_path / "data"
    models_root = tmp_path / "models"
    control_root = data_root / "control"
    live_root = data_root / "live_session"
    sessions_root = data_root / "sessions"
    monitor_log = data_root / "monitor_log.json"

    monkeypatch.setattr(paths, "data_dir", lambda: str(data_root))
    monkeypatch.setattr(paths, "models_dir", lambda: str(models_root))
    monkeypatch.setattr(paths, "control_dir", lambda: str(control_root))
    monkeypatch.setattr(paths, "settings_file", lambda: str(data_root / "settings.json"))
    monkeypatch.setattr(paths, "users_file", lambda: str(data_root / "users.json"))
    monkeypatch.setattr(paths, "lockouts_file", lambda: str(data_root / "lockouts.json"))
    monkeypatch.setattr(paths, "account_creation_limits_file", lambda: str(data_root / "account_creation_limits.json"))
    monkeypatch.setattr(paths, "remembered_login_file", lambda: str(data_root / "remembered_login.json"))
    monkeypatch.setattr(paths, "sessions_dir", lambda: str(sessions_root))
    monkeypatch.setattr(paths, "live_session_dir", lambda: str(live_root))
    monkeypatch.setattr(paths, "runtime_base_dir", lambda: str(tmp_path))
    monkeypatch.setattr(paths, "monitor_log_file", lambda: str(monitor_log))

    # Avoid host keyring/real user secret stores in tests.  The encrypted files
    # are still Fernet-encrypted, just with a temp-directory key file.
    monkeypatch.setattr(secret_backend, "keyring", None)

    for folder in (data_root, models_root, control_root, live_root, sessions_root):
        folder.mkdir(parents=True, exist_ok=True)

    security = sys.modules.get("security")
    if security is not None:
        monkeypatch.setattr(security, "MODELS_DIR", str(models_root), raising=False)
        monkeypatch.setattr(security, "KEY_FILE", str(models_root / "secret.key"), raising=False)
        monkeypatch.setattr(security, "KEY_FILE_DPAPI", str(models_root / "secret.key.dpapi"), raising=False)
        monkeypatch.setattr(security, "HASH_FILE", str(models_root / "model.hash"), raising=False)
        monkeypatch.setattr(security, "CLASSIFIER_HASH_FILE", str(models_root / "classifier.hash"), raising=False)
        reset = getattr(security, "reset_security_caches", None)
        if callable(reset):
            reset()

    return {
        "data_root": data_root,
        "models_root": models_root,
        "control_root": control_root,
        "live_root": live_root,
        "sessions_root": sessions_root,
        "monitor_log": monitor_log,
    }


def reload_encrypted_session_modules(*names: str) -> tuple[ModuleType, ...]:
    """Reload modules that cache security/path imports around encrypted fixtures."""

    loaded: list[ModuleType] = []
    for name in names:
        module = importlib.import_module(name)
        loaded.append(importlib.reload(module))
    security = sys.modules.get("security")
    reset = getattr(security, "reset_security_caches", None)
    if callable(reset):
        reset()
    return tuple(loaded)


def stabilize_fast_training_modules(model_training: ModuleType) -> None:
    """Keep encrypted-session integration fixtures deterministic and bounded.

    The production training code remains unchanged.  These focused tests build
    many encrypted synthetic sessions only to verify fixture decryptability,
    context routing, and artifact wiring; using smaller deterministic estimators
    avoids CI timeouts while still exercising real Fernet IO, HMAC sidecars,
    IsolationForest, classifier sidecars, metadata writes, and runtime loading.
    """

    def _one_job(*_args: Any, **_kwargs: Any) -> int:
        return 1

    def _iforest_kwargs(contamination: float) -> dict[str, Any]:
        return {"contamination": float(contamination), "random_state": 42, "n_jobs": 1}

    def _fast_supervised_classifier(family: str) -> tuple[Any, dict[str, Any]]:
        params = {
            "strategy": "fixture_probability_prior",
            "fixture_family": str(family or "random_forest"),
            "fixture_reason": "encrypted_session_fixture_classifier_speed",
        }
        return FixtureProbabilityClassifier(), dict(params)

    def _skip_deep_sequence_training(**_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "skipped",
            "reason": "encrypted_fixture_fast_training",
            "artifact_written": False,
        }

    def _skip_hybrid_pro_artifacts(**_kwargs: Any) -> dict[str, Any]:
        return {
            "training_strategy": "context_aware",
            "model_family": "classic_isolation_forest",
            "hybrid_pro_enabled": False,
            "layer_artifacts": {},
            "skipped_layers": {
                "hybrid_pro": "skipped_for_encrypted_fixture_speed",
            },
            "skip_reason_codes": ["encrypted_fixture_fast_training"],
            "dependency_versions": {},
            "layer_readiness": {},
            "modality_mapping": {},
        }

    def _skip_classical_baselines(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        # The encrypted-session integration fixtures verify IO, metadata, routing,
        # publishing, and runtime loading.  Dedicated classical-baseline tests cover
        # these estimators directly; skipping the high-dimensional covariance inverse
        # here avoids platform-dependent full-suite stalls without weakening the
        # security assertions exercised by these fixtures.
        return {
            "baseline_version": "encrypted-session-fixture-fast",
            "models": {},
            "skipped": {"classical_baselines": "skipped_for_encrypted_fixture_speed"},
            "report_only": True,
        }

    def _skip_candidate_artifacts(**kwargs: Any) -> dict[str, Any]:
        import json
        from pathlib import Path

        model_dir = Path(kwargs.get("model_dir") or ".")
        model_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": "test-fixture",
            "builder_version": "encrypted-session-fixture-fast",
            "status_counts": {"trained": 0, "skipped": 1, "failed": 0},
            "report_only": True,
            "can_lock": False,
            "can_lock_alone": False,
            "can_influence_device": False,
            "runtime_authoritative": False,
            "trigger_face_confirmation": False,
            "candidates": {},
        }
        manifest_path = model_dir / "candidate_artifacts_manifest.json"
        writer = kwargs.get("atomic_write_text_fn")
        if callable(writer):
            writer(str(manifest_path), json.dumps(manifest, indent=2, ensure_ascii=False))
        else:
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return {
            "schema_version": "test-fixture",
            "builder_version": "encrypted-session-fixture-fast",
            "manifest_path": "candidate_artifacts_manifest.json",
            "manifest": manifest,
            "candidate_artifacts": {},
            "status_counts": dict(manifest["status_counts"]),
            "report_only": True,
            "can_lock": False,
            "can_lock_alone": False,
            "can_influence_device": False,
            "runtime_authoritative": False,
            "trigger_face_confirmation": False,
        }

    model_training.USING_LIGHTGBM = False
    model_training.LGBMClassifier = None
    model_training._cpu_parallel_jobs = _one_job
    model_training._iforest_fit_kwargs = _iforest_kwargs
    model_training._make_supervised_classifier = _fast_supervised_classifier
    model_training._allow_expensive_offline_evaluation = lambda *_args, **_kwargs: False
    model_training._run_deep_sequence_training = _skip_deep_sequence_training
    model_training.build_classical_baselines = _skip_classical_baselines

    pipeline = sys.modules.get("training_core.pipeline")
    if pipeline is not None:
        setattr(pipeline, "build_report_only_candidate_artifacts", _skip_candidate_artifacts)
        setattr(pipeline, "build_hybrid_pro_artifacts", _skip_hybrid_pro_artifacts)
        setattr(pipeline, "build_classical_baselines", _skip_classical_baselines)
