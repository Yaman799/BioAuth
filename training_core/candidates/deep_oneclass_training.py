from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .common import _artifact_metadata, _dependency_available, _finite_quantile
from .constants import (
    AtomicBytesWriter,
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    DEFAULT_DEEP_BATCH_SIZE,
    DEFAULT_DEEP_LEARNING_RATE,
    DEFAULT_DEEP_MAX_EPOCHS,
    DEEP_ONECLASS_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    MIN_DEEP_SEQUENCE_LENGTH,
    MIN_DEEP_SEQUENCE_WINDOWS,
    NEAR_CONSTANT_STD_EPSILON,
)
from .io import _write_torch_artifact
from .manifest import _manifest_entry


def _train_deep_oneclass_candidate(
    candidate_id: str,
    *,
    sequence_tensor: np.ndarray,
    feature_names: Sequence[str],
    feature_schema_version: str | None,
    model_dir: Path,
    writer: AtomicBytesWriter,
    max_epochs: int,
    batch_size: int,
    learning_rate: float,
    seed: int,
) -> dict[str, Any]:
    from .deep_oneclass import (
        _deep_candidate_architecture,
        _deep_model_for_candidate,
        _deep_skipped,
        _default_deep_model_config,
        _is_deep_svdd_candidate,
        _is_mouse_deep_candidate,
        _torch_version,
    )

    cid = str(candidate_id)
    if not _dependency_available("torch"):
        return _deep_skipped(cid, reason="dependency_missing", feature_names=feature_names)
    X = np.asarray(sequence_tensor, dtype=np.float32)
    if X.ndim != 3 or X.shape[0] <= 0:
        reason = "insufficient_mouse_windows" if _is_mouse_deep_candidate(cid) else "insufficient_sequence_windows"
        return _deep_skipped(cid, reason=reason, feature_names=feature_names)
    if X.shape[2] <= 0 or not feature_names:
        return _deep_skipped(cid, reason="insufficient_window_features", feature_names=feature_names, training_sample_count=int(X.shape[0]), sequence_count=int(X.shape[0]))
    if X.shape[1] < MIN_DEEP_SEQUENCE_LENGTH or X.shape[0] < MIN_DEEP_SEQUENCE_WINDOWS:
        reason = "insufficient_mouse_windows" if _is_mouse_deep_candidate(cid) and X.shape[0] <= 0 else "insufficient_sequence_windows"
        return _deep_skipped(cid, reason=reason, feature_names=feature_names, training_sample_count=int(X.shape[0]), sequence_count=int(X.shape[0]))
    if not np.isfinite(X).any():
        return _deep_skipped(cid, reason="insufficient_window_features", feature_names=feature_names, training_sample_count=int(X.shape[0]), sequence_count=int(X.shape[0]), extra={"warnings": ["non_finite_sequence_tensor"]})
    finite_X = np.where(np.isfinite(X), X, 0.0).astype(np.float32)
    risk_spread_input = float(np.nanmax(finite_X) - np.nanmin(finite_X)) if finite_X.size else 0.0
    if float(np.nanstd(finite_X)) <= NEAR_CONSTANT_STD_EPSILON:
        return _deep_skipped(
            cid,
            reason="insufficient_window_features",
            feature_names=feature_names,
            training_sample_count=int(finite_X.shape[0]),
            sequence_count=int(finite_X.shape[0]),
            extra={"warnings": ["near_constant_feature_matrix"], "input_spread": risk_spread_input},
        )
    try:
        import torch
        from torch.utils.data import DataLoader, TensorDataset

        try:
            torch.set_num_threads(1)
        except Exception:
            pass
        torch.manual_seed(int(seed))
        np.random.seed(int(seed))
        model_config = _default_deep_model_config(cid, feature_dim=int(finite_X.shape[2]), sequence_length=int(finite_X.shape[1]))
        model = _deep_model_for_candidate(cid, feature_dim=int(finite_X.shape[2]), model_config=model_config)
        dataset = TensorDataset(torch.tensor(finite_X, dtype=torch.float32))
        loader = DataLoader(dataset, batch_size=max(1, int(batch_size)), shuffle=True)
        optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
        model.train()
        center_tensor = None
        if _is_deep_svdd_candidate(cid):
            model.eval()
            embeddings = []
            with torch.no_grad():
                for (xb,) in DataLoader(dataset, batch_size=max(1, int(batch_size)), shuffle=False):
                    embeddings.append(model(xb).detach())
            if not embeddings:
                return _deep_skipped(cid, reason="threshold_unavailable", feature_names=feature_names, training_sample_count=int(finite_X.shape[0]), sequence_count=int(finite_X.shape[0]))
            center_tensor = torch.cat(embeddings, dim=0).mean(dim=0)
            model.train()
        losses: list[float] = []
        for _epoch in range(max(1, int(max_epochs))):
            epoch_losses: list[float] = []
            for (xb,) in loader:
                optimizer.zero_grad(set_to_none=True)
                if _is_deep_svdd_candidate(cid):
                    embedding = model(xb)
                    loss = torch.mean(torch.sum((embedding - center_tensor) ** 2, dim=1))
                else:
                    recon = model(xb)
                    loss = torch.mean((recon - xb) ** 2)
                loss.backward()
                optimizer.step()
                epoch_losses.append(float(loss.detach().cpu().item()))
            losses.append(float(np.mean(epoch_losses)) if epoch_losses else 0.0)
        model.eval()
        errors: list[np.ndarray] = []
        center_vector: list[float] | None = None
        with torch.no_grad():
            full = torch.tensor(finite_X, dtype=torch.float32)
            if _is_deep_svdd_candidate(cid):
                embeddings = model(full)
                center = embeddings.mean(dim=0)
                center_vector = [float(v) for v in center.detach().cpu().numpy().reshape(-1)]
                err = torch.sum((embeddings - center) ** 2, dim=1).detach().cpu().numpy().astype(float)
            else:
                recon = model(full)
                err = torch.mean((recon - full) ** 2, dim=(1, 2)).detach().cpu().numpy().astype(float)
            errors.append(err)
        train_errors = np.concatenate(errors).reshape(-1) if errors else np.asarray([], dtype=float)
        threshold = _finite_quantile(train_errors, 0.95)
        p99 = _finite_quantile(train_errors, 0.99)
        if threshold is None:
            return _deep_skipped(cid, reason="threshold_unavailable", feature_names=feature_names, training_sample_count=int(finite_X.shape[0]), sequence_count=int(finite_X.shape[0]))
        risk_std = float(np.std(train_errors)) if train_errors.size else 0.0
        risk_spread = float(np.max(train_errors) - np.min(train_errors)) if train_errors.size else 0.0
        collapse_warning = bool(risk_spread <= NEAR_CONSTANT_STD_EPSILON or risk_std <= NEAR_CONSTANT_STD_EPSILON)
        metadata = _artifact_metadata(
            candidate_id=cid,
            model_family=_deep_candidate_architecture(cid),
            feature_names=feature_names,
            feature_schema_version=feature_schema_version,
            threshold=threshold,
            threshold_source="owner_reconstruction_error_p95" if not _is_deep_svdd_candidate(cid) else "owner_distance_to_center_p95",
            training_sample_count=int(finite_X.shape[0]),
            hyperparameters={"max_epochs": int(max_epochs), "batch_size": int(batch_size), "learning_rate": float(learning_rate), **model_config},
            extra={
                "builder_version": DEEP_ONECLASS_CANDIDATE_ARTIFACT_BUILDER_VERSION,
                "dependency_name": "torch",
                "dependency_version": _torch_version(),
                "dependency_available": True,
                "dependency_status": "ok",
                "artifact_serialization": "torch_state_dict",
                "trained_on": "genuine_owner_sequence_windows_only",
                "sequence_count": int(finite_X.shape[0]),
                "sequence_length": int(finite_X.shape[1]),
                "feature_count": int(finite_X.shape[2]),
                "model_config": model_config,
                "training_stats": {
                    "loss_history": [float(v) for v in losses],
                    "owner_error_mean": float(np.mean(train_errors)) if train_errors.size else 0.0,
                    "owner_error_std": risk_std,
                    "owner_error_min": float(np.min(train_errors)) if train_errors.size else 0.0,
                    "owner_error_max": float(np.max(train_errors)) if train_errors.size else 0.0,
                    "owner_error_p95": float(threshold),
                    "owner_error_p99": None if p99 is None else float(p99),
                    "risk_spread": risk_spread,
                    "collapse_warning": collapse_warning,
                },
                "collapse_diagnostics": {"risk_spread": risk_spread, "risk_std": risk_std, "collapse_warning": collapse_warning},
            },
        )
        schema = {
            "artifact_schema": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
            "layout": "NTF",
            "feature_names": [str(name) for name in feature_names],
            "feature_schema_version": feature_schema_version,
            "sequence_length": int(finite_X.shape[1]),
            "feature_dim": int(finite_X.shape[2]),
        }
        artifact: dict[str, Any] = {
            "artifact_schema": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
            "schema": schema,
            "feature_schema": schema,
            "candidate_id": cid,
            "model_family": _deep_candidate_architecture(cid),
            "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
            "model_config": model_config,
            "feature_names": [str(name) for name in feature_names],
            "threshold": float(threshold),
            "decision_threshold": float(threshold),
            "sequence_threshold": float(threshold),
            "threshold_source": metadata["threshold_source"],
            "training_metadata": dict(metadata),
            "training_stats": metadata["training_stats"],
            "report_only": True,
            "can_lock": False,
            "can_lock_alone": False,
            "can_influence_device": False,
            "runtime_authoritative": False,
            "trigger_face_confirmation": False,
        }
        if center_vector is not None:
            artifact["center_vector"] = center_vector
            artifact["svdd_center"] = center_vector
        rel_path, digest = _write_torch_artifact(model_dir=model_dir, candidate_id=cid, artifact=artifact, writer=writer)
        return _manifest_entry(
            candidate_id=cid,
            status="trained",
            artifact_path=rel_path,
            feature_names=feature_names,
            threshold=float(threshold),
            threshold_source=str(metadata["threshold_source"]),
            training_sample_count=int(finite_X.shape[0]),
            reason="ok",
            model_family=_deep_candidate_architecture(cid),
            artifact_digest=digest,
            extra={
                "builder_version": DEEP_ONECLASS_CANDIDATE_ARTIFACT_BUILDER_VERSION,
                "dependency_name": "torch",
                "dependency_version": _torch_version(),
                "dependency_available": True,
                "dependency_status": "ok",
                "artifact_serialization": "torch_state_dict",
                "artifact_mode": "offline_candidate_report_only",
                "trained_on": "genuine_owner_sequence_windows_only",
                "sequence_count": int(finite_X.shape[0]),
                "sequence_length": int(finite_X.shape[1]),
                "feature_count": int(finite_X.shape[2]),
                "model_config": model_config,
                "collapse_diagnostics": metadata["collapse_diagnostics"],
                "training_stats": metadata["training_stats"],
            },
        )
    except Exception as exc:
        return _manifest_entry(
            candidate_id=cid,
            status="failed",
            artifact_path=None,
            feature_names=feature_names,
            threshold=None,
            threshold_source="not_available",
            training_sample_count=int(X.shape[0]) if X.ndim == 3 else 0,
            reason=f"training_failed:{type(exc).__name__}",
            model_family=_deep_candidate_architecture(cid),
            extra={
                "builder_version": DEEP_ONECLASS_CANDIDATE_ARTIFACT_BUILDER_VERSION,
                "dependency_name": "torch",
                "dependency_version": _torch_version(),
                "dependency_available": _dependency_available("torch"),
                "artifact_mode": "failed",
                "trained_on": "genuine_owner_sequence_windows_only",
            },
        )
