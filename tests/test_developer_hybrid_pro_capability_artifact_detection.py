from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hybrid_pro_libraries_available_with_versions() -> None:
    from hybrid_pro_capability import check_hybrid_pro_libraries

    status = check_hybrid_pro_libraries(
        spec_finder=lambda name: object(),
        version_lookup=lambda name: {"torch": "2.5.1", "lightgbm": "4.6.0"}[name],
    )

    assert status["available"] is True
    assert status["modules"]["torch"]["available"] is True
    assert status["modules"]["torch"]["version"] == "2.5.1"
    assert status["modules"]["lightgbm"]["version"] == "4.6.0"
    assert status["reason_codes"] == []


def test_hybrid_pro_libraries_missing_are_reported_safely() -> None:
    from hybrid_pro_capability import check_hybrid_pro_libraries

    status = check_hybrid_pro_libraries(spec_finder=lambda name: None)

    assert status["available"] is False
    assert set(status["missing_libraries"]) == {"torch", "lightgbm"}
    assert "torch_missing" in status["reason_codes"]
    assert "lightgbm_missing" in status["reason_codes"]


def _bundle(tmp_path: Path, *, full_hybrid: bool = False) -> dict[str, str]:
    base = tmp_path / "candidate_bundle"
    base.mkdir()
    (base / "model.pkl").write_bytes(b"model")
    (base / "classifier.pkl").write_bytes(b"classifier")
    metadata = {
        "model_status": "approved_for_shadow",
        "classifier_family": "random_forest",
        "feature_schema_version": "feature-v1",
        "runtime_schema_version": "sequence-multiscale-v1",
        "context_models": {"bundles": {"mouse_heavy": {"model": "context_mouse.pkl"}}},
    }
    if full_hybrid:
        (base / "keyboard_verifier.pt").write_bytes(b"keyboard")
        (base / "mouse_verifier.pt").write_bytes(b"mouse")
        (base / "sequence_model.pt").write_bytes(b"sequence")
        metadata["deep_runtime"] = {
            "deep_sequence_runtime_enabled": True,
            "sequence_model": {"enabled": True, "artifact": "sequence_model.pt"},
        }
    (base / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return {
        "base": str(base),
        "model": str(base / "model.pkl"),
        "classifier": str(base / "classifier.pkl"),
        "metadata": str(base / "metadata.json"),
        "sequence_model": str(base / "sequence_model.pt"),
    }


def test_artifact_detector_distinguishes_libraries_from_missing_artifacts(tmp_path: Path) -> None:
    from hybrid_pro_capability import build_hybrid_pro_status

    status = build_hybrid_pro_status(
        bundle_paths=_bundle(tmp_path, full_hybrid=False),
        spec_finder=lambda name: object(),
        version_lookup=lambda name: "1.0",
    )

    assert status["libraries_available"] is True
    assert status["artifacts_available"] is False
    assert status["runtime_mode"] == "context_aware"
    assert status["runtime_model_family"] == "random_forest"
    assert set(status["missing_artifacts"]) == {"keyboard", "mouse", "combined"}
    assert "hybrid_libraries_available_artifacts_missing" in status["reason_codes"]


def test_artifact_detector_reports_full_hybrid_artifacts_when_files_exist(tmp_path: Path) -> None:
    from hybrid_pro_capability import build_hybrid_pro_status

    status = build_hybrid_pro_status(
        bundle_paths=_bundle(tmp_path, full_hybrid=True),
        spec_finder=lambda name: object(),
        version_lookup=lambda name: "1.0",
    )

    assert status["libraries_available"] is True
    assert status["artifacts_available"] is True
    assert status["runtime_mode"] == "cnn_lstm"
    assert status["runtime_model_family"] == "hybrid_pro_cnn_lstm"
    assert status["missing_artifacts"] == []
    assert status["artifact_status"]["layers"]["keyboard"]["available"] is True
    assert status["artifact_status"]["layers"]["mouse"]["available"] is True
    assert status["artifact_status"]["layers"]["combined"]["available"] is True


def test_hybrid_direct_state_exposes_backend_owned_hybrid_pro_status(tmp_path: Path) -> None:
    from hybrid_direct_contract import build_hybrid_direct_state_from_runtime
    from hybrid_pro_capability import build_hybrid_pro_status

    pro_status = build_hybrid_pro_status(
        bundle_paths=_bundle(tmp_path, full_hybrid=False),
        spec_finder=lambda name: object(),
        version_lookup=lambda name: "1.0",
    )
    state = build_hybrid_direct_state_from_runtime(
        {"active": True, "flow": "protected_active", "monitorReady": True, "runtime_status": "legitimate", "decision": "legit", "risk": 8},
        developer_simulation=True,
        runtime_bundle_source="developer_shadow_candidate",
        hybrid_pro_status=pro_status,
    )

    assert state["hybridProLibrariesAvailable"] is True
    assert state["hybridProArtifactsAvailable"] is False
    assert state["hybridRuntimeMode"] == "context_aware"
    assert "hybrid_libraries_available_artifacts_missing" in state["hybridProReasonCodes"]
    assert state["can_influence_device"] is False
    assert state["combined_risk"]["available"] is True


def test_hybrid_direct_qml_displays_backend_hybrid_pro_status_without_local_readiness() -> None:
    qml = (ROOT / "qml" / "pages" / "HybridDirectTestPage.qml").read_text(encoding="utf-8")
    assert "hybridProCapabilityCard" in qml
    assert "hybridState.hybridProLibrariesAvailable" in qml
    assert "hybridState.hybridProArtifactsAvailable" in qml
    assert "hybridState.hybridRuntimeMode" in qml
    assert "hybridState.hybridProReasonCodes" in qml
    assert "backend.hybridProStatus" not in qml
    for pattern in (
        r"function\s+\w*hybridProReady\w*\(",
        r"function\s+\w*artifactReady\w*\(",
        r"function\s+\w*fusion\w*\(",
        r"function\s+\w*lock\w*\(",
    ):
        assert re.search(pattern, qml) is None


def test_desktop_bridge_exposes_optional_hybrid_pro_status_property() -> None:
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    assert '@Property("QVariantMap", notify=hybridDirectChanged)' in desktop
    assert "def hybridProStatus(self) -> Dict[str, Any]:" in desktop
