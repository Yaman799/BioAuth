from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping
import types

ROOT = Path(__file__).absolute().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


_TEST_STUB_PREVIOUS: dict[str, object | None] = {}


def _install_test_stub(name: str, module: types.ModuleType) -> None:
    if name not in _TEST_STUB_PREVIOUS:
        _TEST_STUB_PREVIOUS[name] = sys.modules.get(name)
    sys.modules[name] = module


def _restore_test_stubs_and_uncache(*imported_module_names: str) -> None:
    for name, previous in _TEST_STUB_PREVIOUS.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    for name in imported_module_names:
        sys.modules.pop(name, None)
        parent_name, _, child_name = name.rpartition(".")
        parent_module = sys.modules.get(parent_name) if parent_name else None
        if parent_module is not None and child_name and getattr(parent_module, child_name, None) is not None:
            try:
                delattr(parent_module, child_name)
            except AttributeError:
                pass

# The source tree normally provides utils.identity through the app bootstrap.
# The focused no-site direct runner stubs it so dashboard imports can be tested
# without changing application behavior.
if True:  # scoped import stub, restored below
    utils_mod = types.ModuleType("utils")
    identity_mod = types.ModuleType("utils.identity")
    identity_mod.slugify_username = lambda value: str(value or "").strip().lower().replace(" ", "_")
    _install_test_stub("utils", utils_mod)
    _install_test_stub("utils.identity", identity_mod)
if True:  # scoped import stub, restored below
    features_mod = types.ModuleType("features")
    features_mod.DEFAULT_MIN_WINDOW_EVENTS = 40
    features_mod.DEFAULT_WINDOW_SECONDS = 30.0
    features_mod.DEFAULT_WINDOW_STEP_SECONDS = 10.0

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
    _install_test_stub("features", features_mod)
if True:  # scoped import stub, restored below
    runtime_mod = types.ModuleType("metadata_core.runtime")
    runtime_mod.load_model_metadata_cached = lambda path, **kwargs: {}
    runtime_mod.resolve_active_runtime_paths = lambda safe, **kwargs: {}
    runtime_mod.resolve_active_runtime_paths_with_validation = lambda safe, **kwargs: ({}, {"ok": False, "reason": "runtime_pointer_missing", "metadata": {}})
    runtime_mod.validate_runtime_bundle_for_activation = lambda paths, **kwargs: {"ok": False, "reason": "runtime_pointer_missing", "metadata": {}}
    _install_test_stub("metadata_core.runtime", runtime_mod)

from evaluation_core.production_evidence import build_production_evidence_report
from metadata_core.dashboard import build_user_dashboard_snapshot
from metadata_core.production_approval import production_approval_observability_payload

_restore_test_stubs_and_uncache(
    "evaluation_core.production_evidence",
    "metadata_core.constants",
    "metadata_core.dashboard",
    "metadata_core.production_approval",
    "metadata_core.runtime",
)


_FORBIDDEN_OBSERVABILITY_TOKENS = (
    "raw_keyboard",
    "keyboard_events",
    "mouse_events",
    "feature_vector",
    "feature_values",
    "raw_biometric",
)


def _passing_evidence() -> dict[str, Any]:
    return build_production_evidence_report(
        candidate_artifact_digest="sha256:candidate-pass",
        baseline_artifact_digest="sha256:baseline",
        evaluation_report_digest="sha256:evaluation",
        runtime_schema_version="runtime-schema-v1",
        model_comparison_windows=[
            {"window_id": f"w{i}", "candidate_decision": "trusted", "baseline_decision": "trusted", "trusted_window": True}
            for i in range(4)
        ],
        post_unlock_windows=[
            {"window_id": f"u{i}", "trusted_window": True, "warning_triggered": False, "simulated_false_lock": False, "feature_quality_ok": True}
            for i in range(3)
        ],
        confirmed_intruder_events=[],
        runtime_decision_summaries=[
            {"decision_id": f"r{i}", "truth": "owner", "candidate_decision": "trusted", "unknown": False, "simulated_false_lock": False, "feature_quality_ok": True}
            for i in range(4)
        ],
    ).to_dict()


def _low_agreement_evidence() -> dict[str, Any]:
    return build_production_evidence_report(
        candidate_artifact_digest="sha256:candidate-low-agreement",
        model_comparison_windows=[
            {"window_id": "w1", "candidate_decision": "warning", "baseline_decision": "trusted", "trusted_window": True}
        ],
        post_unlock_windows=[],
        confirmed_intruder_events=[],
        runtime_decision_summaries=[],
    ).to_dict()


def _session_meta(session_id: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "user_id": "alice",
        "session_kind": "enrollment",
        "final_decision": "accepted",
        "archive_label": "accepted",
        "training_counts_toward_minimum": True,
        "metadata_trusted": True,
        "keyboard_rows": 40,
        "mouse_rows": 40,
        "duration_seconds": 60,
    }
    payload.update(extra)
    return payload


