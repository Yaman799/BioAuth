from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import traceback

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "start_app_error.log"


def _show_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "BioAuth launcher", 0x10)
    except Exception:
        pass


def _write_log(prefix: str, detail: str) -> None:
    try:
        LOG_PATH.write_text(f"{prefix}\n\n{detail}", encoding="utf-8")
    except Exception:
        pass


def main() -> None:
    os.chdir(BASE_DIR)
    sys.path.insert(0, str(BASE_DIR))
    try:
        from bioauth_runtime.desktop_relaunch_guard import record_desktop_launch_path

        record_desktop_launch_path(
            project_root=str(BASE_DIR),
            launch_path="start_app.pyw:import_desktop_app",
            command=[str(sys.executable or ""), *[str(arg) for arg in sys.argv]],
            selected_executable=str(sys.executable or ""),
            before_qt=True,
        )
    except Exception:
        pass
    import desktop_app

    desktop_app.main()


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code in (None, False) else 1)
        if code:
            detail = f"BioAuth exited during startup with code: {exc.code!r}."
            _write_log(detail, traceback.format_exc())
            _show_error(
                "BioAuth could not start.\n\n"
                "A startup log was written to start_app_error.log in the project folder."
            )
        raise
    except Exception:
        detail = traceback.format_exc()
        _write_log("BioAuth failed before the UI could open.", detail)
        _show_error(
            "BioAuth could not start.\n\n"
            "See start_app_error.log in the project folder for details."
        )
        raise SystemExit(1)
