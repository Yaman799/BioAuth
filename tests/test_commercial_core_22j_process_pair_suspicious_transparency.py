from __future__ import annotations

from pathlib import Path

from bioauth_model.scoring import final_decision_from_metrics, resolve_sensitivity_config


def test_suspicious_decision_records_probability_reason_when_risk_is_low() -> None:
    config = resolve_sensitivity_config("balanced")
    metrics = {
        "risk": 19,
        "raw": 0.1,
        "ml_pred": 0,
        "intruder_prob": float(config["multi_suspicious_prob"]) + 0.01,
        "suspicious_windows": 0,
        "severe_windows": 0,
        "classifier_used": True,
        "config": config,
    }
    outcome = final_decision_from_metrics(metrics=metrics, window_count=3)
    assert outcome.final == "suspicious"
    assert outcome.risk == 19
    assert outcome.decision_reason == "multi_suspicious_probability_threshold"
    assert isinstance(outcome.decision_details, dict)
    assert outcome.decision_details["risk_below_suspicious_risk_threshold"] is True
    assert outcome.decision_details["multi_suspicious_risk"] == int(config["multi_suspicious_risk"])


def test_runtime_prediction_exports_decision_transparency_fields() -> None:
    source = Path("src/bioauth/ml/inference.py").read_text(encoding="utf-8")
    assert '"decision_reason": str(outcome.decision_reason or "")' in source
    assert '"decision_details": dict(outcome.decision_details or {})' in source
    monitor = Path("src/bioauth/runtime/monitor_impl.py").read_text(encoding="utf-8")
    assert '"runtime_model_decision_reason"' in monitor
    assert '"runtime_suspicious_transparency"' in monitor


def test_logger_exit_after_ready_stops_monitor_pair() -> None:
    source = Path("bridge/session_mixin.py").read_text(encoding="utf-8")
    assert "def _mark_logger_exited_after_ready" in source
    assert "process_pair_state" in source
    assert "logger_exited_monitor_stopped" in source
    assert "request_stop(\"monitor\")" in source
    assert "_terminate_process_key(" in source
    assert '"status": "logger_exited_after_ready"' in source
    assert "self._is_protected_logger_process_key(str(key))" in source


def test_logger_exit_status_is_treated_as_technical_failure() -> None:
    labels = Path("bridge/runtime_labels.py").read_text(encoding="utf-8")
    assert '"logger_exited_after_ready"' in labels
    assert 'runtime_detail_logger_exited_after_ready' in labels
    dashboard = Path("bridge/refresh_dashboard_helpers.py").read_text(encoding="utf-8")
    assert '"logger_exited_after_ready"' in dashboard
