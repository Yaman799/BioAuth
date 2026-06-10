from __future__ import annotations

"""Commercial PyInstaller allowlist for BioAuth Desktop.

This module is intentionally used by ``BioAuth.spec`` only.  It does not
change runtime behavior; it only describes which source-tree files are allowed
as PyInstaller data files in the commercial package.
"""

import fnmatch
import os
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from build_tools.demo_classic_policy import is_demo_classic_path

DataPair = Tuple[str, str]

# Root files that are intentionally carried as data files in the commercial
# package.  Runtime Python modules are also discovered/imported by PyInstaller,
# but keeping the compatibility entry files visible preserves worker/self-check
# expectations without collecting the whole repository.
COMMERCIAL_ROOT_FILES: tuple[str, ...] = (
    "desktop_app.py",
    "worker_bootstrap.py",
    "logger.py",
    "monitor.py",
    "model_training.py",
    "model_inference.py",
    "paths.py",
    "security.py",
    "secure_storage.py",
    "app_settings.py",
    "license_manager.py",
    "runtime_policy.py",
    "safety_gate_policy.py",
    "identity_confirmation.py",
    "face_camera_provider.py",
    "release_profile.py",
    "release_runtime.py",
    "PRIVACY_POLICY.md",
    "EULA.txt",
    "VERSION",
    "release_config.json",
    "bioauth.ico",
    "logo.png",
)

# New src-layout commercial package.  Root compatibility wrappers stay in
# COMMERCIAL_ROOT_FILES while moved implementations are collected from src/.
COMMERCIAL_SRC_PACKAGE_DIRS: tuple[str, ...] = (
    "src/bioauth",
)

# Runtime packages/directories required by the desktop product.  These are
# source allowlist entries, not broad repository includes.
COMMERCIAL_RUNTIME_DIRS: tuple[str, ...] = (
    "bridge",
    "monitor_core",
    "feature_extractors",
    "metadata_core",
    "model_runtime",
    "bioauth_model",
    "training_core",
    "shadow_core",
    "bio_platform",
    # Dynamic runtime imports used by desktop_app/self-checks.  They are kept
    # explicit so the commercial package remains closed over runtime features
    # without collecting tests, docs, reports, or dev tools.
    "companion",
    "deep_sequence",
    "evaluation_core",
    "hybrid_candidates",
    "utils",
)

# Build support files that are allowed inside a package because packaged
# self-check/release-readiness commands import them or verify their presence.
# Full build_tools/, demo hooks, signing tools, and local build scripts are not
# collected by the commercial spec.
COMMERCIAL_BUILD_SUPPORT_FILES: tuple[str, ...] = (
    "build_tools/packaged_runtime_support.py",
    "build_tools/packaged_smoke.py",
    "build_tools/packaged_smoke_entry.py",
    "build_tools/generate_update_manifest.py",
)

DEMO_BUILD_SUPPORT_FILES: tuple[str, ...] = (
    "build_tools/runtime_demo_classic_protected.py",
)

# Commercial config is intentionally narrow: onboarding slide metadata and the
# fullscreen onboarding images referenced by that metadata.  Old/alternate
# onboarding image sets are repository assets only.
COMMERCIAL_CONFIG_FILES: tuple[str, ...] = (
    "config/onboarding_slides.json",
)
COMMERCIAL_CONFIG_DIRS: tuple[str, ...] = (
    "config/onboarding_assets/fullscreen",
)

# QML is collected file-by-file so unused generated image sets can be excluded
# while preserving all QML pages/components/theme files and referenced assets.
QML_UNUSED_ASSET_PREFIXES: tuple[str, ...] = (
    "qml/assets/bioauth/01_hero_full_uncut",
    "qml/assets/bioauth/02_hero_16x9_fit_no_crop",
    "qml/assets/bioauth/03_small_icon_tiles_uncut",
    "qml/assets/bioauth/04_badges_uncut",
    "qml/assets/bioauth/05_contact_sheets",
    "qml/assets/bioauth/05_flat_icons",
)
QML_UNUSED_ASSET_FILES: tuple[str, ...] = (
    "qml/assets/bioauth/ASSET_MANIFEST.json",
)

# Repository-only/development roots that must never be collected by the
# commercial package unless a future explicit build profile adds a separate
# allowlist.  These are kept for reporting and validation.
COMMERCIAL_EXCLUDED_ROOTS: tuple[str, ...] = (
    "tests",
    "docs",
    "reports",
    ".github",
    "archive",
    "tools/dev",
    "scripts/debug",
)

