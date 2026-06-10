from __future__ import annotations

import importlib.util
import math
import os
import platform
import time
import tracemalloc
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

import numpy as np

DEEP_RUNTIME_CONTRACT_VERSION = "deep-runtime-v1"
DEEP_RUNTIME_DEFAULT_MODE = "auto"
DEEP_RUNTIME_FALLBACK_MODE = "classic"
DEEP_RUNTIME_MODES = ("classic", "hybrid", "auto", "hybrid_accelerated")
DEEP_RUNTIME_FALLBACK_REASONS = (
    "ok",
    "classic_requested",
    "benchmark_not_run",
    "deep_runtime_not_available_yet",
    "accelerated_backend_unavailable",
    "backend_import_failed",
    "model_unavailable",
)
DEEP_RUNTIME_FALLBACK_REASON_TEXT = {
    "ok": "Enhanced runtime is active.",
    "classic_requested": "Core protection is selected. Enhanced runtime is not requested.",
    "benchmark_not_run": "Enhanced runtime is waiting for a local device check. Core protection remains active.",
    "deep_runtime_not_available_yet": "Enhanced runtime is not available in this build yet. Core protection remains active.",
    "accelerated_backend_unavailable": "The faster enhanced backend is not available on this device. Core protection remains active.",
    "backend_import_failed": "Enhanced runtime could not load its optional backend. Core protection remains active.",
    "model_unavailable": "Enhanced runtime model files are not available. Core protection remains active.",
}
DEEP_RUNTIME_BENCHMARK_VERSION = "device-benchmark-v1"
DEEP_RUNTIME_LATENCY_TARGETS_MS = {
    "hybrid_accelerated": 14.0,
    "hybrid": 28.0,
    "classic": 45.0,
}
DEFAULT_SEQUENCE_MODEL_FAMILY = "cnn_lstm"
DEFAULT_SEQUENCE_LENGTH = 4
DEFAULT_TENSOR_LAYOUT = "NTF"
DEFAULT_LATENCY_BUDGET_MS = 35.0


@dataclass(frozen=True)
class _BackendCandidate:
    name: str
    available: bool
    accelerated: bool


def normalize_deep_runtime_mode(value: Any, *, default: str = DEEP_RUNTIME_DEFAULT_MODE) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "": default,
        "default": default,
        "automatic": "auto",
        "auto_mode": "auto",
        "legacy": "classic",
        "baseline": "classic",
        "classic_only": "classic",
        "hybridaccelerated": "hybrid_accelerated",
        "accelerated": "hybrid_accelerated",
        "accelerated_hybrid": "hybrid_accelerated",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in DEEP_RUNTIME_MODES else default


def supported_deep_runtime_modes() -> list[str]:
    return list(DEEP_RUNTIME_MODES)


