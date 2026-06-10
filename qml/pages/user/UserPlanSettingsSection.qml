import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"
import "../settings"
import "../../theme/Ui.js" as Ui

GridLayout {
    id: planSettingsSection
    property var settingsRoot
    property var theme: settingsRoot ? settingsRoot.theme : backend.theme
    readonly property var faceState: settingsRoot ? settingsRoot.faceState : ({})
    readonly property var privacyState: settingsRoot ? settingsRoot.privacyState : ({})
    readonly property var learningState: settingsRoot ? settingsRoot.learningState : ({})
    readonly property var benchmarkState: settingsRoot ? settingsRoot.benchmarkState : ({})
    readonly property var updateState: settingsRoot ? settingsRoot.updateState : ({})
    readonly property var licenseState: settingsRoot ? settingsRoot.licenseState : ({})
    Layout.fillWidth: true
    columns: settingsRoot.compactLayout ? 1 : 2
    columnSpacing: 18
    rowSpacing: 18
    visible: settingsRoot.activeSection === "plan"
    enabled: visible
    Layout.preferredHeight: visible ? implicitHeight : 0
    Layout.minimumHeight: visible ? implicitHeight : 0
    Layout.maximumHeight: visible ? 1000000 : 0

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: planContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: planContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.storageIcon; tone: settingsRoot.licenseStateTone(); Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Label { Layout.fillWidth: true; text: settingsRoot.label("الترخيص والخطة", "License & plan"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("التفعيل والاستيراد يستخدمان مسار النظام الموجود. لا يتم حفظ رمز الترخيص داخل هذه الشاشة.", "Activation and import use the existing system flow. The license code is not stored on this screen.")
                        color: theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                    }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.storageIcon
                tone: settingsRoot.licenseStateTone()
                title: settingsRoot.label("حالة الترخيص", "License status")
                detail: settingsRoot.licenseStateSummary()
                trailingText: settingsRoot.safeString(settingsRoot.licenseState.effective_tier || settingsRoot.licenseState.tier, settingsRoot.label("خطة أساسية", "Basic"))
            }

            Label {
                Layout.fillWidth: true
                visible: settingsRoot.licenseFeedbackText.length > 0
                text: settingsRoot.licenseFeedbackText
                color: Ui.roleColor(theme, settingsRoot.licenseFeedbackTone)
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    Layout.fillWidth: true
                    text: settingsRoot.label("رمز الترخيص", "License code")
                    color: theme.text
                    font.bold: true
                    wrapMode: Text.Wrap
                }

                AppTextField {
                    id: licenseCodeInput
                    Layout.fillWidth: true
                    placeholderText: settingsRoot.label("أدخل رمز الترخيص", "Enter license code")
                    echoMode: TextInput.Password
                    inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                    enabled: !settingsRoot.licenseActionInFlight && !settingsRoot.settingsActionInFlight
                    Component.onCompleted: settingsRoot.licenseCodeField = licenseCodeInput
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    AppButton {
                        text: settingsRoot.licenseActionInFlight ? settingsRoot.label("جاري التفعيل…", "Activating…") : settingsRoot.label("تفعيل الترخيص", "Activate license")
                        role: "success"
                        enabled: !settingsRoot.licenseActionInFlight && !settingsRoot.settingsActionInFlight
                        onClicked: settingsRoot.activateUserLicense()
                    }

                    AppButton {
                        text: settingsRoot.label("تحديث الحالة", "Refresh status")
                        role: "details"
                        enabled: !settingsRoot.licenseActionInFlight && !settingsRoot.settingsActionInFlight
                        onClicked: settingsRoot.refreshUserLicenseStatus()
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    Layout.fillWidth: true
                    text: settingsRoot.label("استيراد ملف ترخيص", "Import license file")
                    color: theme.text
                    font.bold: true
                    wrapMode: Text.Wrap
                }

                AppTextField {
                    id: licensePathInput
                    Layout.fillWidth: true
                    placeholderText: settingsRoot.label("مسار ملف الترخيص المحلي", "Local license file path")
                    inputMethodHints: Qt.ImhNoPredictiveText
                    enabled: !settingsRoot.licenseActionInFlight && !settingsRoot.settingsActionInFlight
                    Component.onCompleted: settingsRoot.licensePathField = licensePathInput
                }

                AppButton {
                    text: settingsRoot.licenseActionInFlight ? settingsRoot.label("جاري الاستيراد…", "Importing…") : settingsRoot.label("استيراد الترخيص", "Import license")
                    role: "details"
                    enabled: !settingsRoot.licenseActionInFlight && !settingsRoot.settingsActionInFlight
                    onClicked: settingsRoot.importUserLicenseFile()
                }
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: updateContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: updateContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.updateIcon; tone: settingsRoot.updateStateTone(); Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Label { Layout.fillWidth: true; text: settingsRoot.label("التحديثات", "Updates"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("الفحص والتنزيل والتثبيت تتطلب نقرات واضحة. التثبيت لا يظهر إلا بعد تحقق النظام من ملف التحديث.", "Check, download, and install require explicit clicks. Install is shown only after the system verifies the update file.")
                        color: theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                    }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.updateIcon
                tone: settingsRoot.updateStateTone()
                title: settingsRoot.label("حالة التحديث", "Update status")
                detail: settingsRoot.updateStateSummary()
                trailingText: settingsRoot.safeString(settingsRoot.updateState.latestVersion, settingsRoot.label("لا يوجد إصدار جديد", "No new version"))
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.infoIcon
                tone: "neutral"
                title: settingsRoot.label("الإصدار الحالي", "Current version")
                detail: settingsRoot.safeString(backend.appVersion || settingsRoot.updateState.currentVersion, settingsRoot.label("غير متوفر", "Unavailable"))
                trailingText: settingsRoot.safeString(settingsRoot.updateState.channel, "")
            }

            Label {
                Layout.fillWidth: true
                visible: settingsRoot.updateFeedbackText.length > 0
                text: settingsRoot.updateFeedbackText
                color: Ui.roleColor(theme, settingsRoot.updateFeedbackTone)
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }

            Label {
                Layout.fillWidth: true
                visible: settingsRoot.updateState.releaseNotes && settingsRoot.updateState.releaseNotes.length > 0
                text: settingsRoot.label("ملاحظات الإصدار", "Release notes") + ": " + settingsRoot.updateState.releaseNotes
                color: theme.muted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AppButton {
                    text: settingsRoot.updateOperationActive() ? settingsRoot.label("جاري الفحص…", "Working…") : settingsRoot.label("التحقق من التحديثات", "Check for updates")
                    role: "details"
                    enabled: !settingsRoot.settingsActionInFlight && !settingsRoot.updateOperationActive() && settingsRoot.updateState.canCheck !== false
                    onClicked: settingsRoot.guardedCheckForUpdates()
                }

                AppButton {
                    text: settingsRoot.label("تنزيل التحديث", "Download update")
                    role: "warn"
                    visible: settingsRoot.updateState.canDownload === true
                    enabled: !settingsRoot.settingsActionInFlight && !settingsRoot.updateOperationActive() && settingsRoot.updateState.canDownload === true
                    onClicked: settingsRoot.guardedDownloadUpdate()
                }

                AppButton {
                    text: settingsRoot.label("فتح المثبت المعتمد", "Open verified installer")
                    role: "warn"
                    visible: settingsRoot.updateState.canInstall === true
                    enabled: !settingsRoot.settingsActionInFlight && !settingsRoot.updateOperationActive() && settingsRoot.updateState.canInstall === true
                    onClicked: settingsRoot.guardedInstallUpdate()
                }
            }

            Label {
                Layout.fillWidth: true
                text: settingsRoot.label("لا توجد تحديثات صامتة: كل خطوة تحتاج موافقة واضحة.", "No silent updates: every step requires clear approval.")
                color: theme.muted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        Layout.columnSpan: settingsRoot.compactLayout ? 1 : 2
        implicitHeight: accessContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: accessContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.settingsIcon; tone: "details"; Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; text: backend.tr("user_settings_interface_title"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label { Layout.fillWidth: true; text: backend.tr("user_settings_interface_body"); color: theme.muted; font.pixelSize: 13; wrapMode: Text.Wrap }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.settingsIcon
                tone: backend.interfaceMode === "developer" ? "warn" : "success"
                title: settingsRoot.label("الوضع الحالي", "Current mode")
                detail: settingsRoot.label(backend.uiMode === "user" ? "الواجهة الأساسية" : "العرض المتقدم", backend.uiMode === "user" ? "Essential view" : "Advanced view")
            }

            AppButton {
                text: settingsRoot.label("فتح العرض المتقدم", "Open advanced view")
                role: "details"
                enabled: backend.interfaceMode !== "developer" && !settingsRoot.settingsActionInFlight
                onClicked: {
                    if (settingsRoot.settingsActionInFlight)
                        return
                    settingsRoot.settingsActionInFlight = true
                    settingsGuardTimer.restart()
                    backend.setInterfaceMode("developer")
                }
            }
        }
    }
}
