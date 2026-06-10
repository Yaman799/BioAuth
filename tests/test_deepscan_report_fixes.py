from __future__ import annotations

from pathlib import Path


def read(rel: str) -> str:
    return Path(rel).read_text(encoding='utf-8')


def test_session_runtime_helpers_non_blocking_start_and_stop() -> None:
    text = read('bridge/session_runtime_helpers.py')
    assert 'time.sleep(0.15)' not in text
    assert '_pending_logger_start = True' in text
    assert 'threading.Thread(target=_wait_for_exit, daemon=True).start()' in text


def test_appshell_uses_static_nav_model_and_computed_titles() -> None:
    text = read('qml/AppShell.qml')
    assert 'ListModel {' in text and 'id: navModel' in text
    assert 'function refreshNavModel()' in text
    assert 'readonly property string currentPageTitle' in text
    assert 'readonly property string currentPageSubtitle' in text
    assert 'pageTitle()' not in text
    assert 'pageSubtitle()' not in text


def test_livesession_uses_persistent_telemetry_model() -> None:
    text = read('qml/pages/LiveSessionPage.qml')
    assert 'id: telemetryListModel' in text
    assert 'function refreshTelemetryModel()' in text
    assert 'model: telemetryModel()' not in text


def test_history_page_caches_sessions_and_selection_count() -> None:
    text = read('qml/pages/HistoryPage.qml')
    assert 'readonly property var sessionList: backend.sessions' in text
    assert 'property int selectionCount: 0' in text
    assert 'function selectedCount()' not in text
    assert 'model: root.sessionList' in text


def test_overview_and_profile_cache_progress_strings() -> None:
    for rel in ('qml/pages/OverviewPage.qml', 'qml/pages/ProfilePage.qml'):
        text = read(rel)
        assert 'readonly property string heartbeatSummary' in text
        assert 'readonly property string positiveSessionsSummary' in text
        assert 'readonly property string referenceNegativesSummary' in text
        assert 'heartbeatText().length' not in text
        assert 'positiveSessionsText().length' not in text


def test_settings_tabs_use_static_models_for_repeater_and_comboboxes() -> None:
    settings = read('qml/pages/SettingsPage.qml')
    assert 'id: settingsTabModel' in settings
    assert 'model: settingsTabModel' in settings
    startup = read('qml/pages/settings/SettingsStartupTab.qml')
    assert 'id: timeoutModel' in startup
    assert 'model: timeoutModel' in startup
    security = read('qml/pages/settings/SettingsSecurityTab.qml')
    assert 'id: retentionModel' in security
    assert 'model: retentionModel' in security


def test_components_no_longer_bind_backend_theme_mode_directly() -> None:
    qml_dir = Path('qml/components')
    for path in qml_dir.glob('*.qml'):
        text = path.read_text(encoding='utf-8')
        assert 'backend.themeMode' not in text
        assert 'property var theme: backend.theme' not in text
