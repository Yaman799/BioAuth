from __future__ import annotations
from typing import Any, Dict
from artifact_integrity import load_sequence_model_artifact as _load_sequence_model_artifact
from artifact_integrity import save_sequence_model_artifact as _save_sequence_model_artifact
def save_sequence_model_artifact(path: str, payload: Dict[str, Any]) -> None:
    _save_sequence_model_artifact(path, payload)
def load_sequence_model_artifact(path: str) -> Dict[str, Any]:
    return _load_sequence_model_artifact(path)
