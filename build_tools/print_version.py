from __future__ import annotations

import argparse

from versioning import read_version, windows_file_version


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the BioAuth application version.")
    parser.add_argument("--windows-file-version", action="store_true", help="Print numeric Windows file version.")
    args = parser.parse_args()
    version = read_version()
    print(windows_file_version(version) if args.windows_file_version else version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
