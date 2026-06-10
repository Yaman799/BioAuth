"""Feature window boundary for the monitor runtime."""
from __future__ import annotations

KEYBOARD_FEATURE_COUNT = 177
MOUSE_FEATURE_COUNT = 175


def expected_feature_counts() -> dict[str, int]:
    """Return the commercial runtime feature counts."""
    return {"keyboard": KEYBOARD_FEATURE_COUNT, "mouse": MOUSE_FEATURE_COUNT}
