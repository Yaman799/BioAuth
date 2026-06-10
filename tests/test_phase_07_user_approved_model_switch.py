from __future__ import annotations

import importlib.util
import base64
import json
import os
import pickle
import shutil
import sys
import tempfile
import types
from pathlib import Path

TMP_HOME = tempfile.mkdtemp(prefix="bioauth_phase07_home_")
os.environ["HOME"] = TMP_HOME
os.environ["BIOAUTH_HOME"] = TMP_HOME

ROOT = Path(__file__).resolve().parent.parent
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

if not _module_available("cryptography.fernet"):  # scoped import stub, restored below
    cryptography_mod = types.ModuleType("cryptography")
    fernet_mod = types.ModuleType("cryptography.fernet")
    class _TestFernet:
        @staticmethod
        def generate_key() -> bytes:
            return base64.urlsafe_b64encode(b"0" * 32)
        def __init__(self, key: bytes) -> None:
            self.key = key
        def encrypt(self, payload: bytes) -> bytes:
            return payload
        def decrypt(self, payload: bytes) -> bytes:
            return payload
    fernet_mod.Fernet = _TestFernet
    cryptography_mod.fernet = fernet_mod
    _install_test_stub("cryptography", cryptography_mod)
    _install_test_stub("cryptography.fernet", fernet_mod)

if True:  # scoped import stub, restored below
    secrets_mod = types.ModuleType("bio_platform.secrets")
    def _load_or_create_secret(*args, **kwargs):
        path = str(kwargs.get("plaintext_path") or (args[0] if args else Path(TMP_HOME) / "secret.key"))
        generate_secret = kwargs.get("generate_secret") or (lambda: base64.urlsafe_b64encode(b"0" * 32))
        if os.path.exists(path):
            return Path(path).read_bytes()
        secret = generate_secret()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_bytes(secret)
        return secret
    secrets_mod.get_secret_backend_name = lambda: "test-file"
    secrets_mod.load_or_create_secret = _load_or_create_secret
    _install_test_stub("bio_platform.secrets", secrets_mod)

if not _module_available("features"):  # scoped import stub, restored below
    features_mod = types.ModuleType("features")
    features_mod.DEFAULT_MIN_WINDOW_EVENTS = 3
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

if not _module_available("numpy"):  # scoped import stub, restored below
    numpy_mod = types.ModuleType("numpy")
    numpy_mod.__version__ = "test"
    _install_test_stub("numpy", numpy_mod)

from evaluation_core.production_evidence import build_production_evidence_report
from metadata_core import auto_promotion
from metadata_core.auto_promotion import approve_production_model_switch, safe_auto_promote_production_bundle
from metadata_core.constants import ACTIVE_WINDOW_SCALES, FEATURE_SCHEMA_VERSION, FEATURE_WINDOW_STRATEGY
from metadata_core.paths import _active_runtime_pointer_path, _user_model_paths, _user_production_paths
from metadata_core.production_approval import build_production_approval_state
from metadata_core.runtime import resolve_active_runtime_paths_with_validation
from security import atomic_write_text, save_metadata_hash, save_model_hash

_restore_test_stubs_and_uncache(
    "artifact_integrity",
    "evaluation_core.production_evidence",
    "metadata_core.auto_promotion",
    "metadata_core.constants",
    "metadata_core.paths",
    "metadata_core.runtime",
    "security",
    "utils.identity",
)


def _security_helpers():
    import security as _security

    return _security


def _cleanup() -> None:
    shutil.rmtree(TMP_HOME, ignore_errors=True)


def _passing_evidence(*, candidate: str = "sha256:user-switch-candidate", partial: bool = False) -> dict:
    report = build_production_evidence_report(
        candidate_artifact_digest=candidate,
        baseline_artifact_digest="sha256:user-switch-baseline",
        evaluation_report_digest="sha256:user-switch-eval",
        runtime_schema_version="runtime-schema-v1",
        model_comparison_windows=[{"window_id": f"m{idx}", "candidate_decision": "trusted", "baseline_decision": "trusted", "trusted_window": True} for idx in range(4)],
        post_unlock_windows=[{"window_id": f"u{idx}", "trusted_window": True, "warning_triggered": False, "simulated_false_lock": False, "feature_quality_ok": True} for idx in range(3)],
        confirmed_intruder_events=[],
        runtime_decision_summaries=[{"decision_id": f"r{idx}", "truth": "owner", "candidate_decision": "trusted", "unknown": False, "simulated_false_lock": False, "feature_quality_ok": True} for idx in range(4)],
    ).to_dict()
    if partial:
        report["gate"] = {"status": "partial", "promotion_effect": "shadow_only", "reason_codes": ["production_evidence_partial"]}
    return report


