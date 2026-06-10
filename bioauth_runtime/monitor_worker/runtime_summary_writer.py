"""Runtime summary publishing for monitor-owned decision payloads."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from control import CONTROL_DIR


def runtime_summary_path() -> Path:
    """Return the canonical runtime_summary.json path."""
    return Path(CONTROL_DIR) / "runtime_summary.json"


def write_runtime_summary_payload(payload: Mapping[str, object] | None) -> bool:
    """Publish the monitor decision payload without recomputing risk."""
    path = runtime_summary_path()
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(dict(payload or {}), handle, ensure_ascii=False, indent=2)
            handle.flush()
        tmp.replace(path)
        return True
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False
