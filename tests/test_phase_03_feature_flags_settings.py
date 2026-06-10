from __future__ import annotations

from pathlib import Path

import app_settings
import bio_platform.secrets as secret_backend
import security


EXPECTED_PHASE_03_FLAGS = {
    "enable_user_shell",
    "enable_manual_model_switch",
    "enable_face_confirmation",
    "enable_face_enrollment",
    "enable_shadow_feedback_from_face",
    "enable_release_autoupdate",
    "enable_startup_protected_sessions_after_build",
}


def _configure_settings_storage(tmp_path: Path, monkeypatch) -> Path:
    settings_path = tmp_path / "settings.json"
    model_dir = tmp_path / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(secret_backend, "keyring", None)
    monkeypatch.setattr(security, "MODELS_DIR", str(model_dir))
    monkeypatch.setattr(security, "KEY_FILE", str(model_dir / "secret.key"))
    monkeypatch.setattr(security, "KEY_FILE_DPAPI", str(model_dir / "secret.key.dpapi"))
    security.reset_security_caches()
    monkeypatch.setattr(app_settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_settings, "SETTINGS_FILE", str(settings_path))
    with app_settings._SETTINGS_LOCK:
        app_settings._SETTINGS_CACHE = None
    return settings_path


def test_phase_03_feature_flags_exist_and_default_safe_off() -> None:
    assert set(app_settings.FEATURE_FLAG_KEYS) == EXPECTED_PHASE_03_FLAGS
    assert set(app_settings.FEATURE_FLAG_DEFAULTS) == EXPECTED_PHASE_03_FLAGS

    payload = app_settings._coerce_settings_payload({})

    # Commercial default (Phase 2): enable_user_shell=True so the product ships
    # with the real user interface active.  All other feature flags remain off by
    # default (experimental or privacy-sensitive features).
    assert payload["enable_user_shell"] is True, (
        "enable_user_shell must default True in commercial builds (Phase 2 audit fix)"
    )
    for key in EXPECTED_PHASE_03_FLAGS - {"enable_user_shell"}:
        assert app_settings.DEFAULT_SETTINGS[key] is False, f"{key} must default to False"
        assert payload[key] is False, f"coerced {key} must be False"
        assert app_settings.feature_flag_enabled(payload, key) is False


def test_old_settings_payloads_are_backfilled_without_activating_features() -> None:
    old_payload = {
        "theme": "light",
        "run_on_startup": True,
        "remember_login_enabled": True,
    }

    migrated = app_settings._coerce_settings_payload(old_payload)

    assert migrated["theme"] == "light"
    assert migrated["run_on_startup"] is True
    assert migrated["remember_login_enabled"] is True
    assert app_settings.normalize_feature_flags(migrated) == dict(app_settings.FEATURE_FLAG_DEFAULTS)


def test_feature_flags_persist_when_explicitly_saved(monkeypatch, tmp_path) -> None:
    _configure_settings_storage(tmp_path, monkeypatch)

    saved = app_settings.save_settings(
        {
            "enable_manual_model_switch": True,
            "enable_face_enrollment": True,
            "enable_release_autoupdate": False,
        }
    )
    assert saved["enable_manual_model_switch"] is True
    assert saved["enable_face_enrollment"] is True
    assert saved["enable_release_autoupdate"] is False

    with app_settings._SETTINGS_LOCK:
        app_settings._SETTINGS_CACHE = None
    loaded = app_settings.load_settings()

    assert loaded["enable_manual_model_switch"] is True
    assert loaded["enable_face_enrollment"] is True
    assert loaded["enable_release_autoupdate"] is False
    assert app_settings.feature_flag_enabled(loaded, "enable_manual_model_switch") is True


