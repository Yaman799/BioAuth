from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_tests_workflow_exists_and_is_linux_fast_gate() -> None:
    workflow = _read(".github/workflows/tests.yml")
    assert "name: BioAuth Tests Coverage Audit SBOM" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "actions/checkout@v4" in workflow
    assert "actions/setup-python@v5" in workflow
    assert 'python-version: "3.13"' in workflow
    assert "QT_QPA_PLATFORM: offscreen" in workflow
    assert "windows-latest" not in workflow
    assert "build_installer.bat" not in workflow
    assert "dist\\BioAuth" not in workflow


def test_tests_workflow_runs_compile_smoke_and_pytest_coverage() -> None:
    workflow = _read(".github/workflows/tests.yml")
    assert "python -m compileall -q ." in workflow
    assert "python -m pytest -q" in workflow
    assert "--cov=." in workflow
    assert "--cov-report=term-missing" in workflow
    assert "--cov-report=xml:reports/coverage/coverage.xml" in workflow
    assert "--junitxml=reports/coverage/pytest-junit.xml" in workflow
    assert "reports/coverage/coverage.xml" in workflow
    assert "reports/coverage/pytest-junit.xml" in workflow


def test_tests_workflow_runs_blocking_audit_and_generates_artifacts() -> None:
    workflow = _read(".github/workflows/tests.yml")
    assert "python -m pip_audit -r requirements.txt -f json -o reports/audit/pip-audit-runtime.json" in workflow
    assert "python -m pip_audit -r requirements-pro.txt -f json -o reports/audit/pip-audit-pro.json" in workflow
    assert "continue-on-error" not in workflow
    assert "reports/audit/*.json" in workflow
    assert "name: bioauth-pip-audit-${{ github.run_id }}" in workflow


def test_tests_workflow_generates_cyclonedx_sbom_and_uploads_it() -> None:
    workflow = _read(".github/workflows/tests.yml")
    assert "cyclonedx-py requirements requirements.txt --of JSON -o reports/sbom/bioauth-runtime.cdx.json" in workflow
    assert "cyclonedx-py requirements requirements-pro.txt --of JSON -o reports/sbom/bioauth-pro.cdx.json" in workflow
    assert "reports/sbom/*.cdx.json" in workflow
    assert "name: bioauth-sbom-${{ github.run_id }}" in workflow


def test_audit_requirements_include_pip_audit_and_cyclonedx_bom() -> None:
    requirements = _read("requirements-audit.txt")
    assert "pip-audit" in requirements
    assert "cyclonedx-bom" in requirements


def test_docs_match_actual_workflow_names_and_boundaries() -> None:
    readme = _read("README_desktop_beta.md")
    readiness = _read("docs/COMMERCIAL_MVP_READINESS.md")
    ci_doc = _read("docs/CI_COVERAGE_AUDIT_SBOM.md")
    combined = "\n".join([readme, readiness, ci_doc])
    assert ".github/workflows/tests.yml" in combined
    assert ".github/workflows/release.yml" in combined
    assert "Linux fast" in combined
    assert "Windows packaged" in combined
    assert "SBOM" in combined
    assert "pip-audit" in combined


def test_release_workflow_remains_windows_packaging_boundary() -> None:
    release = _read(".github/workflows/release.yml")
    assert "runs-on: windows-latest" in release
    assert "dist\\BioAuth\\BioAuth.exe --self-check-packaging" in release
    assert "build_installer.bat" in release
    assert "Upload release artifacts" in release


def test_workflow_yaml_static_sanity() -> None:
    workflow = _read(".github/workflows/tests.yml")
    assert "\t" not in workflow
    assert workflow.count("${{") == workflow.count("}}")
    assert "jobs:" in workflow
    assert "steps:" in workflow
    assert workflow.rstrip().endswith("reports/sbom/*.cdx.json")
