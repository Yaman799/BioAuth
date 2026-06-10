from __future__ import annotations

import threading
import time
import types

import bridge.refresh_dashboard_helpers as dashboard_helpers
import bridge.refresh_runtime_helpers as runtime_helpers


class DummySignal:
    def __init__(self) -> None:
        self.count = 0
        self.payloads = []

    def emit(self, *args):
        self.count += 1
        self.payloads.append(args)




def _install_pyside_stubs():
    import sys

    if "PySide6" in sys.modules:
        return
    pyside = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")
    qtqml = types.ModuleType("PySide6.QtQml")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class QObject:
        pass

    class QUrl:
        @staticmethod
        def fromLocalFile(path):
            return str(path)

    class QTimer:
        @staticmethod
        def singleShot(*args, **kwargs):
            callback = args[-1] if args else None
            if callable(callback):
                callback()

    class QIcon:
        def __init__(self, *args, **kwargs):
            pass

    class QDesktopServices:
        @staticmethod
        def openUrl(*args, **kwargs):
            return True

    class QAction:
        def __init__(self, *args, **kwargs):
            pass

    class QQmlApplicationEngine:
        pass

    class QApplication:
        pass

    class QMenu:
        pass

    class QSystemTrayIcon:
        pass

    def Signal(*args, **kwargs):
        return DummySignal()

    def Slot(*args, **kwargs):
        def decorate(func):
            return func
        return decorate

    def Property(*args, **kwargs):
        def decorate(func):
            return property(func)
        return decorate

    qtcore.QObject = QObject
    qtcore.Property = Property
    qtcore.QTimer = QTimer
    qtcore.QUrl = QUrl
    qtcore.Signal = Signal
    qtcore.Slot = Slot
    qtgui.QAction = QAction
    qtgui.QDesktopServices = QDesktopServices
    qtgui.QIcon = QIcon
    qtqml.QQmlApplicationEngine = QQmlApplicationEngine
    qtwidgets.QApplication = QApplication
    qtwidgets.QMenu = QMenu
    qtwidgets.QSystemTrayIcon = QSystemTrayIcon

    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtQml"] = qtqml
    sys.modules["PySide6.QtWidgets"] = qtwidgets


class CapturingThread:
    targets = []

    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self):
        CapturingThread.targets.append(self.target)


class DeferredQTimer:
    callbacks = []

    @staticmethod
    def singleShot(*args, **kwargs):
        callback = args[-1] if args else None
        if callable(callback):
            DeferredQTimer.callbacks.append(callback)


def _facade(thread_cls=CapturingThread, qtimer=None):
    return types.SimpleNamespace(
        time=time,
        threading=types.SimpleNamespace(Thread=thread_cls),
        QTimer=qtimer,
        slugify_username=lambda value: str(value or "").strip().lower(),
        runtime_status_is_technical_failure=lambda status: False,
        runtime_status_awaits_evidence=lambda status: False,
        runtime_status_key=lambda status, active=False, restricted=False: f"status:{status}:{active}:{restricted}",
        runtime_status_detail_key=lambda status: "",
        runtime_decision_key=lambda decision: f"decision:{decision}",
        runtime_policy_display_fields=lambda *args, **kwargs: {},
        MAX_ENROLLMENT_SESSIONS=5,
        MIN_ENROLLMENT_SESSIONS=3,
    )


