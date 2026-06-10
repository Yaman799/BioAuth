"""Safe optional-dependency probes for Hybrid Candidate training/evaluation.

This module deliberately performs no package installation and imports no heavy
ML libraries at module import time.  Callers can use the cheap probe for UI/docs
or request an actual import only when executing an optional candidate.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import platform
from dataclasses import dataclass
from typing import Any, Mapping

DEPENDENCY_PROBE_VERSION = "deep-candidate-dependency-probe-v1"
DEPENDENCY_OK = "ok"
DEPENDENCY_MISSING = "dependency_missing"
DEPENDENCY_IMPORT_FAILED = "dependency_import_failed"
UNSUPPORTED_ENVIRONMENT = "unsupported_environment"

OPTIONAL_DEPENDENCY_REASON_CATEGORIES = {
    DEPENDENCY_MISSING,
    DEPENDENCY_IMPORT_FAILED,
    UNSUPPORTED_ENVIRONMENT,
}


@dataclass(frozen=True)
class DependencyStatus:
    """Structured status for one runtime or candidate dependency."""

    module_name: str
    package_name: str
    available: bool
    reason: str
    version: str | None = None
    import_checked: bool = False
    import_error: str = ""
    python_version: str = platform.python_version()
    platform: str = platform.platform()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DEPENDENCY_PROBE_VERSION,
            "module_name": self.module_name,
            "package_name": self.package_name,
            "available": bool(self.available),
            "reason": self.reason,
            "version": self.version,
            "import_checked": bool(self.import_checked),
            "import_error": self.import_error,
            "python_version": self.python_version,
            "platform": self.platform,
        }


def _clean_name(value: Any) -> str:
    return str(value or "").strip()


def _safe_find_spec(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def safe_dependency_version(package_name: str, *, module_name: str | None = None) -> str | None:
    """Return a package/module version without requiring callers to import it."""

    package = _clean_name(package_name or module_name)
    module = _clean_name(module_name or package_name)
    if package:
        try:
            return str(importlib.metadata.version(package))
        except Exception:
            pass
    if module:
        try:
            loaded = importlib.import_module(module)
            value = getattr(loaded, "__version__", None)
            return str(value) if value not in (None, "") else None
        except Exception:
            return None
    return None


def probe_dependency(
    module_name: str,
    *,
    package_name: str | None = None,
    require_import: bool = False,
) -> DependencyStatus:
    """Probe a dependency safely.

    ``require_import=False`` only checks import metadata/spec availability and is
    safe for app startup/status surfaces.  ``require_import=True`` is intended for
    candidate execution paths where an estimator class or PyTorch runtime is
    actually needed; import failures still return structured status instead of
    raising.
    """

    module = _clean_name(module_name)
    package = _clean_name(package_name or module)
    if not module:
        return DependencyStatus(module, package, False, DEPENDENCY_MISSING)
    if not _safe_find_spec(module):
        return DependencyStatus(module, package, False, DEPENDENCY_MISSING)
    version = safe_dependency_version(package, module_name=module)
    if not require_import:
        return DependencyStatus(module, package, True, DEPENDENCY_OK, version=version, import_checked=False)
    try:
        importlib.import_module(module)
    except Exception as exc:
        return DependencyStatus(
            module,
            package,
            False,
            DEPENDENCY_IMPORT_FAILED,
            version=version,
            import_checked=True,
            import_error=f"{type(exc).__name__}:{exc}",
        )
    return DependencyStatus(module, package, True, DEPENDENCY_OK, version=version, import_checked=True)


def dependency_available(module_name: str, *, package_name: str | None = None, require_import: bool = False) -> bool:
    return bool(probe_dependency(module_name, package_name=package_name, require_import=require_import).available)


def dependency_missing_metadata(module_name: str, *, package_name: str | None = None, require_import: bool = False) -> dict[str, Any]:
    status = probe_dependency(module_name, package_name=package_name, require_import=require_import)
    payload = status.to_dict()
    payload["dependency_missing"] = not bool(status.available)
    payload["unavailable_reason_category"] = DEPENDENCY_MISSING if not status.available else DEPENDENCY_OK
    return payload


def normalize_unavailable_reason_category(reason: Any) -> str:
    raw = _clean_name(reason).lower()
    if raw.startswith(DEPENDENCY_MISSING) or raw.startswith(DEPENDENCY_IMPORT_FAILED):
        return DEPENDENCY_MISSING
    if raw.startswith("insufficient_"):
        return "insufficient_data"
    if raw in {"missing_trained_artifact", "missing_artifact", "sequence_artifact_missing"} or raw.startswith("artifact_load_error"):
        return "missing_artifact"
    if raw in {"missing_trainer", "unsupported_candidate", "unsupported_supervised_candidate"}:
        return "missing_trainer"
    if raw.startswith("unsupported_environment"):
        return UNSUPPORTED_ENVIRONMENT
    if raw.startswith("missing_artifact_schema") or raw.startswith("metadata_invalid"):
        return "missing_artifact_schema"
    if raw.startswith("calibration_") or raw.startswith("missing_calibration"):
        return "calibration_or_intruder_data_missing"
    return raw or "unavailable"


CANDIDATE_DEPENDENCY_MODULES: Mapping[str, tuple[str, ...]] = {
    "supervised_lightgbm": ("lightgbm",),
    "supervised_xgboost": ("xgboost",),
    "supervised_catboost": ("catboost",),
    "keyboard_bigru_cnn_attention": ("torch",),
    "keyboard_type2branch": ("torch",),
    "keyboard_typeformer": ("torch",),
    "keyboard_siamese_triplet": ("torch",),
    "mouse_resnet_gru": ("torch",),
    "mouse_autoencoder": ("torch",),
    "mouse_deep_svdd": ("torch",),
    "oneclass_lstm_autoencoder": ("torch",),
    "oneclass_conv_autoencoder": ("torch",),
    "oneclass_deep_svdd": ("torch",),
    "combined_cnn_lstm": ("torch",),
}


def candidate_dependency_status(candidate_id: str, *, require_import: bool = False) -> dict[str, Any]:
    modules = CANDIDATE_DEPENDENCY_MODULES.get(str(candidate_id or "").strip(), ())
    statuses = [probe_dependency(module, require_import=require_import).to_dict() for module in modules]
    missing = [item for item in statuses if not bool(item.get("available"))]
    return {
        "schema_version": DEPENDENCY_PROBE_VERSION,
        "candidate_id": str(candidate_id or "").strip(),
        "dependencies": statuses,
        "available": not missing,
        "reason": DEPENDENCY_OK if not missing else DEPENDENCY_MISSING,
        "missing_dependencies": [str(item.get("module_name") or "") for item in missing],
    }


__all__ = [
    "CANDIDATE_DEPENDENCY_MODULES",
    "DEPENDENCY_IMPORT_FAILED",
    "DEPENDENCY_MISSING",
    "DEPENDENCY_OK",
    "DEPENDENCY_PROBE_VERSION",
    "DependencyStatus",
    "UNSUPPORTED_ENVIRONMENT",
    "candidate_dependency_status",
    "dependency_available",
    "dependency_missing_metadata",
    "normalize_unavailable_reason_category",
    "probe_dependency",
    "safe_dependency_version",
]
