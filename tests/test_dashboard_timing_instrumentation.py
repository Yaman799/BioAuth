from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import types


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _install_if_missing(monkeypatch, name: str, module: types.ModuleType) -> None:
    if name not in sys.modules and not _module_available(name):
        if monkeypatch is None:
            sys.modules[name] = module
        else:
            monkeypatch.setitem(sys.modules, name, module)


def _install_fake_secret_backend(monkeypatch=None) -> None:
    fake = types.ModuleType("bio_platform.secrets")
    fake.get_secret_backend_name = lambda: "test"
    fake.load_or_create_secret = lambda *args, **kwargs: b"0" * 32
    _install_if_missing(monkeypatch, "bio_platform.secrets", fake)

    utils_pkg = types.ModuleType("utils")
    identity_mod = types.ModuleType("utils.identity")
    identity_mod.slugify_username = lambda value: str(value or "").strip().lower().replace(" ", "-")
    if "utils.identity" not in sys.modules and not _module_available("utils.identity"):
        _install_if_missing(monkeypatch, "utils", utils_pkg)
        if monkeypatch is None:
            sys.modules["utils.identity"] = identity_mod
        else:
            monkeypatch.setitem(sys.modules, "utils.identity", identity_mod)

    features_mod = types.ModuleType("features")
    features_mod.DEFAULT_MIN_WINDOW_EVENTS = 10
    features_mod.DEFAULT_WINDOW_SECONDS = 30.0
    features_mod.DEFAULT_WINDOW_STEP_SECONDS = 15.0

    features_mod.TRANSITION_SESSION_START_SECONDS = 2.0
    features_mod.TRANSITION_POST_IDLE_GAP_SECONDS = 30.0
    features_mod.TRANSITION_ACTIVITY_SHIFT_THRESHOLD = 0.35
    features_mod.SEQUENCE_FEATURES_VERSION = "test-sequence-v1"
    features_mod.SEQUENCE_TREND_LOOKBACK = 3
    features_mod.annotate_transition_windows = lambda samples, *args, **kwargs: list(samples or [])
    features_mod.annotate_sequence_trend_windows = lambda samples, *args, **kwargs: list(samples or [])
    features_mod.classify_behavior_context = lambda sample, *args, **kwargs: {"context": "mixed", "confidence": 0.0}
    features_mod.extract_context_router_features = lambda sample, *args, **kwargs: {"context": "mixed", "confidence": 0.0}
    features_mod.extract_keyboard_features = lambda *args, **kwargs: {}
    features_mod.extract_mouse_features = lambda *args, **kwargs: {}
    features_mod.extract_combined_features = lambda *args, **kwargs: {}
    features_mod.extract_window_feature_samples = lambda *args, **kwargs: []
    features_mod.extract_multi_scale_window_feature_samples = lambda *args, **kwargs: []
    features_mod.extract_session_quality_indicators = lambda *args, **kwargs: {"quality_score": 1.0, "accepted": True}
    _install_if_missing(monkeypatch, "features", features_mod)

    paths_mod = types.ModuleType("paths")
    paths_mod.data_dir = lambda: str(Path("/tmp/bioauth-test-data"))
    paths_mod.models_dir = lambda: str(Path("/tmp/bioauth-test-models"))
    paths_mod.control_dir = lambda: str(Path("/tmp/bioauth-test-data/control"))
    paths_mod.settings_file = lambda: str(Path("/tmp/bioauth-test-data/settings.json"))
    paths_mod.users_file = lambda: str(Path("/tmp/bioauth-test-data/users.json"))
    paths_mod.lockouts_file = lambda: str(Path("/tmp/bioauth-test-data/lockouts.json"))
    paths_mod.account_creation_limits_file = lambda: str(Path("/tmp/bioauth-test-data/account_creation_limits.json"))
    paths_mod.remembered_login_file = lambda: str(Path("/tmp/bioauth-test-data/remembered_login.json"))
    paths_mod.sessions_dir = lambda: str(Path("/tmp/bioauth-test-sessions"))
    paths_mod.live_session_dir = lambda: str(Path("/tmp/bioauth-test-live"))
    paths_mod.runtime_base_dir = lambda: str(Path("/tmp/bioauth-test-runtime"))
    _install_if_missing(monkeypatch, "paths", paths_mod)

    deep_runtime_mod = types.ModuleType("deep_runtime")
    deep_runtime_mod.build_deep_runtime_metadata_contract = lambda: {"enabled": False, "sequence_model": {}}
    deep_runtime_mod.resolve_runtime_rollout_state = lambda *_args, **_kwargs: {"production_decision_influence_enabled": False, "effective_mode": "classic"}
    _install_if_missing(monkeypatch, "deep_runtime", deep_runtime_mod)

    security_mod = types.ModuleType("security")
    security_mod.atomic_write_text = lambda path, text: Path(path).write_text(text, encoding="utf-8")
    _install_if_missing(monkeypatch, "security", security_mod)

    pandas_mod = types.ModuleType("pandas")
    class _Timestamp:
        @staticmethod
        def fromtimestamp(value):
            import datetime
            return datetime.datetime.fromtimestamp(float(value))
    pandas_mod.Timestamp = _Timestamp
    _install_if_missing(monkeypatch, "pandas", pandas_mod)


