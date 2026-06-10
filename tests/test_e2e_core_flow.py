from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

from tests.encrypted_session_fixtures import isolate_encrypted_session_runtime, stabilize_fast_training_modules


KB_HEADER = "key,event,timestamp"
MS_HEADER = "x,y,event,timestamp"


def _install_fake_pynput() -> None:
    if "pynput" in sys.modules:
        return
    pynput = types.ModuleType("pynput")
    keyboard = types.ModuleType("pynput.keyboard")
    mouse = types.ModuleType("pynput.mouse")

    class _Listener:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def start(self):
            return self

        def stop(self):
            return None

    keyboard.Listener = _Listener
    mouse.Listener = _Listener
    pynput.keyboard = keyboard
    pynput.mouse = mouse
    sys.modules["pynput"] = pynput
    sys.modules["pynput.keyboard"] = keyboard
    sys.modules["pynput.mouse"] = mouse


def _install_fake_pyside6() -> None:
    if "PySide6" in sys.modules:
        return
    pyside6 = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")
    qtqml = types.ModuleType("PySide6.QtQml")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class _QObject:
        def __init__(self, *args, **kwargs):
            pass

    class _Signal:
        def __init__(self, *args, **kwargs):
            pass
        def emit(self, *args, **kwargs):
            return None
        def connect(self, *args, **kwargs):
            return None

    def _decorator(*args, **kwargs):
        def _wrap(func):
            return func
        return _wrap

    class _QTimer:
        @staticmethod
        def singleShot(*args, **kwargs):
            return None

    class _QUrl:
        def __init__(self, value=""):
            self.value = value

    class _QCoreApplication:
        @staticmethod
        def translate(_context, text):
            return text

    class _QLocale:
        @staticmethod
        def system():
            return _QLocale()

        def name(self):
            return "en_US"

    class _QRunnable:
        def run(self):
            return None

    class _QThreadPool:
        @staticmethod
        def globalInstance():
            return _QThreadPool()

        def start(self, runnable):
            if hasattr(runnable, "run"):
                runnable.run()
            return None

    class _QDesktopServices:
        @staticmethod
        def openUrl(*args, **kwargs):
            return True

    class _QtObject:
        def __init__(self, *args, **kwargs):
            pass
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    qtcore.QObject = _QObject
    qtcore.Property = lambda *args, **kwargs: property(args[-1]) if args and callable(args[-1]) else None
    qtcore.QTimer = _QTimer
    qtcore.QUrl = _QUrl
    qtcore.QCoreApplication = _QCoreApplication
    qtcore.QLocale = _QLocale
    qtcore.QRunnable = _QRunnable
    qtcore.QThreadPool = _QThreadPool
    qtcore.Qt = _QtObject()
    qtcore.Signal = _Signal
    qtcore.Slot = _decorator
    qtgui.QDesktopServices = _QDesktopServices
    qtgui.QIcon = _QtObject
    qtqml.QQmlApplicationEngine = _QtObject
    qtwidgets.QApplication = _QtObject
    qtwidgets.QMenu = _QtObject
    qtwidgets.QSystemTrayIcon = _QtObject
    pyside6.QtCore = qtcore
    pyside6.QtGui = qtgui
    pyside6.QtQml = qtqml
    pyside6.QtWidgets = qtwidgets
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtQml"] = qtqml
    sys.modules["PySide6.QtWidgets"] = qtwidgets


@pytest.fixture()
def runtime_modules(tmp_path, monkeypatch):
    roots = isolate_encrypted_session_runtime(tmp_path, monkeypatch)
    data_root = roots["data_root"]
    models_root = roots["models_root"]

    _install_fake_pynput()
    _install_fake_pyside6()

    import control
    import security
    import artifact_integrity
    import model_metadata
    import model_training
    import model_inference
    import auth
    import logger
    import monitor

    control = importlib.reload(control)
    security = importlib.reload(security)
    artifact_integrity = importlib.reload(artifact_integrity)
    auth = importlib.reload(auth)
    model_metadata = importlib.reload(model_metadata)
    model_training = importlib.reload(model_training)
    stabilize_fast_training_modules(model_training)
    model_inference = importlib.reload(model_inference)
    logger = importlib.reload(logger)
    monitor = importlib.reload(monitor)
    security.reset_security_caches()

    auth.CREATE_USER_COOLDOWN_SECONDS = 0
    auth.CREATE_USER_MAX_IN_WINDOW = 99

    return {
        "tmp_path": tmp_path,
        "data_root": data_root,
        "models_root": models_root,
        "control": control,
        "security": security,
        "artifact_integrity": artifact_integrity,
        "auth": auth,
        "model_metadata": model_metadata,
        "model_training": model_training,
        "model_inference": model_inference,
        "logger": logger,
        "monitor": monitor,
    }


