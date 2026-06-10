from __future__ import annotations

import importlib
import json
from pathlib import Path
import artifact_integrity

from features import classify_behavior_context
from tests.encrypted_session_fixtures import isolate_encrypted_session_runtime, stabilize_fast_training_modules


def _configure_runtime(tmp_path, monkeypatch):
    isolate_encrypted_session_runtime(tmp_path, monkeypatch)



def _reload_modules():
    import auth
    import model_evaluation
    import model_inference
    import model_metadata
    import model_training
    import security
    import feature_extractors
    import feature_extractors.context
    import features
    import training_core.context_models
    import training_core.data
    import training_core.pipeline
    import training_core.selection
    import training_core.supervised

    security = importlib.reload(security)
    feature_extractors.context = importlib.reload(feature_extractors.context)
    feature_extractors = importlib.reload(feature_extractors)
    features = importlib.reload(features)
    training_core.data = importlib.reload(training_core.data)
    training_core.selection = importlib.reload(training_core.selection)
    training_core.context_models = importlib.reload(training_core.context_models)
    training_core.supervised = importlib.reload(training_core.supervised)
    training_core.pipeline = importlib.reload(training_core.pipeline)
    model_metadata = importlib.reload(model_metadata)
    auth = importlib.reload(auth)
    model_training = importlib.reload(model_training)
    stabilize_fast_training_modules(model_training)
    model_inference = importlib.reload(model_inference)
    model_evaluation = importlib.reload(model_evaluation)
    security.reset_security_caches()
    return security, model_metadata, auth, model_training, model_inference, model_evaluation



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
    x = 120
    y = 90
    for idx in range(move_count):
        rows.append([x, y, "move", round(ts, 4)])
        x += step_x
        y += step_y
        ts += gap
        if idx % 9 == 0:
            rows.append([x, y, "click_press", round(ts, 4)])
            ts += gap / 2.0
            rows.append([x, y, "click_release", round(ts, 4)])
            ts += gap / 2.0
    return rows



