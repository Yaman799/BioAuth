from __future__ import annotations

import json
import os
from importlib import import_module
from typing import Dict, Mapping


def _facade():
    return import_module("model_evaluation")


def _write_evaluation_files(output_dir: str, report: Mapping[str, object], summary_text: str) -> Dict[str, str]:
    facade = _facade()
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, facade.EVALUATION_REPORT_FILENAME)
    summary_path = os.path.join(output_dir, facade.EVALUATION_SUMMARY_FILENAME)
    facade.atomic_write_text(report_path, json.dumps(report, indent=2, ensure_ascii=False))
    facade.atomic_write_text(summary_path, summary_text)
    return {"report_path": report_path, "summary_path": summary_path}


def _build_summary_markdown(report: Mapping[str, object]) -> str:
    primary_key = str(report.get("primary_evaluation") or "candidate_bundle")
    sections = report.get("evaluations") or {}
    primary = sections.get(primary_key) if isinstance(sections, Mapping) else None
    metrics = primary.get("metrics") if isinstance(primary, Mapping) else {}
    confusion = (metrics.get("confusion_matrix") or {}) if isinstance(metrics, Mapping) else {}
    sample_counts = (metrics.get("sample_counts") or {}) if isinstance(metrics, Mapping) else {}
    thresholds = (metrics.get("thresholds") or {}) if isinstance(metrics, Mapping) else {}
    label_convention = (metrics.get("label_convention") or {}) if isinstance(metrics, Mapping) else {}
    deep_sequence = dict(report.get("deep_sequence") or {}) if isinstance(report, Mapping) else {}
    deep_validation = dict(deep_sequence.get("validation_metrics") or {})
    hybrid_metrics = dict(report.get("hybrid_scoring") or {}) if isinstance(report, Mapping) else {}
    classical_baselines = dict(report.get("classical_baselines") or {}) if isinstance(report, Mapping) else {}
    experimental_deep_verifiers = dict(report.get("experimental_deep_verifiers") or {}) if isinstance(report, Mapping) else {}
    experimental_deep_names = ", ".join(sorted((experimental_deep_verifiers.get("verifiers") or {}).keys())) if isinstance(experimental_deep_verifiers.get("verifiers"), Mapping) else "none"
    classical_names = ", ".join(sorted((classical_baselines.get("baselines") or {}).keys())) if isinstance(classical_baselines.get("baselines"), Mapping) else "none"
    safety = dict(report.get("safety_metrics") or {}) if isinstance(report, Mapping) else {}
    coverage = dict(safety.get("data_coverage") or {})
    return "\n".join([
        "# BioAuth Evaluation Summary",
        "",
        f"- Generated at: {report.get('generated_at')}",
        f"- Primary evaluation: {primary_key}",
        f"- Split method: {report.get('split_method')}",
        f"- Label convention: genuine={label_convention.get('genuine', 0)}, intruder={label_convention.get('intruder', 1)}, score_direction={label_convention.get('score_direction', 'higher_score_more_suspicious')}",
        f"- AUC: {metrics.get('auc')}",
        f"- EER: {metrics.get('eer')}",
        f"- EER threshold: {metrics.get('eer_threshold')}",
        f"- Global threshold: {metrics.get('global_threshold')}",
        f"- Per-user threshold: {metrics.get('per_user_threshold')}",
        f"- F1: {metrics.get('f1')}",
        f"- Precision: {metrics.get('precision')}",
        f"- Recall: {metrics.get('recall')}",
        f"- FAR (false accepts / intruders predicted legitimate): {metrics.get('far')}",
        f"- FRR (false rejects / legitimate sessions flagged): {metrics.get('frr')}",
        f"- Sample counts: total={sample_counts.get('total', metrics.get('session_count'))} genuine={sample_counts.get('genuine', metrics.get('legitimate_session_count'))} intruder={sample_counts.get('intruder', metrics.get('intruder_session_count'))}",
        f"- Threshold calibration available: {thresholds.get('available')}",
        f"- FRR_user: {safety.get('frr_user')}",
        f"- FAR_intruder: {safety.get('far_intruder')}",
        f"- Warnings/hour: {safety.get('warning_per_hour')}",
        f"- Locks/hour: {safety.get('lock_per_hour')}",
        f"- False lock count: {safety.get('false_lock_count')}",
        f"- Low-quality decision rate: {safety.get('low_quality_decision_rate')}",
        f"- Closed beta coverage ready: {coverage.get('closed_beta_ready')}",
        f"- Sessions: {metrics.get('session_count')}",
        f"- Windows: {metrics.get('window_count')}",
        f"- Confusion matrix: TN={confusion.get('tn', 0)} FP={confusion.get('fp', 0)} FN={confusion.get('fn', 0)} TP={confusion.get('tp', 0)}",
        f"- Supervised classifier: {((report.get('supervised_classifier') or {}).get('selected_family'))}",
        f"- Deep sequence status: {deep_sequence.get('status')}",
        f"- Deep sequence artifact: {deep_sequence.get('artifact_file')}",
        f"- Deep sequence validation AUC: {deep_validation.get('auc')}",
        f"- Deep sequence validation F1: {deep_validation.get('f1')}",
        f"- Hybrid shadow AUC: {hybrid_metrics.get('auc')}",
        f"- Hybrid shadow F1: {hybrid_metrics.get('f1')}",
        f"- Classical baselines: {classical_names}",
        f"- Classical baselines score direction: {classical_baselines.get('score_direction')}",
        f"- Classical baselines can lock alone: {classical_baselines.get('can_lock_alone', False)}",
        f"- Experimental deep verifiers: {experimental_deep_names}",
        f"- Experimental deep verifier score direction: {experimental_deep_verifiers.get('score_direction')}",
        f"- Experimental deep verifiers can lock alone: {experimental_deep_verifiers.get('can_lock_alone', False)}",
    ])


