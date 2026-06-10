from __future__ import annotations

import importlib.util
import json
import os
import pickle
import shutil
import sys
import tempfile
from pathlib import Path

TMP_HOME = tempfile.mkdtemp(prefix="bioauth_phase7_home_")
os.environ["HOME"] = TMP_HOME

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

# Standalone focused tests run with python -S in the delivery container, where
# third-party site packages are intentionally unavailable. Provide the tiny
# Fernet surface security.py needs for keyed HMAC sidecars; production code still
# uses the real cryptography package when the app runs normally.
import base64
import types

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
from metadata_core import auto_promotion
from metadata_core.auto_promotion import auto_promotion_block_reason, approve_production_model_switch, safe_auto_promote_production_bundle
from metadata_core.constants import ACTIVE_WINDOW_SCALES, FEATURE_SCHEMA_VERSION, FEATURE_WINDOW_STRATEGY
from metadata_core.paths import _active_runtime_pointer_path, _user_model_paths, _user_production_paths
from metadata_core.runtime import resolve_active_runtime_paths_with_validation, validate_runtime_bundle_for_activation
from security import atomic_write_text, save_metadata_hash, save_model_hash

_restore_test_stubs_and_uncache(
    "artifact_integrity",
    "evaluation_core.production_evidence",
    "metadata_core.auto_promotion",
    "metadata_core.constants",
    "metadata_core.paths",
    "metadata_core.runtime",
    "security",
)


def _security_helpers():
    import security as _security

    return _security


def _cleanup() -> None:
    shutil.rmtree(TMP_HOME, ignore_errors=True)


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
        "policy_details": {
            "gate_results": {"minimum_support": True, "f1": True, "far": True, "frr": True, "precision": True, "recall": True, "auc": True},
            "safety_gate_results": {"safety_metrics_present": True, "false_lock_count": True, "warning_per_hour": True, "low_quality_decision_rate": True, "data_coverage": True, "raw_data_absent": True},
        },
        "candidate_artifact_digest": "sha256:auto-promotion-candidate",
        "baseline_artifact_digest": "sha256:auto-promotion-baseline",
        "evaluation_report_digest": "sha256:auto-promotion-eval",
        "runtime_schema_version": "runtime-schema-v1",
        "rollback_ready": True,
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
        _security_helpers().atomic_write_text(paths["evaluation_report"], json.dumps({"primary_evaluation": "candidate_bundle", "evaluations": {"candidate_bundle": {"metrics": {"f1": 0.99}}}}, indent=2))
        _security_helpers().atomic_write_text(paths["evaluation_summary"], "candidate evaluation summary\n")


def _settings(enabled: bool = True) -> dict:
    return {"auto_promote_when_production_safe_enabled": enabled}


def test_approved_for_shadow_never_promotes() -> None:
    assert auto_promotion_block_reason(
        settings=_settings(True),
        candidate_metadata=_metadata(status="approved_for_shadow"),
        runtime_validation={"ok": False},
    ) == "model_not_approved_for_production"


def test_approved_for_production_waits_for_user_approval_before_switch() -> None:
    user = "phase7_valid"
    candidate = _user_model_paths(user)
    _write_bundle(candidate, metadata=_metadata())
    result = safe_auto_promote_production_bundle(user, settings=_settings(True), runtime_validation={"ok": False})
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["reason"] == "production_ready_pending_user_approval"
    assert result["productionReadyPendingUserApproval"] is True
    assert result["protectedSessionsAvailable"] is False
    assert not os.path.exists(_active_runtime_pointer_path(user))


def test_invalid_runtime_metadata_blocks_promotion() -> None:
    user = "phase7_bad_metadata"
    candidate = _user_model_paths(user)
    _write_bundle(candidate, metadata=_metadata(schema="old-schema"))
    result = safe_auto_promote_production_bundle(user, settings=_settings(True), runtime_validation={"ok": False})
    assert result["ok"] is False
    assert result["changed"] is False
    assert "staging_runtime_invalid" in result["reason"]
    assert result["protectedSessionsAvailable"] is False


