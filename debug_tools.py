from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot, QUrl
from PySide6.QtGui import QTextCursor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

DEBUG_PANEL_ENV = "BIOAUTH_DEBUG_PANEL"
DEBUG_PANEL_LOG_NAME = "bioauth_debug_panel.log"


def debug_panel_requested() -> bool:
    value = str(os.environ.get(DEBUG_PANEL_ENV, "") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _compact_payload(payload: Any) -> str:
    if payload in (None, "", {}, []):
        return ""
    try:
        return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    except Exception:
        return str(payload)


def _diag_value(data: Dict[str, Any], *path: str, default: Any = "-") -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    if current in (None, ""):
        return default
    return current


def _diag_count(value: Any) -> int:
    if isinstance(value, dict):
        return len(value)
    if isinstance(value, (list, tuple, set)):
        return len(value)
    try:
        return int(value or 0)
    except Exception:
        return 0


def _compact_diag(value: Any, *, max_len: int = 160) -> str:
    try:
        if isinstance(value, (dict, list, tuple)):
            text = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
        else:
            text = str(value)
    except Exception:
        text = str(value)
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


class DebugPanelWindow(QMainWindow):
    def __init__(self, log_path: str) -> None:
        super().__init__()
        self._log_path = str(log_path)
        self.setWindowTitle("BioAuth Debug Panel")
        self.resize(980, 760)
        self.setMinimumSize(760, 520)
        try:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        except Exception:
            pass

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("BioAuth live debug window")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Shows UI clicks, backend actions, worker progress, heartbeats, and warnings while the app is running."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(subtitle)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._clear_button = QPushButton("Clear")
        self._copy_button = QPushButton("Copy all")
        self._copy_summary_button = QPushButton("Copy summary")
        self._open_button = QPushButton("Open log file")
        self._open_logs_button = QPushButton("Open logs folder")
        self._open_control_button = QPushButton("Open control folder")
        self._status_chip = QLabel("Listening")
        self._status_chip.setStyleSheet(
            "padding: 6px 10px; border: 1px solid #9db6d1; border-radius: 12px; background: #eef5ff;"
        )
        toolbar.addWidget(self._clear_button)
        toolbar.addWidget(self._copy_button)
        toolbar.addWidget(self._copy_summary_button)
        toolbar.addWidget(self._open_button)
        toolbar.addWidget(self._open_logs_button)
        toolbar.addWidget(self._open_control_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self._status_chip)
        layout.addLayout(toolbar)

        summary_frame = QFrame()
        summary_frame.setFrameShape(QFrame.StyledPanel)
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setContentsMargins(10, 10, 10, 10)
        summary_layout.setSpacing(6)
        self._summary_label = QLabel("Waiting for heartbeat…")
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._summary_label.setStyleSheet("font-family: Consolas, 'Courier New', monospace; line-height: 1.35;")
        summary_layout.addWidget(self._summary_label)
        layout.addWidget(summary_frame)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        try:
            self._log_view.document().setMaximumBlockCount(1200)
        except Exception:
            pass
        self._log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._log_view.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 12px;")
        layout.addWidget(self._log_view, 1)

        self.setCentralWidget(root)

        self._latest_snapshot: Dict[str, Any] = {}
        self._clear_button.clicked.connect(self._clear)
        self._copy_button.clicked.connect(self._copy_all)
        self._copy_summary_button.clicked.connect(self._copy_summary)
        self._open_button.clicked.connect(self._open_log_file)
        self._open_logs_button.clicked.connect(self._open_logs_folder)
        self._open_control_button.clicked.connect(self._open_control_folder)

    @Slot()
    def _clear(self) -> None:
        self._log_view.clear()

    @Slot()
    def _copy_all(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        clipboard = app.clipboard()
        if clipboard is None:
            return
        clipboard.setText(self._log_view.toPlainText())

    @Slot()
    def _copy_summary(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        clipboard = app.clipboard()
        if clipboard is None:
            return
        clipboard.setText(self._summary_label.text())

    def _open_folder(self, path: str) -> None:
        try:
            safe = str(path or "")
            if safe and os.path.exists(safe):
                QDesktopServices.openUrl(QUrl.fromLocalFile(safe))
        except Exception:
            return

    @Slot()
    def _open_logs_folder(self) -> None:
        self._open_folder(str(Path(self._log_path).parent))

    @Slot()
    def _open_control_folder(self) -> None:
        data = dict(getattr(self, "_latest_snapshot", {}) or {})
        control = (((data.get("debug_health") or {}).get("control") or {}) if isinstance(data.get("debug_health"), dict) else {})
        control_dir = str(control.get("control_dir") or control.get("path") or "")
        if not control_dir:
            runtime = (data.get("debug_runtime") or {}) if isinstance(data.get("debug_runtime"), dict) else {}
            control_dir = str(runtime.get("control_dir") or "")
            if not control_dir:
                base_dir = str(runtime.get("base_dir") or "")
                # Developer fallback: show the app folder if the local control path is unavailable.
                control_dir = base_dir
        self._open_folder(control_dir)

    @Slot()
    def _open_log_file(self) -> None:
        try:
            if os.path.exists(self._log_path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(self._log_path))
        except Exception:
            return

    @Slot(str)
    def append_entry(self, line: str) -> None:
        text = str(line or "").rstrip()
        if not text:
            return
        self._log_view.appendPlainText(text)
        cursor = self._log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._log_view.setTextCursor(cursor)
        self._log_view.ensureCursorVisible()

    @Slot(object)
    def update_snapshot(self, snapshot: object) -> None:
        data = dict(snapshot or {}) if isinstance(snapshot, dict) else {}
        self._latest_snapshot = dict(data)
        user = str(data.get("user") or "-")
        flow = str(data.get("flow") or "-")
        runtime = str(data.get("runtime_status") or "idle")
        decision = str(data.get("runtime_decision") or "-")
        refresh_ms = int(data.get("refresh_interval_ms") or 0)
        processes = ", ".join(list(data.get("processes") or [])) or "-"
        training_active = bool(data.get("training_active"))
        training_percent = int(data.get("training_percent") or 0)
        training_headline = str(data.get("training_headline") or "-")
        training_detail = str(data.get("training_detail") or "-")
        status_message = str(data.get("status_message") or "-")
        status_tone = str(data.get("status_tone") or "info")
        threads = int(data.get("thread_count") or 0)
        last_ui = float(data.get("last_ui_activity_age_sec") or 0.0)
        pending_monitor = bool(data.get("pending_monitor_start"))
        history_sync = bool(data.get("history_sync_pending"))
        diag_code = str(data.get("runtime_diag_code") or "-")
        diag_reason = str(data.get("runtime_diag_reason") or "-")
        diag_summary = str(data.get("runtime_diag_summary") or "-")
        confirmation_rule = str(data.get("runtime_confirmation_rule") or "-")
        lock_allowed = bool(data.get("runtime_locking_allowed", True))
        lock_suppressed = float(data.get("runtime_lock_suppressed_for_sec") or 0.0)
        warning_count = int(data.get("runtime_warning_count") or 0)
        legit_streak = int(data.get("runtime_legit_streak") or 0)
        recent_decisions = list(data.get("runtime_recent_decisions") or [])
        recent_risks = list(data.get("runtime_recent_risks") or [])
        recent_ages = list(data.get("runtime_recent_ages_sec") or [])
        transition_status = str(data.get("runtime_transition_status") or "-")
        transition_active = bool(data.get("runtime_transition_active"))
        transition_recent = int(data.get("runtime_transition_recent_windows") or 0)
        transition_settled = int(data.get("runtime_transition_recent_settled_windows") or 0)
        transition_strength = float(data.get("runtime_transition_strength") or 0.0)
        window_count = int(data.get("runtime_window_count") or 0)
        window_diag_summary = str(data.get("runtime_window_diag_summary") or "-")
        monitor_failed = bool(data.get("monitor_failed"))
        risk_engine_stopped = bool(data.get("risk_engine_stopped"))
        monitor_exit_code = data.get("monitor_exit_code")
        monitor_exit_reason = str(data.get("monitor_exit_reason") or "-")
        monitor_exit_detail = str(data.get("monitor_exit_detail") or "-")
        monitor_stderr_tail = list(data.get("monitor_stderr_tail") or [])[-3:]
        monitor_stdout_tail = list(data.get("monitor_stdout_tail") or [])[-3:]
        full_heartbeat = str(os.environ.get("BIOAUTH_DEBUG_PANEL_FULL_HEARTBEAT", "") or "").strip().lower() in {"1", "true", "yes", "on"}
        top_risky_windows = list(data.get("runtime_top_risky_windows") or [])
        last_window_diag = dict(data.get("runtime_last_window_diag") or {})
        if not full_heartbeat:
            top_risky_windows = top_risky_windows[:2]
            if last_window_diag:
                last_window_diag = {
                    "index": last_window_diag.get("index"),
                    "risk": last_window_diag.get("risk"),
                    "context": last_window_diag.get("context") or last_window_diag.get("used_context"),
                    "event_count": last_window_diag.get("event_count"),
                    "quality_ok": last_window_diag.get("quality_ok"),
                    "quality_lock_ok": last_window_diag.get("quality_lock_ok"),
                    "reason_codes": list(last_window_diag.get("reason_codes") or [])[:6],
                }
        health = data.get("debug_health") if isinstance(data.get("debug_health"), dict) else {}
        production = data.get("debug_production_approval") if isinstance(data.get("debug_production_approval"), dict) else {}
        runtime_debug = data.get("debug_runtime") if isinstance(data.get("debug_runtime"), dict) else {}
        shadow = data.get("debug_shadow") if isinstance(data.get("debug_shadow"), dict) else {}
        profile = data.get("debug_profile_summary") if isinstance(data.get("debug_profile_summary"), dict) else {}
        session_readiness = health.get("session_readiness") if isinstance(health.get("session_readiness"), dict) else {}
        control = health.get("control") if isinstance(health.get("control"), dict) else {}
        lock = control.get("session_state_lock") if isinstance(control.get("session_state_lock"), dict) else {}
        checks = health.get("checks") if isinstance(health.get("checks"), list) else []

        lines = [
            "[Startup / Environment]",
            f"schema={data.get('debug_panel_schema_version') or '-'}",
            f"user={user}",
            f"pid={runtime_debug.get('pid', '-')}",
            f"parent_pid={runtime_debug.get('parent_pid', '-')}",
            f"python={runtime_debug.get('executable', '-')}",
            f"cwd={runtime_debug.get('cwd', '-')}",
            f"base_dir={runtime_debug.get('base_dir', '-')}",
            f"start_app_bat_detected={runtime_debug.get('start_app_bat_detected', False)}",
            f"env={_compact_diag(runtime_debug.get('env') or {}, max_len=220)}",
            "",
            "[Session State / Locks]",
            f"flow={flow}",
            f"runtime_status={runtime}",
            f"lock_exists={lock.get('exists', '-')}",
            f"lock_owner_pid={lock.get('owner_pid', '-')}",
            f"lock_owner_alive={lock.get('owner_alive', '-')}",
            f"lock_age_sec={lock.get('age_sec', '-')}",
            f"control_available={control.get('available', '-')}",
            f"quarantine_count={_diag_count(control.get('quarantine_files') or control.get('quarantine'))}",
            "",
            "[Training Readiness]",
            f"training_active={training_active}",
            f"training_percent={training_percent}",
            f"training_headline={training_headline}",
            f"training_detail={training_detail}",
            f"training_can_start={session_readiness.get('training_can_start', '-')}",
            f"primary_blocker={session_readiness.get('primary_blocker', '-')}",
            f"accepted_enrollment_sessions={session_readiness.get('accepted_enrollment_sessions', '-')}",
            f"counts_toward_training_minimum={session_readiness.get('counts_toward_training_minimum', '-')}",
            f"training_deficit={session_readiness.get('training_deficit', '-')}",
            f"rejection_reason_counts={_compact_diag(session_readiness.get('rejection_reason_counts') or {}, max_len=220)}",
            "",
            "[Protection / Monitor Readiness]",
            f"pending_monitor_start={pending_monitor}",
            f"running_processes={processes}",
            f"production_ready={profile.get('production_ready', '-')}",
            f"can_start_monitor={profile.get('can_start_monitor', '-')}",
            f"runtime_locking_allowed={lock_allowed}",
            f"runtime_lock_suppressed_for_sec={lock_suppressed:.1f}",
            f"monitor_failed={monitor_failed}",
            f"risk_engine_stopped={risk_engine_stopped}",
            f"monitor_exit_code={monitor_exit_code}",
            f"monitor_exit_reason={monitor_exit_reason}",
            f"monitor_exit_detail={_compact_diag(monitor_exit_detail, max_len=180)}",
            f"monitor_stderr_tail={_compact_diag(monitor_stderr_tail, max_len=220)}",
            f"monitor_stdout_tail={_compact_diag(monitor_stdout_tail, max_len=220)}",
            "",
            "[Production Approval / Promotion Gate]",
            f"candidate_status={production.get('candidate_status') or production.get('modelStatus') or profile.get('candidate_status', '-')}",
            f"approval_status={production.get('status', '-')}",
            f"protected_sessions_available={production.get('protected_sessions_available', production.get('protectedSessionsAvailable', '-'))}",
            f"reason_code={production.get('reason_code') or production.get('reasonCode') or '-'}",
            f"reason_codes={_compact_diag(production.get('reason_codes') or production.get('reasonCodes') or [], max_len=220)}",
            f"selection_status={production.get('selectionPromotionStatus') or production.get('selection_promotion_status') or '-'}",
            f"selection_weighted_score={production.get('selectionPromotionWeightedScore', production.get('selection_promotion_weighted_score', '-'))}",
            "",
            "[Shadow Diagnostics]",
            f"shadow_status={_compact_diag(shadow.get('status') or shadow.get('phase') or shadow.get('mode') or '-', max_len=120)}",
            f"shadow_process_running={shadow.get('process_running', shadow.get('running', '-'))}",
            f"shadow_state_kind={shadow.get('session_kind') or shadow.get('runtime_mode') or '-'}",
            f"shadow_default_env_enabled={runtime_debug.get('env', {}).get('BIOAUTH_ENABLE_SHADOW_EVIDENCE_MONITOR', '')}",
            f"shadow_ledger_records={_diag_value(health, 'shadow', 'ledger_record_count', default='-')}",
            f"shadow_last_error={_compact_diag(shadow.get('last_error') or '-', max_len=160)}",
            "",
            "[Hybrid Removal Status]",
            f"hybrid_required_for_training={False}",
            f"hybrid_removed_from_commercial_flow={True}",
            f"legacy_hybrid_env={runtime_debug.get('env', {}).get('BIOAUTH_HYBRID_TEST_ONLY', '')}",
            "",
            "[Runtime / Fusion / Face Feedback]",
            f"runtime_decision={decision}",
            f"runtime_diag_code={diag_code}",
            f"runtime_diag_reason={diag_reason}",
            f"runtime_diag_summary={diag_summary}",
            f"runtime_confirmation_rule={confirmation_rule}",
            f"runtime_warning_count={warning_count}",
            f"runtime_legit_streak={legit_streak}",
            f"runtime_window_count={window_count}",
            f"runtime_transition_status={transition_status}",
            f"runtime_transition_active={transition_active}",
            f"runtime_window_diag_summary={window_diag_summary}",
            f"runtime_top_risky_windows={top_risky_windows}",
            f"runtime_last_window_diag={last_window_diag}",
            f"runtime_recent_decisions={recent_decisions}",
            f"runtime_recent_risks={recent_risks}",
            "",
            "[Performance / Refresh]",
            f"refresh_interval_ms={refresh_ms}",
            f"thread_count={threads}",
            f"last_ui_activity_age_sec={last_ui:.1f}",
            f"history_sync_pending={history_sync}",
            f"health_overall_status={health.get('overall_status', '-')}",
            f"health_checks={_compact_diag(checks, max_len=240)}",
            "",
            "[Status]",
            f"status_tone={status_tone}",
            f"status_message={status_message}",
        ]
        self._summary_label.setText("\n".join(lines))
        if training_active or flow != "idle":
            self._status_chip.setText("Busy")
            self._status_chip.setStyleSheet(
                "padding: 6px 10px; border: 1px solid #f59e0b; border-radius: 12px; background: #fff7e8; color: #8a4b00;"
            )
        else:
            self._status_chip.setText("Listening")
            self._status_chip.setStyleSheet(
                "padding: 6px 10px; border: 1px solid #9db6d1; border-radius: 12px; background: #eef5ff;"
            )


class _DebugLoggingHandler(logging.Handler):
    def __init__(self, controller: "DebugPanelController") -> None:
        super().__init__(level=logging.INFO)
        self._controller = controller
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            logger_name = str(record.name or "")
            should_forward = record.levelno >= logging.WARNING or logger_name.startswith(
                (
                    "bridge",
                    "model_training",
                    "model_metadata",
                    "model_evaluation",
                    "monitor",
                    "logger",
                    "shadow_model",
                    "desktop_app",
                )
            )
            if not should_forward:
                return
            self._controller.trace(
                "python-log",
                self.format(record),
                payload={"logger": logger_name, "level": record.levelname},
                level=str(record.levelname or "INFO").lower(),
            )
        except Exception:
            return


class DebugPanelController(QObject):
    entryReady = Signal(str)
    snapshotReady = Signal(object)

    def __init__(self, app: QApplication, base_dir: str) -> None:
        super().__init__(app)
        self._app = app
        self._base_dir = str(base_dir)
        self._log_path = str(Path(base_dir) / DEBUG_PANEL_LOG_NAME)
        self._window = DebugPanelWindow(self._log_path)
        self._bridge: Optional[Any] = None
        self._last_heartbeat_signature = ""
        self._last_trace_at = 0.0
        self._last_entry_file_flush_at = 0.0
        self._logging_handler: Optional[_DebugLoggingHandler] = None
        self._entry_file = open(self._log_path, "a", encoding="utf-8", errors="replace")

        self.entryReady.connect(self._window.append_entry)
        self.snapshotReady.connect(self._window.update_snapshot)

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(4000)
        self._heartbeat_timer.timeout.connect(self._emit_heartbeat)

        self._install_logging_handler()
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        self.trace("app", "Debug panel opened", payload={"log_path": self._log_path})

    def set_bridge(self, bridge: Any) -> None:
        self._bridge = bridge
        self._heartbeat_timer.start()
        self.trace("app", "Backend bridge attached to debug panel")
        self._emit_heartbeat(force_trace=True)

    def shutdown(self) -> None:
        try:
            self.trace("app", "Debug panel shutting down")
        except Exception:
            pass
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.stop()
        if self._logging_handler is not None:
            try:
                logging.getLogger().removeHandler(self._logging_handler)
            except Exception:
                pass
            self._logging_handler = None
        try:
            self._entry_file.close()
        except Exception:
            pass

    def _install_logging_handler(self) -> None:
        if self._logging_handler is not None:
            return
        handler = _DebugLoggingHandler(self)
        root = logging.getLogger()
        root.addHandler(handler)
        self._logging_handler = handler

    def trace(self, category: str, message: str, payload: Optional[Dict[str, Any]] = None, level: str = "info") -> None:
        timestamp = time.strftime("%H:%M:%S")
        millis = int((time.time() % 1.0) * 1000)
        thread_name = threading.current_thread().name
        prefix = f"[{timestamp}.{millis:03d}] [{str(level or 'info').upper()}] [{thread_name}] [{str(category or 'event')}]"
        payload_text = _compact_payload(payload)
        line = f"{prefix} {str(message or '').strip()}"
        if payload_text:
            line = f"{line} | {payload_text}"
        now = time.time()
        try:
            self._entry_file.write(line + "\n")
            should_flush = str(level or "info").strip().lower() in {"warn", "warning", "error", "critical"} or (now - float(self._last_entry_file_flush_at or 0.0)) >= 1.0
            if should_flush:
                self._entry_file.flush()
                self._last_entry_file_flush_at = now
        except Exception:
            pass
        self._last_trace_at = now
        self.entryReady.emit(line)

    def _heartbeat_message(self, snapshot: Dict[str, Any]) -> str:
        user = str(snapshot.get("user") or "-")
        flow = str(snapshot.get("flow") or "-")
        runtime = str(snapshot.get("runtime_status") or "idle")
        decision = str(snapshot.get("runtime_decision") or "-")
        training_active = bool(snapshot.get("training_active"))
        training_percent = int(snapshot.get("training_percent") or 0)
        training_detail = str(snapshot.get("training_detail") or "-")
        processes = ", ".join(list(snapshot.get("processes") or [])) or "-"
        diag_code = str(snapshot.get("runtime_diag_code") or "")
        diag_summary = str(snapshot.get("runtime_diag_summary") or "").strip()
        message = (
            f"heartbeat user={user} flow={flow} runtime={runtime} decision={decision} "
            f"training_active={training_active} training_percent={training_percent} "
            f"training_detail={training_detail} processes={processes}"
        )
        if diag_code or diag_summary:
            message = f"{message} diag={diag_code or '-'}"
        return message

    @Slot()
    def _emit_heartbeat(self, force_trace: bool = False) -> None:
        bridge = self._bridge
        if bridge is None:
            return
        try:
            snapshot = bridge._debug_snapshot()
        except Exception as exc:
            self.trace("heartbeat", "Failed to read backend snapshot", payload={"error": str(exc)}, level="error")
            return
        self.snapshotReady.emit(snapshot)
        signature = _compact_payload(
            {
                "flow": snapshot.get("flow"),
                "runtime_status": snapshot.get("runtime_status"),
                "runtime_decision": snapshot.get("runtime_decision"),
                "runtime_diag_code": snapshot.get("runtime_diag_code"),
                "runtime_diag_summary": snapshot.get("runtime_diag_summary"),
                "training_active": snapshot.get("training_active"),
                "training_percent": snapshot.get("training_percent"),
                "training_detail": snapshot.get("training_detail"),
                "processes": snapshot.get("processes"),
            }
        )
        active = bool(snapshot.get("training_active")) or str(snapshot.get("flow") or "idle") != "idle"
        stale_gap = time.time() - float(self._last_trace_at or 0.0)
        if force_trace or active or signature != self._last_heartbeat_signature or stale_gap >= 10.0:
            payload = snapshot
            full_payload = str(os.environ.get("BIOAUTH_DEBUG_PANEL_FULL_HEARTBEAT", "") or "").strip().lower() in {"1", "true", "yes", "on"}
            if not full_payload:
                payload = {
                    "user": snapshot.get("user"),
                    "flow": snapshot.get("flow"),
                    "runtime_status": snapshot.get("runtime_status"),
                    "runtime_decision": snapshot.get("runtime_decision"),
                    "runtime_diag_code": snapshot.get("runtime_diag_code"),
                    "runtime_diag_reason": snapshot.get("runtime_diag_reason"),
                    "training_active": snapshot.get("training_active"),
                    "training_percent": snapshot.get("training_percent"),
                    "processes": snapshot.get("processes"),
                    "refresh_interval_ms": snapshot.get("refresh_interval_ms"),
                    "status_tone": snapshot.get("status_tone"),
                    "status_message": snapshot.get("status_message"),
                    "thread_count": snapshot.get("thread_count"),
                    "pending_monitor_start": snapshot.get("pending_monitor_start"),
                }
            self.trace("heartbeat", self._heartbeat_message(snapshot), payload=payload)
        self._last_heartbeat_signature = signature


def create_debug_panel(app: QApplication, base_dir: str) -> DebugPanelController:
    return DebugPanelController(app, base_dir)
