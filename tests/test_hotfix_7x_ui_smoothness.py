from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_user_shell_uses_smooth_page_transition_container():
    qml = _read("qml/UserShell.qml")
    assert "id: contentPageViewport" in qml
    assert "id: contentPageStack" in qml
    assert "id: contentPageMotion" in qml
    assert "property int _pageSlideDirection" in qml
    assert "Easing.OutCubic" in qml


def test_admin_shell_uses_same_lightweight_page_transition():
    qml = _read("qml/AppShell.qml")
    assert "id: contentPageViewport" in qml
    assert "id: contentPageStack" in qml
    assert "id: contentPageMotion" in qml
    assert "property int _pageSlideDirection" in qml
    assert "Easing.OutCubic" in qml


def test_live_telemetry_animates_display_risk_and_tone_changes():
    qml = _read("qml/components/LiveTelemetryPanel.qml")
    assert "displayRiskAnimated" in qml
    assert "displayRiskTargetValue" in qml
    assert "Behavior on displayRiskAnimated" in qml
    assert "NumberAnimation { duration: 620" in qml
    assert "Behavior on border.color" in qml


def test_glass_card_has_lightweight_cached_surface_and_color_behaviors():
    qml = _read("qml/components/GlassCard.qml")
    assert "layer.enabled: visible" in qml
    assert "layer.smooth: true" in qml
    assert "Behavior on color" in qml
    assert "Behavior on border.color" in qml
