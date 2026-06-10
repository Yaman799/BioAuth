import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

Item {
    property var controller
    property var theme
    property var rootWindow
    property var updateState: backend.updateState || ({})
    function trx(arText, enText) { return controller ? controller.trx(arText, enText) : enText }
    Layout.fillWidth: true
        implicitHeight: generalContent.implicitHeight

    ColumnLayout {
        id: generalContent
        width: parent.width
        spacing: 16

        GridLayout {
            id: generalGrid
            Layout.fillWidth: true
            columns: width >= 1120 ? 2 : 1
            columnSpacing: 16
            rowSpacing: 16


        GlassCard {
            Layout.fillWidth: true
            implicitHeight: updateContent.implicitHeight + 40
            ColumnLayout {
                id: updateContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                SectionHeader {
                    title: trx("Updates", "Updates")
                    subtitle: trx("تحقق يدويًا من إصدارات GitHub العامة وثبّت فقط بعد التحقق من SHA256.", "Manually check public GitHub Releases and install only after SHA256 verification.")
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: updateSummary.implicitHeight + 28
                    radius: 18
                    color: theme.surface1
                    border.color: theme.border
                    border.width: 1
                    ColumnLayout {
                        id: updateSummary
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 8
                        Label {
                            Layout.fillWidth: true
                            text: trx("Current version", "Current version") + ": " + (backend.appVersion || updateState.currentVersion || "-")
                            color: theme.text
                            font.bold: true
                            wrapMode: Text.Wrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: trx("Latest version", "Latest version") + ": " + (updateState.latestVersion && updateState.latestVersion.length > 0 ? updateState.latestVersion : "-")
                            color: theme.muted
                            wrapMode: Text.Wrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: trx("Status", "Status") + ": " + (updateState.status || "Idle")
                            color: (updateState.state === "hash_verification_failed" || updateState.state === "invalid_update_manifest" || updateState.state === "download_failed" || updateState.state === "install_failed") ? theme.danger : (updateState.state === "ready_to_install" ? theme.success : theme.text)
                            font.bold: true
                            wrapMode: Text.Wrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: updateState.message || trx("Click Check for updates to contact the configured public GitHub Releases endpoint.", "Click Check for updates to contact the configured public GitHub Releases endpoint.")
                            color: theme.muted
                            wrapMode: Text.Wrap
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: updateState.releaseNotes && updateState.releaseNotes.length > 0
                            text: trx("Release notes", "Release notes") + ": " + updateState.releaseNotes
                            color: theme.muted
                            wrapMode: Text.Wrap
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            AppButton {
                                text: trx("Check for updates", "Check for updates")
                                role: "details"
                                compact: true
                                enabled: updateState.canCheck !== false
                                onClicked: backend.checkForUpdates()
                            }
                            AppButton {
                                text: trx("Download update", "Download update")
                                role: "warn"
                                compact: true
                                visible: updateState.canDownload === true
                                enabled: updateState.canDownload === true
                                onClicked: backend.downloadAvailableUpdate()
                            }
                            AppButton {
                                text: trx("Install verified update", "Install verified update")
                                role: "warn"
                                compact: true
                                visible: updateState.canInstall === true
                                enabled: updateState.canInstall === true
                                onClicked: backend.openDownloadedUpdateInstaller()
                            }
                            Label {
                                Layout.fillWidth: true
                                text: trx("No silent updates: download and install both require your click.", "No silent updates: download and install both require your click.")
                                color: theme.muted
                                wrapMode: Text.Wrap
                            }
                        }
                    }
                }
            }
        }


            GlassCard {
                Layout.fillWidth: true
                implicitHeight: interfaceModeContent.implicitHeight + 40
                ColumnLayout {
                    id: interfaceModeContent
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 14
                    SectionHeader {
                        title: trx("عرض التطبيق", "App view")
                        subtitle: trx("اختر طريقة عرض الواجهة فقط. هذا لا يبدأ جلسات الحماية ولا يوقفها.", "Choose only how the app is displayed. This does not start or stop protection.")
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        ChoiceChip {
                            titleText: trx("الواجهة الأساسية", "Essential view")
                            descriptionText: trx("واجهة مبسطة للاستخدام اليومي. اختيارك محفوظ بواسطة النظام.", "A simplified view for everyday use. Your choice is saved by the system.")
                            selected: backend.interfaceMode === "user"
                            accentColor: theme.accent
                            onChosen: backend.setInterfaceMode("user")
                        }
                        ChoiceChip {
                            titleText: trx("العرض المتقدم", "Advanced view")
                            descriptionText: trx("عرض موسّع يحتوي على التشخيصات الكاملة.", "An expanded view with full diagnostics.")
                            selected: backend.interfaceMode === "developer"
                            accentColor: theme.primary
                            onChosen: backend.setInterfaceMode("developer")
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: trx("العرض الحالي", "Current view") + ": " + (backend.uiMode === "user" ? trx("الواجهة الأساسية", "Essential view") : trx("العرض المتقدم", "Advanced view"))
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                implicitHeight: themeCardContent.implicitHeight + 40
                ColumnLayout {
                    id: themeCardContent
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 14
                    SectionHeader {
                        title: trx("Theme", "Theme")
                        subtitle: trx("اختر مظهر التطبيق.", "Choose the app appearance.")
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        ChoiceChip {
                            titleText: trx("داكن", "Dark")
                            descriptionText: trx("الوضع الداكن المناسب للعمل اليومي.", "Dark mode for everyday use.")
                            selected: controller.draftTheme === "dark"
                            accentColor: theme.accent
                            onChosen: controller.draftTheme = "dark"
                        }
                        ChoiceChip {
                            titleText: trx("فاتح", "Light")
                            descriptionText: trx("الوضع الفاتح بواجهة واضحة.", "Light mode with a clear interface.")
                            selected: controller.draftTheme === "light"
                            accentColor: theme.primary
                            onChosen: controller.draftTheme = "light"
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: themeSummaryContent.implicitHeight + 28
                        radius: 18
                        color: controller.draftTheme === "dark" ? "#0f1928" : "#eff5fc"
                        border.color: theme.border
                        border.width: 1
                        ColumnLayout {
                            id: themeSummaryContent
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 4
                            Label { text: trx("Current mode", "Current mode"); color: theme.muted; font.bold: true }
                            Label { text: controller.draftTheme === "dark" ? trx("Dark mode selected", "Dark mode selected") : trx("Light mode selected", "Light mode selected"); color: theme.text }
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                implicitHeight: languageCardContent.implicitHeight + 40
                ColumnLayout {
                    id: languageCardContent
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 14
                    SectionHeader {
                        title: trx("Language", "Language")
                        subtitle: trx("اختر لغة الواجهة.", "Choose the interface language.")
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        ChoiceChip {
                            titleText: "العربية"
                            descriptionText: trx("واجهة عربية كاملة.", "Full Arabic interface.")
                            selected: controller.draftLanguage === "ar"
                            accentColor: "#a855f7"
                            onChosen: controller.draftLanguage = "ar"
                        }
                        ChoiceChip {
                            titleText: "English"
                            descriptionText: trx("واجهة إنجليزية كاملة.", "Full English interface.")
                            selected: controller.draftLanguage === "en"
                            accentColor: "#06b6d4"
                            onChosen: controller.draftLanguage = "en"
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: languageSummaryContent.implicitHeight + 28
                        radius: 18
                        color: controller.draftTheme === "dark" ? "#0f1928" : "#eff5fc"
                        border.color: theme.border
                        border.width: 1
                        ColumnLayout {
                            id: languageSummaryContent
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 4
                            Label { text: trx("Current language", "Current language"); color: theme.muted; font.bold: true }
                            Label { text: controller.draftLanguage === "ar" ? trx("Arabic selected", "Arabic selected") : trx("English selected", "English selected"); color: theme.text }
                        }
                    }
                }
            }
        }

        GlassCard {
            Layout.fillWidth: true
            implicitHeight: buttonSoundsContent.implicitHeight + 40
            ColumnLayout {
                id: buttonSoundsContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                SectionHeader {
                    title: trx("Button sounds", "Button sounds")
                    subtitle: trx("تحكم بأصوات الضغطات داخل الواجهة وأصوات تنبيه ويندوز الناتجة عنها بدون التأثير على بقية التنبيهات الأمنية.", "Control button click sounds and related Windows click feedback without affecting other security notifications.")
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: buttonSoundsRow.implicitHeight + 28
                    radius: 18
                    color: controller.draftButtonSoundsMuted ? theme.dangerBg : theme.surface1
                    border.color: controller.draftButtonSoundsMuted ? theme.danger : theme.border
                    border.width: 1

                    function toggleMuteState() {
                        controller.draftButtonSoundsMuted = !controller.draftButtonSoundsMuted
                    }

                    RowLayout {
                        id: buttonSoundsRow
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 14
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Label { text: controller.draftButtonSoundsMuted ? trx("Muted", "Muted") : trx("Enabled", "Enabled"); color: theme.text; font.bold: true }
                            Label { text: controller.draftButtonSoundsMuted ? trx("تم كتم أصوات الأزرار وأصوات تنبيه ويندوز الناتجة عن ضغطات الواجهة.", "Button sounds and Windows click feedback are muted.") : trx("أصوات الأزرار مفعّلة حاليًا لكل الضغطات داخل الواجهة.", "Button sounds are currently active for interface clicks."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                        StartupSwitch {
                            checked: controller.draftButtonSoundsMuted
                            onToggled: function(nextChecked) { controller.draftButtonSoundsMuted = nextChecked }
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: parent.toggleMuteState()
                    }
                }
            }
        }
    }
}