def normalize_deep_runtime_fallback_reason(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "": "ok",
        "none": "ok",
        "ready": "ok",
        "success": "ok",
        "not_run": "benchmark_not_run",
        "benchmark_missing": "benchmark_not_run",
        "classic": "classic_requested",
        "classic_only": "classic_requested",
        "runtime_not_ready": "deep_runtime_not_available_yet",
        "runtime_unavailable": "deep_runtime_not_available_yet",
        "backend_unavailable": "accelerated_backend_unavailable",
        "accelerated_unavailable": "accelerated_backend_unavailable",
        "backend_failed": "backend_import_failed",
        "import_failed": "backend_import_failed",
        "missing_model": "model_unavailable",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in DEEP_RUNTIME_FALLBACK_REASONS else "deep_runtime_not_available_yet"


def deep_runtime_is_fallback(reason: Any) -> bool:
    return normalize_deep_runtime_fallback_reason(reason) not in {"ok", "classic_requested"}


def deep_runtime_fallback_reason_text(reason: Any) -> str:
    normalized = normalize_deep_runtime_fallback_reason(reason)
    return DEEP_RUNTIME_FALLBACK_REASON_TEXT.get(normalized, DEEP_RUNTIME_FALLBACK_REASON_TEXT["deep_runtime_not_available_yet"])


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def detect_backend_inventory() -> Dict[str, Any]:
    candidates = (
        _BackendCandidate(name="openvino", available=_module_available("openvino"), accelerated=True),
        _BackendCandidate(name="onnxruntime_cpu", available=_module_available("onnxruntime"), accelerated=True),
        _BackendCandidate(name="numpy_proxy", available=True, accelerated=False),
    )
    available = [candidate.name for candidate in candidates if candidate.available]
    preferred = next((candidate.name for candidate in candidates if candidate.available), "classic")
    accelerated_available = any(candidate.available and candidate.accelerated for candidate in candidates)
    return {
        "preferred_backend": preferred,
        "available_backends": available,
        "accelerated_available": bool(accelerated_available),
        "onnxruntime_available": _module_available("onnxruntime"),
        "openvino_available": _module_available("openvino"),
    }


def _physical_memory_bytes() -> Optional[int]:
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except Exception:
            return None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        return int(page_size) * int(pages)
    except Exception:
        return None


def _memory_gib() -> Optional[float]:
    total = _physical_memory_bytes()
    if total is None or total <= 0:
        return None
    return float(total) / float(1024 ** 3)


def default_benchmark_record() -> Dict[str, Any]:
    inventory = detect_backend_inventory()
    return {
        "version": DEEP_RUNTIME_BENCHMARK_VERSION,
        "status": "not_run",
        "recommended_mode": DEEP_RUNTIME_FALLBACK_MODE,
        "recommended_backend": "classic",
        "effective_mode": DEEP_RUNTIME_FALLBACK_MODE,
        "fallback_reason": "benchmark_not_run",
        "latency": {},
        "memory_delta_mb": 0.0,
        "cpu_time_ratio": 0.0,
        "cpu_count": int(os.cpu_count() or 1),
        "total_memory_gib": _memory_gib(),
        "backend_inventory": inventory,
        "notes": ["Benchmark not executed yet."],
    }


def _float_or_default(value: Any, default: float) -> float:
    try:
        number = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return float(number)


def _classify_recommendation(*, latency_p95_ms: float, memory_gib: Optional[float], cpu_count: int, backend_inventory: Mapping[str, Any]) -> tuple[str, str, list[str]]:
    notes: list[str] = []
    accelerated_available = bool(backend_inventory.get("accelerated_available"))
    memory_ok_for_hybrid = memory_gib is None or memory_gib >= 8.0
    memory_ok_for_accel = memory_gib is None or memory_gib >= 12.0

    if accelerated_available and cpu_count >= 8 and memory_ok_for_accel and latency_p95_ms <= DEEP_RUNTIME_LATENCY_TARGETS_MS["hybrid_accelerated"]:
        notes.append("Device benchmark meets the accelerated Hybrid budget.")
        preferred_backend = str(backend_inventory.get("preferred_backend") or "onnxruntime_cpu")
        return "hybrid_accelerated", preferred_backend, notes
    if cpu_count >= 6 and memory_ok_for_hybrid and latency_p95_ms <= DEEP_RUNTIME_LATENCY_TARGETS_MS["hybrid"]:
        notes.append("Device benchmark meets the standard Hybrid budget.")
        return "hybrid", "classic", notes
    notes.append("Device benchmark stays on the Classic path to preserve runtime stability.")
    return "classic", "classic", notes


def run_local_device_benchmark(*, sequence_length: int = DEFAULT_SEQUENCE_LENGTH, feature_dim: int = 96, warmup_passes: int = 2, benchmark_passes: int = 7, seed: int = 13) -> Dict[str, Any]:
    backend_inventory = detect_backend_inventory()
    cpu_count = int(os.cpu_count() or 1)
    memory_gib = _memory_gib()
    rng = np.random.default_rng(seed)

    features = rng.standard_normal((24, int(max(2, sequence_length)), int(max(16, feature_dim))), dtype=np.float32)
    w1 = rng.standard_normal((features.shape[-1], 64), dtype=np.float32)
    w2 = rng.standard_normal((64, 32), dtype=np.float32)
    recurrent = rng.standard_normal((32, 32), dtype=np.float32)

    def _single_pass() -> float:
        started = time.perf_counter()
        hidden = np.zeros((features.shape[0], 32), dtype=np.float32)
        conv_like = np.maximum(features @ w1, 0.0)
        for step in range(conv_like.shape[1]):
            hidden = np.tanh((conv_like[:, step, :] @ w2) + (hidden @ recurrent))
        _ = hidden.mean(axis=0)
        return (time.perf_counter() - started) * 1000.0

    init_started = time.perf_counter()
    tracemalloc.start()
    proc_started = time.process_time()
    try:
        for _ in range(max(1, int(warmup_passes))):
            _single_pass()
        latencies_ms = [_single_pass() for _ in range(max(3, int(benchmark_passes)))]
        current_mem, peak_mem = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    init_ms = (time.perf_counter() - init_started) * 1000.0
    proc_elapsed = max(0.0, time.process_time() - proc_started)
    wall_elapsed = max(1e-6, init_ms / 1000.0)
    cpu_time_ratio = float(max(0.0, min(4.0, proc_elapsed / wall_elapsed)))

    latency_p50 = float(np.percentile(latencies_ms, 50))
    latency_p95 = float(np.percentile(latencies_ms, 95))
    recommended_mode, recommended_backend, notes = _classify_recommendation(
        latency_p95_ms=latency_p95,
        memory_gib=memory_gib,
        cpu_count=cpu_count,
        backend_inventory=backend_inventory,
    )

    return {
        "version": DEEP_RUNTIME_BENCHMARK_VERSION,
        "status": "ok",
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": cpu_count,
        "total_memory_gib": round(memory_gib, 2) if memory_gib is not None else None,
        "backend_inventory": backend_inventory,
        "startup_ms": round(init_ms, 3),
        "latency": {
            "p50_ms": round(latency_p50, 3),
            "p95_ms": round(latency_p95, 3),
            "samples_ms": [round(float(value), 3) for value in latencies_ms],
        },
        "memory_delta_mb": round(float(max(current_mem, peak_mem)) / float(1024 ** 2), 3),
        "cpu_time_ratio": round(cpu_time_ratio, 3),
        "sequence_length": int(max(2, sequence_length)),
        "feature_dim": int(max(16, feature_dim)),
        "recommended_mode": recommended_mode,
        "recommended_backend": recommended_backend,
        "effective_mode": DEEP_RUNTIME_FALLBACK_MODE,
        "fallback_reason": "deep_runtime_not_available_yet",
        "notes": notes,
    }


def build_deep_runtime_metadata_contract(*, sequence_length: int = DEFAULT_SEQUENCE_LENGTH, latency_budget_ms: float = DEFAULT_LATENCY_BUDGET_MS) -> Dict[str, Any]:
    return {
        "contract_version": DEEP_RUNTIME_CONTRACT_VERSION,
        "supported_modes": supported_deep_runtime_modes(),
        "default_mode": DEEP_RUNTIME_DEFAULT_MODE,
        "fallback_mode": DEEP_RUNTIME_FALLBACK_MODE,
        "latency_budget_ms": float(latency_budget_ms),
        "auto_benchmark_required": True,
        "manual_override_supported": True,
        "selected_backend": "classic",
        "recommended_backend": "classic",
        "benchmark_profile_required_for_hybrid": True,
        "deep_sequence_runtime_enabled": False,
        "effective_mode": DEEP_RUNTIME_FALLBACK_MODE,
        "fallback_reason": "deep_runtime_not_available_yet",
        "sequence_model": {
            "planned_family": DEFAULT_SEQUENCE_MODEL_FAMILY,
            "enabled": False,
            "artifact": None,
            "framework": None,
            "sequence_length": int(max(2, sequence_length)),
            "tensor_layout": DEFAULT_TENSOR_LAYOUT,
            "status": "reserved_for_future_phase",
        },
        "experimental_deep_verifiers": {
            "schema_version": "phase8-deep-verifier-metadata-v1",
            "score_direction": "higher_score_more_suspicious",
            "runtime_authoritative": False,
            "can_lock_alone": False,
            "can_influence_device": False,
            "threshold_source": "not_calibrated",
            "verifiers": {
                "keyboard": {
                    "architecture": "keyboard_bigru_cnn_attention",
                    "input_modality": "keyboard",
                    "enabled": False,
                    "experimental": True,
                    "status": "experimental_shadow_only",
                    "sequence_length": int(max(2, sequence_length)),
                    "tensor_layout": DEFAULT_TENSOR_LAYOUT,
                },
                "mouse": {
                    "architecture": "mouse_resnet_gru",
                    "input_modality": "mouse",
                    "enabled": False,
                    "experimental": True,
                    "status": "experimental_shadow_only",
                    "sequence_length": int(max(2, sequence_length)),
                    "tensor_layout": DEFAULT_TENSOR_LAYOUT,
                },
                "type2branch_candidate": {
                    "architecture": "type2branch_inspired",
                    "input_modality": "keyboard",
                    "enabled": False,
                    "experimental": True,
                    "status": "future_candidate_disabled",
                },
                "typeformer_candidate": {
                    "architecture": "typeformer_inspired",
                    "input_modality": "keyboard_free_text",
                    "enabled": False,
                    "experimental": True,
                    "status": "future_candidate_disabled",
                },
            },
        },
    }


def normalize_benchmark_record(data: Any) -> Dict[str, Any]:
    base = default_benchmark_record()
    if not isinstance(data, Mapping):
        return base
    merged = dict(base)
    merged.update(dict(data))
    merged["recommended_mode"] = normalize_deep_runtime_mode(merged.get("recommended_mode"), default=DEEP_RUNTIME_FALLBACK_MODE)
    merged["effective_mode"] = normalize_deep_runtime_mode(merged.get("effective_mode"), default=DEEP_RUNTIME_FALLBACK_MODE)
    backend_inventory = dict(base.get("backend_inventory") or {})
    if isinstance(data.get("backend_inventory"), Mapping):
        backend_inventory.update(dict(data.get("backend_inventory") or {}))
    merged["backend_inventory"] = backend_inventory
    merged["recommended_backend"] = str(merged.get("recommended_backend") or "classic")
    merged["fallback_reason"] = normalize_deep_runtime_fallback_reason(merged.get("fallback_reason"))
    merged["fallbackReason"] = merged["fallback_reason"]
    merged["fallback_reason_text"] = deep_runtime_fallback_reason_text(merged.get("fallback_reason"))
    merged["fallbackReasonText"] = merged["fallback_reason_text"]
    merged["is_fallback"] = deep_runtime_is_fallback(merged.get("fallback_reason"))
    merged["isFallback"] = merged["is_fallback"]
    latency = dict(merged.get("latency") or {})
    merged["latency"] = {
        "p50_ms": round(_float_or_default(latency.get("p50_ms"), 0.0), 3),
        "p95_ms": round(_float_or_default(latency.get("p95_ms"), 0.0), 3),
        "samples_ms": [round(_float_or_default(value, 0.0), 3) for value in list(latency.get("samples_ms") or [])[:16]],
    }
    merged["cpu_count"] = int(max(1, int(merged.get("cpu_count") or 1)))
    total_memory = merged.get("total_memory_gib")
    merged["total_memory_gib"] = round(_float_or_default(total_memory, 0.0), 2) if total_memory not in (None, "") else None
    merged["memory_delta_mb"] = round(_float_or_default(merged.get("memory_delta_mb"), 0.0), 3)
    merged["cpu_time_ratio"] = round(_float_or_default(merged.get("cpu_time_ratio"), 0.0), 3)
    merged["notes"] = [str(item) for item in list(merged.get("notes") or [])[:8]]
    return merged


def resolve_deep_runtime_state(settings: Mapping[str, Any] | None = None, *, runtime_metadata: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    config = dict(settings or {})
    requested_mode = normalize_deep_runtime_mode(config.get("deep_runtime_mode"), default=DEEP_RUNTIME_DEFAULT_MODE)
    manual_override = bool(config.get("deep_runtime_manual_override", requested_mode != DEEP_RUNTIME_DEFAULT_MODE))
    benchmark = normalize_benchmark_record(config.get("deep_runtime_benchmark"))
    backend_inventory = dict(benchmark.get("backend_inventory") or detect_backend_inventory())
    recommendation_mode = normalize_deep_runtime_mode(benchmark.get("recommended_mode"), default=DEEP_RUNTIME_FALLBACK_MODE)
    recommendation_backend = str(benchmark.get("recommended_backend") or "classic")
    desired_mode = requested_mode if manual_override or requested_mode != DEEP_RUNTIME_DEFAULT_MODE else recommendation_mode

    metadata_deep = dict((runtime_metadata or {}).get("deep_runtime") or {}) if isinstance(runtime_metadata, Mapping) else {}
    sequence_model = dict(metadata_deep.get("sequence_model") or {})
    deep_runtime_ready = bool(metadata_deep.get("deep_sequence_runtime_enabled")) and bool(sequence_model.get("enabled")) and bool(sequence_model.get("artifact"))

    effective_mode = DEEP_RUNTIME_FALLBACK_MODE
    fallback_reason = "classic_requested"
    selected_backend = "classic"
    if desired_mode == "classic":
        if requested_mode == "auto" and not manual_override and benchmark.get("status") != "ok":
            fallback_reason = "benchmark_not_run"
        else:
            fallback_reason = "classic_requested"
    elif benchmark.get("status") != "ok":
        fallback_reason = "benchmark_not_run"
    elif not deep_runtime_ready:
        fallback_reason = "deep_runtime_not_available_yet"
    elif desired_mode == "hybrid_accelerated" and not bool(backend_inventory.get("accelerated_available")):
        fallback_reason = "accelerated_backend_unavailable"
    else:
        effective_mode = desired_mode
        selected_backend = recommendation_backend if effective_mode == "hybrid_accelerated" else "classic"
        fallback_reason = "ok"

    fallback_reason = normalize_deep_runtime_fallback_reason(fallback_reason)
    fallback_reason_text = deep_runtime_fallback_reason_text(fallback_reason)
    is_fallback = deep_runtime_is_fallback(fallback_reason)

    return {
        "requested_mode": requested_mode,
        "manual_override": manual_override,
        "supported_modes": supported_deep_runtime_modes(),
        "benchmark": benchmark,
        "recommended_mode": recommendation_mode,
        "recommended_backend": recommendation_backend,
        "desired_mode": desired_mode,
        "effective_mode": effective_mode,
        "selected_backend": selected_backend,
        "fallback_reason": fallback_reason,
        "fallbackReason": fallback_reason,
        "fallback_reason_text": fallback_reason_text,
        "fallbackReasonText": fallback_reason_text,
        "is_fallback": is_fallback,
        "isFallback": is_fallback,
        "deep_runtime_ready": deep_runtime_ready,
        "backend_inventory": backend_inventory,
        "contract_version": DEEP_RUNTIME_CONTRACT_VERSION,
    }


def resolve_runtime_rollout_state(settings: Mapping[str, Any] | None = None, *, runtime_metadata: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    state = dict(resolve_deep_runtime_state(settings, runtime_metadata=runtime_metadata))
    metadata_deep = dict((runtime_metadata or {}).get("deep_runtime") or {}) if isinstance(runtime_metadata, Mapping) else {}
    sequence_model = dict(metadata_deep.get("sequence_model") or {})
    rollout_details = dict((runtime_metadata or {}).get("rollout_details") or {}) if isinstance(runtime_metadata, Mapping) else {}
    rollout_status = str((runtime_metadata or {}).get("rollout_status") or metadata_deep.get("runtime_rollout_stage") or rollout_details.get("rollout_status") or "classic_only_ready") if isinstance(runtime_metadata, Mapping) else "classic_only_ready"
    shadow_only = bool(metadata_deep.get("runtime_shadow_only", True))
    decision_influence = bool(metadata_deep.get("runtime_decision_influence_enabled", rollout_details.get("production_decision_enabled", False)))
    diagnostics_enabled = bool(metadata_deep.get("runtime_shadow_diagnostics_enabled", rollout_details.get("shadow_diagnostics_enabled", True)))
    rollback_to_classic = bool(metadata_deep.get("runtime_rollback_to_classic_on_failure", rollout_details.get("rollback_to_classic_on_failure", True)))
    runtime_ready = bool(metadata_deep.get("deep_sequence_runtime_enabled")) and bool(sequence_model.get("enabled")) and bool(sequence_model.get("artifact"))
    allowed_modes = [normalize_deep_runtime_mode(item, default=DEEP_RUNTIME_FALLBACK_MODE) for item in list(rollout_details.get("allowed_modes") or [])]
    if not allowed_modes:
        allowed_modes = ["classic", "auto"]

    production_decision_enabled = False
    rollout_reason = str(state.get("fallback_reason") or "classic_requested")
    effective_mode = str(state.get("effective_mode") or "classic")
    desired_mode = str(state.get("desired_mode") or "classic")
    if effective_mode in {"hybrid", "hybrid_accelerated"} and runtime_ready:
        if effective_mode not in allowed_modes:
            rollout_reason = "mode_blocked_by_policy"
        elif not diagnostics_enabled and not decision_influence:
            rollout_reason = "deep_runtime_disabled"
        elif shadow_only or not decision_influence:
            rollout_reason = "shadow_only_policy"
        elif effective_mode == "hybrid_accelerated" and rollout_status != "accelerated_ready":
            rollout_reason = "accelerated_policy_not_ready"
        elif effective_mode == "hybrid_accelerated" and str(state.get("selected_backend") or "classic") == "classic":
            rollout_reason = "accelerated_backend_unavailable"
        else:
            production_decision_enabled = True
            rollout_reason = "ok"
    elif desired_mode == "hybrid_accelerated" and rollout_status != "accelerated_ready":
        rollout_reason = "accelerated_policy_not_ready"

    state.update({
        "rollout_status": rollout_status,
        "rollout_allowed_modes": allowed_modes,
        "shadow_only": shadow_only,
        "shadow_diagnostics_enabled": diagnostics_enabled,
        "production_decision_enabled": production_decision_enabled,
        "rollback_to_classic_on_failure": rollback_to_classic,
        "runtime_activation_reason": rollout_reason,
        "runtime_ready": runtime_ready,
    })
    return state


__all__ = [
    "DEEP_RUNTIME_BENCHMARK_VERSION",
    "DEEP_RUNTIME_CONTRACT_VERSION",
    "DEEP_RUNTIME_DEFAULT_MODE",
    "DEEP_RUNTIME_FALLBACK_MODE",
    "DEEP_RUNTIME_MODES",
    "DEEP_RUNTIME_FALLBACK_REASONS",
    "DEEP_RUNTIME_FALLBACK_REASON_TEXT",
    "DEFAULT_LATENCY_BUDGET_MS",
    "DEFAULT_SEQUENCE_LENGTH",
    "DEFAULT_SEQUENCE_MODEL_FAMILY",
    "DEFAULT_TENSOR_LAYOUT",
    "build_deep_runtime_metadata_contract",
    "default_benchmark_record",
    "deep_runtime_fallback_reason_text",
    "deep_runtime_is_fallback",
    "detect_backend_inventory",
    "normalize_benchmark_record",
    "normalize_deep_runtime_fallback_reason",
    "normalize_deep_runtime_mode",
    "resolve_deep_runtime_state",
    "resolve_runtime_rollout_state",
    "run_local_device_benchmark",
    "supported_deep_runtime_modes",
]
