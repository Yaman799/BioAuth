from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import app_settings

ROOT = Path(__file__).resolve().parent.parent


def test_feature_flag_defaults_are_single_source_for_default_settings() -> None:
    for key, value in app_settings.FEATURE_FLAG_DEFAULTS.items():
        assert app_settings.DEFAULT_SETTINGS[key] is value

    payload = app_settings._coerce_settings_payload({})
    assert app_settings.normalize_feature_flags(payload) == dict(app_settings.FEATURE_FLAG_DEFAULTS)


def test_production_approval_payload_has_no_duplicate_literal_keys() -> None:
    tree = ast.parse((ROOT / "metadata_core" / "production_approval.py").read_text(encoding="utf-8"))
    duplicates: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        literal_keys = [key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
        for key, count in Counter(literal_keys).items():
            if count > 1:
                duplicates.append((node.lineno, key))
    assert duplicates == []
