import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"
import "../settings"
import "../../theme/Ui.js" as Ui

GridLayout {
    id: faceSettingsSection
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
    visible: settingsRoot.activeSection === "face"
    enabled: visible
    Layout.preferredHeight: visible ? implicitHeight : 0
    Layout.minimumHeight: visible ? implicitHeight : 0
    Layout.maximumHeight: visible ? 1000000 : 0

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: faceContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: faceContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.faceIcon; tone: "success"; Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; text: backend.tr("user_settings_face_title"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label { Layout.fillWidth: true; text: backend.tr("user_settings_face_body"); color: theme.muted; font.pixelSize: 13; wrapMode: Text.Wrap }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                InfoPill {
                    textValue: settingsRoot.userSafeText(faceState.statusText, backend.tr("face_status_not_enrolled"))
                    pillTone: faceState.enrolled ? "success" : ((faceState.statusText || "").toString().length > 0 ? "warn" : "neutral")
                }
                AppButton {
                    text: backend.tr("user_settings_open_face")
                    role: "details"
                    enabled: rootWindow !== undefined
                    onClicked: { if (rootWindow !== undefined) rootWindow.navSelection = 3 }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: faceAdvancedSettingsPrompt.implicitHeight + 24
                radius: 18
                color: Ui.colorToken(theme, "surface1")
                border.color: settingsRoot.showFaceAdvancedSettings ? Ui.roleColor(theme, "warn") : Ui.colorToken(theme, "border")
                border.width: 1

                RowLayout {
                    id: faceAdvancedSettingsPrompt
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    AssetIcon {
                        sourceUrl: settingsRoot.warningIcon
                        tone: settingsRoot.showFaceAdvancedSettings ? "warn" : "neutral"
                        Layout.preferredWidth: 38
                        Layout.preferredHeight: 38
                        iconPadding: 7
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Label {
                            Layout.fillWidth: true
                            text: settingsRoot.label("خيارات الوجه المتقدمة", "Advanced face options")
                            color: theme.text
                            font.bold: true
                            wrapMode: Text.Wrap
                            horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        }

                        Label {
                            Layout.fillWidth: true
                            text: settingsRoot.label("إعداد وتشغيل الوجه اليومي يتم من صفحة الوجه. هذه المفاتيح مخصصة للحالات المتقدمة فقط.", "Daily face setup and use stays on the Face page. These switches are reserved for advanced cases only.")
                            color: theme.muted
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                            horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        }
                    }

                    AppButton {
                        text: settingsRoot.showFaceAdvancedSettings ? settingsRoot.label("إخفاء", "Hide") : settingsRoot.label("عرض", "Show")
                        role: settingsRoot.showFaceAdvancedSettings ? "warn" : "neutral"
                        compact: true
                        enabled: !settingsRoot.settingsActionInFlight && !settingsRoot.faceOperationInFlight
                        onClicked: settingsRoot.showFaceAdvancedSettings = !settingsRoot.showFaceAdvancedSettings
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                visible: settingsRoot.showFaceAdvancedSettings
                enabled: visible
                Layout.preferredHeight: visible ? implicitHeight : 0
                Layout.minimumHeight: visible ? implicitHeight : 0
                Layout.maximumHeight: visible ? 1000000 : 0
                implicitHeight: userSettingsFaceEnrollmentRow.implicitHeight + 24
                radius: 18
                color: Ui.colorToken(theme, "surface1")
                border.color: Ui.colorToken(theme, "border")
                border.width: 1

                RowLayout {
                    id: userSettingsFaceEnrollmentRow
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    StartupSwitch {
                        theme: settingsRoot.calmToggleTheme
                        objectName: "userSettingsFaceEnrollmentFeatureToggle"
                        checked: settingsRoot.faceEnrollmentFeatureEnabled
                        enabled: !settingsRoot.settingsActionInFlight && !settingsRoot.faceOperationInFlight
                        onToggled: function(nextChecked) { settingsRoot.guardedToggleFaceEnrollmentFeature(nextChecked) }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Label { text: settingsRoot.label("إعداد الوجه", "Face setup"); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: settingsRoot.faceEnrollmentFeatureEnabled ? settingsRoot.label("إعداد الوجه متاح.", "Face setup is available.") : settingsRoot.label("إعداد الوجه متوقف.", "Face setup is off."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                visible: settingsRoot.showFaceAdvancedSettings
                enabled: visible
                Layout.preferredHeight: visible ? implicitHeight : 0
                Layout.minimumHeight: visible ? implicitHeight : 0
                Layout.maximumHeight: visible ? 1000000 : 0
                implicitHeight: userSettingsFaceConfirmationRow.implicitHeight + 24
                radius: 18
                color: Ui.colorToken(theme, "surface1")
                border.color: Ui.colorToken(theme, "border")
                border.width: 1

                RowLayout {
                    id: userSettingsFaceConfirmationRow
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    StartupSwitch {
                        theme: settingsRoot.calmToggleTheme
                        objectName: "userSettingsFaceConfirmationFeatureToggle"
                        checked: settingsRoot.faceConfirmationFeatureEnabled
                        enabled: !settingsRoot.settingsActionInFlight && !settingsRoot.faceOperationInFlight
                        onToggled: function(nextChecked) { settingsRoot.guardedToggleFaceConfirmationFeature(nextChecked) }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Label { text: settingsRoot.label("تأكيد الوجه", "Face confirmation"); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: settingsRoot.faceConfirmationFeatureEnabled ? settingsRoot.label("يمكن طلب تأكيد الوجه عند الحاجة.", "Face confirmation can be requested when needed.") : settingsRoot.label("تأكيد الوجه متوقف.", "Face confirmation is off."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: faceBoundaryContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: faceBoundaryContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.consentIcon; tone: "info"; Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; text: settingsRoot.label("الموافقة والحالة", "Consent & state"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label { Layout.fillWidth: true; text: settingsRoot.label("أي تحقق أو تسجيل للوجه يبقى مملوكاً للنظام.", "Any face verification or enrollment remains system-managed."); color: theme.muted; font.pixelSize: 13; wrapMode: Text.Wrap }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.consentIcon
                tone: learningState.consentSatisfied ? "success" : "warn"
                title: settingsRoot.label("الموافقة", "Consent")
                detail: learningState.consentSatisfied ? settingsRoot.label("الموافقة مسجلة حسب حالة النظام.", "Consent is recorded according to system state.") : settingsRoot.label("قد تكون الموافقة مطلوبة قبل بعض الميزات.", "Consent may be required before some features.")
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.faceIcon
                tone: faceState.enrolled ? "success" : "neutral"
                title: settingsRoot.label("حالة التسجيل", "Enrollment state")
                detail: faceState.enrolled ? settingsRoot.label("التسجيل مؤكد حسب النظام.", "Enrollment is confirmed by the system.") : settingsRoot.label("لا يتم افتراض التسجيل من الواجهة.", "Enrollment is not assumed by the UI.")
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AppButton {
                    text: settingsRoot.label("فتح صفحة الوجه", "Open face page")
                    role: "details"
                    enabled: settingsRoot.rootWindow && settingsRoot.rootWindow.navSelection !== undefined
                    onClicked: settingsRoot.openFaceSettingsPage()
                }

                Label {
                    Layout.fillWidth: true
                    text: settingsRoot.label("التسجيل أو اختبار التأكيد يتم من صفحة الوجه حتى تبقى خطوات الموافقة والكاميرا واضحة.", "Enrollment or confirmation testing stays on the face page so consent and camera steps remain clear.")
                    color: theme.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}
