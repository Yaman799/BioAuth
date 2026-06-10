"""Context-specific training helpers extracted in Phase 4.

This module owns routed context bundle training and context artifact persistence
so the legacy training pipeline can delegate the context-specific submodel block
without keeping the full implementation inline.
"""

from __future__ import annotations

import json
import os
import pickle
from typing import Any, Callable, Dict, List

import numpy as np

from artifact_integrity import remove_classifier_sidecar, save_classifier_sidecar
from features import classify_behavior_context
from model_metadata import (
    CONTEXT_ROUTER_MIN_CONFIDENCE,
    CONTEXT_ROUTING_VERSION,
    MIN_CONTEXT_POSITIVE_SESSION_SUPPORT,
    MIN_CONTEXT_POSITIVE_WINDOW_SAMPLES,
    ROUTER_CONTEXTS,
)
from security import atomic_write_bytes, atomic_write_text, save_metadata_hash, save_model_hash
from training_core.calibration import _score_percentiles_dict
from training_core.data import get_anomaly_scores

CONTEXT_SELECTION_VERSION = "phase5-context-v1"


def _context_dir(model_dir: str, context_name: str) -> str:
    return os.path.join(model_dir, "contexts", str(context_name or "unknown").strip().lower())


def train_context_submodels(
    *,
    model_dir: str,
    feature_names: List[str],
    X: np.ndarray,
    y: np.ndarray,
    samples: List[Dict[str, float]],
    sample_sources: List[str],
    active_window_scales: List[float],
    metadata_template: Dict[str, Any],
    iforest_factory: Any,
    iforest_fit_kwargs_builder: Callable[[float], Dict[str, Any]],
    classifier_trainer: Callable[..., tuple[Any | None, Dict[str, Any]]],
    minimum_negative_samples: int,
    challenger_selection_version: str,
) -> Dict[str, Any]:
    route_records = [classify_behavior_context(sample) for sample in samples]
    context_counts: Dict[str, Dict[str, Any]] = {}
    bundles: Dict[str, Dict[str, Any]] = {}

    for context_name in ROUTER_CONTEXTS:
        pos_idx = [
            idx
            for idx, (label, route) in enumerate(zip(y.tolist(), route_records))
            if int(label) == 0 and str(route.get("context") or "") == context_name
        ]
        neg_idx = [
            idx
            for idx, (label, route) in enumerate(zip(y.tolist(), route_records))
            if int(label) == 1 and str(route.get("context") or "") == context_name
        ]
        pos_sessions = sorted({sample_sources[idx] for idx in pos_idx})
        neg_sessions = sorted({sample_sources[idx] for idx in neg_idx})
        avg_confidence = float(np.mean([float(route_records[idx].get("confidence") or 0.0) for idx in pos_idx])) if pos_idx else 0.0
        context_counts[context_name] = {
            "positive_window_samples": int(len(pos_idx)),
            "negative_window_samples": int(len(neg_idx)),
            "positive_session_count": int(len(pos_sessions)),
            "negative_session_count": int(len(neg_sessions)),
            "average_positive_router_confidence": round(avg_confidence, 6),
        }
        if len(pos_idx) < int(MIN_CONTEXT_POSITIVE_WINDOW_SAMPLES):
            continue
        if len(pos_sessions) < int(MIN_CONTEXT_POSITIVE_SESSION_SUPPORT):
            continue

        X_pos = X[np.asarray(pos_idx, dtype=int)]
        X_neg = X[np.asarray(neg_idx, dtype=int)] if neg_idx else np.asarray([], dtype=float).reshape(0, X.shape[1])
        contamination = 0.06 if len(X_pos) >= 40 else 0.08 if len(X_pos) >= 20 else 0.1
        context_model = iforest_factory(**iforest_fit_kwargs_builder(contamination))
        context_model.fit(X_pos)
        pos_scores = get_anomaly_scores(context_model, X_pos)
        score_percentiles = _score_percentiles_dict(pos_scores)
        context_classifier, classifier_info = classifier_trainer(
            X_pos,
            X_neg,
            pos_sample_sources=[sample_sources[idx] for idx in pos_idx],
            neg_sample_sources=[sample_sources[idx] for idx in neg_idx],
            minimum_negative_samples=minimum_negative_samples,
        )
        context_counts[context_name]["classifier_family"] = classifier_info.get("classifier_family")

        context_dir = _context_dir(model_dir, context_name)
        os.makedirs(context_dir, exist_ok=True)
        context_model_file = os.path.join(context_dir, "model.pkl")
        context_classifier_file = os.path.join(context_dir, "classifier.pkl")
        context_metadata_file = os.path.join(context_dir, "metadata.json")

        atomic_write_bytes(context_model_file, pickle.dumps(context_model, protocol=pickle.HIGHEST_PROTOCOL))
        save_model_hash(context_model_file)
        if context_classifier is not None:
            atomic_write_bytes(context_classifier_file, pickle.dumps(context_classifier, protocol=pickle.HIGHEST_PROTOCOL))
            save_classifier_sidecar(context_classifier_file)
        else:
            try:
                if os.path.exists(context_classifier_file):
                    os.remove(context_classifier_file)
            except OSError:
                pass
            remove_classifier_sidecar(context_classifier_file)

        context_metadata = dict(metadata_template)
        context_metadata.update(classifier_info)
        context_metadata["supervised_classifier_selection_version"] = challenger_selection_version
        context_metadata["classifier_family"] = classifier_info.get("classifier_family")
        context_metadata["supervised_candidates"] = dict((classifier_info.get("supervised_classifier") or {}).get("head_to_head") or {})
        context_metadata.update(
            {
                "bundle_role": "context_submodel",
                "routed_context": context_name,
                "model_status": metadata_template.get("model_status") or "pending_evaluation",
                "policy_version": metadata_template.get("policy_version"),
                "approval_reason": f"Context-specific submodel for {context_name} with global fallback.",
                "feature_names": list(feature_names),
                "score_percentiles": score_percentiles,
                "positive_window_samples": int(len(X_pos)),
                "negative_window_samples": int(len(X_neg)),
                "context_router_version": CONTEXT_ROUTING_VERSION,
                "context_router_min_confidence": float(CONTEXT_ROUTER_MIN_CONFIDENCE),
                "active_window_scales": [float(scale) for scale in active_window_scales],
                "context_support": dict(context_counts[context_name]),
                "artifacts": {
                    "model": "model.pkl",
                    "classifier": "classifier.pkl" if context_classifier is not None else None,
                    "metadata": "metadata.json",
                },
            }
        )
        atomic_write_text(context_metadata_file, json.dumps(context_metadata, indent=2, ensure_ascii=False))
        save_metadata_hash(context_metadata_file)

        bundles[context_name] = {
            "model": os.path.relpath(context_model_file, model_dir),
            "classifier": os.path.relpath(context_classifier_file, model_dir) if context_classifier is not None else None,
            "metadata": os.path.relpath(context_metadata_file, model_dir),
            "positive_window_samples": int(len(X_pos)),
            "negative_window_samples": int(len(X_neg)),
            "positive_session_count": int(len(pos_sessions)),
            "negative_session_count": int(len(neg_sessions)),
            "average_positive_router_confidence": round(avg_confidence, 6),
        }

    return {
        "enabled": bool(bundles),
        "version": CONTEXT_ROUTING_VERSION,
        "routing_mode": "window_level_rule_router",
        "global_fallback_enabled": True,
        "default_context": "global_fallback",
        "min_confidence": float(CONTEXT_ROUTER_MIN_CONFIDENCE),
        "available_contexts": list(ROUTER_CONTEXTS),
        "active_contexts": sorted(bundles.keys()),
        "context_sample_counts": context_counts,
        "bundles": bundles,
    }


__all__ = [
    "CONTEXT_SELECTION_VERSION",
    "_context_dir",
    "train_context_submodels",
]
