"""Frozen feature/window schema contract for BioAuth runtime and evaluation.

Commercial-Core-05 intentionally does not add new behavioral features.  It
freezes the *contract* around the existing conservative keyboard/mouse/window
features so promotion gates, runtime-fed shadow evidence, and external dataset
converters can compare apples to apples across builds.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from metadata_core.constants import (
    ACTIVE_WINDOW_SCALES,
    FEATURE_SCHEMA_VERSION,
    FEATURE_WINDOW_STRATEGY,
    MIN_WINDOW_EVENTS,
    PREDICT_WINDOW_STEP_SECONDS,
    WINDOW_SECONDS,
    WINDOW_STEP_SECONDS,
)
from feature_extractors.combined import extract_combined_features
from feature_extractors.conservative_v2 import CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION
from feature_extractors.windows import _scale_label

FEATURE_SCHEMA_CONTRACT_VERSION = "commercial-core-11-feature-schema-contract-v2"
WINDOW_SCHEMA_VERSION = "bioauth-runtime-window-schema-v2"
FEATURE_VALUE_POLICY_VERSION = "feature-values-non-finite-to-zero-v1"
FEATURE_NAME_ORDERING = "lexicographic-stable-v1"
FEATURE_SCHEMA_DIGEST_ALGORITHM = "sha256"

# These fields are produced by the current multi-scale window builder and must
# remain stable while FEATURE_SCHEMA_VERSION stays unchanged.
MULTISCALE_REQUIRED_FIELDS: tuple[str, ...] = (
    "multiscale_anchor_end",
    "multiscale_anchor_offset",
    "multiscale_active_scale_count",
    "multiscale_requested_scale_count",
    "multiscale_scale_coverage",
)

SEQUENCE_REQUIRED_FIELDS: tuple[str, ...] = (
    "sequence_window_index",
    "transition_window_index",
    "transition_flag",
    "transition_settled_flag",
)

RAW_PROHIBITED_FIELD_PATTERNS: tuple[str, ...] = (
    "raw_key",
    "raw_text",
    "typed_text",
    "plaintext",
    "password",
    "face_image",
    "face_frame",
    "face_embedding",
    "screenshot",
)

_ALLOWED_ROOT_PREFIXES: tuple[str, ...] = (
    "multiscale_",
    "scale_",
    "adjacent_",
    "trend_",
    "transition_",
    "sequence_",
    # Legacy single-scale names are kept compatible because older tests and
    # offline runners can still feed single-scale windows.
    "kb_",
    "ms_",
    "session_",
    "window_",
    "pre_window_",
)

_NUMERIC_PATTERN = re.compile(r"^-?\d+(?:\.\d+)?$")


def _stable_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest_payload(payload: Mapping[str, Any]) -> str:
    return f"sha256:{hashlib.sha256(_stable_json(payload).encode('utf-8')).hexdigest()}"


def _empty_base_feature_names() -> list[str]:
    base = extract_combined_features(pd.DataFrame(), pd.DataFrame())
    return sorted(str(name) for name in base.keys())


def _scale_control_fields(scale: float) -> list[str]:
    label = _scale_label(float(scale))
    prefix = f"scale_{label}"
    return [
        f"{prefix}_requested_seconds",
        f"{prefix}_window_total_events",
        f"{prefix}_window_seconds",
        f"{prefix}_start_offset",
        f"{prefix}_end_offset",
        f"{prefix}_pre_window_idle_gap_seconds",
        f"{prefix}_active",
    ]


def expected_scale_feature_names(scales: Iterable[float] | None = None) -> list[str]:
    """Return the deterministic base feature names expected per active scale.

    This is intentionally conservative: sequence/trend features are represented
    by namespace rules because their exact count depends on available history.
    """

    resolved_scales = sorted({float(scale) for scale in (scales or ACTIVE_WINDOW_SCALES) if float(scale) > 0.0})
    base_names = _empty_base_feature_names()
    out: list[str] = []
    for scale in resolved_scales:
        label = _scale_label(scale)
        prefix = f"scale_{label}"
        out.extend(_scale_control_fields(scale))
        out.extend(f"{prefix}_{name}" for name in base_names)
    return sorted(dict.fromkeys(out))


def feature_family_for_name(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return "invalid"
    if text.startswith("multiscale_"):
        return "window_multiscale_control"
    if text.startswith("adjacent_"):
        return "sequence_adjacent_window_delta"
    if text.startswith("trend_"):
        return "sequence_tempo_trend"
    if text.startswith("transition_"):
        return "transition_window_policy"
    if text.startswith("sequence_"):
        return "sequence_window_index"
    if text.startswith("scale_"):
        if "_session_" in text:
            return "session_modality_fusion"
        if "_kb_" in text:
            return "keyboard_behavior"
        if "_ms_" in text:
            return "mouse_behavior"
        return "scaled_window_control"
    if text.startswith("kb_v2_"):
        return "keyboard_conservative_v2"
    if text.startswith("ms_v2_"):
        return "mouse_conservative_v2"
    if text.startswith("session_v2_"):
        return "session_conservative_v2"
    if text.startswith("kb_"):
        return "legacy_keyboard_behavior"
    if text.startswith("ms_"):
        return "legacy_mouse_behavior"
    if text.startswith("session_"):
        return "legacy_session_modality_fusion"
    if text.startswith("window_") or text.startswith("pre_window_"):
        return "legacy_window_control"
    return "unknown"


def feature_name_allowed(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    if any(bad in text.lower() for bad in RAW_PROHIBITED_FIELD_PATTERNS):
        return False
    return text.startswith(_ALLOWED_ROOT_PREFIXES)


def summarize_feature_names(feature_names: Sequence[str] | None) -> dict[str, Any]:
    names = sorted(dict.fromkeys(str(name) for name in (feature_names or []) if str(name or "").strip()))
    families: dict[str, int] = {}
    for name in names:
        family = feature_family_for_name(name)
        families[family] = families.get(family, 0) + 1
    unknown_names = [name for name in names if not feature_name_allowed(name) or feature_family_for_name(name) == "unknown"]
    return {
        "feature_count": int(len(names)),
        "feature_name_ordering": FEATURE_NAME_ORDERING,
        "families": dict(sorted(families.items())),
        "unknown_feature_count": int(len(unknown_names)),
        "unknown_feature_name_samples": unknown_names[:10],
        "feature_name_samples": names[:12],
    }


def validate_feature_names(feature_names: Sequence[str] | None, *, require_multiscale: bool = True) -> dict[str, Any]:
    names = sorted(dict.fromkeys(str(name) for name in (feature_names or []) if str(name or "").strip()))
    errors: list[str] = []
    warnings: list[str] = []
    if not names:
        errors.append("feature_names_empty")
    prohibited = [name for name in names if any(bad in name.lower() for bad in RAW_PROHIBITED_FIELD_PATTERNS)]
    if prohibited:
        errors.append("prohibited_raw_field_names_present")
    unknown = [name for name in names if not feature_name_allowed(name) or feature_family_for_name(name) == "unknown"]
    if unknown:
        errors.append("unknown_feature_names_present")
    if require_multiscale:
        missing = [name for name in MULTISCALE_REQUIRED_FIELDS if name not in names]
        if missing:
            errors.append("missing_multiscale_required_fields")
            warnings.append("missing:" + ",".join(missing[:8]))
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "unknown_feature_name_samples": unknown[:10],
        "prohibited_feature_name_samples": prohibited[:10],
        **summarize_feature_names(names),
    }


def normalize_feature_sample(sample: Mapping[str, Any] | None) -> dict[str, float]:
    """Return numeric, finite feature values following the frozen value policy."""

    out: dict[str, float] = {}
    for key, value in dict(sample or {}).items():
        if not feature_name_allowed(str(key)):
            continue
        try:
            number = float(value)
        except Exception:
            number = 0.0
        if number != number or number in (float("inf"), float("-inf")):
            number = 0.0
        out[str(key)] = number
    return out


def validate_feature_sample(sample: Mapping[str, Any] | None, *, require_multiscale: bool = True) -> dict[str, Any]:
    payload = dict(sample or {})
    names_result = validate_feature_names(list(payload.keys()), require_multiscale=require_multiscale)
    non_numeric: list[str] = []
    non_finite: list[str] = []
    for key, value in payload.items():
        try:
            number = float(value)
        except Exception:
            non_numeric.append(str(key))
            continue
        if number != number or number in (float("inf"), float("-inf")):
            non_finite.append(str(key))
    errors = list(names_result.get("errors") or [])
    if non_numeric:
        errors.append("non_numeric_feature_values_present")
    if non_finite:
        errors.append("non_finite_feature_values_present")
    return {
        **names_result,
        "ok": not errors,
        "errors": errors,
        "non_numeric_feature_name_samples": non_numeric[:10],
        "non_finite_feature_name_samples": non_finite[:10],
        "value_policy_version": FEATURE_VALUE_POLICY_VERSION,
    }


def build_feature_schema_contract(feature_names: Sequence[str] | None = None) -> dict[str, Any]:
    expected_names = expected_scale_feature_names(ACTIVE_WINDOW_SCALES)
    observed_summary = summarize_feature_names(feature_names or [])
    validation = validate_feature_names(feature_names or [], require_multiscale=bool(feature_names)) if feature_names else {"ok": True, "errors": [], "warnings": []}
    contract: dict[str, Any] = {
        "contract_version": FEATURE_SCHEMA_CONTRACT_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "window_schema_version": WINDOW_SCHEMA_VERSION,
        "feature_window_strategy": FEATURE_WINDOW_STRATEGY,
        "feature_extension_profile": CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION,
        "feature_value_policy_version": FEATURE_VALUE_POLICY_VERSION,
        "feature_name_ordering": FEATURE_NAME_ORDERING,
        "digest_algorithm": FEATURE_SCHEMA_DIGEST_ALGORITHM,
        "active_window_scales": [float(scale) for scale in ACTIVE_WINDOW_SCALES],
        "window_seconds": float(WINDOW_SECONDS),
        "window_step_seconds": float(WINDOW_STEP_SECONDS),
        "predict_window_step_seconds": float(PREDICT_WINDOW_STEP_SECONDS),
        "min_window_events": int(MIN_WINDOW_EVENTS),
        "required_multiscale_fields": list(MULTISCALE_REQUIRED_FIELDS),
        "required_sequence_fields": list(SEQUENCE_REQUIRED_FIELDS),
        "allowed_root_prefixes": list(_ALLOWED_ROOT_PREFIXES),
        "raw_prohibited_field_patterns": list(RAW_PROHIBITED_FIELD_PATTERNS),
        "expected_scaled_base_feature_count": int(len(expected_names)),
        "expected_scaled_base_feature_samples": expected_names[:18],
        "observed": observed_summary,
        "validation": validation,
        "compatibility_notes": [
            "Commercial-Core-11 adds a conservative v2 feature extension while keeping the existing runtime feature_schema_version stable for old-model compatibility.",
            "New v2 features are aggregate timing/category/motion metrics only; no raw typed text, raw face frames, or raw mouse streams are persisted.",
            "Unknown or raw-like feature names are rejected for promotion/evaluation contracts.",
            "Single-scale legacy windows remain tolerated for offline/replay compatibility, but runtime promotion expects multiscale windows.",
        ],
    }
    digest_input = dict(contract)
    digest_input.pop("schema_digest", None)
    contract["schema_digest"] = _digest_payload(digest_input)
    return contract


__all__ = [
    "FEATURE_SCHEMA_CONTRACT_VERSION",
    "WINDOW_SCHEMA_VERSION",
    "FEATURE_VALUE_POLICY_VERSION",
    "FEATURE_NAME_ORDERING",
    "CONSERVATIVE_FEATURE_SCHEMA_V2_VERSION",
    "MULTISCALE_REQUIRED_FIELDS",
    "SEQUENCE_REQUIRED_FIELDS",
    "RAW_PROHIBITED_FIELD_PATTERNS",
    "build_feature_schema_contract",
    "expected_scale_feature_names",
    "feature_family_for_name",
    "feature_name_allowed",
    "normalize_feature_sample",
    "summarize_feature_names",
    "validate_feature_names",
    "validate_feature_sample",
]
