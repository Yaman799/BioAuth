from __future__ import annotations

import json
import types

import numpy as np
import pytest
from pathlib import Path
from typing import Any, Mapping

from hybrid_candidates.offline_runner import REPORT_SOURCE_USER_REPLAY_SESSIONS, run_offline_candidate_replay
from metadata_core.constants import KB_HEADER, MS_HEADER
from security import compact_chunks, write_encrypted
from hybrid_candidates.schema import CandidateResult
from training_core.data import extract_window_samples_from_session
from tests.encrypted_session_fixtures import isolate_encrypted_session_runtime



@pytest.fixture(autouse=True)
def _isolate_encrypted_replay_security(tmp_path: Path, monkeypatch: Any) -> None:
    isolate_encrypted_session_runtime(tmp_path, monkeypatch)


def _write_session(root: Path, name: str, label: str, *, keyboard: bool = True, mouse: bool = True) -> Path:
    session = root / name
    session.mkdir(parents=True)
    (session / "metadata.json").write_text(json.dumps({"session_id": name, "label": label, "profile_id": "profile-a", "quality_score": 0.91}), encoding="utf-8")
    if keyboard:
        keyboard_path = session / "keyboard_log.csv"
        write_encrypted(str(keyboard_path), [["a", "press", 1.0], ["a", "release", 1.08]], KB_HEADER)
        compact_chunks(str(keyboard_path), KB_HEADER)
    if mouse:
        mouse_path = session / "mouse_log.csv"
        write_encrypted(str(mouse_path), [[2, 3, "move", 1.0], [3, 5, "move", 2.0]], MS_HEADER)
        compact_chunks(str(mouse_path), MS_HEADER)
    return session



def _write_dense_window_session(root: Path, name: str, label: str) -> Path:
    session = root / name
    session.mkdir(parents=True)
    (session / "metadata.json").write_text(json.dumps({"session_id": name, "label": label, "profile_id": "profile-a", "quality_score": 0.91}), encoding="utf-8")
    keyboard_rows = []
    mouse_rows = []
    for idx in range(180):
        ts = 1.0 + idx * 0.1
        keyboard_rows.append(["a", "press" if idx % 2 == 0 else "release", ts])
        mouse_rows.append([idx % 100, (idx * 3) % 100, "move", ts])
    keyboard_path = session / "keyboard_log.csv"
    mouse_path = session / "mouse_log.csv"
    write_encrypted(str(keyboard_path), keyboard_rows, KB_HEADER)
    compact_chunks(str(keyboard_path), KB_HEADER)
    write_encrypted(str(mouse_path), mouse_rows, MS_HEADER)
    compact_chunks(str(mouse_path), MS_HEADER)
    return session


def _result(candidate_id: str, _session: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    features = dict(context.get("feature_sample") or {})
    risk = 0.1 if features.get("keyboard_row_count") else 0.7
    if str(getattr(_session, "label", "")) == "intruder":
        risk = 0.9
    return CandidateResult(
        id=candidate_id,
        display_name="Isolation Forest",
        group="classic",
        available=True,
        trained_artifact_loaded=True,
        risk=risk,
        decision="intruder" if risk >= 0.5 else "genuine",
        can_vote=True,
        can_lock_alone=False,
        reason="test_adapter_from_replay_features",
        latency_ms=1.25,
        artifact_id="sha256:test-artifact",
        threshold_source="test_threshold",
        errors=(),
    ).to_dict()


def test_c11_offline_runner_discovers_replay_sessions_writes_user_replay_reports(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, "owner-1", "owner")
    _write_session(sessions_root, "intruder-1", "intruder")
    _write_session(sessions_root, "unknown-1", "unknown")

    output = tmp_path / "reports" / "hybrid_direct"
    summary = run_offline_candidate_replay(
        selected_candidates=["classic_isolation_forest"],
        sessions_root=sessions_root,
        output_dir=output,
        adapter_overrides={"classic_isolation_forest": _result},
    )

    assert summary["status"] == "completed"
    assert summary["source"] == REPORT_SOURCE_USER_REPLAY_SESSIONS
    assert summary["sessions_root"] == str(sessions_root)
    assert summary["sessions_discovered"] == 3
    assert summary["sessions_evaluated"] == 3
    assert summary["labeled_session_count"] == 2
    assert summary["unlabeled_session_count"] == 1
    assert summary["candidate_algorithms_executed"] is True
    assert summary["training_performed"] is False
    assert summary["production_selection_performed"] is False
    assert summary["benchmark_selection_performed"] is False
    assert summary["can_influence_device"] is False
    assert summary["trigger_face_confirmation"] is False
    assert summary["runtime_authoritative"] is False

    paths = {key: Path(value) for key, value in summary["report_paths"].items()}
    for name in ["candidate_results", "model_comparison", "group_vote_comparison", "fusion_report", "thresholds", "latency_report", "summary"]:
        assert paths[name].exists(), name
    fusion = json.loads(paths["fusion_report"].read_text(encoding="utf-8"))
    assert fusion["source"] == REPORT_SOURCE_USER_REPLAY_SESSIONS
    assert fusion["run_status"] == "completed"
    assert fusion["trigger_face_confirmation"] is False
    summary_md = paths["summary"].read_text(encoding="utf-8")
    assert "Source: `user_replay_sessions`" in summary_md
    assert "Metric-eligible labeled sessions: 2" in summary_md
    combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in paths.values())
    assert "keyboard_events" not in combined
    assert "mouse_events" not in combined
    assert "dwell_ms" not in combined
    assert "flight_ms" not in combined



