from __future__ import annotations

import importlib
import json
import os
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent


def configure_headless_env() -> None:
    if os.name != 'nt' and not str(os.environ.get('DISPLAY', '') or '').strip():
        os.environ.setdefault('PYNPUT_BACKEND', 'dummy')
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _json_default(value: Any):
    if isinstance(value, (set, tuple)):
        return list(value)
    return str(value)


def run_packaging_selfcheck() -> int:
    configure_headless_env()
    checks: list[tuple[str, bool, str]] = []
    def record(name: str, ok: bool, detail: str = '') -> None:
        checks.append((name, ok, detail))
    for name, path in {
        'runtime support module': ROOT / 'build_tools' / 'packaged_runtime_support.py',
        'deep runtime module': ROOT / 'deep_runtime.py',
        'deep sequence inference': ROOT / 'deep_sequence' / 'inference.py',
    }.items():
        record(name, path.exists(), str(path))
    for mod in ('deep_runtime', 'deep_sequence.inference', 'deep_sequence.models', 'artifact_integrity', 'update_client', 'bio_platform.startup', 'release_runtime'):
        try:
            importlib.import_module(mod)
            record(f'{mod} import', True)
        except Exception as exc:
            record(f'{mod} import', False, str(exc))
    for name, path in {
        'QML Main.qml': ROOT / 'qml' / 'Main.qml',
        'QML theme directory': ROOT / 'qml' / 'theme',
        'onboarding assets': ROOT / 'config' / 'onboarding_assets',
        'BioAuth icon': ROOT / 'bioauth.ico',
        'runtime metadata directory': ROOT / 'model_runtime',
    }.items():
        record(name, path.exists(), str(path))
    try:
        import PySide6  # noqa: F401
        from PySide6.QtQml import QQmlApplicationEngine  # noqa: F401
        record('PySide6/QML runtime import', True)
    except Exception as exc:
        record('PySide6/QML runtime import', False, str(exc))
    for mod in ('sklearn', 'joblib', 'threadpoolctl'):
        try:
            importlib.import_module(mod)
            record(f'{mod} ML import', True)
        except Exception as exc:
            record(f'{mod} ML import', False, str(exc))
    for mod in ('lightgbm', 'torch', 'cv2'):
        try:
            importlib.import_module(mod)
            record(f'{mod} optional import', True)
        except Exception as exc:
            # Optional profiles may omit these packages. The release-readiness report
            # exposes the state without failing classic-minimal packages.
            record(f'{mod} optional import', True, f'optional unavailable: {exc.__class__.__name__}')
    try:
        from release_runtime import runtime_path_report
        path_report = runtime_path_report()
        record('user-writable runtime data dir', bool(path_report.get('data_dir_writable')), str(path_report.get('data_dir')))
        record('runtime data outside install root', bool(path_report.get('data_dir_outside_runtime_base')), str(path_report.get('runtime_base_dir')))
        record('release diagnostics outside install root', bool(path_report.get('event_log_outside_runtime_base')), str(path_report.get('release_event_log_file')))
    except Exception as exc:
        record('release runtime path report', False, str(exc))
    failed = False
    print('== BioAuth packaging self-check ==')
    for name, ok, detail in checks:
        state = 'OK' if ok else 'FAIL'
        suffix = f' :: {detail}' if detail else ''
        print(f'[{state}] {name}{suffix}')
        failed = failed or (not ok)
    return 1 if failed else 0


