from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "BioAuth.spec"
def _commercial_datas_pairs() -> list[tuple[str, str]]:
    from build_tools.commercial_package_allowlist import collect_commercial_datas

    return collect_commercial_datas(ROOT)


def test_face_model_asset_directory_is_packaged_when_present() -> None:
    assert (ROOT / "models" / "face").is_dir(), "H7 face model directory must exist as the runtime asset anchor"

    pairs = set(_commercial_datas_pairs())

    assert any(source.startswith("models/face/") and dest.startswith("models/face") for source, dest in pairs)


def test_face_packaging_paths_are_project_relative_and_existing_datas_based() -> None:
    pairs = _commercial_datas_pairs()

    for source, destination in pairs:
        assert not Path(source).is_absolute(), f"datas source must remain project-relative: {source}"
        assert not Path(destination).is_absolute(), f"datas destination must remain project-relative: {destination}"

    assert any(source.startswith("models/face/") and dest.startswith("models/face") for source, dest in pairs)


def test_face_packaging_preserves_commercial_runtime_allowlist_groups() -> None:
    pairs = set(_commercial_datas_pairs())
    sources = {source for source, _ in pairs}

    assert any(source.endswith(".qml") and source.startswith("qml/") for source in sources)
    assert "config/onboarding_slides.json" in sources
    assert any(source.startswith("config/onboarding_assets/fullscreen/") for source in sources)
    assert any(source.startswith("model_runtime/") for source in sources)
    assert any(source.startswith("models/face/") for source in sources)
    assert all(not source.startswith("reports/") for source in sources)


def test_face_backend_dependencies_are_packaged_only_through_face_profile_controls() -> None:
    spec = SPEC_PATH.read_text(encoding="utf-8")

    assert "include_face_backends" in spec
    assert "BIOAUTH_INCLUDE_OPENCV" in spec
    assert "_maybe_collect(\"cv2\", INCLUDE_OPENCV)" in spec
    assert "if not INCLUDE_OPENCV:" in spec
    assert "excludes += [\"cv2\", \"opencv-python\"]" in spec
