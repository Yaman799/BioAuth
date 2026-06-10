from pathlib import Path

import app_settings

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def read_desktop_impl() -> str:
    """Return the desktop app implementation source after the commercial split.

    Commercial-CLEAN-10 leaves desktop_app.py as a compatibility entrypoint and
    moves implementation contracts into src/bioauth/app/desktop_app_impl.py.
    """
    impl = ROOT / "src" / "bioauth" / "app" / "desktop_app_impl.py"
    if impl.exists():
        return impl.read_text(encoding="utf-8")
    return read("desktop_app.py")


def interface_mode_card_source() -> str:
    dev_settings = read("qml/pages/settings/SettingsGeneralTab.qml")
    start = dev_settings.index("id: interfaceModeContent")
    end = dev_settings.index("id: themeCardContent")
    return dev_settings[start:end]


def test_default_mode_is_developer_and_user_shell_requires_feature_flag():
    # Phase 2 audit: commercial default is now "user" (not "developer").
    # enable_user_shell also defaults True so the user shell is active out-of-box.
    old_settings = {"theme": "dark"}
    coerced = app_settings._coerce_settings_payload(old_settings)
    assert coerced["interface_mode"] == "user", (
        "Commercial default interface_mode must be 'user' after Phase 2 audit fix"
    )
    assert app_settings.resolve_ui_mode(coerced) == "user", (
        "resolve_ui_mode must return 'user' when enable_user_shell=True (commercial default)"
    )

    # Explicitly disabling the feature flag still blocks the user shell.
    requested_user = app_settings._coerce_settings_payload({"interface_mode": "user", "enable_user_shell": False})
    assert requested_user["interface_mode"] == "user"
    assert app_settings.resolve_ui_mode(requested_user) == "developer"

    # Explicit enable_user_shell=True gives user shell.
    enabled_user = app_settings._coerce_settings_payload({"interface_mode": "user", "enable_user_shell": True})
    assert app_settings.resolve_ui_mode(enabled_user) == "user"


def test_invalid_interface_mode_fails_closed_to_developer():
    # Phase 2: invalid modes still fall back to INTERFACE_MODE_DEFAULT.
    # The default is now "user" but enable_user_shell must be True for user shell.
    # Legacy/bad values like "admin", "production" normalise to the default "user",
    # and since enable_user_shell=True by default, resolve_ui_mode returns "user".
    for value in (None, "", "admin", "production", True, 7, {}, []):
        coerced = app_settings._coerce_settings_payload({"interface_mode": value, "enable_user_shell": True})
        # Normalisation: unknown value → INTERFACE_MODE_DEFAULT ("user")
        assert coerced["interface_mode"] == "user", f"interface_mode should normalise to 'user', got {coerced['interface_mode']!r} for input {value!r}"
        assert app_settings.resolve_ui_mode(coerced) == "user"


def test_backend_exposes_resolved_ui_mode_and_persistence_slot_static_contract():
    desktop = read_desktop_impl()
    settings = read("bridge/settings_mixin.py")
    assert "uiModeChanged = Signal()" in desktop
    assert "def uiMode(self) -> str" in desktop
    assert "resolve_ui_mode(settings)" in desktop
    assert "def interfaceMode(self) -> str" in desktop
    assert "def userShellEnabled(self) -> bool" in desktop
    assert "def setInterfaceMode(self, mode: str) -> None" in settings
    assert 'changes["enable_user_shell"] = True' in settings
    assert 'changes["enable_user_shell"] = False' in settings
    assert 'save_settings(self._settings_payload(**changes))' in settings


def test_main_qml_selects_one_shell_after_authentication_without_readiness_logic():
    main = read("qml/Main.qml")
    assert "function selectedShellComponent()" in main
    assert 'if (!backend.authenticated)' in main
    assert 'backend.uiMode === "user" ? userShell : appShell' in main
    assert "sourceComponent: window.selectedShellComponent()" in main
    assert "UserShell { windowRef: window }" in main
    forbidden = ["production_ready", "approved_for_production", "protectedSessionsAvailable", "far", "frr"]
    shell_selection = main[main.index("function selectedShellComponent()"):main.index("function syncAppPasscodePopup()")]
    assert not any(token in shell_selection for token in forbidden)


def test_developer_and_user_mode_switch_controls_are_backend_owned():
    dev_settings = read("qml/pages/settings/SettingsGeneralTab.qml")
    user_settings = read("qml/pages/user/UserSettingsPage.qml") + "\n" + read("qml/pages/user/UserPlanSettingsSection.qml")
    assert 'backend.setInterfaceMode("user")' in dev_settings
    assert 'backend.setInterfaceMode("developer")' in dev_settings
    assert 'backend.setInterfaceMode("developer")' in user_settings
    assert "backend.interfaceMode" in user_settings
    assert "backend.uiMode" in user_settings
    mode_card = interface_mode_card_source()
    assert "startProtected" not in mode_card
    assert "stopCurrentSession" not in mode_card


def test_user_shell_stays_free_of_developer_diagnostics():
    user_files = [
        "qml/UserShell.qml",
        "qml/pages/user/UserHomePage.qml",
        "qml/pages/user/UserProtectionPage.qml",
        "qml/pages/user/UserModelUpdatePage.qml",
        "qml/pages/user/UserSettingsPage.qml",
    ]
    forbidden = ["FAR", "FRR", "far", "frr", "Drift", "drift", "reason_codes", "gateResults", "shadowStatus"]
    for rel in user_files:
        text = read(rel)
        assert not any(token in text for token in forbidden), rel

def test_backend_ui_mode_slot_grants_user_shell_flag_without_qml_readiness_logic():
    settings = read("bridge/settings_mixin.py")
    slot = settings[settings.index("def setInterfaceMode"):settings.index("def setThemeMode")]
    assert 'changes: Dict[str, Any] = {"interface_mode": requested}' in slot
    assert 'if requested == "user":' in slot
    assert 'changes["enable_user_shell"] = True' in slot
    assert 'elif requested == "developer":' in slot
    assert 'changes["enable_user_shell"] = False' in slot
    assert 'if requested == current:\n            return' not in slot
    forbidden = ["startProtected", "stopCurrentSession", "protectedSessionsAvailable", "production_ready", "approved_for_production"]
    assert not any(token in slot for token in forbidden)


def test_user_ui_choice_copy_no_longer_says_user_shell_is_unavailable_when_clicked():
    dev_settings = read("qml/pages/settings/SettingsGeneralTab.qml")
    mode_card = interface_mode_card_source()
    assert 'backend.setInterfaceMode("user")' in mode_card
    assert 'backend.setInterfaceMode("developer")' in mode_card
    assert "enable_user_shell مفعّلة" not in mode_card
    assert "Loads only when enable_user_shell is enabled" not in mode_card
