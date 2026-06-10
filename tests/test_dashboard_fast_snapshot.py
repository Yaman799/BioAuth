from __future__ import annotations

from pathlib import Path

from tests.test_dashboard_timing_instrumentation import _install_fake_secret_backend


def _metadata_fixture(tmp_path: Path, count: int = 12):
    session_paths = []
    metadata = {}
    for idx in range(count):
        kind = "enrollment" if idx < 8 else "protected"
        path = str(tmp_path / f"alice_{kind}_legit_s{idx:03d}")
        session_paths.append(path)
        metadata[path] = {
            "user_id": "alice",
            "session_id": f"s{idx:03d}",
            "created_at": str(1000 + idx),
            "session_kind": kind,
            "final_decision": "legit",
            "archive_label": "legit",
            "bucket": "accepted",
            "training_eligible": True,
            "metadata_trusted": True,
            "metadata_integrity": "verified",
            "duration_seconds": 60,
            "keyboard_rows": 100,
            "mouse_rows": 100,
        }
    return session_paths, metadata


def _snapshot_kwargs(tmp_path: Path, session_paths, metadata):
    model_dir = tmp_path / "models" / "alice"
    pointer_path = model_dir / "active_runtime.json"
    model_paths = {"model": str(model_dir / "model.pkl"), "metadata": str(model_dir / "metadata.json")}
    return {
        "list_session_dirs_fn": lambda: list(session_paths),
        "read_session_metadata_fn": lambda path: dict(metadata[path]),
        "resolve_active_runtime_paths_fn": lambda safe: None,
        "validate_runtime_bundle_for_activation_fn": lambda runtime_paths: {"ok": True, "reason": "unused", "metadata": {}},
        "active_runtime_pointer_path_fn": lambda safe: str(pointer_path),
        "user_model_paths_fn": lambda safe: dict(model_paths),
        "user_model_dir_fn": lambda safe: str(model_dir),
    }


def test_fast_dashboard_snapshot_returns_counts_with_recent_sessions_only(tmp_path):
    _install_fake_secret_backend()
    from metadata_core.dashboard import build_user_dashboard_snapshot

    session_paths, metadata = _metadata_fixture(tmp_path, count=12)
    snapshot = build_user_dashboard_snapshot(
        "alice",
        include_training_selection_details=False,
        session_detail_limit=5,
        **_snapshot_kwargs(tmp_path, session_paths, metadata),
    )

    profile = snapshot["profile"]
    assert len(snapshot["sessions"]) == 5
    assert profile["history_session_count"] == 12
    assert profile["history_visible_session_count"] == 5
    assert profile["history_is_partial"] is True
    assert profile["dashboard_snapshot_mode"] == "fast"
    assert profile["trusted_session_count"] == 8
    assert profile["training_can_start"] is True


def test_full_history_snapshot_returns_all_sessions_when_explicitly_requested(tmp_path):
    _install_fake_secret_backend()
    from metadata_core.dashboard import build_user_dashboard_snapshot, summarize_user_sessions

    session_paths, metadata = _metadata_fixture(tmp_path, count=12)
    kwargs = _snapshot_kwargs(tmp_path, session_paths, metadata)
    snapshot = build_user_dashboard_snapshot(
        "alice",
        include_training_selection_details=True,
        session_detail_limit=None,
        **kwargs,
    )
    summarized = summarize_user_sessions("alice", **kwargs)

    assert len(snapshot["sessions"]) == 12
    assert len(summarized) == 12
    assert snapshot["profile"]["history_loaded"] is True
    assert snapshot["profile"]["history_is_partial"] is False
    assert snapshot["profile"]["dashboard_snapshot_mode"] == "full"


