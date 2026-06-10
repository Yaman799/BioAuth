"""Extracted implementation section for `src/bioauth/app/desktop_app_impl.py`."""
from __future__ import annotations
import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from app_passcode import is_passcode_configured
from bioauth_version import get_app_version
from app_settings import (
    PRIVACY_POLICY_VERSION,
    has_current_evidence_consent,
    has_current_privacy_consent,
    normalize_interface_mode,
    resolve_ui_mode,
)
from deep_runtime import (
    deep_runtime_fallback_reason_text,
    deep_runtime_is_fallback,
    normalize_benchmark_record,
    normalize_deep_runtime_fallback_reason,
    normalize_deep_runtime_mode,
    resolve_deep_runtime_state,
)
from license_manager import evaluate_license
from metadata_core.auto_enrollment import build_auto_enrollment_state, is_passive_auto_enrollment_state, passive_collection_should_start
from metadata_core.auto_training_scheduler import background_action_from_status
from metadata_core.autonomous_readiness_loop import build_autonomous_readiness_loop_state
from metadata_core.remediation_loop import (
    REMEDIATION_REASON_CODE_MAPPING_TABLE,
    RemediationPlan,
    build_remediation_plan_from_gate_state,
    normalize_reason_codes,
)
from metadata_core.production_approval import (
    apply_production_approval_runtime_context,
    production_approval_observability_payload,
    production_approval_observability_signature,
    with_protected_sessions_ready_notification_state,
)
from metadata_core.shadow_loop import build_shadow_loop_state
from metadata_core.developer_readiness import build_effective_production_ready_state
from release_profile import profile_payload
from release_runtime import runtime_path_report, write_release_runtime_event
from onboarding_content import build_onboarding_slides
from startup_branding import create_startup_splash, finish_startup_splash, should_show_startup_splash
from hybrid_direct_contract import build_default_hybrid_direct_state, normalize_hybrid_direct_state
from safety_gate_policy import (
    build_safety_gate_report,
    emergency_disable_hybrid_state,
    rollback_to_classic_state,
    safety_gate_results_for_hybrid_state,
    write_safety_gate_report,
)
from bridge.shared import (
    BASE_DIR,
    LOGGER_SCRIPT,
    MAX_ENROLLMENT_SESSIONS,
    MIN_ENROLLMENT_SESSIONS,
    MONITOR_SCRIPT,
    normalize_sensitivity_preset,
    PRIVACY_POLICY_PATH,
    ABOUT_US_PATH,
    Property,
    QApplication,
    QIcon,
    QLocale_name,
    QMenu,
    QObject,
    QQmlApplicationEngine,
    QSystemTrayIcon,
    QTimer,
    QUrl,
    REFRESH_IDLE_AUTH_MS,
    STRINGS,
    Signal,
    Slot,
    THEMES,
    _run_worker_if_requested,
    is_startup_enabled,
    load_settings,
    save_settings_async,
)
from bridge.auth_mixin import AuthMixin
from bridge.refresh_mixin import RefreshMixin
from bridge.session_mixin import SessionMixin
from bridge.settings_mixin import SettingsMixin
from bridge.update_mixin import UpdateMixin
from bridge import session_runtime_helpers, session_training_helpers
from bridge.qt_thread_dispatch import install_qt_thread_dispatcher

def _format_qml_warning(warning: Any) -> str:
    """Best-effort conversion of a QQmlError/warning object to text."""

    try:
        value = warning.toString()
    except Exception:
        value = str(warning)
    return str(value or "").strip()

def _write_qml_startup_failure_log(qml_path: str, warnings: List[str]) -> None:
    """Write a local startup diagnostics file before exiting on QML load failure.

    ``start_app.pyw`` only sees the final ``SystemExit`` traceback, so QML parse and
    import warnings can otherwise be lost for users launching BioAuth outside a
    console.  The log contains paths and diagnostics only; it does not include
    passcodes, tokens, biometric samples, model payloads, or settings contents.
    """

    try:
        lines = [
            "BioAuth QML startup failure diagnostics",
            f"qml_path={qml_path}",
            f"cwd={os.getcwd()}",
            f"frozen={bool(getattr(sys, 'frozen', False))}",
            "warnings:",
        ]
        if warnings:
            lines.extend(f"- {item}" for item in warnings)
        else:
            lines.append("- <no QQmlApplicationEngine warnings captured>")
        log_path = os.path.join(BASE_DIR, "start_app_qml_error.log")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        print(f"QML diagnostics log: {log_path}", file=sys.stderr)
    except Exception as exc:
        print(f"Failed to write QML diagnostics log: {exc}", file=sys.stderr)

def run_runtime_smoke_selfcheck() -> int:
    from build_tools import packaged_runtime_support as _support
    return _support.run_runtime_smoke_selfcheck()

def run_packaging_performance_check() -> int:
    from build_tools import packaged_runtime_support as _support
    return _support.run_packaging_performance_check()