def _generate_keyboard_rows(*, start: float, pair_count: int, dwell: float, gap: float, keys: list[str]) -> list[list[object]]:
    rows: list[list[object]] = []
    ts = float(start)
    for idx in range(pair_count):
        key = keys[idx % len(keys)]
        rows.append([key, "press", round(ts, 4)])
        rows.append([key, "release", round(ts + dwell, 4)])
        ts += gap
    return rows


def _generate_mouse_rows(*, start: float, move_count: int, step_x: int, step_y: int, gap: float) -> list[list[object]]:
    rows: list[list[object]] = []
    ts = float(start)
    x = 100
    y = 200
    for idx in range(move_count):
        x += step_x + (idx % 3)
        y += step_y + ((idx + 1) % 2)
        rows.append([x, y, "move", round(ts, 4)])
        if idx % 8 == 0:
            rows.append([x, y, "click", round(ts + 0.015, 4)])
        ts += gap
    return rows


def _write_live_session(security, keyboard_path: Path, mouse_path: Path, *, keyboard_rows: list[list[object]], mouse_rows: list[list[object]]) -> None:
    security.write_encrypted(str(keyboard_path), [], KB_HEADER)
    security.write_encrypted(str(mouse_path), [], MS_HEADER)
    security.append_encrypted_rows(str(keyboard_path), keyboard_rows, KB_HEADER)
    security.append_encrypted_rows(str(mouse_path), mouse_rows, MS_HEADER)


def _archive_session(runtime_modules, *, session_id: str, user_id: str, session_kind: str, keyboard_rows: list[list[object]], mouse_rows: list[list[object]], decision: str = "legit", stop_reason: str = "control_stop", mtime: int = 0) -> Path:
    logger = runtime_modules["logger"]
    security = runtime_modules["security"]
    keyboard_path = Path(logger.KEYBOARD_FILE)
    mouse_path = Path(logger.MOUSE_FILE)

    _write_live_session(security, keyboard_path, mouse_path, keyboard_rows=keyboard_rows, mouse_rows=mouse_rows)

    logger.ARGS = {
        "legacy": False,
        "user_id": user_id,
        "safe_user": user_id,
        "session_label": decision,
        "session_kind": session_kind,
        "control_name": f"logger_user_{user_id}",
    }
    logger.SESSION_ID = session_id
    logger.SESSION_STARTED_AT = 1000.0 + float(mtime)
    logger.SESSION_STARTED_AT_TEXT = f"2026-04-10 12:{mtime:02d}:00"
    logger._archived = False
    logger._stop_reason = stop_reason

    logger.archive_live_session()

    if decision == "legit":
        archive_dir = Path(logger.AUTHORIZED_ARCHIVE_DIR) / f"{user_id}_{session_kind}_{decision}_{session_id}"
    else:
        archive_dir = Path(logger.REJECTED_ARCHIVE_DIR) / decision / f"{user_id}_{session_kind}_{decision}_{session_id}"
    assert archive_dir.exists()
    if mtime:
        for path in [archive_dir, archive_dir / "metadata.json", archive_dir / "keyboard_log.csv", archive_dir / "mouse_log.csv"]:
            if path.exists():
                path.touch()
        archive_dir.touch()
    return archive_dir


