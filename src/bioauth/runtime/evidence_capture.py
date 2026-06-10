from __future__ import annotations

import json
import logging
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from app_settings import PRIVACY_POLICY_VERSION, has_current_evidence_consent, load_settings
from paths import evidence_dir
from security import _calculate_file_sha256, atomic_write_text

LOGGER = logging.getLogger(__name__)
_EVIDENCE_LOCK = threading.RLock()

SUPPORTED_INCIDENTS = {"confirmed_intruder", "device_locked_by_intruder"}
DEFAULT_RETENTION_DAYS = 30
DEFAULT_SCREENSHOT_TIMEOUT_SEC = 1.5
DEFAULT_WEBCAM_TIMEOUT_SEC = 2.5
DEFAULT_WEBCAM_FRAMES = 2


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_component(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw).strip("_")
    return cleaned or fallback


def _incident_timestamp(now: Optional[datetime] = None) -> str:
    current = now if isinstance(now, datetime) else _utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _json_dumps(data: Mapping[str, Any]) -> str:
    return json.dumps(dict(data), ensure_ascii=False, indent=2, sort_keys=True)


def _restrict_directory_permissions(path: str) -> None:
    try:
        if os.name == "posix":
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    except OSError:
        LOGGER.debug("Failed restricting evidence directory permissions for %s", path, exc_info=True)
        return


def _write_json(path: str, data: Mapping[str, Any]) -> None:
    atomic_write_text(path, _json_dumps(data))


def _settings_value(settings: Optional[Mapping[str, Any]], key: str, default: Any) -> Any:
    if isinstance(settings, Mapping) and key in settings:
        return settings.get(key)
    runtime = load_settings()
    return runtime.get(key, default)


def evidence_enabled(settings: Optional[Mapping[str, Any]] = None) -> bool:
    return bool(_settings_value(settings, "incident_evidence_enabled", False))


def screenshot_enabled(settings: Optional[Mapping[str, Any]] = None) -> bool:
    return bool(_settings_value(settings, "incident_evidence_capture_screenshot", False))


def webcam_enabled(settings: Optional[Mapping[str, Any]] = None) -> bool:
    return bool(_settings_value(settings, "incident_evidence_capture_webcam", False))


def evidence_consent_valid(settings: Optional[Mapping[str, Any]] = None) -> bool:
    payload = dict(settings) if isinstance(settings, Mapping) else load_settings()
    return has_current_evidence_consent(payload)


def retention_days(settings: Optional[Mapping[str, Any]] = None) -> int:
    try:
        value = int(_settings_value(settings, "incident_evidence_retention_days", DEFAULT_RETENTION_DAYS) or DEFAULT_RETENTION_DAYS)
    except (TypeError, ValueError):
        value = DEFAULT_RETENTION_DAYS
    return max(1, min(365, value))


def webcam_frame_count(settings: Optional[Mapping[str, Any]] = None) -> int:
    try:
        value = int(_settings_value(settings, "incident_evidence_webcam_frames", DEFAULT_WEBCAM_FRAMES) or DEFAULT_WEBCAM_FRAMES)
    except (TypeError, ValueError):
        value = DEFAULT_WEBCAM_FRAMES
    return max(1, min(2, value))


def _build_incident_dir(session_id: str, ts_token: str) -> str:
    session_token = _safe_component(session_id, "unknown")
    root = os.path.join(evidence_dir(), f"session_{session_token}", f"incident_{ts_token}")
    os.makedirs(root, exist_ok=True)
    _restrict_directory_permissions(root)
    return root


