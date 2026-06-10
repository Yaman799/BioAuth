"""Mouse event normalization for the logger worker."""
from __future__ import annotations

import math
import time
from typing import Any


def button_name(button: Any) -> str:
    name = getattr(button, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip().lower()
    return str(button).split(".")[-1].strip().lower() or "unknown"


def mouse_row(x: float, y: float, event: str, timestamp: float | None = None) -> list[object]:
    return [x, y, str(event), timestamp if timestamp is not None else time.time()]


def keep_motion(last: tuple[float, float, float] | None, x: float, y: float, ts: float, *, seconds: float, pixels: float) -> bool:
    if last is None:
        return True
    last_x, last_y, last_ts = last
    return ts - last_ts >= seconds or math.hypot(x - last_x, y - last_y) >= pixels
