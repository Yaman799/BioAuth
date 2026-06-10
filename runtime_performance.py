from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Mapping

RUNTIME_PERFORMANCE_SCHEMA_VERSION = "runtime-performance-v1"
MONITOR_CYCLE_BUDGET_MS = 1500.0
CSV_READ_BUDGET_MS = 450.0
FEATURE_EXTRACTION_BUDGET_MS = 650.0
MODEL_INFERENCE_BUDGET_MS = 450.0


def _round_ms(value: float) -> float:
    try:
        return round(float(value), 3)
    except Exception:
        return 0.0


class PerfProbe:
    """Small timing collector for runtime diagnostics only.

    The probe stores aggregate timings and never stores raw keyboard/mouse rows,
    feature vectors, model inputs, or predictions. It is safe to include in
    monitor state/support bundles as a performance diagnostic.
    """

    def __init__(self) -> None:
        self._metrics: Dict[str, float] = {}

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self._metrics[str(name)] = _round_ms((time.perf_counter() - started) * 1000.0)

    def set_ms(self, name: str, value: Any) -> None:
        try:
            self._metrics[str(name)] = _round_ms(float(value))
        except Exception:
            self._metrics[str(name)] = 0.0

    def set_count(self, name: str, value: Any) -> None:
        try:
            self._metrics[str(name)] = int(value)
        except Exception:
            self._metrics[str(name)] = 0

    def payload(self, *, total_started_at: float | None = None) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "schema_version": RUNTIME_PERFORMANCE_SCHEMA_VERSION,
            "budgets_ms": {
                "monitor_cycle": MONITOR_CYCLE_BUDGET_MS,
                "csv_read": CSV_READ_BUDGET_MS,
                "feature_extraction": FEATURE_EXTRACTION_BUDGET_MS,
                "model_inference": MODEL_INFERENCE_BUDGET_MS,
            },
            "measurements_ms": {},
            "counts": {},
        }
        if total_started_at is not None:
            self._metrics["prediction_total_ms"] = _round_ms((time.perf_counter() - float(total_started_at)) * 1000.0)
        for key, value in sorted(self._metrics.items()):
            if key.endswith("_count") or key.endswith("_rows") or key.endswith("_windows"):
                data["counts"][key] = int(value)
            else:
                data["measurements_ms"][key] = _round_ms(float(value))
        data["budget_status"] = budget_status(data)
        return data


def budget_status(payload: Mapping[str, Any]) -> Dict[str, bool]:
    measurements = dict((payload or {}).get("measurements_ms") or {})
    budgets = dict((payload or {}).get("budgets_ms") or {})
    return {
        "monitor_cycle_ok": float(measurements.get("monitor_cycle_ms", 0.0) or 0.0) <= float(budgets.get("monitor_cycle", MONITOR_CYCLE_BUDGET_MS)),
        "csv_read_ok": float(measurements.get("csv_read_ms", 0.0) or 0.0) <= float(budgets.get("csv_read", CSV_READ_BUDGET_MS)),
        "feature_extraction_ok": float(measurements.get("feature_extraction_ms", 0.0) or 0.0) <= float(budgets.get("feature_extraction", FEATURE_EXTRACTION_BUDGET_MS)),
        "model_inference_ok": float(measurements.get("model_inference_ms", 0.0) or 0.0) <= float(budgets.get("model_inference", MODEL_INFERENCE_BUDGET_MS)),
    }


INCREMENTAL_READING_DESIGN = {
    "status": "design_ready_not_enabled_by_default",
    "cursor_fields": ["file_path", "last_position", "last_size", "last_mtime_ns", "chunk_id", "header_hash"],
    "fallbacks": ["file_rotation", "file_truncation", "header_mismatch", "decrypt_error", "chunk_store_reset"],
    "safety_rule": "fallback_to_full_read_once_with_deduplication_before_any_runtime_decision",
    "reason_not_enabled": "encrypted/chunked log rotation needs Windows E2E regression before production use",
}
