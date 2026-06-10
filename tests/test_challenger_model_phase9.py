from __future__ import annotations

import json
from pathlib import Path
import artifact_integrity

import model_training

from tests.test_context_models_phase5 import (
    _configure_runtime,
    _generate_keyboard_rows,
    _generate_mouse_rows,
    _reload_modules,
    _write_archived_session,
)


def test_train_user_model_persists_challenger_classifier_metadata_and_report(tmp_path, monkeypatch):
    _configure_runtime(tmp_path, monkeypatch)
    security, model_metadata, auth, model_training, model_inference, _model_evaluation = _reload_modules()

    auth.CREATE_USER_COOLDOWN_SECONDS = 0
    auth.CREATE_USER_MAX_IN_WINDOW = 99
    assert auth.create_user("alice", "Password1234", "Alice")["ok"] is True

    alice_keys = ["k_a", "k_s", "k_d", "k_f"]
    intruder_keys = ["k_j", "k_k", "k_l", "k_i"]

    enrollment_specs = [
        ("e1", 128, 0.08, 0.18, 20, 3, 2, 0.50, 1),
        ("e2", 122, 0.09, 0.19, 18, 3, 2, 0.47, 2),
        ("e3", 126, 0.08, 0.20, 22, 3, 2, 0.45, 3),
        ("e4", 118, 0.09, 0.21, 24, 3, 2, 0.44, 4),
    ]
    for session_id, pair_count, dwell, gap, move_count, step_x, step_y, mouse_gap, mtime in enrollment_specs:
        _write_archived_session(
            security,
            model_metadata,
            session_id=session_id,
            user_id="alice",
            session_kind="enrollment",
            keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=pair_count, dwell=dwell, gap=gap, keys=alice_keys),
            mouse_rows=_generate_mouse_rows(start=0.04, move_count=move_count, step_x=step_x, step_y=step_y, gap=mouse_gap),
            mtime=mtime,
        )

    target_session = _write_archived_session(
        security,
        model_metadata,
        session_id="p1",
        user_id="alice",
        session_kind="protected",
        keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=28, dwell=0.09, gap=0.62, keys=alice_keys),
        mouse_rows=_generate_mouse_rows(start=0.03, move_count=150, step_x=6, step_y=5, gap=0.16),
        mtime=5,
    )

    negative_specs = [
        ("n1", "bob", "enrollment", 96, 0.10, 0.24, 72, 5, 4, 0.25, 6),
        ("n2", "charlie", "protected", 44, 0.11, 0.72, 128, 7, 5, 0.18, 7),
        ("n3", "dina", "enrollment", 50, 0.10, 0.54, 54, 4, 3, 0.34, 8),
        ("n4", "eric", "protected", 42, 0.12, 0.76, 132, 8, 6, 0.17, 9),
    ]
    for session_id, user_id, session_kind, pair_count, dwell, gap, move_count, step_x, step_y, mouse_gap, mtime in negative_specs:
        _write_archived_session(
            security,
            model_metadata,
            session_id=session_id,
            user_id=user_id,
            session_kind=session_kind,
            keyboard_rows=_generate_keyboard_rows(start=0.0, pair_count=pair_count, dwell=dwell, gap=gap, keys=intruder_keys),
            mouse_rows=_generate_mouse_rows(start=0.06, move_count=move_count, step_x=step_x, step_y=step_y, gap=mouse_gap),
            mtime=mtime,
        )

    result = model_training.train_user_model("alice", min_sessions=2, max_enrollment_sessions=4)
    assert result["ok"] is True
    assert "stronger challenger supervised model" in result["message"]

    paths = model_metadata._user_model_paths("alice")
    metadata = json.loads(Path(paths["metadata"]).read_text(encoding="utf-8"))
    supervised = metadata["supervised_classifier"]
    assert supervised["enabled"] is True
    assert metadata["classifier_family"] in {"random_forest", "lightgbm"}
    assert supervised["selected_family"] == metadata["classifier_family"]
    assert supervised["selection_version"] == "phase9-challenger-v2"
    assert supervised["selection_metric"] == "auc_with_far_frr_guard_then_f1_fallback"
    assert supervised["selection_constraints"]["min_auc_improvement"] == 0.02
    assert "random_forest" in supervised["head_to_head"]
    if supervised["challenger_family"] == "lightgbm":
        assert "lightgbm" in supervised["head_to_head"]

    evaluation = json.loads(Path(paths["evaluation_report"]).read_text(encoding="utf-8"))
    assert evaluation["supervised_classifier"]["enabled"] is True
    assert evaluation["supervised_classifier"]["selected_family"] == metadata["classifier_family"]
    assert "random_forest" in evaluation["supervised_classifier"]["head_to_head"]

    model = artifact_integrity.load_model(str(paths["model"]))
    details = model_inference.predict_from_session_details(
        model=model,
        session_path=str(target_session),
        metadata_file=str(paths["metadata"]),
        classifier_file=str(paths["classifier"]),
        metadata=metadata,
    )
    assert details["status"] in {"ok", "transitioning"}
    assert details["supervised_classifier"]["enabled"] is True
    assert details["supervised_classifier"]["selected_family"] == metadata["classifier_family"]


def test_select_primary_supervised_family_requires_meaningful_auc_margin():
    selected = model_training._select_primary_supervised_family({
        "random_forest": {"auc": 0.80, "f1": 0.70, "far": 0.05, "frr": 0.08},
        "lightgbm": {"auc": 0.812, "f1": 0.76, "far": 0.05, "frr": 0.08},
    })
    assert selected == "random_forest"


def test_select_primary_supervised_family_rejects_challenger_when_far_worsens():
    selected = model_training._select_primary_supervised_family({
        "random_forest": {"auc": 0.80, "f1": 0.70, "far": 0.05, "frr": 0.08},
        "lightgbm": {"auc": 0.84, "f1": 0.78, "far": 0.07, "frr": 0.08},
    })
    assert selected == "random_forest"


def test_select_primary_supervised_family_rejects_challenger_when_frr_worsens():
    selected = model_training._select_primary_supervised_family({
        "random_forest": {"auc": 0.80, "f1": 0.70, "far": 0.05, "frr": 0.08},
        "lightgbm": {"auc": 0.84, "f1": 0.78, "far": 0.05, "frr": 0.11},
    })
    assert selected == "random_forest"


def test_select_primary_supervised_family_allows_challenger_when_margin_and_guards_pass():
    selected = model_training._select_primary_supervised_family({
        "random_forest": {"auc": 0.80, "f1": 0.70, "far": 0.05, "frr": 0.08},
        "lightgbm": {"auc": 0.83, "f1": 0.75, "far": 0.05, "frr": 0.08},
    })
    assert selected == "lightgbm"


def test_select_primary_supervised_family_uses_f1_fallback_only_when_auc_unavailable():
    selected = model_training._select_primary_supervised_family({
        "random_forest": {"auc": None, "f1": 0.70, "far": 0.05, "frr": 0.08},
        "lightgbm": {"auc": None, "f1": 0.73, "far": 0.05, "frr": 0.08},
    })
    assert selected == "lightgbm"