class AsyncDashboardBridge:
    DASHBOARD_SNAPSHOT_ACTIVE_SEC = 4.0
    DASHBOARD_SNAPSHOT_IDLE_SEC = 60.0
    DASHBOARD_SNAPSHOT_BACKGROUND_SEC = 60.0
    HISTORY_POST_STOP_REFRESH_MS = 300

    def __init__(self, flow: str = "idle") -> None:
        self._current_user = {"user_id": "alice"}
        self._profile = {}
        self._sessions = []
        self._runtime_state = {"flow": flow}
        self._status_message = ""
        self._status_tone = "info"
        self._dashboard_snapshot_cache = {}
        self._dashboard_snapshot_user = ""
        self._dashboard_snapshot_cached_at = 0.0
        self._dashboard_snapshot_refresh_enabled = True
        self._dashboard_snapshot_refresh_inflight = False
        self._dashboard_snapshot_refresh_user = ""
        self._dashboard_snapshot_refresh_force = False
        self._dashboard_snapshot_refresh_requested_at = 0.0
        self._dashboard_snapshot_refresh_generation = 0
        self._dashboard_snapshot_result = None
        self._dashboard_snapshot_result_user = ""
        self._dashboard_snapshot_result_error = ""
        self._dashboard_snapshot_result_completed_at = 0.0
        self._dashboard_snapshot_result_generation = 0
        self._dashboard_snapshot_applied_generation = 0
        self._dashboard_snapshot_result_lock = threading.Lock()
        self._dashboard_snapshot_active_workers = {}
        self._dashboard_snapshot_result_duration_ms = 0
        self._dashboard_snapshot_loading = False
        self._dashboard_snapshot_stale = False
        self._dashboard_snapshot_updating = False
        self._dashboard_last_refresh_duration_ms = 0
        self._dashboard_last_snapshot_duration_ms = 0
        self._dashboard_last_refresh_error = ""
        self._dashboard_last_refresh_reason = ""
        self._dashboard_last_refresh_completed_at = 0.0
        self._last_dashboard_snapshot_timing = {}
        self._refresh_inflight = False
        self._refresh_requested = False
        self._refresh_requested_force = False
        self._refresh_requested_reason = ""
        self._refresh_debounce_pending = False
        self._refresh_debounce_force = False
        self._refresh_debounce_reason = ""
        self._refresh_active_reason = ""
        self._refresh_active_coalesced = False
        self._refresh_followup_scheduled = False
        self._training_in_progress = False
        self._background = False
        self._history_sync_pending = False
        self._history_sync_deadline = 0.0
        self._history_sync_hard_deadline = 0.0
        self._history_sync_status = ""
        self._history_sync_warning = ""
        self._shadow_status = {"phase": "collecting", "ready": False, "suggestion_pending": False}
        self._pending_logger_start = False
        self._pending_monitor_start = False
        self._shadow_worker_running = False
        self.profileChanged = DummySignal()
        self.sessionsChanged = DummySignal()
        self.runtimeStateChanged = DummySignal()
        self.statusChanged = DummySignal()
        self.controlsChanged = DummySignal()
        self.dashboardStateChanged = DummySignal()

    def _t(self, key, **kwargs):
        if kwargs:
            return f"{key}:{kwargs}"
        return key

    def _session_flow(self, state):
        return str((state or {}).get("flow") or "idle")

    def _dashboard_snapshot_ttl_sec(self):
        return runtime_helpers.dashboard_snapshot_ttl_sec(self)

    def _dashboard_snapshot(self, user_id, *, force=False):
        return dashboard_helpers.dashboard_snapshot(self, user_id, force=force)

    def _update_dashboard(self):
        return dashboard_helpers.update_dashboard(self)

    def _build_runtime_state_view(self, state):
        return dashboard_helpers.build_runtime_state_view(self, state)

    def _build_profile_view(self, profile):
        return dashboard_helpers.build_profile_view(self, profile)

    def _status_for_dashboard(self, profile, runtime_state):
        return dashboard_helpers.status_for_dashboard(self, profile, runtime_state)

    def _sync_history_after_archive(self, user_id, runtime_view, profile_view, sessions_view):
        return profile_view, sessions_view

    def _set_status(self, message, tone="info"):
        return runtime_helpers.set_status(self, message, tone)

    def _emit_controls_changed(self, *, runtime_changed=False, profile_changed=False, controls_changed=True):
        return runtime_helpers.emit_controls_changed(self, runtime_changed=runtime_changed, profile_changed=profile_changed, controls_changed=controls_changed)

    def _invalidate_dashboard_snapshot_cache(self):
        return runtime_helpers.invalidate_dashboard_snapshot_cache(self)

    def _dashboard_state(self):
        return runtime_helpers.dashboard_state_payload(self)

    def _active_state_for_current_user(self):
        return dict(self._runtime_state)

    def _cleanup_processes(self):
        pass

    def _maybe_finish_pending_logger_start(self):
        pass

    def _maybe_finish_pending_monitor_start(self):
        pass

    def _maybe_autostart_protection(self):
        return False

    def _maybe_process_shadow_session(self):
        pass

    def _maybe_process_shadow_backlog(self):
        pass

    def _consume_shadow_status_result(self):
        return None

    def _should_refresh_shadow_status(self):
        return False

    def _check_shadow_suggestion(self, shadow_status):
        pass

    def _refresh_shadow_status(self, shadow_status=None):
        pass

    def _handle_state_alerts(self):
        pass

    def _maybe_resume_protection_after_unlock(self, state):
        return False

    def _update_refresh_timer(self, *, force=False):
        pass

    def requestRefresh(self, reason="manual", force=False):
        return runtime_helpers.request_refresh(self, reason=reason, force=force)

    def refreshNow(self):
        return runtime_helpers.refresh_now(self)


