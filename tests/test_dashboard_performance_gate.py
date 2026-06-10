from __future__ import annotations

import json
import time
from pathlib import Path

import bridge.refresh_dashboard_helpers as dashboard_helpers
import bridge.refresh_runtime_helpers as runtime_helpers
from tests.test_dashboard_async_idle_refresh import AsyncDashboardBridge, CapturingThread, DeferredQTimer, _install_facade
from tests.test_dashboard_timing_instrumentation import _install_fake_secret_backend


FAST_REFRESH_LIMIT_SEC = 0.200
CACHED_REFRESH_LIMIT_SEC = 0.050
INDEX_HOT_LIMIT_SEC = 0.025
FAST_SNAPSHOT_COLD_LIMIT_SEC = 0.250


def _fake_index_entries(tmp_path: Path, count: int) -> list[dict]:
    entries: list[dict] = []
    for index in range(count):
        # Keep generated paths deterministic and metadata-only. The dashboard
        # fast path should not need raw biometric files or per-session metadata
        # reads when the index is supplied.
        kind = "enrollment" if index % 3 != 0 else "protected"
        created_minute = index % 60
        entries.append(
            {
                "path": str(tmp_path / "sessions" / "authorized" / f"alice_{kind}_legit_s{index:04d}"),
                "session_id": f"s{index:04d}",
                "user_id": "alice",
                "safe_user": "alice",
                "created_at": f"2026-04-28 10:{created_minute:02d}:00",
                "mtime": 1777380000.0 + index,
                "session_kind": kind,
                "decision": "legit",
                "bucket": "accepted",
                "duration_seconds": 72,
                "keyboard_rows": 120,
                "mouse_rows": 140,
                "training_eligible": kind == "enrollment",
                "metadata_trusted": True,
                "metadata_integrity": "verified",
                "metadata_inferred": False,
                "metadata_diagnostic": "",
                "index_schema_version": 1,
                "path_mtime_ns": 1,
                "path_size": 0,
                "metadata_mtime_ns": 1,
                "metadata_size": 128,
            }
        )
    return entries


def _snapshot_kwargs(tmp_path: Path, entries: list[dict], calls: dict[str, int] | None = None) -> dict:
    calls = calls if isinstance(calls, dict) else {"index": 0, "dirs": 0, "metadata": 0}
    model_dir = tmp_path / "models" / "alice"
    model_paths = {"model": str(model_dir / "model.pkl"), "metadata": str(model_dir / "metadata.json")}

    def list_index_entries(*, timing_collector=None):
        calls["index"] = calls.get("index", 0) + 1
        if isinstance(timing_collector, dict):
            timing_collector["session_index_hit"] = True
            timing_collector["session_index_rebuild"] = False
            timing_collector["session_index_count"] = len(entries)
            timing_collector["session_index_ms"] = 0
        return list(entries)

    return {
        "include_training_selection_details": False,
        "session_detail_limit": 10,
        "list_session_index_entries_fn": list_index_entries,
        "resolve_active_runtime_paths_fn": lambda safe: None,
        "validate_runtime_bundle_for_activation_fn": lambda runtime_paths: {"ok": False, "reason": "runtime_pointer_missing", "metadata": None},
        "active_runtime_pointer_path_fn": lambda safe: str(model_dir / "active_runtime.json"),
        "user_model_paths_fn": lambda safe: dict(model_paths),
        "user_model_dir_fn": lambda safe: str(model_dir),
        "_calls": calls,
    }


def _build_dashboard_snapshot(tmp_path: Path, count: int):
    _install_fake_secret_backend()
    from metadata_core.dashboard import build_user_dashboard_snapshot

    entries = _fake_index_entries(tmp_path, count)
    calls = {"index": 0, "dirs": 0, "metadata": 0}
    kwargs = _snapshot_kwargs(tmp_path, entries, calls)
    kwargs_without_private = {key: value for key, value in kwargs.items() if not key.startswith("_")}
    timing: dict[str, object] = {}
    started = time.perf_counter()
    snapshot = build_user_dashboard_snapshot("alice", timing_collector=timing, **kwargs_without_private)
    elapsed = time.perf_counter() - started
    return snapshot, timing, calls, elapsed


