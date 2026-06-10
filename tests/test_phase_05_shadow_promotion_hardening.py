from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

import metadata_core.auto_promotion as auto_promotion
import metadata_core.runtime as runtime
import shadow_core.promotion as shadow_promotion
from bridge.i18n import translate_backend_result


@contextlib.contextmanager
def _null_context(*_args, **_kwargs):
    yield


def test_promote_shadow_model_is_deprecated_evidence_only_contract(monkeypatch):
    events: list[tuple[str, dict]] = []

    class ForbiddenShadowFacade:
        def copy_verified_temp(self, *_args, **_kwargs):  # pragma: no cover - must not be reached
            raise AssertionError("shadow promotion must not copy artifacts into production")

        def load_model(self, *_args, **_kwargs):  # pragma: no cover - must not be reached
            raise AssertionError("shadow promotion must not load a shadow model as production")

    monkeypatch.setattr(shadow_promotion, "_shadow_facade", lambda: ForbiddenShadowFacade())
    monkeypatch.setattr(shadow_promotion, "user_model_lifecycle_lock", lambda _user_id: _null_context())
    monkeypatch.setattr(shadow_promotion, "_shadow_lock", lambda _user_id: _null_context())
    monkeypatch.setattr(shadow_promotion, "SHADOW_EVAL_SESSIONS", 3)
    monkeypatch.setattr(shadow_promotion, "SHADOW_MIN_SESSIONS", 3)
    monkeypatch.setattr(
        shadow_promotion,
        "_read_shadow_state",
        lambda _user_id: {
            "phase": "ready",
            "promote_suggested": True,
            "candidate_sessions": ["s1", "s2", "s3"],
            "eval_deltas": [3.0, 4.0, 5.0],
            "total_eval_count": 3,
            "avg_delta": 4.0,
        },
    )
    monkeypatch.setattr(
        shadow_promotion,
        "log_shadow_event",
        lambda user_id, event_type, **fields: events.append((event_type, fields)),
    )

    result = shadow_promotion.promote_shadow_model("alice")

    assert result["ok"] is False
    assert result["message_key"] == "shadow_promotion_evidence_only"
    assert result["evidence_only"] is True
    assert result["shadow_only"] is True
    assert result["deprecated_direct_activation"] is True
    assert result["production_activation_blocked"] is True
    assert result["requires_status"] == "approved_for_production"
    assert result["requires_user_approval"] is True
    assert result["rollback_required"] is True
    assert result["changed"] is False
    assert result["active_runtime_pointer_written"] is False
    assert result["protectedSessionsAvailable"] is False
    assert result["production_state_changed"] is False
    assert len(events) == 1
    assert events[0][0] == "promotion_blocked"
    assert events[0][1]["reason"] == "shadow_promotion_evidence_only"
    assert events[0][1]["promotion_effect"] == "shadow_only"


def test_approved_for_shadow_cannot_auto_promote_or_touch_pointer(monkeypatch, tmp_path):
    pointer = tmp_path / "active_runtime_pointer.json"
    pointer.write_text('{"source":"existing_production"}', encoding="utf-8")
    monkeypatch.setattr(auto_promotion, "_active_runtime_pointer_path", lambda _user_id: str(pointer))

    def forbidden_writer(*_args, **_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("shadow-only metadata must not write the active production pointer")

    monkeypatch.setattr(auto_promotion, "write_active_runtime_pointer", forbidden_writer)

    result = auto_promotion.safe_auto_promote_production_bundle(
        "alice",
        settings={"auto_promote_when_production_safe_enabled": True},
        candidate_paths={
            "base": str(tmp_path / "candidate"),
            "model": str(tmp_path / "candidate" / "model.pkl"),
            "metadata": str(tmp_path / "candidate" / "metadata.json"),
            "classifier": str(tmp_path / "candidate" / "classifier.pkl"),
        },
        candidate_metadata={"model_status": "approved_for_shadow"},
        runtime_validation={"ok": False, "reason": "runtime_pointer_missing"},
        authenticated=True,
        training_active=False,
        session_flow="idle",
        app_locked=False,
    )

    assert result["ok"] is False
    assert result["changed"] is False
    assert result["reason"] == "model_not_approved_for_production"
    assert result["protectedSessionsAvailable"] is False
    assert pointer.read_text(encoding="utf-8") == '{"source":"existing_production"}'


def test_runtime_pointer_rejects_shadow_promote_sources_even_when_validation_is_mocked_ok(monkeypatch, tmp_path):
    model_root = tmp_path / "models" / "alice"
    pointer = model_root / "active_runtime_pointer.json"
    production_base = model_root / "production_bundle"
    bundle_paths = {
        "base": str(production_base),
        "model": str(production_base / "model.pkl"),
        "classifier": str(production_base / "classifier.pkl"),
        "metadata": str(production_base / "metadata.json"),
        "evaluation_report": str(production_base / "evaluation_report.json"),
        "evaluation_summary": str(production_base / "evaluation_summary.md"),
    }
    monkeypatch.setattr(runtime, "_user_model_dir", lambda _user_id: str(model_root))
    monkeypatch.setattr(runtime, "_active_runtime_pointer_path", lambda _user_id: str(pointer))
    monkeypatch.setattr(
        runtime,
        "validate_runtime_bundle_for_activation",
        lambda _paths: {"ok": True, "reason": "ok", "artifact_identity": {"metadata_sha256": "sha256:prod"}},
    )

    for source in ("shadow_promotion", "promoteShadowModel", "approved_for_shadow", "candidate_shadow_review"):
        with pytest.raises(ValueError, match="active_runtime_pointer_requires_explicit_production_source"):
            runtime.write_active_runtime_pointer("alice", bundle_paths, source=source)

    assert not pointer.exists()


def test_shadow_promotion_copy_has_safe_backend_and_qml_wording():
    overview = Path("qml/pages/OverviewPage.qml").read_text(encoding="utf-8")
    profile = Path("qml/pages/ProfilePage.qml").read_text(encoding="utf-8")
    main = Path("qml/Main.qml").read_text(encoding="utf-8")
    i18n = Path("bridge/i18n.py").read_text(encoding="utf-8")
    auth = Path("bridge/auth_mixin.py").read_text(encoding="utf-8")

    forbidden_shadow_phrases = [
        "Shadow model is ready to activate",
        "The shadow model has shown sustained improvement and can now be activated manually",
        "Activate new model",
        "Activate it now",
        "Activate now",
        "Shadow model activated successfully",
    ]
    combined = "\n".join([overview, main, i18n])
    for phrase in forbidden_shadow_phrases:
        assert phrase not in combined

    assert "Shadow phase" in profile
    assert "Review shadow evidence" not in overview
    assert "cannot activate production until production approval" in main
    message = translate_backend_result("en", {"message_key": "shadow_promotion_evidence_only"})
    assert "Shadow validation is evidence-only" in message
    assert "approved_for_production" in message
    assert '"info" if safe_shadow_only else "danger"' in auth
