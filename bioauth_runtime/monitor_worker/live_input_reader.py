"""Live input read boundary for monitor runtime."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Dict

from security import read_decrypted

KB_HEADER = "key,event,timestamp"
MS_HEADER = "x,y,event,timestamp"


def live_session_files(live_session_dir: str) -> dict[str, Path]:
    """Return expected live input files without reading model features."""
    base = Path(live_session_dir)
    return {"keyboard": base / "keyboard_log.csv", "mouse": base / "mouse_log.csv"}


def live_input_snapshot(live_session_dir: str) -> Dict[str, Any]:
    files = live_session_files(live_session_dir)
    keyboard = _log_snapshot(files["keyboard"], KB_HEADER)
    mouse = _log_snapshot(files["mouse"], MS_HEADER)
    return {
        "live_session_dir": str(Path(live_session_dir)) if live_session_dir else "",
        "keyboard": keyboard,
        "mouse": mouse,
        "keyboard_counter": int(keyboard.get("chunk_counter") or 0),
        "mouse_counter": int(mouse.get("chunk_counter") or 0),
        "keyboard_rows": int(keyboard.get("row_count") or 0),
        "mouse_rows": int(mouse.get("row_count") or 0),
        "input_rows": int(keyboard.get("row_count") or 0) + int(mouse.get("row_count") or 0),
        "chunk_store_present": bool(keyboard.get("chunk_store_present") or mouse.get("chunk_store_present")),
        "readable": bool(keyboard.get("readable")) or bool(mouse.get("readable")),
    }


def _log_snapshot(path: Path, header: str) -> Dict[str, Any]:
    chunk_dir = Path(str(path) + ".d")
    snapshot: Dict[str, Any] = {
        "path": str(path),
        "chunk_dir": str(chunk_dir),
        "file_present": path.is_file(),
        "chunk_store_present": chunk_dir.is_dir(),
        "chunk_counter": _read_counter(chunk_dir),
        "chunk_file_count": _chunk_file_count(chunk_dir),
        "row_count": 0,
        "readable": False,
        "error": "",
    }
    if not path.is_file() and not chunk_dir.is_dir():
        return snapshot
    try:
        text = read_decrypted(str(path), header, strict=True)
        snapshot["row_count"] = _count_csv_rows(text, header)
        snapshot["readable"] = True
    except Exception as exc:
        snapshot["error"] = type(exc).__name__
    return snapshot


def _read_counter(chunk_dir: Path) -> int:
    try:
        raw = (chunk_dir / "counter").read_text(encoding="utf-8").strip()
        return int(raw) if raw.isdigit() else 0
    except Exception:
        return 0


def _chunk_file_count(chunk_dir: Path) -> int:
    try:
        return sum(1 for child in chunk_dir.iterdir() if child.is_file() and child.suffix == ".enc")
    except Exception:
        return 0


def _count_csv_rows(text: str, header: str) -> int:
    stripped = str(text or "").strip()
    if not stripped or stripped == header:
        return 0
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return 0
    expected = header.split(",")
    if rows[0] != expected:
        return 0
    return sum(1 for row in rows[1:] if any(str(cell or "").strip() for cell in row))
