from __future__ import annotations

import hashlib
import json
import os
import tempfile
from importlib import import_module
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from evaluation_core.production_evidence import build_production_evidence_report_from_summaries


def _facade():
    return import_module("model_evaluation")


def _sha256_file_digest(path: str) -> str:
    text_path = str(path or "").strip()
    if not text_path or not os.path.exists(text_path):
        return ""
    digest = hashlib.sha256()
    with open(text_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _sha256_json_digest(payload: Mapping[str, Any] | None) -> str:
    try:
        encoded = json.dumps(dict(payload or {}), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError):
        return ""
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _production_evidence_summaries(
    *,
    metadata: Mapping[str, Any] | None,
    training_selection: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Return only explicit privacy-safe production evidence summaries.

    This does not derive evidence from raw sessions or biometric feature values.
    Missing source data intentionally remains missing/partial evidence.
    """

    merged: Dict[str, Any] = {}
    for source in (metadata, training_selection):
        if not isinstance(source, Mapping):
            continue
        for key in ("production_evidence_summaries", "production_evidence_inputs"):
            value = source.get(key)
            if isinstance(value, Mapping):
                merged.update(dict(value))
    return merged


def evaluate_candidate_model(*, positive_sessions: Sequence[str], negative_sessions: Sequence[str], model_file: str, metadata_file: str, classifier_file: str, output_dir: Optional[str] = None, bundle_role: str = "candidate", user_id: str = "", allow_temp_retraining: bool = True, training_selection: Optional[Mapping[str, Any]] = None, progress_callback: Optional[Callable[[float, str, Optional[Mapping[str, Any]]], None]] = None) -> Dict[str, Any]:
    facade = _facade()
    model = facade.load_model(model_file)
    metadata = facade.load_metadata(metadata_file) or {}
    classifier = facade.load_classifier(classifier_file) if os.path.exists(classifier_file) else None
    positive_list = facade._unique_paths(positive_sessions)
    negative_list = facade._unique_paths(negative_sessions)
    split_plan = facade.plan_session_holdout_split(positive_list, negative_list)
    cv_splits = facade.plan_session_cross_validation_splits(positive_list, negative_list)
    evaluations: Dict[str, Any] = {}
    warnings: list[str] = []
    facade._emit_evaluation_progress(progress_callback, 0.08, "training_detail_evaluation_candidate_bundle")
    evaluations["candidate_bundle"] = facade.evaluate_model_bundle(model, metadata, classifier, positive_list, negative_list)
    split_method = "candidate_bundle_resubstitution"
    primary_evaluation = "candidate_bundle"
    if allow_temp_retraining and cv_splits:
        fold_results = []
        total_folds = max(1, len(cv_splits))
        for split in cv_splits:
            fold_index = int(split.get("fold_index") or 0)
            fold_base = 0.16 + (0.46 * max(0, fold_index - 1) / total_folds)
            fold_span = 0.46 / total_folds
            facade._emit_evaluation_progress(progress_callback, fold_base, "training_detail_evaluation_fold", {"current": fold_index, "total": total_folds})
            with tempfile.TemporaryDirectory(prefix="bioauth_cv_") as temp_dir:
                temp_model = os.path.join(temp_dir, "model.pkl")
                temp_classifier = os.path.join(temp_dir, "classifier.pkl")
                temp_metadata = os.path.join(temp_dir, "metadata.json")
                def _fold_progress(local_fraction: float, detail_key: str = "", message_params: Optional[Mapping[str, Any]] = None) -> None:
                    facade._emit_evaluation_progress(progress_callback, fold_base + (fold_span * max(0.0, min(1.0, float(local_fraction)))), detail_key or "training_detail_evaluation_fold", message_params or {"current": fold_index, "total": total_folds})
                trained_model, status = facade.train_model(sessions=list(split["train_positive_sessions"]) + list(split["train_negative_sessions"]), negative_sessions=list(split["train_negative_sessions"]), model_file=temp_model, classifier_file=temp_classifier, metadata_file=temp_metadata, progress_callback=_fold_progress)
                if trained_model is None or status != "ok" or not os.path.exists(temp_metadata):
                    warnings.append(f"Cross-validation fold {split['fold_index']} fell back because the temporary split model could not be trained.")
                    continue
                fold_metadata = facade.load_metadata(temp_metadata) or {}
                fold_classifier = facade.load_classifier(temp_classifier) if os.path.exists(temp_classifier) else None
                fold_eval = facade.evaluate_model_bundle(trained_model, fold_metadata, fold_classifier, split["test_positive_sessions"], split["test_negative_sessions"])
                fold_results.append({**split, "evaluation": fold_eval})
        if fold_results:
            evaluations["session_cross_validation"] = facade._aggregate_cross_validation_evaluations(fold_results)
            split_method = "session_cross_validation_round_robin_v1"
            primary_evaluation = "session_cross_validation"
        else:
            warnings.append("Session-wise cross-validation was not available because no fold completed successfully.")
    has_test_sessions = bool(split_plan.get("test_positive_sessions") or split_plan.get("test_negative_sessions"))
    if allow_temp_retraining and has_test_sessions:
        facade._emit_evaluation_progress(progress_callback, 0.68, "training_detail_evaluation_holdout")
        with tempfile.TemporaryDirectory(prefix="bioauth_holdout_") as temp_dir:
            temp_model = os.path.join(temp_dir, "model.pkl")
            temp_classifier = os.path.join(temp_dir, "classifier.pkl")
            temp_metadata = os.path.join(temp_dir, "metadata.json")
            def _holdout_progress(local_fraction: float, detail_key: str = "", message_params: Optional[Mapping[str, Any]] = None) -> None:
                facade._emit_evaluation_progress(progress_callback, 0.68 + (0.18 * max(0.0, min(1.0, float(local_fraction)))), detail_key or "training_detail_evaluation_holdout", message_params)
            trained_model, status = facade.train_model(sessions=list(split_plan["train_positive_sessions"]) + list(split_plan["train_negative_sessions"]), negative_sessions=list(split_plan["train_negative_sessions"]), model_file=temp_model, classifier_file=temp_classifier, metadata_file=temp_metadata, progress_callback=_holdout_progress)
            if trained_model is not None and status == "ok" and os.path.exists(temp_metadata):
                holdout_metadata = facade.load_metadata(temp_metadata) or {}
                holdout_classifier = facade.load_classifier(temp_classifier) if os.path.exists(temp_classifier) else None
                evaluations["session_holdout"] = facade.evaluate_model_bundle(trained_model, holdout_metadata, holdout_classifier, split_plan["test_positive_sessions"], split_plan["test_negative_sessions"])
                if primary_evaluation == "candidate_bundle":
                    split_method = "session_holdout_latest_sessions"
                    primary_evaluation = "session_holdout"
            else:
                warnings.append("Holdout evaluation fell back to candidate-bundle scoring because the temporary split model could not be trained.")
    else:
        warnings.append("Holdout evaluation was not available because the session pool was too small for a clean train/test split.")
    primary_reference_positive = positive_list
    primary_reference_negative = negative_list
    if primary_evaluation == "session_holdout" and has_test_sessions:
        primary_reference_positive = list(split_plan["test_positive_sessions"])
        primary_reference_negative = list(split_plan["test_negative_sessions"])
    facade._emit_evaluation_progress(progress_callback, 0.94, "training_detail_evaluation_compare_production")
    current_production = facade._evaluate_current_production_bundle(user_id=str(user_id or ""), reference_positive_sessions=primary_reference_positive, reference_negative_sessions=primary_reference_negative, candidate_base_dir=os.path.dirname(model_file))
    facade._emit_evaluation_progress(progress_callback, 0.98, "training_detail_writing_reports")
    report: Dict[str, Any] = {
        "schema_version": facade.EVALUATION_SCHEMA_VERSION,
        "generated_at": facade._now_timestamp(),
        "user_id": str(user_id or ""),
        "bundle_role": str(bundle_role or "candidate"),
        "model_files": {"model": os.path.basename(model_file), "metadata": os.path.basename(metadata_file), "classifier": os.path.basename(classifier_file) if os.path.exists(classifier_file) else None},
        "split_method": split_method,
        "split_policy_version": "session-cross-validation-v1" if primary_evaluation == "session_cross_validation" else "session-holdout-v1",
        "threshold_policy": {"decision_function": "final_decision_from_metrics", "risk_sensitivity_default": str(metadata.get("risk_sensitivity_default") or "balanced")},
        "feature_schema": {"version": str(metadata.get("feature_schema_version") or "single-scale-v1"), "window_strategy": str(metadata.get("feature_window_strategy") or "single_scale"), "active_window_scales": [float(scale) for scale in (metadata.get("active_window_scales") or [metadata.get("window_seconds") or 0.0]) if scale], "window_step_seconds": float(metadata.get("window_step_seconds") or 0.0), "predict_window_step_seconds": float(metadata.get("predict_window_step_seconds") or 0.0), "per_scale_sample_counts": dict(metadata.get("per_scale_sample_counts") or {})},
        "sequence_features": {"version": (((metadata.get("sequence_features") or {}).get("version"))), "enabled": bool(((metadata.get("sequence_features") or {}).get("enabled", False))), "families_enabled": list(((metadata.get("sequence_features") or {}).get("families_enabled") or [])), "feature_counts": dict(((metadata.get("sequence_features") or {}).get("feature_counts") or {})), "lookback_windows": int(((metadata.get("sequence_features") or {}).get("lookback_windows") or 0))},
        "context_router": {"version": str((metadata.get("context_router") or {}).get("version") or "disabled"), "enabled": bool((metadata.get("context_router") or {}).get("enabled")), "active_contexts": list(((metadata.get("context_models") or {}).get("active_contexts") or [])), "global_fallback_enabled": bool(((metadata.get("context_router") or {}).get("global_fallback_enabled"))), "min_confidence": float(((metadata.get("context_router") or {}).get("min_confidence") or 0.0)), "context_sample_counts": dict(((metadata.get("context_models") or {}).get("context_sample_counts") or {}))},
        "transition_policy": {"version": (((metadata.get("transition_policy") or {}).get("version"))), "enabled": bool(((metadata.get("transition_policy") or {}).get("enabled", False))), "session_start_seconds": float(((metadata.get("transition_policy") or {}).get("session_start_seconds") or 0.0)), "post_idle_gap_seconds": float(((metadata.get("transition_policy") or {}).get("post_idle_gap_seconds") or 0.0)), "activity_shift_threshold": float(((metadata.get("transition_policy") or {}).get("activity_shift_threshold") or 0.0)), "runtime_transition_status": ((metadata.get("transition_policy") or {}).get("runtime_transition_status"))},
        "transition_training": dict((metadata.get("transition_training") or {})),
        "supervised_classifier": {"selection_version": (((metadata.get("supervised_classifier") or {}).get("selection_version"))), "enabled": bool(((metadata.get("supervised_classifier") or {}).get("enabled"))), "selected_family": ((metadata.get("supervised_classifier") or {}).get("selected_family")), "baseline_family": ((metadata.get("supervised_classifier") or {}).get("baseline_family")), "challenger_family": ((metadata.get("supervised_classifier") or {}).get("challenger_family")), "selection_reason": ((metadata.get("supervised_classifier") or {}).get("selection_reason")), "selection_metric": ((metadata.get("supervised_classifier") or {}).get("selection_metric")), "validation_split": dict(((metadata.get("supervised_classifier") or {}).get("validation_split") or {})), "head_to_head": dict(((metadata.get("supervised_classifier") or {}).get("head_to_head") or {})), "hyperparameters": dict(((metadata.get("supervised_classifier") or {}).get("hyperparameters") or {}))},
        "user_calibration": {"version": (((metadata.get("user_calibration") or {}).get("version"))), "enabled": bool(((metadata.get("user_calibration") or {}).get("enabled"))), "maturity_flag": bool(((metadata.get("user_calibration") or {}).get("maturity_flag"))), "maturity_reason": ((metadata.get("user_calibration") or {}).get("maturity_reason")), "positive_session_count": int(((metadata.get("user_calibration") or {}).get("positive_session_count") or 0)), "positive_window_samples": int(((metadata.get("user_calibration") or {}).get("positive_window_samples") or 0)), "safe_band": dict(((metadata.get("user_calibration") or {}).get("safe_band") or {})), "warning_band": dict(((metadata.get("user_calibration") or {}).get("warning_band") or {}))},
        "deep_sequence": {"available": bool((metadata.get("deep_sequence_training") or {}).get("artifact_written")), "status": ((metadata.get("deep_sequence_training") or {}).get("status")), "artifact_file": ((metadata.get("deep_sequence_training") or {}).get("artifact_file")), "framework": ((metadata.get("deep_sequence_training") or {}).get("framework")), "train_metrics": dict(((metadata.get("deep_sequence_training") or {}).get("train_metrics") or {})), "validation_metrics": dict(((metadata.get("deep_sequence_training") or {}).get("validation_metrics") or {})), "sequence_data": dict((metadata.get("sequence_data") or {})), "runtime_enabled": bool(((metadata.get("deep_runtime") or {}).get("deep_sequence_runtime_enabled")))},
        "dataset": {
            "positive_sessions": [facade._safe_session_name(path) for path in positive_list],
            "negative_sessions": [facade._safe_session_name(path) for path in negative_list],
            "split_plan": {key: [facade._safe_session_name(path) for path in value] for key, value in split_plan.items()},
            "cross_validation_folds": [{"fold_index": int(split.get("fold_index") or 0), "train_positive_sessions": [facade._safe_session_name(path) for path in list(split.get("train_positive_sessions") or [])], "test_positive_sessions": [facade._safe_session_name(path) for path in list(split.get("test_positive_sessions") or [])], "train_negative_sessions": [facade._safe_session_name(path) for path in list(split.get("train_negative_sessions") or [])], "test_negative_sessions": [facade._safe_session_name(path) for path in list(split.get("test_negative_sessions") or [])]} for split in cv_splits],
            "training_selection": dict(training_selection or {}),
        },
        "warnings": warnings,
        "evaluations": evaluations,
        "primary_evaluation": primary_evaluation,
        "hybrid_scoring": dict(((evaluations.get(primary_evaluation) or {}).get("hybrid_shadow_metrics") or {})),
    }
    primary_result = evaluations.get(primary_evaluation) if isinstance(evaluations, Mapping) else None
    primary_sessions = (primary_result or {}).get("session_results") if isinstance(primary_result, Mapping) else []
    beta_coverage = {}
    if isinstance(training_selection, Mapping):
        beta_coverage = dict(training_selection.get("beta_coverage") or {})
    if not beta_coverage:
        beta_coverage = dict((metadata.get("beta_coverage") or {})) if isinstance(metadata, Mapping) else {}
    report["safety_metrics"] = facade.calculate_user_facing_safety_metrics(primary_sessions or [], beta_coverage=beta_coverage)
    report["closed_beta"] = {
        "checklist_version": "closed-beta-safety-v1",
        "target_user_count": "20-50",
        "required_platform": "Windows",
        "requires_dpi_variation": True,
        "requires_keyboard_layout_variation": True,
        "requires_language_context_variation": True,
        "conservative_false_lock_target": "zero_or_near_zero",
    }
    if current_production is not None:
        evaluations["current_production_bundle"] = current_production
        candidate_metrics = dict(((evaluations.get(primary_evaluation) or {}).get("metrics") or {}))
        production_metrics = dict((current_production.get("metrics") or {}))
        report["current_production_comparison"] = {"available": True, "reference_scope": "primary_evaluation_reference_pool", "candidate_primary_evaluation": primary_evaluation, "candidate_metrics": candidate_metrics, "production_metrics": production_metrics, "delta_vs_current_production": {"auc": (candidate_metrics.get("auc") - production_metrics.get("auc")) if candidate_metrics.get("auc") is not None and production_metrics.get("auc") is not None else None, "f1": float(candidate_metrics.get("f1") or 0.0) - float(production_metrics.get("f1") or 0.0), "far": float(candidate_metrics.get("far") or 0.0) - float(production_metrics.get("far") or 0.0), "frr": float(candidate_metrics.get("frr") or 0.0) - float(production_metrics.get("frr") or 0.0)}}
    else:
        report["current_production_comparison"] = {"available": False}

    production_evidence_summaries = _production_evidence_summaries(
        metadata=metadata,
        training_selection=training_selection,
    )
    production_evidence_summaries.setdefault("candidate_artifact_digest", _sha256_file_digest(model_file))
    if current_production is not None:
        production_evidence_summaries.setdefault("baseline_artifact_digest", _sha256_json_digest(current_production))
    production_evidence_summaries.setdefault(
        "evaluation_report_digest",
        _sha256_json_digest({key: value for key, value in report.items() if key != "production_evidence"}),
    )
    production_evidence_summaries.setdefault("runtime_schema_version", str(report.get("feature_schema", {}).get("version") or ""))
    try:
        from metadata_core.production_evidence_pipeline import build_production_evidence_report_for_user

        report["production_evidence"] = build_production_evidence_report_for_user(
            str(user_id or ""),
            candidate_artifact_digest=str(production_evidence_summaries.get("candidate_artifact_digest") or ""),
            baseline_artifact_digest=str(production_evidence_summaries.get("baseline_artifact_digest") or ""),
            evaluation_report_digest=str(production_evidence_summaries.get("evaluation_report_digest") or ""),
            runtime_schema_version=str(production_evidence_summaries.get("runtime_schema_version") or ""),
            explicit_summaries=production_evidence_summaries,
        ).to_dict()
    except Exception:
        # Fail closed: if the real evidence ledger cannot be read in this
        # environment, preserve the existing missing/partial evidence behavior.
        report["production_evidence"] = build_production_evidence_report_from_summaries(production_evidence_summaries).to_dict()

    summary_text = facade._build_summary_markdown(report)
    if output_dir:
        report_paths = facade._write_evaluation_files(output_dir, report, summary_text)
        beta_report_path = os.path.join(output_dir, facade.BETA_EVALUATION_REPORT_FILENAME)
        facade.atomic_write_text(beta_report_path, facade.build_closed_beta_report(report))
        report["report_files"] = {
            "evaluation_report": os.path.basename(report_paths["report_path"]),
            "evaluation_summary": os.path.basename(report_paths["summary_path"]),
            "closed_beta_report": os.path.basename(beta_report_path),
        }
        facade.atomic_write_text(report_paths["report_path"], json.dumps(report, indent=2, ensure_ascii=False))
    facade._emit_evaluation_progress(progress_callback, 1.0, "training_detail_writing_reports")
    return report
