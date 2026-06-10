import json
from pathlib import Path
from hybrid_direct_contract import build_default_hybrid_direct_state, build_hybrid_direct_state
from safety_gate_policy import REQUIRED_GATE_KEYS, build_safety_gate_report, emergency_disable_hybrid_state, render_safety_gate_report_markdown, rollback_to_classic_state, safety_gate_results_for_hybrid_state


def _write_valid_rollback_snapshot(path: Path, *, legacy_names: bool=False) -> Path:
    payload = {
        "version": "classic-rollback-snapshot-v1",
        "created_at": "2026-05-04T20:53:49Z",
        "developer_direct_enabled": False,
    }
    if legacy_names:
        payload.update({"target_mode": "classic_only", "can_influence_device": False})
    else:
        payload.update({"rollback_target": "classic_only", "hybrid_can_influence_device": False})
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path

def test_safety_gates_fail_closed_by_default(tmp_path):
    report = build_safety_gate_report({}, build_default_hybrid_direct_state(), rollback_snapshot_path=tmp_path/'missing.json')
    assert report['developer_direct_enabled'] is False
    assert report['can_influence_device'] is False
    assert report['influence_allowed'] is False
    assert report['status'] == 'fail_closed'
    assert report['experiment_can_lock_alone'] is False
    assert report['no_single_model_can_lock'] is True
    for key in REQUIRED_GATE_KEYS: assert key in report['gate_results']
    assert report['gate_results']['no_single_model_lock_enforced']['passed'] is True
    assert report['gate_results']['timeout_fallback_enabled']['passed'] is True
    assert report['gate_results']['schema_error_fallback_enabled']['passed'] is True

def test_rollback_snapshot_gate_rejects_empty_json_object(tmp_path):
    snap = tmp_path/'rollback.json'; snap.write_text('{}', encoding='utf-8')
    report = build_safety_gate_report({}, {}, rollback_snapshot_path=snap)
    assert report['rollback_snapshot_exists'] is False
    assert report['gate_results']['rollback_snapshot_exists']['passed'] is False

def test_rollback_snapshot_gate_validates_required_content(tmp_path):
    snap = _write_valid_rollback_snapshot(tmp_path/'rollback.json')
    report = build_safety_gate_report({}, {}, rollback_snapshot_path=snap)
    assert report['rollback_snapshot_exists'] is True
    assert report['gate_results']['rollback_snapshot_exists']['passed'] is True
    assert str(snap) in report['gate_results']['rollback_snapshot_exists']['evidence']

def test_rollback_snapshot_gate_accepts_safe_legacy_snapshot_names(tmp_path):
    snap = _write_valid_rollback_snapshot(tmp_path/'rollback.json', legacy_names=True)
    report = build_safety_gate_report({}, {}, rollback_snapshot_path=snap)
    assert report['rollback_snapshot_exists'] is True
    assert report['gate_results']['rollback_snapshot_exists']['passed'] is True

def test_emergency_disable_returns_classic_only_and_preserves_no_lock():
    state = emergency_disable_hybrid_state({'enabled': True, 'can_influence_device': True})
    assert state['enabled'] is False and state['mode'] == 'classic_only'
    assert state['can_influence_device'] is False
    assert state['experiment_can_lock_alone'] is False
    assert state['no_single_model_can_lock'] is True
    assert 'classic_only_fallback_active' in state['reason_codes']

def test_rollback_to_classic_preserves_evidence_and_reports():
    state = rollback_to_classic_state({'enabled': True})
    assert state['enabled'] is False and state['mode'] == 'classic_only'
    assert 'model_evidence_preserved' in state['reason_codes']
    assert 'reports_preserved' in state['reason_codes']

def test_hybrid_state_carries_phase_10_safety_gate_keys(tmp_path):
    snap=_write_valid_rollback_snapshot(tmp_path/'snapshot.json')
    report=build_safety_gate_report({}, {}, rollback_snapshot_path=snap)
    state=build_hybrid_direct_state({'safety_gate_results': safety_gate_results_for_hybrid_state(report)})
    for key in REQUIRED_GATE_KEYS: assert key in state['safety_gate_results']
    assert state['enabled'] is False and state['can_influence_device'] is False

def test_safety_gate_markdown_contains_required_release_evidence(tmp_path):
    snap=_write_valid_rollback_snapshot(tmp_path/'snapshot.json')
    md=render_safety_gate_report_markdown(build_safety_gate_report({}, {}, rollback_snapshot_path=snap))
    assert 'BioAuth Phase 10 Safety Gate Report' in md
    assert 'evaluation_harness_passed' in md
    assert 'timeout_fallback_enabled' in md
    assert 'Developer Direct remains OFF by default' in md

def test_qml_safety_gate_card_is_backend_display_only():
    qml=Path('qml/pages/settings/SettingsSecurityTab.qml').read_text(encoding='utf-8')
    assert 'backend.safetyGateReport' in qml
    assert 'backend.emergencyDisableHybrid()' in qml
    assert 'backend.rollbackToClassic()' in qml
    assert 'backend.writeSafetyGateReport()' in qml
    for token in ['evaluation_harness_passed =','thresholds_calibrated =','face_confirmation_enabled =','influence_allowed =','productionReady','protectedSessionsAvailable','computeFusion']:
        assert token not in qml

def test_desktop_exposes_backend_owned_safety_slots_and_property():
    src=Path('desktop_app.py').read_text(encoding='utf-8')
    for token in ['safetyGateReportChanged = Signal()','def safetyGateReport','def emergencyDisableHybrid','def rollbackToClassic','def writeSafetyGateReport','developer_direct_test_enabled=False','hybrid_can_influence_device=False','deep_runtime_mode="classic"']:
        assert token in src
