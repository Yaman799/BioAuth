from __future__ import annotations

import argparse
import fnmatch
from pathlib import Path

FORBIDDEN_NAMES = {
    ".github",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    ".coverage",
    "archive",
    "docs",
    "reports",
    "tests",
    "validation",
    "validation_artifacts",
    "old_supervised_block.txt",
    "train_model_chunk.txt",
    "BioAuth_Phase0_Freeze_Artifacts.zip",
    "BioAuth_Phase1_Report_And_Patch.zip",
    "BioAuth_Phase2_Report_And_Patch.zip",
    "BioAuth_Phase3_Report_And_Patch.zip",
    "BioAuth_Phase4_Report_And_Patch.zip",
    "BioAuth_Phase5_Report_And_Patch.zip",
}

FORBIDDEN_PATTERNS = (
    "pytest*.log",
    "manual_phase*.log",
    "phase*_*.log",
    "*.pyc",
    "*.pyo",
    "*.tmp",
    "*.bak",
    "*.orig",
    "*.rej",
    "*.patch",
    "*.diff",
    "*.pkl",
    "*.joblib",
    "*.pt",
    "*.onnx",
    "*.sqlite",
    "*.db",
    "*.jsonl",
    "*.exitcode",
    "*.log.md",
    "*.manifest.json",
    "*.manifest_compare.json",
    "*.delivery_report.json",
    "*.delivery_gate.log",
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

ALLOWED_SOURCE_ONLY = {
    "requirements-dev.txt",
}

# These are valid source-tree compatibility files, but they should not be
# collected into the packaged PyInstaller release path.  Keep this as a
# release-only check so local source scans do not fail just because the repo
# still carries compatibility wrappers.
RELEASE_ONLY_FORBIDDEN_NAMES = {
    "desktop_app_tk.py",
    "legacy",
    "ui",
}


def _is_allowed_evidence_exception(path: Path) -> bool:
    """Return True for runtime model assets allowed in commercial output.

    Commercial-CLEAN-02 excludes all reports/docs from packaged output.  Required
    face model files under models/face remain allowed even when their extension
    would normally be considered a generated model artifact.
    """

    parts = path.parts
    return len(parts) >= 2 and parts[0] == "models" and parts[1] == "face"


def _is_allowed_source_safety_report(path: Path, *, release_mode: bool) -> bool:
    """Allow source-tree safety policy docs while keeping dist output clean."""
    parts = path.parts
    if release_mode or not parts or parts[0] != "reports":
        return False
    return len(parts) == 1 or (len(parts) >= 2 and parts[1] == "safety")


def _is_generated_evidence_path(path: Path) -> bool:
    parts = path.parts
    if len(parts) >= 2 and parts[0] == "docs" and parts[1] in {"validation", "manifests"}:
        return True
    if len(parts) >= 1 and parts[0] == "validation":
        return True
    if len(parts) >= 1 and parts[0] == "validation_artifacts":
        return True
    if len(parts) >= 1 and parts[0] == "docs":
        return True
    if len(parts) >= 1 and parts[0] == "reports":
        return True
    return False


def _is_forbidden(path: Path, *, release_mode: bool = True) -> bool:
    if _is_allowed_evidence_exception(path):
        return False
    if _is_allowed_source_safety_report(path, release_mode=release_mode):
        return False
    if _is_generated_evidence_path(path):
        return True
    parts_tuple = path.parts
    parts = set(parts_tuple)
    if parts & FORBIDDEN_NAMES:
        return True
    if len(parts_tuple) >= 2 and parts_tuple[0] == "tools" and parts_tuple[1] == "dev":
        return True
    if len(parts_tuple) >= 2 and parts_tuple[0] == "scripts" and parts_tuple[1] == "debug":
        return True
    if release_mode and (parts & RELEASE_ONLY_FORBIDDEN_NAMES):
        return True
    name = path.name
    return any(fnmatch.fnmatch(name, pattern) for pattern in FORBIDDEN_PATTERNS)


def scan_profile_exclusions(root: Path, excluded_packages: list[str]) -> list[str]:
    problems: list[str] = []
    normalized = {str(item).lower().replace("-", "_") for item in excluded_packages}
    if not normalized or not root.exists():
        return problems
    for path in root.rglob("*"):
        name = path.name.lower().replace("-", "_")
        stem = path.stem.lower().replace("-", "_")
        for package in normalized:
            if name == package or stem == package or name.startswith(package + ".") or name.startswith(package + "_"):
                problems.append(str(path.relative_to(root)))
    return sorted(set(problems))


def scan_tree(root: Path, *, release_mode: bool = True) -> list[str]:
    problems: list[str] = []
    if not root.exists():
        return [f"missing path: {root}"]
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if str(rel) in ALLOWED_SOURCE_ONLY:
            continue
        if _is_forbidden(rel, release_mode=release_mode):
            problems.append(str(rel))
    return sorted(set(problems))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail release builds that contain dev/cache/log/scratch artifacts.")
    parser.add_argument("--dist", type=Path, required=True, help="Packaged dist directory to scan, e.g. dist/BioAuth")
    parser.add_argument("--source-tree", action="store_true", help="Scan a source checkout; allow compatibility-only legacy sources.")
    args = parser.parse_args(argv)

    problems = scan_tree(args.dist, release_mode=not args.source_tree)
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from release_profile import package_profile_payload
        profile = package_profile_payload()
        profile_hits = scan_profile_exclusions(args.dist, list(profile.get("excluded_packages") or []))
        problems.extend(f"profile_excluded_dependency:{item}" for item in profile_hits)
    except Exception as exc:
        print(f"[WARN] Package profile exclusion scan skipped: {exc}")
    if problems:
        print("[FAIL] Release hygiene check found forbidden files:")
        for item in problems:
            print(f"  - {item}")
        return 1
    print(f"[ OK ] Release hygiene check passed: {args.dist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
