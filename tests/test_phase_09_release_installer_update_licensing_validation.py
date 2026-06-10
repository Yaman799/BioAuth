from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from build_tools.release_validation import build_release_validation_report, validate_release_config

ROOT = Path(__file__).resolve().parent.parent


def test_phase9_release_validation_report_passes_source_template_with_warning() -> None:
    report = build_release_validation_report(strict_production=False)
    assert report["ok"] is True
    assert report["error_count"] == 0
    assert report["check_count"] >= 25
    names = {item["name"] for item in report["checks"]}
    assert "build_exe_runs_release_readiness_selfcheck" in names
    assert "build_installer_verifies_setup_signature" in names
    assert "update_manifest_roundtrip_validates" in names
    assert "license_invalid_code_falls_back_to_basic" in names
    assert "license_basic_safety_features_preserved" in names


def test_phase9_strict_production_blocks_placeholder_release_config() -> None:
    checks = validate_release_config(ROOT, strict_production=True)
    lookup = {item["name"]: item for item in checks}
    assert lookup["release_config_repo_configured_for_updates"]["ok"] is False
    assert lookup["release_config_repo_configured_for_updates"]["severity"] == "error"
    assert lookup["strict_production_release_config_requires_signing"]["ok"] is False


def test_phase9_release_validation_cli_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "release_validation.json"
    result = subprocess.run(
        [sys.executable, "build_tools/release_validation.py", "--json-output", str(out)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "bioauth-release-validation-v1"
    assert payload["ok"] is True


def test_phase9_packaged_release_readiness_selfcheck_includes_release_validation_gate() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "from build_tools.packaged_runtime_support import run_release_readiness_selfcheck; raise SystemExit(run_release_readiness_selfcheck())"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    names = {item["name"] for item in payload["checks"]}
    assert "commercial_release_validation_gate" in names
