from __future__ import annotations

import importlib


def test_project_modules_are_real_after_prior_test_stubs() -> None:
    expectations = {
        "paths": "monitor_log_file",
        "security": "atomic_write_text",
        "deep_runtime": "resolve_runtime_rollout_state",
        "features": "extract_combined_features",
    }
    for module_name, attribute in expectations.items():
        module = importlib.import_module(module_name)
        assert hasattr(module, attribute), f"{module_name} lost {attribute}; likely sys.modules pollution"
        assert getattr(module, "__file__", None), f"{module_name} resolved to a synthetic test stub"


def test_optional_dependency_stubs_do_not_replace_installed_packages() -> None:
    for module_name in ("pandas", "numpy"):
        module = importlib.import_module(module_name)
        assert getattr(module, "__file__", None), f"{module_name} resolved to a synthetic test stub"
