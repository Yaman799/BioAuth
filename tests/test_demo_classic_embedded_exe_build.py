from __future__ import annotations

import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_demo_classic_runtime_hook_forces_expected_environment(monkeypatch) -> None:
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED", raising=False)
    monkeypatch.delenv("BIOAUTH_DEMO_CLASSIC_PROTECTED_EMBEDDED", raising=False)
    monkeypatch.delenv("BIOAUTH_BUILD_FLAVOR", raising=False)
    monkeypatch.delenv("BIOAUTH_ENABLE_FACE_CONFIRMATION_DEV", raising=False)
    monkeypatch.delenv("BIOAUTH_ENABLE_FACE_ENROLLMENT_DEV", raising=False)

    hook_path = ROOT / "build_tools" / "runtime_demo_classic_protected.py"
    spec = importlib.util.spec_from_file_location("runtime_demo_classic_protected_under_test", hook_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert os.environ["BIOAUTH_DEMO_CLASSIC_PROTECTED"] == "1"
    assert os.environ["BIOAUTH_DEMO_CLASSIC_PROTECTED_EMBEDDED"] == "1"
    assert os.environ["BIOAUTH_BUILD_FLAVOR"] == "demo-classic-protected"
    assert os.environ["BIOAUTH_ENABLE_FACE_CONFIRMATION_DEV"] == "1"
    assert os.environ["BIOAUTH_ENABLE_FACE_ENROLLMENT_DEV"] == "1"

    # The runtime hook mutates os.environ directly just like PyInstaller does.
    # Clean these extra hook keys immediately so unrelated settings tests in the
    # same pytest process do not see local face feature flags as globally enabled.
    for key in (
        "BIOAUTH_ENABLE_FACE_CONFIRMATION_DEV",
        "BIOAUTH_ENABLE_FACE_ENROLLMENT_DEV",
        "BIOAUTH_DEMO_CLASSIC_PROTECTED",
        "BIOAUTH_DEMO_CLASSIC_PROTECTED_EMBEDDED",
        "BIOAUTH_BUILD_FLAVOR",
    ):
        os.environ.pop(key, None)


def test_bioauth_spec_has_conditional_demo_classic_runtime_hook() -> None:
    text = (ROOT / "BioAuth.spec").read_text(encoding="utf-8")
    assert "demo_classic_build_enabled" in text
    assert "BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED" in text
    assert "BIOAUTH_BUILD_FLAVOR=demo-classic-protected" in text
    assert "runtime_demo_classic_protected.py" in text
    assert "RUNTIME_HOOKS.append" in text
    assert "APP_BASENAME" in text
    assert "COLLECT_BASENAME" in text


def test_demo_classic_builder_sets_build_flag_flavor_and_unique_output_name() -> None:
    text = (ROOT / "tools" / "dev" / "launchers" / "build_exe_demo_classic.bat").read_text(encoding="utf-8")
    assert 'set "BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED=1"' in text
    assert 'set "BIOAUTH_BUILD_FLAVOR=demo-classic-protected"' in text
    assert 'if "%BIOAUTH_PACKAGE_PROFILE%"=="" set "BIOAUTH_PACKAGE_PROFILE=hybrid-pro-face"' in text
    assert 'set "BIOAUTH_EXE_NAME=BioAuth_DemoClassicProtected"' in text
    assert 'set "BIOAUTH_DIST_NAME=BioAuth_DemoClassicProtected"' in text
    assert "call build_exe.bat" in text


def test_normal_builder_still_defaults_to_product_output_names() -> None:
    text = (ROOT / "build_exe.bat").read_text(encoding="utf-8")
    assert 'if "%BIOAUTH_EXE_NAME%"=="" set "BIOAUTH_EXE_NAME=BioAuth"' in text
    assert 'if "%BIOAUTH_DIST_NAME%"=="" set "BIOAUTH_DIST_NAME=BioAuth"' in text
    assert r"dist\%BIOAUTH_DIST_NAME%\%BIOAUTH_EXE_NAME%.exe --self-check-packaging" in text


def test_commercial_policy_requires_demo_build_flag_and_flavor(monkeypatch) -> None:
    from build_tools.demo_classic_policy import demo_classic_build_enabled

    assert demo_classic_build_enabled({}) is False
    assert demo_classic_build_enabled({"BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED": "1"}) is False
    assert demo_classic_build_enabled({
        "BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED": "1",
        "BIOAUTH_BUILD_FLAVOR": "demo-classic-protected",
    }) is True


def test_commercial_allowlist_excludes_demo_classic_module_by_default() -> None:
    from build_tools.commercial_package_allowlist import collect_commercial_datas

    commercial = {src for src, _ in collect_commercial_datas(ROOT, include_demo=False)}
    demo = {src for src, _ in collect_commercial_datas(ROOT, include_demo=True)}

    assert "build_tools/runtime_demo_classic_protected.py" not in commercial
    assert "metadata_core/demo_classic_runtime_activation.py" not in commercial
    assert "build_tools/runtime_demo_classic_protected.py" in demo
    assert "metadata_core/demo_classic_runtime_activation.py" in demo