def test_training_eligibility_summary_uses_all_sessions_even_when_recent_list_is_small(tmp_path):
    _install_fake_secret_backend()
    from metadata_core.dashboard import build_user_dashboard_snapshot

    session_paths, metadata = _metadata_fixture(tmp_path, count=20)
    # Make only the oldest enrollment sessions eligible. The latest 5 rows are
    # protected sessions, so the fast visible list alone would be insufficient.
    for path in session_paths[8:]:
        metadata[path]["session_kind"] = "protected"
    snapshot = build_user_dashboard_snapshot(
        "alice",
        include_training_selection_details=False,
        session_detail_limit=5,
        **_snapshot_kwargs(tmp_path, session_paths, metadata),
    )

    assert [item["session_kind"] for item in snapshot["sessions"]] == ["protected"] * 5
    assert snapshot["profile"]["trusted_session_count"] == 8
    assert snapshot["profile"]["training_can_start"] is True
    assert snapshot["profile"]["training_block_reason"] == ""


def test_fast_snapshot_preserves_qml_session_row_keys(tmp_path):
    _install_fake_secret_backend()
    from metadata_core.dashboard import build_user_dashboard_snapshot

    session_paths, metadata = _metadata_fixture(tmp_path, count=3)
    snapshot = build_user_dashboard_snapshot(
        "alice",
        include_training_selection_details=False,
        session_detail_limit=2,
        **_snapshot_kwargs(tmp_path, session_paths, metadata),
    )
    row = snapshot["sessions"][0]

    for key in (
        "path",
        "session_id",
        "created_at",
        "session_kind",
        "decision",
        "bucket",
        "duration_seconds",
        "keyboard_rows",
        "mouse_rows",
        "metadata_trusted",
        "metadata_integrity",
        "training_visibility",
        "training_status_tone",
        "training_counts_toward_minimum",
        "training_selected",
        "training_block_reason",
        "training_reason_detail",
    ):
        assert key in row


def test_large_fast_snapshot_materializes_only_visible_session_rows(tmp_path, monkeypatch):
    _install_fake_secret_backend()
    import metadata_core.dashboard as dashboard

    session_paths, metadata = _metadata_fixture(tmp_path, count=250)
    calls = {"session_view": 0}
    original = dashboard._session_view_from_meta

    def counting_session_view(path, meta):
        calls["session_view"] += 1
        return original(path, meta)

    monkeypatch.setattr(dashboard, "_session_view_from_meta", counting_session_view)
    snapshot = dashboard.build_user_dashboard_snapshot(
        "alice",
        include_training_selection_details=False,
        session_detail_limit=10,
        **_snapshot_kwargs(tmp_path, session_paths, metadata),
    )

    assert len(snapshot["sessions"]) == 10
    assert snapshot["profile"]["history_session_count"] == 250
    assert calls["session_view"] == 10



def test_explicit_full_history_request_updates_bridge_sessions(monkeypatch):
    import bridge.refresh_dashboard_helpers as dashboard_helpers
    from tests.test_dashboard_async_idle_refresh import AsyncDashboardBridge, CapturingThread, _install_facade

    _install_facade(monkeypatch)
    bridge = AsyncDashboardBridge(flow="idle")
    full_sessions = [{"session_id": f"s{i}", "path": f"/tmp/s{i}"} for i in range(12)]
    full_snapshot = {
        "profile": {"history_session_count": 12, "history_visible_session_count": 12, "history_loaded": True},
        "sessions": full_sessions,
    }
    monkeypatch.setattr(dashboard_helpers, "_compute_full_history_snapshot", lambda self, user_id: full_snapshot)
    monkeypatch.setattr(dashboard_helpers, "_compute_dashboard_snapshot", lambda self, user_id: {"profile": {"history_session_count": 12}, "sessions": full_sessions[:5]})

    dashboard_helpers.load_full_history(bridge)
    assert bridge._dashboard_full_history_requested is True
    assert CapturingThread.targets

    CapturingThread.targets.pop(0)()
    dashboard_helpers.update_dashboard(bridge)

    assert bridge._sessions == full_sessions
    assert bridge._profile["history_loaded"] is True
    assert bridge._profile["history_is_partial"] is False
