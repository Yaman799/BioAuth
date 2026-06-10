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

TMP_HOME = tempfile.mkdtemp(prefix="bioauth_phase9_home_")
os.environ["HOME"] = TMP_HOME

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

# Standalone focused tests are run with python -S in the delivery container.
# Provide tiny test doubles for optional third-party/platform modules that are
# not part of the safety invariants under review.
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

if True:  # scoped import stub, restored below
    utils_mod = types.ModuleType("utils")
    identity_mod = types.ModuleType("utils.identity")

    def _slugify_username(value: object) -> str:
        text = str(value or "").strip().lower()
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)
        return safe or "user"

    identity_mod.slugify_username = _slugify_username
    utils_mod.identity = identity_mod
    _install_test_stub("utils", utils_mod)
    _install_test_stub("utils.identity", identity_mod)

from evaluation_core.production_evidence import build_production_evidence_report
from metadata_core.auto_enrollment import build_auto_enrollment_state, passive_collection_should_start
from metadata_core.auto_promotion import auto_promotion_block_reason, approve_production_model_switch, safe_auto_promote_production_bundle
from metadata_core.auto_training_scheduler import auto_training_should_start, training_readiness_signature
from metadata_core.constants import ACTIVE_WINDOW_SCALES, FEATURE_SCHEMA_VERSION, FEATURE_WINDOW_STRATEGY
from metadata_core.model_readiness import build_model_readiness_state
from metadata_core.paths import _user_model_paths
from metadata_core.production_approval import build_production_approval_state
from metadata_core.runtime import resolve_active_runtime_paths_with_validation
from security import atomic_write_text, save_metadata_hash, save_model_hash

_restore_test_stubs_and_uncache(
    "artifact_integrity",
    "evaluation_core.production_evidence",
    "metadata_core.auto_enrollment",
    "metadata_core.auto_promotion",
    "metadata_core.auto_training_scheduler",
    "metadata_core.constants",
    "metadata_core.model_readiness",
    "metadata_core.paths",
    "metadata_core.production_approval",
    "metadata_core.runtime",
    "security",
)

QML_FILES = [
    ROOT / "qml" / "pages" / "ProfilePage.qml",
    ROOT / "qml" / "pages" / "HistoryPage.qml",
    ROOT / "qml" / "pages" / "settings" / "SettingsSecurityTab.qml",
    ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml",
    ROOT / "qml" / "components" / "LiveTelemetryPanel.qml",
]


def _security_helpers():
    import security as _security

    return _security


def _cleanup() -> None:
    # Avoid slow recursive cleanup on constrained delivery filesystems.
    # The temp home is isolated per test process and discarded by the container.
    return None


def _settings(*, auto_enroll: bool = True, auto_train: bool = True, auto_promote: bool = True) -> dict:
    return {
        "smart_auto_enrollment_enabled": auto_enroll,
        "auto_train_when_ready_enabled": auto_train,
        "auto_promote_when_production_safe_enabled": auto_promote,
    }


def _trusted_session(session_id: str, *, keyboard_rows: int = 80, mouse_rows: int = 80, bucket: str = "accepted", time_bucket: str = "morning") -> dict:
    return {
        "session_id": session_id,
        "session_kind": "enrollment",
        "training_counts_toward_minimum": True,
        "metadata_trusted": True,
        "bucket": bucket,
        "keyboard_rows": keyboard_rows,
        "mouse_rows": mouse_rows,
        "time_of_day_bucket": time_bucket,
        "created_at": "2026-04-29 08:00:00",
    }


def _rejected_session(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "session_kind": "enrollment",
        "training_counts_toward_minimum": False,
        "metadata_trusted": False,
        "bucket": "rejected",
        "keyboard_rows": 100,
        "mouse_rows": 100,
    }


def _passing_production_evidence() -> dict:
    return build_production_evidence_report(
        candidate_artifact_digest="sha256:auto-promotion-candidate",
        baseline_artifact_digest="sha256:auto-promotion-baseline",
        evaluation_report_digest="sha256:auto-promotion-eval",
        runtime_schema_version="runtime-schema-v1",
        model_comparison_windows=[
            {"window_id": f"w{idx}", "candidate_decision": "trusted", "baseline_decision": "trusted", "trusted_window": True}
            for idx in range(4)
        ],
        post_unlock_windows=[
            {"window_id": f"u{idx}", "trusted_window": True, "warning_triggered": False, "simulated_false_lock": False, "feature_quality_ok": True}
            for idx in range(3)
        ],
        confirmed_intruder_events=[],
        runtime_decision_summaries=[
            {"decision_id": f"r{idx}", "truth": "owner", "candidate_decision": "trusted", "unknown": False, "simulated_false_lock": False, "feature_quality_ok": True}
            for idx in range(4)
        ],
    ).to_dict()


