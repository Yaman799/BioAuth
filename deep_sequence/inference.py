from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, Mapping, Sequence

import numpy as np

from artifact_integrity import SecurityError, load_sequence_model_artifact
from deep_runtime import DEFAULT_SEQUENCE_LENGTH
from .models import TORCH_AVAILABLE, KeyboardBiGruCnnAttention, MouseResNetGruVerifier, SequenceCnnLstm, _torch_runtime
from .tensorization import build_keyboard_sequence_tensor, build_mouse_sequence_tensor, session_order_sort_key


class SequenceRuntimeBuffer:
    def __init__(self, *, feature_names: Sequence[str], sequence_length: int = DEFAULT_SEQUENCE_LENGTH) -> None:
        self.feature_names = [str(name) for name in list(feature_names or []) if str(name or '').strip()]
        self.sequence_length = max(2, int(sequence_length or DEFAULT_SEQUENCE_LENGTH))
        self._rows = []

    def push_many(self, samples: Sequence[Mapping[str, Any]]) -> None:
        ordered = sorted((dict(sample or {}) for sample in list(samples or [])), key=session_order_sort_key)
        self._rows = [[_safe_float(sample.get(name), 0.0) for name in self.feature_names] for sample in ordered]

    @property
    def size(self) -> int:
        return len(self._rows)

    def latest_tensor(self) -> np.ndarray | None:
        if len(self._rows) < self.sequence_length or not self.feature_names:
            return None
        arr = np.asarray(self._rows[-self.sequence_length:], dtype=np.float32)
        return arr[None, :, :] if arr.ndim == 2 else None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        return float(default)
    return float(number) if np.isfinite(number) else float(default)


@lru_cache(maxsize=4)
def _cached_sequence_payload(artifact_path: str, size: int, mtime_ns: int) -> Dict[str, Any]:
    return load_sequence_model_artifact(artifact_path)


@lru_cache(maxsize=4)
def _cached_loaded_runtime_model(artifact_path: str, size: int, mtime_ns: int, feature_dim: int) -> Dict[str, Any]:
    payload = _cached_sequence_payload(artifact_path, int(size), int(mtime_ns))
    model = SequenceCnnLstm(feature_dim=int(feature_dim))
    model.load_state_dict(payload.get('state_dict') or {})
    model.eval()
    return {'payload': payload, 'model': model}