def _runtime_meta(*, artifact_name: str, rollout_status: str = 'hybrid_ready', production_enabled: bool = True, shadow_only: bool = False, preferred_backend: str = 'pytorch_cpu') -> dict:
    allowed_modes = ['classic', 'auto', 'hybrid']
    if rollout_status == 'accelerated_ready':
        allowed_modes.append('hybrid_accelerated')
    return {
        'rollout_status': rollout_status,
        'rollout_details': {
            'rollout_status': rollout_status,
            'production_decision_enabled': bool(production_enabled),
            'shadow_diagnostics_enabled': True,
            'rollback_to_classic_on_failure': True,
            'allowed_modes': allowed_modes,
            'preferred_mode': 'hybrid_accelerated' if rollout_status == 'accelerated_ready' else ('hybrid' if production_enabled else 'classic'),
            'preferred_backend': preferred_backend,
            'blocked_reason': None if production_enabled else 'shadow_only_policy',
        },
        'deep_runtime': {
            'deep_sequence_runtime_enabled': True,
            'runtime_shadow_only': bool(shadow_only),
            'runtime_decision_influence_enabled': bool(production_enabled),
            'runtime_shadow_diagnostics_enabled': True,
            'runtime_rollback_to_classic_on_failure': True,
            'runtime_rollout_stage': rollout_status,
            'sequence_model': {'enabled': True, 'artifact': artifact_name, 'sequence_length': 4},
        },
        'artifacts': {'sequence_model': artifact_name},
    }


def _write_sequence_artifact(path: str, *, valid: bool = True) -> None:
    from artifact_integrity import save_sequence_model_artifact
    from deep_sequence.models import SequenceCnnLstm
    if valid:
        model = SequenceCnnLstm(feature_dim=2)
        payload = {'feature_names': ['f1', 'f2'], 'model_config': {'feature_dim': 2, 'sequence_length': 4}, 'state_dict': model.state_dict()}
    else:
        payload = {'feature_names': ['f1', 'f2'], 'model_config': {'feature_dim': 2, 'sequence_length': 4}, 'state_dict': {}}
    save_sequence_model_artifact(path, payload)


def _window_samples() -> list[dict[str, float]]:
    return [
        {'sequence_window_index': 0, 'window_start_offset': 0.0, 'f1': 1.0, 'f2': 2.0},
        {'sequence_window_index': 1, 'window_start_offset': 1.0, 'f1': 2.0, 'f2': 3.0},
        {'sequence_window_index': 2, 'window_start_offset': 2.0, 'f1': 3.0, 'f2': 4.0},
        {'sequence_window_index': 3, 'window_start_offset': 3.0, 'f1': 4.0, 'f2': 5.0},
    ]


def _evaluate_runtime_case(*, settings: dict, meta: dict, metadata_file: str, window_samples: list[dict[str, float]]) -> dict:
    from deep_runtime import resolve_runtime_rollout_state
    from deep_sequence.inference import run_shadow_sequence_scoring
    state = resolve_runtime_rollout_state(settings, runtime_metadata=meta)
    response = run_shadow_sequence_scoring(window_samples=window_samples, metadata_file=metadata_file, meta=meta, runtime_state=state)
    if bool(state.get('production_decision_enabled')) and bool(response.get('used')):
        decision_source = 'hybrid_production'
    elif bool(state.get('production_decision_enabled')) and bool(state.get('rollback_to_classic_on_failure')):
        decision_source = 'classic_rollback'
    else:
        decision_source = 'classic'
    return {'state': state, 'response': response, 'decision_source': decision_source}


