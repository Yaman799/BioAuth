"""Backend-owned Safety Gates and Classic rollback helpers for Hybrid Direct."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Mapping
SAFETY_GATE_POLICY_VERSION = "safety-gates-v1"
REQUIRED_GATE_KEYS = ("evaluation_harness_passed","thresholds_calibrated","face_confirmation_enabled","rollback_snapshot_exists","no_single_model_lock_enforced","developer_consent_enabled","timeout_fallback_enabled","schema_error_fallback_enabled")
def _project_root_from_moved_module() -> Path:
    """Return the same source-tree root used before Commercial-CLEAN-07.

    The original root-level module used ``Path(__file__).resolve().parent``.
    After moving the implementation under ``src/bioauth/runtime``, that would
    incorrectly point at the package directory.  Resolve back to the repository
    root so report/safety paths remain byte-for-byte compatible with the old
    source layout and frozen build behavior.
    """

    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "desktop_app.py").exists():
            return parent
        if parent.name == "src":
            return parent.parent
    return here.parent


PROJECT_ROOT = _project_root_from_moved_module()
ROLLBACK_SNAPSHOT_PATH = PROJECT_ROOT / "reports" / "safety" / "phase_10_classic_rollback_snapshot.json"
SAFETY_GATE_REPORT_PATH = PROJECT_ROOT / "reports" / "safety_gate_report.md"
def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
def _bool(v: Any, default: bool=False) -> bool:
    if v is None: return bool(default)
    if isinstance(v,str): return v.strip().lower() in {"1","true","yes","on","enabled","passed"}
    return bool(v)
def _gate(passed: bool, status: str, reason_codes: list[str], *, evidence: str="") -> Dict[str, Any]:
    ok=bool(passed)
    return {"passed":ok,"status":str(status),"display_label":"passed" if ok else "fail_closed","tone":"success" if ok else "warn","reason_codes":[str(c) for c in reason_codes if str(c).strip()],"evidence":str(evidence or "")}
def _timestamp_is_valid(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip(): return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return True
    except ValueError:
        return False
def _rollback_snapshot_payload_is_valid(payload: Any) -> bool:
    if not isinstance(payload, Mapping): return False
    has_version=bool(str(payload.get("version") or payload.get("schema_version") or "").strip())
    target=str(payload.get("rollback_target", payload.get("target_mode", "")) or "").strip()
    developer_direct_disabled=payload.get("developer_direct_enabled") is False
    if "hybrid_can_influence_device" in payload:
        hybrid_influence_disabled=payload.get("hybrid_can_influence_device") is False
    else:
        hybrid_influence_disabled=payload.get("can_influence_device") is False
    timestamp_ok=_timestamp_is_valid(payload.get("created_at") or payload.get("generated_at"))
    return bool(has_version and target=="classic_only" and developer_direct_disabled and hybrid_influence_disabled and timestamp_ok)
def _has_rollback_snapshot(path: Path|None=None) -> bool:
    p=path or ROLLBACK_SNAPSHOT_PATH
    try:
        if not p.is_file() or p.stat().st_size<=0: return False
        with p.open("r", encoding="utf-8") as f:
            return _rollback_snapshot_payload_is_valid(json.load(f))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
def build_default_safety_gate_results() -> Dict[str, Dict[str, Any]]:
    gates={
        "evaluation_harness_passed":_gate(False,"unverified",["evaluation_harness_not_verified"],evidence="evaluation report required"),
        "thresholds_calibrated":_gate(False,"unverified",["thresholds_not_calibrated"],evidence="threshold evidence required"),
        "face_confirmation_enabled":_gate(False,"disabled",["face_confirmation_not_enabled"],evidence="app settings"),
        "rollback_snapshot_exists":_gate(False,"missing",["rollback_snapshot_missing"],evidence=str(ROLLBACK_SNAPSHOT_PATH)),
        "no_single_model_lock_enforced":_gate(True,"enforced",["single_model_lock_forbidden"],evidence="backend invariant"),
        "developer_consent_enabled":_gate(False,"disabled",["developer_consent_required"],evidence="explicit consent required"),
        "timeout_fallback_enabled":_gate(True,"enforced",["timeout_fallback_to_classic_enabled"],evidence="fusion policy"),
        "schema_error_fallback_enabled":_gate(True,"enforced",["schema_error_fallback_to_classic_enabled"],evidence="fusion policy"),
        "developer_direct_default_off":_gate(True,"enforced",["developer_direct_off_by_default"],evidence="safe default"),
        "emergency_disable_available":_gate(True,"available",["emergency_disable_returns_classic_only"],evidence="backend slot"),
    }
    gates["developer_direct_enabled"]=_gate(False,"disabled",["developer_direct_disabled"],evidence="safe default")
    gates["evaluation_harness"]=dict(gates["evaluation_harness_passed"])
    gates["face_confirmation"]=dict(gates["face_confirmation_enabled"])
    gates["rollback_snapshot"]=dict(gates["rollback_snapshot_exists"])
    gates["no_single_model_lock"]=dict(gates["no_single_model_lock_enforced"])
    gates["experiment_can_lock_alone_false"]=_gate(True,"enforced",["experiment_can_lock_alone_false"],evidence="backend invariant")
    gates["device_influence"]=_gate(False,"disabled",["device_influence_disabled"],evidence="gated")
    return gates
def build_safety_gate_report(settings: Mapping[str,Any]|None=None, hybrid_state: Mapping[str,Any]|None=None, *, rollback_snapshot_path: Path|None=None, timestamp: str|None=None) -> Dict[str, Any]:
    settings=dict(settings or {}) if isinstance(settings,Mapping) else {}; hybrid=dict(hybrid_state or {}) if isinstance(hybrid_state,Mapping) else {}; gates=build_default_safety_gate_results()
    dev=_bool(hybrid.get("enabled",settings.get("developer_direct_test_enabled",False))); exp_lock=_bool(hybrid.get("experiment_can_lock_alone",False)); no_single=bool(hybrid.get("no_single_model_can_lock",True)) and not exp_lock
    can_inf=_bool(hybrid.get("can_influence_device",settings.get("hybrid_can_influence_device",False))) and dev
    vals={"evaluation_harness_passed":_bool(settings.get("evaluation_harness_passed",False)),"thresholds_calibrated":_bool(settings.get("thresholds_calibrated",False)),"face_confirmation_enabled":_bool(settings.get("face_confirmation_enabled",False)),"rollback_snapshot_exists":_has_rollback_snapshot(rollback_snapshot_path),"developer_consent_enabled":_bool(settings.get("developer_direct_consent_enabled",False))}
    gates["developer_direct_enabled"]=_gate(dev,"enabled" if dev else "disabled",["developer_direct_enabled"] if dev else ["developer_direct_disabled"],evidence="backend hybridDirectState.enabled")
    for k,ok in vals.items(): gates[k]=_gate(ok,"passed" if ok else ("missing" if k=="rollback_snapshot_exists" else "unverified"),[k] if ok else [k+"_not_ready"],evidence=str(rollback_snapshot_path or ROLLBACK_SNAPSHOT_PATH) if k=="rollback_snapshot_exists" else "backend setting/evidence")
    gates["evaluation_harness"]=dict(gates["evaluation_harness_passed"]); gates["face_confirmation"]=dict(gates["face_confirmation_enabled"]); gates["rollback_snapshot"]=dict(gates["rollback_snapshot_exists"])
    gates["no_single_model_lock_enforced"]=_gate(no_single,"enforced" if no_single else "blocked",["single_model_lock_forbidden"] if no_single else ["single_model_lock_invariant_failed"],evidence="hybridDirectState")
    gates["no_single_model_lock"]=dict(gates["no_single_model_lock_enforced"]); gates["experiment_can_lock_alone_false"]=_gate(not exp_lock,"enforced" if not exp_lock else "blocked",["experiment_can_lock_alone_false"] if not exp_lock else ["experiment_can_lock_alone_blocked"],evidence="hybridDirectState")
    req=all(bool(gates[k]["passed"]) for k in REQUIRED_GATE_KEYS); influence=bool(req and dev and can_inf)
    gates["device_influence"]=_gate(influence,"enabled" if influence else "disabled",["device_influence_enabled"] if influence else ["device_influence_disabled","safety_gates_fail_closed"],evidence="all gates required")
    return {"version":SAFETY_GATE_POLICY_VERSION,"timestamp":str(timestamp or utc_timestamp()),"developer_direct_enabled":dev,"can_influence_device":influence,"experiment_can_lock_alone":False,"no_single_model_can_lock":no_single,"rollback_snapshot_path":str(rollback_snapshot_path or ROLLBACK_SNAPSHOT_PATH),"rollback_snapshot_exists":vals["rollback_snapshot_exists"],"gate_results":gates,"required_gate_keys":list(REQUIRED_GATE_KEYS),"all_required_gates_passed":req,"influence_allowed":influence,"status":"ready" if influence else "fail_closed","reason_codes":["all_required_gates_passed"] if influence else ["safety_gates_fail_closed","developer_direct_off_by_default"]}
def safety_gate_results_for_hybrid_state(report: Mapping[str,Any]|None) -> Dict[str, Dict[str, Any]]:
    return dict(report.get("gate_results",{})) if isinstance(report,Mapping) and isinstance(report.get("gate_results"),Mapping) else build_default_safety_gate_results()
def emergency_disable_hybrid_state(previous: Mapping[str,Any]|None=None, *, timestamp: str|None=None) -> Dict[str, Any]:
    return {"enabled":False,"mode":"classic_only","can_influence_device":False,"experiment_can_lock_alone":False,"no_single_model_can_lock":True,"fusion_state":"unavailable","face_required":False,"final_action":"classic_only_emergency_disabled","final_action_provenance":"backend_emergency_disable_hybrid","reason_codes":["emergency_disable_hybrid_invoked","developer_direct_disabled","device_influence_disabled","classic_only_fallback_active","single_model_lock_forbidden"],"errors":[],"timestamp":str(timestamp or utc_timestamp())}
def rollback_to_classic_state(previous: Mapping[str,Any]|None=None, *, timestamp: str|None=None) -> Dict[str, Any]:
    return {"enabled":False,"mode":"classic_only","can_influence_device":False,"experiment_can_lock_alone":False,"no_single_model_can_lock":True,"fusion_state":"unavailable","face_required":False,"final_action":"rollback_to_classic_only","final_action_provenance":"backend_classic_rollback","reason_codes":["rollback_to_classic_invoked","developer_direct_disabled","device_influence_disabled","model_evidence_preserved","reports_preserved","single_model_lock_forbidden"],"errors":[],"timestamp":str(timestamp or utc_timestamp())}
def render_safety_gate_report_markdown(report: Mapping[str,Any]) -> str:
    gates=report.get("gate_results",{}) if isinstance(report,Mapping) else {}; lines=["# BioAuth Phase 10 Safety Gate Report","",f"Version: {report.get('version',SAFETY_GATE_POLICY_VERSION)}",f"Generated: {report.get('timestamp',utc_timestamp())}",f"Status: {report.get('status','fail_closed')}",f"Developer Direct Enabled: {bool(report.get('developer_direct_enabled',False))}",f"Influence Allowed: {bool(report.get('influence_allowed',False))}","","| Gate | Passed | Status | Reason codes | Evidence |","| --- | --- | --- | --- | --- |"]
    for k in sorted(gates):
        g=gates.get(k) if isinstance(gates.get(k),Mapping) else {}; lines.append(f"| {k} | {bool(g.get('passed',False))} | {g.get('status','')} | {', '.join(str(x) for x in g.get('reason_codes',[]))} | {g.get('evidence','')} |")
    lines += ["","Safety invariants:","- Developer Direct remains OFF by default.","- Experimental influence is disabled unless all backend gates pass and explicit developer consent is present.","- No single model can lock the device.","- Hybrid Red requires Face Confirmation before any existing incident lock path may proceed.","- Rollback and emergency disable preserve model evidence, logs, reports, and project files."]
    return "\n".join(lines)+"\n"
def write_safety_gate_report(report: Mapping[str,Any], path: Path|None=None) -> str:
    target=path or SAFETY_GATE_REPORT_PATH; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(render_safety_gate_report_markdown(report),encoding="utf-8"); return str(target)
