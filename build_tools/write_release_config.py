from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "release_config.json"


def build_release_config(
    *,
    owner: str,
    repo: str,
    channel: str,
    api_base: str,
    manifest_name: str,
    verification: str,
    signing_required: bool,
    silent_install: bool,
) -> dict:
    owner = str(owner or "").strip()
    repo = str(repo or "").strip()
    channel = str(channel or "beta").strip().lower()
    api_base = str(api_base or "https://api.github.com").strip().rstrip("/")
    manifest_name = str(manifest_name or "bioauth-update.json").strip()
    verification = str(verification or "sha256").strip().lower()
    if not owner or owner == "CHANGE_ME_OWNER":
        raise ValueError("A real GitHub repository owner is required.")
    if not repo or repo == "CHANGE_ME_REPO":
        raise ValueError("A real GitHub repository name is required.")
    if verification != "sha256":
        raise ValueError("This release path currently supports SHA256 verification only.")
    if not manifest_name or "/" in manifest_name or "\\" in manifest_name:
        raise ValueError("manifest_name must be a safe file name.")
    return {
        "update_repo_owner": owner,
        "update_repo_name": repo,
        "update_channel": channel,
        "update_api_base": api_base,
        "manifest_name": manifest_name,
        "verification": verification,
        "signing_required": bool(signing_required),
        "silent_install": bool(silent_install),
        "notes": "Generated for this GitHub Release build. Updates are verified by SHA256; silent install is disabled.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write BioAuth GitHub Release updater configuration.")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--channel", default="beta")
    parser.add_argument("--api-base", default="https://api.github.com")
    parser.add_argument("--manifest-name", default="bioauth-update.json")
    parser.add_argument("--verification", default="sha256")
    parser.add_argument("--signing-required", action="store_true")
    parser.add_argument("--silent-install", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = build_release_config(
        owner=args.owner,
        repo=args.repo,
        channel=args.channel,
        api_base=args.api_base,
        manifest_name=args.manifest_name,
        verification=args.verification,
        signing_required=bool(args.signing_required),
        silent_install=bool(args.silent_install),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[ OK ] Wrote release config: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
