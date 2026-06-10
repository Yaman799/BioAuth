"""Thin compatibility wrapper for the BioAuth monitor worker.

Root ``monitor.py`` remains because packaged workers and source launches still
execute this filename directly. Runtime orchestration enters through
``bioauth_runtime.monitor_worker`` and executes in-process; this wrapper must
not spawn or relaunch another Python interpreter.
"""
from __future__ import annotations


def _guard_root_wrapper() -> None:
    from pathlib import Path
    from bioauth_runtime.wrapper_guard import enter_root_wrapper

    result = enter_root_wrapper("monitor", project_root=str(Path(__file__).resolve().parent), script_path=str(Path(__file__).resolve()))
    if not bool(result.get("ok")):
        raise SystemExit(2)


def legacy_public_api():
    from bioauth_runtime.monitor_worker.main import legacy_public_api as _legacy_public_api

    return _legacy_public_api()


def main(argv: list[str] | None = None) -> int:
    from bioauth_runtime.monitor_worker.main import main as _main

    return int(_main(argv) or 0)


def run_monitor(argv: list[str] | None = None) -> int:
    from bioauth_runtime.monitor_worker.main import run_monitor as _run_monitor

    return int(_run_monitor(argv) or 0)


def monitor(argv: list[str] | None = None) -> int:
    """Historical public worker entrypoint."""
    return run_monitor(argv)


def __getattr__(name: str):
    api = legacy_public_api()
    if name in api:
        globals().update(api)
        globals()["main"] = main
        globals()["run_monitor"] = run_monitor
        globals()["monitor"] = monitor
        return api[name]
    raise AttributeError(name)


if __name__ == "__main__":
    _guard_root_wrapper()
    raise SystemExit(main())
