from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .common import _artifact_metadata, _dependency_available, _finite_quantile, _utc_now_iso
from .constants import (
    AtomicBytesWriter,
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    MIN_COMBINED_SEQUENCE_WINDOWS,
    MIN_DEEP_SEQUENCE_LENGTH,
    MIN_DEEP_SEQUENCE_NATIVE_WINDOWS,
    NEAR_CONSTANT_STD_EPSILON,
)
from .io import _write_torch_artifact
from .manifest import _manifest_entry, _trained_entry


def _train_deep_sequence_native_candidate(
    candidate_id: str,
    *,
    sequence_tensor: np.ndarray,
    sequence_labels: Sequence[int] | np.ndarray | None,
    feature_names: Sequence[str],
    feature_schema_version: str | None,
    model_dir: Path,
    writer: AtomicBytesWriter,
    max_epochs: int,
    batch_size: int,
    learning_rate: float,
    seed: int,
) -> dict[str, Any]:
    from .deep_oneclass import _torch_version
    from .deep_sequence import (
        _binary_metrics,
        _deep_sequence_native_architecture,
        _deep_sequence_native_model_for_candidate,
        _deep_sequence_native_skipped,
        _default_deep_sequence_native_model_config,
    )

    cid = str(candidate_id)
    if not _dependency_available("torch"):
        return _deep_sequence_native_skipped(cid, reason="dependency_missing", feature_names=feature_names)
    X = np.asarray(sequence_tensor, dtype=np.float32)
    if X.ndim != 3 or X.shape[0] <= 0:
        reason = "insufficient_mouse_windows" if cid == "mouse_resnet_gru" else "insufficient_combined_windows"
        return _deep_sequence_native_skipped(cid, reason=reason, feature_names=feature_names)
    if X.shape[2] <= 0 or not feature_names:
        reason = "insufficient_mouse_windows" if cid == "mouse_resnet_gru" else "insufficient_combined_windows"
        return _deep_sequence_native_skipped(cid, reason=reason, feature_names=feature_names, training_sample_count=int(X.shape[0]), sequence_count=int(X.shape[0]))
    if X.shape[1] < MIN_DEEP_SEQUENCE_LENGTH or X.shape[0] < MIN_DEEP_SEQUENCE_NATIVE_WINDOWS:
        reason = "insufficient_mouse_windows" if cid == "mouse_resnet_gru" else "insufficient_combined_windows"
        return _deep_sequence_native_skipped(cid, reason=reason, feature_names=feature_names, training_sample_count=int(X.shape[0]), sequence_count=int(X.shape[0]))
    if not np.isfinite(X).any():
        reason = "insufficient_mouse_windows" if cid == "mouse_resnet_gru" else "insufficient_combined_windows"
        return _deep_sequence_native_skipped(cid, reason=reason, feature_names=feature_names, training_sample_count=int(X.shape[0]), sequence_count=int(X.shape[0]), extra={"warnings": ["non_finite_sequence_tensor"]})
    finite_X = np.where(np.isfinite(X), X, 0.0).astype(np.float32)
    if float(np.nanstd(finite_X)) <= NEAR_CONSTANT_STD_EPSILON:
        reason = "insufficient_mouse_windows" if cid == "mouse_resnet_gru" else "insufficient_combined_windows"
        return _deep_sequence_native_skipped(
            cid,
            reason=reason,
            feature_names=feature_names,
            training_sample_count=int(finite_X.shape[0]),
            sequence_count=int(finite_X.shape[0]),
            extra={"warnings": ["near_constant_sequence_tensor"], "input_spread": float(np.nanmax(finite_X) - np.nanmin(finite_X)) if finite_X.size else 0.0},
        )
    y = np.zeros((finite_X.shape[0],), dtype=np.float32) if sequence_labels is None else np.asarray(sequence_labels, dtype=np.float32).reshape(-1)
    if y.shape[0] != finite_X.shape[0]:
        return _deep_sequence_native_skipped(cid, reason="insufficient_combined_windows", feature_names=feature_names, training_sample_count=int(finite_X.shape[0]), sequence_count=int(finite_X.shape[0]), extra={"warnings": ["label_count_mismatch"]})
    y = np.where(y >= 0.5, 1.0, 0.0).astype(np.float32)
    owner_count = int(np.sum(y == 0.0))
    intruder_count = int(np.sum(y == 1.0))
    if cid == "combined_cnn_lstm" and (owner_count < MIN_COMBINED_SEQUENCE_WINDOWS or intruder_count < 1):
        return _deep_sequence_native_skipped(
            cid,
            reason="insufficient_combined_windows",
            feature_names=feature_names,
            training_sample_count=int(finite_X.shape[0]),
            sequence_count=int(finite_X.shape[0]),
            owner_sequence_count=owner_count,
            intruder_sequence_count=intruder_count,
            extra={"requires_trusted_intruder_sequences": True, "minimum_owner_sequences": MIN_COMBINED_SEQUENCE_WINDOWS, "minimum_intruder_sequences": 1},
        )
    if cid == "mouse_resnet_gru" and owner_count < MIN_DEEP_SEQUENCE_NATIVE_WINDOWS:
        return _deep_sequence_native_skipped(cid, reason="insufficient_mouse_windows", feature_names=feature_names, training_sample_count=int(finite_X.shape[0]), sequence_count=int(finite_X.shape[0]), owner_sequence_count=owner_count)
    try:
        import torch
        from torch.utils.data import DataLoader, TensorDataset

        try:
            torch.set_num_threads(1)
        except Exception:
            pass
        torch.manual_seed(int(seed))
        np.random.seed(int(seed))
        model_config = _default_deep_sequence_native_model_config(cid, feature_dim=int(finite_X.shape[2]), sequence_length=int(finite_X.shape[1]))
        model = _deep_sequence_native_model_for_candidate(cid, feature_dim=int(finite_X.shape[2]), model_config=model_config)
        dataset = TensorDataset(torch.tensor(finite_X, dtype=torch.float32), torch.tensor(y, dtype=torch.float32))
        loader = DataLoader(dataset, batch_size=max(1, int(batch_size)), shuffle=True)
        if cid == "combined_cnn_lstm" and intruder_count > 0:
            pos_weight = torch.tensor([float(max(1, owner_count) / max(1, intruder_count))], dtype=torch.float32)
            criterion = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
        else:
            criterion = torch.nn.BCEWithLogitsLoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
        losses: list[float] = []
        model.train()
        for _epoch in range(max(1, int(max_epochs))):
            epoch_losses: list[float] = []
            for xb, yb in loader:
                optimizer.zero_grad(set_to_none=True)
                logits = model(xb).reshape(-1)
                loss = criterion(logits, yb.reshape(-1))
                loss.backward()
                optimizer.step()
                epoch_losses.append(float(loss.detach().cpu().item()))
            losses.append(float(np.mean(epoch_losses)) if epoch_losses else 0.0)
        model.eval()
        with torch.no_grad():
            logits = model(torch.tensor(finite_X, dtype=torch.float32)).reshape(-1)
            risks = torch.sigmoid(logits).detach().cpu().numpy().astype(float)
        if cid == "combined_cnn_lstm":
            threshold = 0.5
            threshold_source = "supervised_probability_default_0_5"
        else:
            threshold_value = _finite_quantile(risks, 0.95)
            if threshold_value is None:
                return _deep_sequence_native_skipped(cid, reason="threshold_unavailable", feature_names=feature_names, training_sample_count=int(finite_X.shape[0]), sequence_count=int(finite_X.shape[0]), owner_sequence_count=owner_count, intruder_sequence_count=intruder_count)
            threshold = float(threshold_value)
            threshold_source = "owner_mouse_resnet_gru_probability_p95"
        p99 = _finite_quantile(risks, 0.99)
        risk_std = float(np.std(risks)) if risks.size else 0.0
        risk_spread = float(np.max(risks) - np.min(risks)) if risks.size else 0.0
        collapse_warning = bool(risk_spread <= NEAR_CONSTANT_STD_EPSILON or risk_std <= NEAR_CONSTANT_STD_EPSILON)
        created_at = _utc_now_iso()
        training_summary = {
            "loss_history": [float(v) for v in losses],
            "owner_sequence_count": owner_count,
            "intruder_sequence_count": intruder_count,
            "risk_mean": float(np.mean(risks)) if risks.size else 0.0,
            "risk_std": risk_std,
            "risk_min": float(np.min(risks)) if risks.size else 0.0,
            "risk_max": float(np.max(risks)) if risks.size else 0.0,
            "risk_p95": float(_finite_quantile(risks, 0.95) or threshold),
            "risk_p99": None if p99 is None else float(p99),
            "risk_spread": risk_spread,
            "collapse_warning": collapse_warning,
            "binary_metrics": _binary_metrics(y, risks, float(threshold)) if cid == "combined_cnn_lstm" else {},
        }
        metadata = _artifact_metadata(
            candidate_id=cid,
            model_family=_deep_sequence_native_architecture(cid),
            feature_names=feature_names,
            feature_schema_version=feature_schema_version,
            threshold=float(threshold),
            threshold_source=threshold_source,
            training_sample_count=int(finite_X.shape[0]),
            hyperparameters={"max_epochs": int(max_epochs), "batch_size": int(batch_size), "learning_rate": float(learning_rate), **model_config},
            extra={
                "builder_version": DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION,
                "created_at": created_at,
                "dependency_name": "torch",
                "dependency_version": _torch_version(),
                "dependency_available": True,
                "dependency_status": "ok",
                "artifact_serialization": "torch_state_dict",
                "trained_on": "genuine_owner_mouse_sequence_windows_only" if cid == "mouse_resnet_gru" else "owner_and_trusted_intruder_combined_sequence_windows",
                "sequence_count": int(finite_X.shape[0]),
                "owner_sequence_count": owner_count,
                "intruder_sequence_count": intruder_count,
                "sequence_length": int(finite_X.shape[1]),
                "feature_count": int(finite_X.shape[2]),
                "model_config": model_config,
                "training_summary": training_summary,
                "training_metadata": training_summary,
                "collapse_diagnostics": {"risk_spread": risk_spread, "risk_std": risk_std, "collapse_warning": collapse_warning},
                "privacy": {"stores_raw_text": False, "raw_text_fields_stored": [], "raw_text_stored": False, "feature_source": "numeric_window_sequence_features"},
                "score_direction": "higher_score_more_suspicious",
            },
        )
        schema = {
            "artifact_schema": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
            "layout": "NTF",
            "feature_names": [str(name) for name in feature_names],
            "feature_schema_version": feature_schema_version,
            "sequence_length": int(finite_X.shape[1]),
            "feature_dim": int(finite_X.shape[2]),
            "privacy": {"stores_raw_text": False, "raw_text_fields_stored": [], "raw_text_stored": False},
        }
        artifact: dict[str, Any] = {
            "artifact_schema": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
            "artifact_version": DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION,
            "schema": schema,
            "feature_schema": schema,
            "candidate_id": cid,
            "model_family": _deep_sequence_native_architecture(cid),
            "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
            "model_config": model_config,
            "feature_names": [str(name) for name in feature_names],
            "threshold": float(threshold),
            "decision_threshold": float(threshold),
            "sequence_threshold": float(threshold),
            "risk_threshold": float(threshold),
            "threshold_source": threshold_source,
            "created_at": created_at,
            "training_summary": training_summary,
            "training_metadata": training_summary,
            "metadata": metadata,
            "privacy": {"stores_raw_text": False, "raw_text_fields_stored": [], "raw_text_stored": False},
            "report_only": True,
            "can_lock": False,
            "can_lock_alone": False,
            "can_influence_device": False,
            "runtime_authoritative": False,
            "trigger_face_confirmation": False,
        }
        try:
            rel_path, digest = _write_torch_artifact(model_dir=model_dir, candidate_id=cid, artifact=artifact, writer=writer)
        except Exception as exc:
            return _manifest_entry(
                candidate_id=cid,
                status="failed",
                artifact_path=None,
                feature_names=feature_names,
                threshold=None,
                threshold_source="not_available",
                training_sample_count=int(finite_X.shape[0]),
                reason="artifact_write_failed",
                model_family=_deep_sequence_native_architecture(cid),
                extra={"builder_version": DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION, "artifact_mode": "failed", "error_type": type(exc).__name__, "privacy": {"stores_raw_text": False, "raw_text_fields_stored": [], "raw_text_stored": False}},
            )
        return _trained_entry(
            candidate_id=cid,
            artifact_path=rel_path,
            artifact_digest=digest,
            feature_names=feature_names,
            threshold=float(threshold),
            training_sample_count=int(finite_X.shape[0]),
            model_family=_deep_sequence_native_architecture(cid),
            extra={
                "builder_version": DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION,
                "created_at": created_at,
                "threshold_source": threshold_source,
                "artifact_serialization": "torch_state_dict",
                "dependency_name": "torch",
                "dependency_version": _torch_version(),
                "dependency_available": True,
                "dependency_status": "ok",
                "artifact_mode": "trained",
                "trained_on": "genuine_owner_mouse_sequence_windows_only" if cid == "mouse_resnet_gru" else "owner_and_trusted_intruder_combined_sequence_windows",
                "sequence_count": int(finite_X.shape[0]),
                "owner_sequence_count": owner_count,
                "intruder_sequence_count": intruder_count,
                "sequence_length": int(finite_X.shape[1]),
                "feature_count": int(finite_X.shape[2]),
                "model_config": model_config,
                "training_summary": training_summary,
                "training_metadata": training_summary,
                "collapse_diagnostics": dict(metadata.get("collapse_diagnostics") or {}),
                "privacy": {"stores_raw_text": False, "raw_text_fields_stored": [], "raw_text_stored": False, "feature_source": "numeric_window_sequence_features"},
                "score_direction": "higher_score_more_suspicious",
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
            model_family=_deep_sequence_native_architecture(cid),
            extra={"builder_version": DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION, "artifact_mode": "failed", "privacy": {"stores_raw_text": False, "raw_text_fields_stored": [], "raw_text_stored": False}},
        )
