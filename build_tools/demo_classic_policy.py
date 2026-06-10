from __future__ import annotations

"""Demo Classic build/runtime flag policy.

Commercial builds must default to product behavior.  Demo Classic is kept in the
source tree for controlled local/demo profiles, but production packaging should
only include its dedicated runtime hook and demo-only modules when the caller
sets both the explicit demo build flag and the explicit demo build flavor.
"""

import os
from typing import Mapping, Any

DEMO_CLASSIC_BUILD_FLAG = "BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED"
DEMO_CLASSIC_BUILD_FLAVOR_ENV = "BIOAUTH_BUILD_FLAVOR"
DEMO_CLASSIC_BUILD_FLAVOR = "demo-classic-protected"
DEMO_CLASSIC_RUNTIME_ENV = "BIOAUTH_DEMO_CLASSIC_PROTECTED"
DEMO_CLASSIC_EMBEDDED_ENV = "BIOAUTH_DEMO_CLASSIC_PROTECTED_EMBEDDED"
_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}

# Standalone demo-only modules/files.  Flag-gated compatibility code that lives
# inside product modules remains in the source tree for now, but these dedicated
# demo modules are excluded from commercial packaging unless the demo flavor is
# explicitly requested.
DEMO_CLASSIC_MODULE_MARKERS = ("demo_classic",)
DEMO_CLASSIC_PATH_MARKERS = ("demo_classic", "runtime_demo_classic_protected.py")


def _source(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return env if env is not None else os.environ


def truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE_VALUES


def demo_classic_build_flavor(env: Mapping[str, str] | None = None) -> str:
    return str(_source(env).get(DEMO_CLASSIC_BUILD_FLAVOR_ENV, "") or "").strip().lower()


def demo_classic_build_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return True only for the explicit demo build profile.

    A stray BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED=1 is not enough for commercial
    packaging.  The dedicated demo builder also sets BIOAUTH_BUILD_FLAVOR to
    ``demo-classic-protected``; normal production/commercial builds do not.
    """
    source = _source(env)
    return truthy(source.get(DEMO_CLASSIC_BUILD_FLAG)) and demo_classic_build_flavor(source) == DEMO_CLASSIC_BUILD_FLAVOR


def is_demo_classic_module(module_name: str) -> bool:
    normalized = str(module_name or "").replace("-", "_").lower()
    return any(marker in normalized for marker in DEMO_CLASSIC_MODULE_MARKERS)


def is_demo_classic_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").replace("-", "_").lower()
    return any(marker in normalized for marker in DEMO_CLASSIC_PATH_MARKERS)


def demo_classic_policy_payload(env: Mapping[str, str] | None = None) -> dict[str, object]:
    source = _source(env)
    return {
        "commercial_default_demo_enabled": False,
        "demo_build_enabled": demo_classic_build_enabled(source),
        "build_flag_set": truthy(source.get(DEMO_CLASSIC_BUILD_FLAG)),
        "build_flavor": demo_classic_build_flavor(source),
        "required_build_flavor": DEMO_CLASSIC_BUILD_FLAVOR,
    }


__all__ = [
    "DEMO_CLASSIC_BUILD_FLAG",
    "DEMO_CLASSIC_BUILD_FLAVOR",
    "DEMO_CLASSIC_BUILD_FLAVOR_ENV",
    "DEMO_CLASSIC_EMBEDDED_ENV",
    "DEMO_CLASSIC_RUNTIME_ENV",
    "demo_classic_build_enabled",
    "demo_classic_build_flavor",
    "demo_classic_policy_payload",
    "is_demo_classic_module",
    "is_demo_classic_path",
    "truthy",
]