def _write_archived_session(
    security,
    model_metadata,
    *,
    session_id: str,
    user_id: str,
    session_kind: str,
    keyboard_rows: list[list[object]],
    mouse_rows: list[list[object]],
    mtime: int,
) -> Path:
    base = Path(model_metadata.sessions_dir()) / "authorized" / f"{user_id}_{session_kind}_legit_{session_id}"
    base.mkdir(parents=True, exist_ok=True)
    security.write_encrypted(str(base / "keyboard_log.csv"), keyboard_rows, model_metadata.KB_HEADER)
    security.write_encrypted(str(base / "mouse_log.csv"), mouse_rows, model_metadata.MS_HEADER)

    all_ts = [float(row[-1]) for row in keyboard_rows + mouse_rows] if (keyboard_rows or mouse_rows) else [0.0]
    metadata = {
        "session_id": session_id,
        "user_id": user_id,
        "session_kind": session_kind,
        "final_decision": "legit",
        "archive_label": "legit",
        "archive_group": "authorized",
        "bucket": "authorized",
        "created_at": f"2026-04-10 12:00:{mtime:02d}",
        "started_at": min(all_ts),
        "started_at_text": f"2026-04-10 12:00:{mtime:02d}",
        "duration_seconds": max(all_ts) - min(all_ts),
        "keyboard_rows": len(keyboard_rows),
        "mouse_rows": len(mouse_rows),
        "training_eligible": True,
        "privacy_mode": "hashed_keys",
    }
    (base / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    security.save_metadata_hash(str(base / "metadata.json"))
    import os

    os.utime(base, (mtime, mtime))
    return base



def test_classify_behavior_context_routes_expected_profiles():
    keyboard_sample = {
        "multiscale_scale_coverage": 1.0,
        "multiscale_active_scale_count": 2.0,
        "multiscale_requested_scale_count": 2.0,
        "scale_12s_active": 1.0,
        "scale_12s_requested_seconds": 12.0,
        "scale_12s_window_seconds": 12.0,
        "scale_12s_window_total_events": 160.0,
        "scale_12s_session_events_per_sec": 13.0,
        "scale_12s_session_kb_share": 0.84,
        "scale_12s_session_ms_share": 0.16,
        "scale_12s_session_modality_switch_ratio": 0.12,
    }
    mouse_sample = {
        "multiscale_scale_coverage": 1.0,
        "multiscale_active_scale_count": 2.0,
        "multiscale_requested_scale_count": 2.0,
        "scale_12s_active": 1.0,
        "scale_12s_requested_seconds": 12.0,
        "scale_12s_window_seconds": 12.0,
        "scale_12s_window_total_events": 180.0,
        "scale_12s_session_events_per_sec": 15.0,
        "scale_12s_session_kb_share": 0.18,
        "scale_12s_session_ms_share": 0.82,
        "scale_12s_session_modality_switch_ratio": 0.16,
    }
    short_sample = {
        "multiscale_scale_coverage": 0.5,
        "multiscale_active_scale_count": 1.0,
        "multiscale_requested_scale_count": 2.0,
        "scale_6s_active": 1.0,
        "scale_6s_requested_seconds": 6.0,
        "scale_6s_window_seconds": 5.5,
        "scale_6s_window_total_events": 44.0,
        "scale_6s_session_events_per_sec": 6.5,
        "scale_6s_session_kb_share": 0.52,
        "scale_6s_session_ms_share": 0.48,
        "scale_6s_session_modality_switch_ratio": 0.25,
        "scale_12s_active": 0.0,
        "scale_12s_requested_seconds": 12.0,
    }

    assert classify_behavior_context(keyboard_sample)["context"] == "keyboard_heavy"
    assert classify_behavior_context(mouse_sample)["context"] == "mouse_heavy"
    assert classify_behavior_context(short_sample)["context"] == "short_session"



def test_train_user_model_persists_context_models_and_routes_runtime(tmp_path, monkeypatch):
    _configure_runtime(tmp_path, monkeypatch)
    security, model_metadata, auth, model_training, model_inference, _model_evaluation = _reload_modules()

    auth.CREATE_USER_COOLDOWN_SECONDS = 0
    auth.CREATE_USER_MAX_IN_WINDOW = 99
    created = auth.create_user("alice", "Password1234", "Alice")
    assert created["ok"] is True

    alice_keys = ["k_a", "k_s", "k_d", "k_f"]
    other_keys = ["k_j", "k_k", "k_l", "k_i"]

    _write_archived_session(
        security,
        model_metadata,
        session_id="e1",
        user_id="alice",
        session_kind="enrollment",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=120, dwell=0.08, gap=0.18, keys=alice_keys),
        mouse_rows=_generate_mouse_rows(start=0.04, move_count=18, step_x=3, step_y=2, gap=0.50),
        mtime=1,
    )
    _write_archived_session(
        security,
        model_metadata,
        session_id="e2",
        user_id="alice",
        session_kind="enrollment",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=112, dwell=0.09, gap=0.20, keys=alice_keys),
        mouse_rows=_generate_mouse_rows(start=0.05, move_count=20, step_x=3, step_y=2, gap=0.46),
        mtime=2,
    )
    mouse_heavy_session = _write_archived_session(
        security,
        model_metadata,
        session_id="p1",
        user_id="alice",
        session_kind="protected",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=26, dwell=0.09, gap=0.62, keys=alice_keys),
        mouse_rows=_generate_mouse_rows(start=0.03, move_count=150, step_x=6, step_y=5, gap=0.16),
        mtime=3,
    )
    _write_archived_session(
        security,
        model_metadata,
        session_id="p2",
        user_id="alice",
        session_kind="protected",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=30, dwell=0.10, gap=0.58, keys=alice_keys),
        mouse_rows=_generate_mouse_rows(start=0.02, move_count=142, step_x=5, step_y=4, gap=0.17),
        mtime=4,
    )

    _write_archived_session(
        security,
        model_metadata,
        session_id="n1",
        user_id="bob",
        session_kind="enrollment",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=96, dwell=0.10, gap=0.24, keys=other_keys),
        mouse_rows=_generate_mouse_rows(start=0.04, move_count=72, step_x=5, step_y=4, gap=0.25),
        mtime=5,
    )
    _write_archived_session(
        security,
        model_metadata,
        session_id="n2",
        user_id="charlie",
        session_kind="protected",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=44, dwell=0.11, gap=0.72, keys=other_keys),
        mouse_rows=_generate_mouse_rows(start=0.03, move_count=128, step_x=7, step_y=5, gap=0.18),
        mtime=6,
    )
    _write_archived_session(
        security,
        model_metadata,
        session_id="n3",
        user_id="dina",
        session_kind="enrollment",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=50, dwell=0.10, gap=0.54, keys=other_keys),
        mouse_rows=_generate_mouse_rows(start=0.06, move_count=54, step_x=4, step_y=3, gap=0.34),
        mtime=7,
    )

    result = model_training.train_user_model("alice", min_sessions=2, max_enrollment_sessions=2)
    assert result["ok"] is True
    assert "context-specific routing with global fallback" in result["message"]

    metadata_path = Path(model_metadata._user_model_paths("alice")["metadata"])
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["context_router"]["enabled"] is True
    active_contexts = set(metadata["context_models"]["active_contexts"])
    assert {"keyboard_heavy", "mouse_heavy"}.issubset(active_contexts)

    for context_name in ("keyboard_heavy", "mouse_heavy"):
        bundle = metadata["context_models"]["bundles"][context_name]
        assert (metadata_path.parent / bundle["model"]).exists()
        assert (metadata_path.parent / bundle["metadata"]).exists()

    paths = model_metadata._user_model_paths("alice")
    evaluation_path = Path(paths["evaluation_report"])
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    assert evaluation["context_router"]["enabled"] is True
    assert {"keyboard_heavy", "mouse_heavy"}.issubset(set(evaluation["context_router"]["active_contexts"]))

    model = artifact_integrity.load_model(str(paths["model"]))
    assert model is not None
    details = model_inference.predict_from_session_details(
        model=model,
        session_path=str(mouse_heavy_session),
        metadata_file=str(metadata_path),
        classifier_file=model_metadata._user_model_paths("alice")["classifier"],
        metadata=metadata,
    )

    assert details["status"] == "ok"
    assert details["window_count"] >= 1
    routing = details["context_routing"]
    assert routing["enabled"] is True
    assert routing["used_context_counts"].get("mouse_heavy", 0) >= 1
    assert routing["routed_window_count"] >= 1