def build_closed_beta_report(report: Mapping[str, object], cohort: Mapping[str, object] | None = None) -> str:
    safety = dict(report.get("safety_metrics") or {}) if isinstance(report, Mapping) else {}
    coverage = dict(safety.get("data_coverage") or {})
    cohort = dict(cohort or {})
    counts = dict(safety.get("counts") or {})
    missing = coverage.get("missing") or []
    if isinstance(missing, str):
        missing = [missing]
    missing_text = ", ".join(str(item) for item in missing) if missing else "none"
    return "\n".join([
        "# BioAuth Closed Beta Safety Report",
        "",
        "## Privacy Boundary",
        "- This report contains aggregate/session-level safety metrics only.",
        "- It must not include raw keyboard events, raw mouse events, screenshots, webcam captures, secrets, or feature vectors.",
        f"- Raw biometric data included: {safety.get('raw_biometric_data_included', False)}",
        "",
        "## User-Facing Safety Metrics",
        f"- FRR_user: {safety.get('frr_user')}",
        f"- FAR_intruder: {safety.get('far_intruder')}",
        f"- warning_per_hour: {safety.get('warning_per_hour')}",
        f"- lock_per_hour: {safety.get('lock_per_hour')}",
        f"- false_lock_count: {safety.get('false_lock_count')}",
        f"- time_to_confirm_intruder: {safety.get('time_to_confirm_intruder')}",
        f"- low_quality_decision_rate: {safety.get('low_quality_decision_rate')}",
        f"- startup_post_idle_warning_rate: {safety.get('startup_post_idle_warning_rate')}",
        "",
        "## Counts",
        f"- Decisions: {counts.get('decision_count', 0)}",
        f"- Legitimate decisions: {counts.get('legitimate_decision_count', 0)}",
        f"- Intruder decisions: {counts.get('intruder_decision_count', 0)}",
        f"- Warnings: {counts.get('warning_count', 0)}",
        f"- Locks: {counts.get('lock_count', 0)}",
        "",
        "## Closed Beta Coverage Checklist",
        "- Target users: 20-50",
        "- Required platform: Windows devices",
        "- Required variation: different DPI profiles",
        "- Required variation: different keyboard layouts",
        "- Required variation: language/context variation",
        f"- Observed beta users: {coverage.get('user_count', 0)}",
        f"- Windows devices: {coverage.get('windows_device_count', 0)}",
        f"- DPI profiles: {coverage.get('dpi_profile_count', 0)}",
        f"- Keyboard layouts: {coverage.get('keyboard_layout_count', 0)}",
        f"- Language/context groups: {coverage.get('language_context_count', 0)}",
        f"- Observation hours: {coverage.get('total_observation_hours', 0)}",
        f"- Coverage ready: {coverage.get('closed_beta_ready', False)}",
        f"- Missing coverage: {missing_text}",
        "",
        "## Conservative Runtime Target",
        "- Conservative beta should target false_lock_count = 0 or as close to zero as practically measurable.",
        "- Any false lock in Conservative mode should block commercial readiness until reviewed.",
        "",
        "## Cohort Notes",
        f"- Cohort label: {cohort.get('label', 'not_provided')}",
        f"- Owner/reviewer: {cohort.get('reviewer', 'not_provided')}",
    ])
