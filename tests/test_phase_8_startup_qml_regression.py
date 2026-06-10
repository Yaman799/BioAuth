from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_confirm_dialog_does_not_override_dialog_rejected_signal():
    text = _read("qml/dialogs/ConfirmDialog.qml")
    assert "signal rejected()" not in text
    assert "onClicked: root.reject()" in text


def test_user_mode_pages_do_not_use_semicolon_separated_qml_child_objects():
    for rel in [
        "qml/pages/user/UserHomePage.qml",
        "qml/pages/user/UserProtectionPage.qml",
        "qml/pages/user/UserFaceConfirmationPage.qml",
        "qml/dialogs/FaceEnrollmentDialog.qml",
    ]:
        text = _read(rel)
        assert "};" not in text, rel


def test_startup_qml_surfaces_are_still_registered():
    main_qml = _read("qml/Main.qml")
    user_shell = _read("qml/UserShell.qml")
    assert "AppShell" in main_qml
    assert "UserShell" in main_qml
    assert "UserHomePage" in user_shell
    assert "UserProtectionPage" in user_shell
    assert "UserFaceConfirmationPage" in user_shell
