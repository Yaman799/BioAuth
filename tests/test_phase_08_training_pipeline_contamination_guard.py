from __future__ import annotations

from pathlib import Path

import pytest

from training_core.pipeline import _scan_positive_training_candidates
from training_core.selection import build_training_selection
from training_core.session_eligibility import assess_positive_training_session


def _base_meta(session_id: str = "s1", *, kind: str = "enrollment") -> dict:
    return {
        "session_id": session_id,
        "user_id": "alice",
        "session_kind": kind,
        "final_decision": "legit",
        "archive_label": "legit",
        "archive_group": "authorized",
        "bucket": "authorized",
        "metadata_trusted": True,
        "metadata_integrity": "verified",
        "metadata_inferred": False,
        "training_eligible": True,
        "keyboard_rows": 120,
        "mouse_rows": 40,
        "duration_seconds": 90.0,
    }


def _accepted(_path: str, meta: dict) -> bool:
    return str(meta.get("bucket") or meta.get("archive_group") or "").lower() in {"accepted", "authorized"}


def _quality(meta: dict) -> bool:
    return int(meta.get("keyboard_rows") or 0) + int(meta.get("mouse_rows") or 0) >= 20 and float(meta.get("duration_seconds") or 0.0) >= 6.0


def test_allowed_verified_enrollment_session_passes_contamination_guard(tmp_path: Path) -> None:
    session_dir = tmp_path / "alice_enrollment_legit_s1"
    session_dir.mkdir()
    result = assess_positive_training_session(
        _base_meta(),
        session_path=str(session_dir),
        user_id="alice",
        is_accepted_session_fn=_accepted,
        session_quality_ok_fn=_quality,
    )
    assert result["allowed"] is True
    assert result["reason_code"] == "allowed"


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"final_decision": "suspicious"}, "sensitive_decision_label"),
        ({"archive_label": "intruder"}, "sensitive_decision_label"),
        ({"metadata_trusted": False}, "metadata_not_trusted"),
        ({"metadata_integrity": "missing"}, "metadata_integrity_not_verified"),
        ({"metadata_inferred": True}, "metadata_inferred_only"),
        ({"user_id": "mallory"}, "session_user_mismatch"),
        ({"session_kind": "shadow"}, "unsupported_session_kind"),
        ({"collection_source": "shadow_evidence"}, "shadow_or_test_source"),
        ({"source": "hybrid_direct_test_monitor"}, "shadow_or_test_source"),
        ({"bundle_role": "candidate"}, "candidate_or_internal_state"),
        ({"candidate_only": True}, "blocked_flag_present"),
        ({"failed_evidence": True}, "blocked_flag_present"),
        ({"training_eligible": False}, "training_eligible_false"),
        ({"quality_ok": False}, "failed_or_low_quality_evidence"),
        ({"evidence_status": "failed"}, "failed_or_incomplete_evidence"),
    ],
)
def test_contaminated_positive_session_categories_are_denied(tmp_path: Path, updates: dict, reason: str) -> None:
    session_dir = tmp_path / "alice_enrollment_legit_s1"
    session_dir.mkdir()
    meta = _base_meta()
    meta.update(updates)
    result = assess_positive_training_session(
        meta,
        session_path=str(session_dir),
        user_id="alice",
        is_accepted_session_fn=_accepted,
        session_quality_ok_fn=_quality,
    )
    assert result["allowed"] is False
    assert result["reason_code"] == reason


def test_low_quality_session_is_denied_before_selection(tmp_path: Path) -> None:
    session_dir = tmp_path / "alice_enrollment_legit_lowq"
    session_dir.mkdir()
    meta = _base_meta("lowq")
    meta.update({"keyboard_rows": 2, "mouse_rows": 1, "duration_seconds": 2.0})
    result = assess_positive_training_session(
        meta,
        session_path=str(session_dir),
        user_id="alice",
        is_accepted_session_fn=_accepted,
        session_quality_ok_fn=_quality,
    )
    assert result["allowed"] is False
    assert result["reason_code"] == "session_quality_gate_failed"


