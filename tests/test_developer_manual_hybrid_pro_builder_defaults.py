from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_build_exe_defaults_manual_build_to_hybrid_pro_face() -> None:
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")
    assert 'if "%BIOAUTH_PACKAGE_PROFILE%"=="" set "BIOAUTH_PACKAGE_PROFILE=hybrid-pro-face"' in script
    assert 'if /I "%BIOAUTH_BUILD_PROFILE%"=="classic" set "BIOAUTH_PACKAGE_PROFILE=classic-minimal"' in script
    assert 'if /I "%BIOAUTH_BUILD_WITH_HYBRID%"=="0" set "BIOAUTH_PACKAGE_PROFILE=classic-minimal"' in script
    assert 'pip install -r requirements-pro.txt' in script
    assert 'pip install -r requirements-face.txt' in script
    assert 'BIOAUTH_INCLUDE_OPENCV=1' in script


def test_build_installer_sets_hybrid_pro_face_for_manual_installer_build() -> None:
    script = (ROOT / "build_installer.bat").read_text(encoding="utf-8")
    assert 'if "%BIOAUTH_PACKAGE_PROFILE%"=="" set "BIOAUTH_PACKAGE_PROFILE=hybrid-pro-face"' in script
    assert 'echo [INFO] Package profile: %BIOAUTH_PACKAGE_PROFILE%' in script
    assert 'call build_exe.bat' in script


def test_bootstrap_build_env_prepares_hybrid_pro_face_environment_by_default() -> None:
    script = (ROOT / "packaging" / "scripts" / "bootstrap_build_env.bat").read_text(encoding="utf-8")
    assert script.startswith("@echo off")
    assert 'if "%BIOAUTH_PACKAGE_PROFILE%"=="" set "BIOAUTH_PACKAGE_PROFILE=hybrid-pro-face"' in script
    assert 'pip install -r requirements-pro.txt' in script
    assert 'pip install -r requirements-face.txt' in script
    assert 'BIOAUTH_INCLUDE_OPENCV=1' in script
    assert 'Installing optional Pro/Hybrid runtime profile' in script


def test_build_docs_describe_hybrid_pro_manual_default() -> None:
    build_readme = (ROOT / "docs/developer/BUILD_README.md").read_text(encoding="utf-8")
    perf = (ROOT / "docs" / "PERFORMANCE_BUILD_PROFILES.md").read_text(encoding="utf-8")
    assert "Manual builds default to `BIOAUTH_PACKAGE_PROFILE=hybrid-pro-face`" in build_readme
    assert "manual default / `production` -> `hybrid-pro-face`" in perf
    assert "classic" in perf and "classic-minimal" in perf