def _validate_runtime_metadata(meta: Mapping[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(meta, Mapping):
        return False, 'metadata_invalid'
    if 'deep_runtime' not in meta:
        return False, 'metadata_invalid:deep_runtime_contract'
    deep_runtime = meta.get('deep_runtime') or {}
    if not isinstance(deep_runtime, Mapping):
        return False, 'metadata_invalid:deep_runtime_contract'
    if 'sequence_model' not in deep_runtime:
        return False, 'metadata_invalid:sequence_model_contract'
    sequence_model = deep_runtime.get('sequence_model') or {}
    if not isinstance(sequence_model, Mapping):
        return False, 'metadata_invalid:sequence_model_contract'
    return True, 'ok'


def _artifact_path(metadata_file: str, meta: Mapping[str, Any]) -> str | None:
    artifacts = dict((meta or {}).get('artifacts') or {}) if isinstance(meta, Mapping) else {}
    deep_runtime = dict((meta or {}).get('deep_runtime') or {}) if isinstance(meta, Mapping) else {}
    sequence_model = dict(deep_runtime.get('sequence_model') or {})
    candidate = str(sequence_model.get('artifact') or artifacts.get('sequence_model') or '').strip()
    if not candidate:
        return None
    return candidate if os.path.isabs(candidate) else os.path.join(os.path.dirname(os.path.abspath(metadata_file)), candidate)


def load_runtime_sequence_model(*, metadata_file: str, meta: Mapping[str, Any], runtime_state: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    state = dict(runtime_state or {})
    metadata_ok, metadata_reason = _validate_runtime_metadata(meta)
    deep_runtime = dict((meta or {}).get('deep_runtime') or {}) if isinstance(meta, Mapping) else {}
    sequence_model = dict(deep_runtime.get('sequence_model') or {}) if isinstance(deep_runtime, Mapping) else {}
    result = {'available': False, 'loaded': False, 'backend': None, 'artifact_path': None, 'artifact_file': None, 'reason': 'classic_mode', 'shadow_only': bool(deep_runtime.get('runtime_shadow_only', True))}
    if str(state.get('desired_mode') or state.get('requested_mode') or 'classic') == 'classic' and str(state.get('effective_mode') or 'classic') == 'classic':
        return result
    if not metadata_ok:
        result['reason'] = metadata_reason
        return result
    if not bool(deep_runtime.get('deep_sequence_runtime_enabled')):
        result['reason'] = str(deep_runtime.get('runtime_activation_blocked_reason') or 'deep_runtime_disabled')
        return result
    if not bool(sequence_model.get('enabled')):
        result['reason'] = 'sequence_contract_disabled'
        return result
    artifact_path = _artifact_path(metadata_file, meta)
    result['artifact_path'] = artifact_path
    result['artifact_file'] = os.path.basename(artifact_path) if artifact_path else None
    if not artifact_path or not os.path.exists(artifact_path):
        result['reason'] = 'sequence_artifact_missing'
        return result
    if str(state.get('effective_mode') or 'classic') == 'hybrid_accelerated':
        result['reason'] = 'accelerated_backend_unavailable_for_pytorch_artifact'
        return result
    if not TORCH_AVAILABLE:
        result['reason'] = 'pytorch_unavailable'
        return result
    try:
        resolved_artifact_path = os.path.realpath(os.path.abspath(artifact_path))
        stat = os.stat(resolved_artifact_path)
        size = int(stat.st_size)
        mtime_ns = int(getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1e9)))
        payload = _cached_sequence_payload(resolved_artifact_path, size, mtime_ns)
        model_config = dict(payload.get('model_config') or {})
        try:
            feature_dim = int(model_config.get('feature_dim') or 0)
        except Exception:
            feature_dim = 0
        if feature_dim <= 0:
            feature_dim = max(1, len(list(payload.get('feature_names') or [])))
        loaded = _cached_loaded_runtime_model(resolved_artifact_path, size, mtime_ns, feature_dim)
    except SecurityError as exc:
        result['reason'] = f'sequence_artifact_invalid:{exc}'
        return result
    except Exception as exc:
        result['reason'] = f'sequence_runtime_model_load_failed:{exc}'
        return result
    result.update({
        'available': True,
        'loaded': True,
        'backend': 'pytorch_cpu',
        'artifact_path': resolved_artifact_path,
        'artifact_file': os.path.basename(resolved_artifact_path),
        'payload': loaded.get('payload') or payload,
        'model': loaded.get('model'),
        'reason': 'ok',
    })
    return result


def _predict_probability(runtime_model: Mapping[str, Any], tensor: np.ndarray) -> float:
    if not TORCH_AVAILABLE:
        raise RuntimeError('PyTorch unavailable')
    torch, _nn = _torch_runtime()
    model = runtime_model.get('model') if isinstance(runtime_model, Mapping) else None
    if model is None:
        raise RuntimeError('sequence_runtime_model_not_loaded')
    with torch.no_grad():
        logits = model(torch.from_numpy(np.asarray(tensor, dtype=np.float32)))
        probs = torch.sigmoid(logits).cpu().numpy().reshape(-1)
    return float(probs[0]) if probs.size else 0.0


def run_shadow_sequence_scoring(*, window_samples: Sequence[Mapping[str, Any]], metadata_file: str, meta: Mapping[str, Any], runtime_state: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    runtime_model = load_runtime_sequence_model(metadata_file=metadata_file, meta=meta, runtime_state=runtime_state)
    response = {'attempted': True, 'available': bool(runtime_model.get('available')), 'loaded': bool(runtime_model.get('loaded')), 'used': False, 'probability': None, 'risk': None, 'reason': str(runtime_model.get('reason') or 'unknown'), 'backend': runtime_model.get('backend'), 'artifact_file': runtime_model.get('artifact_file'), 'sequence_length': None, 'buffer_size': 0, 'shadow_only': bool(runtime_model.get('shadow_only', True))}
    if not runtime_model.get('loaded'):
        return response
    payload = dict(runtime_model.get('payload') or {})
    feature_names = list(payload.get('feature_names') or [])
    seq_len = int(((payload.get('model_config') or {}).get('sequence_length') or DEFAULT_SEQUENCE_LENGTH))
    response['sequence_length'] = seq_len
    buffer = SequenceRuntimeBuffer(feature_names=feature_names, sequence_length=seq_len)
    buffer.push_many(window_samples)
    response['buffer_size'] = buffer.size
    tensor = buffer.latest_tensor()
    if tensor is None:
        response['reason'] = 'insufficient_sequence_buffer'
        return response
    try:
        probability = _predict_probability(runtime_model, tensor)
    except Exception as exc:
        response['reason'] = f'sequence_inference_failed:{exc}'
        return response
    response.update({'used': True, 'probability': round(float(probability), 6), 'risk': int(round(float(probability) * 100.0)), 'reason': 'ok'})
    return response


def _experimental_deep_abstain(*, modality: str, architecture: str, reason: str, feature_names: Sequence[str] | None = None, sequence_length: int | None = None, buffer_size: int = 0) -> Dict[str, Any]:
    return {
        "available": False,
        "used": False,
        "status": "unavailable",
        "decision": "abstain",
        "risk": None,
        "score": None,
        "probability": None,
        "reason": str(reason or "unavailable"),
        "reason_codes": [str(reason or "unavailable")],
        "architecture": str(architecture),
        "modality": str(modality),
        "feature_names": [str(name) for name in list(feature_names or [])],
        "sequence_length": int(sequence_length or 0),
        "buffer_size": int(buffer_size or 0),
        "experimental": True,
        "runtime_authoritative": False,
        "can_lock_alone": False,
        "can_influence_device": False,
        "fusion_weight": 0.0,
    }


def _experimental_probability(model: Any, tensor: np.ndarray) -> float:
    if not TORCH_AVAILABLE:
        raise RuntimeError("pytorch_unavailable")
    torch, _nn = _torch_runtime()
    model.eval()
    with torch.no_grad():
        logits = model(torch.from_numpy(np.asarray(tensor, dtype=np.float32)))
        probs = torch.sigmoid(logits).cpu().numpy().reshape(-1)
    return float(probs[0]) if probs.size else 0.0


def run_experimental_keyboard_verifier(*, window_samples: Sequence[Mapping[str, Any]], feature_names: Sequence[str] | None = None, sequence_length: int = DEFAULT_SEQUENCE_LENGTH) -> Dict[str, Any]:
    payload = build_keyboard_sequence_tensor(window_samples, feature_names=feature_names, sequence_length=sequence_length)
    if not payload.get("available"):
        return _experimental_deep_abstain(
            modality="keyboard", architecture="keyboard_bigru_cnn_attention", reason=str(payload.get("reason") or "unavailable"),
            feature_names=payload.get("feature_names") or feature_names, sequence_length=int(payload.get("sequence_length") or sequence_length), buffer_size=int(payload.get("buffer_size") or 0),
        )
    if not TORCH_AVAILABLE:
        return _experimental_deep_abstain(modality="keyboard", architecture="keyboard_bigru_cnn_attention", reason="pytorch_unavailable", feature_names=payload.get("feature_names"), sequence_length=int(payload.get("sequence_length") or sequence_length), buffer_size=int(payload.get("buffer_size") or 0))
    try:
        model = KeyboardBiGruCnnAttention(feature_dim=int(payload.get("feature_count") or 1))
        probability = _experimental_probability(model, payload["tensor"])
    except Exception as exc:
        return _experimental_deep_abstain(modality="keyboard", architecture="keyboard_bigru_cnn_attention", reason=f"experimental_keyboard_inference_failed:{exc}", feature_names=payload.get("feature_names"), sequence_length=int(payload.get("sequence_length") or sequence_length), buffer_size=int(payload.get("buffer_size") or 0))
    return {
        "available": True, "used": True, "status": "experimental_shadow_only", "decision": "scored",
        "risk": round(float(probability) * 100.0, 6), "score": round(float(probability), 6), "probability": round(float(probability), 6),
        "reason": "ok", "reason_codes": ["experimental_shadow_only", "no_single_model_lock"],
        "architecture": "keyboard_bigru_cnn_attention", "modality": "keyboard",
        "feature_names": list(payload.get("feature_names") or []), "sequence_length": int(payload.get("sequence_length") or sequence_length),
        "buffer_size": int(payload.get("buffer_size") or 0), "experimental": True, "runtime_authoritative": False,
        "can_lock_alone": False, "can_influence_device": False, "fusion_weight": 0.0,
    }


def run_experimental_mouse_verifier(*, window_samples: Sequence[Mapping[str, Any]], feature_names: Sequence[str] | None = None, sequence_length: int = DEFAULT_SEQUENCE_LENGTH) -> Dict[str, Any]:
    payload = build_mouse_sequence_tensor(window_samples, feature_names=feature_names, sequence_length=sequence_length)
    if not payload.get("available"):
        return _experimental_deep_abstain(
            modality="mouse", architecture="mouse_resnet_gru", reason=str(payload.get("reason") or "unavailable"),
            feature_names=payload.get("feature_names") or feature_names, sequence_length=int(payload.get("sequence_length") or sequence_length), buffer_size=int(payload.get("buffer_size") or 0),
        )
    if not TORCH_AVAILABLE:
        return _experimental_deep_abstain(modality="mouse", architecture="mouse_resnet_gru", reason="pytorch_unavailable", feature_names=payload.get("feature_names"), sequence_length=int(payload.get("sequence_length") or sequence_length), buffer_size=int(payload.get("buffer_size") or 0))
    try:
        model = MouseResNetGruVerifier(feature_dim=int(payload.get("feature_count") or 1))
        probability = _experimental_probability(model, payload["tensor"])
    except Exception as exc:
        return _experimental_deep_abstain(modality="mouse", architecture="mouse_resnet_gru", reason=f"experimental_mouse_inference_failed:{exc}", feature_names=payload.get("feature_names"), sequence_length=int(payload.get("sequence_length") or sequence_length), buffer_size=int(payload.get("buffer_size") or 0))
    return {
        "available": True, "used": True, "status": "experimental_shadow_only", "decision": "scored",
        "risk": round(float(probability) * 100.0, 6), "score": round(float(probability), 6), "probability": round(float(probability), 6),
        "reason": "ok", "reason_codes": ["experimental_shadow_only", "no_single_model_lock"],
        "architecture": "mouse_resnet_gru", "modality": "mouse",
        "feature_names": list(payload.get("feature_names") or []), "sequence_length": int(payload.get("sequence_length") or sequence_length),
        "buffer_size": int(payload.get("buffer_size") or 0), "experimental": True, "runtime_authoritative": False,
        "can_lock_alone": False, "can_influence_device": False, "fusion_weight": 0.0,
    }
