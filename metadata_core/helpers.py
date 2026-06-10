"""Shared metadata utility helpers."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional



def _format_timestamp(ts: Optional[float]) -> Optional[str]:
    if ts in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _now_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _parse_timestamp_value(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        pass
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except Exception:
            continue
    return None


def _read_text_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _append_jsonl(path: str, entry: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass


def _unique_existing_paths(paths: List[str], limit: Optional[int] = None) -> List[str]:
    seen = set()
    cleaned: List[str] = []
    for raw in paths:
        resolved = os.path.abspath(str(raw or "").strip())
        if not resolved or resolved in seen or not os.path.isdir(resolved):
            continue
        seen.add(resolved)
        cleaned.append(resolved)
    if limit is not None and limit > 0:
        cleaned = cleaned[-int(limit) :]
    return cleaned
