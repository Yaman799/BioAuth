from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BASE_REQUIRED_MODULES = [
    ("PyInstaller", "PyInstaller"),
    ("PySide6", "PySide6"),
    ("numpy", "numpy"),
    ("pandas", "pandas"),
    ("sklearn", "scikit-learn"),
    ("pynput", "pynput"),
    ("cryptography", "cryptography"),
]

PROFILE_REQUIRED_MODULES = {
    "classic-minimal": [],
    "hybrid-pro": [("torch", "torch"), ("lightgbm", "lightgbm")],
    "hybrid-pro-face": [("torch", "torch"), ("lightgbm", "lightgbm"), ("cv2", "opencv-contrib-python")],
    "dev": [("torch", "torch"), ("lightgbm", "lightgbm")],
}

# Backward-compatible release/test gate surface: historically this list
# represented the full Hybrid/Pro release dependency set, including LightGBM.
# Runtime preflight still chooses profile-specific requirements in main().
REQUIRED_MODULES = BASE_REQUIRED_MODULES + PROFILE_REQUIRED_MODULES["hybrid-pro"]

OPTIONAL_MODULES = [
    ("pyod", "pyod", "Optional. The training stack falls back to scikit-learn IsolationForest when pyod is unavailable."),
    ("pygame", "pygame", "Optional. UI sounds fall back to winsound or system players when pygame is unavailable."),
    ("torch", "torch", "Optional for Hybrid packaging. Classic-only builds remain supported without it."),
    ("onnxruntime", "onnxruntime", "Optional. Accelerated Hybrid rollout stays disabled when it is unavailable."),
    ("openvino", "openvino", "Optional. Accelerated Hybrid rollout stays disabled when it is unavailable."),
    ("cv2", "opencv-contrib-python", "Optional unless the package profile includes Face Confirmation."),
]


def configure_headless_import_env() -> None:
    if os.name == "nt":
        return
    if not str(os.environ.get("DISPLAY", "") or "").strip():
        os.environ.setdefault("PYNPUT_BACKEND", "dummy")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def fail(msg: str) -> int:
    print(f"[FAIL] {msg}")
    return 1


def ok(msg: str) -> None:
    print(f"[ OK ] {msg}")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def hybrid_build_requested() -> bool:
    return str(os.environ.get("BIOAUTH_BUILD_WITH_HYBRID", "") or "").strip().lower() in {"1", "true", "yes", "on"}


def validate_required_project_files(root: Path) -> str | None:
    desktop_app = root / "desktop_app.py"
    qml_main = root / "qml" / "Main.qml"
    icon_file = root / "bioauth.ico"
    privacy_policy = root / "PRIVACY_POLICY.md"

    if not desktop_app.exists():
        return "desktop_app.py is missing."
    if not qml_main.exists():
        return "qml/Main.qml is missing."
    if not icon_file.exists():
        return "bioauth.ico is missing."
    if not privacy_policy.exists():
        return "PRIVACY_POLICY.md is missing."
    if not privacy_policy.read_text(encoding="utf-8").strip():
        return "PRIVACY_POLICY.md is empty."
    return None


def validate_required_modules(required_modules) -> list[str]:
    missing = []
    for module_name, package_name in required_modules:
        try:
            importlib.import_module(module_name)
            ok(f"{package_name} importable")
        except Exception as exc:
            missing.append(f"{package_name} ({exc})")
    return missing


def validate_optional_modules(optional_modules) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for module_name, package_name, note in optional_modules:
        try:
            importlib.import_module(module_name)
            ok(f"{package_name} importable")
            results[package_name] = True
        except Exception as exc:
            warn(f"{package_name} unavailable ({exc}). {note}")
            results[package_name] = False
    return results


def main() -> int:
    configure_headless_import_env()
    print("== BioAuth build preflight ==")
    print(f"Project root: {ROOT}")
    print(f"Python exe : {sys.executable}")
    print(f"Python ver : {sys.version.split()[0]}")

    try:
        sys.path.insert(0, str(ROOT))
        from release_profile import assert_release_profile_safe, package_profile_payload, profile_payload
        profile = profile_payload()
        package_profile = package_profile_payload()
        print(f"Build profile: {profile.get('profile')}")
        print(f"Package profile: {package_profile.get('package_profile')}")
        assert_release_profile_safe()
        ok("release profile policy passed")
    except Exception as exc:
        return fail(f"Release profile validation failed: {exc}")

    if "WindowsApps" in sys.executable:
        return fail("Microsoft Store Python is being used. Activate .venv\\Scripts\\python.exe explicitly.")

    if not Path(sys.executable).exists():
        return fail("Python executable does not exist.")

    required_file_error = validate_required_project_files(ROOT)
    if required_file_error:
        return fail(required_file_error)

    package_name = str(package_profile.get("package_profile") or "classic-minimal")
    required_modules = list(BASE_REQUIRED_MODULES) + list(PROFILE_REQUIRED_MODULES.get(package_name, []))
    missing = validate_required_modules(required_modules)
    if missing:
        print("[FAIL] Missing or broken required dependencies:")
        for item in missing:
            print(f"  - {item}")
        return 1

    optional = validate_optional_modules(OPTIONAL_MODULES)
    if (hybrid_build_requested() or bool(package_profile.get("include_deep_deps"))) and not optional.get("torch", False):
        return fail("Hybrid package profile was requested but torch is not importable.")
    if bool(package_profile.get("include_face_backends")) and not optional.get("opencv-contrib-python", False):
        return fail("Face package profile was requested but cv2/opencv-contrib-python is not importable.")

    try:
        from PySide6 import QtCore  # noqa: F401
        ok("PySide6 core import passed")
    except Exception as exc:
        return fail(f"PySide6 failed to import: {exc}")

    try:
        sys.path.insert(0, str(ROOT))
        import desktop_app  # noqa: F401
        ok("desktop_app import smoke test passed")
    except Exception as exc:
        return fail(f"desktop_app failed to import: {exc}")

    ok("Preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
