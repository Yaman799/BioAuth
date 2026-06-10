from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

ROOT = Path(__file__).resolve().parent.parent
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
PLACEHOLDER_OWNER = "CHANGE_ME_OWNER"
PLACEHOLDER_REPO_NAMES = {"CHANGE_ME_REPO", ""}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8") or "{}")
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _check(name: str, ok: bool, *, detail: str = "", severity: str = "error", **extra: Any) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "name": str(name),
        "ok": bool(ok),
        "severity": str(severity or "error"),
    }
    if detail:
        item["detail"] = str(detail)[:500]
    item.update(extra)
    return item


def _safe_file_name(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and "/" not in text and "\\" not in text and text not in {".", ".."}


def validate_required_release_files(root: Path = ROOT) -> List[Dict[str, Any]]:
    required = [
        "BioAuth.spec",
        "BioAuthInstaller.iss",
        "build_exe.bat",
        "build_installer.bat",
        "build_tools/preflight.py",
        "build_tools/generate_update_manifest.py",
        "build_tools/write_release_config.py",
        "build_tools/sign_windows_artifact.bat",
        "build_tools/verify_windows_signature.bat",
        "release_config.json",
        "PRIVACY_POLICY.md",
        "EULA.txt",
        "VERSION",
    ]
    return [_check(f"required_file:{rel}", (root / rel).is_file(), detail=rel) for rel in required]


def validate_build_and_installer_scripts(root: Path = ROOT) -> List[Dict[str, Any]]:
    build_exe = _read(root / "build_exe.bat")
    build_installer = _read(root / "build_installer.bat")
    installer = _read(root / "BioAuthInstaller.iss")
    workflow = _read(root / ".github" / "workflows" / "release.yml")
    checks = [
        _check("build_exe_uses_project_venv_python", ".venv\\Scripts\\python.exe" in build_exe),
        _check("build_exe_runs_preflight", "build_tools\\preflight.py" in build_exe),
        _check("build_exe_runs_release_readiness_selfcheck", "--self-check-release-readiness" in build_exe),
        _check("build_exe_signs_packaged_exe_when_configured", "sign_windows_artifact.bat" in build_exe),
        _check("build_installer_builds_exe_first", "call build_exe.bat" in build_installer),
        _check("build_installer_signs_setup_when_configured", "sign_windows_artifact.bat" in build_installer),
        _check("build_installer_verifies_setup_signature", "verify_windows_signature.bat" in build_installer),
        _check("installer_uses_per_user_install", "PrivilegesRequired=lowest" in installer),
        _check("installer_startup_task_is_optional", "Name: \"startup\"" in installer and "Flags: unchecked" in installer),
        _check("installer_warns_before_startup_task", "Startup does not bypass sign-in" in installer),
        _check("installer_preserves_local_data_by_default", "Choose No to preserve accounts" in installer and "DelTree(DataDir" in installer),
        _check("release_workflow_runs_on_windows", "runs-on: windows-latest" in workflow),
        _check("release_workflow_writes_packaged_update_config", "write_release_config.py" in workflow),
        _check("release_workflow_generates_update_manifest", "generate_update_manifest.py" in workflow and "bioauth-update.json" in workflow),
        _check("release_workflow_uploads_release_checksums", "SHA256SUMS.txt" in workflow),
    ]
    return checks


def validate_release_config(root: Path = ROOT, *, strict_production: bool = False) -> List[Dict[str, Any]]:
    path = root / "release_config.json"
    payload = _json(path)
    owner = str(payload.get("update_repo_owner") or payload.get("repo_owner") or "").strip()
    repo = str(payload.get("update_repo_name") or payload.get("repo_name") or "").strip()
    manifest_name = str(payload.get("manifest_name") or payload.get("update_manifest_name") or "").strip()
    verification = str(payload.get("verification") or "").strip().lower()
    signing_required = bool(payload.get("signing_required", False))
    silent_install = bool(payload.get("silent_install", False))
    configured = bool(owner and repo and owner != PLACEHOLDER_OWNER and repo not in PLACEHOLDER_REPO_NAMES)
    checks = [
        _check("release_config_is_json_object", bool(payload), detail=str(path)),
        _check("release_config_uses_sha256_verification", verification == "sha256", detail=verification),
        _check("release_config_disables_silent_install", silent_install is False, detail=str(silent_install)),
        _check("release_config_manifest_name_safe", _safe_file_name(manifest_name), detail=manifest_name),
        _check("release_config_repo_template_or_configured", bool(owner) and bool(repo), detail=f"owner={owner or '<empty>'}; repo={repo or '<empty>'}"),
    ]
    if configured:
        checks.append(_check("release_config_repo_configured_for_updates", True, severity="info", detail=f"{owner}/{repo}"))
    else:
        checks.append(_check("release_config_repo_configured_for_updates", not strict_production, severity="error" if strict_production else "warning", detail="Source template may keep placeholders; production release config must be generated before packaging."))
    if strict_production:
        checks.append(_check("strict_production_release_config_requires_signing", signing_required is True, detail=str(signing_required)))
    else:
        checks.append(_check("source_release_config_signing_template_ok", signing_required in {True, False}, severity="info", detail=str(signing_required)))
    return checks


def validate_production_policy(*, strict_production: bool = False, env: Mapping[str, str] | None = None) -> List[Dict[str, Any]]:
    from release_profile import production_profile_errors

    source = dict(os.environ if env is None else env)
    profile = str(source.get("BIOAUTH_BUILD_PROFILE") or "production" if strict_production else source.get("BIOAUTH_BUILD_PROFILE") or "beta")
    policy_env = dict(source)
    policy_env["BIOAUTH_BUILD_PROFILE"] = profile
    errors = production_profile_errors(policy_env)
    checks = [
        _check("production_signing_policy_is_fail_closed", bool(production_profile_errors({"BIOAUTH_BUILD_PROFILE": "production"})), detail="production without signing is rejected"),
        _check("production_rejects_stray_demo_classic_flag", any("BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED" in item for item in production_profile_errors({
            "BIOAUTH_BUILD_PROFILE": "production",
            "BIOAUTH_ENABLE_SIGNING": "1",
            "BIOAUTH_SIGN_CERT_SHA1": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
            "BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED": "1",
        })), detail="commercial production cannot enable Demo Classic by accident"),
    ]
    if strict_production:
        checks.append(_check("current_production_env_signing_configured", not errors, detail="; ".join(errors)))
    else:
        checks.append(_check("current_release_profile_policy_checked", True, severity="info", detail=f"profile={profile}; errors={len(errors)}"))
    return checks


def validate_update_manifest_roundtrip() -> List[Dict[str, Any]]:
    from build_tools.generate_update_manifest import build_manifest
    from update_client import validate_update_manifest

    checks: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="bioauth_release_validation_") as tmp:
        installer = Path(tmp) / "BioAuthDesktopSetup_9.9.9.exe"
        installer.write_bytes(b"bioauth-test-installer-payload")
        manifest = build_manifest(
            installer=installer,
            version="9.9.9",
            channel="beta",
            min_supported_version="1.0.0",
            mandatory=False,
            release_notes="Release validation smoke manifest.",
            published_at="2026-06-05T00:00:00Z",
        )
        validated = validate_update_manifest(manifest, channel="beta")
        checks.append(_check("update_manifest_roundtrip_validates", validated["installer_name"] == installer.name and len(validated["installer_sha256"]) == 64, detail=installer.name))
        checks.append(_check("update_manifest_declares_artifacts", "artifact_names" in validated and "SHA256SUMS.txt" in list(validated.get("artifact_names") or []), detail=str(validated.get("artifact_names"))))
    return checks