def run_runtime_smoke_selfcheck() -> int:
    configure_headless_env()
    scenarios: list[dict[str, Any]] = []
    def record(name: str, ok: bool, **detail: Any) -> None:
        payload = {'name': name, 'ok': bool(ok)}
        payload.update(detail)
        scenarios.append(payload)
    with tempfile.TemporaryDirectory(prefix='bioauth_smoke_') as tmpdir:
        settings_hybrid = {'deep_runtime_mode': 'hybrid', 'deep_runtime_manual_override': True, 'deep_runtime_benchmark': {'status': 'ok', 'recommended_mode': 'hybrid', 'recommended_backend': 'classic'}}
        settings_auto = {'deep_runtime_mode': 'auto', 'deep_runtime_manual_override': False, 'deep_runtime_benchmark': {'status': 'not_run', 'recommended_mode': 'classic', 'recommended_backend': 'classic'}}
        settings_accel = {'deep_runtime_mode': 'hybrid_accelerated', 'deep_runtime_manual_override': True, 'deep_runtime_benchmark': {'status': 'ok', 'recommended_mode': 'hybrid_accelerated', 'recommended_backend': 'openvino', 'backend_inventory': {'preferred_backend': 'classic', 'available_backends': ['classic'], 'accelerated_available': False}}}
        good_artifact = os.path.join(tmpdir, 'sequence_model.pt')
        _write_sequence_artifact(good_artifact, valid=True)
        good_meta = _runtime_meta(artifact_name=os.path.basename(good_artifact), rollout_status='hybrid_ready', production_enabled=True, shadow_only=False)
        good_meta_file = os.path.join(tmpdir, 'good_meta.json')
        Path(good_meta_file).write_text(json.dumps(good_meta), encoding='utf-8')
        good_case = _evaluate_runtime_case(settings=settings_hybrid, meta=good_meta, metadata_file=good_meta_file, window_samples=_window_samples())
        record('hybrid_ready_runtime', good_case['decision_source'] == 'hybrid_production', decision_source=good_case['decision_source'])
        missing_meta = _runtime_meta(artifact_name='missing_sequence_model.pt', rollout_status='hybrid_ready', production_enabled=True, shadow_only=False)
        missing_file = os.path.join(tmpdir, 'missing_meta.json')
        Path(missing_file).write_text(json.dumps(missing_meta), encoding='utf-8')
        missing_case = _evaluate_runtime_case(settings=settings_hybrid, meta=missing_meta, metadata_file=missing_file, window_samples=_window_samples())
        record('missing_artifact_fallback', missing_case['decision_source'] == 'classic_rollback', reason=(missing_case['response'] or {}).get('reason'))
        corrupt_artifact = os.path.join(tmpdir, 'corrupt_sequence_model.pt')
        Path(corrupt_artifact).write_bytes(b'not-a-valid-sequence-artifact')
        corrupt_meta = _runtime_meta(artifact_name=os.path.basename(corrupt_artifact), rollout_status='hybrid_ready', production_enabled=True, shadow_only=False)
        corrupt_file = os.path.join(tmpdir, 'corrupt_meta.json')
        Path(corrupt_file).write_text(json.dumps(corrupt_meta), encoding='utf-8')
        corrupt_case = _evaluate_runtime_case(settings=settings_hybrid, meta=corrupt_meta, metadata_file=corrupt_file, window_samples=_window_samples())
        record('corrupted_artifact_fallback', corrupt_case['decision_source'] == 'classic_rollback', reason=(corrupt_case['response'] or {}).get('reason'))
        invalid_meta = {'bundle_role': 'production'}
        invalid_file = os.path.join(tmpdir, 'invalid_meta.json')
        Path(invalid_file).write_text(json.dumps(invalid_meta), encoding='utf-8')
        invalid_case = _evaluate_runtime_case(settings=settings_hybrid, meta=invalid_meta, metadata_file=invalid_file, window_samples=_window_samples())
        record('invalid_metadata_guard', invalid_case['decision_source'] == 'classic', reason=(invalid_case['response'] or {}).get('reason'))
        accel_meta = _runtime_meta(artifact_name=os.path.basename(good_artifact), rollout_status='accelerated_ready', production_enabled=True, shadow_only=False, preferred_backend='openvino')
        accel_file = os.path.join(tmpdir, 'accel_meta.json')
        Path(accel_file).write_text(json.dumps(accel_meta), encoding='utf-8')
        accel_case = _evaluate_runtime_case(settings=settings_accel, meta=accel_meta, metadata_file=accel_file, window_samples=_window_samples())
        record('accelerated_backend_unavailable', accel_case['decision_source'] == 'classic', activation_reason=(accel_case['state'] or {}).get('runtime_activation_reason'))
        auto_case = _evaluate_runtime_case(settings=settings_auto, meta=good_meta, metadata_file=good_meta_file, window_samples=_window_samples())
        record('benchmark_unavailable_auto_fallback', auto_case['decision_source'] == 'classic', activation_reason=(auto_case['state'] or {}).get('runtime_activation_reason'))
        bad_artifact = os.path.join(tmpdir, 'bad_sequence_model.pt')
        _write_sequence_artifact(bad_artifact, valid=False)
        bad_meta = _runtime_meta(artifact_name=os.path.basename(bad_artifact), rollout_status='hybrid_ready', production_enabled=True, shadow_only=False)
        bad_file = os.path.join(tmpdir, 'bad_meta.json')
        Path(bad_file).write_text(json.dumps(bad_meta), encoding='utf-8')
        bad_case = _evaluate_runtime_case(settings=settings_hybrid, meta=bad_meta, metadata_file=bad_file, window_samples=_window_samples())
        record('deep_runtime_exception_fallback', bad_case['decision_source'] == 'classic_rollback', reason=(bad_case['response'] or {}).get('reason'))
    ok = all(item.get('ok') for item in scenarios)
    print(json.dumps({'ok': ok, 'scenarios': scenarios}, ensure_ascii=False, default=_json_default))
    return 0 if ok else 1


