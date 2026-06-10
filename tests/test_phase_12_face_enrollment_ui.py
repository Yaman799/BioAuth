from __future__ import annotations
import ast
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "qml"
FACE_PAGE = QML / "pages" / "user" / "UserFaceConfirmationPage.qml"
FACE_DIALOG = QML / "dialogs" / "FaceEnrollmentDialog.qml"
USER_SHELL = QML / "UserShell.qml"
USER_SETTINGS = QML / "pages" / "user" / "UserSettingsPage.qml"
def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def read_desktop_impl() -> str:
    impl = ROOT/"src"/"bioauth"/"app"/"desktop_app_impl.py"
    if impl.exists(): return impl.read_text(encoding="utf-8")
    return read(ROOT/"desktop_app.py")
def bridge_slot_names() -> set[str]:
    tree = ast.parse(read(ROOT / "bridge" / "settings_mixin.py")); names=set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any((getattr(dec,"id","")=="Slot") or (isinstance(dec,ast.Call) and getattr(dec.func,"id","")=="Slot") for dec in node.decorator_list): names.add(node.name)
    return names
def test_face_enrollment_ui_files_exist_and_are_lazy_loaded():
    assert FACE_PAGE.exists(); assert FACE_DIALOG.exists(); shell=read(USER_SHELL)
    assert 'ListElement { navIndex: 3; glyph: "☺"; titleKey: "user_shell_face"' in shell
    assert "active: navSelection === 3" in shell and "UserFaceConfirmationPage { rootWindow: shell }" in shell and "active: navSelection === 4" in shell
def test_enrollment_uses_backend_owned_availability_guard():
    dialog=read(FACE_DIALOG)
    assert "backend.faceConfirmationState.faceEnrollmentAvailable !== true" in dialog
    assert "backend.faceConfirmationState.faceEnrollmentAvailable === true" in dialog
    assert "backend.enrollFaceTemplate()" in dialog
    assert "backend.grantFaceTemplateConsent()" in dialog
def test_face_buttons_call_real_backend_slots_with_duplicate_guards():
    page=read(FACE_PAGE); dialog=read(FACE_DIALOG); slots=bridge_slot_names()
    for expected in {"grantFaceTemplateConsent","setFaceConfirmationEnabled","enrollFaceTemplate","testFaceConfirmation","deleteFaceTemplate"}: assert expected in slots
    assert "property bool faceActionInFlight" in page and "property bool enrollmentInFlight" in dialog
    assert "if (root.faceActionInFlight)" in page and "if (enrollmentInFlight)" in dialog
    assert page.count("backend.setFaceConfirmationEnabled(") == 1
    assert "root.guardedToggleFace(true)" in page and "root.guardedToggleFace(false)" in page
    assert page.count("backend.testFaceConfirmation()") == 1 and page.count("backend.deleteFaceTemplate()") == 1 and dialog.count("backend.enrollFaceTemplate()") == 1
def test_delete_template_and_camera_failure_are_user_safe():
    page=read(FACE_PAGE); dialog=read(FACE_DIALOG); i18n=read(ROOT/"bridge"/"i18n.py")
    assert "face_delete_template" in page and "face_status_camera_unavailable" in i18n and "backendCameraStatusDetail" in dialog
    combined=(page+"\n"+dialog).lower()
    for token in ["embedding","template_digest","source_frame_paths","raw frame","raw image path"]: assert token not in combined
def test_face_ui_does_not_compute_biometric_or_production_readiness_locally():
    combined="\n".join(read(path) for path in [FACE_PAGE,FACE_DIALOG,USER_SETTINGS]).lower()
    for token in ["productioneligibility","production_eligibility","protectedsessionsavailable","approved_for_production","far","frr","reason_code","gate_results","verify_frame_against_template","template_digest","face_template_path"]: assert token not in combined
    assert "backend.faceconfirmationstate" in combined
def test_bridge_face_state_is_safe_and_not_connected_to_lock_path():
    settings=read(ROOT/"bridge"/"settings_mixin.py"); desktop=read_desktop_impl(); monitor=read(ROOT/"monitor.py")
    assert "faceConfirmationChanged = Signal()" in desktop and "def faceConfirmationState" in desktop
    assert "lockIntegrationEnabled" in settings and "rawImagesStored" in settings
    assert "enrollFaceTemplate" not in monitor and "testFaceConfirmation" not in monitor and "deleteFaceTemplate" not in monitor
def test_i18n_keys_exist_in_english_and_arabic():
    i18n=read(ROOT/"bridge"/"i18n.py")
    for key in ["user_shell_face","face_page_title","face_dialog_consent_checkbox","face_enable_confirmation","face_delete_template","face_status_camera_unavailable","face_confirmation_enabled"]: assert i18n.count(f'"{key}"') >= 2
