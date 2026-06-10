"""Thin compatibility wrapper for the BioAuth logger worker.

Root ``logger.py`` remains because packaged workers and source launches still
execute this filename directly. Runtime orchestration lives in
``bioauth_runtime.logger_worker`` and executes in-process; this wrapper must not
spawn or relaunch another Python interpreter.
"""
from __future__ import annotations


def _guard_root_wrapper() -> None:
    from pathlib import Path
    from bioauth_runtime.wrapper_guard import enter_root_wrapper

    result = enter_root_wrapper("logger", project_root=str(Path(__file__).resolve().parent), script_path=str(Path(__file__).resolve()))
    if not bool(result.get("ok")):
        raise SystemExit(2)


def legacy_public_api():
    from bioauth_runtime.logger_worker.main import legacy_public_api as _legacy_public_api

    return _legacy_public_api()


def main(argv: list[str] | None = None) -> int:
    from bioauth_runtime.logger_worker.main import main as _main

    return int(_main(argv) or 0)


def run_logger(argv: list[str] | None = None) -> int:
    from bioauth_runtime.logger_worker.main import run_logger as _run_logger

    return int(_run_logger(argv) or 0)


def __getattr__(name: str):
    api = legacy_public_api()
    if name in api:
        globals().update(api)
        globals()["main"] = main
        globals()["run_logger"] = run_logger
        return api[name]
    raise AttributeError(name)


if __name__ == "__main__":
    _guard_root_wrapper()
    raise SystemExit(main())