def run_release_readiness_selfcheck() -> int:
    configure_headless_env()
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, **detail: Any) -> None:
        item = {'name': name, 'ok': bool(ok)}
        item.update(detail)
        checks.append(item)

    try:
        from release_runtime import runtime_path_report, startup_protected_session_decision
        report = runtime_path_report()
        record('runtime_paths_user_writable', bool(report.get('data_dir_writable')), data_dir=report.get('data_dir'))
        record('runtime_paths_not_install_dir', bool(report.get('data_dir_outside_runtime_base')) and bool(report.get('event_log_outside_runtime_base')), runtime_base_dir=report.get('runtime_base_dir'))
        denied = startup_protected_session_decision(settings={'run_on_startup': True, 'remember_login_enabled': True, 'startup_protected_sessions_enabled': False}, background=True, authenticated=True, has_current_consent=True, profile={'production_ready': True, 'model_status': 'approved_for_production'}, flow='idle')
        allowed = startup_protected_session_decision(settings={'run_on_startup': True, 'remember_login_enabled': True, 'startup_protected_sessions_enabled': True}, background=True, authenticated=True, has_current_consent=True, profile={'production_ready': True, 'model_status': 'approved_for_production'}, flow='idle')
        record('startup_protected_sessions_fail_closed_without_explicit_setting', not bool(denied.get('allowed')), reason=denied.get('reason'))
        record('startup_protected_sessions_allowed_only_with_valid_state', bool(allowed.get('allowed')), reason=allowed.get('reason'))
    except Exception as exc:
        record('release_runtime_helpers', False, error=str(exc))

    for mod in ('update_client', 'bio_platform.startup', 'app_settings', 'persistent_login'):
        try:
            importlib.import_module(mod)
            record(f'{mod}_import', True)
        except Exception as exc:
            record(f'{mod}_import', False, error=str(exc))

    qml_files = sorted((ROOT / 'qml').rglob('*.qml')) if (ROOT / 'qml').exists() else []
    record('qml_inventory_present', len(qml_files) > 0, qml_file_count=len(qml_files))
    record('qml_main_present', (ROOT / 'qml' / 'Main.qml').is_file(), path=str(ROOT / 'qml' / 'Main.qml'))
    record('update_manifest_generator_present', (ROOT / 'build_tools' / 'generate_update_manifest.py').is_file())
    record('packaged_smoke_script_present', (ROOT / 'build_tools' / 'packaged_smoke.py').is_file())

    try:
        from build_tools.release_validation import build_release_validation_report
        validation = build_release_validation_report(strict_production=False)
        record(
            'commercial_release_validation_gate',
            bool(validation.get('ok')),
            error_count=validation.get('error_count'),
            warning_count=validation.get('warning_count'),
            check_count=validation.get('check_count'),
        )
    except Exception as exc:
        record('commercial_release_validation_gate', False, error=str(exc))

    ok = all(item.get('ok') for item in checks)
    print(json.dumps({'ok': ok, 'checks': checks}, ensure_ascii=False, default=_json_default))
    return 0 if ok else 1