def validate_license_safe_mode() -> List[Dict[str, Any]]:
    import license_manager

    invalid = license_manager.evaluate_license_code("not-a-license-code")
    features = invalid.get("features") if isinstance(invalid, dict) else {}
    basic_required = [
        "basic_protection",
        "start_protected_session",
        "stop_protected_session",
        "delete_my_data",
        "delete_evidence",
        "export_support_bundle",
        "local_recovery",
    ]
    malformed = license_manager.import_license_file(Path(tempfile.gettempdir()) / "bioauth_missing_license_file_for_validation.lic")
    checks = [
        _check("license_invalid_code_falls_back_to_basic", str(invalid.get("state") or "").endswith("basic") and invalid.get("premium_active") is False, detail=str(invalid.get("state"))),
        _check("license_basic_safety_features_preserved", all(bool((features or {}).get(name)) for name in basic_required), detail=",".join(name for name in basic_required if not bool((features or {}).get(name)))),
        _check("license_missing_file_safe_failure", malformed.get("ok") is False and str((malformed.get("licenseStatus") or {}).get("state") or "").endswith("basic"), detail=str(malformed.get("state"))),
    ]
    return checks


def build_release_validation_report(*, strict_production: bool = False) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    sections = [
        ("required_files", validate_required_release_files),
        ("build_installer_scripts", validate_build_and_installer_scripts),
        ("release_config", lambda root=ROOT: validate_release_config(root, strict_production=strict_production)),
        ("production_policy", lambda root=ROOT: validate_production_policy(strict_production=strict_production)),
        ("update_manifest", lambda root=ROOT: validate_update_manifest_roundtrip()),
        ("license_safe_mode", lambda root=ROOT: validate_license_safe_mode()),
    ]
    for section, fn in sections:
        try:
            section_checks = fn(ROOT) if section in {"required_files", "build_installer_scripts"} else fn()
        except Exception as exc:
            section_checks = [_check(section, False, detail=f"{exc.__class__.__name__}: {exc}")]
        for item in section_checks:
            item.setdefault("section", section)
            item["section"] = section
        checks.extend(section_checks)
    errors = [item for item in checks if not item.get("ok") and item.get("severity") == "error"]
    warnings = [item for item in checks if not item.get("ok") and item.get("severity") == "warning"]
    return {
        "schema_version": "bioauth-release-validation-v1",
        "strict_production": bool(strict_production),
        "ok": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "check_count": len(checks),
        "checks": checks,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate BioAuth commercial release, updater, installer, and license gates without building artifacts.")
    parser.add_argument("--strict-production", action="store_true", help="Fail if production release config/signing requirements are not fully configured.")
    parser.add_argument("--json-output", type=Path, help="Optional path to write the validation report JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_release_validation_report(strict_production=bool(args.strict_production))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