def test_invalid_feature_flag_values_fail_closed_without_crashing() -> None:
    payload = app_settings._coerce_settings_payload(
        {
            "enable_user_shell": "not-a-bool",
            "enable_manual_model_switch": {"enabled": True},
            "enable_face_confirmation": [True],
            "enable_face_enrollment": 42,
            "enable_shadow_feedback_from_face": None,
            "enable_release_autoupdate": "disabled",
            "enable_startup_protected_sessions_after_build": "enabled",
        }
    )

    # enable_user_shell: "not-a-bool" is not a recognised bool string,
    # so _coerce_safe_bool falls back to the per-flag default (True since Phase 2).
    assert payload["enable_user_shell"] is True
    assert payload["enable_manual_model_switch"] is False
    assert payload["enable_face_confirmation"] is False
    assert payload["enable_face_enrollment"] is False
    assert payload["enable_shadow_feedback_from_face"] is False
    assert payload["enable_release_autoupdate"] is False
    assert payload["enable_startup_protected_sessions_after_build"] is True


def test_unknown_feature_flags_are_ignored_and_disabled() -> None:
    payload = app_settings._coerce_settings_payload(
        {
            "enable_user_shell": False,
            "enable_unreviewed_future_feature": True,
        }
    )

    assert "enable_unreviewed_future_feature" in payload
    assert "enable_unreviewed_future_feature" not in app_settings.normalize_feature_flags(payload)
    assert app_settings.feature_flag_enabled(payload, "enable_unreviewed_future_feature") is False


def test_qml_does_not_compute_backend_owned_readiness_or_eligibility_locally() -> None:
    """QML may display backend-owned flags, but must not invent safety readiness.

    Later phases legitimately expose UI mode and feature-flag state in QML. The
    invariant from Phase 03 is narrower: production/model/protected-session
    readiness and approval eligibility remain backend-owned decisions.
    """
    import re

    qml_root = Path(__file__).resolve().parents[1] / "qml"
    qml_files = list(qml_root.rglob("*.qml"))
    qml_sources = {path: path.read_text(encoding="utf-8") for path in qml_files}
    combined = "\n".join(qml_sources.values())

    # Backend-owned flags may be surfaced in QML copy/bindings now, but QML must
    # not call the Python helper directly or locally recompute feature flag state.
    assert "feature_flag_enabled(" not in combined

    readiness_assignment = re.compile(
        r"\b(?:var|let|const|property\s+(?:bool|var|string|int|real))\s+"
        r"(?:productionReady|modelReady|protectedSessionsReady|protectedSessionsAvailable|"
        r"evidenceGateReady|approvalEligible|productionEligible|modelReadinessReady)\b\s*=\s*(.+)",
        re.IGNORECASE,
    )
    suspicious_terms = re.compile(
        r"(training|evidence|gate|approval|approved|production|model|runtime|shadow|"
        r"protectedSessions|protected_sessions|ready|readiness|threshold)",
        re.IGNORECASE,
    )
    local_boolean_mix = re.compile(r"(&&|\|\||\?|===|!==|==|!=|>=|<=|>|<)")

    offenders: list[str] = []
    for path, source in qml_sources.items():
        for line_no, line in enumerate(source.splitlines(), start=1):
            match = readiness_assignment.search(line)
            if not match:
                continue
            expression = match.group(1)
            if suspicious_terms.search(expression) and local_boolean_mix.search(expression):
                offenders.append(f"{path.relative_to(qml_root.parent)}:{line_no}: {line.strip()}")

    assert offenders == []

    forbidden_local_functions = re.compile(
        r"function\s+(?:compute|derive|calculate|resolve)?"
        r"(?:Production|Model|ProtectedSessions|EvidenceGate|Approval)"
        r"(?:Ready|Readiness|Eligible|Eligibility|Available)\s*\(",
        re.IGNORECASE,
    )
    function_offenders = [
        f"{path.relative_to(qml_root.parent)}"
        for path, source in qml_sources.items()
        if forbidden_local_functions.search(source)
    ]
    assert function_offenders == []
