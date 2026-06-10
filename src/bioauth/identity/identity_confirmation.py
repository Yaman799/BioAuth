from __future__ import annotations

"""Opt-in local identity confirmation service.

Phase 13 exposes a fail-closed pre-lock helper for monitor integration.
It never stores raw face frames and never writes production training data.
"""

import queue
import threading
import time
from typing import Any, Callable, Iterable, Mapping

from face_biometrics import (
    DEFAULT_VERIFY_THRESHOLD,
    DEFAULT_MIN_SAMPLE_COUNT,
    FACE_MODELS_INVALID,
    FACE_MODELS_MISSING,
    FaceBackendUnavailable,
    FaceBiometricsError,
    FaceEmbeddingEngine,
    FaceQualityError,
    build_enrollment_template,
    verify_frame_against_template,
)
from face_template_store import FaceTemplateStore


PRE_LOCK_FACE_CONFIRMATION_METHOD = "local_face_confirmation"


def _pre_lock_result(
    *,
    attempted: bool,
    status: str,
    lock_suppressed: bool = False,
    fallback_reason: str = "",
    elapsed_ms: float = 0.0,
    verified_owner_after_anomaly: bool = False,
) -> dict[str, Any]:
    """Build privacy-safe pre-lock confirmation metadata.

    The object intentionally contains only policy/result metadata.  It must not
    include raw frames, template payloads, embeddings, image paths, or template
    digests because it can be copied into monitor state and logs.
    """

    safe_status = str(status or "failed").strip().lower() or "failed"
    safe_fallback = str(fallback_reason or "").strip().lower()
    return {
        "attempted": bool(attempted),
        "method": PRE_LOCK_FACE_CONFIRMATION_METHOD,
        "status": safe_status,
        "lock_suppressed": bool(lock_suppressed),
        "fallback_reason": safe_fallback,
        "elapsed_ms": round(max(0.0, float(elapsed_ms)), 3),
        "verified_owner_after_anomaly": bool(verified_owner_after_anomaly),
        "eligible_for_shadow_evidence": bool(verified_owner_after_anomaly),
        "eligible_for_direct_production_training": False,
        "raw_images_stored": False,
        "lock_integration_enabled": True,
    }


def _call_with_timeout(callback: Callable[[], Mapping[str, Any]], timeout_sec: float) -> tuple[dict[str, Any] | None, bool, float]:
    """Run a confirmation callback with a daemon-thread timeout.

    The monitor must never hang while trying optional face confirmation.  If the
    callback is slow or blocks on camera/backend state, the existing protected
    response continues.
    """

    started = time.monotonic()
    q: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def runner() -> None:
        try:
            q.put(("ok", dict(callback() or {})))
        except Exception as exc:  # pragma: no cover - surfaced by caller result
            q.put(("error", exc))

    thread = threading.Thread(target=runner, name="bioauth-face-pre-lock", daemon=True)
    thread.start()
    thread.join(max(0.05, float(timeout_sec)))
    elapsed = (time.monotonic() - started) * 1000.0
    if thread.is_alive():
        return None, True, elapsed
    try:
        kind, payload = q.get_nowait()
    except queue.Empty:
        return {}, False, elapsed
    if kind == "error":
        raise payload
    return dict(payload or {}), False, elapsed


