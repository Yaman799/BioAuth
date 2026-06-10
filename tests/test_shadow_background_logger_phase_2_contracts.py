from __future__ import annotations

import os

from paths import control_dir, data_dir, live_session_dir, models_dir, sessions_dir
from shadow_core.background_contracts import (
    shadow_evidence_ledger_path,
    shadow_evidence_paths,
    shadow_evidence_state_path,
    shadow_gate_result_path,
    shadow_logger_key,
    shadow_logger_process_key,
    shadow_logger_stop_control_name,
    shadow_monitor_key,
    shadow_monitor_process_key,
    shadow_monitor_stop_control_name,
)


def test_shadow_logger_key_is_isolated_from_normal_logger_key_for_same_user():
    user = "Alice Example"
    normal_key = "logger_user_alice_example"

    assert shadow_logger_key(user) == "shadow_logger_user_alice_example"
    assert shadow_logger_process_key(user) == shadow_logger_key(user)
    assert shadow_logger_key(user) != normal_key
    assert not shadow_logger_key(user).startswith("logger_user_")


def test_shadow_monitor_key_is_isolated_from_normal_monitor_key():
    user = "Alice Example"

    assert shadow_monitor_key(user) == "shadow_monitor_user_alice_example"
    assert shadow_monitor_process_key(user) == shadow_monitor_key(user)
    assert shadow_monitor_key(user) != "monitor"


def test_shadow_stop_control_names_cannot_collide_with_normal_controls():
    user = "Alice Example"
    normal_logger_control = "logger_user_alice_example"
    normal_monitor_control = "monitor"

    shadow_logger_control = shadow_logger_stop_control_name(user)
    shadow_monitor_control = shadow_monitor_stop_control_name(user)

    assert shadow_logger_control != normal_logger_control
    assert shadow_logger_control != normal_monitor_control
    assert shadow_monitor_control != normal_logger_control
    assert shadow_monitor_control != normal_monitor_control
    assert shadow_logger_control != shadow_monitor_control

    normal_logger_path = os.path.join(control_dir(), f"{normal_logger_control}.json")
    normal_monitor_path = os.path.join(control_dir(), f"{normal_monitor_control}.json")
    shadow_logger_path = os.path.join(control_dir(), f"{shadow_logger_control}.json")
    shadow_monitor_path = os.path.join(control_dir(), f"{shadow_monitor_control}.json")

    assert shadow_logger_path != normal_logger_path
    assert shadow_logger_path != normal_monitor_path
    assert shadow_monitor_path != normal_logger_path
    assert shadow_monitor_path != normal_monitor_path


def test_shadow_evidence_paths_are_isolated_from_training_and_runtime_state():
    user = "Alice Example"
    paths = shadow_evidence_paths(user)

    assert paths["state"] == shadow_evidence_state_path(user)
    assert paths["ledger"] == shadow_evidence_ledger_path(user)
    assert paths["gate_result"] == shadow_gate_result_path(user)
    assert paths["state"].endswith(os.path.join("shadow_evidence", "alice_example", "shadow_evidence_state.json"))
    assert paths["ledger"].endswith(os.path.join("shadow_evidence", "alice_example", "shadow_evidence_ledger.jsonl"))

    forbidden_roots = [
        os.path.realpath(sessions_dir()),
        os.path.realpath(live_session_dir()),
        os.path.realpath(control_dir()),
        os.path.realpath(models_dir()),
    ]
    for key, path in paths.items():
        if key == "base":
            continue
        real_path = os.path.realpath(path)
        for forbidden_root in forbidden_roots:
            assert os.path.commonpath([real_path, forbidden_root]) != forbidden_root

    assert os.path.commonpath([os.path.realpath(paths["base"]), os.path.realpath(data_dir())]) == os.path.realpath(data_dir())


def test_shadow_contracts_use_existing_user_sanitization_deterministically():
    user = "  Yaman / Admin!!  "

    assert shadow_logger_key(user) == "shadow_logger_user_yaman_admin"
    assert shadow_monitor_key(user) == "shadow_monitor_user_yaman_admin"
    assert shadow_evidence_state_path(user).endswith(os.path.join("shadow_evidence", "yaman_admin", "shadow_evidence_state.json"))


def test_session_mixin_exposes_backend_only_shadow_contract_wrappers():
    from pathlib import Path

    source = Path("bridge/session_mixin.py").read_text(encoding="utf-8")
    for name in [
        "_shadow_logger_key",
        "_shadow_logger_process_key",
        "_shadow_logger_stop_control_name",
        "_shadow_monitor_key",
        "_shadow_monitor_process_key",
        "_shadow_monitor_stop_control_name",
        "_shadow_evidence_state_path",
        "_shadow_evidence_ledger_path",
        "_shadow_eval_report_path",
        "_shadow_gate_result_path",
        "_shadow_evidence_paths",
    ]:
        assert f"def {name}(" in source
    assert "Property(" not in source[source.index("def _shadow_logger_key"):source.index("def _new_live_session_dir")]
