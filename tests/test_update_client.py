from __future__ import annotations

import json
from pathlib import Path

import pytest

from update_client import (
    GitHubReleaseUpdateClient,
    InvalidUpdateManifest,
    UpdateConfig,
    compare_versions,
    find_release_asset,
    sha256_file,
    validate_update_manifest,
)


def _manifest(version: str = "1.0.1-beta.1", sha: str | None = None) -> dict:
    return {
        "app": "BioAuth",
        "channel": "beta",
        "version": version,
        "installer_name": f"BioAuthDesktopSetup_{version}.exe",
        "installer_sha256": sha or ("a" * 64),
        "min_supported_version": "1.0.0",
        "mandatory": False,
        "release_notes": "Beta update notes.",
        "published_at": "2026-04-30T00:00:00Z",
    }


def test_version_comparison_update_same_downgrade_and_beta() -> None:
    assert compare_versions("1.0.1", "1.0.0") > 0
    assert compare_versions("1.0.1", "1.0.1") == 0
    assert compare_versions("1.0.1", "1.0.2") < 0
    assert compare_versions("1.0.1-beta.2", "1.0.1-beta.1") > 0
    assert compare_versions("1.0.1", "1.0.1-beta.1") > 0


def test_manifest_validation_accepts_complete_manifest() -> None:
    manifest = validate_update_manifest(_manifest(), channel="beta")
    assert manifest["version"] == "1.0.1-beta.1"
    assert manifest["installer_sha256"] == "a" * 64


def test_manifest_validation_rejects_missing_fields() -> None:
    payload = _manifest()
    payload.pop("installer_sha256")
    with pytest.raises(InvalidUpdateManifest):
        validate_update_manifest(payload, channel="beta")


def test_manifest_validation_rejects_bad_sha256() -> None:
    payload = _manifest(sha="bad")
    with pytest.raises(InvalidUpdateManifest):
        validate_update_manifest(payload, channel="beta")


def test_correct_sha256_accepted_and_bad_download_deleted(tmp_path: Path) -> None:
    installer_bytes = b"real installer bytes"
    good_hash = __import__("hashlib").sha256(installer_bytes).hexdigest()
    manifest = _manifest(sha=good_hash)
    release = {
        "draft": False,
        "prerelease": True,
        "assets": [
            {"name": "bioauth-update.json", "browser_download_url": "https://example.test/manifest"},
            {"name": manifest["installer_name"], "browser_download_url": "https://example.test/installer"},
        ],
    }

    def http_get(url: str, **_: object) -> bytes:
        if url.endswith("/releases"):
            return json.dumps([release]).encode()
        if url.endswith("/manifest"):
            return json.dumps(manifest).encode()
        if url.endswith("/installer"):
            return installer_bytes
        raise AssertionError(url)

    client = GitHubReleaseUpdateClient(
        UpdateConfig(repo_owner="owner", repo_name="repo", channel="beta"),
        current_version="1.0.0",
        http_get=http_get,
        download_dir=tmp_path,
    )
    check = client.check_for_update()
    assert check["state"] == "update_available"
    downloaded = client.safe_download_candidate()
    assert downloaded["state"] == "ready_to_install"
    assert sha256_file(downloaded["downloadedPath"]) == good_hash

    bad_manifest = dict(manifest)
    bad_manifest["installer_sha256"] = "b" * 64

    def bad_http_get(url: str, **_: object) -> bytes:
        if url.endswith("/releases"):
            return json.dumps([release]).encode()
        if url.endswith("/manifest"):
            return json.dumps(bad_manifest).encode()
        if url.endswith("/installer"):
            return installer_bytes
        raise AssertionError(url)

    bad_client = GitHubReleaseUpdateClient(
        UpdateConfig(repo_owner="owner", repo_name="repo", channel="beta"),
        current_version="1.0.0",
        http_get=bad_http_get,
        download_dir=tmp_path / "bad",
    )
    assert bad_client.check_for_update()["state"] == "update_available"
    failed = bad_client.safe_download_candidate()
    assert failed["state"] == "hash_verification_failed"
    assert not list((tmp_path / "bad").glob("*.exe"))


def test_network_failure_does_not_crash() -> None:
    def failing_get(url: str, **_: object) -> bytes:
        raise OSError("offline")

    client = GitHubReleaseUpdateClient(
        UpdateConfig(repo_owner="owner", repo_name="repo", channel="beta"),
        current_version="1.0.0",
        http_get=failing_get,
    )
    result = client.check_for_update()
    assert result["ok"] is False
    assert result["state"] in {"download_failed", "invalid_update_manifest"}


def test_github_release_asset_selection_with_mocked_data() -> None:
    release = {
        "assets": [
            {"name": "other.txt", "browser_download_url": "https://example.test/other"},
            {"name": "bioauth-update.json", "browser_download_url": "https://example.test/manifest"},
        ]
    }
    asset = find_release_asset(release, "bioauth-update.json")
    assert asset is not None
    assert asset.browser_download_url.endswith("/manifest")
