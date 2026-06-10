from __future__ import annotations

import copy
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple
from pathlib import Path

CONFIG_RELATIVE_PATH = os.path.join("config", "onboarding_slides.json")

DEFAULT_ONBOARDING_SPEC: List[Dict[str, Any]] = [
    {
        "id": "welcome",
        "order": 10,
        "enabled": True,
        "tone": "info",
        "badge": "01",
        "eyebrow_key": "onboarding_welcome_eyebrow",
        "title_key": "onboarding_slide_1_title",
        "description_key": "onboarding_slide_1_body",
        "points_keys": ["onboarding_slide_1_point_1", "onboarding_slide_1_point_2"],
    },
    {
        "id": "start",
        "order": 20,
        "enabled": True,
        "tone": "details",
        "badge": "02",
        "eyebrow_key": "onboarding_start_eyebrow",
        "title_key": "onboarding_slide_2_title",
        "description_key": "onboarding_slide_2_body",
        "points_keys": ["onboarding_slide_2_point_1", "onboarding_slide_2_point_2"],
    },
    {
        "id": "training",
        "order": 30,
        "enabled": True,
        "tone": "success",
        "badge": "03",
        "eyebrow_key": "onboarding_features_eyebrow",
        "title_key": "onboarding_slide_3_title",
        "description_key": "onboarding_slide_3_body",
        "points_keys": ["onboarding_slide_3_point_1", "onboarding_slide_3_point_2"],
    },
    {
        "id": "risk",
        "order": 40,
        "enabled": True,
        "tone": "warn",
        "badge": "04",
        "eyebrow_key": "onboarding_notes_eyebrow",
        "title_key": "onboarding_slide_4_title",
        "description_key": "onboarding_slide_4_body",
        "points_keys": ["onboarding_slide_4_point_1", "onboarding_slide_4_point_2"],
    },
    {
        "id": "ready",
        "order": 50,
        "enabled": True,
        "tone": "primary",
        "badge": "05",
        "eyebrow_key": "onboarding_ready_eyebrow",
        "title_key": "onboarding_slide_5_title",
        "description_key": "onboarding_slide_5_body",
        "points_keys": ["onboarding_slide_5_point_1", "onboarding_slide_5_point_2"],
    },
]


def _config_path(base_dir: str) -> str:
    return os.path.join(str(base_dir or ""), CONFIG_RELATIVE_PATH)


def _resolve_media_path(base_dir: str, raw_value: Any) -> str:
    if raw_value is None:
        return ""
    value = str(raw_value or "").strip()
    if not value:
        return ""
    if value.startswith(("file://", "qrc:/", ":/", "http://", "https://")):
        return value
    candidate = Path(base_dir or "") / value
    if candidate.exists():
        return candidate.resolve().as_uri()
    return ""


def _normalize_points(raw_spec: Dict[str, Any]) -> List[Any]:
    if isinstance(raw_spec.get("points"), list):
        return list(raw_spec.get("points") or [])
    if isinstance(raw_spec.get("points_keys"), list):
        return [{"key": item} if isinstance(item, str) else item for item in list(raw_spec.get("points_keys") or [])]
    fallback: List[Any] = []
    for key_name, text_name in (("point1_key", "point1"), ("point2_key", "point2")):
        if isinstance(raw_spec.get(key_name), str) and raw_spec.get(key_name):
            fallback.append({"key": str(raw_spec.get(key_name))})
        elif raw_spec.get(text_name) is not None:
            fallback.append(raw_spec.get(text_name))
    return fallback


def _normalize_slide_spec(raw_slide: Any, index: int) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_slide, dict):
        return None
    enabled = raw_slide.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in {"0", "false", "no", "off"}
    if not bool(enabled):
        return None
    order_value = raw_slide.get("order", index + 1)
    try:
        order_value = int(order_value)
    except Exception:
        order_value = index + 1
    tone = str(raw_slide.get("tone") or "info").strip() or "info"
    badge = str(raw_slide.get("badge") or f"{index + 1:02d}").strip() or f"{index + 1:02d}"
    icon = raw_slide.get("icon")
    if icon is None:
        icon = raw_slide.get("visual")
    icon_text = str(icon).strip() if icon is not None else ""

    spec = {
        "id": str(raw_slide.get("id") or f"slide_{index + 1}").strip() or f"slide_{index + 1}",
        "order": order_value,
        "tone": tone,
        "badge": badge,
        "icon": icon_text,
        "image": raw_slide.get("image"),
        "image_alt": raw_slide.get("image_alt"),
        "image_only": bool(raw_slide.get("image_only", False)),
        "image_max_width": raw_slide.get("image_max_width"),
        "image_max_height": raw_slide.get("image_max_height"),
        "eyebrow": raw_slide.get("eyebrow"),
        "eyebrow_key": raw_slide.get("eyebrow_key"),
        "title": raw_slide.get("title"),
        "title_key": raw_slide.get("title_key"),
        "description": raw_slide.get("description"),
        "description_key": raw_slide.get("description_key"),
        "points": _normalize_points(raw_slide),
    }
    return spec


