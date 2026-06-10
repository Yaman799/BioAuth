from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / 'dist'
BUILD_DIR = ROOT / 'build'
SPEC_FILE = ROOT / 'BioAuth.spec'
SMOKE_ENTRY = ROOT / 'build_tools' / 'packaged_smoke_entry.py'
REPORT_FILE = ROOT / 'packaged_smoke_report.json'


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault('PYNPUT_BACKEND', 'dummy')
    env.setdefault('QT_QPA_PLATFORM', 'offscreen')
    env.setdefault('BIOAUTH_BUILD_WITH_HYBRID', '1')
    return env


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd or ROOT), env=_env(), text=True, capture_output=True)


def _binary_path(profile: str) -> Path:
    name = 'BioAuth' if profile == 'full_app' else 'BioAuthSmoke'
    if os.name == 'nt':
        return DIST_DIR / name / f'{name}.exe'
    return DIST_DIR / name / name


def _build(profile: str) -> Dict[str, Any]:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    started = time.perf_counter()
    if profile == 'full_app':
        cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', str(SPEC_FILE)]
    else:
        cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', str(SMOKE_ENTRY), '--name', 'BioAuthSmoke', '--console', '--paths', str(ROOT), '--exclude-module', 'torch', '--hidden-import', 'build_tools.packaged_runtime_support', '--hidden-import', 'deep_runtime', '--hidden-import', 'artifact_integrity', '--hidden-import', 'deep_sequence.inference', '--hidden-import', 'deep_sequence.models', '--collect-submodules', 'deep_sequence', '--collect-submodules', 'metadata_core']
    proc = _run(cmd)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {'profile': profile, 'ok': proc.returncode == 0, 'returncode': proc.returncode, 'elapsed_ms': round(elapsed_ms, 3), 'stdout_tail': proc.stdout[-4000:], 'stderr_tail': proc.stderr[-4000:], 'binary': str(_binary_path(profile))}


def _run_binary(profile: str, flag: str) -> Dict[str, Any]:
    binary = _binary_path(profile)
    started = time.perf_counter()
    proc = _run([str(binary), flag])
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    payload: Dict[str, Any] | None = None
    stdout = proc.stdout.strip()
    if stdout:
        for line in reversed(stdout.splitlines()):
            stripped = line.strip()
            if stripped.startswith('{') and stripped.endswith('}'):
                try:
                    payload = json.loads(stripped)
                    break
                except Exception:
                    continue
    return {'ok': proc.returncode == 0, 'returncode': proc.returncode, 'elapsed_ms': round(elapsed_ms, 3), 'stdout_tail': proc.stdout[-4000:], 'stderr_tail': proc.stderr[-4000:], 'json': payload}


def main() -> int:
    build_attempts = []
    selected_profile = None
    for profile in ('full_app', 'smoke_entry'):
        build = _build(profile)
        build_attempts.append(build)
        if bool(build.get('ok')) and Path(build.get('binary') or '').exists():
            selected_profile = profile
            break
    results: Dict[str, Any] = {'build_attempts': build_attempts, 'selected_profile': selected_profile}
    ok = selected_profile is not None
    if ok and selected_profile is not None:
        if selected_profile == 'full_app':
            results['packaging_selfcheck'] = _run_binary(selected_profile, '--self-check-packaging')
        else:
            results['packaging_selfcheck'] = {'ok': True, 'skipped': True, 'reason': 'smoke_entry_profile'}
        results['runtime_smoke'] = _run_binary(selected_profile, '--self-check-runtime-smoke')
        results['release_readiness'] = _run_binary(selected_profile, '--self-check-release-readiness')
        results['performance'] = _run_binary(selected_profile, '--self-check-performance')
        ok = all(bool((results.get(name) or {}).get('ok')) for name in ('packaging_selfcheck', 'runtime_smoke', 'release_readiness', 'performance'))
    results['ok'] = ok
    REPORT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