def _metadata(*, candidate: str = "sha256:user-switch-candidate", status: str = "approved_for_production", schema: str = FEATURE_SCHEMA_VERSION, partial_evidence: bool = False) -> dict:
    return {
        "model_status": status,
        "bundle_role": "candidate",
        "feature_schema_version": schema,
        "feature_window_strategy": FEATURE_WINDOW_STRATEGY,
        "active_window_scales": list(ACTIVE_WINDOW_SCALES),
        "candidate_artifact_digest": candidate,
        "baseline_artifact_digest": "sha256:user-switch-baseline",
        "evaluation_report_digest": "sha256:user-switch-eval",
        "runtime_schema_version": "runtime-schema-v1",
        "rollback_ready": True,
        "policy_details": {
            "gate_results": {"minimum_support": True, "f1": True, "far": True, "frr": True, "precision": True, "recall": True, "auc": True},
            "safety_gate_results": {"safety_metrics_present": True, "false_lock_count": True, "warning_per_hour": True, "low_quality_decision_rate": True, "data_coverage": True, "raw_data_absent": True},
        },
        "rollout_details": {"allowed_modes": ["classic", "auto"], "rollback_to_classic_on_failure": True},
        "production_evidence": _passing_evidence(candidate=candidate, partial=partial_evidence),
    }


def _write_bundle(paths: dict, *, metadata: dict, marker: str = "candidate") -> None:
    os.makedirs(paths["base"], exist_ok=True)
    Path(paths["model"]).write_bytes(pickle.dumps({"kind": "model", "marker": marker}))
    _security_helpers().save_model_hash(paths["model"])
    _security_helpers().atomic_write_text(paths["metadata"], json.dumps(metadata, indent=2, ensure_ascii=False))
    _security_helpers().save_metadata_hash(paths["metadata"])
    _security_helpers().atomic_write_text(paths["evaluation_report"], json.dumps({"evaluation_report_digest": metadata.get("evaluation_report_digest")}, indent=2))
    _security_helpers().atomic_write_text(paths["evaluation_summary"], "candidate evaluation summary\n")


def test_cannot_switch_without_user_approval() -> None:
    user = "phase07_no_user_approval"
    meta = _metadata()
    _write_bundle(_user_model_paths(user), metadata=meta)
    result = approve_production_model_switch(user, meta["candidate_artifact_digest"], user_approved=False)
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["reason"] == "user_approval_required"
    assert not os.path.exists(_active_runtime_pointer_path(user))


def test_cannot_approve_wrong_digest() -> None:
    user = "phase07_wrong_digest"
    meta = _metadata()
    _write_bundle(_user_model_paths(user), metadata=meta)
    result = approve_production_model_switch(user, "sha256:not-the-candidate", user_approved=True)
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["reason"] == "candidate_digest_mismatch"
    assert not os.path.exists(_active_runtime_pointer_path(user))


def test_incomplete_gates_evidence_blocks_approval() -> None:
    user = "phase07_incomplete_gates"
    meta = _metadata(partial_evidence=True)
    _write_bundle(_user_model_paths(user), metadata=meta)
    result = approve_production_model_switch(user, meta["candidate_artifact_digest"], user_approved=True)
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["reason"] in {"production_evidence_not_passed", "production_evidence_partial"}
    assert not os.path.exists(_active_runtime_pointer_path(user))


def test_runtime_validation_failure_blocks_switch() -> None:
    user = "phase07_runtime_invalid"
    meta = _metadata(schema="old-schema")
    _write_bundle(_user_model_paths(user), metadata=meta)
    result = approve_production_model_switch(user, meta["candidate_artifact_digest"], user_approved=True)
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["reason"].startswith("staging_runtime_invalid:")
    assert not os.path.exists(_active_runtime_pointer_path(user))