def test_scan_positive_training_candidates_only_returns_trusted_verified_allowed_sessions(tmp_path: Path) -> None:
    allowed1 = tmp_path / "alice_enrollment_legit_allowed1"
    allowed2 = tmp_path / "alice_enrollment_legit_allowed2"
    suspicious = tmp_path / "alice_enrollment_suspicious_bad"
    shadow = tmp_path / "alice_enrollment_legit_shadow"
    unverified = tmp_path / "alice_enrollment_legit_unverified"
    low_quality = tmp_path / "alice_enrollment_legit_lowq"
    protected = tmp_path / "alice_protected_legit_p1"
    for item in (allowed1, allowed2, suspicious, shadow, unverified, low_quality, protected):
        item.mkdir()

    metas = {
        str(allowed1): _base_meta("allowed1"),
        str(allowed2): _base_meta("allowed2"),
        str(suspicious): {**_base_meta("bad"), "final_decision": "suspicious"},
        str(shadow): {**_base_meta("shadow"), "collection_source": "shadow_evidence"},
        str(unverified): {**_base_meta("unverified"), "metadata_integrity": "missing"},
        str(low_quality): {**_base_meta("lowq"), "keyboard_rows": 1, "mouse_rows": 1, "duration_seconds": 1.0},
        str(protected): _base_meta("p1", kind="protected"),
    }

    scanned = _scan_positive_training_candidates(
        safe="alice",
        min_sessions=2,
        mark_profile_state_fn=lambda _safe, _state: None,
        training_result_fn=lambda ok, key, message, **extra: {"ok": ok, "message_key": key, "message": message, **extra},
        user_session_paths_fn=lambda _safe: list(metas.keys()),
        read_session_metadata_fn=lambda path: metas[path],
        is_accepted_session_fn=_accepted,
        session_quality_ok_fn=_quality,
        report_progress_fn=lambda *_args, **_kwargs: None,
    )

    assert scanned["ok"] is True
    positives = [path for path, _meta in scanned["positive_candidates"]]
    assert positives == [str(allowed1), str(allowed2), str(protected)]
    assert str(suspicious) not in positives
    assert str(shadow) not in positives
    assert str(unverified) not in positives
    assert str(low_quality) not in positives
    assert scanned["enrollment_total"] == 2


def test_selection_rechecks_allowlist_and_drops_contaminated_positive_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clean = tmp_path / "alice_enrollment_legit_clean"
    contaminated = tmp_path / "alice_enrollment_legit_shadow"
    for item in (clean, contaminated):
        item.mkdir()

    def fake_quality_record(session_path: str, meta: dict, *, role: str, strict: bool) -> dict:
        return {
            "session_path": str(Path(session_path).absolute()),
            "session_name": Path(session_path).name,
            "session_kind": str(meta.get("session_kind") or "enrollment"),
            "role": role,
            "quality_score": 0.9,
            "quality_tier": "high",
            "quality_components": {},
            "quality_indicators": {"event_density": 8.0, "duration_seconds": 90.0},
            "activity_band": "mid",
            "duration_band": "high",
            "modality_band": "mixed",
            "training_eligible": True,
            "metadata_trusted": True,
            "window_budget": 8,
            "selection_score": 0.0,
            "selection_reason": "",
            "excluded": False,
            "exclusion_reason": None,
        }

    monkeypatch.setattr("training_core.selection._compute_session_quality_record", fake_quality_record)

    summary = build_training_selection(
        [
            (str(clean), _base_meta("clean")),
            (str(contaminated), {**_base_meta("shadow"), "collection_source": "shadow_evidence"}),
        ],
        [],
        max_enrollment_sessions=10,
    )

    assert summary["positive_sessions"] == [str(clean.absolute())]
    included_names = {item["session_name"] for item in summary["included_sessions"]}
    assert clean.name in included_names
    assert contaminated.name not in included_names
    assert summary["training_session_eligibility_version"].startswith("phase8-contamination-guard")