def _metadata(*, status: str = "approved_for_production", role: str = "candidate", schema: str = FEATURE_SCHEMA_VERSION) -> dict:
    return {
        "model_status": status,
        "bundle_role": role,
        "feature_schema_version": schema,
        "feature_window_strategy": FEATURE_WINDOW_STRATEGY,
        "active_window_scales": list(ACTIVE_WINDOW_SCALES),
        "candidate_artifact_digest": "sha256:auto-promotion-candidate",
        "baseline_artifact_digest": "sha256:auto-promotion-baseline",
        "evaluation_report_digest": "sha256:auto-promotion-eval",
        "runtime_schema_version": "runtime-schema-v1",
        "rollback_ready": True,
        "policy_details": {
            "gate_results": {"minimum_support": True, "f1": True, "far": True, "frr": True, "precision": True, "recall": True, "auc": True},
            "safety_gate_results": {"safety_metrics_present": True, "false_lock_count": True, "warning_per_hour": True, "low_quality_decision_rate": True, "data_coverage": True, "raw_data_absent": True},
        },
        "rollout_status": "classic_only_ready",
        "rollout_details": {"allowed_modes": ["classic", "auto"], "rollback_to_classic_on_failure": True},
        "production_evidence": _passing_production_evidence() if status == "approved_for_production" else {},
    }


def _write_bundle(paths: dict, *, metadata: dict | None = None, include_model: bool = True, include_report: bool = True) -> None:
    os.makedirs(paths["base"], exist_ok=True)
    if include_model:
        Path(paths["model"]).write_bytes(pickle.dumps({"kind": "model", "path": paths["model"]}))
        _security_helpers().save_model_hash(paths["model"])
    if metadata is not None:
        _security_helpers().atomic_write_text(paths["metadata"], json.dumps(metadata, indent=2, ensure_ascii=False))
        _security_helpers().save_metadata_hash(paths["metadata"])
    if include_report:
        _security_helpers().atomic_write_text(paths["evaluation_report"], json.dumps({"evaluations": {"candidate_bundle": {"metrics": {"f1": 0.99}}}}, indent=2))
        _security_helpers().atomic_write_text(paths["evaluation_summary"], "candidate evaluation summary\n")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_no_consent_blocks_passive_enrollment() -> None:
    should_start, reason = passive_collection_should_start(
        settings=_settings(auto_enroll=True),
        profile={"production_ready": False, "session_count": 0, "recommended_session_count": 15},
        runtime_state={},
        sessions=[],
        consent_satisfied=False,
        authenticated=True,
    )
    state = build_auto_enrollment_state(
        settings=_settings(auto_enroll=True),
        profile={},
        sessions=[],
        consent_satisfied=False,
        collecting=True,
        collection_block_reason=reason,
    )
    assert should_start is False
    assert reason == "consent_required"
    assert state["collecting"] is False
    assert state["consentSatisfied"] is False
    assert "privacy consent" in state["collectionStatusText"].lower()


def test_consent_and_enabled_allow_backend_collection_state() -> None:
    should_start, reason = passive_collection_should_start(
        settings=_settings(auto_enroll=True),
        profile={"production_ready": False, "session_count": 0, "minimum_session_count": 8, "recommended_session_count": 15},
        runtime_state={},
        sessions=[],
        consent_satisfied=True,
        authenticated=True,
    )
    state = build_auto_enrollment_state(
        settings=_settings(auto_enroll=True),
        profile={"training_can_start": False, "minimum_session_count": 8, "recommended_session_count": 15},
        sessions=[],
        consent_satisfied=True,
        collecting=should_start,
        collection_block_reason=reason,
    )
    assert should_start is True
    assert reason == "ready"
    assert state["enabled"] is True
    assert state["collecting"] is True
    assert "quality gates" in state["collectionStatusText"].lower()


def test_accepted_sessions_count_only_existing_quality_gate_outputs() -> None:
    sessions = [
        _trusted_session("trusted-1", keyboard_rows=90, mouse_rows=90, time_bucket="morning"),
        _trusted_session("trusted-1", keyboard_rows=90, mouse_rows=90, time_bucket="morning"),
        _rejected_session("rejected-1"),
        {"session_id": "protected-1", "session_kind": "protected", "training_counts_toward_minimum": True},
    ]
    state = build_auto_enrollment_state(
        settings=_settings(auto_enroll=True),
        profile={"training_can_start": False, "minimum_session_count": 2, "recommended_session_count": 4},
        sessions=sessions,
        consent_satisfied=True,
        collecting=False,
    )
    assert state["acceptedSessions"] == 1
    assert state["timeOfDayCoverage"]["morning"] == 1
    assert state["inputCoverage"]["keyboard"] in {"partial", "strong"}
    assert state["inputCoverage"]["mixed"] in {"partial", "strong"}


