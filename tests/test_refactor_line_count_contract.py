from __future__ import annotations

from pathlib import Path


SPLIT_DIRS = [
    Path("bridge/session_runtime_split"),
    Path("bridge/refresh_runtime_split"),
    Path("bridge/dashboard_refresh_split"),
    Path("monitor_core/common_split"),
    Path("src/bioauth/input/logger_impl_split"),
    Path("src/bioauth/runtime/monitor_impl_split"),
    Path("src/bioauth/app/desktop_app_split"),
]

ALLOWED_TARGET_EXCEPTIONS = {
    Path("src/bioauth/runtime/monitor_impl.py"): "legacy monitor() loop kept intact",
    Path("src/bioauth/app/desktop_app_impl.py"): "PySide AppBridge signal/property class kept intact",
}


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_new_split_modules_stay_below_hard_limit() -> None:
    oversized = []
    for directory in SPLIT_DIRS:
        for path in directory.glob("*.py"):
            if path.name == "__init__.py":
                continue
            lines = _line_count(path)
            if lines > 500:
                oversized.append((str(path), lines))
    assert oversized == []


def test_target_legacy_files_are_small_or_documented_exceptions() -> None:
    targets = [
        Path("bridge/session_runtime_helpers.py"),
        Path("bridge/refresh_runtime_helpers.py"),
        Path("bridge/refresh_dashboard_helpers.py"),
        Path("monitor_core/common.py"),
        Path("src/bioauth/input/logger_impl.py"),
        Path("src/bioauth/runtime/monitor_impl.py"),
        Path("src/bioauth/app/desktop_app_impl.py"),
    ]
    unexpected = [str(path) for path in targets if _line_count(path) > 300 and path not in ALLOWED_TARGET_EXCEPTIONS]
    assert unexpected == []


def test_no_new_dumping_ground_module_names() -> None:
    banned = {"runtime_helpers.py", "storage_utils.py", "process_manager.py", "common_utils.py"}
    created = {path.name for directory in SPLIT_DIRS for path in directory.glob("*.py")}
    assert banned.isdisjoint(created)
