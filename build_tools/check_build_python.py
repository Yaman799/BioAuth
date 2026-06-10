from __future__ import annotations

import platform
import struct
import sys


def fail(message: str) -> int:
    print(f"[FAIL] {message}")
    return 1


def main() -> int:
    version = sys.version_info
    bits = struct.calcsize("P") * 8
    machine = platform.machine().lower()
    print(f"[INFO] Python executable: {sys.executable}")
    print(f"[INFO] Python version   : {version.major}.{version.minor}.{version.micro}")
    print(f"[INFO] Python arch      : {bits}-bit ({machine})")

    if "WindowsApps" in sys.executable:
        return fail("Microsoft Store Python is not supported for stable EXE builds. Install python.org x64 Python 3.11 and rebuild the .venv.")

    if bits != 64:
        return fail("Use 64-bit Python. 32-bit Python is not supported for this build.")

    if version[:2] != (3, 11):
        return fail("Recommended build interpreter is Python 3.11 x64. Recreate .venv with py -3.11 -m venv .venv")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