def run_packaging_performance_check() -> int:
    configure_headless_env()
    from deep_runtime import resolve_runtime_rollout_state
    from deep_sequence.inference import load_runtime_sequence_model, run_shadow_sequence_scoring
    from deep_sequence.models import _torch_runtime
    started = time.perf_counter()
    torch_before = _torch_runtime.cache_info().currsize
    with tempfile.TemporaryDirectory(prefix='bioauth_perf_') as tmpdir:
        artifact = os.path.join(tmpdir, 'sequence_model.pt')
        _write_sequence_artifact(artifact, valid=True)
        meta = _runtime_meta(artifact_name=os.path.basename(artifact), rollout_status='hybrid_ready', production_enabled=True, shadow_only=False)
        metadata_file = os.path.join(tmpdir, 'meta.json')
        Path(metadata_file).write_text(json.dumps(meta), encoding='utf-8')
        state = resolve_runtime_rollout_state({'deep_runtime_mode': 'hybrid', 'deep_runtime_manual_override': True, 'deep_runtime_benchmark': {'status': 'ok', 'recommended_mode': 'hybrid', 'recommended_backend': 'classic'}}, runtime_metadata=meta)
        tracemalloc.start()
        try:
            load_started = time.perf_counter()
            model_info = load_runtime_sequence_model(metadata_file=metadata_file, meta=meta, runtime_state=state)
            load_ms = (time.perf_counter() - load_started) * 1000.0
            latencies = []
            last_response = {}
            for _ in range(5):
                infer_started = time.perf_counter()
                last_response = run_shadow_sequence_scoring(window_samples=_window_samples(), metadata_file=metadata_file, meta=meta, runtime_state=state)
                latencies.append((time.perf_counter() - infer_started) * 1000.0)
            current_mem, peak_mem = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        torch_after = _torch_runtime.cache_info().currsize
    p95_index = max(0, min(len(latencies) - 1, int(round((len(latencies) - 1) * 0.95)))) if latencies else 0
    metrics = {'startup_probe_ms': round((time.perf_counter() - started) * 1000.0, 3), 'deferred_torch_before': int(torch_before), 'deferred_torch_after': int(torch_after), 'model_loading_ms': round(float(load_ms), 3), 'inference_p95_ms': round(float(sorted(latencies)[p95_index] if latencies else 0.0), 3), 'inference_samples_ms': [round(float(v), 3) for v in latencies], 'memory_peak_mb': round(float(max(current_mem, peak_mem)) / float(1024 ** 2), 3), 'runtime_model_loaded': bool(model_info.get('loaded')), 'runtime_inference_used': bool(last_response.get('used'))}
    limits = {'startup_probe_ms': 9000.0, 'model_loading_ms': 2500.0, 'inference_p95_ms': 1200.0, 'memory_peak_mb': 256.0}
    ok = metrics['runtime_model_loaded'] and metrics['runtime_inference_used'] and metrics['deferred_torch_before'] == 0 and metrics['deferred_torch_after'] >= 1 and metrics['startup_probe_ms'] <= limits['startup_probe_ms'] and metrics['model_loading_ms'] <= limits['model_loading_ms'] and metrics['inference_p95_ms'] <= limits['inference_p95_ms'] and metrics['memory_peak_mb'] <= limits['memory_peak_mb']
    print(json.dumps({'ok': ok, 'limits': limits, 'metrics': metrics}, ensure_ascii=False, default=_json_default))
    return 0 if ok else 1