def _dashboard_fixture(tmp_path: Path):
    session_paths = [
        str(tmp_path / "alice_enrollment_legit_s1"),
        str(tmp_path / "bob_enrollment_legit_s2"),
        str(tmp_path / "alice_protected_legit_s3"),
    ]
    metadata = {
        session_paths[0]: {
            "user_id": "alice",
            "session_id": "s1",
            "created_at": "2026-04-01 10:00:00",
            "session_kind": "enrollment",
            "final_decision": "legit",
            "archive_label": "legit",
            "bucket": "accepted",
            "training_eligible": True,
            "metadata_trusted": True,
            "metadata_integrity": "verified",
            "duration_seconds": 60,
            "keyboard_rows": 100,
            "mouse_rows": 100,
        },
        session_paths[1]: {
            "user_id": "bob",
            "session_id": "s2",
            "created_at": "2026-04-02 10:00:00",
            "session_kind": "enrollment",
            "final_decision": "legit",
            "archive_label": "legit",
            "bucket": "accepted",
            "training_eligible": True,
            "metadata_trusted": True,
            "metadata_integrity": "verified",
            "duration_seconds": 60,
            "keyboard_rows": 100,
            "mouse_rows": 100,
        },
        session_paths[2]: {
            "user_id": "alice",
            "session_id": "s3",
            "created_at": "2026-04-03 10:00:00",
            "session_kind": "protected",
            "final_decision": "legit",
            "archive_label": "legit",
            "bucket": "accepted",
            "training_eligible": True,
            "metadata_trusted": True,
            "metadata_integrity": "verified",
            "duration_seconds": 60,
            "keyboard_rows": 100,
            "mouse_rows": 100,
        },
    }
    return session_paths, metadata


def test_dashboard_timing_collector_does_not_change_snapshot_results(tmp_path, monkeypatch):
    _install_fake_secret_backend(monkeypatch)
    from metadata_core.dashboard import build_user_dashboard_snapshot

    session_paths, metadata = _dashboard_fixture(tmp_path)
    model_dir = tmp_path / "models" / "alice"
    pointer_path = model_dir / "active_runtime.json"
    model_paths = {"model": str(model_dir / "model.pkl"), "metadata": str(model_dir / "metadata.json")}

    kwargs = {
        "include_training_selection_details": False,
        "list_session_dirs_fn": lambda: list(session_paths),
        "read_session_metadata_fn": lambda path: dict(metadata[path]),
        "resolve_active_runtime_paths_fn": lambda safe: None,
        "validate_runtime_bundle_for_activation_fn": lambda runtime_paths: {"ok": True, "reason": "unused", "metadata": {}},
        "active_runtime_pointer_path_fn": lambda safe: str(pointer_path),
        "user_model_paths_fn": lambda safe: dict(model_paths),
        "user_model_dir_fn": lambda safe: str(model_dir),
    }

    baseline = build_user_dashboard_snapshot("alice", **kwargs)
    timing = {}
    instrumented = build_user_dashboard_snapshot("alice", timing_collector=timing, **kwargs)

    assert instrumented == baseline
    assert timing["session_count"] == len(instrumented["sessions"])
    for key in (
        "session_dirs_ms",
        "metadata_reads_ms",
        "training_snapshot_ms",
        "runtime_validation_ms",
        "model_metadata_ms",
        "dashboard_total_ms",
    ):
        assert key in timing
        assert isinstance(timing[key], int)
        assert timing[key] >= 0


def test_slow_refresh_payload_includes_dashboard_timing_fields(monkeypatch):
    import bridge.refresh_runtime_helpers as runtime_helpers

    class FakeTime:
        def __init__(self):
            self.value = 1000.0

        def time(self):
            self.value += 0.05
            return self.value

    fake_time = FakeTime()
    monkeypatch.setattr(runtime_helpers, "_facade", lambda: types.SimpleNamespace(time=fake_time))

    captured = []

    class Bridge:
        _current_user = {"user_id": "alice"}
        _runtime_state = {"flow": "idle"}
        _training_in_progress = False
        _status_message = ""
        _shadow_status = {"phase": "collecting"}
        _last_dashboard_snapshot_timing = {
            "session_count": 2,
            "cache_hit": False,
            "session_dirs_ms": 3,
            "metadata_reads_ms": 4,
            "training_snapshot_ms": 5,
            "runtime_validation_ms": 6,
            "model_metadata_ms": 7,
            "dashboard_total_ms": 8,
        }

        def _debug_trace(self, channel, message, payload=None, level="info"):
            captured.append((channel, message, dict(payload or {}), level))

        def _cleanup_processes(self):
            pass

        def _maybe_finish_pending_logger_start(self):
            pass

        def _maybe_finish_pending_monitor_start(self):
            pass

        def _update_dashboard(self):
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

        def _refresh_shadow_status(self, shadow_status):
            pass

        def _handle_state_alerts(self):
            pass

        def _maybe_resume_protection_after_unlock(self, state):
            return False

        def _update_refresh_timer(self):
            pass

        def _session_flow(self, state):
            return str((state or {}).get("flow") or "idle")

    runtime_helpers.refresh_now(Bridge())

    payload = [item[2] for item in captured if item[1] == "Slow refresh cycle completed"][0]
    assert payload["flow"] == "idle"
    assert payload["session_count"] == 2
    assert payload["cache_hit"] is False
    assert payload["session_dirs_ms"] == 3
    assert payload["metadata_reads_ms"] == 4
    assert payload["training_snapshot_ms"] == 5
    assert payload["runtime_validation_ms"] == 6
    assert payload["model_metadata_ms"] == 7
    assert payload["dashboard_total_ms"] == 8
    assert "path" not in payload
    assert "token" not in payload
    assert "passcode" not in payload
