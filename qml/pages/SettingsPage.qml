import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "settings" as SettingsUi

Item {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property int activeTab: 0
    property bool draftsReady: false
    property string draftTheme: "dark"
    property string draftLanguage: "en"
    property bool draftButtonSoundsMuted: false
    property string draftDeepRuntimeMode: "auto"
    property string draftRiskSensitivity: "balanced"
    property bool draftRememberLoginEnabled: false
    property bool draftRunOnStartup: false
    property bool draftIncidentEvidenceEnabled: false
    property bool draftSmartAutoEnrollmentEnabled: false
    property bool draftAutoTrainWhenReadyEnabled: false
    property bool draftAutoPromoteWhenProductionSafeEnabled: false
    property bool draftIncidentEvidenceCaptureScreenshot: true
    property bool draftIncidentEvidenceCaptureWebcam: true
    property int draftIncidentEvidenceRetentionDays: 30
    property bool draftAppPasscodeEnabled: false
    property int draftAppPasscodeTimeoutSec: 60
    property bool compactPage: (rootWindow ? rootWindow.width : width) < 1180
    property bool narrowPage: (rootWindow ? rootWindow.width : width) < 980
    property bool veryNarrowPage: (rootWindow ? rootWindow.width : width) < 760
    property var currentPasscodeField: null
    property var newPasscodeField: null
    property var confirmPasscodeField: null

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function syncDraftsFromBackend() {
        draftTheme = backend.themeMode
        draftLanguage = backend.language
        draftButtonSoundsMuted = backend.buttonSoundsMuted
        draftDeepRuntimeMode = backend.deepRuntimeMode
        draftRiskSensitivity = backend.riskSensitivityPreset
        draftRememberLoginEnabled = backend.rememberLoginEnabled
        draftRunOnStartup = backend.runOnStartup
        draftIncidentEvidenceEnabled = backend.incidentEvidenceEnabled
        draftSmartAutoEnrollmentEnabled = (backend.autoEnrollmentState && backend.autoEnrollmentState.enabled === true)
        draftAutoTrainWhenReadyEnabled = (backend.autoEnrollmentState && backend.autoEnrollmentState.autoTrainingEnabled === true)
        draftAutoPromoteWhenProductionSafeEnabled = (backend.autoEnrollmentState && backend.autoEnrollmentState.autoPromotionEnabled === true)
        draftIncidentEvidenceCaptureScreenshot = backend.incidentEvidenceCaptureScreenshot
        draftIncidentEvidenceCaptureWebcam = backend.incidentEvidenceCaptureWebcam
        draftIncidentEvidenceRetentionDays = backend.incidentEvidenceRetentionDays
        draftAppPasscodeEnabled = backend.appPasscodeEnabled
        draftAppPasscodeTimeoutSec = backend.appPasscodeTimeoutSec
        draftsReady = true
    }
    readonly property bool hasSettingsDraftChanges: draftsReady && (draftTheme !== backend.themeMode || draftLanguage !== backend.language || draftButtonSoundsMuted !== backend.buttonSoundsMuted || draftDeepRuntimeMode !== backend.deepRuntimeMode || draftRiskSensitivity !== backend.riskSensitivityPreset || draftRememberLoginEnabled !== backend.rememberLoginEnabled || draftRunOnStartup !== backend.runOnStartup || draftIncidentEvidenceEnabled !== backend.incidentEvidenceEnabled || draftSmartAutoEnrollmentEnabled !== (backend.autoEnrollmentState && backend.autoEnrollmentState.enabled === true) || draftAutoTrainWhenReadyEnabled !== (backend.autoEnrollmentState && backend.autoEnrollmentState.autoTrainingEnabled === true) || draftAutoPromoteWhenProductionSafeEnabled !== (backend.autoEnrollmentState && backend.autoEnrollmentState.autoPromotionEnabled === true) || draftIncidentEvidenceCaptureScreenshot !== backend.incidentEvidenceCaptureScreenshot || draftIncidentEvidenceCaptureWebcam !== backend.incidentEvidenceCaptureWebcam || draftIncidentEvidenceRetentionDays !== backend.incidentEvidenceRetentionDays || draftAppPasscodeEnabled !== backend.appPasscodeEnabled || draftAppPasscodeTimeoutSec !== backend.appPasscodeTimeoutSec)
    readonly property bool hasPasscodeDraftChanges: (currentPasscodeField && currentPasscodeField.text !== "") || (newPasscodeField && newPasscodeField.text !== "") || (confirmPasscodeField && confirmPasscodeField.text !== "")
    readonly property bool hasPendingChanges: hasSettingsDraftChanges || hasPasscodeDraftChanges
    function clearPasscodeDrafts() {
        if (currentPasscodeField) currentPasscodeField.text = ""
        if (newPasscodeField) newPasscodeField.text = ""
        if (confirmPasscodeField) confirmPasscodeField.text = ""
    }
    function applyChanges() {
        if (draftTheme !== backend.themeMode) backend.setThemeMode(draftTheme)
        if (draftLanguage !== backend.language) backend.setLanguageCode(draftLanguage)
        if (draftButtonSoundsMuted !== backend.buttonSoundsMuted) backend.setButtonSoundsMuted(draftButtonSoundsMuted)
        if (draftDeepRuntimeMode !== backend.deepRuntimeMode) backend.setDeepRuntimeMode(draftDeepRuntimeMode)
        if (draftRiskSensitivity !== backend.riskSensitivityPreset) backend.setRiskSensitivityPreset(draftRiskSensitivity)
        if (draftRememberLoginEnabled !== backend.rememberLoginEnabled) backend.setRememberLoginEnabled(draftRememberLoginEnabled)
        if (draftRunOnStartup !== backend.runOnStartup) backend.setStartupEnabled(draftRunOnStartup)
        if (draftIncidentEvidenceEnabled !== backend.incidentEvidenceEnabled) backend.setIncidentEvidenceEnabled(draftIncidentEvidenceEnabled)
        if (draftSmartAutoEnrollmentEnabled !== (backend.autoEnrollmentState && backend.autoEnrollmentState.enabled === true)) backend.setSmartAutoEnrollmentEnabled(draftSmartAutoEnrollmentEnabled)
        if (draftAutoTrainWhenReadyEnabled !== (backend.autoEnrollmentState && backend.autoEnrollmentState.autoTrainingEnabled === true)) backend.setAutoTrainWhenReadyEnabled(draftAutoTrainWhenReadyEnabled)
        if (draftAutoPromoteWhenProductionSafeEnabled !== (backend.autoEnrollmentState && backend.autoEnrollmentState.autoPromotionEnabled === true)) backend.setAutoPromoteWhenProductionSafeEnabled(draftAutoPromoteWhenProductionSafeEnabled)
        if (draftIncidentEvidenceCaptureScreenshot !== backend.incidentEvidenceCaptureScreenshot) backend.setIncidentEvidenceCaptureScreenshot(draftIncidentEvidenceCaptureScreenshot)
        if (draftIncidentEvidenceCaptureWebcam !== backend.incidentEvidenceCaptureWebcam) backend.setIncidentEvidenceCaptureWebcam(draftIncidentEvidenceCaptureWebcam)
        if (draftIncidentEvidenceRetentionDays !== backend.incidentEvidenceRetentionDays) backend.setIncidentEvidenceRetentionDays(draftIncidentEvidenceRetentionDays)
        if ((newPasscodeField && newPasscodeField.text !== "") || (confirmPasscodeField && confirmPasscodeField.text !== "")) {
            backend.updateAppPasscode(currentPasscodeField ? currentPasscodeField.text : "", newPasscodeField.text, confirmPasscodeField.text)
            clearPasscodeDrafts()
        }
        if (draftAppPasscodeTimeoutSec !== backend.appPasscodeTimeoutSec) backend.setAppPasscodeTimeoutSec(draftAppPasscodeTimeoutSec)
        if (draftAppPasscodeEnabled !== backend.appPasscodeEnabled) {
            if (draftAppPasscodeEnabled) {
                backend.setAppPasscodeEnabled(true)
            } else if (backend.disableAppPasscode(currentPasscodeField ? currentPasscodeField.text : "")) {
                clearPasscodeDrafts()
            }
        }
        Qt.callLater(syncDraftsFromBackend)
    }
    ListModel {
        id: settingsTabModel
        ListElement { title: ""; note: ""; icon: "" }
        ListElement { title: ""; note: ""; icon: "" }
        ListElement { title: ""; note: ""; icon: "" }
        ListElement { title: ""; note: ""; icon: "" }
        ListElement { title: ""; note: ""; icon: "" }
        ListElement { title: ""; note: ""; icon: "" }
    }
    function setSectionModelRow(row, title, note, icon) {
        settingsTabModel.setProperty(row, "title", title)
        settingsTabModel.setProperty(row, "note", note)
        settingsTabModel.setProperty(row, "icon", icon)
    }
    function refreshTabModel() {
        setSectionModelRow(0, trx("General", "General"), trx("Theme, language, and interaction preferences", "Theme, language, and interaction preferences"), "⚙")
        setSectionModelRow(1, trx("Security & Privacy", "Security & Privacy"), trx("Password, remembered sign-in, and local evidence controls", "Password, remembered sign-in, and local evidence controls"), "◇")
        setSectionModelRow(2, trx("Protection & Risk", "Protection & Risk"), trx("Profile readiness, runtime trust, and risk sensitivity", "Profile readiness, runtime trust, and risk sensitivity"), "◎")
        setSectionModelRow(3, trx("Startup & Sessions", "Startup & Sessions"), trx("Windows startup and app passcode session guard", "Windows startup and app passcode session guard"), "↗")
        setSectionModelRow(4, trx("Account & Data", "Account & Data"), trx("Identity, recovery, profile reset, and account deletion", "Identity, recovery, profile reset, and account deletion"), "ID")
        setSectionModelRow(5, trx("Performance / Advanced", "Performance / Advanced"), trx("Deep runtime mode and device benchmark", "Deep runtime mode and device benchmark"), "⚡")
    }
    function sectionStatus(index) {
        if (index === 0) return root.draftTheme + " / " + root.draftLanguage
        if (index === 1) return root.draftSmartAutoEnrollmentEnabled ? trx("Smart enrollment", "Smart enrollment") : (root.draftRememberLoginEnabled ? trx("Remembered", "Remembered") : trx("Local only", "Local only"))
        if (index === 2) return root.draftRiskSensitivity
        if (index === 3) return root.draftRunOnStartup ? trx("Startup on", "Startup on") : trx("Manual", "Manual")
        if (index === 4) return (backend.currentUser && (backend.currentUser.display_name || backend.currentUser.user_id)) || trx("Account", "Account")
        if (index === 5) return root.draftDeepRuntimeMode
        return ""
    }
    Component.onCompleted: { syncDraftsFromBackend(); refreshTabModel() }

    Connections {
        target: backend
        function onThemeChanged() { if (!root.hasPendingChanges) root.syncDraftsFromBackend() }
        function onLanguageChanged() { if (!root.hasPendingChanges) root.syncDraftsFromBackend(); root.refreshTabModel() }
        function onStartupChanged() { if (!root.hasPendingChanges) root.syncDraftsFromBackend() }
        function onRememberLoginChanged() { if (!root.hasPendingChanges) root.syncDraftsFromBackend() }
        function onRiskSensitivityChanged() { if (!root.hasPendingChanges) root.syncDraftsFromBackend() }
        function onButtonSoundsMutedChanged() { if (!root.hasPendingChanges) root.syncDraftsFromBackend() }
        function onDeepRuntimeChanged() { if (!root.hasPendingChanges) root.syncDraftsFromBackend() }
        function onIncidentEvidenceChanged() { if (!root.hasPendingChanges) root.syncDraftsFromBackend() }
        function onAppPasscodeChanged() { if (!root.hasPendingChanges) root.syncDraftsFromBackend() }
        function onAutoEnrollmentChanged() { if (!root.hasPendingChanges) root.syncDraftsFromBackend() }
    }


    Component {
        id: generalTabComponent
        SettingsUi.SettingsGeneralTab {
            controller: root
            theme: root.theme
            rootWindow: root.rootWindow
        }
    }

    Component {
        id: securityTabComponent
        SettingsUi.SettingsSecurityTab {
            controller: root
            theme: root.theme
            rootWindow: root.rootWindow
            sectionMode: "security"
        }
    }

    Component {
        id: protectionTabComponent
        SettingsUi.SettingsSecurityTab {
            controller: root
            theme: root.theme
            rootWindow: root.rootWindow
            sectionMode: "protection"
        }
    }

    Component {
        id: startupTabComponent
        SettingsUi.SettingsStartupTab {
            controller: root
            theme: root.theme
            rootWindow: root.rootWindow
            Component.onCompleted: {
                root.currentPasscodeField = currentPasscodeFieldRef
                root.newPasscodeField = newPasscodeFieldRef
                root.confirmPasscodeField = confirmPasscodeFieldRef
            }
        }
    }

    Component {
        id: accountTabComponent
        SettingsUi.SettingsAccountTab {
            controller: root
            theme: root.theme
            rootWindow: root.rootWindow
        }
    }

    Component {
        id: performanceTabComponent
        SettingsUi.SettingsPerformanceTab {
            controller: root
            theme: root.theme
            rootWindow: root.rootWindow
        }
    }

    anchors.fill: parent

    ScrollView {
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        Item {
            width: parent.width
            implicitHeight: settingsColumn.implicitHeight + 24

            ColumnLayout {
                id: settingsColumn
                width: parent.width
                spacing: 16

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: settingsIntroContent.implicitHeight + 44

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 22
                        spacing: 16

                        ColumnLayout {
                            id: settingsIntroContent
                            Layout.fillWidth: true
                            spacing: 8
                            SectionHeader {
                                title: backend.tr("settings")
                                subtitle: trx("إعدادات التطبيق والأمان والتشغيل من مكان واحد.", "App, security, and startup settings in one place.")
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 10
                                InfoPill { textValue: backend.tr("theme") + ": " + root.draftTheme; pillTone: "details" }
                                InfoPill { textValue: backend.tr("language") + ": " + root.draftLanguage; pillTone: "analyze" }
                                InfoPill { textValue: trx("Startup", "Startup") + ": " + (root.draftRunOnStartup ? trx("On", "On") : trx("Off", "Off")); pillTone: root.draftRunOnStartup ? "success" : "neutral" }
                            }
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: root.veryNarrowPage ? 1 : 2
                    columnSpacing: 12
                    rowSpacing: 12

                    Repeater {
                        model: settingsTabModel
                        delegate: SettingsSectionCard {
                            theme: root.theme
                            titleText: title
                            noteText: note
                            iconText: icon
                            statusText: root.sectionStatus(index)
                            selected: root.activeTab === index
                            onChosen: root.activeTab = index
                        }
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    visible: root.hasPendingChanges
                    implicitHeight: pendingChangesRow.implicitHeight + 36
                    RowLayout {
                        id: pendingChangesRow
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 14
                        Rectangle {
                            implicitWidth: 44
                            implicitHeight: 44
                            radius: 14
                            color: theme.warningBg
                            border.color: theme.warn
                            border.width: 1
                            Label { anchors.centerIn: parent; text: "!"; color: theme.warn; font.bold: true; font.pixelSize: 20 }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Label { text: backend.tr("save_changes"); color: theme.text; font.bold: true }
                            Label { text: backend.tr("unsaved_changes_note"); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                        AppButton {
                            text: backend.tr("save_changes")
                            role: "warn"
                            onClicked: root.applyChanges()
                        }
                    }
                }

                Loader {
                    id: generalTabLoader
                    Layout.fillWidth: true
                    active: root.activeTab === 0
                    visible: active
                    asynchronous: true
                    sourceComponent: generalTabComponent
                }

                Loader {
                    id: securityTabLoader
                    Layout.fillWidth: true
                    active: root.activeTab === 1
                    visible: active
                    asynchronous: true
                    sourceComponent: securityTabComponent
                }

                Loader {
                    id: protectionTabLoader
                    Layout.fillWidth: true
                    active: root.activeTab === 2
                    visible: active
                    asynchronous: true
                    sourceComponent: protectionTabComponent
                }

                Loader {
                    id: startupTabLoader
                    Layout.fillWidth: true
                    active: root.activeTab === 3
                    visible: active
                    asynchronous: true
                    sourceComponent: startupTabComponent
                    onActiveChanged: {
                        if (!active) {
                            root.currentPasscodeField = null
                            root.newPasscodeField = null
                            root.confirmPasscodeField = null
                        }
                    }
                    onLoaded: {
                        root.currentPasscodeField = item.currentPasscodeFieldRef
                        root.newPasscodeField = item.newPasscodeFieldRef
                        root.confirmPasscodeField = item.confirmPasscodeFieldRef
                    }
                }

                Loader {
                    id: accountTabLoader
                    Layout.fillWidth: true
                    active: root.activeTab === 4
                    visible: active
                    asynchronous: true
                    sourceComponent: accountTabComponent
                }

                Loader {
                    id: performanceTabLoader
                    Layout.fillWidth: true
                    active: root.activeTab === 5
                    visible: active
                    asynchronous: true
                    sourceComponent: performanceTabComponent
                }
            }
        }
    }
}
