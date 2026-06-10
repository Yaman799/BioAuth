"""Production runtime profile loading boundary."""
from __future__ import annotations

from typing import Any


def load_production_runtime_bundle(user_id: str) -> Any:
    """Load the active production runtime bundle through the existing loader."""
    from model_inference import _load_user_runtime_bundle

    return _load_user_runtime_bundle(user_id)