def test_refresh_now_does_not_wait_for_slow_dashboard_computation(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")
    compute_called = {"value": False}

    def slow_compute(self, user_id):
        compute_called["value"] = True
        time.sleep(0.5)
        return {"profile": {"session_count": 1}, "sessions": []}

    monkeypatch.setattr(dashboard_helpers, "_compute_dashboard_snapshot", slow_compute)

    started = time.perf_counter()
    bridge.refreshNow()
    elapsed = time.perf_counter() - started

    assert elapsed < FAST_REFRESH_LIMIT_SEC
    assert compute_called["value"] is False
    assert len(CapturingThread.targets) == 1
    assert bridge._dashboard_state()["loading"] is True


def test_cached_dashboard_refresh_is_under_50ms(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")
    bridge._dashboard_snapshot_cache = {"profile": {"session_count": 1, "ready": True}, "sessions": [{"session_id": "cached"}]}
    bridge._dashboard_snapshot_user = "alice"
    bridge._dashboard_snapshot_cached_at = time.time()
    monkeypatch.setattr(
        dashboard_helpers,
        "_compute_dashboard_snapshot",
        lambda self, user_id: (_ for _ in ()).throw(AssertionError("cached refresh should not compute dashboard")),
    )

    started = time.perf_counter()
    bridge.refreshNow()
    elapsed = time.perf_counter() - started

    assert elapsed < CACHED_REFRESH_LIMIT_SEC
    assert bridge._sessions == [{"session_id": "cached"}]
    assert CapturingThread.targets == []
    assert bridge._last_dashboard_snapshot_timing["cache_hit"] is True


def test_dashboard_fast_snapshot_generated_session_counts(tmp_path):
    for count in (0, 10, 100, 1000):
        snapshot, timing, calls, elapsed = _build_dashboard_snapshot(tmp_path / f"case_{count}", count)
        expected_visible = min(10, count)
        assert elapsed < FAST_SNAPSHOT_COLD_LIMIT_SEC
        assert calls["index"] == 1
        assert calls["dirs"] == 0
        assert calls["metadata"] == 0
        assert len(snapshot["sessions"]) == expected_visible
        assert snapshot["profile"]["history_session_count"] == count
        assert snapshot["profile"]["history_visible_session_count"] == expected_visible
        assert timing["session_index_hit"] is True
        assert timing["session_index_rebuild"] is False
        assert timing["metadata_reads_ms"] == 0
        assert timing["dashboard_snapshot_mode"] == ("fast" if count > expected_visible else "full")


def _patch_sessions_root(monkeypatch, tmp_path: Path) -> Path:
    from metadata_core import sessions

    root = tmp_path / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sessions.paths, "sessions_dir", lambda: str(root))
    sessions.invalidate_session_discovery_cache()
    return root


def _write_session(root: Path, index: int) -> None:
    folder = root / "authorized" / f"alice_enrollment_legit_s{index:04d}"
    folder.mkdir(parents=True, exist_ok=True)
    metadata = {
        "session_id": f"s{index:04d}",
        "user_id": "alice",
        "session_kind": "enrollment",
        "archive_label": "legit",
        "final_decision": "legit",
        "bucket": "accepted",
        "created_at": f"2026-04-28 10:{index % 60:02d}:00",
        "duration_seconds": 72,
        "keyboard_rows": 120,
        "mouse_rows": 140,
        "training_eligible": True,
        "metadata_trusted": True,
        "metadata_integrity": "verified",
    }
    (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def test_session_index_hot_path_under_25ms_for_1000_sessions(tmp_path, monkeypatch):
    _install_fake_secret_backend()
    from metadata_core import sessions

    root = _patch_sessions_root(monkeypatch, tmp_path)
    index_path = root / sessions.SESSION_INDEX_FILENAME
    entries = _fake_index_entries(root, 1000)
    payload = {
        "version": sessions.SESSION_INDEX_VERSION,
        "kind": "bioauth_session_index",
        "base_dir": str(root.resolve()),
        "built_at": time.time(),
        "parent_signature": sessions._parent_signature(str(root)),
        "entries": entries,
    }
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    # Prime the file-signature memory cache, then measure the hot indexed path
    # used by repeated dashboard refreshes.
    assert len(sessions.list_session_index_entries()) == 1000

    timing: dict[str, object] = {}
    started = time.perf_counter()
    indexed_entries = sessions.list_session_index_entries(timing_collector=timing)
    elapsed = time.perf_counter() - started

    assert len(indexed_entries) == 1000
    assert timing["session_index_hit"] is True
    assert timing["session_index_rebuild"] is False
    assert elapsed < INDEX_HOT_LIMIT_SEC


def test_missing_or_rebuilt_session_index_does_not_block_refresh_now(monkeypatch):
    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")

    monkeypatch.setattr(
        dashboard_helpers,
        "_compute_dashboard_snapshot",
        lambda self, user_id: (_ for _ in ()).throw(AssertionError("index rebuild/dashboard compute must run only in worker")),
    )

    started = time.perf_counter()
    bridge.refreshNow()
    elapsed = time.perf_counter() - started

    assert elapsed < FAST_REFRESH_LIMIT_SEC
    assert len(CapturingThread.targets) == 1
    assert bridge._dashboard_snapshot_refresh_inflight is True


def test_worker_coalescing_prevents_duplicate_dashboard_refresh_work(monkeypatch):
    DeferredQTimer.callbacks.clear()
    _install_facade(monkeypatch, qtimer=DeferredQTimer)
    bridge = AsyncDashboardBridge(flow="idle")
    calls = {"dashboard": 0}
    bridge._update_dashboard = lambda: calls.__setitem__("dashboard", calls["dashboard"] + 1)

    runtime_helpers.request_refresh(bridge, reason="history:delete", force=False)
    runtime_helpers.request_refresh(bridge, reason="training:finished", force=False)
    runtime_helpers.request_refresh(bridge, reason="settings:updated", force=False)

    assert calls["dashboard"] == 0
    assert len(DeferredQTimer.callbacks) == 1
    DeferredQTimer.callbacks.pop(0)()
    assert calls["dashboard"] == 1