def confirm_identity_before_lock(
    user_id: str,
    *,
    settings: Mapping[str, Any] | None,
    service: Any | None = None,
    service_factory: Callable[[], Any] | None = None,
    camera_provider: Any | None = None,
    camera_provider_factory: Callable[..., Any] | None = None,
    frame: Any | None = None,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    """Best-effort owner confirmation immediately before protected response.

    LOCK-FACE-01 hardens this path so the timeout covers the whole pre-lock
    operation: service construction, status lookup, camera provider creation,
    frame capture, and the final verification call.  Any timeout/unavailable/
    failed result is privacy-safe and fail-closed for the caller.
    """

    from app_settings import feature_flag_enabled, has_current_face_template_consent

    started = time.monotonic()
    payload = settings if isinstance(settings, Mapping) else {}
    try:
        timeout = max(0.1, float(timeout_sec if timeout_sec is not None else payload.get("face_confirmation_pre_lock_timeout_sec", 3.0) or 3.0))
    except Exception:
        timeout = 3.0

    if not user_id:
        return _pre_lock_result(attempted=False, status="signed_out", fallback_reason="signed_out")
    if not bool(feature_flag_enabled(payload, "enable_face_confirmation")) or not bool(payload.get("face_confirmation_enabled", False)):
        return _pre_lock_result(attempted=False, status="disabled", fallback_reason="feature_disabled")
    if not has_current_face_template_consent(dict(payload)):
        return _pre_lock_result(attempted=False, status="consent_required", fallback_reason="consent_required")

    def _elapsed_ms() -> float:
        return (time.monotonic() - started) * 1000.0

    def _operation() -> Mapping[str, Any]:
        try:
            svc = service or (service_factory() if callable(service_factory) else IdentityConfirmationService())
        except Exception as exc:
            status = _backend_error_status(exc)
            return _pre_lock_result(attempted=True, status=status, fallback_reason=status, elapsed_ms=_elapsed_ms())

        try:
            status_payload = dict(svc.status(user_id) or {}) if hasattr(svc, "status") else {}
        except Exception:
            return _pre_lock_result(attempted=True, status="status_unavailable", fallback_reason="status_exception", elapsed_ms=_elapsed_ms())
        if not bool(status_payload.get("enrolled", False)):
            return _pre_lock_result(attempted=True, status="not_enrolled", fallback_reason="not_enrolled", elapsed_ms=_elapsed_ms())

        verification_frame = frame
        if verification_frame is None and (camera_provider is not None or callable(camera_provider_factory)):
            capture_timeout = min(timeout, 3.0 if bool(payload.get("face_confirmation_demo_prelock_override", False)) else 1.5)
            verification_frame, capture_status = _capture_pre_lock_frame(
                camera_provider=camera_provider,
                camera_provider_factory=camera_provider_factory,
                timeout_sec=capture_timeout,
            )
            if verification_frame is None:
                elapsed = _elapsed_ms()
                capture_status_text = str(capture_status.get("status") or "camera_unavailable").strip().lower() or "camera_unavailable"
                reason = str(capture_status.get("reason") or capture_status.get("failure_reason") or capture_status_text).strip().lower() or "camera_unavailable"
                if capture_status_text in {"opencv_unavailable"} or reason in {"opencv_unavailable", "opencv_import_failed"}:
                    return _pre_lock_result(attempted=True, status="opencv_unavailable", fallback_reason="opencv_unavailable", elapsed_ms=elapsed)
                if capture_status_text in {"capture_timeout"} or reason in {"capture_timeout"}:
                    return _pre_lock_result(attempted=True, status="camera_unavailable", fallback_reason="capture_timeout", elapsed_ms=elapsed)
                if capture_status_text in {"no_frame_captured"} or reason in {"no_frame_captured", "first_frame_failed"}:
                    return _pre_lock_result(attempted=True, status="camera_unavailable", fallback_reason="first_frame_failed", elapsed_ms=elapsed)
                if capture_status_text in {"device_open_failed"} or reason in {"device_open_failed", "permission_or_device_open_failure"}:
                    return _pre_lock_result(attempted=True, status="camera_unavailable", fallback_reason="camera_permission_or_device_open_failure", elapsed_ms=elapsed)
                return _pre_lock_result(attempted=True, status="camera_unavailable", fallback_reason=reason, elapsed_ms=elapsed)

        try:
            if hasattr(svc, "confirm_before_lock"):
                result = dict(svc.confirm_before_lock(user_id, frame=verification_frame) or {})
            elif hasattr(svc, "verify"):
                result = dict(svc.verify(user_id, verification_frame) or {})
            else:
                raise FaceBackendUnavailable("face_confirmation_backend_unavailable")
        except FaceQualityError as exc:
            quality = _quality_error_result(exc)
            status = str(quality.get("status") or "quality_rejected")
            reason = str(quality.get("reason") or status)
            return _pre_lock_result(attempted=True, status=status, fallback_reason=reason, elapsed_ms=_elapsed_ms())
        except FaceBackendUnavailable as exc:
            status = _backend_error_status(exc)
            return _pre_lock_result(attempted=True, status=status, fallback_reason=status, elapsed_ms=_elapsed_ms())
        except Exception:
            return _pre_lock_result(attempted=True, status="exception", fallback_reason="backend_exception", elapsed_ms=_elapsed_ms())

        verified = bool(result.get("verified", False)) or str(result.get("status") or "").strip().lower() in {"verified", "verified_owner"}
        status = "verified_owner" if verified else str(result.get("status") or "not_verified").strip().lower() or "not_verified"
        reason = "" if verified else (str(result.get("fallback_reason") or result.get("reason") or status).strip().lower() or "not_verified")
        if status == "quality_rejected" and reason == "no_face":
            status = "no_face_detected"
        return _pre_lock_result(
            attempted=True,
            status=status,
            lock_suppressed=verified,
            fallback_reason=reason,
            elapsed_ms=_elapsed_ms(),
            verified_owner_after_anomaly=verified,
        )

    try:
        result, timed_out, elapsed = _call_with_timeout(_operation, timeout)
    except Exception:
        elapsed = (time.monotonic() - started) * 1000.0
        return _pre_lock_result(attempted=True, status="exception", fallback_reason="backend_exception", elapsed_ms=elapsed)
    if timed_out:
        return _pre_lock_result(
            attempted=True,
            status="timeout",
            fallback_reason="pre_lock_face_timeout",
            elapsed_ms=elapsed,
            lock_suppressed=False,
            verified_owner_after_anomaly=False,
        )
    return dict(result or _pre_lock_result(attempted=True, status="exception", fallback_reason="backend_empty_result", elapsed_ms=elapsed))

def _safe_error(status: str, exc: Exception) -> dict[str, Any]:
    # User-safe, non-sensitive error surface.  Do not include frame data or raw
    # biometric values in errors.
    return {"status": status, "ok": False, "reason": str(exc)}


def _backend_error_status(exc: Exception) -> str:
    reason = str(exc or "").strip().lower()
    if reason in {FACE_MODELS_MISSING, FACE_MODELS_INVALID}:
        return reason
    return "camera_unavailable"


def build_default_identity_confirmation_service() -> "IdentityConfirmationService":
    """Build the real local face service used by backend-owned confirmation flows."""

    from face_biometrics import OpenCVFaceEngine

    return IdentityConfirmationService(engine=OpenCVFaceEngine())


def _capture_pre_lock_frame(
    *,
    camera_provider: Any | None,
    camera_provider_factory: Callable[..., Any] | None,
    timeout_sec: float | None = None,
) -> tuple[Any | None, dict[str, Any]]:
    """Capture one in-memory frame for the intended pre-lock path only."""

    try:
        provider = camera_provider
        if provider is None and callable(camera_provider_factory):
            try:
                provider = camera_provider_factory(timeout_sec=timeout_sec, warmup_frames=2)
            except TypeError:
                try:
                    provider = camera_provider_factory(warmup_frames=2)
                except TypeError:
                    provider = camera_provider_factory()
        if provider is None or not hasattr(provider, "capture_verification_frame"):
            return None, {"ok": False, "status": "camera_unavailable", "reason": "camera_provider_unavailable", "frame_count": 0}
        capture = provider.capture_verification_frame()
    except Exception:
        return None, {"ok": False, "status": "camera_unavailable", "reason": "camera_capture_exception", "frame_count": 0}

    if hasattr(capture, "to_safe_dict"):
        safe = dict(capture.to_safe_dict() or {})
    else:
        safe = {
            "ok": bool(getattr(capture, "ok", False)),
            "status": str(getattr(capture, "status", "camera_unavailable") or "camera_unavailable"),
            "reason": str(getattr(capture, "reason", "camera_unavailable") or "camera_unavailable"),
            "frame_count": int(getattr(capture, "frame_count", 0) or 0),
        }
    frame = getattr(capture, "frame", None)
    if bool(safe.get("ok", False)) and frame is not None:
        safe["ok"] = True
        safe["status"] = str(safe.get("status") or "captured")
        safe["reason"] = str(safe.get("reason") or safe.get("status") or "captured")
        return frame, safe
    safe["ok"] = False
    safe.setdefault("status", "camera_unavailable")
    safe.setdefault("reason", str(safe.get("status") or "camera_unavailable"))
    safe.setdefault("frame_count", 0)
    return None, safe


def _quality_error_result(exc: FaceQualityError) -> dict[str, Any]:
    reason = str(exc or "quality_rejected").strip().lower() or "quality_rejected"
    rejection_reasons = tuple(str(item or "").strip().lower() for item in getattr(exc, "rejection_reasons", ()) if str(item or "").strip())
    reason_set = set(rejection_reasons)
    status = "quality_rejected"
    safe_reason = reason
    if rejection_reasons:
        if reason_set <= {"no_face"}:
            status = "no_face_detected"
            safe_reason = "no_face"
        elif reason_set <= {"multiple_faces"}:
            status = "multiple_faces_detected"
            safe_reason = "multiple_faces"
        elif reason_set <= {"low_quality_face", "low_quality_face_too_small", "invalid_frame", "invalid_frame_values", "invalid_face_detection", "invalid_face_geometry", "empty_embedding", "zero_embedding", "non_finite_embedding"}:
            status = "poor_quality"
            safe_reason = "poor_quality"
    return {"status": status, "ok": False, "reason": safe_reason}


class IdentityConfirmationService:
    def __init__(self, *, store: FaceTemplateStore | None = None, engine: FaceEmbeddingEngine | None = None) -> None:
        self.store = store or FaceTemplateStore()
        self.engine = engine

    def _engine_or_unavailable(self) -> FaceEmbeddingEngine:
        if self.engine is None:
            raise FaceBackendUnavailable("face_engine_unavailable")
        return self.engine

    def enroll(self, user_id: str, frames: Iterable[Any], *, consent_granted: bool, min_samples: int = 3) -> dict[str, Any]:
        try:
            engine = self._engine_or_unavailable()
            template = build_enrollment_template(frames, engine, min_samples=min_samples)
            stored = self.store.save_template(user_id, template, consent_granted=consent_granted)
            return {
                "status": "enrolled",
                "ok": True,
                "template_digest": stored.get("template_digest"),
                "sample_count": stored.get("sample_count"),
                "quality_score": stored.get("quality_score"),
                "raw_images_stored": False,
            }
        except PermissionError as exc:
            return _safe_error("consent_required", exc)
        except FaceBackendUnavailable as exc:
            return _safe_error(_backend_error_status(exc), exc)
        except FaceQualityError as exc:
            return _quality_error_result(exc)
        except FaceBiometricsError as exc:
            return _safe_error("failed", exc)

    def verify(self, user_id: str, frame: Any, *, threshold: float = DEFAULT_VERIFY_THRESHOLD) -> dict[str, Any]:
        try:
            engine = self._engine_or_unavailable()
            template = self.store.load_template(user_id)
            if not template:
                return {"status": "not_enrolled", "ok": False, "verified": False}
            result = verify_frame_against_template(frame, template, engine, threshold=threshold)
            return {"ok": bool(result.get("verified")), "verified": bool(result.get("verified")), **result}
        except FaceBackendUnavailable as exc:
            return _safe_error(_backend_error_status(exc), exc)
        except FaceQualityError as exc:
            return _safe_error("quality_rejected", exc)
        except FaceBiometricsError as exc:
            return _safe_error("failed", exc)

    def test_verification(self, user_id: str, frame: Any, *, threshold: float = DEFAULT_VERIFY_THRESHOLD) -> dict[str, Any]:
        # Same verification primitive, intentionally not connected to lock state.
        result = self.verify(user_id, frame, threshold=threshold)
        result["lock_integration_enabled"] = False
        return result

    def test_verification_frames(self, user_id: str, frames: Iterable[Any], *, threshold: float = DEFAULT_VERIFY_THRESHOLD) -> dict[str, Any]:
        """Verify against several full camera frames without storing raw images.

        This UI test path improves capture stability by trying multiple
        backend-owned full-frame samples.  It does not lower the matching
        threshold and it is intentionally not connected to lock/unlock state.
        Multiple faces fail closed immediately.  Quality-only failures are
        skipped so a later clear full-frame sample can be used.
        """

        safe_frames = tuple(frames or ())
        if not safe_frames:
            return {
                "status": "camera_unavailable",
                "ok": False,
                "verified": False,
                "reason": "no_verification_frames",
                "verification_frame_count": 0,
                "usable_frame_count": 0,
                "lock_integration_enabled": False,
            }
        try:
            engine = self._engine_or_unavailable()
            template = self.store.load_template(user_id)
            if not template:
                return {"status": "not_enrolled", "ok": False, "verified": False, "lock_integration_enabled": False}
            first_not_verified: dict[str, Any] | None = None
            quality_reasons: list[str] = []
            usable_frame_count = 0
            for frame in safe_frames:
                try:
                    result = verify_frame_against_template(frame, template, engine, threshold=threshold)
                except FaceQualityError as exc:
                    reason = str(exc or "quality_rejected").strip().lower() or "quality_rejected"
                    if reason == "multiple_faces":
                        return {
                            "status": "multiple_faces_detected",
                            "ok": False,
                            "verified": False,
                            "reason": "multiple_faces",
                            "verification_frame_count": len(safe_frames),
                            "usable_frame_count": usable_frame_count,
                            "lock_integration_enabled": False,
                        }
                    quality_reasons.append(reason)
                    continue
                usable_frame_count += 1
                result = {"ok": bool(result.get("verified")), "verified": bool(result.get("verified")), **result}
                result["verification_frame_count"] = len(safe_frames)
                result["usable_frame_count"] = usable_frame_count
                result["lock_integration_enabled"] = False
                if bool(result.get("verified", False)) or str(result.get("status") or "").strip().lower() in {"verified", "verified_owner"}:
                    return result
                if first_not_verified is None:
                    first_not_verified = dict(result)
            if first_not_verified is not None:
                first_not_verified.setdefault("verification_frame_count", len(safe_frames))
                first_not_verified.setdefault("usable_frame_count", usable_frame_count)
                first_not_verified.setdefault("lock_integration_enabled", False)
                return first_not_verified
            reason_set = {str(reason or "").strip().lower() for reason in quality_reasons if str(reason or "").strip()}
            if reason_set and reason_set <= {"no_face"}:
                status, reason = "no_face_detected", "no_face"
            elif "multiple_faces" in reason_set:
                status, reason = "multiple_faces_detected", "multiple_faces"
            elif reason_set:
                status, reason = "poor_quality", "poor_quality"
            else:
                status, reason = "quality_rejected", "quality_rejected"
            return {
                "status": status,
                "ok": False,
                "verified": False,
                "reason": reason,
                "verification_frame_count": len(safe_frames),
                "usable_frame_count": usable_frame_count,
                "lock_integration_enabled": False,
            }
        except FaceBackendUnavailable as exc:
            result = _safe_error(_backend_error_status(exc), exc)
        except FaceBiometricsError as exc:
            result = _safe_error("failed", exc)
        result["verified"] = False
        result["lock_integration_enabled"] = False
        result.setdefault("verification_frame_count", len(safe_frames))
        result.setdefault("usable_frame_count", 0)
        return result

    def confirm_before_lock(self, user_id: str, frame: Any = None, *, threshold: float = DEFAULT_VERIFY_THRESHOLD) -> dict[str, Any]:
        # Pre-lock confirmation uses the same privacy-safe verifier.  Without a
        # camera frame provider it fails safely as camera_unavailable/not_verified.
        if frame is None:
            return {"status": "camera_unavailable", "ok": False, "verified": False}
        result = self.verify(user_id, frame, threshold=threshold)
        result["lock_integration_enabled"] = True
        return result

    def delete_template(self, user_id: str) -> dict[str, Any]:
        deleted = self.store.delete_template(user_id)
        return {"status": "deleted" if deleted else "not_enrolled", "ok": True, "deleted": bool(deleted)}

    def status(self, user_id: str) -> dict[str, Any]:
        payload = self.store.status(user_id)
        payload["lock_integration_enabled"] = False
        return payload
