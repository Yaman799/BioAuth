from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .common import _artifact_metadata, _dependency_available, _finite_quantile
from .constants import (
    AtomicBytesWriter,
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    KEYBOARD_DEEP_CANDIDATE_ARTIFACT_BUILDER_VERSION,
    MIN_KEYBOARD_SEQUENCE_LENGTH,
    MIN_KEYBOARD_SEQUENCE_WINDOWS,
    MIN_TYPEFORMER_FREE_TEXT_LENGTH,
    NEAR_CONSTANT_STD_EPSILON,
)
from .io import _write_torch_artifact
from .manifest import _manifest_entry, _trained_entry


def _train_keyboard_deep_candidate(
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
    pair_count: int = 0,
) -> dict[str, Any]:
    from .deep_oneclass import _torch_version
    from .keyboard_deep import (
        _default_keyboard_model_config,
        _is_keyboard_siamese_candidate,
        _is_keyboard_typeformer_candidate,
        _keyboard_candidate_architecture,
        _keyboard_model_for_candidate,
        _keyboard_skipped,
    )

    cid = str(candidate_id)
    if not _dependency_available("torch"):
        return _keyboard_skipped(cid, reason="dependency_missing", feature_names=feature_names)
    X = np.asarray(sequence_tensor, dtype=np.float32)
    if X.ndim != 3 or X.shape[0] <= 0:
        return _keyboard_skipped(cid, reason="insufficient_keyboard_windows", feature_names=feature_names)
    if X.shape[2] <= 0 or not feature_names:
        return _keyboard_skipped(cid, reason="insufficient_window_features", feature_names=feature_names, training_sample_count=int(X.shape[0]), sequence_count=int(X.shape[0]))
    min_len = MIN_TYPEFORMER_FREE_TEXT_LENGTH if _is_keyboard_typeformer_candidate(cid) else MIN_KEYBOARD_SEQUENCE_LENGTH
    if X.shape[1] < min_len:
        reason = "insufficient_free_text_data" if _is_keyboard_typeformer_candidate(cid) else "insufficient_keyboard_windows"
        return _keyboard_skipped(cid, reason=reason, feature_names=feature_names, training_sample_count=int(X.shape[0]), sequence_count=int(X.shape[0]))
    if X.shape[0] < MIN_KEYBOARD_SEQUENCE_WINDOWS:
        return _keyboard_skipped(cid, reason="insufficient_keyboard_windows", feature_names=feature_names, training_sample_count=int(X.shape[0]), sequence_count=int(X.shape[0]))
    if _is_keyboard_siamese_candidate(cid) and int(pair_count) < 1:
        return _keyboard_skipped(cid, reason="missing_reference_template", feature_names=feature_names, training_sample_count=int(X.shape[0]), sequence_count=int(X.shape[0]), extra={"pair_count": int(pair_count), "triplet_count": 0})
    if not np.isfinite(X).any():
        return _keyboard_skipped(cid, reason="insufficient_window_features", feature_names=feature_names, training_sample_count=int(X.shape[0]), sequence_count=int(X.shape[0]), extra={"warnings": ["non_finite_sequence_tensor"]})
    finite_X = np.where(np.isfinite(X), X, 0.0).astype(np.float32)
    risk_spread_input = float(np.nanmax(finite_X) - np.nanmin(finite_X)) if finite_X.size else 0.0
    if float(np.nanstd(finite_X)) <= NEAR_CONSTANT_STD_EPSILON:
        return _keyboard_skipped(
            cid,
            reason="insufficient_window_features",
            feature_names=feature_names,
            training_sample_count=int(finite_X.shape[0]),
            sequence_count=int(finite_X.shape[0]),
            extra={"warnings": ["near_constant_keyboard_feature_matrix"], "input_spread": risk_spread_input},
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
        model_config = _default_keyboard_model_config(cid, feature_dim=int(finite_X.shape[2]), sequence_length=int(finite_X.shape[1]))
        model = _keyboard_model_for_candidate(cid, feature_dim=int(finite_X.shape[2]), model_config=model_config)
        dataset = TensorDataset(torch.tensor(finite_X, dtype=torch.float32))
        loader = DataLoader(dataset, batch_size=max(1, int(batch_size)), shuffle=True)
        optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
        losses: list[float] = []
        model.train()
        for _epoch in range(max(1, int(max_epochs))):
            epoch_losses: list[float] = []
            for (xb,) in loader:
                optimizer.zero_grad(set_to_none=True)
                output = model(xb)
                if cid == "keyboard_bigru_cnn_attention":
                    # Owner-only diagnostic training: genuine owner windows are the only
                    # positive source, so train the logit toward low intruder risk.
                    loss = torch.nn.functional.binary_cross_entropy_with_logits(output.reshape(-1), torch.zeros_like(output.reshape(-1)))
                else:
                    embeddings = output.reshape(output.shape[0], -1)
                    center = embeddings.detach().mean(dim=0, keepdim=True)
                    loss = torch.mean(torch.sum((embeddings - center) ** 2, dim=1))
                loss.backward()
                optimizer.step()
                epoch_losses.append(float(loss.detach().cpu().item()))
            losses.append(float(np.mean(epoch_losses)) if epoch_losses else 0.0)
        model.eval()
        with torch.no_grad():
            full = torch.tensor(finite_X, dtype=torch.float32)
            output = model(full)
            if cid == "keyboard_bigru_cnn_attention":
                risks = torch.sigmoid(output.reshape(-1)).detach().cpu().numpy().astype(float)
                reference_embedding: list[float] = [float(np.mean(risks))] if risks.size else []
                threshold_source = "owner_keyboard_intruder_probability_p95"
            else:
                embeddings_tensor = output.reshape(output.shape[0], -1)
                center_tensor = embeddings_tensor.mean(dim=0)
                reference_embedding = [float(v) for v in center_tensor.detach().cpu().numpy().reshape(-1)]
                risks = torch.linalg.vector_norm(embeddings_tensor - center_tensor, dim=1).detach().cpu().numpy().astype(float)
                threshold_source = "owner_keyboard_embedding_distance_p95"
        threshold = _finite_quantile(risks, 0.95)
        p99 = _finite_quantile(risks, 0.99)
        if threshold is None or not reference_embedding:
            return _keyboard_skipped(cid, reason="threshold_unavailable", feature_names=feature_names, training_sample_count=int(finite_X.shape[0]), sequence_count=int(finite_X.shape[0]))
        risk_std = float(np.std(risks)) if risks.size else 0.0
        risk_spread = float(np.max(risks) - np.min(risks)) if risks.size else 0.0
        collapse_warning = bool(risk_spread <= NEAR_CONSTANT_STD_EPSILON or risk_std <= NEAR_CONSTANT_STD_EPSILON)
        metadata = _artifact_metadata(
            candidate_id=cid,
            model_family=_keyboard_candidate_architecture(cid),
            feature_names=feature_names,
            feature_schema_version=feature_schema_version,
            threshold=threshold,
            threshold_source=threshold_source,
            training_sample_count=int(finite_X.shape[0]),
            hyperparameters={"max_epochs": int(max_epochs), "batch_size": int(batch_size), "learning_rate": float(learning_rate), **model_config},
            extra={
                "builder_version": KEYBOARD_DEEP_CANDIDATE_ARTIFACT_BUILDER_VERSION,
                "dependency_name": "torch",
                "dependency_version": _torch_version(),
                "dependency_available": True,
                "dependency_status": "ok",
                "artifact_serialization": "torch_state_dict",
                "trained_on": "genuine_owner_keyboard_timing_sequence_windows_only",
                "sequence_count": int(finite_X.shape[0]),
                "sequence_length": int(finite_X.shape[1]),
                "feature_count": int(finite_X.shape[2]),
                "model_config": model_config,
                "reference_template": reference_embedding,
                "reference_embedding": reference_embedding,
                "training_metadata": {
                    "loss_history": [float(v) for v in losses],
                    "owner_risk_mean": float(np.mean(risks)) if risks.size else 0.0,
                    "owner_risk_std": risk_std,
                    "owner_risk_min": float(np.min(risks)) if risks.size else 0.0,
                    "owner_risk_max": float(np.max(risks)) if risks.size else 0.0,
                    "owner_risk_p95": float(threshold),
                    "owner_risk_p99": None if p99 is None else float(p99),
                    "risk_spread": risk_spread,
                    "collapse_warning": collapse_warning,
                    "pair_count": int(pair_count),
                    "triplet_count": 0,
                },
                "collapse_diagnostics": {"risk_spread": risk_spread, "risk_std": risk_std, "collapse_warning": collapse_warning},
                "privacy": {"stores_raw_text": False, "raw_text_fields_stored": [], "feature_source": "keyboard_timing_rhythm_windows"},
            },
        )
        schema = {
            "artifact_schema": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
            "layout": "NTF",
            "feature_names": [str(name) for name in feature_names],
            "feature_schema_version": feature_schema_version,
            "sequence_length": int(finite_X.shape[1]),
            "feature_dim": int(finite_X.shape[2]),
            "privacy": {"stores_raw_text": False, "raw_text_fields_stored": []},
        }
        artifact: dict[str, Any] = {
            "artifact_schema": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
            "schema": schema,
            "feature_schema": schema,
            "candidate_id": cid,
            "model_family": _keyboard_candidate_architecture(cid),
            "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
            "model_config": model_config,
            "feature_names": [str(name) for name in feature_names],
            "threshold": float(threshold),
            "decision_threshold": float(threshold),
            "risk_threshold": float(threshold),
            "threshold_source": threshold_source,
            "reference_template": reference_embedding,
            "reference_embedding": reference_embedding,
            "training_metadata": dict(metadata.get("training_metadata") or {}),
            "metadata": metadata,
            "privacy": {"stores_raw_text": False, "raw_text_fields_stored": [], "raw_text_stored": False},
            "report_only": True,
            "can_lock": False,
            "can_lock_alone": False,
            "can_influence_device": False,
            "runtime_authoritative": False,
            "trigger_face_confirmation": False,
        }
        rel_path, digest = _write_torch_artifact(model_dir=model_dir, candidate_id=cid, artifact=artifact, writer=writer)
        return _trained_entry(
            candidate_id=cid,
            artifact_path=rel_path,
            artifact_digest=digest,
            feature_names=feature_names,
            threshold=threshold,
            training_sample_count=int(finite_X.shape[0]),
            model_family=_keyboard_candidate_architecture(cid),
            extra={
                "builder_version": KEYBOARD_DEEP_CANDIDATE_ARTIFACT_BUILDER_VERSION,
                "artifact_serialization": "torch_state_dict",
                "dependency_name": "torch",
                "dependency_version": _torch_version(),
                "dependency_available": True,
                "dependency_status": "ok",
                "artifact_mode": "trained",
                "trained_on": "genuine_owner_keyboard_timing_sequence_windows_only",
                "sequence_count": int(finite_X.shape[0]),
                "sequence_length": int(finite_X.shape[1]),
                "feature_count": int(finite_X.shape[2]),
                "model_config": model_config,
                "reference_template": reference_embedding,
                "reference_embedding": reference_embedding,
                "training_metadata": dict(metadata.get("training_metadata") or {}),
                "collapse_diagnostics": dict(metadata.get("collapse_diagnostics") or {}),
                "privacy": {"stores_raw_text": False, "raw_text_fields_stored": [], "raw_text_stored": False},
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
            model_family=_keyboard_candidate_architecture(cid),
            extra={"builder_version": KEYBOARD_DEEP_CANDIDATE_ARTIFACT_BUILDER_VERSION, "artifact_mode": "failed", "privacy": {"stores_raw_text": False, "raw_text_fields_stored": []}},
        )