def test_auto_path_reports_pending_user_approval_without_switching() -> None:
    user = "phase07_auto_pending"
    meta = _metadata()
    _write_bundle(_user_model_paths(user), metadata=meta)
    result = safe_auto_promote_production_bundle(user, settings={"auto_promote_when_production_safe_enabled": True}, runtime_validation={"ok": False})
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["reason"] == "production_ready_pending_user_approval"
    assert result["candidateDigest"] == meta["candidate_artifact_digest"]
    assert result["protectedSessionsAvailable"] is False
    assert not os.path.exists(_active_runtime_pointer_path(user))


def test_successful_user_approval_updates_active_pointer_atomically() -> None:
    user = "phase07_success"
    meta = _metadata()
    _write_bundle(_user_model_paths(user), metadata=meta)
    result = approve_production_model_switch(user, meta["candidate_artifact_digest"], user_approved=True, approved_by="alice")
    assert result["ok"] is True
    assert result["changed"] is True
    assert result["reason"] == "user_approved_model_switch_activated"
    paths, validation = resolve_active_runtime_paths_with_validation(user)
    assert paths is not None
    assert validation["ok"] is True
    assert validation["metadata"]["bundle_role"] == "production"
    assert validation["metadata"]["model_status"] == "approved_for_production"
    assert validation["metadata"]["user_approved_model_switch"] is True
    assert validation["metadata"]["user_approval_candidate_digest"] == meta["candidate_artifact_digest"]
    assert result["rollbackReady"] is True


def test_pointer_write_failure_rolls_back_existing_production_bundle() -> None:
    user = "phase07_rollback"
    meta = _metadata()
    _write_bundle(_user_model_paths(user), metadata=meta, marker="new-candidate")
    original_meta = _metadata()
    original_meta["bundle_role"] = "production"
    original_meta["marker"] = "original-production"
    production = _user_production_paths(user)
    _write_bundle(production, metadata=original_meta, marker="original-production")
    before = json.loads(Path(production["metadata"]).read_text(encoding="utf-8"))
    original_writer = auto_promotion.write_active_runtime_pointer
    def broken_writer(*args, **kwargs):
        raise RuntimeError("simulated pointer write failure")
    auto_promotion.write_active_runtime_pointer = broken_writer
    try:
        result = approve_production_model_switch(user, meta["candidate_artifact_digest"], user_approved=True)
    finally:
        auto_promotion.write_active_runtime_pointer = original_writer
    after = json.loads(Path(production["metadata"]).read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["changed"] is False
    assert "user_approved_switch_failed_safe" in result["reason"]
    assert after.get("marker") == before.get("marker") == "original-production"


def test_backend_state_marks_pending_user_approval_without_qml_readiness_logic() -> None:
    meta = _metadata()
    state = build_production_approval_state(candidate_paths={}, candidate_metadata=meta, runtime_validation={"ok": False, "reason": "runtime_pointer_missing", "metadata": meta})
    assert state["productionReadyPendingUserApproval"] is True
    assert state["userApprovalRequired"] is True
    assert state["modelSwitchCandidateDigest"] == meta["candidate_artifact_digest"]
    assert state["protectedSessionsAvailable"] is False
    overview = (ROOT / "qml" / "pages" / "OverviewPage.qml").read_text(encoding="utf-8")
    qml = (ROOT / "qml" / "pages" / "user" / "UserModelUpdatePage.qml").read_text(encoding="utf-8")
    assert "backend.requestUserApproveModelUpdate()" in qml
    assert "backend.approveProductionModelSwitch(" not in qml
    assert "approveProductionModelSwitch" not in overview
    assert "productionEligibilityPassed:" not in qml + overview
    assert "productionEvidencePassed &&" not in qml + overview
    bridge = (ROOT / "bridge" / "auth_mixin.py").read_text(encoding="utf-8")
    assert "def approveProductionModelSwitch" in bridge


if __name__ == "__main__":
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
        print("8 phase 07 user-approved model switch tests passed", flush=True)
    finally:
        _cleanup()
    os._exit(0)