def test_shadow_only_blocks_protected_sessions_and_enters_safe_readiness() -> None:
    production_state = build_production_approval_state(
        candidate_paths={},
        candidate_metadata={"model_status": "approved_for_shadow", "approval_reason": "production margins were not met"},
        runtime_validation={"ok": False, "reason": "model_not_approved_for_production"},
    )
    readiness = build_model_readiness_state(
        profile={"training_can_start": True, "session_count": 8},
        production_approval=production_state,
        sessions=[_trusted_session("trusted-shadow")],
    )
    assert production_state["modelStatus"] == "approved_for_shadow"
    assert production_state["protectedSessionsAvailable"] is False
    assert production_state["productionReady"] is False
    assert readiness["productionReady"] is False
    assert readiness["nextBestAction"] in {"collect_diverse_high_quality_sessions", "continue_shadow_validation_collect_targeted_sessions"}


def test_shadow_only_never_auto_promotes() -> None:
    reason = auto_promotion_block_reason(
        settings=_settings(auto_promote=True),
        candidate_metadata=_metadata(status="approved_for_shadow"),
        runtime_validation={"ok": False},
    )
    assert reason == "model_not_approved_for_production"


def test_production_approved_valid_bundle_requires_user_approval_before_unlock_backend_state() -> None:
    user = "phase9_valid_bundle"
    candidate = _user_model_paths(user)
    metadata = _metadata()
    _write_bundle(candidate, metadata=metadata)
    preview = safe_auto_promote_production_bundle(user, settings=_settings(auto_promote=True), runtime_validation={"ok": False})
    assert preview["ok"] is False
    assert preview["changed"] is False
    assert preview["reason"] == "production_ready_pending_user_approval"
    assert preview["protectedSessionsAvailable"] is False
    assert preview["requiresUserApproval"] is True
    paths, validation = resolve_active_runtime_paths_with_validation(user)
    assert paths is None
    assert validation["ok"] is False

    approved = approve_production_model_switch(user, metadata["candidate_artifact_digest"], user_approved=True)
    assert approved["ok"] is True
    assert approved["changed"] is True
    assert approved["protectedSessionsAvailable"] is True
    paths, validation = resolve_active_runtime_paths_with_validation(user)
    assert paths is not None
    assert validation["ok"] is True
    production_state = build_production_approval_state(
        candidate_paths=candidate,
        candidate_metadata=metadata,
        runtime_validation=validation,
        runtime_paths=paths,
    )
    assert production_state["modelStatus"] == "approved_for_production"
    assert production_state["protectedSessionsAvailable"] is True


def test_invalid_runtime_bundle_blocks_auto_promotion() -> None:
    user = "phase9_invalid_bundle"
    candidate = _user_model_paths(user)
    _write_bundle(candidate, metadata=_metadata(schema="old-schema"))
    result = safe_auto_promote_production_bundle(user, settings=_settings(auto_promote=True), runtime_validation={"ok": False})
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["protectedSessionsAvailable"] is False
    assert "staging_runtime_invalid" in result["reason"]


def test_repeated_training_loop_is_prevented_for_same_trusted_data() -> None:
    profile = {"training_can_start": True, "session_count": 2, "minimum_session_count": 2, "recommended_session_count": 4}
    sessions = [_trusted_session("train-1"), _trusted_session("train-2")]
    signature = training_readiness_signature(user_id="phase9_user", profile=profile, sessions=sessions)
    should_start, reason, returned_signature = auto_training_should_start(
        settings=_settings(auto_enroll=True, auto_train=True),
        profile=profile,
        runtime_state={},
        sessions=sessions,
        user_id="phase9_user",
        consent_satisfied=True,
        authenticated=True,
        training_active=False,
        session_flow="idle",
        last_completed_signature=signature,
    )
    assert returned_signature == signature
    assert should_start is False
    assert reason == "already_trained_for_current_data"


def test_qml_backend_owned_state_and_privacy_transparency_are_visible() -> None:
    combined = "\n".join(_read(path) for path in QML_FILES)
    for forbidden in [
        "productionReady:",
        "protectedSessionsAvailable:",
        "modelStatus:",
        "failedProductionGates:",
        "activeRoutedContexts:",
    ]:
        assert forbidden not in combined
    assert "backend.autoEnrollmentState" in combined
    assert "backend.modelReadinessState" in combined
    assert "backend.productionApprovalState" in combined
    assert "Requires explicit privacy consent" in combined
    assert "Learning your behavior" in combined or "learns your natural behavior" in combined
    assert "BioAuth is validating your protection model safely in the background." in combined
    assert "Protected Sessions stay locked until production approval passes" in combined
    assert "Fallback reason" in combined
    assert "force approved_for_production" not in combined.lower()


def test_start_protected_session_stays_backend_gated() -> None:
    runtime_helper = _read(ROOT / "bridge" / "session_runtime_helpers.py")
    profile_qml = _read(ROOT / "qml" / "pages" / "ProfilePage.qml")
    assert "profile.get(\"production_ready\")" in runtime_helper
    assert "Protected Sessions are ready" in profile_qml
    assert "startProtectedSession" not in profile_qml
    assert "protectedSessionsAvailable:" not in profile_qml


if __name__ == "__main__":
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
        print("10 focused auto readiness final gate phase9 tests passed", flush=True)
    finally:
        _cleanup()
    raise SystemExit(0)