def _normalize_manifest(raw_manifest: Any) -> List[Dict[str, Any]]:
    if isinstance(raw_manifest, dict):
        raw_slides = raw_manifest.get("slides")
    elif isinstance(raw_manifest, list):
        raw_slides = raw_manifest
    else:
        raw_slides = None
    if not isinstance(raw_slides, list):
        return []
    slides: List[Dict[str, Any]] = []
    for index, raw_slide in enumerate(raw_slides):
        normalized = _normalize_slide_spec(raw_slide, index)
        if normalized is not None:
            slides.append(normalized)
    slides.sort(key=lambda item: (int(item.get("order", 0) or 0), str(item.get("id") or "")))
    return slides


def load_onboarding_slide_specs(base_dir: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    default_specs = _normalize_manifest(copy.deepcopy(DEFAULT_ONBOARDING_SPEC))
    path = _config_path(base_dir)
    if not os.path.exists(path):
        return default_specs, {"source": "default", "reason": "missing_file", "path": path}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw_manifest = json.load(handle)
    except Exception as exc:
        return default_specs, {"source": "default", "reason": f"invalid_file:{exc.__class__.__name__}", "path": path}
    normalized = _normalize_manifest(raw_manifest)
    if not normalized:
        return default_specs, {"source": "default", "reason": "empty_or_invalid_manifest", "path": path}
    return normalized, {"source": "file", "reason": "ok", "path": path}


def _resolve_text(value: Any, *, translate: Callable[[str], str], language: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        key = value.get("key")
        if isinstance(key, str) and key.strip():
            return translate(key.strip())
        lang_value = value.get(language)
        if isinstance(lang_value, str) and lang_value.strip():
            return lang_value
        fallback_value = value.get("en")
        if isinstance(fallback_value, str) and fallback_value.strip():
            return fallback_value
        fallback_value = value.get("ar")
        if isinstance(fallback_value, str) and fallback_value.strip():
            return fallback_value
        fallback_value = value.get("default")
        if isinstance(fallback_value, str) and fallback_value.strip():
            return fallback_value
    return str(value or "")


def build_onboarding_slides(
    base_dir: str,
    *,
    translate: Callable[[str], str],
    language: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    specs, status = load_onboarding_slide_specs(base_dir)
    language_name = str(language or "en").strip().lower() or "en"
    slides: List[Dict[str, Any]] = []
    for index, spec in enumerate(specs):
        eyebrow_value = {"key": spec.get("eyebrow_key")} if spec.get("eyebrow_key") else spec.get("eyebrow")
        title_value = {"key": spec.get("title_key")} if spec.get("title_key") else spec.get("title")
        description_value = {"key": spec.get("description_key")} if spec.get("description_key") else spec.get("description")
        points = [
            _resolve_text(point_spec, translate=translate, language=language_name)
            for point_spec in list(spec.get("points") or [])
        ]
        points = [item for item in points if str(item or "").strip()]
        image_alt_value = spec.get("image_alt")
        slides.append(
            {
                "id": str(spec.get("id") or f"slide_{index + 1}"),
                "tone": str(spec.get("tone") or "info"),
                "badge": str(spec.get("badge") or f"{index + 1:02d}"),
                "icon": str(spec.get("icon") or ""),
                "visualText": str(spec.get("icon") or spec.get("badge") or f"{index + 1:02d}"),
                "eyebrow": _resolve_text(eyebrow_value, translate=translate, language=language_name),
                "title": _resolve_text(title_value, translate=translate, language=language_name),
                "description": _resolve_text(description_value, translate=translate, language=language_name),
                "points": points,
                "point1": points[0] if len(points) > 0 else "",
                "point2": points[1] if len(points) > 1 else "",
                "imageSource": _resolve_media_path(base_dir, spec.get("image")),
                "imageAlt": _resolve_text(image_alt_value, translate=translate, language=language_name) if image_alt_value else "",
                "imageOnly": bool(spec.get("image_only", False)),
                "imageMaxWidth": int(spec.get("image_max_width") or 0),
                "imageMaxHeight": int(spec.get("image_max_height") or 0),
            }
        )
    return slides, status
