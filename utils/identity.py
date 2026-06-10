from __future__ import annotations

import re

_MAX_SLUG_LENGTH = 40
_INVALID_CHARS_RE = re.compile(r"[^a-zA-Z0-9_\-.]+")
_DUPLICATE_UNDERSCORES_RE = re.compile(r"_+")


def slugify_username(value: str) -> str:
    """Normalize usernames into a stable filesystem-safe slug.

    This keeps the legacy character policy used by the desktop app:
    - lowercase ASCII
    - keep letters, digits, underscore, dash and dot
    - collapse invalid runs to a single underscore
    - trim leading/trailing separators
    - cap the stored slug length to preserve existing file naming behavior
    """
    text = _INVALID_CHARS_RE.sub("_", str(value).strip().lower())
    text = _DUPLICATE_UNDERSCORES_RE.sub("_", text).strip("_.-")
    return text[:_MAX_SLUG_LENGTH]
