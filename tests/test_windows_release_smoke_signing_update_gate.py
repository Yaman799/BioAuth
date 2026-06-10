from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from release_profile import assert_release_profile_safe, production_profile_errors
from update_client import UpdateConfig, validate_update_manifest

ROOT = Path(__file__).resolve().parent.parent


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_windows_release_gate_doc_marks_public_release_blocked_without_evidence() -> None:
    readme = _read("README.md")
    build_readme = _read("docs/developer/BUILD_README.md")
    assert "Production release builds require signing to be enabled" in readme
    assert "Unsigned builds must use a non-production profile" in readme
    assert "Production builds reject dev-only flags and unsigned production artifacts" in build_readme
    assert "BIOAUTH_ENABLE_SIGNING=1" in build_readme
    assert "BIOAUTH_SIGN_CERT_PFX_BASE64" in build_readme
    assert "Production preflight fails early" in build_readme


def test_signature_verification_helper_is_present_and_policy_safe() -> None:
    signer = ROOT / "build_tools" / "sign_windows_artifact.bat"
    verifier = ROOT / "build_tools" / "verify_windows_signature.bat"
    assert signer.is_file()
    assert verifier.is_file()

    sign_text = signer.read_text(encoding="utf-8")
    verify_text = verifier.read_text(encoding="utf-8")
    assert "BIOAUTH_ENABLE_SIGNING" in sign_text
    assert "Signing enabled but no BIOAUTH_SIGN_CERT_SHA1, BIOAUTH_SIGN_CERT_FILE, or BIOAUTH_SIGN_CERT_PFX_BASE64" in sign_text
    assert "BIOAUTH_SIGN_CERT_PFX_BASE64" in sign_text
    assert "exit /b 1" in sign_text
    assert "BIOAUTH_ENABLE_SIGNING" in verify_text
    assert "signtool" in verify_text.lower()
    assert "verify /pa /v" in verify_text
    assert "Public release remains blocked for unsigned artifacts" in verify_text


def test_installer_build_has_interpreter_and_signature_verification() -> None:
    build_exe = _read("build_exe.bat")
    build_installer = _read("build_installer.bat")
    assert '.venv\\Scripts\\python.exe' in build_exe
    assert 'build_tools\\preflight.py' in build_exe
    assert 'build_tools\\sign_windows_artifact.bat "dist\\BioAuth\\BioAuth.exe"' in build_exe
    assert 'build_tools\\sign_windows_artifact.bat "%%I"' in build_installer
    assert 'build_tools\\verify_windows_signature.bat "%%I"' in build_installer


def test_release_workflow_keeps_windows_boundary_and_verifies_signatures() -> None:
    workflow = _read(".github/workflows/release.yml")
    assert "runs-on: windows-latest" in workflow
    assert 'BIOAUTH_ENABLE_SIGNING: "1"' in workflow
    assert 'BIOAUTH_BUILD_PROFILE=$buildProfile' in workflow
    assert '--signing-required' in workflow
    assert 'build_installer.bat' in workflow
    assert 'tests/test_windows_release_smoke_signing_update_gate.py' in workflow
    assert 'bioauth-update.json' in workflow
    assert 'SHA256SUMS.txt' in workflow
    assert 'GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}' in workflow
    assert 'BIOAUTH_SIGN_CERT_SHA1: ${{ secrets.BIOAUTH_SIGN_CERT_SHA1 }}' in workflow
    assert 'BIOAUTH_SIGN_CERT_PFX_BASE64: ${{ secrets.BIOAUTH_SIGN_CERT_PFX_BASE64 }}' in workflow
    assert 'BIOAUTH_SIGN_CERT_PASSWORD: ${{ secrets.BIOAUTH_SIGN_CERT_PASSWORD }}' in workflow
    assert 'Configure Windows signing certificate' in workflow


def test_readme_does_not_claim_linux_ci_proves_windows_release() -> None:
    combined = "\n".join([
        _read("README.md"),
        _read("docs/developer/BUILD_README.md"),
        _read(".github/workflows/release.yml"),
    ]).lower()
    forbidden_claims = [
        "linux ci proves windows release",
        "linux tests prove windows packaging",
        "public release is allowed without signing",
    ]
    for phrase in forbidden_claims:
        assert phrase not in combined


def test_production_signing_is_fail_closed() -> None:
    disabled = production_profile_errors({"BIOAUTH_BUILD_PROFILE": "production", "BIOAUTH_ENABLE_SIGNING": "0"})
    assert any("BIOAUTH_ENABLE_SIGNING" in item for item in disabled)

    missing = production_profile_errors({"BIOAUTH_BUILD_PROFILE": "production"})
    assert any("BIOAUTH_ENABLE_SIGNING" in item for item in missing)

    missing_cert = production_profile_errors({"BIOAUTH_BUILD_PROFILE": "production", "BIOAUTH_ENABLE_SIGNING": "1"})
    assert any("Production signing requires" in item for item in missing_cert)

    assert_release_profile_safe({
        "BIOAUTH_BUILD_PROFILE": "production",
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_SHA1": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
    })
    assert_release_profile_safe({
        "BIOAUTH_BUILD_PROFILE": "production",
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_FILE": "C:/runner/cert.pfx",
        "BIOAUTH_SIGN_CERT_PASSWORD": "dummy-password",
    })

    beta = production_profile_errors({"BIOAUTH_BUILD_PROFILE": "beta", "BIOAUTH_ENABLE_SIGNING": "0"})
    assert beta == []


def test_update_gate_uses_manual_sha256_path_without_silent_install() -> None:
    cfg = UpdateConfig.from_env()
    # The checked-in source template is intentionally not production-signing-required;
    # the Windows release workflow regenerates the packaged config with --signing-required.
    assert cfg.verification == "sha256"
    assert cfg.silent_install is False

    manifest = validate_update_manifest(
        {
            "app": "BioAuth",
            "channel": "beta",
            "version": "1.0.1",
            "installer_name": "BioAuthDesktopSetup_1.0.1.exe",
            "installer_sha256": "a" * 64,
            "min_supported_version": "1.0.0",
            "mandatory": False,
            "release_notes": "Manual test release",
            "published_at": "2026-05-16T00:00:00Z",
        },
        channel="beta",
    )
    assert manifest["installer_sha256"] == "a" * 64


def test_runner_script_executes_static_release_gate_checks() -> None:
    runner = ROOT / "tests" / "run_windows_release_smoke_signing_update_gate_checks.py"
    result = subprocess.run(
        [sys.executable, str(runner)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "ALL_WINDOWS_RELEASE_GATE_CHECKS_PASSED=" in result.stdout
    if os.name != "nt":
        assert "WINDOWS_ARTIFACT_EXECUTION_SKIPPED=non_windows" in result.stdout


def test_production_profile_rejects_stray_demo_classic_build_flag() -> None:
    from release_profile import production_profile_errors

    errors = production_profile_errors({
        "BIOAUTH_BUILD_PROFILE": "production",
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_SHA1": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
        "BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED": "1",
    })
    assert any("BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED" in item for item in errors)

    explicit_demo_flavor = production_profile_errors({
        "BIOAUTH_BUILD_PROFILE": "production",
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_SHA1": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
        "BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED": "1",
        "BIOAUTH_BUILD_FLAVOR": "demo-classic-protected",
    })
    assert explicit_demo_flavor == []

