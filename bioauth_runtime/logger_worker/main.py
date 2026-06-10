"""Logger worker entrypoint adapter for Clean Runtime Core V2."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .config import parse_logger_config
from .heartbeat import clean_stale_logger_temp_heartbeats


def main(argv: list[str] | None = None) -> int:
    """Run the logger worker with the legacy runtime implementation."""
    return run_logger(argv)


def run_logger(argv: list[str] | None = None) -> int:
    """Preserve CLI behavior while new modules own config and heartbeat setup."""
    if argv is not None:
        old_argv = sys.argv[:]
        sys.argv = [old_argv[0] if old_argv else "logger.py", *argv]
    else:
        old_argv = None
    try:
        parse_logger_config(sys.argv[1:])
        clean_stale_logger_temp_heartbeats()
        return int(_legacy_logger_impl().run_logger())
    finally:
        if old_argv is not None:
            sys.argv = old_argv


def legacy_public_api() -> dict[str, Any]:
    """Expose the historical logger module surface lazily for old tests/tools."""
    module = _legacy_logger_impl()
    return {name: value for name, value in module.__dict__.items() if not name.startswith("__")}


def _legacy_logger_impl() -> ModuleType:
    root = Path(__file__).resolve().parents[2]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return importlib.import_module("bioauth.input.logger_impl")