def test_c11_offline_runner_uses_training_window_feature_names_for_model_artifacts(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    session = _write_dense_window_session(sessions_root, "owner-window", "owner")
    samples = extract_window_samples_from_session(str(session), strict=True)
    assert samples
    feature_names = list(samples[0].keys())[:24]
    seen: dict[str, Any] = {}

    class WindowAwareArtifact:
        def decision_function(self, X: np.ndarray) -> np.ndarray:
            seen["shape"] = tuple(X.shape)
            seen["nonzero"] = int(np.count_nonzero(X))
            return np.linspace(-0.1, -0.3, X.shape[0])

    def resolver(candidate_id: str, _session: Any, _context: Mapping[str, Any]) -> dict[str, Any]:
        return {"artifact": WindowAwareArtifact(), "metadata": {"feature_names": feature_names}}

    summary = run_offline_candidate_replay(
        selected_candidates=["classic_isolation_forest"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        artifact_resolver=resolver,
    )
    rows = [json.loads(line) for line in Path(summary["report_paths"]["candidate_results"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[0]["available"] is True
    assert seen["shape"][0] > 1
    assert seen["shape"][1] == len(feature_names)
    assert seen["nonzero"] > 0


def test_c11_missing_artifacts_are_unavailable_not_fake_scores(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, "owner-1", "owner")
    summary = run_offline_candidate_replay(
        selected_candidates=["classic_isolation_forest", "keyboard_type2branch"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
    )
    rows = [json.loads(line) for line in Path(summary["report_paths"]["candidate_results"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    for row in rows:
        assert row["available"] is False
        assert row["risk"] is None
        assert row["decision"] == "unavailable"
        assert row["can_vote"] is False
        assert row["can_lock_alone"] is False
    assert {row["reason"] for row in rows} <= {"missing_trained_artifact", "dependency_missing", "insufficient_free_text_data"}


def test_c11_candidate_failure_is_captured_without_crashing_run(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, "owner-1", "owner")

    def boom(candidate_id: str, session: Any, context: Mapping[str, Any]) -> dict[str, Any]:
        raise RuntimeError("adapter exploded")

    summary = run_offline_candidate_replay(
        selected_candidates=["classic_isolation_forest"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        adapter_overrides={"classic_isolation_forest": boom},
    )
    assert summary["status"] == "completed"
    rows = [json.loads(line) for line in Path(summary["report_paths"]["candidate_results"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["available"] is False
    assert rows[0]["reason"] == "candidate_runner_error"
    assert rows[0]["can_lock_alone"] is False


def test_c11_no_eligible_sessions_generates_safe_no_data_report(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, "unknown-1", "unknown")
    summary = run_offline_candidate_replay(sessions_root=sessions_root, output_dir=tmp_path / "reports")
    assert summary["status"] == "no_eligible_sessions"
    assert summary["source"] == REPORT_SOURCE_USER_REPLAY_SESSIONS
    assert summary["sessions_root"] == str(sessions_root)
    assert summary["session_count"] == 0
    assert summary["sessions_evaluated"] == 0
    assert summary["candidate_algorithms_executed"] is False
    assert summary["reason"] == "no eligible labeled replay sessions"
    assert summary["can_influence_device"] is False
    assert summary["trigger_face_confirmation"] is False
    paths = {key: Path(value) for key, value in summary["report_paths"].items()}
    assert paths["summary"].exists()
    fusion = json.loads(paths["fusion_report"].read_text(encoding="utf-8"))
    assert fusion["source"] == REPORT_SOURCE_USER_REPLAY_SESSIONS
    assert fusion["run_status"] == "no_eligible_sessions"


class _Signal:
    def __init__(self) -> None:
        self.count = 0
    def emit(self) -> None:
        self.count += 1


class _HybridApp:
    def __init__(self) -> None:
        self._current_user = {"user_id": "alice"}
        self._profile = {"production_ready": True}
        self._runtime_state = {}
        self._training_in_progress = False
        self._pending_logger_start = False
        self._pending_monitor_start = False
        self._pending_shadow_evidence_monitor_start = False
        self._running_processes = {}
        self._hybrid_direct_state = {}
        self._hybrid_direct_test_running = False
        self._latest_hybrid_direct_test_result = {}
        self.hybridDirectChanged = _Signal()
        self.controlsChanged = _Signal()
        self.statuses: list[tuple[str, str]] = []
        self.refreshes: list[tuple[str, bool]] = []
    def _safe_user(self) -> str:
        return "alice"
    def _session_flow(self) -> str:
        return "idle"
    def _shadow_logger_process_key(self) -> str:
        return "shadow_logger_user_alice"
    def _shadow_monitor_process_key(self) -> str:
        return "shadow_monitor_user_alice"
    def _debug_trace(self, *args: Any, **kwargs: Any) -> None:
        return None
    def _set_status(self, message: str, tone: str) -> None:
        self.statuses.append((message, tone))
    def requestRefresh(self, reason: str, force: bool = False) -> None:
        self.refreshes.append((reason, force))


def test_c11_run_hybrid_direct_test_calls_offline_replay_not_monitor(monkeypatch, tmp_path: Path) -> None:
    import bridge.session_runtime_helpers as helpers

    called: dict[str, Any] = {}

    def fake_runner(**kwargs: Any) -> dict[str, Any]:
        called["kwargs"] = kwargs
        out = Path(kwargs["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        return {
            "status": "completed",
            "source": "user_replay_sessions",
            "session_count": 2,
            "sessions_discovered": 2,
            "sessions_evaluated": 2,
            "labeled_session_count": 2,
            "unlabeled_session_count": 0,
            "candidate_count": 1,
            "candidate_result_rows": 2,
            "available_candidate_count": 0,
            "unavailable_candidate_count": 2,
            "missing_artifact_count": 2,
            "report_paths": {"summary": str(out / "hybrid_direct_summary.md")},
            "warnings": [],
            "errors": [],
            "candidate_algorithms_executed": True,
            "training_performed": False,
            "production_selection_performed": False,
            "benchmark_selection_performed": False,
            "can_lock": False,
            "can_lock_alone": False,
            "can_influence_device": False,
            "trigger_face_confirmation": False,
            "runtime_authoritative": False,
        }

    monkeypatch.setattr("hybrid_candidates.offline_runner.run_offline_candidate_replay", fake_runner)
    monkeypatch.setattr(helpers, "_hybrid_direct_test_report_path", lambda self: str(tmp_path / "backend_report.json"))
    monkeypatch.setattr(helpers, "_hybrid_direct_replay_sessions_root", lambda: str(tmp_path / "sessions"))
    app = _HybridApp()
    result = helpers.run_hybrid_direct_test(app)
    assert called["kwargs"]
    assert called["kwargs"]["sessions_root"] == str(tmp_path / "sessions")
    assert result["passed"] is True
    assert result["mode"] == "offline_candidate_replay"
    assert result["source"] == "user_replay_sessions"
    assert result["safety"]["device_lock_allowed"] is False
    assert result["safety"]["face_confirmation_trigger_allowed"] is False
    assert result["offline_replay"]["candidate_algorithms_executed"] is True
    assert result["offline_replay"]["can_influence_device"] is False
    assert result["offline_replay"]["trigger_face_confirmation"] is False
    assert "hybrid_direct_offline_replay_only" in result["reason_codes"]
    assert Path(result["report_path"]).exists()
    assert app._hybrid_direct_test_running is False
    assert app._hybrid_direct_state["report_source"] == "user_replay_sessions"
    assert app._hybrid_direct_state["can_influence_device"] is False


def test_c11_runtime_helper_keeps_monitor_smoke_path_separate() -> None:
    helper = Path("bridge/session_runtime_helpers.py").read_text(encoding="utf-8")
    assert "def run_hybrid_direct_test" in helper
    assert "run_offline_candidate_replay" in helper
    assert "def run_hybrid_direct_monitor_smoke_test" in helper
    run_body = helper[helper.index("def run_hybrid_direct_test"):helper.index("def run_hybrid_direct_monitor_smoke_test")]
    assert "subprocess.run" not in run_body
    assert "BIOAUTH_HYBRID_TEST_ONLY" not in run_body
    assert "offline_candidate_replay" in run_body
    assert "device_influence_disabled" in run_body
    assert "face_confirmation_disabled" in run_body


def test_c11_qml_remains_backend_owned_for_reports_and_metrics() -> None:
    qml = Path("qml/pages/HybridDirectTestPage.qml").read_text(encoding="utf-8")
    assert "backend.latestHybridDirectReportState" in qml
    assert "hybridDirectLatestReportSourcePill" in qml
    assert "hybridDirectLatestReportRunStatusPill" in qml
    forbidden = ["function computeAuc", "function computeEer", "function buildGroupVote", "triggerFaceConfirmation", "LockWorkStation"]
    for token in forbidden:
        assert token not in qml


def test_p1a_mouse_layer_artifact_adapter_integrates_existing_layer_iforest(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    session = _write_dense_window_session(sessions_root, "owner-mouse-layer", "owner")
    samples = extract_window_samples_from_session(str(session), strict=True)
    feature_names = list(samples[0].keys())[:16]

    class MouseLayerModel:
        def decision_function(self, X: np.ndarray) -> np.ndarray:
            return np.linspace(0.4, 0.2, X.shape[0])

    artifact = {
        "artifact_version": "hybrid-pro-artifacts-v1",
        "layer": "mouse",
        "model_family": "hybrid_pro_layer_iforest",
        "feature_names": feature_names,
        "model": MouseLayerModel(),
    }

    def resolver(candidate_id: str, _session: Any, _context: Mapping[str, Any]) -> dict[str, Any]:
        assert candidate_id == "mouse_resnet_gru"
        return {"artifact": artifact, "metadata": {"feature_names": feature_names, "artifact_id": "sha256:mouse-layer-test"}}

    summary = run_offline_candidate_replay(
        selected_candidates=["mouse_resnet_gru"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        artifact_resolver=resolver,
    )
    rows = [json.loads(line) for line in Path(summary["report_paths"]["candidate_results"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and rows[0]["candidate_id"] == "mouse_resnet_gru"
    assert rows[0]["available"] is True
    assert rows[0]["reason"] == "hybrid_pro_layer_iforest_compat"
    assert rows[0]["artifact_adapter"] == "hybrid_pro_layer_iforest_compat"
    assert rows[0]["feature_source"] == "training_window_samples"
    assert rows[0]["can_lock_alone"] is False
    assert rows[0]["trigger_face_confirmation"] is False


def test_p1a_hybrid_pro_fusion_artifact_adapter_uses_layer_votes(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_dense_window_session(sessions_root, "owner-fusion-layer", "owner")
    fusion_artifact = {
        "artifact_version": "hybrid-pro-artifacts-v1",
        "layer": "combined",
        "model_family": "hybrid_pro_fusion",
        "fusion_strategy": "layer_risk_weighted_average",
        "available_layers": ["mouse"],
    }

    def mouse_result(candidate_id: str, _session: Any, _context: Mapping[str, Any]) -> dict[str, Any]:
        return CandidateResult(
            id=candidate_id,
            display_name="Mouse ResNet-GRU",
            group="mouse",
            available=True,
            trained_artifact_loaded=True,
            risk=0.72,
            decision="intruder",
            can_vote=True,
            can_lock_alone=False,
            reason="test_mouse_vote",
            latency_ms=1.0,
            artifact_id="sha256:mouse",
            threshold_source="test",
            errors=(),
        ).to_dict()

    def resolver(candidate_id: str, _session: Any, _context: Mapping[str, Any]) -> dict[str, Any]:
        if candidate_id == "fusion_logistic_stacking":
            return {"artifact": fusion_artifact, "metadata": {"artifact_id": "sha256:fusion"}}
        return {}

    summary = run_offline_candidate_replay(
        selected_candidates=["mouse_resnet_gru", "fusion_logistic_stacking"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        adapter_overrides={"mouse_resnet_gru": mouse_result},
        artifact_resolver=resolver,
    )
    rows = [json.loads(line) for line in Path(summary["report_paths"]["candidate_results"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    fusion = [row for row in rows if row["candidate_id"] == "fusion_logistic_stacking"][0]
    assert fusion["available"] is True
    assert fusion["reason"] == "hybrid_pro_weighted_layer_fusion_compat"
    assert fusion["risk"] == 0.72
    assert fusion["artifact_adapter"] == "hybrid_pro_fusion_compat"
    assert fusion["feature_source"] == "group_votes"
    assert fusion["can_vote"] is False
    assert fusion["can_lock_alone"] is False


def test_p1a_candidate_bundle_artifact_resolver_maps_declared_files(tmp_path: Path) -> None:
    from hybrid_candidates.artifact_resolver import build_candidate_bundle_artifact_resolver

    bundle = tmp_path / "candidate_bundle"
    bundle.mkdir()
    (bundle / "model.pkl").write_bytes(b"not-a-real-pickle-for-path-only")
    (bundle / "classifier.pkl").write_bytes(b"not-a-real-pickle-for-path-only")
    metadata = {
        "feature_names": ["f1", "f2"],
        "artifacts": {"model": "model.pkl", "classifier": "classifier.pkl"},
        "layer_artifacts": {},
    }
    (bundle / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    resolver = build_candidate_bundle_artifact_resolver(bundle_dir=bundle)
    classic = resolver("classic_isolation_forest", None, {})
    supervised = resolver("supervised_random_forest", None, {})
    assert classic["artifact_path"].endswith("model.pkl")
    assert supervised["artifact_path"].endswith("classifier.pkl")
    assert classic["metadata"]["artifact_resolver_schema_version"] == "hybrid-direct-artifact-resolver-p1a-v1"
    assert classic["metadata"]["can_lock_alone"] is False


def test_p1a1_mouse_layer_empty_windows_reports_precise_reason(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, "owner-empty-window", "owner")

    class MouseLayerModel:
        def decision_function(self, X: np.ndarray) -> np.ndarray:
            return np.zeros(X.shape[0], dtype=float)

    artifact = {
        "artifact_version": "hybrid-pro-artifacts-v1",
        "layer": "mouse",
        "model_family": "hybrid_pro_layer_iforest",
        "feature_names": ["missing_training_feature"],
        "model": MouseLayerModel(),
    }

    def resolver(candidate_id: str, _session: Any, _context: Mapping[str, Any]) -> dict[str, Any]:
        assert candidate_id == "mouse_resnet_gru"
        return {"artifact": artifact, "metadata": {"feature_names": artifact["feature_names"], "artifact_id": "sha256:mouse-empty"}}

    summary = run_offline_candidate_replay(
        selected_candidates=["mouse_resnet_gru"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        artifact_resolver=resolver,
    )
    rows = [json.loads(line) for line in Path(summary["report_paths"]["candidate_results"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and rows[0]["candidate_id"] == "mouse_resnet_gru"
    assert rows[0]["available"] is False
    assert rows[0]["reason"] in {"window_feature_empty", "window_feature_matrix_unavailable"}
    assert rows[0]["reason"] != "adapter_error"
    assert rows[0]["artifact_adapter"] == "hybrid_pro_layer_iforest_compat"
    assert rows[0]["feature_source"] == "training_window_samples"
    assert rows[0]["errors"] == []
    assert rows[0]["can_lock_alone"] is False


def test_p1a1_sequence_empty_tensor_reports_precise_reason() -> None:
    from hybrid_candidates.adapters.deep_sequence import evaluate_combined_cnn_lstm

    artifact = {
        "artifact_version": "cnn-lstm-trainer-v1",
        "model_family": "cnn_lstm",
        "state_dict": {},
        "model_config": {"feature_dim": 5, "sequence_length": 4},
    }
    result = evaluate_combined_cnn_lstm(
        np.zeros((0, 4, 5), dtype=float),
        artifact=artifact,
        metadata={
            "hybrid_direct_sequence_unavailable_reason": "insufficient_sequence_windows",
            "hybrid_direct_sequence_count": 0,
            "hybrid_direct_feature_count": 5,
        },
    )
    assert result["available"] is False
    assert result["reason"] == "insufficient_sequence_windows"
    assert result["reason"] != "sequence_inference_error:RuntimeError"
    assert result["artifact_adapter"] == "sequence_cnn_lstm_pytorch"
    assert result["feature_source"] == "training_window_sequences"
    assert result["sequence_count"] == 0
    assert result["feature_count"] == 5
    assert result["can_lock_alone"] is False


def test_p1a1_hybrid_pro_fusion_missing_layer_vote_reason_is_precise(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, "owner-fusion-no-vote", "owner")
    fusion_artifact = {
        "artifact_version": "hybrid-pro-artifacts-v1",
        "layer": "combined",
        "model_family": "hybrid_pro_fusion",
        "fusion_strategy": "layer_risk_weighted_average",
        "available_layers": ["mouse"],
    }

    def resolver(candidate_id: str, _session: Any, _context: Mapping[str, Any]) -> dict[str, Any]:
        if candidate_id == "fusion_logistic_stacking":
            return {"artifact": fusion_artifact, "metadata": {"artifact_id": "sha256:fusion-no-vote"}}
        return {}

    summary = run_offline_candidate_replay(
        selected_candidates=["fusion_logistic_stacking"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        artifact_resolver=resolver,
    )
    rows = [json.loads(line) for line in Path(summary["report_paths"]["candidate_results"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and rows[0]["candidate_id"] == "fusion_logistic_stacking"
    assert rows[0]["available"] is False
    assert rows[0]["reason"] == "no_available_layer_votes"
    assert rows[0]["reason"] != "missing_calibration_threshold"
    assert rows[0]["artifact_adapter"] == "hybrid_pro_fusion_compat"
    assert rows[0]["feature_source"] == "group_votes"
    assert rows[0]["can_lock_alone"] is False


def test_p1b_threshold_and_dataset_diagnostics_are_written(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, "owner-p1b", "owner")
    _write_session(sessions_root, "intruder-p1b", "intruder")

    def scored(candidate_id: str, session: Any, _context: Mapping[str, Any]) -> dict[str, Any]:
        risk = 0.2 if str(getattr(session, "label", "")) == "owner" else 0.8
        return CandidateResult(
            id=candidate_id,
            display_name="Isolation Forest",
            group="classic",
            available=True,
            trained_artifact_loaded=True,
            risk=risk,
            decision="intruder" if risk >= 0.5 else "genuine",
            can_vote=True,
            can_lock_alone=False,
            reason="test_p1b_diagnostics",
            latency_ms=1.0,
            artifact_id="sha256:p1b",
            threshold_source="test_threshold",
            errors=(),
        ).to_dict()

    summary = run_offline_candidate_replay(
        selected_candidates=["classic_isolation_forest"],
        sessions_root=sessions_root,
        output_dir=tmp_path / "reports",
        adapter_overrides={"classic_isolation_forest": scored},
    )

    paths = {key: Path(value) for key, value in summary["report_paths"].items()}
    assert paths["thresholds"].exists()
    assert paths["threshold_diagnostics"].exists()
    assert paths["dataset_diagnostics"].exists()

    thresholds = json.loads(paths["thresholds"].read_text(encoding="utf-8"))
    dataset = json.loads(paths["dataset_diagnostics"].read_text(encoding="utf-8"))
    assert thresholds["diagnostics"]["schema_version"] == "hybrid-direct-threshold-diagnostics-v1"
    assert dataset["schema_version"] == "hybrid-direct-dataset-diagnostics-v1"
    assert "intruder_sample_count_below_10" in dataset["diagnostic_warnings"]
    candidate = thresholds["diagnostics"]["candidates"]["classic_isolation_forest"]
    assert candidate["score_distributions"]["genuine_owner"]["count"] == 1
    assert candidate["score_distributions"]["intruder"]["count"] == 1
    assert candidate["threshold_evaluations"]["default_0_5"]["confusion_matrix"] == {"fn": 0, "fp": 0, "tn": 1, "tp": 1}
    assert candidate["can_lock_alone"] is False
    assert thresholds["diagnostics"]["can_influence_device"] is False
    assert thresholds["diagnostics"]["runtime_authoritative"] is False

    csv_text = paths["threshold_diagnostics"].read_text(encoding="utf-8")
    assert "owner_p95" in csv_text
    assert "best_balanced_threshold" in csv_text
    summary_md = paths["summary"].read_text(encoding="utf-8")
    assert "## P1B diagnostics" in summary_md
