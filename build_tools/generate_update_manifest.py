from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict

try:
    from generate_checksums import sha256_file
    from versioning import normalize_tag_or_version, read_version
except ModuleNotFoundError:
    from build_tools.generate_checksums import sha256_file
    from build_tools.versioning import normalize_tag_or_version, read_version

REQUIRED_FIELDS = {
    "app",
    "channel",
    "version",
    "installer_name",
    "installer_sha256",
    "min_supported_version",
    "mandatory",
    "release_notes",
    "published_at",
}


def _published_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_manifest(
    *,
    installer: Path,
    version: str,
    channel: str,
    min_supported_version: str,
    mandatory: bool,
    release_notes: str,
    published_at: str,
) -> Dict[str, Any]:
    if not installer.is_file():
        raise FileNotFoundError(f"Installer file not found: {installer}")
    normalized_version = normalize_tag_or_version(version)
    normalized_min = normalize_tag_or_version(min_supported_version)
    installer_hash = sha256_file(installer)
    if not installer_hash or len(installer_hash) != 64:
        raise ValueError("installer_sha256 must be a non-empty SHA256 hash")
    manifest: Dict[str, Any] = {
        "app": "BioAuth",
        "channel": str(channel or "beta").strip().lower(),
        "version": normalized_version,
        "installer_name": installer.name,
        "installer_sha256": installer_hash,
        "min_supported_version": normalized_min,
        "mandatory": bool(mandatory),
        "release_notes": str(release_notes or "").strip(),
        "published_at": str(published_at or "").strip(),
        "update_manifest_name": "bioauth-update.json",
        "artifact_names": [installer.name, "bioauth-update.json", "SHA256SUMS.txt"],
        "checksums": {installer.name: installer_hash},
    }
    missing = sorted(REQUIRED_FIELDS.difference(manifest.keys()))
    if missing:
        raise ValueError("Manifest missing required fields: " + ", ".join(missing))
    if not manifest["channel"]:
        raise ValueError("Manifest channel must not be empty")
    if not manifest["release_notes"]:
        raise ValueError("Manifest release_notes must not be empty")
    if not manifest["published_at"]:
        raise ValueError("Manifest published_at must not be empty")
    return manifest


def write_release_checksums(installer: Path, manifest_path: Path, output: Path) -> None:
    rows = []
    for path in (installer, manifest_path):
        rows.append(f"{sha256_file(path)}  {path.name}")
    output.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate BioAuth GitHub Release update manifest and release SHA256SUMS.")
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--version", default="")
    parser.add_argument("--channel", default="beta")
    parser.add_argument("--min-supported-version", default="1.0.0")
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--release-notes", default="BioAuth beta update.")
    parser.add_argument("--release-notes-file", type=Path)
    parser.add_argument("--published-at", default="")
    parser.add_argument("--output", type=Path, default=Path("bioauth-update.json"))
    parser.add_argument("--sums-output", type=Path, default=Path("SHA256SUMS.txt"))
    args = parser.parse_args(argv)

    notes = args.release_notes
    if args.release_notes_file and args.release_notes_file.is_file():
        notes = args.release_notes_file.read_text(encoding="utf-8").strip()
    version = args.version or read_version()
    manifest = build_manifest(
        installer=args.installer,
        version=version,
        channel=args.channel,
        min_supported_version=args.min_supported_version,
        mandatory=bool(args.mandatory),
        release_notes=notes,
        published_at=args.published_at or _published_now(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    write_release_checksums(args.installer, args.output, args.sums_output)
    print(f"[ OK ] Wrote update manifest: {args.output}")
    print(f"[ OK ] Wrote release checksums: {args.sums_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
