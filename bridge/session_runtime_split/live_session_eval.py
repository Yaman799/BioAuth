"""Extracted implementation section for `bridge/session_runtime_helpers.py`."""
from __future__ import annotations
import json
import logging
import os
import re
import signal
import threading
import time
from collections import deque
from importlib import import_module
from typing import Any, Dict, List, Optional
from release_runtime import startup_protected_session_decision, write_release_runtime_event

def run_hybrid_direct_test(self) -> Dict[str, Any]:  # [FLOW: DEVELOPER — requires BIOAUTH_HYBRID_TEST_ONLY]
    """Run backend-owned offline replay candidate evaluation for Hybrid Direct Test.

    This is the button/slot path. It is offline/replay/report-only and never
    starts the old monitor smoke subprocess, locks the device, triggers Face
    Confirmation, modifies production pointers, trains models, or enables live
    candidate influence.
    """

    report_path = _hybrid_direct_test_report_path(self)
    result = _hybrid_removed_from_commercial_flow_payload(self, report_path=report_path)
    setattr(self, "_latest_hybrid_direct_test_result", result)
    setattr(self, "_hybrid_direct_test_running", False)
    signal = getattr(self, "hybridDirectChanged", None)
    if signal is not None and hasattr(signal, "emit"):
        signal.emit()
    try:
        self._set_status("Hybrid Direct Test has been removed from the commercial training flow.", "info")
    except Exception:
        pass
    return dict(result)

    blockers = hybrid_direct_test_blockers(self)
    report_path = _hybrid_direct_test_report_path(self)
    if blockers:
        result = _hybrid_direct_test_result_payload(self, passed=False, reason_codes=blockers, report_path=report_path)
        result.update({"mode": "offline_candidate_replay", "status": "blocked", "source": "user_replay_sessions"})
        _write_backend_hybrid_direct_test_report(self, result, report_path)
        setattr(self, "_latest_hybrid_direct_test_result", result)
        signal = getattr(self, "hybridDirectChanged", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        try:
            self._set_status(_hybrid_result_status_message(self, result), "warn")
        except Exception:
            pass
        return dict(result)

    setattr(self, "_hybrid_direct_test_running", True)
    signal = getattr(self, "hybridDirectChanged", None)
    controls = getattr(self, "controlsChanged", None)
    if signal is not None and hasattr(signal, "emit"):
        signal.emit()
    if controls is not None and hasattr(controls, "emit"):
        controls.emit()
    started_payload = _hybrid_direct_test_result_payload(
        self,
        passed=False,
        reason_codes=["offline_candidate_replay_started", "device_influence_disabled", "face_confirmation_disabled"],
        report_path=report_path,
        extra={"mode": "offline_candidate_replay", "status": "running", "source": "user_replay_sessions"},
    )
    setattr(self, "_latest_hybrid_direct_test_result", started_payload)
    _update_hybrid_direct_state_from_offline_summary(self, {"offline_replay": {"status": "running", "source": "user_replay_sessions"}, **started_payload})

    try:
        from hybrid_candidates.artifact_resolver import build_candidate_bundle_artifact_resolver
        from hybrid_candidates.offline_runner import run_offline_candidate_replay
        from metadata_core.paths import _user_model_paths

        replay_sessions_root = _hybrid_direct_replay_sessions_root()
        try:
            model_paths = _user_model_paths(_current_safe_user(self))
            artifact_resolver = build_candidate_bundle_artifact_resolver(bundle_dir=model_paths.get("base"), metadata_path=model_paths.get("metadata"))
        except Exception:
            LOGGER.debug("Failed creating Hybrid Direct candidate-bundle artifact resolver", exc_info=True)
            artifact_resolver = None
        summary = run_offline_candidate_replay(output_dir=_hybrid_direct_reports_dir(), sessions_root=replay_sessions_root or None, artifact_resolver=artifact_resolver)
        reason_codes = _hybrid_direct_offline_reason_codes(summary)
        passed = str(summary.get("status") or "") in {"completed", "no_eligible_sessions", "completed_with_candidate_or_session_errors"}
        result = _hybrid_direct_test_result_payload(
            self,
            passed=passed,
            reason_codes=reason_codes,
            report_path=report_path,
            extra={
                "mode": "offline_candidate_replay",
                "status": str(summary.get("status") or "completed"),
                "source": "user_replay_sessions",
                "offline_replay": dict(summary),
                "report_paths": dict(summary.get("report_paths") or {}),
                "sessions_root": str(summary.get("sessions_root") or ""),
                "session_count": int(summary.get("session_count") or 0),
                "labeled_session_count": int(summary.get("labeled_session_count") or 0),
                "unlabeled_session_count": int(summary.get("unlabeled_session_count") or 0),
                "candidate_count": int(summary.get("candidate_count") or 0),
                "available_candidate_count": int(summary.get("available_candidate_count") or 0),
                "unavailable_candidate_count": int(summary.get("unavailable_candidate_count") or 0),
                "missing_artifact_count": int(summary.get("missing_artifact_count") or 0),
                "warnings": list(summary.get("warnings") or []),
                "errors": list(summary.get("errors") or []),
            },
        )
        _write_backend_hybrid_direct_test_report(self, result, report_path)
        setattr(self, "_latest_hybrid_direct_test_result", result)
        _update_hybrid_direct_state_from_offline_summary(self, result)
        try:
            status = str(summary.get("status") or "completed")
            if status == "no_eligible_sessions":
                self._set_status("Hybrid Direct offline replay generated a safe no-data report.", "warn")
            else:
                self._set_status("Hybrid Direct offline replay completed and reports were generated.", "success" if passed else "warn")
        except Exception:
            pass
        return dict(result)
    except Exception as exc:
        LOGGER.exception("Hybrid Direct offline replay failed to run")
        result = _hybrid_direct_test_result_payload(
            self,
            passed=False,
            reason_codes=["offline_candidate_replay_error", "device_influence_disabled", "face_confirmation_disabled"],
            report_path=report_path,
            extra={"mode": "offline_candidate_replay", "status": "failed", "source": "user_replay_sessions", "error": type(exc).__name__},
        )
        _write_backend_hybrid_direct_test_report(self, result, report_path)
        setattr(self, "_latest_hybrid_direct_test_result", result)
        _update_hybrid_direct_state_from_offline_summary(self, result)
        try:
            self._set_status(_hybrid_result_status_message(self, result), "danger")
        except Exception:
            pass
        return dict(result)
    finally:
        setattr(self, "_hybrid_direct_test_running", False)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit()
        if controls is not None and hasattr(controls, "emit"):
            controls.emit()
        _request_refresh(self, "hybrid_direct_offline_replay:finished", True)