def test_missing_required_artifact_blocks_promotion() -> None:
    user = "phase7_missing_artifact"
    candidate = _user_model_paths(user)
    _write_bundle(candidate, metadata=_metadata(), include_model=False)
    result = safe_auto_promote_production_bundle(user, settings=_settings(True), runtime_validation={"ok": False})
    assert result["ok"] is False
    assert result["changed"] is False
    assert "missing_artifact:model" in result["reason"]
    assert result["protectedSessionsAvailable"] is False


def test_auto_promotion_requires_enabled_setting() -> None:
    user = "phase7_disabled"
    candidate = _user_model_paths(user)
    _write_bundle(candidate, metadata=_metadata())
    result = safe_auto_promote_production_bundle(user, settings=_settings(False), runtime_validation={"ok": False})
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["reason"] == "auto_promotion_disabled"
    assert not os.path.exists(_active_runtime_pointer_path(user))


def test_rollback_restores_existing_production_bundle_when_user_approved_pointer_write_fails() -> None:
    user = "phase7_rollback"
    candidate = _user_model_paths(user)
    meta = _metadata()
    _write_bundle(candidate, metadata=meta)
    production = _user_production_paths(user)
    original_meta = _metadata(role="production")
    original_meta["marker"] = "original-production"
    _write_bundle(production, metadata=original_meta)
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


def test_start_protected_session_and_qml_remain_backend_gated() -> None:
    runtime_helper = (ROOT / "bridge" / "session_runtime_helpers.py").read_text(encoding="utf-8")
    desktop = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    refresh = (ROOT / "bridge" / "refresh_runtime_helpers.py").read_text(encoding="utf-8")
    profile_qml = (ROOT / "qml" / "pages" / "ProfilePage.qml").read_text(encoding="utf-8")
    settings_qml = (ROOT / "qml" / "pages" / "settings" / "SettingsPerformanceTab.qml").read_text(encoding="utf-8")
    live_qml = (ROOT / "qml" / "components" / "LiveTelemetryPanel.qml").read_text(encoding="utf-8")
    assert "profile.get(\"production_ready\")" in runtime_helper
    assert "safe_auto_promote_production_bundle" in (ROOT / "bridge" / "session_promotion_helpers.py").read_text(encoding="utf-8")
    assert "_maybe_auto_promote_production" in refresh
    assert "backend.productionApprovalState" in profile_qml
    assert "productionReady:" not in profile_qml
    assert "protectedSessionsAvailable:" not in profile_qml
    assert "autoPromotion" in profile_qml
    assert "autoPromotion" in settings_qml
    assert "autoPromotion" in live_qml
    assert "def productionApprovalState" in desktop
    assert "autoPromotionState" in desktop


def test_production_ready_is_backend_owned_after_user_approved_validation_only() -> None:
    user = "phase7_backend_owned"
    candidate = _user_model_paths(user)
    meta = _metadata()
    _write_bundle(candidate, metadata=meta)
    preview = safe_auto_promote_production_bundle(user, settings=_settings(True), runtime_validation={"ok": False})
    assert preview["reason"] == "production_ready_pending_user_approval"
    result = approve_production_model_switch(user, meta["candidate_artifact_digest"], user_approved=True)
    assert result["ok"] is True
    production = _user_production_paths(user)
    validation = validate_runtime_bundle_for_activation(production)
    assert validation["ok"] is True
    assert validation["metadata"]["bundle_role"] == "production"
    assert validation["metadata"]["model_status"] == "approved_for_production"
    assert validation["metadata"]["user_approved_model_switch"] is True


if __name__ == "__main__":
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
        print("8 focused safe auto/user-approved promotion phase7 tests passed", flush=True)
    finally:
        _cleanup()
    os._exit(0)
