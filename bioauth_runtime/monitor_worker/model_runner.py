"""Model inference boundary for monitor runtime."""
from __future__ import annotations

from typing import Any


def predict_session_details(*args: Any, **kwargs: Any) -> Any:
    """Run the existing model inference call without UI or lifecycle logic."""
    from model_inference import predict_from_session_details

    return predict_from_session_details(*args, **kwargs)
