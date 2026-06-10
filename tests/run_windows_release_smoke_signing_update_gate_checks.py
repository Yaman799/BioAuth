#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
TEST_MODULE_PATH = Path(__file__).with_name("test_windows_release_smoke_signing_update_gate.py")


def _load_test_module():
    spec = importlib.util.spec_from_file_location("test_windows_release_smoke_signing_update_gate", TEST_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load Windows release smoke/signing/update gate test module")
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_windows_release_smoke_signing_update_gate"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    module = _load_test_module()
    checks: list[Callable[[], None]] = [
        module.test_windows_release_gate_doc_marks_public_release_blocked_without_evidence,
        module.test_signature_verification_helper_is_present_and_policy_safe,
        module.test_installer_build_has_interpreter_and_signature_verification,
        module.test_release_workflow_keeps_windows_boundary_and_verifies_signatures,
        module.test_readme_does_not_claim_linux_ci_proves_windows_release,
        module.test_production_signing_is_fail_closed,
        module.test_update_gate_uses_manual_sha256_path_without_silent_install,
    ]
    for check in checks:
        check()
        print(f"PASS {check.__name__}", flush=True)
    if os.name != "nt":
        print("WINDOWS_ARTIFACT_EXECUTION_SKIPPED=non_windows", flush=True)
        print("REASON=Windows installer/signature artifact execution requires Windows and is covered by the release workflow.", flush=True)
    else:
        print("WINDOWS_ARTIFACT_EXECUTION_STATIC_ONLY=runner_validates_gates_without_building_artifacts", flush=True)
    print(f"ALL_WINDOWS_RELEASE_GATE_CHECKS_PASSED={len(checks)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
