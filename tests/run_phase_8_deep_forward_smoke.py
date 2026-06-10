from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_PATH = REPO_ROOT / "deep_sequence" / "models.py"

import torch

spec = importlib.util.spec_from_file_location("phase8_models_smoke", MODELS_PATH)
models = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["phase8_models_smoke"] = models
spec.loader.exec_module(models)


def main() -> None:
    torch.manual_seed(8)
    sequence = models.SequenceCnnLstm(feature_dim=3)
    keyboard = models.KeyboardBiGruCnnAttention(feature_dim=8, cnn_channels=8, gru_hidden_size=8, attention_hidden_size=8)
    mouse = models.MouseResNetGruVerifier(feature_dim=9, channels=8, gru_hidden_size=8)
    sequence_logits = sequence(torch.zeros((2, 4, 3), dtype=torch.float32))
    keyboard_logits = keyboard(torch.zeros((2, 5, 8), dtype=torch.float32))
    mouse_logits = mouse(torch.zeros((2, 6, 9), dtype=torch.float32))
    result = {
        "sequence_cnn_lstm_shape": list(sequence_logits.shape),
        "keyboard_shape": list(keyboard_logits.shape),
        "mouse_shape": list(mouse_logits.shape),
        "keyboard_experimental": bool(keyboard.experimental),
        "mouse_experimental": bool(mouse.experimental),
        "keyboard_can_lock_alone": bool(keyboard.can_lock_alone),
        "mouse_can_lock_alone": bool(mouse.can_lock_alone),
        "keyboard_score_direction": keyboard.score_direction,
        "mouse_score_direction": mouse.score_direction,
    }
    print(json.dumps(result, sort_keys=True), flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