def _snapshot(candidate_metadata: Mapping[str, Any], sessions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sessions = list(sessions or [])
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        metadata_path = base / "candidate.json"
        model_path = base / "candidate.pkl"
        metadata_path.write_text("{}", encoding="utf-8")
        model_path.write_text("model", encoding="utf-8")
        session_paths: list[str] = []
        session_by_path: dict[str, dict[str, Any]] = {}
        for idx, meta in enumerate(sessions):
            session_dir = base / f"alice_session_{idx}"
            session_dir.mkdir()
            session_paths.append(str(session_dir))
            session_by_path[str(session_dir)] = dict(meta)

        return build_user_dashboard_snapshot(
            "alice",
            include_training_selection_details=False,
            session_detail_limit=None,
            list_session_dirs_fn=lambda: list(session_paths),
            read_session_metadata_fn=lambda path: dict(session_by_path[path]),
            use_session_index=False,
            user_model_paths_fn=lambda safe: {"metadata": str(metadata_path), "model": str(model_path), "evaluation_report": "", "evaluation_summary": ""},
            user_model_dir_fn=lambda safe: str(base),
            active_runtime_pointer_path_fn=lambda safe: str(base / "missing_pointer.json"),
            load_model_metadata_fn=lambda path, **kwargs: dict(candidate_metadata),
            resolve_active_runtime_paths_fn=lambda safe, **kwargs: {},
            validate_runtime_bundle_for_activation_fn=lambda paths, **kwargs: {"ok": False, "reason": "runtime_bundle_invalid", "metadata": dict(candidate_metadata)},
        )


def _walk_keys(payload: Any):
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield str(key)
            yield from _walk_keys(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            yield from _walk_keys(item)


def test_dashboard_payload_contains_evidence_and_remediation_state():
    snapshot = _snapshot(
        {
            "model_status": "approved_for_production",
            "production_evidence": _low_agreement_evidence(),
            "policy_details": {"gate_results": {"f1": True, "far": True, "frr": True}},
        }
    )
    profile = snapshot["profile"]

    assert profile["evidence_gate_status"] in {"partial", "fail"}
    assert "insufficient_model_agreement" in profile["evidence_reason_codes"]
    assert profile["remediation_state"]["action"] == "collect_more_shadow_comparison_windows"
    assert profile["remediation_next_action"] == "collect_more_shadow_comparison_windows"
    assert profile["retry_allowed"] is False
    assert profile["model_readiness_state"]["remediationState"]["action"] == "collect_more_shadow_comparison_windows"


def test_dashboard_payload_missing_evidence_safe_defaults():
    snapshot = _snapshot({"model_status": "approved_for_production", "policy_details": {"gate_results": {"f1": True, "far": True, "frr": True}}})
    profile = snapshot["profile"]

    assert profile["evidence_gate_status"] == "partial"
    assert profile["evidence_promotion_effect"] == "shadow_only"
    assert profile["production_ready"] is False
    assert profile["production_approval_state"]["protectedSessionsAvailable"] is False
    assert profile["retry_allowed"] is False


def test_observability_payload_no_raw_biometric_data():
    snapshot = _snapshot(
        {
            "model_status": "approved_for_production",
            "production_evidence": _passing_evidence(),
            "policy_details": {"gate_results": {"f1": True, "far": True, "frr": True}},
        }
    )
    state = dict(snapshot["profile"]["production_approval_state"])
    state.update({"raw_keyboard_events": ["secret"], "mouse_events": [1], "feature_vector": [0.1]})
    payload = production_approval_observability_payload(state)
    joined = " ".join(_walk_keys(payload)).lower()
    for token in _FORBIDDEN_OBSERVABILITY_TOKENS:
        assert token not in joined


def test_qml_has_no_local_production_ready_logic():
    qml_root = ROOT / "qml"
    local_patterns = [
        re.compile(r"^\s*(?:readonly\s+)?property\s+[^\n]*\bproductionReady\b", re.MULTILINE),
        re.compile(r"^\s*productionReady\s*:", re.MULTILINE),
        re.compile(r"^\s*modelReady\s*:", re.MULTILINE),
        re.compile(r"^\s*approvalPassed\s*:", re.MULTILINE),
    ]
    offenders = []
    for path in qml_root.rglob("*.qml"):
        text = path.read_text(encoding="utf-8")
        for pattern in local_patterns:
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_qml_does_not_compute_protected_sessions_available():
    qml_root = ROOT / "qml"
    local_patterns = [
        re.compile(r"^\s*(?:readonly\s+)?property\s+[^\n]*\bprotectedSessionsAvailable\b", re.MULTILINE),
        re.compile(r"^\s*protectedSessionsAvailable\s*:", re.MULTILINE),
    ]
    offenders = []
    for path in qml_root.rglob("*.qml"):
        text = path.read_text(encoding="utf-8")
        for pattern in local_patterns:
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def _run() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = []
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - direct runner prints focused failures.
            failures.append(f"{test.__name__}: {type(exc).__name__}: {exc}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"{len(tests)} dashboard evidence/remediation display tests passed", flush=True)


if __name__ == "__main__":
    _run()
