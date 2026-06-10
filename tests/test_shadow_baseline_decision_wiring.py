from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_pyside6_stub() -> None:
    if "PySide6" in sys.modules:
        return
    core = types.ModuleType("PySide6.QtCore")
    core.QLocale = type("QLocale", (), {"name": lambda self: "en_US"})
    core.QObject = object
    core.Property = lambda *args, **kwargs: (lambda func: func)
    core.QTimer = object
    core.QUrl = type("QUrl", (), {"fromLocalFile": staticmethod(lambda path: path)})
    core.Signal = lambda *args, **kwargs: None
    core.Slot = lambda *args, **kwargs: (lambda func: func)
    gui = types.ModuleType("PySide6.QtGui")
    gui.QDesktopServices = type("QDesktopServices", (), {"openUrl": staticmethod(lambda *_args, **_kwargs: True)})
    gui.QIcon = object
    qml = types.ModuleType("PySide6.QtQml")
    qml.QQmlApplicationEngine = object
    widgets = types.ModuleType("PySide6.QtWidgets")
    widgets.QApplication = object
    widgets.QSystemTrayIcon = object
    widgets.QMenu = object
    pkg = types.ModuleType("PySide6")
    pkg.QtCore = core
    pkg.QtGui = gui
    pkg.QtQml = qml
    pkg.QtWidgets = widgets
    sys.modules["PySide6"] = pkg
    sys.modules["PySide6.QtCore"] = core
    sys.modules["PySide6.QtGui"] = gui
    sys.modules["PySide6.QtQml"] = qml
    sys.modules["PySide6.QtWidgets"] = widgets


_install_pyside6_stub()

from evaluation_core.production_evidence import ProductionEvidenceReasonCode, ProductionEvidenceStatus
from metadata_core import production_evidence_pipeline as pipe
import monitor


def _shadow_runtime_state(**extra):
    payload = {
        "session_id": "shadow-baseline-window",
        "runtime_telemetry_seq": 7,
        "session_kind": "shadow_evidence",
        "runtime_mode": "shadow_evidence",
        "evidence_source": "shadow_evidence_monitor",
        "model_decision": "legit",
        "risk": 10,
        "avg_risk": 10,
        "runtime_quality_ok_windows": 1,
        "runtime_low_quality_windows": 0,
    }
    payload.update(extra)
    return payload


def _append_record(tmp_path: Path, state: dict) -> dict:
    window_id = str(state.get("runtime_telemetry_seq") or state.get("session_id") or "window")
    ledger = tmp_path / f"evidence-{window_id}.jsonl"
    pipe.append_runtime_monitor_evidence_record(
        user_id="owner",
        state=state,
        runtime={
            "metadata": {"runtime_schema_version": "runtime-v1", "artifact_digest": "sha256:candidate"},
            "paths": {},
        },
        prediction={"final": "legit", "status": "ok", "risk": 10},
        ledger_path=str(ledger),
    )
    records = pipe.read_evidence_records("owner", ledger_path=str(ledger))
    assert len(records) == 1
    return records[0]


def test_monitor_shadow_baseline_fields_are_added_from_active_production_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "SHADOW_EVIDENCE_ONLY", True)
    baseline_runtime = {
        "model": object(),
        "metadata": {"artifact_digest": "sha256:baseline"},
        "paths": {},
    }
    monkeypatch.setattr(monitor, "_load_user_runtime_bundle", lambda user_id: baseline_runtime)
    monkeypatch.setattr(monitor, "_predict_runtime", lambda runtime: {"status": "ok", "final": "legit", "risk": 12})

    baseline_fields = monitor._shadow_baseline_evidence_fields_for_user("owner")
    record = _append_record(
        tmp_path,
        _shadow_runtime_state(
            **baseline_fields,
            candidate_would_lock_if_production=True,
        ),
    )

    assert baseline_fields == {
        "baseline_decision": "trusted",
        "baseline_risk": 12,
        "baseline_would_lock_if_production": False,
        "baseline_artifact_digest": "sha256:baseline",
    }
    assert record["baseline_decision"] == "trusted"
    assert record["baseline_risk_bucket"] == "low"
    assert record["baseline_would_lock_if_production"] is False
    assert record["candidate_would_lock_if_production"] is True


def test_monitor_does_not_fabricate_baseline_when_production_runtime_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "SHADOW_EVIDENCE_ONLY", True)
    monkeypatch.setattr(monitor, "_load_user_runtime_bundle", lambda user_id: None)

    baseline_fields = monitor._shadow_baseline_evidence_fields_for_user("owner")
    record = _append_record(tmp_path, _shadow_runtime_state(**baseline_fields))

    assert baseline_fields == {}
    assert record["baseline_decision"] == ""
    assert ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING in record["reason_codes"]
    summaries = pipe.aggregate_evidence_records([record], runtime_schema_version="runtime-v1")
    assert summaries["pipeline_accepted_record_count"] == 1
    assert summaries["model_comparison_windows"] == []
    assert ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA in summaries["pipeline_reason_codes"]


def test_aggregate_evidence_records_adds_model_window_only_when_baseline_decision_exists(tmp_path):
    comparable = _append_record(
        tmp_path,
        _shadow_runtime_state(
            baseline_decision="trusted",
            baseline_risk=8,
            baseline_would_lock_if_production=False,
            baseline_artifact_digest="sha256:baseline",
        ),
    )
    missing_baseline = _append_record(tmp_path, _shadow_runtime_state(session_id="missing-baseline-window", runtime_telemetry_seq=8))

    with_baseline = pipe.aggregate_evidence_records([comparable], runtime_schema_version="runtime-v1")
    without_baseline = pipe.aggregate_evidence_records([missing_baseline], runtime_schema_version="runtime-v1")
    mixed = pipe.aggregate_evidence_records([comparable, missing_baseline], runtime_schema_version="runtime-v1")

    assert len(with_baseline["model_comparison_windows"]) == 1
    assert with_baseline["model_comparison_windows"][0]["baseline_decision"] == "trusted"
    assert without_baseline["model_comparison_windows"] == []
    assert len(mixed["model_comparison_windows"]) == 1


def test_windows_collected_without_baseline_is_not_sufficient_for_model_agreement(tmp_path):
    record = _append_record(tmp_path, _shadow_runtime_state())

    report = pipe.build_production_evidence_report_from_records([record], runtime_schema_version="runtime-v1")
    summaries = pipe.aggregate_evidence_records([record], runtime_schema_version="runtime-v1")

    assert summaries["pipeline_accepted_record_count"] == 1
    assert summaries["model_comparison_windows"] == []
    assert report.model_agreement.overall_agreement_rate == 0.0
    assert report.model_agreement.trusted_window_agreement_rate == 0.0
    assert report.gate.status is not ProductionEvidenceStatus.PASS
    assert ProductionEvidenceReasonCode.BASELINE_DECISION_MISSING in report.gate.reason_codes
    assert ProductionEvidenceReasonCode.INSUFFICIENT_MODEL_AGREEMENT_DATA in report.gate.reason_codes
