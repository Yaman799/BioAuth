from __future__ import annotations

from pathlib import Path

import pytest

from release_profile import assert_release_profile_safe, production_profile_errors, signing_configuration_errors

ROOT = Path(__file__).resolve().parent.parent


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_production_profile_fails_when_signing_disabled() -> None:
    errors = production_profile_errors({"BIOAUTH_BUILD_PROFILE": "production", "BIOAUTH_ENABLE_SIGNING": "0"})
    assert any("BIOAUTH_ENABLE_SIGNING" in item for item in errors)
    with pytest.raises(RuntimeError):
        assert_release_profile_safe({"BIOAUTH_BUILD_PROFILE": "production", "BIOAUTH_ENABLE_SIGNING": "0"})


def test_production_profile_fails_when_signing_enabled_without_certificate_config() -> None:
    errors = production_profile_errors({"BIOAUTH_BUILD_PROFILE": "production", "BIOAUTH_ENABLE_SIGNING": "1"})
    assert any("Production signing requires" in item for item in errors)
    with pytest.raises(RuntimeError):
        assert_release_profile_safe({"BIOAUTH_BUILD_PROFILE": "production", "BIOAUTH_ENABLE_SIGNING": "1"})


def test_production_profile_accepts_thumbprint_or_file_password_config() -> None:
    thumbprint_env = {
        "BIOAUTH_BUILD_PROFILE": "production",
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_SHA1": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
    }
    assert production_profile_errors(thumbprint_env) == []
    assert_release_profile_safe(thumbprint_env)

    file_env = {
        "BIOAUTH_BUILD_PROFILE": "production",
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_FILE": "C:/runner/temp/bioauth_signing_cert.pfx",
        "BIOAUTH_SIGN_CERT_PASSWORD": "unit-test-secret-placeholder",
    }
    assert production_profile_errors(file_env) == []
    assert_release_profile_safe(file_env)

    pfx_secret_env = {
        "BIOAUTH_BUILD_PROFILE": "production",
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_PFX_BASE64": "BASE64_PLACEHOLDER",
        "BIOAUTH_SIGN_CERT_PASSWORD": "unit-test-secret-placeholder",
    }
    assert production_profile_errors(pfx_secret_env) == []
    assert_release_profile_safe(pfx_secret_env)


def test_production_file_signing_requires_password() -> None:
    errors = production_profile_errors({
        "BIOAUTH_BUILD_PROFILE": "production",
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_FILE": "C:/runner/temp/bioauth_signing_cert.pfx",
    })
    assert any("BIOAUTH_SIGN_CERT_PASSWORD" in item for item in errors)


def test_development_profile_does_not_require_signing_configuration() -> None:
    assert production_profile_errors({"BIOAUTH_BUILD_PROFILE": "dev", "BIOAUTH_ENABLE_SIGNING": "0"}) == []
    assert production_profile_errors({"BIOAUTH_BUILD_PROFILE": "beta", "BIOAUTH_ENABLE_SIGNING": "0"}) == []


def test_signing_configuration_error_messages_do_not_include_secret_values() -> None:
    env = {
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_FILE": "C:/runner/temp/bioauth_signing_cert.pfx",
        "BIOAUTH_SIGN_CERT_PASSWORD": "SUPER_SECRET_PASSWORD_VALUE",
    }
    assert signing_configuration_errors(env) == []

    missing = signing_configuration_errors({"BIOAUTH_ENABLE_SIGNING": "1"})
    joined = "\n".join(missing)
    assert "SUPER_SECRET_PASSWORD_VALUE" not in joined
    assert "unit-test-secret-placeholder" not in joined


def test_github_release_workflow_wires_signing_secrets_without_literal_secret_values() -> None:
    workflow = _read(".github/workflows/release.yml")
    assert "BIOAUTH_SIGN_CERT_SHA1: ${{ secrets.BIOAUTH_SIGN_CERT_SHA1 }}" in workflow
    assert "BIOAUTH_SIGN_CERT_FILE: ${{ secrets.BIOAUTH_SIGN_CERT_FILE }}" in workflow
    assert "BIOAUTH_SIGN_CERT_PASSWORD: ${{ secrets.BIOAUTH_SIGN_CERT_PASSWORD }}" in workflow
    assert "BIOAUTH_SIGN_CERT_PFX_BASE64: ${{ secrets.BIOAUTH_SIGN_CERT_PFX_BASE64 }}" in workflow
    assert "Configure Windows signing certificate" in workflow
    assert "RUNNER_TEMP" in workflow
    assert "FromBase64String" in workflow
    assert "Production signing is enabled but no BIOAUTH_SIGN_CERT_SHA1" in workflow
    assert "SUPER_SECRET" not in workflow
    assert "unit-test-secret-placeholder" not in workflow


def test_signing_batch_uses_secret_variables_but_does_not_echo_password() -> None:
    signer = _read("build_tools/sign_windows_artifact.bat")
    assert "BIOAUTH_SIGN_CERT_SHA1" in signer
    assert "BIOAUTH_SIGN_CERT_FILE" in signer
    assert "BIOAUTH_SIGN_CERT_PASSWORD" in signer
    assert "/p \"%BIOAUTH_SIGN_CERT_PASSWORD%\"" in signer
    assert "echo %BIOAUTH_SIGN_CERT_PASSWORD%" not in signer.lower()
    assert "set BIOAUTH_SIGN_CERT_PASSWORD" not in signer


def test_docs_name_required_github_secrets_and_warn_no_private_material_committed() -> None:
    combined = "\n".join([
        _read("README.md"),
        _read("docs/developer/BUILD_README.md"),
        _read("docs/WINDOWS_RELEASE_SMOKE_SIGNING_UPDATE_GATE.md"),
    ])
    assert "BIOAUTH_SIGN_CERT_SHA1" in combined
    assert "BIOAUTH_SIGN_CERT_PFX_BASE64" in combined
    assert "BIOAUTH_SIGN_CERT_PASSWORD" in combined
    assert "Production preflight fails early" in combined
    assert "must never contain certificate files" in combined or "should ever be committed" in combined

