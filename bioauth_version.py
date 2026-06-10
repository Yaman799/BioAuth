from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Tuple

_APP_NAME = "BioAuth"
_VERSION_FILE = Path(__file__).resolve().with_name("VERSION")
_DEFAULT_VERSION = "1.0.0"
_VERSION_RE = re.compile(r"^v?(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?)$")


def normalize_version(value: str | None, *, default: str = _DEFAULT_VERSION) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = str(default or _DEFAULT_VERSION).strip()
    match = _VERSION_RE.match(raw)
    if not match:
        raise ValueError(f"Invalid BioAuth version: {raw!r}")
    return match.group("version")


def read_version_file(path: Path | None = None) -> str:
    version_path = path or _VERSION_FILE
    try:
        return normalize_version(version_path.read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return _DEFAULT_VERSION


def get_app_version() -> str:
    env_version = os.environ.get("BIOAUTH_APP_VERSION") or os.environ.get("BIOAUTH_VERSION")
    if env_version:
        return normalize_version(env_version)
    return read_version_file()


def app_name() -> str:
    return _APP_NAME


def version_as_windows_tuple(version: str | None = None) -> Tuple[int, int, int, int]:
    current = normalize_version(version or get_app_version())
    core = current.split("-", 1)[0]
    major, minor, patch = [int(part) for part in core.split(".")]
    prerelease = current.split("-", 1)[1] if "-" in current else ""
    build = 0
    if prerelease:
        numeric_parts = [int(part) for part in re.findall(r"(?:^|[.-])(\d+)(?:$|[.-])", prerelease)]
        if numeric_parts:
            build = min(max(numeric_parts[-1], 0), 65535)
    return major, minor, patch, build


APP_VERSION = get_app_version()
