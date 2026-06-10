"""Training data/session helpers extracted in Phase 2.

This module owns encrypted session log reading, session-level feature extraction,
window sampling, and small numeric normalization helpers. Legacy callers keep
using ``model_training`` and ``training_core`` through re-export aliases.
"""

from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from features import (
    extract_combined_features,
    extract_multi_scale_window_feature_samples,
    extract_window_feature_samples,
)
from model_metadata import (
    ACTIVE_WINDOW_SCALES,
    KB_HEADER,
    MAX_TRAIN_WINDOWS_PER_SESSION,
    MIN_WINDOW_EVENTS,
    MS_HEADER,
    WINDOW_SECONDS,
    WINDOW_STEP_SECONDS,
)

LOGGER = logging.getLogger(__name__)


def _read_decrypted_current(filepath: str, header: str, *, strict: bool = False) -> str:
    """Resolve security.read_decrypted at call time after test/runtime reloads."""
    from security import read_decrypted as active_read_decrypted

    return active_read_decrypted(filepath, header, strict=strict)


class EncryptedSessionReadError(RuntimeError):
    """Raised when a training session log exists but cannot be read safely."""


def read_csv_encrypted(filepath: str, header: str, *, strict: bool = False) -> pd.DataFrame:
    expected_columns = header.split(',')
    chunk_dir = f"{filepath}.d"
    if not os.path.exists(filepath) and not os.path.isdir(chunk_dir):
        return pd.DataFrame(columns=expected_columns)
    try:
        text = _read_decrypted_current(filepath, header, strict=strict)
        stripped = text.strip()
        if not stripped or stripped == header:
            return pd.DataFrame(columns=expected_columns)
        rows = pd.read_csv(io.StringIO(text), header=0)
        if list(rows.columns) != expected_columns:
            raise EncryptedSessionReadError(
                f"Unexpected columns in encrypted log {filepath}: "
                f"got {list(rows.columns)} expected {expected_columns}"
            )
        return rows
    except EncryptedSessionReadError:
        raise
    except (OSError, ValueError, TypeError, pd.errors.ParserError) as exc:
        if strict:
            raise EncryptedSessionReadError(f"Failed to read encrypted session log {filepath}") from exc
        LOGGER.warning("Failed to read encrypted session log %s: %s", filepath, exc)
        return pd.DataFrame(columns=expected_columns)


def extract_from_session(session_path: str, *, strict: bool = False) -> Dict[str, float]:
    kb = read_csv_encrypted(os.path.join(session_path, 'keyboard_log.csv'), KB_HEADER, strict=strict)
    ms = read_csv_encrypted(os.path.join(session_path, 'mouse_log.csv'), MS_HEADER, strict=strict)
    if kb.empty and ms.empty:
        return {}
    return extract_combined_features(kb, ms)


def _normalize_window_scales(window_scales: Optional[List[float]] = None) -> List[float]:
    raw_scales = list(ACTIVE_WINDOW_SCALES if window_scales is None else window_scales)
    resolved: List[float] = []
    seen = set()
    for value in raw_scales:
        try:
            scale = float(value)
        except Exception:
            continue
        if not np.isfinite(scale) or scale <= 0.0:
            continue
        rounded = round(scale, 6)
        if rounded in seen:
            continue
        seen.add(rounded)
        resolved.append(float(scale))
    resolved.sort()
    return resolved


def _scale_metadata_label(scale_seconds: float) -> str:
    value = float(scale_seconds)
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value))}s"
    return f"{str(value).replace('.', '_')}s"


def _per_scale_sample_counts(samples: List[Dict[str, float]], window_scales: List[float]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for scale in window_scales:
        label = _scale_metadata_label(scale)
        active_key = f"scale_{label}_active"
        counts[label] = int(sum(1 for sample in samples if float(sample.get(active_key, 0.0) or 0.0) >= 0.5))
    return counts


def extract_window_samples_from_session(
    session_path: str,
    window_seconds: float = WINDOW_SECONDS,
    step_seconds: float = WINDOW_STEP_SECONDS,
    min_total_events: int = MIN_WINDOW_EVENTS,
    max_windows: int = MAX_TRAIN_WINDOWS_PER_SESSION,
    window_scales: Optional[List[float]] = None,
    *,
    strict: bool = False,
) -> List[Dict[str, float]]:
    kb = read_csv_encrypted(os.path.join(session_path, 'keyboard_log.csv'), KB_HEADER, strict=strict)
    ms = read_csv_encrypted(os.path.join(session_path, 'mouse_log.csv'), MS_HEADER, strict=strict)
    if kb.empty and ms.empty:
        return []
    resolved_scales = _normalize_window_scales(window_scales)
    if len(resolved_scales) > 1:
        return extract_multi_scale_window_feature_samples(
            kb,
            ms,
            window_scales=resolved_scales,
            step_seconds=step_seconds,
            min_total_events=min_total_events,
            max_windows=max_windows,
        )
    return extract_window_feature_samples(
        kb,
        ms,
        window_seconds=float(resolved_scales[0]) if resolved_scales else window_seconds,
        step_seconds=step_seconds,
        min_total_events=min_total_events,
        max_windows=max_windows,
    )


def build_matrix(samples: List[Dict[str, float]], feature_names: List[str]) -> np.ndarray:
    return np.asarray([[float(sample.get(name, 0.0) or 0.0) for name in feature_names] for sample in samples], dtype=float)


def get_anomaly_scores(model: Any, X: np.ndarray) -> np.ndarray:
    return -model.decision_function(X)


def normalize_feature_dict(sample: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for key, value in sample.items():
        try:
            number = float(value)
        except Exception:
            number = 0.0
        if not np.isfinite(number):
            number = 0.0
        out[key] = number
    return out


__all__ = [
    'EncryptedSessionReadError',
    'read_csv_encrypted',
    'extract_from_session',
    '_normalize_window_scales',
    '_scale_metadata_label',
    '_per_scale_sample_counts',
    'extract_window_samples_from_session',
    'build_matrix',
    'get_anomaly_scores',
    'normalize_feature_dict',
]
