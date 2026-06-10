from __future__ import annotations

from pathlib import Path

from release_profile import normalize_package_profile, package_profile_payload

ROOT = Path(__file__).resolve().parent.parent


def test_release_profile_supports_full_feature_hybrid_pro_face() -> None:
    payload = package_profile_payload("hybrid-pro-face")
    assert payload["package_profile"] == "hybrid-pro-face"
    assert payload["requirements"] == ["requirements.txt", "requirements-pro.txt", "requirements-face.txt"]
    assert payload["include_deep_deps"] is True
    assert payload["include_lightgbm"] is True
    assert payload["include_face_backends"] is True
    assert "face_confirmation" in payload["feature_scope"]


def test_package_profile_aliases_keep_old_hybrid_and_new_full_feature_distinct() -> None:
    assert normalize_package_profile("hybrid-pro") == "hybrid-pro"
    assert normalize_package_profile("pro") == "hybrid-pro"
    assert normalize_package_profile("hybrid-pro-face") == "hybrid-pro-face"
    assert normalize_package_profile("full-feature") == "hybrid-pro-face"
    assert normalize_package_profile("beta") == "hybrid-pro-face"


def test_manual_and_release_builders_default_to_hybrid_pro_face_and_install_face_requirements() -> None:
    build_exe = (ROOT / "build_exe.bat").read_text(encoding="utf-8")
    build_installer = (ROOT / "build_installer.bat").read_text(encoding="utf-8")
    bootstrap = (ROOT / "packaging" / "scripts" / "bootstrap_build_env.bat").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    for text in (build_exe, build_installer, bootstrap):
        assert 'BIOAUTH_PACKAGE_PROFILE=hybrid-pro-face' in text
    assert 'pip install -r requirements-pro.txt' in build_exe
    assert 'pip install -r requirements-face.txt' in build_exe
    assert 'pip install -r requirements-face.txt' in bootstrap
    assert 'BIOAUTH_INCLUDE_OPENCV=1' in build_exe
    assert 'BIOAUTH_INCLUDE_OPENCV=1' in build_installer
    assert 'BIOAUTH_PACKAGE_PROFILE=hybrid-pro-face' in workflow
    assert 'BIOAUTH_INCLUDE_OPENCV: "1"' in workflow


def test_dev_and_audit_requirements_are_not_runtime_installer_dependencies() -> None:
    release_doc = (ROOT / "docs" / "RELEASE_REQUIREMENTS_PROFILE.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    tests_workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert "requirements-dev.txt" in release_doc
    assert "requirements-audit.txt" in release_doc
    assert "not runtime installer dependencies" in release_doc
    assert "requirements-dev.txt" in workflow  # release tests only
    assert "requirements-audit.txt" in tests_workflow  # audit CI only
