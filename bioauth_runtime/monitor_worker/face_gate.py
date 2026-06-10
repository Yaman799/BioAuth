"""Pre-lock face gate for qualified high-risk runtime decisions."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Mapping

LOGGER = logging.getLogger(__name__)

_LOCK_REASONS = {
    "camera_unavailable": "camera_unavailable",
    "camera_failure": "camera_failure",
    "no_face": "no_face",
    "other_face": "other_face",
    "refused": "face_confirmation_refused",
    "timeout": "face_confirmation_timeout",
    "error": "face_confirmation_error",
}

_RAW_FORBIDDEN_KEYS = {
    "frame",
    "frames",
    "image",
    "images",
    "embedding",
    "template",
    "template_digest",
    "source_frame_paths",
}


def confirm_before_lock(
    *,
    user_id: str,
    settings: Mapping[str, Any] | None,
    service_factory: Callable[[], Any] | None = None,
    camera_provider_factory: Callable[..., Any] | None = None,
    timeout_sec: float = 3.0,
    confirmation_func: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run local identity confirmation and return a structured gate result."""
    started = time.monotonic()
    func = confirmation_func or _default_confirmation_func()
    try:
        raw = func(
            str(user_id or ""),
            settings=dict(settings or {}),
            service_factory=service_factory,
            camera_provider_factory=camera_provider_factory,
            timeout_sec=timeout_sec,
        )
    except Exception as exc:
        LOGGER.warning("face_gate_confirmation_error: %s", exc, exc_info=True)
        raw = {"attempted": True, "status": "exception", "fallback_reason": "backend_exception"}
    safe = sanitize_face_result(raw)
    result = map_face_result(safe)
    result["raw_result"] = safe
    result.setdefault("duration_ms", int((time.monotonic() - started) * 1000))
    return result


def map_face_result(face_result: Mapping[str, Any] | None) -> dict[str, Any]:
    """Map legacy face metadata into the Phase 5 gate contract."""
    safe = sanitize_face_result(face_result)
    status = _structured_status(safe)
    should_lock = status != "owner_verified"
    lock_reason = _LOCK_REASONS.get(status, "") if should_lock else ""
    return {
        "status": status,
        "should_lock": should_lock,
        "reason": _reason_for(status, safe),
        "lock_reason": lock_reason,
        "final_action": "continue_after_owner_face_verified" if not should_lock else "windows_lock_requested",
        "confidence": _safe_number(safe.get("confidence", safe.get("score"))),
        "score": _safe_number(safe.get("score", safe.get("confidence"))),
        "duration_ms": _duration_ms(safe),
        "error_message": _safe_error_message(safe),
    }


def sanitize_face_result(face_result: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return privacy-safe face metadata without image/template material."""
    safe = dict(face_result or {})
    for key in _RAW_FORBIDDEN_KEYS:
        safe.pop(key, None)
    safe.setdefault("raw_images_stored", False)
    return safe


def owner_verified(face_result: Mapping[str, Any] | None) -> bool:
    """Return True when the face gate should suppress Windows lock."""
    return map_face_result(face_result)["status"] == "owner_verified"


def _default_confirmation_func() -> Callable[..., Mapping[str, Any]]:
    from identity_confirmation import confirm_identity_before_lock

    return confirm_identity_before_lock


def _structured_status(face_result: Mapping[str, Any]) -> str:
    raw_status = str(face_result.get("status") or "").strip().lower()
    fallback = str(face_result.get("fallback_reason") or face_result.get("reason") or "").strip().lower()
    verified = bool(face_result.get("verified")) or bool(face_result.get("lock_suppressed"))
    verified = verified and bool(face_result.get("verified_owner_after_anomaly", verified))
    if verified or raw_status in {"verified", "verified_owner", "owner_verified"}:
        return "owner_verified"
    if raw_status in {"timeout"} or fallback in {"pre_lock_face_timeout", "timeout"}:
        return "timeout"
    if raw_status in {"refused", "user_refused", "cancelled", "canceled"} or fallback in {"refused", "user_refused"}:
        return "refused"
    if raw_status in {"no_face", "no_face_detected"} or fallback in {"no_face", "no_face_detected"}:
        return "no_face"
    if raw_status in {"not_verified", "different_face", "other_face"} or fallback in {"different_face", "other_face", "not_verified"}:
        return "other_face"
    if raw_status in {"camera_unavailable", "opencv_unavailable", "device_open_failed"}:
        return "camera_unavailable"
    if fallback in {"camera_unavailable", "capture_timeout", "camera_permission_or_device_open_failure"}:
        return "camera_unavailable"
    if raw_status in {"exception", "error", "backend_exception"} or fallback in {"backend_exception", "error"}:
        return "error"
    return "camera_failure"


def _reason_for(status: str, face_result: Mapping[str, Any]) -> str:
    reason = str(face_result.get("fallback_reason") or face_result.get("reason") or "").strip().lower()
    return reason or status


def _duration_ms(face_result: Mapping[str, Any]) -> int:
    value = face_result.get("duration_ms", face_result.get("elapsed_ms", 0))
    try:
        return int(max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0


def _safe_number(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _safe_error_message(face_result: Mapping[str, Any]) -> str:
    if _structured_status(face_result) != "error":
        return ""
    return str(face_result.get("error_message") or face_result.get("fallback_reason") or "face_confirmation_error")[:160]
