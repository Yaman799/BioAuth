from __future__ import annotations

import json
from pathlib import Path

from build_tools.generate_update_manifest import build_manifest, main
from update_client import validate_update_manifest


def test_manifest_generator_uses_actual_installer_sha256(tmp_path: Path) -> None:
    installer = tmp_path / "BioAuthDesktopSetup_1.0.1-beta.1.exe"
    installer.write_bytes(b"dummy installer")
    output = tmp_path / "bioauth-update.json"
    sums = tmp_path / "SHA256SUMS.txt"

    exit_code = main([
        "--installer", str(installer),
        "--version", "1.0.1-beta.1",
        "--channel", "beta",
        "--release-notes", "Dummy release notes.",
        "--published-at", "2026-04-30T00:00:00Z",
        "--output", str(output),
        "--sums-output", str(sums),
    ])

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    validate_update_manifest(payload, channel="beta")
    assert payload["installer_name"] == installer.name
    assert payload["installer_sha256"] in sums.read_text(encoding="utf-8")


def test_manifest_generator_rejects_missing_installer(tmp_path: Path) -> None:
    missing = tmp_path / "missing.exe"
    try:
        build_manifest(
            installer=missing,
            version="1.0.1-beta.1",
            channel="beta",
            min_supported_version="1.0.0",
            mandatory=False,
            release_notes="Notes.",
            published_at="2026-04-30T00:00:00Z",
        )
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing installer was accepted")
