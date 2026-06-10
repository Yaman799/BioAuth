from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("test_ci_coverage_audit_sbom_gate.py")
spec = importlib.util.spec_from_file_location("test_ci_coverage_audit_sbom_gate", MODULE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("failed to load CI gate test module")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

TESTS = [
    module.test_tests_workflow_exists_and_is_linux_fast_gate,
    module.test_tests_workflow_runs_compile_smoke_and_pytest_coverage,
    module.test_tests_workflow_runs_blocking_audit_and_generates_artifacts,
    module.test_tests_workflow_generates_cyclonedx_sbom_and_uploads_it,
    module.test_audit_requirements_include_pip_audit_and_cyclonedx_bom,
    module.test_docs_match_actual_workflow_names_and_boundaries,
    module.test_release_workflow_remains_windows_packaging_boundary,
    module.test_workflow_yaml_static_sanity,
]

for test in TESTS:
    test()
    print(f"PASS {test.__name__}")

print(f"ALL_CI_COVERAGE_AUDIT_SBOM_CHECKS_PASSED={len(TESTS)}")