def _install_facade(monkeypatch, thread_cls=CapturingThread, qtimer=None):
    CapturingThread.targets.clear()
    facade = _facade(thread_cls, qtimer=qtimer)
    monkeypatch.setattr(dashboard_helpers, "_facade", lambda: facade)
    monkeypatch.setattr(runtime_helpers, "_facade", lambda: facade)
    return facade




def _install_auth_mixin_shared_stub():
    import sys

    shared = types.ModuleType("bridge.shared")

    def Slot(*args, **kwargs):
        def decorate(func):
            return func
        return decorate

    shared.Slot = Slot
    shared.verify_user = lambda username, password: {"ok": False}
    shared.cleanup_old_backups = lambda user_id: None
    shared.translate_backend_result = lambda language, result, default_message="", default_key="": default_message or default_key
    shared.user_requires_onboarding = lambda user: False
    for name in (
        "change_password",
        "create_user",
        "delete_user_account",
        "delete_user_data",
        "dismiss_shadow_suggestion",
        "generate_password_recovery_code",
        "lookup_username_hint_by_email",
        "reset_password_with_recovery",
        "reveal_username_by_email",
        "promote_shadow_model",
        "reset_user_profile",
        "user_profile_status",
        "clear_persistent_login",
        "remember_user",
        "restore_remembered_user",
        "verify_password_reset_recovery",
    ):
        setattr(shared, name, lambda *args, **kwargs: {"ok": True})
    previous_shared = sys.modules.get("bridge.shared")
    previous_auth = sys.modules.pop("bridge.auth_mixin", None)
    sys.modules["bridge.shared"] = shared
    return previous_shared, previous_auth


def _restore_auth_mixin_shared_stub(previous_shared, previous_auth):
    import sys

    sys.modules.pop("bridge.auth_mixin", None)
    if previous_auth is not None:
        sys.modules["bridge.auth_mixin"] = previous_auth
    if previous_shared is not None:
        sys.modules["bridge.shared"] = previous_shared
    else:
        sys.modules.pop("bridge.shared", None)


