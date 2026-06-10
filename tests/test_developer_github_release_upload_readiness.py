from __future__ import annotations

import json
from pathlib import Path

import pytest

from build_tools.write_release_config import build_release_config, main as write_release_config_main
from update_client import UpdateConfig, load_release_config

ROOT = Path(__file__).resolve().parent.parent


def test_release_config_template_uses_hash_verification_without_silent_install() -> None:
    payload = json.loads((ROOT / "release_config.json").read_text(encoding="utf-8"))
    assert payload["verification"] == "sha256"
    assert payload["signing_required"] is False
    assert payload["silent_install"] is False
    assert payload["manifest_name"] == "bioauth-update.json"


def test_update_config_reads_release_config_file_and_env_overrides(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "release_config.json"
    config.write_text(
        json.dumps(
            {
                "update_repo_owner": "file-owner",
                "update_repo_name": "file-repo",
                "update_channel": "beta",
                "manifest_name": "bioauth-update.json",
                "verification": "sha256",
                "signing_required": False,
                "silent_install": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BIOAUTH_RELEASE_CONFIG", str(config))
    loaded = load_release_config()
    assert loaded["update_repo_owner"] == "file-owner"
    cfg = UpdateConfig.from_env()
    assert cfg.repo_owner == "file-owner"
    assert cfg.repo_name == "file-repo"
    assert cfg.uses_hash_verification_only is True
    assert cfg.silent_install is False

    monkeypatch.setenv("BIOAUTH_UPDATE_REPO_OWNER", "env-owner")
    cfg = UpdateConfig.from_env()
    assert cfg.repo_owner == "env-owner"
    assert cfg.repo_name == "file-repo"


def test_write_release_config_rejects_placeholders_and_writes_real_repo(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_release_config(
            owner="CHANGE_ME_OWNER",
            repo="BioAuth",
            channel="beta",
            api_base="https://api.github.com",
            manifest_name="bioauth-update.json",
            verification="sha256",
            signing_required=False,
            silent_install=False,
        )
    output = tmp_path / "release_config.json"
    assert write_release_config_main([
        "--owner", "octo-org",
        "--repo", "bioauth",
        "--channel", "beta",
        "--output", str(output),
    ]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["update_repo_owner"] == "octo-org"
    assert payload["update_repo_name"] == "bioauth"
    assert payload["verification"] == "sha256"
    assert payload["signing_required"] is False
    assert payload["silent_install"] is False


def test_release_workflow_bakes_config_and_uses_sha256_not_signing_token() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "write_release_config.py" in workflow
    assert "--verification \"sha256\"" in workflow
    assert "--signing-required" in workflow
    assert "BIOAUTH_ENABLE_SIGNING: \"1\"" in workflow
    assert "BIOAUTH_SIGN_CERT_SHA1: ${{ secrets.BIOAUTH_SIGN_CERT_SHA1 }}" in workflow
    assert "BIOAUTH_SIGN_CERT_PFX_BASE64: ${{ secrets.BIOAUTH_SIGN_CERT_PFX_BASE64 }}" in workflow
    assert "BIOAUTH_SIGN_CERT_PASSWORD: ${{ secrets.BIOAUTH_SIGN_CERT_PASSWORD }}" in workflow
    assert "Configure Windows signing certificate" in workflow
    assert "choco install innosetup" in workflow
    assert "SHA256SUMS.txt" in workflow


def test_release_profile_requires_signing_for_production(monkeypatch) -> None:
    from release_profile import production_profile_errors

    errors = production_profile_errors({"BIOAUTH_BUILD_PROFILE": "production", "BIOAUTH_ENABLE_SIGNING": "0"})
    assert any("BIOAUTH_ENABLE_SIGNING" in item for item in errors)

    errors = production_profile_errors({"BIOAUTH_BUILD_PROFILE": "production", "BIOAUTH_ENABLE_SIGNING": "1"})
    assert any("Production signing requires" in item for item in errors)

    configured = production_profile_errors({
        "BIOAUTH_BUILD_PROFILE": "production",
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_SHA1": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
    })
    assert not configured

    beta_errors = production_profile_errors({"BIOAUTH_BUILD_PROFILE": "beta", "BIOAUTH_ENABLE_SIGNING": "0"})
    assert not beta_errors

    demo_flag_errors = production_profile_errors({
        "BIOAUTH_BUILD_PROFILE": "production",
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_SHA1": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
        "BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED": "1",
    })
    assert any("BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED" in item for item in demo_flag_errors)

    explicit_demo_flavor_errors = production_profile_errors({
        "BIOAUTH_BUILD_PROFILE": "production",
        "BIOAUTH_ENABLE_SIGNING": "1",
        "BIOAUTH_SIGN_CERT_SHA1": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
        "BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED": "1",
        "BIOAUTH_BUILD_FLAVOR": "demo-classic-protected",
    })
    assert not explicit_demo_flavor_errors


def test_pyinstaller_spec_packages_commercial_release_config_without_dev_docs() -> None:
    from build_tools.commercial_package_allowlist import collect_commercial_datas

    pairs = set(collect_commercial_datas(ROOT))

    assert ("release_config.json", ".") in pairs
    assert ("PRIVACY_POLICY.md", ".") in pairs
    assert ("EULA.txt", ".") in pairs
    assert all(not source.startswith("docs/") and source != "docs" for source, _ in pairs)
    assert ("CHANGELOG.md", ".") not in pairs


def test_gitignore_blocks_generated_evidence_and_personal_runtime_artifacts() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in [
        "reports/*",
        "!reports/safety/**",
        "validation/",
        "validation_artifacts/",
        "docs/validation/",
        "*.manifest.json",
        "*.delivery_report.json",
        "*.delivery_gate.log",
        "*.exitcode",
        "*.log.md",
        "*.pkl",
        "*.joblib",
        "*.pt",
        "*.onnx",
        "*.sqlite",
        "*.jsonl",
    ]:
        assert pattern in gitignore
