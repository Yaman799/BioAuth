from __future__ import annotations

import app_settings
import model_training


def test_phase6_candidate_artifacts_remain_enabled_outside_pytest_by_default(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("BIOAUTH_ENABLE_CANDIDATE_ARTIFACTS_IN_TESTS", raising=False)
    monkeypatch.setattr(app_settings, "load_settings", lambda: {}, raising=False)

    settings = model_training._candidate_training_settings()

    assert settings["enable_candidate_artifacts"] is True
    assert settings["enable_deep_candidate_artifacts"] is True
    assert settings["strict_candidate_training"] is False


def test_phase6_candidate_artifacts_default_off_during_pytest_unless_explicit(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_example.py::test_case (call)")
    monkeypatch.delenv("BIOAUTH_ENABLE_CANDIDATE_ARTIFACTS_IN_TESTS", raising=False)
    monkeypatch.setattr(app_settings, "load_settings", lambda: {}, raising=False)

    settings = model_training._candidate_training_settings()

    assert settings["enable_candidate_artifacts"] is False
    assert settings["enable_deep_candidate_artifacts"] is False
    assert settings["strict_candidate_training"] is False


def test_phase6_candidate_artifacts_test_env_override(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_example.py::test_case (call)")
    monkeypatch.setenv("BIOAUTH_ENABLE_CANDIDATE_ARTIFACTS_IN_TESTS", "1")
    monkeypatch.setattr(app_settings, "load_settings", lambda: {}, raising=False)

    settings = model_training._candidate_training_settings()

    assert settings["enable_candidate_artifacts"] is True
    assert settings["enable_deep_candidate_artifacts"] is True
