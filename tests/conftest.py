from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Optional sandbox-only forced exit after a compact pytest summary."""
    if os.environ.get("BIOAUTH_FORCE_PYTEST_EXIT") == "1":
        passed = len(terminalreporter.stats.get("passed", []))
        failed = len(terminalreporter.stats.get("failed", []))
        errors = len(terminalreporter.stats.get("error", []))
        duration = max(0.0, time.time() - float(getattr(terminalreporter, "_sessionstarttime", time.time()) or time.time()))
        if failed or errors or exitstatus:
            terminalreporter.write_line(f"{failed} failed, {errors} errors in {duration:.2f}s")
        else:
            terminalreporter.write_line(f"{passed} passed in {duration:.2f}s")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(int(exitstatus or 0))


_SYS_MODULES_GUARDED_NAMES = (
    "paths",
    "security",
    "pandas",
    "deep_runtime",
    "features",
    "utils",
    "utils.identity",
    "metadata_core.runtime",
    "bio_platform.secrets",
    "cryptography",
    "cryptography.fernet",
    "numpy",
    "artifact_integrity",
    "sklearn",
    "sklearn.ensemble",
    "sklearn.metrics",
    "sklearn.model_selection",
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtQml",
    "PySide6.QtWidgets",
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",
)


def _is_test_stub_module(module: object) -> bool:
    """Return True for lightweight ModuleType stubs injected by tests.

    Real project and third-party modules normally expose ``__file__``. The
    pollution that broke later imports used bare ``types.ModuleType`` objects
    without a source path, so only those synthetic modules are cleaned up.
    """

    return getattr(module, "__file__", None) in (None, "") and getattr(module, "__name__", None) is not None


@pytest.fixture(autouse=True)
def _restore_guarded_sys_modules_after_test():
    before = {name: sys.modules.get(name) for name in _SYS_MODULES_GUARDED_NAMES}
    yield
    for name in _SYS_MODULES_GUARDED_NAMES:
        current = sys.modules.get(name)
        original = before[name]
        if current is original:
            continue
        if current is not None and _is_test_stub_module(current):
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def _reset_security_caches_if_loaded() -> None:
    module = sys.modules.get("security")
    reset = getattr(module, "reset_security_caches", None)
    if callable(reset):
        reset()


@pytest.fixture(autouse=True)
def _reset_security_caches_around_test():
    # Several encrypted-session tests reload security/path modules and point the
    # secret key at per-test temp folders.  Clearing only memoized key/cipher
    # objects between tests prevents a stale Fernet key from being reused with a
    # newly monkeypatched KEY_FILE, without changing production encryption.
    _reset_security_caches_if_loaded()
    yield
    _reset_security_caches_if_loaded()