def cleanup_old_evidence(settings: Optional[Mapping[str, Any]] = None, *, now: Optional[float] = None) -> Dict[str, Any]:
    current = float(time.time() if now is None else now)
    ttl_seconds = float(retention_days(settings) * 86400)
    root = evidence_dir()
    removed: List[str] = []
    if not os.path.isdir(root):
        return {"removed": removed, "root": root}
    with _EVIDENCE_LOCK:
        for session_dir in list(Path(root).glob("session_*")):
            if not session_dir.is_dir():
                continue
            for incident_dir in list(session_dir.glob("incident_*")):
                try:
                    modified = incident_dir.stat().st_mtime
                except OSError:
                    continue
                if current - modified < ttl_seconds:
                    continue
                try:
                    shutil.rmtree(incident_dir)
                    removed.append(str(incident_dir))
                except OSError:
                    LOGGER.warning("Failed removing old evidence directory %s", incident_dir, exc_info=True)
            try:
                if session_dir.is_dir() and not any(session_dir.iterdir()):
                    session_dir.rmdir()
            except OSError:
                pass
    return {"removed": removed, "root": root}


def delete_evidence_for_session(session_id: str) -> None:
    token = _safe_component(session_id, "unknown")
    path = os.path.join(evidence_dir(), f"session_{token}")
    if not os.path.isdir(path):
        return
    try:
        shutil.rmtree(path)
    except OSError:
        LOGGER.warning("Failed deleting evidence for session %s", session_id, exc_info=True)


