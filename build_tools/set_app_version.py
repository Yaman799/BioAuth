from __future__ import annotations

import argparse

from versioning import write_version


def main() -> int:
    parser = argparse.ArgumentParser(description="Set the BioAuth source-of-truth VERSION file for a build.")
    parser.add_argument("version", help="Version or Git tag, for example v1.0.1-beta.1")
    args = parser.parse_args()
    version = write_version(args.version)
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
