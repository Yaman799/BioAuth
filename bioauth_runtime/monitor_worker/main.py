"""Monitor worker entrypoint adapter for Clean Runtime Core V2."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .config import parse_monitor_config
from .heartbeat import clean_stale_monitor_temp_heartbeats


def main(argv: list[str] | None = None) -> int:
    """Run the monitor worker with the legacy runtime implementation."""
    return run_monitor(argv)


def run_monitor(argv: list[str] | None = None) -> int:
    """Preserve CLI behavior while new modules own config and heartbeat setup."""
    if argv is not None:
        old_argv = sys.argv[:]
        sys.argv = [old_argv[0] if old_argv else "monitor.py", *argv]
    else:
        old_argv = None
    try:
        parse_monitor_config(sys.argv[1:])
        clean_stale_monitor_temp_heartbeats()
        result = _legacy_monitor_impl().monitor()
        return int(result or 0)
    finally:
        if old_argv is not None:
            sys.argv = old_argv


def legacy_public_api() -> dict[str, Any]:
    """Expose the historical monitor module surface lazily for old tests/tools."""
    module = _legacy_monitor_impl()
    return {name: value for name, value in module.__dict__.items() if not name.startswith("__")}


def _legacy_monitor_impl() -> ModuleType:
    root = Path(__file__).resolve().parents[2]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return importlib.import_module("bioauth.runtime.monitor_impl")