def delete_evidence_for_user(user_id: str) -> None:
    safe_user = _safe_component(user_id, "unknown")
    root = evidence_dir()
    if not os.path.isdir(root):
        return
    for incident_json in Path(root).glob("session_*/incident_*/incident.json"):
        try:
            payload = json.loads(incident_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Skipping unreadable evidence incident record %s during user evidence deletion", incident_json, exc_info=True)
            continue
        if _safe_component(payload.get("user_id"), "") != safe_user:
            continue
        try:
            shutil.rmtree(str(incident_json.parent))
        except OSError:
            LOGGER.warning("Failed deleting evidence incident %s for user %s", incident_json.parent, user_id, exc_info=True)


def _ensure_qt_gui_app():
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError as exc:  # pragma: no cover - depends on runtime extras
        LOGGER.info("Qt GUI is unavailable for evidence capture: %s", exc)
        return None, f"qt_unavailable: {exc}"
    app = QGuiApplication.instance()
    created = False
    if app is None:
        try:
            app = QGuiApplication(["bioauth-evidence"])
            created = True
        except Exception as exc:  # pragma: no cover - depends on runtime platform
            LOGGER.warning("Qt GUI application initialization failed for evidence capture.", exc_info=True)
            return None, f"qt_app_init_failed: {exc}"
    return (app, created), None


def _process_qt_events(app: Any, timeout_sec: float, predicate) -> bool:
    deadline = time.time() + max(0.05, float(timeout_sec))
    while time.time() < deadline:
        try:
            app.processEvents()
        except Exception:
            LOGGER.debug("Qt event processing failed during evidence capture.", exc_info=True)
        if predicate():
            return True
        time.sleep(0.01)
    try:
        app.processEvents()
    except Exception:
        LOGGER.debug("Final Qt event processing failed during evidence capture.", exc_info=True)
    return predicate()


def try_capture_screenshot(output_path: str, *, timeout_sec: float = DEFAULT_SCREENSHOT_TIMEOUT_SEC) -> Dict[str, Any]:
    context, error = _ensure_qt_gui_app()
    if context is None:
        return {"status": "failed", "error_reason": error, "file_path": output_path, "display_count": 0}
    app, _created = context
    try:
        from PySide6.QtCore import QPoint, QRect, Qt
        from PySide6.QtGui import QPainter, QPixmap
    except ImportError as exc:  # pragma: no cover - depends on runtime extras
        LOGGER.info("Qt GUI screenshot dependencies are unavailable: %s", exc)
        return {"status": "failed", "error_reason": f"qt_gui_import_failed: {exc}", "file_path": output_path, "display_count": 0}

    def _screens_ready() -> bool:
        try:
            return bool(list(app.screens()))
        except Exception:
            LOGGER.debug("Qt screen enumeration failed during evidence capture.", exc_info=True)
            return False

    if not _process_qt_events(app, timeout_sec, _screens_ready):
        return {"status": "failed", "error_reason": "screen_unavailable", "file_path": output_path, "display_count": 0}

    try:
        screens = list(app.screens())
        if not screens:
            return {"status": "failed", "error_reason": "screen_unavailable", "file_path": output_path, "display_count": 0}
        if len(screens) == 1:
            pixmap = screens[0].grabWindow(0)
            if pixmap.isNull():
                return {"status": "failed", "error_reason": "empty_screenshot", "file_path": output_path, "display_count": 1}
            ok = bool(pixmap.save(output_path, "PNG"))
            width = int(pixmap.width())
            height = int(pixmap.height())
        else:
            bounds = QRect()
            for screen in screens:
                bounds = bounds.united(screen.geometry())
            canvas = QPixmap(bounds.size())
            canvas.fill(Qt.GlobalColor.black)
            painter = QPainter(canvas)
            for screen in screens:
                shot = screen.grabWindow(0)
                geom = screen.geometry()
                painter.drawPixmap(QPoint(geom.x() - bounds.x(), geom.y() - bounds.y()), shot)
            painter.end()
            ok = bool(canvas.save(output_path, "PNG"))
            width = int(canvas.width())
            height = int(canvas.height())
        if not ok:
            return {"status": "failed", "error_reason": "save_failed", "file_path": output_path, "display_count": len(screens)}
        return {
            "status": "success",
            "file_path": output_path,
            "display_count": len(screens),
            "resolution": f"{width}x{height}",
        }
    except Exception as exc:  # pragma: no cover - platform specific
        LOGGER.warning("Screenshot evidence capture failed.", exc_info=True)
        return {"status": "failed", "error_reason": f"screenshot_failed: {exc}", "file_path": output_path, "display_count": 0}


def try_capture_webcam_burst(output_dir: str, *, count: int = DEFAULT_WEBCAM_FRAMES, timeout_sec: float = DEFAULT_WEBCAM_TIMEOUT_SEC) -> Dict[str, Any]:
    frame_count = max(1, min(2, int(count or DEFAULT_WEBCAM_FRAMES)))
    context, error = _ensure_qt_gui_app()
    if context is None:
        return {"status": "failed", "error_reason": error, "saved_paths": [], "captured_count": 0}
    app, _created = context
    try:
        from PySide6.QtMultimedia import QCamera, QImageCapture, QMediaCaptureSession, QMediaDevices
    except ImportError as exc:  # pragma: no cover - depends on runtime extras
        LOGGER.info("Qt multimedia evidence dependencies are unavailable: %s", exc)
        return {"status": "failed", "error_reason": f"qt_multimedia_unavailable: {exc}", "saved_paths": [], "captured_count": 0}

    devices = []
    try:
        devices = list(QMediaDevices.videoInputs())
    except Exception:
        LOGGER.warning("Camera device enumeration failed for evidence capture.", exc_info=True)
        devices = []
    if not devices:
        return {"status": "failed", "error_reason": "camera_unavailable", "saved_paths": [], "captured_count": 0}

    saved: List[str] = []
    errors: List[str] = []
    capture_session = QMediaCaptureSession()
    camera = QCamera(devices[0])
    image_capture = QImageCapture()
    capture_session.setCamera(camera)
    capture_session.setImageCapture(image_capture)

    def _on_saved(_capture_id: int, file_name: str) -> None:
        if file_name:
            saved.append(str(file_name))

    def _on_error(*args: Any) -> None:
        message = str(args[-1] if args else "capture_failed")
        errors.append(message)

    try:
        image_capture.imageSaved.connect(_on_saved)
    except Exception:
        LOGGER.debug("Could not connect camera imageSaved signal for evidence capture.", exc_info=True)
    try:
        image_capture.errorOccurred.connect(_on_error)
    except Exception:
        LOGGER.debug("Could not connect camera error signal for evidence capture.", exc_info=True)

    try:
        camera.start()
    except Exception as exc:  # pragma: no cover - platform specific
        LOGGER.warning("Camera evidence capture failed to start.", exc_info=True)
        return {"status": "failed", "error_reason": f"camera_start_failed: {exc}", "saved_paths": [], "captured_count": 0}

    try:
        if not _process_qt_events(app, timeout_sec, lambda: bool(image_capture.isReadyForCapture())):
            return {"status": "failed", "error_reason": "camera_not_ready", "saved_paths": [], "captured_count": 0}
        for index in range(frame_count):
            target_path = os.path.join(output_dir, f"webcam_{index + 1:02d}.jpg")
            before = len(saved)
            try:
                image_capture.captureToFile(target_path)
            except Exception as exc:  # pragma: no cover - platform specific
                LOGGER.warning("Camera evidence capture request failed.", exc_info=True)
                errors.append(f"capture_request_failed: {exc}")
                continue
            completed = _process_qt_events(app, timeout_sec, lambda: len(saved) > before or os.path.exists(target_path) or bool(errors))
            if not completed:
                errors.append("camera_capture_timeout")
                continue
            if os.path.exists(target_path) and target_path not in saved:
                saved.append(target_path)
        captured_count = len([path for path in saved if os.path.exists(path)])
        status = "success" if captured_count == frame_count else "partial_success" if captured_count > 0 else "failed"
        error_reason = "; ".join(errors) if errors else ""
        return {
            "status": status,
            "error_reason": error_reason,
            "saved_paths": [path for path in saved if os.path.exists(path)],
            "captured_count": captured_count,
            "requested_count": frame_count,
        }
    finally:
        try:
            camera.stop()
        except Exception:
            LOGGER.debug("Camera stop failed during evidence capture cleanup.", exc_info=True)


def update_incident_record(incident_path: str, **changes: Any) -> Dict[str, Any]:
    target = str(incident_path or "").strip()
    if not target or not os.path.exists(target):
        return {}
    try:
        with open(target, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            payload = {}
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Incident record %s could not be loaded for update; recreating safe payload.", target, exc_info=True)
        payload = {}
    payload.update({key: value for key, value in changes.items()})
    _write_json(target, payload)
    return payload


def _build_incident_payload(*, event: Mapping[str, Any], ts_token: str, incident_dir: str, screenshot_result: Mapping[str, Any], webcam_result: Mapping[str, Any], archive_status: str, lock_status: str) -> Dict[str, Any]:
    session_id = str(event.get("session_id") or "")
    user_id = str(event.get("user_id") or "")
    incident_type = str(event.get("incident_type") or "confirmed_intruder")
    payload: Dict[str, Any] = {
        "incident_id": f"{_safe_component(session_id, 'session')}-{ts_token}",
        "session_id": session_id,
        "user_id": user_id,
        "incident_type": incident_type,
        "trigger_reason": str(event.get("trigger_reason") or incident_type),
        "timestamp": _utc_now().isoformat(),
        "incident_directory": incident_dir,
        "screenshot_status": str(screenshot_result.get("status") or "not_requested"),
        "webcam_status": str(webcam_result.get("status") or "not_requested"),
        "webcam_frames_saved": int(webcam_result.get("captured_count", 0) or 0),
        "archive_status": archive_status,
        "lock_status": lock_status,
        "error_details": {
            "screenshot": str(screenshot_result.get("error_reason") or ""),
            "webcam": str(webcam_result.get("error_reason") or ""),
        },
        "capture_mode": "explicit_consent_local_only",
        "privacy_mode": "incident_only",
        "privacy_policy_version": PRIVACY_POLICY_VERSION,
        "evidence_consent_policy_version": str(event.get("evidence_consent_policy_version") or ""),
        "evidence_consent_timestamp": str(event.get("evidence_consent_timestamp") or ""),
        "files": {
            "screenshot": os.path.basename(str(screenshot_result.get("file_path") or "")) if screenshot_result.get("file_path") else "",
            "webcam": [os.path.basename(str(path)) for path in list(webcam_result.get("saved_paths") or [])],
        },
    }
    if screenshot_result.get("resolution"):
        payload["screenshot_resolution"] = str(screenshot_result.get("resolution"))
    if screenshot_result.get("display_count") not in (None, ""):
        payload["display_count"] = int(screenshot_result.get("display_count") or 0)
    return payload


def capture_incident_evidence(event: Mapping[str, Any], *, settings: Optional[Mapping[str, Any]] = None, archive_status: str = "pending", lock_status: str = "pending") -> Dict[str, Any]:
    event = dict(event or {})
    incident_type = str(event.get("incident_type") or "confirmed_intruder").strip().lower() or "confirmed_intruder"
    if incident_type not in SUPPORTED_INCIDENTS:
        return {"enabled": False, "status": "skipped", "reason": "unsupported_incident", "incident_type": incident_type}
    effective_settings = dict(settings) if isinstance(settings, Mapping) else load_settings()
    if not evidence_enabled(effective_settings):
        return {"enabled": False, "status": "disabled", "reason": "opt_in_disabled", "incident_type": incident_type}
    if not evidence_consent_valid(effective_settings):
        return {"enabled": False, "status": "blocked", "reason": "explicit_consent_required", "incident_type": incident_type}

    event.setdefault("evidence_consent_policy_version", str(effective_settings.get("incident_evidence_consent_policy_version") or ""))
    event.setdefault("evidence_consent_timestamp", str(effective_settings.get("incident_evidence_consent_timestamp") or ""))
    cleanup_old_evidence(effective_settings)
    ts_token = _incident_timestamp()
    session_id = str(event.get("session_id") or "unknown")
    incident_dir = _build_incident_dir(session_id, ts_token)
    screenshot_path = os.path.join(incident_dir, "evidence_screen.png")
    screenshot_result: Dict[str, Any] = {"status": "not_requested", "file_path": screenshot_path, "display_count": 0}
    webcam_result: Dict[str, Any] = {"status": "not_requested", "saved_paths": [], "captured_count": 0}

    with _EVIDENCE_LOCK:
        if screenshot_enabled(effective_settings):
            screenshot_result = dict(try_capture_screenshot(screenshot_path))
        if webcam_enabled(effective_settings):
            webcam_result = dict(try_capture_webcam_burst(incident_dir, count=webcam_frame_count(effective_settings)))

        incident_payload = _build_incident_payload(
            event=event,
            ts_token=ts_token,
            incident_dir=incident_dir,
            screenshot_result=screenshot_result,
            webcam_result=webcam_result,
            archive_status=archive_status,
            lock_status=lock_status,
        )

        hashes: Dict[str, str] = {}
        candidate_files = []
        if screenshot_result.get("status") == "success" and os.path.exists(screenshot_path):
            candidate_files.append(screenshot_path)
        candidate_files.extend([path for path in list(webcam_result.get("saved_paths") or []) if os.path.exists(path)])
        for path in candidate_files:
            try:
                hashes[os.path.basename(path)] = f"sha256:{_calculate_file_sha256(path)}"
            except Exception as exc:
                LOGGER.warning("Failed hashing evidence file %s: %s", path, exc, exc_info=True)

        hashes_path = os.path.join(incident_dir, "hashes.json")
        incident_path = os.path.join(incident_dir, "incident.json")
        _write_json(hashes_path, hashes)
        _write_json(incident_path, incident_payload)

    saved_count = len(candidate_files)
    required_channels = int(bool(screenshot_enabled(effective_settings))) + int(bool(webcam_enabled(effective_settings)))
    saved_channels = int(screenshot_result.get("status") == "success") + int(bool(webcam_result.get("saved_paths") or []))
    if required_channels <= 0:
        result_status = "failed" if saved_count <= 0 else "partial_success"
    elif saved_channels >= required_channels:
        result_status = "success"
    elif saved_channels > 0:
        result_status = "partial_success"
    else:
        result_status = "failed"
    return {
        "enabled": True,
        "status": result_status,
        "incident_dir": incident_dir,
        "incident_path": incident_path,
        "hashes_path": hashes_path,
        "incident_id": incident_payload["incident_id"],
        "timestamp": incident_payload["timestamp"],
        "screenshot_status": incident_payload["screenshot_status"],
        "webcam_status": incident_payload["webcam_status"],
        "webcam_frames_saved": incident_payload["webcam_frames_saved"],
        "saved_file_count": saved_count,
        "hashes": hashes,
        "payload": incident_payload,
    }
