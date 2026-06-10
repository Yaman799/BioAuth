from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from release_runtime import runtime_path_report, startup_protected_session_decision, write_release_runtime_event
from update_client import InvalidUpdateManifest, validate_update_manifest
from build_tools.generate_update_manifest import build_manifest


def _valid_manifest(**overrides):
    payload = {
        "app": "BioAuth",
        "channel": "stable",
        "version": "1.2.3",
        "installer_name": "BioAuthDesktopSetup_1.2.3.exe",
        "installer_sha256": "a" * 64,
        "min_supported_version": "1.0.0",
        "mandatory": False,
        "release_notes": "Safe release notes.",
        "published_at": "2026-05-04T00:00:00Z",
        "update_manifest_name": "bioauth-update.json",
        "artifact_names": ["BioAuthDesktopSetup_1.2.3.exe", "bioauth-update.json", "SHA256SUMS.txt"],
        "checksums": {"BioAuthDesktopSetup_1.2.3.exe": "a" * 64},
    }
    payload.update(overrides)
    return payload


def test_startup_protected_session_requires_explicit_setting() -> None:
    decision = startup_protected_session_decision(
        settings={"run_on_startup": True, "remember_login_enabled": True, "startup_protected_sessions_enabled": False},
        background=True,
        authenticated=True,
        has_current_consent=True,
        profile={"production_ready": True, "model_status": "approved_for_production"},
        flow="idle",
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "startup_protected_sessions_enabled_required"
    assert decision["production_decision_changed"] is False
    assert decision["production_threshold_changed"] is False
    assert decision["protected_sessions_unlocked_by_startup"] is False
    assert decision["collect_owner_enrollment_data"] is False


def test_startup_protected_session_allowed_only_with_valid_state() -> None:
    decision = startup_protected_session_decision(
        settings={"run_on_startup": True, "remember_login_enabled": True, "startup_protected_sessions_enabled": True},
        background=True,
        authenticated=True,
        has_current_consent=True,
        profile={"production_ready": True, "model_status": "approved_for_production"},
        flow="idle",
    )

    assert decision["allowed"] is True
    assert decision["reason"] == "allowed"


@pytest.mark.parametrize(
    "field,settings,background,authenticated,consent,profile,flow,expected_reason",
    [
        ("background", {"run_on_startup": True, "remember_login_enabled": True, "startup_protected_sessions_enabled": True}, False, True, True, {"production_ready": True}, "idle", "background_required"),
        ("run_on_startup", {"run_on_startup": False, "remember_login_enabled": True, "startup_protected_sessions_enabled": True}, True, True, True, {"production_ready": True}, "idle", "run_on_startup_required"),
        ("remember_login", {"run_on_startup": True, "remember_login_enabled": False, "startup_protected_sessions_enabled": True}, True, True, True, {"production_ready": True}, "idle", "remember_login_enabled_required"),
        ("authenticated", {"run_on_startup": True, "remember_login_enabled": True, "startup_protected_sessions_enabled": True}, True, False, True, {"production_ready": True}, "idle", "authenticated_required"),
        ("consent", {"run_on_startup": True, "remember_login_enabled": True, "startup_protected_sessions_enabled": True}, True, True, False, {"production_ready": True}, "idle", "has_current_consent_required"),
        ("profile", {"run_on_startup": True, "remember_login_enabled": True, "startup_protected_sessions_enabled": True}, True, True, True, {"production_ready": False}, "idle", "profile_production_ready_required"),
        ("flow", {"run_on_startup": True, "remember_login_enabled": True, "startup_protected_sessions_enabled": True}, True, True, True, {"production_ready": True}, "enrollment_active", "flow_idle_required"),
    ],
)
def test_startup_protected_session_fails_closed_for_each_missing_gate(field, settings, background, authenticated, consent, profile, flow, expected_reason) -> None:
    decision = startup_protected_session_decision(
        settings=settings,
        background=background,
        authenticated=authenticated,
        has_current_consent=consent,
        profile=profile,
        flow=flow,
    )

    assert decision["allowed"] is False, field
    assert decision["reason"] == expected_reason


def test_release_runtime_log_is_user_writable_and_sanitized(monkeypatch, tmp_path: Path) -> None:
    install_root = tmp_path / "install"
    data_root = tmp_path / "user_data"
    install_root.mkdir()
    data_root.mkdir()
    monkeypatch.setattr("release_runtime.runtime_base_dir", lambda: str(install_root))
    monkeypatch.setattr("release_runtime.app_data_dir", lambda: str(data_root.parent))
    monkeypatch.setattr("release_runtime.data_dir", lambda: str(data_root))

    report = runtime_path_report()
    assert report["data_dir_writable"] is True
    assert report["data_dir_outside_runtime_base"] is True
    assert report["event_log_outside_runtime_base"] is True

    assert write_release_runtime_event(
        "background_worker_start_failed",
        key="monitor",
        process="monitor.py",
        reason="start_failed",
        detail=str(install_root / "secret" / "raw_behavior.csv"),
        raw_biometric_payload={"must": "not be logged"},
    )
    log_path = Path(report["release_event_log_file"])
    row = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert row["event_type"] == "background_worker_start_failed"
    assert row["process"] == "monitor.py"
    assert "raw_biometric_payload" not in row
    assert "raw_behavior.csv" not in row["detail"]
    assert "[path]" in row["detail"]


def test_update_manifest_accepts_release_metadata_and_rejects_bad_metadata() -> None:
    manifest = validate_update_manifest(_valid_manifest(), channel="stable")
    assert manifest["artifact_names"][0] == manifest["installer_name"]
    assert manifest["checksums"][manifest["installer_name"]] == manifest["installer_sha256"]

    with pytest.raises(InvalidUpdateManifest):
        validate_update_manifest(_valid_manifest(checksums={"BioAuthDesktopSetup_1.2.3.exe": "b" * 64}), channel="stable")
    with pytest.raises(InvalidUpdateManifest):
        validate_update_manifest(_valid_manifest(artifact_names=["bioauth-update.json"]), channel="stable")
    with pytest.raises(InvalidUpdateManifest):
        validate_update_manifest(_valid_manifest(release_notes_url="http://example.invalid/notes"), channel="stable")


def test_update_manifest_generator_emits_artifact_metadata(tmp_path: Path) -> None:
    installer = tmp_path / "BioAuthDesktopSetup_1.2.3.exe"
    installer.write_bytes(b"installer")
    digest = hashlib.sha256(b"installer").hexdigest()

    manifest = build_manifest(
        installer=installer,
        version="1.2.3",
        channel="stable",
        min_supported_version="1.0.0",
        mandatory=False,
        release_notes="Release notes",
        published_at="2026-05-04T00:00:00Z",
    )

    assert manifest["installer_sha256"] == digest
    assert manifest["artifact_names"] == [installer.name, "bioauth-update.json", "SHA256SUMS.txt"]
    assert manifest["checksums"][installer.name] == digest
    assert manifest["update_manifest_name"] == "bioauth-update.json"


def test_packaging_release_files_cover_runtime_assets_and_no_website_files() -> None:
    from build_tools.commercial_package_allowlist import collect_commercial_datas

    spec = Path("BioAuth.spec").read_text(encoding="utf-8")
    datas = set(collect_commercial_datas(Path.cwd()))
    assert any(source.startswith("qml/") and dest.startswith("qml") for source, dest in datas)
    assert any(source.startswith("config/onboarding_assets") for source, _dest in datas)
    assert any(source.startswith("model_runtime/") and dest == "model_runtime" for source, dest in datas)
    assert '"release_runtime"' in spec
    assert '"update_client"' in spec
    assert "cv2" in spec

    smoke = Path("build_tools/packaged_smoke.py").read_text(encoding="utf-8")
    entry = Path("build_tools/packaged_smoke_entry.py").read_text(encoding="utf-8")
    assert "--self-check-release-readiness" in smoke
    assert "--self-check-release-readiness" in entry

    installer = Path("BioAuthInstaller.iss").read_text(encoding="utf-8")
    assert "Protected sessions after startup require the separate in-app setting" in installer
    assert "Choose No to preserve accounts, settings, sessions, logs, trained models, evaluation evidence, and templates." in installer
    assert "DelTree(DataDir" in installer  # still only after explicit uninstall confirmation

    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "--self-check-release-readiness" in workflow
    assert "secrets.GITHUB_TOKEN" in workflow
    assert "BIOAUTH_UPDATE_TOKEN" not in workflow

    forbidden_roots = [Path("website"), Path("landing"), Path("public"), Path("web")]
    assert not any(path.exists() for path in forbidden_roots)