def test_e2e_core_flow_from_logger_archive_to_training_and_monitor(runtime_modules):
    auth = runtime_modules["auth"]
    model_metadata = runtime_modules["model_metadata"]
    model_training = runtime_modules["model_training"]
    model_inference = runtime_modules["model_inference"]
    monitor = runtime_modules["monitor"]
    artifact_integrity = runtime_modules["artifact_integrity"]

    assert auth.create_user("alice", "Password1234", "Alice")["ok"] is True
    assert auth.create_user("bob", "Password1234", "Bob")["ok"] is True

    alice_keys = ["ka", "ks", "kd", "kf", "kg"]
    bob_keys = ["bx", "bc", "bv", "bb", "bn"]

    alice_enrollment_1 = _archive_session(
        runtime_modules,
        session_id="alice_s1",
        user_id="alice",
        session_kind="enrollment",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=150, dwell=0.075, gap=0.25, keys=alice_keys),
        mouse_rows=_generate_mouse_rows(start=0.02, move_count=120, step_x=5, step_y=3, gap=0.25),
        decision="legit",
        mtime=1,
    )
    alice_enrollment_2 = _archive_session(
        runtime_modules,
        session_id="alice_s2",
        user_id="alice",
        session_kind="enrollment",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=152, dwell=0.08, gap=0.255, keys=alice_keys),
        mouse_rows=_generate_mouse_rows(start=0.01, move_count=122, step_x=4, step_y=3, gap=0.255),
        decision="legit",
        mtime=2,
    )
    bob_reference_1 = _archive_session(
        runtime_modules,
        session_id="bob_s1",
        user_id="bob",
        session_kind="enrollment",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=140, dwell=0.22, gap=0.35, keys=bob_keys),
        mouse_rows=_generate_mouse_rows(start=0.04, move_count=112, step_x=12, step_y=8, gap=0.35),
        decision="legit",
        mtime=3,
    )
    bob_reference_2 = _archive_session(
        runtime_modules,
        session_id="bob_s2",
        user_id="bob",
        session_kind="enrollment",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=142, dwell=0.24, gap=0.355, keys=bob_keys),
        mouse_rows=_generate_mouse_rows(start=0.03, move_count=114, step_x=11, step_y=7, gap=0.355),
        decision="legit",
        mtime=4,
    )

    model_metadata.invalidate_session_discovery_cache()
    discovered = model_metadata.list_session_dirs()

    assert str(alice_enrollment_1.resolve()) in discovered
    assert str(alice_enrollment_2.resolve()) in discovered
    assert str(bob_reference_1.resolve()) in discovered
    assert str(bob_reference_2.resolve()) in discovered

    discovered_meta = {Path(path).name: model_metadata.read_session_metadata(path) for path in discovered}
    assert discovered_meta[alice_enrollment_1.name]["training_eligible"] is True
    assert discovered_meta[alice_enrollment_1.name]["archive_group"] == "authorized"
    assert discovered_meta[bob_reference_1.name]["user_id"] == "bob"

    result = model_training.train_user_model("alice", min_sessions=2, max_enrollment_sessions=2)

    assert result["ok"] is True
    assert result["message_key"] == "training_finished_summary"

    profile = model_metadata.user_profile_status("alice")
    assert profile["ready"] is True
    assert profile["session_count"] == 2

    alice_paths = model_metadata._user_model_paths("alice")
    assert Path(alice_paths["model"]).exists()
    assert Path(alice_paths["metadata"]).exists()
    assert Path(alice_paths["classifier"]).exists()

    live_keyboard_rows = _generate_keyboard_rows(start=0.0, pair_count=146, dwell=0.078, gap=0.252, keys=alice_keys)
    live_mouse_rows = _generate_mouse_rows(start=0.02, move_count=116, step_x=5, step_y=3, gap=0.252)
    _write_live_session(
        runtime_modules["security"],
        Path(model_metadata.LIVE_SESSION_DIR) / "keyboard_log.csv",
        Path(model_metadata.LIVE_SESSION_DIR) / "mouse_log.csv",
        keyboard_rows=live_keyboard_rows,
        mouse_rows=live_mouse_rows,
    )

    user_model = artifact_integrity.load_model(alice_paths["model"])
    assert user_model is not None

    inference_details = model_inference.predict_from_session_details(
        user_model,
        model_metadata.LIVE_SESSION_DIR,
        metadata_file=alice_paths["metadata"],
        classifier_file=alice_paths["classifier"],
    )

    assert inference_details["status"] == "ok"
    assert inference_details["window_count"] >= 1
    assert inference_details["final"] in {"legit", "legitimate", "suspicious", "intruder"}

    monitor.EXPECTED_USER = "alice"
    runtime = monitor._load_runtime_model()
    monitor_details = monitor._predict_runtime(runtime)
    assert monitor_details["status"] == "model_unavailable"

    production_paths = model_metadata._user_production_paths("alice")
    production_meta = artifact_integrity.load_metadata(alice_paths["metadata"]) or {}
    production_meta.update({
        "bundle_role": "production",
        "model_status": "approved_for_production",
        "runtime_requires_production_approval": True,
        "evaluation_report_file": production_meta.get("evaluation_report_file") or "evaluation_report.json",
    })
    security = runtime_modules["security"]
    security.atomic_write_bytes(production_paths["model"], Path(alice_paths["model"]).read_bytes())
    security.save_model_hash(production_paths["model"])
    security.atomic_write_text(production_paths["metadata"], __import__("json").dumps(production_meta, indent=2))
    security.save_metadata_hash(production_paths["metadata"])
    if Path(alice_paths["classifier"]).exists():
        security.atomic_write_bytes(production_paths["classifier"], Path(alice_paths["classifier"]).read_bytes())
        artifact_integrity.save_classifier_sidecar(production_paths["classifier"])
    model_metadata.write_active_runtime_pointer("alice", production_paths, source="e2e-test")

    runtime = monitor._load_runtime_model()
    monitor_details = monitor._predict_runtime(runtime)

    assert monitor_details["status"] == "ok"
    assert monitor_details["window_count"] >= 1
    assert monitor_details["final"] == inference_details["final"]
