from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_benchmark_stubs() -> None:
    # The source archive used in CI may omit optional utility packages that are
    # provided by the full desktop runtime. Keep this debug benchmark runnable
    # by installing only the minimal identity helper needed by dashboard code.
    try:
        import utils.identity  # type: ignore  # noqa: F401
        return
    except Exception:
        import types

        utils_pkg = types.ModuleType("utils")
        identity_mod = types.ModuleType("utils.identity")
        identity_mod.slugify_username = lambda value: str(value or "").strip().lower().replace(" ", "-")
        sys.modules.setdefault("utils", utils_pkg)
        sys.modules["utils.identity"] = identity_mod
    if "features" not in sys.modules:
        import types

        features_mod = types.ModuleType("features")
        features_mod.DEFAULT_MIN_WINDOW_EVENTS = 10
        features_mod.DEFAULT_WINDOW_SECONDS = 30.0
        features_mod.DEFAULT_WINDOW_STEP_SECONDS = 15.0
        sys.modules["features"] = features_mod
    if "deep_runtime" not in sys.modules:
        import types

        deep_runtime_mod = types.ModuleType("deep_runtime")
        deep_runtime_mod.build_deep_runtime_metadata_contract = lambda: {"enabled": False, "sequence_model": {}}
        sys.modules["deep_runtime"] = deep_runtime_mod
    if "security" not in sys.modules:
        import types

        security_mod = types.ModuleType("security")
        security_mod.atomic_write_text = lambda path, text: Path(path).write_text(text, encoding="utf-8")
        security_mod.verify_metadata_hash = lambda path: False
        sys.modules["security"] = security_mod


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


def _index_entry(root: Path, index: int) -> dict[str, Any]:
    return {
        "path": str(root / "authorized" / f"alice_enrollment_legit_s{index:04d}"),
        "session_id": f"s{index:04d}",
        "user_id": "alice",
        "safe_user": "alice",
        "created_at": f"2026-04-28 10:{index % 60:02d}:00",
        "mtime": 1777380000.0 + index,
        "session_kind": "enrollment",
        "decision": "legit",
        "bucket": "accepted",
        "duration_seconds": 72,
        "keyboard_rows": 120,
        "mouse_rows": 140,
        "training_eligible": True,
        "metadata_trusted": True,
        "metadata_integrity": "verified",
        "metadata_inferred": False,
        "metadata_diagnostic": "",
        "index_schema_version": 1,
        "dir_mtime_ns": 1,
        "dir_size": 0,
        "metadata_mtime_ns": 1,
        "metadata_size": 128,
        "metadata_hash_mtime_ns": 0,
        "metadata_hash_size": 0,
    }


def _write_direct_index(sessions_module: Any, root: Path, count: int) -> None:
    payload = {
        "version": sessions_module.SESSION_INDEX_VERSION,
        "kind": "bioauth_session_index",
        "base_dir": str(root.resolve()),
        "built_at": time.time(),
        "parent_signature": sessions_module._parent_signature(str(root)),
        "entries": [_index_entry(root, index) for index in range(count)],
    }
    (root / sessions_module.SESSION_INDEX_FILENAME).write_text(json.dumps(payload), encoding="utf-8")


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def run(count: int) -> dict[str, Any]:
    _install_benchmark_stubs()
    from metadata_core import sessions
    from metadata_core.dashboard import build_user_dashboard_snapshot

    with tempfile.TemporaryDirectory(prefix="bioauth-dashboard-perf-") as tmp:
        root = Path(tmp) / "sessions"
        root.mkdir(parents=True, exist_ok=True)
        original_sessions_dir = sessions.paths.sessions_dir
        sessions.paths.sessions_dir = lambda: str(root)
        try:
            sessions.invalidate_session_discovery_cache()
            seeded_direct_index = count > 250
            if seeded_direct_index:
                _write_direct_index(sessions, root, count)
                rebuild_ms = None
                # Prime the in-memory file-signature cache so index_hit_ms
                # represents the normal repeated-refresh hot path.
                sessions.list_session_index_entries()
            else:
                for index in range(count):
                    _write_session(root, index)
                started = time.perf_counter()
                sessions.rebuild_session_index()
                rebuild_ms = _elapsed_ms(started)

            timing: dict[str, Any] = {}
            started = time.perf_counter()
            indexed = sessions.list_session_index_entries(timing_collector=timing)
            index_hit_ms = _elapsed_ms(started)

            model_root = Path(tmp) / "models" / "alice"
            model_paths = {"model": str(model_root / "model.pkl"), "metadata": str(model_root / "metadata.json")}
            dashboard_timing: dict[str, Any] = {}
            started = time.perf_counter()
            snapshot = build_user_dashboard_snapshot(
                "alice",
                include_training_selection_details=False,
                session_detail_limit=10,
                timing_collector=dashboard_timing,
                resolve_active_runtime_paths_fn=lambda safe: None,
                validate_runtime_bundle_for_activation_fn=lambda runtime_paths: {"ok": False, "reason": "runtime_pointer_missing", "metadata": None},
                active_runtime_pointer_path_fn=lambda safe: str(model_root / "active_runtime.json"),
                user_model_paths_fn=lambda safe: dict(model_paths),
                user_model_dir_fn=lambda safe: str(model_root),
            )
            dashboard_ms = _elapsed_ms(started)
            return {
                "session_count": count,
                "index_entries": len(indexed),
                "visible_sessions": len(snapshot.get("sessions") or []),
                "rebuild_ms": rebuild_ms,
                "seeded_direct_index": seeded_direct_index,
                "index_hit_ms": index_hit_ms,
                "dashboard_ms": dashboard_ms,
                "index_timing": timing,
                "dashboard_timing": dashboard_timing,
            }
        finally:
            sessions.paths.sessions_dir = original_sessions_dir
            sessions.invalidate_session_discovery_cache()


def main() -> int:
    parser = argparse.ArgumentParser(description="BioAuth dashboard performance smoke gate")
    parser.add_argument("--counts", default="0,10,100,1000", help="Comma-separated generated session counts")
    args = parser.parse_args()
    counts = [int(item.strip()) for item in str(args.counts).split(",") if item.strip()]
    payload = [run(count) for count in counts]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