_FORBIDDEN_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
}
_FORBIDDEN_FILE_PATTERNS = (
    "*.pyc",
    "*.pyo",
    "*.tmp",
    "*.bak",
    "*.orig",
    "*.rej",
    "pytest*.log",
    "*.log",
    "*.jsonl",
    "DEMO_CLASSIC_*_Report.md",
    "RUNTIME_*_PATCH_REPORT.md",
    "LOCK_FACE_*_PATCH_REPORT.md",
    "UI_SOUND_*_PATCH_REPORT.md",
    "PATCH_NOTES.txt",
    "STARTUP_QML_REPAIR_NOTE.txt",
    "DEV_MONITOR_LOGGING.md",
    "DEV_LOCK_OVERRIDE_TESTING.md",
    "BUILD_DEMO_CLASSIC_PROTECTED_EXE.md",
)


def _as_posix(path: Path | str) -> str:
    return str(path).replace(os.sep, "/")


def _is_forbidden_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, pattern) for pattern in _FORBIDDEN_FILE_PATTERNS)


def _is_forbidden_path(rel: str) -> bool:
    parts = rel.split("/")
    if any(part in _FORBIDDEN_DIR_NAMES for part in parts):
        return True
    if any(rel == root or rel.startswith(root + "/") for root in COMMERCIAL_EXCLUDED_ROOTS):
        return True
    if _is_forbidden_file(rel):
        return True
    return False


def _should_skip_qml(rel: str) -> bool:
    if rel in QML_UNUSED_ASSET_FILES:
        return True
    return any(rel == prefix or rel.startswith(prefix + "/") for prefix in QML_UNUSED_ASSET_PREFIXES)


def _collect_file(root: Path, rel: str, *, include_demo: bool = False) -> list[DataPair]:
    path = root / rel
    if not path.exists() or _is_forbidden_path(rel):
        return []
    if not include_demo and is_demo_classic_path(rel):
        return []
    return [(rel, ".")]


def _collect_tree(root: Path, source_dir: str, dest_dir: str | None = None, *, qml_filter: bool = False, include_demo: bool = False) -> list[DataPair]:
    base = root / source_dir
    if not base.exists():
        return []
    dest_root = dest_dir or source_dir
    items: list[DataPair] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = _as_posix(path.relative_to(root))
        if _is_forbidden_path(rel):
            continue
        if not include_demo and is_demo_classic_path(rel):
            continue
        if qml_filter and _should_skip_qml(rel):
            continue
        dest = _as_posix(Path(dest_root) / Path(rel).relative_to(source_dir).parent)
        items.append((rel, dest))
    return items


def _dedupe(pairs: Iterable[DataPair]) -> list[DataPair]:
    seen: set[DataPair] = set()
    out: list[DataPair] = []
    for src, dest in pairs:
        pair = (_as_posix(src), _as_posix(dest) or ".")
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    return out


def collect_commercial_datas(project_root: str | os.PathLike[str] = ".", *, include_demo: bool = False) -> list[DataPair]:
    """Return PyInstaller data tuples for the commercial package allowlist."""

    root = Path(project_root)
    pairs: list[DataPair] = []

    for rel in COMMERCIAL_ROOT_FILES:
        pairs.extend(_collect_file(root, rel, include_demo=include_demo))

    for rel in COMMERCIAL_BUILD_SUPPORT_FILES:
        path = root / rel
        if path.exists() and not _is_forbidden_path(rel):
            pairs.append((rel, _as_posix(Path(rel).parent)))

    if include_demo:
        for rel in DEMO_BUILD_SUPPORT_FILES:
            path = root / rel
            if path.exists() and not _is_forbidden_path(rel):
                pairs.append((rel, _as_posix(Path(rel).parent)))

    for rel in COMMERCIAL_CONFIG_FILES:
        pairs.extend(_collect_file(root, rel, include_demo=include_demo))
    for rel in COMMERCIAL_CONFIG_DIRS:
        pairs.extend(_collect_tree(root, rel, rel, include_demo=include_demo))

    pairs.extend(_collect_tree(root, "qml", "qml", qml_filter=True, include_demo=include_demo))
    pairs.extend(_collect_tree(root, "models/face", "models/face", include_demo=include_demo))

    # Include src/bioauth implementation modules while root wrappers preserve
    # legacy imports during the gradual commercial package split.
    for rel in COMMERCIAL_SRC_PACKAGE_DIRS:
        pairs.extend(_collect_tree(root, rel, rel, include_demo=include_demo))

    for rel in COMMERCIAL_RUNTIME_DIRS:
        pairs.extend(_collect_tree(root, rel, rel, include_demo=include_demo))

    return _dedupe(pairs)


__all__ = [
    "COMMERCIAL_BUILD_SUPPORT_FILES",
    "COMMERCIAL_CONFIG_DIRS",
    "COMMERCIAL_CONFIG_FILES",
    "COMMERCIAL_EXCLUDED_ROOTS",
    "COMMERCIAL_ROOT_FILES",
    "COMMERCIAL_SRC_PACKAGE_DIRS",
    "COMMERCIAL_RUNTIME_DIRS",
    "DEMO_BUILD_SUPPORT_FILES",
    "QML_UNUSED_ASSET_FILES",
    "QML_UNUSED_ASSET_PREFIXES",
    "collect_commercial_datas",
]