def test_refresh_now_returns_quickly_when_dashboard_compute_is_slow(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")
    called = {"compute": False}

    def slow_compute(self, user_id):
        called["compute"] = True
        time.sleep(1.0)
        return {"profile": {"session_count": 1}, "sessions": []}

    monkeypatch.setattr(dashboard_helpers, "_compute_dashboard_snapshot", slow_compute)

    started = time.perf_counter()
    bridge.refreshNow()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.2
    assert called["compute"] is False
    assert len(CapturingThread.targets) == 1
    assert bridge._last_dashboard_snapshot_timing["cache_hit"] is False


def test_dashboard_snapshot_uses_async_worker_even_when_flow_is_idle(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")
    monkeypatch.setattr(
        dashboard_helpers,
        "_compute_dashboard_snapshot",
        lambda self, user_id: (_ for _ in ()).throw(AssertionError("sync compute should not run")),
    )

    snapshot = dashboard_helpers.dashboard_snapshot(bridge, "alice")

    assert snapshot == {"profile": {}, "sessions": []}
    assert len(CapturingThread.targets) == 1
    assert bridge._dashboard_snapshot_refresh_inflight is True
    assert bridge._dashboard_snapshot_refresh_user == "alice"


def test_cached_dashboard_snapshot_returns_immediately(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")
    cached = {"profile": {"session_count": 1, "ready": True}, "sessions": [{"session_id": "s1"}]}
    bridge._dashboard_snapshot_cache = cached
    bridge._dashboard_snapshot_user = "alice"
    bridge._dashboard_snapshot_cached_at = time.time()
    monkeypatch.setattr(
        dashboard_helpers,
        "_compute_dashboard_snapshot",
        lambda self, user_id: (_ for _ in ()).throw(AssertionError("cached path should not compute")),
    )

    started = time.perf_counter()
    snapshot = dashboard_helpers.dashboard_snapshot(bridge, "alice")
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert snapshot == cached
    assert CapturingThread.targets == []
    assert bridge._last_dashboard_snapshot_timing["cache_hit"] is True
    assert bridge._last_dashboard_snapshot_timing["session_count"] == 1


def test_worker_completion_updates_cache_and_emits_dashboard_signals(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")
    result = {
        "profile": {"session_count": 1, "ready": True, "training_can_start": True},
        "sessions": [{"session_id": "s1", "created_at": "2026-04-01 10:00:00"}],
    }
    monkeypatch.setattr(dashboard_helpers, "_compute_dashboard_snapshot", lambda self, user_id: result)

    dashboard_helpers.update_dashboard(bridge)
    assert len(CapturingThread.targets) == 1
    bridge.profileChanged.count = 0
    bridge.sessionsChanged.count = 0
    bridge.runtimeStateChanged.count = 0

    CapturingThread.targets.pop(0)()
    dashboard_helpers.update_dashboard(bridge)

    assert bridge._dashboard_snapshot_cache == result
    assert bridge._profile["session_count"] == 1
    assert bridge._sessions == result["sessions"]
    assert bridge.profileChanged.count >= 1
    assert bridge.sessionsChanged.count >= 1


def test_sign_in_and_logout_do_not_synchronously_compute_dashboard_snapshot(monkeypatch):
    _install_facade(monkeypatch)
    previous_shared, previous_auth = _install_auth_mixin_shared_stub()
    import bridge.auth_mixin as auth_mixin

    bridge = AsyncDashboardBridge(flow="idle")
    bridge.currentUserChanged = DummySignal()
    bridge.authenticatedChanged = DummySignal()
    bridge.onboardingChanged = DummySignal()
    bridge.shadowChanged = DummySignal()
    bridge.passcodeSetupPromptChanged = DummySignal()
    bridge._remember_current_user = lambda: None
    bridge._clear_remembered_user = lambda: None
    bridge._reset_shadow_runtime_flags = lambda: bridge.shadowChanged.emit()
    bridge._clear_stale_runtime_state = lambda: None
    bridge._reset_app_passcode_runtime = lambda *args, **kwargs: None
    bridge._record_ui_activity = lambda: None
    bridge._show_new_user_onboarding_if_needed = lambda user: None
    bridge.stopCurrentSession = lambda silent=False: None
    bridge._clear_pending_monitor_start = lambda: None
    bridge._emit_all = lambda: None
    bridge._onboarding_visible = False
    bridge._onboarding_mode = "consent"
    bridge._pending_onboarding_do_not_show_again = False
    bridge._pending_onboarding_tour_skipped = False
    bridge._pending_new_account_passcode_prompt = False
    bridge._passcode_setup_prompt_visible = False
    monkeypatch.setattr(auth_mixin, "verify_user", lambda username, password: {"ok": True, "user": {"user_id": "alice", "username": username}})
    monkeypatch.setattr(auth_mixin, "cleanup_old_backups", lambda user_id: None)
    monkeypatch.setattr(
        dashboard_helpers,
        "_compute_dashboard_snapshot",
        lambda self, user_id: (_ for _ in ()).throw(AssertionError("sign-in/logout must not sync compute dashboard")),
    )

    started = time.perf_counter()
    auth_mixin.AuthMixin.signIn(bridge, "alice", "correct horse battery staple")
    sign_in_elapsed = time.perf_counter() - started

    assert sign_in_elapsed < 0.2
    assert len(CapturingThread.targets) == 1

    started = time.perf_counter()
    auth_mixin.AuthMixin.logout(bridge)
    logout_elapsed = time.perf_counter() - started

    assert logout_elapsed < 0.2
    assert bridge._current_user is None
    _restore_auth_mixin_shared_stub(previous_shared, previous_auth)
