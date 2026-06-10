from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate SHA256SUMS for release artifacts.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("SHA256SUMS.txt"))
    args = parser.parse_args(argv)
    rows = []
    for root in args.paths:
        if not root.exists():
            continue
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in sorted(files):
            if path.name == args.output.name:
                continue
            rows.append(f"{sha256_file(path)}  {path.as_posix()}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    print(f"[ OK ] Wrote checksums: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
