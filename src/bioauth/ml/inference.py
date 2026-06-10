"""Runtime inference and risk-scoring flow."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

import logging
import os
import time
import numpy as np

from app_settings import load_settings
from deep_runtime import resolve_runtime_rollout_state
from deep_sequence.inference import run_shadow_sequence_scoring
from artifact_integrity import load_classifier, load_metadata, load_model
from bioauth_model.scoring import (
    DEFAULT_RISK_SENSITIVITY,
    DecisionOutcome,
    compute_risk as _compute_risk,
    final_decision_from_metrics,
    normalize_sensitivity_preset,
    score_windows,
)
from model_metadata import (
    CLASSIFIER_FILE,
    KB_HEADER,
    CONTEXT_ROUTER_MIN_CONFIDENCE,
    LIVE_SESSION_DIR,
    METADATA_FILE,
    MIN_WINDOW_EVENTS,
    MODEL_FILE,
    PREDICT_WINDOW_STEP_SECONDS,
    WINDOW_SECONDS,
    resolve_active_runtime_paths,
    runtime_deep_contract_state,
    runtime_feature_schema_mismatch_reason,
    validate_runtime_bundle_for_activation,
)
from features import annotate_sequence_trend_windows, annotate_transition_windows, classify_behavior_context, extract_context_router_features, extract_multi_scale_window_feature_samples, extract_window_feature_samples
from runtime_policy import normalize_calibration_maturity
from runtime_performance import PerfProbe
from model_training import (
    EncryptedSessionReadError,
    MAX_PREDICT_WINDOWS,
    build_matrix,
    get_anomaly_scores,
    normalize_feature_dict,
    read_csv_encrypted,
)

from model_runtime.dynamic_fusion import apply_dynamic_fusion_v1
from model_runtime.diagnostics import (
    _apply_mouse_fallback_guard,
    _build_window_diagnostics,
    _mouse_fallback_guard_profile,
    _quality_gate_status,
    _safe_float,
    _window_diag_brief,
)
from model_runtime.bundles import (
    _load_runtime_context_bundles,
    _load_user_runtime_bundle,
    _resolve_runtime_window_scales,
)
from hybrid_runtime_layers import build_runtime_layer_payloads

LOGGER = logging.getLogger(__name__)






























def _score_single_sample(
    sample: Mapping[str, Any],
    *,
    model: Any,
    metadata: Mapping[str, Any],
    classifier: Any = None,
    classifier_fallback: Any = None,
) -> tuple[float, float, float | None]:
    feature_names = [str(name) for name in (metadata.get("feature_names") or [])]
    X = build_matrix([normalize_feature_dict(dict(sample))], feature_names)
    raw_score = float(get_anomaly_scores(model, X)[0])
    risk_value = float(compute_risk(raw_score, dict(metadata)))
    active_classifier = classifier if classifier is not None else classifier_fallback
    classifier_prob: float | None = None
    if active_classifier is not None:
        preds = np.asarray(active_classifier.predict(X), dtype=float)
        classifier_prob = float(preds[0]) if preds.size else 0.0
        if hasattr(active_classifier, "predict_proba"):
            try:
                probs = np.asarray(active_classifier.predict_proba(X), dtype=float)
                if probs.ndim == 2 and probs.shape[1] >= 2:
                    classifier_prob = float(probs[0, 1])
            except (TypeError, ValueError) as exc:
                LOGGER.warning("Classifier probability fallback failed: %s", exc)
    return raw_score, risk_value, classifier_prob










def _build_transition_state(window_samples: list[Mapping[str, Any]], meta: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    policy = dict((meta or {}).get("transition_policy") or {}) if isinstance(meta, Mapping) else {}
    samples = [dict(sample or {}) for sample in window_samples]
    if not samples:
        return {
            "enabled": bool(policy.get("enabled", True)),
            "active": False,
            "status": "settled",
            "transition_window_count": 0,
            "transition_prevalence": 0.0,
            "recent_transition_windows": 0,
            "recent_settled_windows": 0,
            "last_transition_flag": False,
            "last_session_start_flag": False,
            "last_post_idle_flag": False,
            "max_transition_strength": 0.0,
        }
    transition_flags = [float(sample.get("transition_flag", 0.0) or 0.0) >= 0.5 for sample in samples]
    transition_strengths = [float(sample.get("transition_strength", 0.0) or 0.0) for sample in samples]
    recent_count = min(2, len(samples))
    recent_flags = transition_flags[-recent_count:]
    recent_transition_windows = int(sum(1 for flag in recent_flags if flag))
    recent_settled_windows = int(recent_count - recent_transition_windows)
    active = bool(transition_flags[-1] or recent_transition_windows >= 1)
    last = samples[-1]
    return {
        "enabled": bool(policy.get("enabled", True)),
        "active": active,
        "status": "transitioning" if active else "settled",
        "transition_window_count": int(sum(1 for flag in transition_flags if flag)),
        "transition_prevalence": round(float(sum(1 for flag in transition_flags if flag) / len(samples)), 6),
        "recent_transition_windows": recent_transition_windows,
        "recent_settled_windows": recent_settled_windows,
        "last_transition_flag": bool(transition_flags[-1]),
        "last_session_start_flag": bool(float(last.get("transition_session_start_flag", 0.0) or 0.0) >= 0.5),
        "last_post_idle_flag": bool(float(last.get("transition_post_idle_flag", 0.0) or 0.0) >= 0.5),
        "max_transition_strength": round(float(max(transition_strengths) if transition_strengths else 0.0), 6),
    }


def _apply_transition_runtime_policy(
    outcome: DecisionOutcome,
    *,
    metrics: Mapping[str, Any],
    window_count: int,
    transition_state: Mapping[str, Any],
    meta: Mapping[str, Any] | None,
) -> tuple[DecisionOutcome, str, Dict[str, Any]]:
    policy = dict((meta or {}).get("transition_policy") or {}) if isinstance(meta, Mapping) else {}
    diagnostics = {
        "enabled": bool(policy.get("enabled", True)),
        "applied": False,
        "bypass_high_risk": False,
        "status": "settled",
    }
    if not bool(policy.get("enabled", True)):
        return outcome, "ok", diagnostics
    if not bool(transition_state.get("active")):
        return outcome, "ok", diagnostics

    high_risk_bypass = float(policy.get("runtime_high_risk_bypass") or 92.0)
    high_severe_window_count = int(policy.get("runtime_high_severe_window_count") or 2)
    min_settled_windows = int(policy.get("runtime_min_settled_windows") or 2)
    severe_windows = int(metrics.get("severe_windows", 0) or 0)
    risk = int(outcome.risk or 0)

    diagnostics["status"] = "transitioning"
    diagnostics["recent_settled_windows"] = int(transition_state.get("recent_settled_windows") or 0)
    diagnostics["min_settled_windows"] = min_settled_windows

    if risk >= high_risk_bypass or severe_windows >= high_severe_window_count:
        diagnostics["bypass_high_risk"] = True
        return outcome, "ok", diagnostics

    if outcome.final in {"suspicious", "intruder"} or int(window_count) < min_settled_windows or int(transition_state.get("recent_settled_windows") or 0) < min_settled_windows:
        diagnostics["applied"] = True
        return outcome, str(policy.get("runtime_transition_status") or "transitioning"), diagnostics
    return outcome, "ok", diagnostics




def _failure_result(status: str, *, error: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "final": "unknown",
        "raw": 0.0,
        "risk": 0,
        "ml": 0,
        "status": str(status or "prediction_failed"),
        "window_count": 0,
    }
    detail = str(error or "").strip()
    if detail:
        payload["error"] = detail
    return payload


def _metadata_supports_classic_prediction(meta: Mapping[str, Any] | None) -> bool:
    if not isinstance(meta, Mapping):
        return False
    feature_names_raw = meta.get("feature_names")
    return isinstance(feature_names_raw, (list, tuple)) and bool(feature_names_raw)


def _resolve_runtime_metadata(metadata: Mapping[str, Any] | None, metadata_file: str) -> tuple[Mapping[str, Any] | None, str | None]:
    candidate = dict(metadata) if isinstance(metadata, Mapping) else None
    if _metadata_supports_classic_prediction(candidate):
        return candidate, None

    if candidate is not None:
        LOGGER.warning(
            "Provided runtime metadata is invalid for classic prediction; attempting file fallback from %s",
            metadata_file,
        )

    fallback = None
    load_error = None
    try:
        fallback = load_metadata(metadata_file)
        if fallback is None:
            load_error = FileNotFoundError(metadata_file)
    except Exception as exc:
        load_error = exc
        try:
            import json
            from pathlib import Path

            fallback = json.loads(Path(metadata_file).read_text(encoding="utf-8") or "{}")
            LOGGER.warning(
                "Runtime metadata fallback used plain JSON parsing for %s after integrity load failure: %s",
                metadata_file,
                exc,
            )
        except Exception:
            fallback = None
    if _metadata_supports_classic_prediction(fallback):
        if candidate is not None:
            LOGGER.info("Recovered runtime metadata from %s after invalid in-memory metadata payload", metadata_file)
        return fallback, None
    if candidate is not None:
        if load_error is not None:
            return None, f"provided_metadata_invalid_no_fallback:{load_error}"
        return None, "provided_metadata_invalid_no_classic_safe_fallback"
    if load_error is not None:
        return None, f"metadata_invalid:{load_error}"
    return None, "metadata_invalid_no_classic_safe_fallback"


def _load_runtime_sensitivity_config(meta: Mapping[str, Any] | None = None) -> tuple[str, Mapping[str, Any] | None]:
    settings = load_settings()
    preset = normalize_sensitivity_preset(str(settings.get("risk_sensitivity") or (meta or {}).get("risk_sensitivity_default") or DEFAULT_RISK_SENSITIVITY))
    overrides = settings.get("risk_threshold_overrides")
    return preset, overrides if isinstance(overrides, Mapping) else None


def compute_risk(raw: float, meta: Dict[str, Any]) -> int:
    return _compute_risk(raw, meta)


def _calibration_enabled(meta: Mapping[str, Any] | None) -> bool:
    profile = ((meta or {}).get("user_calibration") or {}) if isinstance(meta, Mapping) else {}
    return bool(profile.get("enabled") and profile.get("maturity_flag"))


def _calibrate_raw_to_user_risk(raw_value: float, meta: Mapping[str, Any] | None) -> float:
    profile = ((meta or {}).get("user_calibration") or {}) if isinstance(meta, Mapping) else {}
    stats = dict(profile.get("positive_session_raw_percentiles") or {})
    warning_band = dict(profile.get("warning_band") or {})
    if not stats:
        return float(compute_risk(raw_value, dict(meta or {})))
    xs = [
        float(stats.get("p50", 0.0)),
        float(stats.get("p75", stats.get("p50", 0.0))),
        float(stats.get("p90", stats.get("p75", 0.0))),
        float(stats.get("p95", stats.get("p90", 0.0))),
        float(stats.get("p98", stats.get("p95", 0.0))),
        float(warning_band.get("tail_high", stats.get("tail_high", stats.get("p98", 0.0) + 1.0))),
    ]
    ys = [10.0, 22.0, 40.0, 60.0, 82.0, 100.0]
    monotonic = []
    floor = None
    for value in xs:
        cur = float(value)
        if floor is not None and cur <= floor:
            cur = floor + 1e-6
        monotonic.append(cur)
        floor = cur
    return float(np.clip(np.interp(float(raw_value), monotonic, ys, left=0.0, right=100.0), 0.0, 100.0))


def predict_from_session_details(
    model: Any,
    session_path: str,
    metadata_file: str = METADATA_FILE,
    classifier_file: str = CLASSIFIER_FILE,
    sensitivity: str | None = None,
    threshold_overrides: Mapping[str, Any] | None = None,
    *,
    metadata: Mapping[str, Any] | None = None,
    classifier: Any = None,
) -> Dict[str, Any]:
    if model is None:
        return _failure_result("model_unavailable")

    meta, metadata_error = _resolve_runtime_metadata(metadata, metadata_file)
    if metadata_error:
        return _failure_result("metadata_invalid", error=metadata_error)
    feature_names_raw = meta.get("feature_names") if isinstance(meta, Mapping) else None
    perf_probe = PerfProbe()
    prediction_started = time.perf_counter()

    clf = classifier if classifier is not None else load_classifier(classifier_file)

    try:
        with perf_probe.span("csv_read_ms"):
            kb = read_csv_encrypted(f"{session_path}/keyboard_log.csv", KB_HEADER, strict=True)
            ms = read_csv_encrypted(f"{session_path}/mouse_log.csv", "x,y,event,timestamp", strict=True)
        perf_probe.set_count("keyboard_rows", len(kb))
        perf_probe.set_count("mouse_rows", len(ms))
    except EncryptedSessionReadError as exc:
        LOGGER.warning("Runtime input read failed for %s: %s", session_path, exc)
        result = _failure_result("input_read_failed", error=str(exc))
        result["runtime_performance"] = perf_probe.payload(total_started_at=prediction_started)
        return result

    if kb.empty and ms.empty:
        result = _failure_result("insufficient_windows")
        result["runtime_performance"] = perf_probe.payload(total_started_at=prediction_started)
        return result

    try:
        runtime_window_scales = _resolve_runtime_window_scales(meta)
        with perf_probe.span("feature_extraction_ms"):
            if len(runtime_window_scales) > 1:
                window_samples = extract_multi_scale_window_feature_samples(
                    kb,
                    ms,
                    window_scales=runtime_window_scales,
                    step_seconds=float(meta.get("predict_window_step_seconds", meta.get("window_step_seconds", PREDICT_WINDOW_STEP_SECONDS)) or PREDICT_WINDOW_STEP_SECONDS),
                    min_total_events=int(meta.get("min_window_events", MIN_WINDOW_EVENTS) or MIN_WINDOW_EVENTS),
                    max_windows=int(meta.get("max_predict_windows", MAX_PREDICT_WINDOWS) or MAX_PREDICT_WINDOWS),
                )
            else:
                window_samples = extract_window_feature_samples(
                    kb,
                    ms,
                    window_seconds=float(meta.get("window_seconds", WINDOW_SECONDS) or WINDOW_SECONDS),
                    step_seconds=float(meta.get("predict_window_step_seconds", meta.get("window_step_seconds", PREDICT_WINDOW_STEP_SECONDS)) or PREDICT_WINDOW_STEP_SECONDS),
                    min_total_events=int(meta.get("min_window_events", MIN_WINDOW_EVENTS) or MIN_WINDOW_EVENTS),
                    max_windows=int(meta.get("max_predict_windows", MAX_PREDICT_WINDOWS) or MAX_PREDICT_WINDOWS),
                )
        perf_probe.set_count("runtime_windows", len(window_samples))
    except (TypeError, ValueError, OverflowError) as exc:
        LOGGER.warning("Runtime metadata invalid for %s: %s", session_path, exc)
        result = _failure_result("metadata_invalid", error=str(exc))
        result["runtime_performance"] = perf_probe.payload(total_started_at=prediction_started)
        return result

    if not window_samples:
        result = _failure_result("insufficient_windows")
        result["runtime_performance"] = perf_probe.payload(total_started_at=prediction_started)
        return result

    feature_names = [str(name) for name in feature_names_raw]
    quality_gate: Dict[str, Any] = {"applied": False, "status": "ok", "reason": "not_evaluated"}
    model_inference_started = time.perf_counter()
    try:
        context_router = dict(meta.get("context_router") or {}) if isinstance(meta, Mapping) else {}
        context_bundles = _load_runtime_context_bundles(metadata_file, meta) if context_router.get("enabled") else {}
        min_confidence = float(context_router.get("min_confidence") or CONTEXT_ROUTER_MIN_CONFIDENCE)

        window_samples = annotate_sequence_trend_windows(annotate_transition_windows(window_samples))
        transition_state = _build_transition_state(window_samples, meta)

        raw_values = []
        risk_values = []
        classifier_prob_values = []
        routing_counts: dict[str, int] = {}
        routed_window_count = 0
        fallback_window_count = 0
        route_records: list[dict[str, Any]] = []
        used_contexts: list[str] = []
        classifier_prob_trace: list[float | None] = []
        base_risk_trace: list[float] = []
        base_classifier_prob_trace: list[float | None] = []
        guard_trace: list[dict[str, Any]] = []
        for sample in window_samples:
            route = classify_behavior_context(sample)
            route_records.append(dict(route or {}))
            target_context = str(route.get("context") or "")
            route_confidence = float(route.get("confidence") or 0.0)
            bundle = context_bundles.get(target_context) if route_confidence >= min_confidence else None
            bundle_model = model if bundle is None else bundle["model"]
            bundle_meta = meta if bundle is None else bundle["metadata"]
            bundle_classifier = clf if bundle is None else bundle.get("classifier")
            used_context = "global_fallback" if bundle is None else target_context
            used_contexts.append(used_context)
            if bundle is None:
                fallback_window_count += 1
            else:
                routed_window_count += 1
            routing_counts[used_context] = routing_counts.get(used_context, 0) + 1
            raw_score, base_risk_value, base_classifier_prob = _score_single_sample(
                sample,
                model=bundle_model,
                metadata=bundle_meta,
                classifier=bundle_classifier,
                classifier_fallback=clf,
            )
            guard_profile = _mouse_fallback_guard_profile(sample=sample, route=route, used_context=used_context)
            adjusted_risk_value, adjusted_classifier_prob, guard_record = _apply_mouse_fallback_guard(
                risk_value=base_risk_value,
                classifier_prob=base_classifier_prob,
                guard_profile=guard_profile,
            )
            raw_values.append(raw_score)
            risk_values.append(float(adjusted_risk_value))
            classifier_prob_trace.append(float(adjusted_classifier_prob) if adjusted_classifier_prob is not None else None)
            base_risk_trace.append(float(base_risk_value))
            base_classifier_prob_trace.append(float(base_classifier_prob) if base_classifier_prob is not None else None)
            guard_trace.append({**guard_profile, **guard_record})
            if adjusted_classifier_prob is not None:
                classifier_prob_values.append(float(adjusted_classifier_prob))

        dynamic_fusion = apply_dynamic_fusion_v1(
            window_samples=window_samples,
            route_records=route_records,
            used_contexts=used_contexts,
            risk_values=risk_values,
            classifier_probs=classifier_prob_trace,
            metadata=meta,
            settings=load_settings(),
        )
        risk_values = [float(value) for value in list(dynamic_fusion.get("risk_values") or [])]
        classifier_prob_trace = list(dynamic_fusion.get("classifier_probs") or [])
        classifier_prob_values = [float(value) for value in classifier_prob_trace if value is not None]

        raw_scores = np.asarray(raw_values, dtype=float)
        base_anomaly_risk_values = np.asarray(risk_values, dtype=float)
        anomaly_risk_values = base_anomaly_risk_values
        calibration_profile = dict(meta.get("user_calibration") or {}) if isinstance(meta, Mapping) else {}
        calibration_maturity = normalize_calibration_maturity(meta if isinstance(meta, Mapping) else {})
        calibration_applied = _calibration_enabled(meta)
        if calibration_applied and raw_scores.size:
            anomaly_risk_values = np.asarray([_calibrate_raw_to_user_risk(raw_value, meta) for raw_value in raw_scores], dtype=float)
        classifier_probs = np.asarray(classifier_prob_values, dtype=float) if classifier_prob_values else None

        preset, runtime_overrides = _load_runtime_sensitivity_config(meta)
        if sensitivity is not None:
            preset = normalize_sensitivity_preset(sensitivity)
        overrides = threshold_overrides if threshold_overrides is not None else runtime_overrides

        runtime_mode = resolve_runtime_rollout_state(load_settings(), runtime_metadata=dict(meta or {}))
        sequence_shadow = run_shadow_sequence_scoring(window_samples=window_samples, metadata_file=metadata_file, meta=meta, runtime_state=runtime_mode)
        sequence_probs = np.asarray([float(sequence_shadow.get("probability"))], dtype=float) if sequence_shadow.get("used") else None
        metrics = score_windows(
            raw_scores=raw_scores,
            anomaly_risk_values=anomaly_risk_values,
            classifier_probs=classifier_probs,
            sensitivity=preset,
            overrides=overrides,
            sequence_probs=sequence_probs,
        )
        classic_outcome: DecisionOutcome = final_decision_from_metrics(metrics=metrics, window_count=len(window_samples))
        outcome: DecisionOutcome = classic_outcome
        hybrid_payload = dict(metrics.get("hybrid") or {})
        hybrid_candidate = None
        hybrid_shadow = None
        decision_source = "classic"
        rollback_reason = None
        if hybrid_payload.get("available"):
            hybrid_candidate = final_decision_from_metrics(metrics={**metrics, **hybrid_payload}, window_count=len(window_samples))
            hybrid_shadow = {
                "available": True,
                "used": True,
                "final": hybrid_candidate.final,
                "risk": hybrid_candidate.risk,
                "ml": hybrid_candidate.ml_pred,
                "intruder_prob": hybrid_candidate.intruder_prob,
                "sequence_prob": hybrid_payload.get("sequence_prob"),
                "shadow_only": not bool(runtime_mode.get("production_decision_enabled")),
                "used_for_decision": False,
            }
        else:
            hybrid_shadow = {
                "available": False,
                "used": False,
                "final": classic_outcome.final,
                "risk": classic_outcome.risk,
                "ml": classic_outcome.ml_pred,
                "intruder_prob": classic_outcome.intruder_prob,
                "sequence_prob": None,
                "shadow_only": not bool(runtime_mode.get("production_decision_enabled")),
                "used_for_decision": False,
            }

        if bool(runtime_mode.get("production_decision_enabled")):
            if hybrid_candidate is not None and bool(sequence_shadow.get("used")):
                outcome = hybrid_candidate
                decision_source = "hybrid_production"
                hybrid_shadow["used_for_decision"] = True
            else:
                rollback_reason = str(sequence_shadow.get("reason") or runtime_mode.get("runtime_activation_reason") or "hybrid_runtime_unavailable")
                decision_source = "classic_rollback"

        outcome, effective_status, transition_runtime = _apply_transition_runtime_policy(
            outcome,
            metrics={**metrics, **(hybrid_payload if decision_source == "hybrid_production" else {})},
            window_count=len(window_samples),
            transition_state=transition_state,
            meta=meta,
        )
        window_diagnostics, window_diagnostics_summary = _build_window_diagnostics(
            window_samples,
            raw_values=raw_values,
            risk_values=risk_values,
            classifier_probs=classifier_prob_trace,
            route_records=route_records,
            used_contexts=used_contexts,
            base_risk_values=base_risk_trace,
            base_classifier_probs=base_classifier_prob_trace,
            guard_records=guard_trace,
            dynamic_fusion_records=list(dynamic_fusion.get("records") or []),
        )
        quality_gate = _quality_gate_status(window_diagnostics_summary)
        runtime_bundle_source = "developer_shadow_candidate" if os.environ.get("BIOAUTH_RUNTIME_BUNDLE_SOURCE", "").strip() == "developer_shadow_candidate" else str((meta or {}).get("runtime_bundle_source") or "")
        layer_payloads = build_runtime_layer_payloads(
            metadata=meta,
            metadata_file=metadata_file,
            window_samples=window_samples,
            prediction={
                "final": outcome.final,
                "risk": outcome.risk,
                "status": effective_status,
                "decision_source": decision_source,
                "decision_reason": outcome.decision_reason,
                "decision_details": dict(outcome.decision_details or {}),
            },
            runtime_bundle_source=runtime_bundle_source,
        )
        perf_probe.set_ms("model_inference_ms", (time.perf_counter() - model_inference_started) * 1000.0)
        if bool(quality_gate.get("applied")):
            effective_status = str(quality_gate.get("status") or "insufficient_evidence")
    except (TypeError, ValueError) as exc:
        LOGGER.warning("Runtime prediction failed for %s: %s", session_path, exc, exc_info=True)
        result = _failure_result("prediction_failed", error=str(exc))
        result["runtime_performance"] = perf_probe.payload(total_started_at=prediction_started)
        return result

    return {
        "final": "unknown" if bool(quality_gate.get("applied")) else outcome.final,
        "raw": outcome.raw,
        "risk": outcome.risk,
        "ml": outcome.ml_pred,
        "status": effective_status,
        "window_count": len(window_samples),
        "base_window_risk_mean": float(np.mean(base_anomaly_risk_values)) if base_anomaly_risk_values.size else 0.0,
        "calibrated_window_risk_mean": float(np.mean(anomaly_risk_values)) if anomaly_risk_values.size else 0.0,
        "user_calibration": {
            "enabled": bool(calibration_profile.get("enabled")),
            "applied": bool(calibration_applied),
            "maturity_flag": bool(calibration_profile.get("maturity_flag")),
            "maturity_reason": calibration_profile.get("maturity_reason"),
        },
        "calibration_maturity": dict(calibration_maturity),
        "transition_state": {
            **transition_state,
            **transition_runtime,
        },
        "sequence_features": {
            "enabled": bool(((meta.get("sequence_features") or {}).get("enabled")) if isinstance(meta, Mapping) else False),
            "version": ((meta.get("sequence_features") or {}).get("version")) if isinstance(meta, Mapping) else None,
            "families_enabled": list(((meta.get("sequence_features") or {}).get("families_enabled") or [])) if isinstance(meta, Mapping) else [],
        },
        "supervised_classifier": {
            "enabled": bool(((meta.get("supervised_classifier") or {}).get("enabled")) if isinstance(meta, Mapping) else False),
            "selected_family": ((meta.get("supervised_classifier") or {}).get("selected_family")) if isinstance(meta, Mapping) else None,
            "selection_version": ((meta.get("supervised_classifier") or {}).get("selection_version")) if isinstance(meta, Mapping) else None,
            "selection_reason": ((meta.get("supervised_classifier") or {}).get("selection_reason")) if isinstance(meta, Mapping) else None,
        },
        "context_routing": {
            "enabled": bool(context_bundles),
            "used_context_counts": routing_counts,
            "routed_window_count": int(routed_window_count),
            "fallback_window_count": int(fallback_window_count),
            "min_confidence": float(min_confidence),
        },
        "decision_source": decision_source,
        "decision_reason": str(outcome.decision_reason or ""),
        "decision_details": dict(outcome.decision_details or {}),
        "runtime_rollout": {
            "production_decision_enabled": bool(runtime_mode.get("production_decision_enabled")),
            "rollout_status": runtime_mode.get("rollout_status"),
            "runtime_activation_reason": runtime_mode.get("runtime_activation_reason"),
            "rollback_reason": rollback_reason,
        },
        "deep_runtime": runtime_mode,
        "deep_sequence": sequence_shadow,
        "hybrid_shadow": hybrid_shadow,
        "runtime_layer_payloads": layer_payloads,
        "dynamic_fusion": dict(dynamic_fusion.get("summary") or {}),
        "runtime_performance": perf_probe.payload(total_started_at=prediction_started),
        "window_quality": dict(window_diagnostics_summary.get("quality") or {}),
        "window_quality_gate": dict(quality_gate),
        "window_diagnostics": window_diagnostics,
        "window_diagnostics_summary": {
            **window_diagnostics_summary,
            "brief": _window_diag_brief(window_diagnostics_summary),
        },
    }


def predict_from_session(
    model: Any,
    session_path: str,
    metadata_file: str = METADATA_FILE,
    classifier_file: str = CLASSIFIER_FILE,
    sensitivity: str | None = None,
    threshold_overrides: Mapping[str, Any] | None = None,
    *,
    metadata: Mapping[str, Any] | None = None,
    classifier: Any = None,
):
    details = predict_from_session_details(
        model,
        session_path,
        metadata_file=metadata_file,
        classifier_file=classifier_file,
        sensitivity=sensitivity,
        threshold_overrides=threshold_overrides,
        metadata=metadata,
        classifier=classifier,
    )
    return details["final"], details["raw"], details["risk"], details["ml"]


def predict_live_session(model: Any):
    return predict_from_session(model, LIVE_SESSION_DIR)


def load_user_model(user_id: str):
    bundle = _load_user_runtime_bundle(user_id)
    return bundle.get("model") if isinstance(bundle, dict) else None


def predict_live_session_for_user(user_id: str):
    bundle = _load_user_runtime_bundle(user_id)
    if not isinstance(bundle, dict):
        return "unknown", 0.0, 0, 0
    return predict_from_session(
        bundle["model"],
        LIVE_SESSION_DIR,
        metadata_file=bundle["metadata_file"],
        classifier_file=bundle["classifier_file"],
        metadata=bundle["metadata"],
        classifier=bundle["classifier"],
    )
