from __future__ import annotations

from pathlib import Path

from build_tools.commercial_package_allowlist import collect_commercial_datas


ROOT = Path(__file__).resolve().parent.parent


def _commercial_datas_pairs() -> list[tuple[str, str]]:
    return collect_commercial_datas(ROOT)


def _has_source_prefix(pairs: list[tuple[str, str]], prefix: str) -> bool:
    return any(source == prefix or source.startswith(prefix + "/") for source, _dest in pairs)


def test_commercial_package_excludes_reports_safety_directory() -> None:
    pairs = _commercial_datas_pairs()

    assert not _has_source_prefix(pairs, "reports/safety")


def test_commercial_package_preserves_runtime_core_datas() -> None:
    pairs = _commercial_datas_pairs()

    for required_prefix in {
        "qml",
        "config/onboarding_slides.json",
        "config/onboarding_assets/fullscreen",
        "model_runtime",
        "models/face",
    }:
        assert _has_source_prefix(pairs, required_prefix), required_prefix

    for forbidden_prefix in {"tests", "docs", "reports", "archive", ".github"}:
        assert not _has_source_prefix(pairs, forbidden_prefix), forbidden_prefix