def run_packaging_selfcheck() -> int:
    checks: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    required_paths = {
        "qml/Main.qml": os.path.join(BASE_DIR, "qml", "Main.qml"),
        "PRIVACY_POLICY.md": os.path.join(BASE_DIR, "PRIVACY_POLICY.md"),
        "bioauth.ico": os.path.join(BASE_DIR, "bioauth.ico"),
    }
    for name, path in required_paths.items():
        record(name, os.path.exists(path), path)

    try:
        import logger  # noqa: F401
        from logger import run_logger  # noqa: F401

        record("logger import", True)
    except Exception as exc:
        record("logger import", False, str(exc))

    try:
        import monitor  # noqa: F401
        from monitor import monitor as _monitor_entry  # noqa: F401

        record("monitor import", True)
    except Exception as exc:
        record("monitor import", False, str(exc))

    try:
        import deep_runtime
        inventory = deep_runtime.detect_backend_inventory()
        record("deep runtime import", True, f"preferred={inventory.get('preferred_backend')}")
    except Exception as exc:
        record("deep runtime import", False, str(exc))

    try:
        import deep_sequence.inference  # noqa: F401
        record("deep sequence runtime import", True)
    except Exception as exc:
        record("deep sequence runtime import", False, str(exc))

    try:
        from PySide6.QtCore import QUrl  # noqa: F401
        from PySide6.QtQml import QQmlApplicationEngine  # noqa: F401

        record("PySide6/QML import", True)
    except Exception as exc:
        record("PySide6/QML import", False, str(exc))

    try:
        path_report = runtime_path_report()
        record("user-writable runtime data dir", bool(path_report.get("data_dir_writable")), str(path_report.get("data_dir")))
        record("runtime data outside install root", bool(path_report.get("data_dir_outside_runtime_base")), str(path_report.get("runtime_base_dir")))
        record("release diagnostics outside install root", bool(path_report.get("event_log_outside_runtime_base")), str(path_report.get("release_event_log_file")))
    except Exception as exc:
        record("release runtime path report", False, str(exc))

    failed = False
    print("== BioAuth packaging self-check ==")
    for name, ok, detail in checks:
        state = "OK" if ok else "FAIL"
        suffix = f" :: {detail}" if detail else ""
        print(f"[{state}] {name}{suffix}")
        failed = failed or (not ok)

    return 1 if failed else 0

def main() -> None:
    _run_worker_if_requested()
    if "--self-check-packaging" in sys.argv:
        raise SystemExit(run_packaging_selfcheck())
    if "--self-check-runtime-smoke" in sys.argv:
        raise SystemExit(run_runtime_smoke_selfcheck())
    if "--self-check-performance" in sys.argv:
        raise SystemExit(run_packaging_performance_check())
    if "--self-check-release-readiness" in sys.argv:
        from build_tools import packaged_runtime_support as _support
        raise SystemExit(_support.run_release_readiness_selfcheck())
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    from bioauth_runtime.desktop_instance import acquire_desktop_instance, release_desktop_instance

    desktop_instance = acquire_desktop_instance(BASE_DIR)
    if not bool(desktop_instance.get("ok")):
        print("[BioAuth] duplicate_desktop_app_detected: another BioAuth desktop instance already owns this project/control directory.", file=sys.stderr)
        print(json.dumps(desktop_instance, ensure_ascii=False, indent=2, default=str), file=sys.stderr)
        raise SystemExit(2)

    app = QApplication(sys.argv)
    app.setOrganizationName("BioAuth")
    app.setApplicationName("BioAuth")
    icon_path = os.path.join(BASE_DIR, "bioauth.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    splash = None
    if should_show_startup_splash(sys.argv):
        splash = create_startup_splash(app, BASE_DIR)

    debug_controller = None
    debug_requested = str(os.environ.get("BIOAUTH_DEBUG_PANEL", "") or "").strip().lower() in {"1", "true", "yes", "on"}
    if debug_requested:
        try:
            from debug_tools import create_debug_panel

            debug_controller = create_debug_panel(app, BASE_DIR)
            app.aboutToQuit.connect(debug_controller.shutdown)
        except Exception as exc:
            print(f"[BioAuth] Failed to open debug panel: {exc}", file=sys.stderr)
            debug_controller = None

    bridge = AppBridge(app=app, background=("--background" in sys.argv))
    try:
        app.aboutToQuit.connect(bridge._cleanup_on_application_shutdown)
    except Exception:
        pass
    try:
        app.commitDataRequest.connect(lambda _manager: bridge._cleanup_on_application_shutdown())
    except Exception:
        pass
    if debug_controller is not None:
        bridge.attachDebugController(debug_controller)

    engine = QQmlApplicationEngine()
    qml_startup_warnings: List[str] = []

    def _record_qml_startup_warnings(warnings: Any) -> None:
        try:
            iterable = list(warnings)
        except TypeError:
            iterable = [warnings]
        for warning in iterable:
            formatted = _format_qml_warning(warning)
            if formatted:
                qml_startup_warnings.append(formatted)

    try:
        engine.warnings.connect(_record_qml_startup_warnings)
    except Exception:
        pass
    engine.rootContext().setContextProperty("backend", bridge)
    qml_path = os.path.join(BASE_DIR, "qml", "Main.qml")
    engine.load(QUrl.fromLocalFile(qml_path))
    if not engine.rootObjects():
        try:
            if splash is not None:
                splash.close()
        except Exception:
            pass
        print("Failed to load QML UI.", file=sys.stderr)
        print(f"QML path: {qml_path}", file=sys.stderr)
        if qml_startup_warnings:
            print("QML diagnostics:", file=sys.stderr)
            for warning in qml_startup_warnings:
                print(f" - {warning}", file=sys.stderr)
        _write_qml_startup_failure_log(qml_path, qml_startup_warnings)
        print("If you are on Windows, install Microsoft Visual C++ 2015-2022 Redistributable (x64) and prefer Python from python.org instead of the Microsoft Store build.", file=sys.stderr)
        raise SystemExit(1)

    root = engine.rootObjects()[0]
    finish_startup_splash(QTimer, splash, root)

    if "--background" in sys.argv and bridge.authenticated:
        try:
            if bridge._tray is not None and hasattr(root, "hide"):
                root.hide()
            elif hasattr(root, "showMinimized"):
                root.showMinimized()
            else:
                root.setProperty("visible", False)
        except Exception:
            pass

    try:
        exit_code = app.exec()
    finally:
        release_desktop_instance()
    sys.exit(exit_code)
