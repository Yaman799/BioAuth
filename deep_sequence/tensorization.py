from __future__ import annotations
from collections import OrderedDict
from typing import Any, Dict, Mapping, Sequence
import numpy as np
SEQUENCE_DATA_VERSION = 'cnn-lstm-sequence-v1'
SEQUENCE_TENSOR_LAYOUT = 'NTF'
SEQUENCE_ORDER_KEYS = ('sequence_window_index', 'window_start_offset', 'transition_window_index', 'window_end_offset')
def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        return float(default)
    return float(number) if np.isfinite(number) else float(default)

def session_order_sort_key(sample: Mapping[str, Any]) -> tuple[float, float, float, float]:
    payload = dict(sample or {})
    return tuple(_safe_float(payload.get(name), default=float(index)) for index, name in enumerate(SEQUENCE_ORDER_KEYS))

def _normalize_feature_names(feature_names: Sequence[str]) -> list[str]:
    seen = set(); ordered=[]
    for feature_name in feature_names:
        normalized = str(feature_name or '').strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized); ordered.append(normalized)
    return ordered

def _session_sample_matrix(samples: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> np.ndarray:
    ordered_features = _normalize_feature_names(feature_names)
    ordered_samples = sorted((dict(sample or {}) for sample in samples), key=session_order_sort_key)
    rows = [[_safe_float(sample.get(feature_name), 0.0) for feature_name in ordered_features] for sample in ordered_samples]
    return np.asarray(rows, dtype=np.float32) if rows else np.zeros((0, len(ordered_features)), dtype=np.float32)

def build_sequence_dataset_from_session_samples(session_samples: Mapping[str, Sequence[Mapping[str, Any]]], feature_names: Sequence[str], labels_by_session: Mapping[str, Any], *, sequence_length: int, stride: int = 1, drop_incomplete: bool = True) -> Dict[str, Any]:
    ordered_features = _normalize_feature_names(feature_names)
    seq_len = max(2, int(sequence_length or 2))
    step = max(1, int(stride or 1))
    X_parts=[]; y_parts=[]; sequence_session_ids=[]; sequence_start_indices=[]; session_sequence_counts={}; skipped_sessions=[]
    for session_id, raw_samples in OrderedDict((str(key), list(value or [])) for key, value in dict(session_samples or {}).items()).items():
        matrix = _session_sample_matrix(raw_samples, ordered_features)
        count = int(matrix.shape[0])
        if count < seq_len:
            session_sequence_counts[session_id]=0
            if count <= 0 or drop_incomplete:
                skipped_sessions.append(session_id); continue
        if count < seq_len and not drop_incomplete:
            padded = np.zeros((seq_len, len(ordered_features)), dtype=np.float32)
            padded[-count:, :] = matrix
            matrix = padded; count = seq_len
        session_count = 0
        for start_idx in range(0, count - seq_len + 1, step):
            X_parts.append(matrix[start_idx:start_idx+seq_len][None, :, :])
            y_parts.append(int(labels_by_session.get(session_id, 0) or 0))
            sequence_session_ids.append(session_id); sequence_start_indices.append(int(start_idx)); session_count += 1
        session_sequence_counts[session_id] = session_count
        if session_count <= 0:
            skipped_sessions.append(session_id)
    X = np.concatenate(X_parts, axis=0).astype(np.float32, copy=False) if X_parts else np.zeros((0, seq_len, len(ordered_features)), dtype=np.float32)
    y = np.asarray(y_parts, dtype=np.int64)
    return {'version': SEQUENCE_DATA_VERSION, 'tensor_layout': SEQUENCE_TENSOR_LAYOUT, 'feature_names': ordered_features, 'feature_count': int(len(ordered_features)), 'sequence_length': int(seq_len), 'stride': int(step), 'X': X, 'y': y, 'sequence_session_ids': sequence_session_ids, 'sequence_start_indices': sequence_start_indices, 'session_sequence_counts': session_sequence_counts, 'session_count': int(len(session_sequence_counts)), 'sequence_count': int(X.shape[0]), 'skipped_sessions': skipped_sessions, 'ordering_keys': list(SEQUENCE_ORDER_KEYS), 'shape': [int(value) for value in X.shape]}


KEYBOARD_SEQUENCE_FEATURE_CANDIDATES = (
    "key_hold_mean", "key_hold_std", "flight_mean", "flight_std", "keys_per_second",
    "backspace_rate", "typing_burst_rate", "digraph_latency_mean",
    "kb_event_count", "session_kb_share",
)
MOUSE_SEQUENCE_FEATURE_CANDIDATES = (
    "dx", "dy", "distance", "velocity", "acceleration", "angle_change",
    "click_state", "scroll_delta", "drag_state", "mouse_event_count", "session_ms_share",
)
DEEP_VERIFIER_TENSOR_SCHEMA_VERSION = "phase8-deep-verifier-tensor-v1"


def infer_modality_feature_names(samples: Sequence[Mapping[str, Any]], *, modality: str) -> list[str]:
    """Infer a stable feature list for keyboard-only or mouse-only verifier tensors.

    The helper is conservative: it only selects known modality-specific candidates
    that are present in the supplied samples, preserving candidate order. It does
    not infer readiness or production eligibility.
    """

    candidates = KEYBOARD_SEQUENCE_FEATURE_CANDIDATES if str(modality) == "keyboard" else MOUSE_SEQUENCE_FEATURE_CANDIDATES
    available: set[str] = set()
    for sample in samples or []:
        if isinstance(sample, Mapping):
            available.update(str(key) for key in sample.keys())
    return [name for name in candidates if name in available]


def build_modality_sequence_tensor(samples: Sequence[Mapping[str, Any]], *, feature_names: Sequence[str] | None = None, modality: str, sequence_length: int, min_sequence_length: int | None = None) -> Dict[str, Any]:
    """Build one latest NTF tensor for a modality verifier or return abstain metadata.

    Missing/short sequences are represented as safe unavailable/abstain payloads
    instead of exceptions so runtime callers can fail closed to classic behavior.
    """

    seq_len = max(2, int(sequence_length or 2))
    min_len = max(2, int(min_sequence_length or seq_len))
    raw_samples = [dict(sample or {}) for sample in list(samples or []) if isinstance(sample, Mapping)]
    selected_features = _normalize_feature_names(feature_names or infer_modality_feature_names(raw_samples, modality=modality))
    if not selected_features:
        return {
            "available": False, "status": "unavailable", "decision": "abstain",
            "reason": "missing_modality_features", "reason_codes": ["missing_modality_features"],
            "modality": str(modality), "feature_names": [], "feature_count": 0,
            "sequence_length": seq_len, "buffer_size": int(len(raw_samples)), "tensor": None,
            "fusion_weight": 0.0, "can_lock_alone": False, "schema_version": DEEP_VERIFIER_TENSOR_SCHEMA_VERSION,
        }
    matrix = _session_sample_matrix(raw_samples, selected_features)
    if int(matrix.shape[0]) < min_len:
        return {
            "available": False, "status": "unavailable", "decision": "abstain",
            "reason": "sequence_too_short", "reason_codes": ["sequence_too_short"],
            "modality": str(modality), "feature_names": selected_features, "feature_count": int(len(selected_features)),
            "sequence_length": seq_len, "buffer_size": int(matrix.shape[0]), "tensor": None,
            "fusion_weight": 0.0, "can_lock_alone": False, "schema_version": DEEP_VERIFIER_TENSOR_SCHEMA_VERSION,
        }
    tensor = matrix[-seq_len:, :][None, :, :].astype(np.float32, copy=False)
    return {
        "available": True, "status": "available", "decision": "ready_for_experimental_scoring",
        "reason": "ok", "reason_codes": ["ok"], "modality": str(modality),
        "feature_names": selected_features, "feature_count": int(len(selected_features)),
        "sequence_length": seq_len, "buffer_size": int(matrix.shape[0]), "tensor": tensor,
        "shape": [int(value) for value in tensor.shape], "fusion_weight": 0.0,
        "can_lock_alone": False, "schema_version": DEEP_VERIFIER_TENSOR_SCHEMA_VERSION,
    }


def build_keyboard_sequence_tensor(samples: Sequence[Mapping[str, Any]], *, feature_names: Sequence[str] | None = None, sequence_length: int, min_sequence_length: int | None = None) -> Dict[str, Any]:
    return build_modality_sequence_tensor(samples, feature_names=feature_names, modality="keyboard", sequence_length=sequence_length, min_sequence_length=min_sequence_length)


def build_mouse_sequence_tensor(samples: Sequence[Mapping[str, Any]], *, feature_names: Sequence[str] | None = None, sequence_length: int, min_sequence_length: int | None = None) -> Dict[str, Any]:
    return build_modality_sequence_tensor(samples, feature_names=feature_names, modality="mouse", sequence_length=sequence_length, min_sequence_length=min_sequence_length)
