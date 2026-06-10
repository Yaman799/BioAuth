from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_file(zf: zipfile.ZipFile, path: Path, arcname: str, added: List[str]) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        zf.write(path, arcname)
        added.append(arcname)
    except OSError:
        return


def _iter_recent_files(directory: Path, patterns: Iterable[str], *, limit: int) -> List[Path]:
    files: List[Path] = []
    if not directory.exists():
        return files
    for pattern in patterns:
        files.extend([p for p in directory.glob(pattern) if p.is_file()])
    unique = sorted(set(files), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return unique[: max(1, limit)]


def _app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "BioAuth"
    return Path.home() / ".local" / "share" / "BioAuth"


def _write_summary(out_dir: Path, added: List[str], extra: dict) -> Path:
    summary = {
        "schema_version": "bioauth-dev-monitor-log-bundle-v1",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "project_root": str(_project_root()),
        "app_data_dir": str(_app_data_dir()),
        "added_files": added,
        **extra,
    }
    path = out_dir / "dev_monitor_log_bundle_summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def build_bundle(output_dir: Path, *, recent_limit: int = 10) -> Path:
    root = _project_root()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / f"bioauth_dev_monitor_logs_{_utc_stamp()}.zip"
    added: List[str] = []
    app_data = _app_data_dir()
    data_dir = app_data / "data"

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Dev JSONL logs produced by tools/dev/launchers/run_desktop_dev_lock_override.bat.
        for p in _iter_recent_files(root / "dev_monitor_logs", ["*.jsonl", "*.log", "*.txt"], limit=recent_limit):
            _add_file(zf, p, f"project/dev_monitor_logs/{p.name}", added)

        # Normal app/debug logs. They contain paths and diagnostics, not raw keystroke rows.
        for name in ["bioauth_debug_panel.log", "start_app_qml_error.log"]:
            _add_file(zf, root / name, f"project/{name}", added)

        # Encrypted monitor log and runtime state files from app data.
        for name in ["monitor_log.json.enc", "session_state.json", "settings.json"]:
            _add_file(zf, data_dir / name, f"app_data/data/{name}", added)

        # Control marker files can explain stop/start behavior; they are tiny and non-raw.
        control_dir = data_dir / "control"
        for p in _iter_recent_files(control_dir, ["*"], limit=recent_limit):
            _add_file(zf, p, f"app_data/data/control/{p.name}", added)

        # Recent evidence metadata, not screenshots/raw captures. Avoid copying incident images/videos.
        evidence_dir = data_dir / "evidence"
        for p in _iter_recent_files(evidence_dir, ["*.json", "*.txt", "*.sha256", "*.hashes.json"], limit=recent_limit):
            _add_file(zf, p, f"app_data/data/evidence/{p.name}", added)

        # Write and include a summary last.
        summary_path = _write_summary(
            output_dir,
            added,
            {
                "bundle_path": str(bundle_path),
                "recent_limit": int(recent_limit),
                "privacy_note": "Bundle excludes raw session CSV rows and incident media. Dev JSONL monitor diagnostics include decision/risk/window summaries only.",
            },
        )
        _add_file(zf, summary_path, "dev_monitor_log_bundle_summary.json", added)

    return bundle_path


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect BioAuth dev monitor diagnostics into a shareable zip.")
    parser.add_argument("--output-dir", default=str(_project_root() / "dev_monitor_logs"), help="Directory where the bundle zip will be written.")
    parser.add_argument("--recent-limit", type=int, default=10, help="Maximum recent files per log category to include.")
    args = parser.parse_args(argv)
    bundle = build_bundle(Path(args.output_dir), recent_limit=args.recent_limit)
    print(str(bundle.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
