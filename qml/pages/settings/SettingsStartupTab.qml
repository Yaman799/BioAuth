import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

Item {
    id: startupTab
    property var controller
    property var theme
    property var rootWindow
    function trx(arText, enText) { return controller ? controller.trx(arText, enText) : enText }

    readonly property var timeoutValues: [30, 60, 120, 300]

    ListModel {
        id: timeoutModel
        ListElement { secs: 30; label: "" }
        ListElement { secs: 60; label: "" }
        ListElement { secs: 120; label: "" }
        ListElement { secs: 300; label: "" }
    }

    function refreshTimeoutLabels() {
        timeoutModel.setProperty(0, "label", backend.tr("app_passcode_timeout_30"))
        timeoutModel.setProperty(1, "label", backend.tr("app_passcode_timeout_60"))
        timeoutModel.setProperty(2, "label", backend.tr("app_passcode_timeout_120"))
        timeoutModel.setProperty(3, "label", backend.tr("app_passcode_timeout_300"))
    }

    Component.onCompleted: refreshTimeoutLabels()
    Connections {
        target: backend
        function onLanguageChanged() { startupTab.refreshTimeoutLabels() }
    }
    property alias currentPasscodeFieldRef: currentPasscodeField
    property alias newPasscodeFieldRef: newPasscodeField
    property alias confirmPasscodeFieldRef: confirmPasscodeField
    Layout.fillWidth: true
        implicitHeight: startupGrid.implicitHeight

    GridLayout {
        id: startupGrid
        width: parent.width
        columns: width >= 1120 ? 2 : 1
        columnSpacing: 16
        rowSpacing: 16

        SettingsCompanionMobileCard {
            Layout.fillWidth: true
            Layout.columnSpan: startupGrid.columns
            controller: controller
            theme: theme
            rootWindow: rootWindow
        }

        GlassCard {
            Layout.fillWidth: true
            implicitHeight: startupLaunchContent.implicitHeight + 40
            ColumnLayout {
                id: startupLaunchContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 14
                SectionHeader {
                    title: trx("Launch on startup", "Launch on startup")
                    subtitle: trx("تشغيل التطبيق تلقائيًا عند تسجيل الدخول إلى ويندوز.", "Launch the app automatically when you sign in to Windows.")
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: startupLaunchRow.implicitHeight + 28
                    radius: 18
                    color: theme.surface1
                    border.color: theme.border
                    border.width: 1

                    function toggleStartupState() {
                        controller.draftRunOnStartup = !controller.draftRunOnStartup
                        if (controller.draftRunOnStartup)
                            controller.draftRememberLoginEnabled = true
                    }

                    RowLayout {
                        id: startupLaunchRow
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 14
                        Rectangle {
                            implicitWidth: 42
                            implicitHeight: 42
                            radius: 14
                            color: controller.draftRunOnStartup ? "#0b6da8" : (theme.iconActiveBg)
                            border.color: controller.draftRunOnStartup ? "#22d3ee" : theme.border
                            border.width: 1
                            Label {
                                anchors.centerIn: parent
                                text: "↗"
                                color: controller.draftRunOnStartup ? "#ffffff" : theme.muted
                                font.pixelSize: 18
                                font.bold: true
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Label { text: backend.tr("run_on_startup"); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: controller.draftRunOnStartup ? trx("Enabled. BioAuth starts after Windows sign-in and can resume protection automatically when a remembered profile is ready.", "Enabled. BioAuth starts after Windows sign-in and can resume protection automatically when a remembered profile is ready.") : trx("Disabled. The app starts only when you open it manually.", "Disabled. The app starts only when you open it manually."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                        StartupSwitch {
                            text: ""
                            checked: controller.draftRunOnStartup
                            onToggled: function(nextChecked) { controller.draftRunOnStartup = nextChecked; if (nextChecked) controller.draftRememberLoginEnabled = true }
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: parent.toggleStartupState()
                    }
                }
            }
        }

        GlassCard {
            Layout.fillWidth: true
            implicitHeight: startupNotesContent.implicitHeight + 40
            ColumnLayout {
                id: startupNotesContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                SectionHeader {
                    title: trx("Startup notes", "Startup notes")
                    subtitle: trx("ما الذي يحدث عند تفعيل التشغيل التلقائي.", "What happens when startup is enabled.")
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: startupNotesSummary.implicitHeight + 28
                    radius: 18
                    color: theme.surface1
                    border.color: theme.border
                    border.width: 1
                    ColumnLayout {
                        id: startupNotesSummary
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 8
                        Label { text: trx("• Enabling startup also keeps remembered sign-in enabled on this device.", "• Enabling startup also keeps remembered sign-in enabled on this device."); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: trx("• If a remembered profile is ready, BioAuth starts protected mode automatically after sign-in.", "• If a remembered profile is ready, BioAuth starts protected mode automatically after sign-in."); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: trx("• If no remembered profile is available, the app still launches but waits for manual sign-in.", "• If no remembered profile is available, the app still launches but waits for manual sign-in."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }
        }

        GlassCard {
            Layout.fillWidth: true
            Layout.columnSpan: startupGrid.columns
            implicitHeight: passcodeContent.implicitHeight + 40

            ColumnLayout {
                id: passcodeContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 14
                SectionHeader {
                    title: backend.tr("app_passcode")
                    subtitle: backend.tr("app_passcode_note")
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: passcodeToggleRow.implicitHeight + 28
                    radius: 18
                    color: theme.surface1
                    border.color: theme.border
                    border.width: 1

                    RowLayout {
                        id: passcodeToggleRow
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 14

                        Rectangle {
                            implicitWidth: 42
                            implicitHeight: 42
                            radius: 14
                            color: controller.draftAppPasscodeEnabled ? "#0b6da8" : (theme.iconActiveBg)
                            border.color: controller.draftAppPasscodeEnabled ? theme.accent : theme.border
                            border.width: 1
                            Label {
                                anchors.centerIn: parent
                                text: "🔒"
                                font.pixelSize: 18
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Label { text: backend.tr("app_passcode"); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label {
                                text: controller.draftAppPasscodeEnabled ? trx("مفعّل. ستُقفل واجهة BioAuth فقط بعد مهلة الخمول، بينما تبقى الحماية والجلسات شغالة في الخلفية.", "Enabled. Only the BioAuth interface locks after the idle timeout while protection and sessions keep running in the background.") : trx("معطّل. تبقى الواجهة مفتوحة حتى عند ترك التطبيق.", "Disabled. The interface stays open even when the app is left unattended.")
                                color: theme.muted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }

                        StartupSwitch {
                            checked: controller.draftAppPasscodeEnabled
                            onToggled: function(nextChecked) { controller.draftAppPasscodeEnabled = nextChecked }
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: controller.compactPage ? 1 : 2
                    columnSpacing: 12
                    rowSpacing: 12

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Label { text: backend.tr("app_passcode_timeout"); color: theme.text; font.bold: true }
                        ComboBox {
                            id: passcodeTimeoutBox
                            Layout.fillWidth: true
                            model: timeoutModel
                            textRole: "label"
                            currentIndex: Math.max(0, timeoutValues.indexOf(controller.draftAppPasscodeTimeoutSec))
                            onActivated: controller.draftAppPasscodeTimeoutSec = timeoutModel.get(currentIndex).secs
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: controller.compactPage
                        Layout.preferredWidth: controller.compactPage ? 0 : 220
                        Layout.alignment: Qt.AlignBottom
                        implicitHeight: 48
                        radius: 16
                        color: theme.surface2
                        border.color: theme.border
                        border.width: 1
                        Label {
                            anchors.centerIn: parent
                            text: backend.appPasscodeConfigured ? trx("الباسكود مضبوط على هذا الجهاز", "Passcode is configured on this device") : trx("لا يوجد باسكود مضبوط بعد", "No passcode set yet")
                            color: backend.appPasscodeConfigured ? theme.text : theme.muted
                            font.bold: backend.appPasscodeConfigured
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 1120 ? 3 : 1
                    columnSpacing: 12
                    rowSpacing: 12

                    AppTextField {
                        id: currentPasscodeField
                        Layout.fillWidth: true
                        placeholderText: backend.tr("app_passcode_current")
                        echoMode: TextInput.Password
                        inputMethodHints: Qt.ImhDigitsOnly | Qt.ImhSensitiveData
                        visible: backend.appPasscodeConfigured
                    }

                    AppTextField {
                        id: newPasscodeField
                        Layout.fillWidth: true
                        placeholderText: backend.tr("app_passcode_new")
                        echoMode: TextInput.Password
                        inputMethodHints: Qt.ImhDigitsOnly | Qt.ImhSensitiveData
                    }

                    AppTextField {
                        id: confirmPasscodeField
                        Layout.fillWidth: true
                        placeholderText: backend.tr("app_passcode_confirm")
                        echoMode: TextInput.Password
                        inputMethodHints: Qt.ImhDigitsOnly | Qt.ImhSensitiveData
                        onAccepted: controller.applyChanges()
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: controller.compactPage ? 1 : 2
                    columnSpacing: 12
                    rowSpacing: 12
                    AppButton {
                        text: backend.tr("app_passcode_clear")
                        role: "danger"
                        compact: true
                        enabled: backend.appPasscodeConfigured
                        onClicked: {
                            if (backend.clearAppPasscode(currentPasscodeField.text)) {
                                currentPasscodeField.text = ""
                                newPasscodeField.text = ""
                                confirmPasscodeField.text = ""
                            }
                            Qt.callLater(controller.syncDraftsFromBackend)
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: trx("قد تستمر الحماية والمراقبة وSmart Auto Enrollment أثناء قفل واجهة BioAuth بالباسكود.", "Protection, monitoring, and Smart Auto Enrollment may continue while the BioAuth interface is passcode-locked.")
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }

}
