from __future__ import annotations

import argparse
from pathlib import Path

from versioning import pyinstaller_version_info_text, read_version, write_version


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PyInstaller Windows version_info.txt for BioAuth.exe.")
    parser.add_argument("--version", default="", help="Version or Git tag. Defaults to VERSION file.")
    parser.add_argument("--output", type=Path, default=Path("version_info.txt"))
    args = parser.parse_args()
    version = write_version(args.version) if args.version else read_version()
    args.output.write_text(pyinstaller_version_info_text(version), encoding="utf-8")
    print(f"[ OK ] Wrote {args.output} for BioAuth {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
