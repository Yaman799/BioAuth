import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"
import "../settings"
import "../../theme/Ui.js" as Ui

GridLayout {
    id: securitySettingsSection
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
    visible: settingsRoot.activeSection === "security"
    enabled: visible
    Layout.preferredHeight: visible ? implicitHeight : 0
    Layout.minimumHeight: visible ? implicitHeight : 0
    Layout.maximumHeight: visible ? 1000000 : 0

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: securityContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: securityContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AssetIcon {
                    sourceUrl: settingsRoot.securityIcon
                    tone: settingsRoot.draftAppPasscodeEnabled ? "success" : "info"
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 44
                    iconPadding: 7
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("حماية رمز الدخول", "App passcode protection")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("فعّل أو أوقف رمز دخول التطبيق من هنا. التحقق والحفظ يبقيان داخل النظام.", "Enable or turn off the app passcode here. Verification and saving remain system-managed.")
                        color: theme.muted
                        font.pixelSize: 13
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.infoIcon
                tone: settingsRoot.securityFeedbackCurrentTone()
                title: settingsRoot.label("حالة تعديل الأمان", "Security edit state")
                detail: settingsRoot.securityFeedbackText.length > 0 ? settingsRoot.securityFeedbackText : settingsRoot.securityFeedbackFallback()
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: appPasscodeToggleRow.implicitHeight + 24
                radius: 18
                color: Ui.colorToken(theme, "surface1")
                border.color: settingsRoot.draftAppPasscodeEnabled ? Ui.roleColor(theme, "success") : Ui.colorToken(theme, "border")
                border.width: 1

                RowLayout {
                    id: appPasscodeToggleRow
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    StartupSwitch {
                        theme: settingsRoot.calmToggleTheme
                        checked: settingsRoot.draftAppPasscodeEnabled
                        enabled: !settingsRoot.securityApplyInFlight && !settingsRoot.generalApplyInFlight
                        onToggled: function(nextChecked) {
                            settingsRoot.setDraftAppPasscodeEnabled(nextChecked)
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Label {
                            Layout.fillWidth: true
                            text: settingsRoot.label("حماية رمز دخول التطبيق", "App passcode guard")
                            color: theme.text
                            font.bold: true
                            horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                            wrapMode: Text.Wrap
                        }

                        Label {
                            Layout.fillWidth: true
                            text: settingsRoot.draftAppPasscodeEnabled ? settingsRoot.label("سيبقى القفل المحلي مفعلاً بعد الحفظ إذا أكد النظام ذلك.", "The local guard stays enabled after saving if BioAuth confirms it.") : settingsRoot.label("إيقاف الحماية يتطلب رمز الدخول الحالي عندما تكون مفعّلة.", "Turning protection off requires the current passcode when it is enabled.")
                            color: theme.muted
                            horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                            wrapMode: Text.Wrap
                        }
                    }

                    InfoPill {
                        textValue: settingsRoot.draftAppPasscodeEnabled ? backend.tr("enabled") : backend.tr("disabled")
                        pillTone: settingsRoot.draftAppPasscodeEnabled ? "success" : "neutral"
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    Layout.fillWidth: true
                    text: settingsRoot.label("مهلة رمز الدخول", "Passcode timeout")
                    color: theme.text
                    font.bold: true
                    horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                    wrapMode: Text.Wrap
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: settingsRoot.compactLayout ? 1 : 2
                    columnSpacing: 10
                    rowSpacing: 10

                    ChoiceChip {
                        titleText: settingsRoot.timeoutLabel(60)
                        descriptionText: settingsRoot.label("قفل سريع بعد دقيقة.", "Quick lock after one minute.")
                        selected: settingsRoot.draftAppPasscodeTimeoutSec === 60
                        accentColor: Ui.roleColor(theme, "success")
                        onChosen: settingsRoot.chooseDraftAppPasscodeTimeout(60)
                    }

                    ChoiceChip {
                        titleText: settingsRoot.timeoutLabel(300)
                        descriptionText: settingsRoot.label("توازن مناسب للاستخدام اليومي.", "Balanced for daily use.")
                        selected: settingsRoot.draftAppPasscodeTimeoutSec === 300
                        accentColor: Ui.roleColor(theme, "success")
                        onChosen: settingsRoot.chooseDraftAppPasscodeTimeout(300)
                    }

                    ChoiceChip {
                        titleText: settingsRoot.timeoutLabel(900)
                        descriptionText: settingsRoot.label("مهلة أطول للجلسات الهادئة.", "Longer timeout for calm sessions.")
                        selected: settingsRoot.draftAppPasscodeTimeoutSec === 900
                        accentColor: Ui.roleColor(theme, "success")
                        onChosen: settingsRoot.chooseDraftAppPasscodeTimeout(900)
                    }

                    ChoiceChip {
                        titleText: settingsRoot.timeoutLabel(1800)
                        descriptionText: settingsRoot.label("أطول خيار مبسط متاح.", "Longest simplified option available.")
                        selected: settingsRoot.draftAppPasscodeTimeoutSec === 1800
                        accentColor: Ui.roleColor(theme, "success")
                        onChosen: settingsRoot.chooseDraftAppPasscodeTimeout(1800)
                    }
                }
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: passcodeUpdateContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: passcodeUpdateContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AssetIcon {
                    sourceUrl: settingsRoot.storageIcon
                    tone: "info"
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 44
                    iconPadding: 7
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("تحديث رمز الدخول", "Update passcode")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("لا يتم تسجيل أو عرض رمز الدخول. الحقول تُمسح بعد الإرسال أو الإلغاء.", "The passcode is not logged or displayed. Fields are cleared after submit or discard.")
                        color: theme.muted
                        font.pixelSize: 13
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                text: settingsRoot.label("رمز الدخول الحالي", "Current passcode")
                color: theme.text
                font.bold: true
                horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                wrapMode: Text.Wrap
            }

            AppTextField {
                id: userSettingsCurrentPasscodeField
                Layout.fillWidth: true
                placeholderText: backend.appPasscodeConfigured ? settingsRoot.label("مطلوب عند التغيير أو الإيقاف", "Required to change or disable") : settingsRoot.label("غير مطلوب لأول إعداد", "Not required for first setup")
                echoMode: TextInput.Password
                maximumLength: 8
                inputMethodHints: Qt.ImhDigitsOnly | Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                Component.onCompleted: settingsRoot.currentPasscodeField = userSettingsCurrentPasscodeField
                Component.onDestruction: if (settingsRoot.currentPasscodeField === userSettingsCurrentPasscodeField) settingsRoot.currentPasscodeField = null
            }

            Label {
                Layout.fillWidth: true
                text: settingsRoot.label("رمز الدخول الجديد", "New passcode")
                color: theme.text
                font.bold: true
                horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                wrapMode: Text.Wrap
            }

            AppTextField {
                id: userSettingsNewPasscodeField
                Layout.fillWidth: true
                placeholderText: settingsRoot.label("4 إلى 8 أرقام", "4 to 8 digits")
                echoMode: TextInput.Password
                maximumLength: 8
                inputMethodHints: Qt.ImhDigitsOnly | Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                Component.onCompleted: settingsRoot.newPasscodeField = userSettingsNewPasscodeField
                Component.onDestruction: if (settingsRoot.newPasscodeField === userSettingsNewPasscodeField) settingsRoot.newPasscodeField = null
            }

            Label {
                Layout.fillWidth: true
                text: settingsRoot.label("تأكيد رمز الدخول", "Confirm passcode")
                color: theme.text
                font.bold: true
                horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                wrapMode: Text.Wrap
            }

            AppTextField {
                id: userSettingsConfirmPasscodeField
                Layout.fillWidth: true
                placeholderText: settingsRoot.label("أعد إدخال الرمز الجديد", "Re-enter the new code")
                echoMode: TextInput.Password
                maximumLength: 8
                inputMethodHints: Qt.ImhDigitsOnly | Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                Component.onCompleted: settingsRoot.confirmPasscodeField = userSettingsConfirmPasscodeField
                Component.onDestruction: if (settingsRoot.confirmPasscodeField === userSettingsConfirmPasscodeField) settingsRoot.confirmPasscodeField = null
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AppButton {
                    text: settingsRoot.securityApplyInFlight ? settingsRoot.label("جاري الحفظ…", "Saving…") : settingsRoot.label("حفظ إعدادات الأمان", "Save security")
                    role: "success"
                    enabled: settingsRoot.hasSecurityDraftChanges && !settingsRoot.securityApplyInFlight && !settingsRoot.settingsActionInFlight
                    onClicked: settingsRoot.applySecuritySettings()
                }

                AppButton {
                    text: settingsRoot.label("إلغاء", "Discard")
                    role: "neutral"
                    enabled: settingsRoot.hasSecurityDraftChanges && !settingsRoot.securityApplyInFlight
                    onClicked: settingsRoot.resetSecurityDrafts()
                }
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: accountPasswordContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: accountPasswordContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AssetIcon {
                    sourceUrl: settingsRoot.securityIcon
                    tone: "info"
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 44
                    iconPadding: 7
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("كلمة مرور الحساب", "Account password")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("غيّر كلمة مرور الحساب المحلي بدون فتح العرض المتقدم. التحقق وسياسة كلمة المرور تبقى داخل النظام.", "Change the local account password without opening the advanced view. Verification and password policy remain system-managed.")
                        color: theme.muted
                        font.pixelSize: 13
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.infoIcon
                tone: settingsRoot.accountSecurityFeedbackCurrentTone()
                title: settingsRoot.label("حالة أمان الحساب", "Account security state")
                detail: settingsRoot.accountSecurityFeedbackText.length > 0 ? settingsRoot.accountSecurityFeedbackText : settingsRoot.accountSecurityFeedbackFallback()
            }

            AppTextField {
                id: userSettingsCurrentAccountPasswordField
                Layout.fillWidth: true
                placeholderText: settingsRoot.label("كلمة المرور الحالية", "Current password")
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                enabled: backend.authenticated === true && !settingsRoot.accountSecurityActionInFlight
                Component.onCompleted: settingsRoot.currentAccountPasswordField = userSettingsCurrentAccountPasswordField
                Component.onDestruction: if (settingsRoot.currentAccountPasswordField === userSettingsCurrentAccountPasswordField) settingsRoot.currentAccountPasswordField = null
            }

            AppTextField {
                id: userSettingsNewAccountPasswordField
                Layout.fillWidth: true
                placeholderText: settingsRoot.label("كلمة مرور جديدة: 10 أحرف على الأقل مع حرف ورقم", "New password: at least 10 characters with a letter and number")
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                enabled: backend.authenticated === true && !settingsRoot.accountSecurityActionInFlight
                Component.onCompleted: settingsRoot.newAccountPasswordField = userSettingsNewAccountPasswordField
                Component.onDestruction: if (settingsRoot.newAccountPasswordField === userSettingsNewAccountPasswordField) settingsRoot.newAccountPasswordField = null
            }

            AppTextField {
                id: userSettingsConfirmAccountPasswordField
                Layout.fillWidth: true
                placeholderText: settingsRoot.label("تأكيد كلمة المرور الجديدة", "Confirm new password")
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                enabled: backend.authenticated === true && !settingsRoot.accountSecurityActionInFlight
                onAccepted: settingsRoot.updateAccountPassword()
                Component.onCompleted: settingsRoot.confirmAccountPasswordField = userSettingsConfirmAccountPasswordField
                Component.onDestruction: if (settingsRoot.confirmAccountPasswordField === userSettingsConfirmAccountPasswordField) settingsRoot.confirmAccountPasswordField = null
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AppButton {
                    text: settingsRoot.accountSecurityActionInFlight ? settingsRoot.label("جاري الإرسال…", "Sending…") : settingsRoot.label("تحديث كلمة المرور", "Update password")
                    role: "details"
                    enabled: backend.authenticated === true
                             && !settingsRoot.accountSecurityActionInFlight
                             && !settingsRoot.settingsActionInFlight
                             && userSettingsCurrentAccountPasswordField.text.length > 0
                             && userSettingsNewAccountPasswordField.text.length > 0
                             && userSettingsConfirmAccountPasswordField.text.length > 0
                    onClicked: settingsRoot.updateAccountPassword()
                }

                AppButton {
                    text: settingsRoot.label("مسح الحقول", "Clear fields")
                    role: "neutral"
                    enabled: !settingsRoot.accountSecurityActionInFlight
                             && (userSettingsCurrentAccountPasswordField.text.length > 0
                                 || userSettingsNewAccountPasswordField.text.length > 0
                                 || userSettingsConfirmAccountPasswordField.text.length > 0)
                    onClicked: {
                        settingsRoot.clearAccountPasswordDrafts()
                        settingsRoot.accountSecurityFeedbackText = ""
                        settingsRoot.accountSecurityFeedbackTone = "neutral"
                    }
                }
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: recoveryCodeContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: recoveryCodeContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AssetIcon {
                    sourceUrl: settingsRoot.storageIcon
                    tone: backend.currentUser && backend.currentUser.password_recovery_ready === true ? "success" : "warn"
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 44
                    iconPadding: 7
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("كود استرداد كلمة المرور", "Password recovery code")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("أنشئ كود استرداد محلي لهذا الحساب. سيعرض BioAuth الكود مرة واحدة فقط داخل رسالة محلية.", "Create a local recovery code for this account. BioAuth shows the code once in a local dialog only.")
                        color: theme.muted
                        font.pixelSize: 13
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.storageIcon
                tone: backend.currentUser && backend.currentUser.password_recovery_ready === true ? "success" : "warn"
                title: settingsRoot.label("حالة كود الاسترداد", "Recovery code state")
                detail: settingsRoot.recoveryStatusLabel()
                trailingText: settingsRoot.label("محلي فقط", "Local only")
            }

            AppTextField {
                id: userSettingsRecoveryPasswordField
                Layout.fillWidth: true
                placeholderText: settingsRoot.label("كلمة المرور الحالية مطلوبة لإنشاء الكود", "Current password required to create the code")
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                enabled: backend.authenticated === true && !settingsRoot.accountSecurityActionInFlight
                onAccepted: settingsRoot.regenerateAccountRecoveryCode()
                Component.onCompleted: settingsRoot.recoveryPasswordField = userSettingsRecoveryPasswordField
                Component.onDestruction: if (settingsRoot.recoveryPasswordField === userSettingsRecoveryPasswordField) settingsRoot.recoveryPasswordField = null
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AppButton {
                    text: backend.currentUser && backend.currentUser.password_recovery_ready === true ? settingsRoot.label("إعادة إنشاء الكود", "Regenerate code") : settingsRoot.label("إنشاء كود استرداد", "Generate recovery code")
                    role: "details"
                    enabled: backend.authenticated === true
                             && !settingsRoot.accountSecurityActionInFlight
                             && !settingsRoot.settingsActionInFlight
                             && userSettingsRecoveryPasswordField.text.length > 0
                    onClicked: settingsRoot.regenerateAccountRecoveryCode()
                }

                AppButton {
                    text: settingsRoot.label("مسح", "Clear")
                    role: "neutral"
                    enabled: !settingsRoot.accountSecurityActionInFlight && userSettingsRecoveryPasswordField.text.length > 0
                    onClicked: {
                        settingsRoot.clearRecoveryPasswordDraft()
                        settingsRoot.accountSecurityFeedbackText = ""
                        settingsRoot.accountSecurityFeedbackTone = "neutral"
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                text: settingsRoot.label("احفظ الكود خارج التطبيق. لا تشاركه، ولا يظهر مرة ثانية بعد إغلاق رسالة النظام.", "Store the code outside the app. Do not share it, and it will not appear again after the system dialog is closed.")
                color: theme.muted
                font.pixelSize: 12
                horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                wrapMode: Text.Wrap
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: confirmedSecurityContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: confirmedSecurityContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.infoIcon; tone: "info"; Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; text: settingsRoot.label("الحالة المؤكدة من النظام", "System-confirmed state"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label { Layout.fillWidth: true; text: settingsRoot.label("هذا الملخص لا يعرض الرمز نفسه، فقط حالة النظام.", "This summary never shows the passcode itself, only system state."); color: theme.muted; font.pixelSize: 13; wrapMode: Text.Wrap }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.securityIcon
                tone: backend.appPasscodeEnabled ? "success" : "neutral"
                title: settingsRoot.label("الحماية مفعّلة", "Protection enabled")
                detail: settingsRoot.yesNo(backend.appPasscodeEnabled)
                trailingText: settingsRoot.label("مسودة", "Draft") + ": " + settingsRoot.yesNo(settingsRoot.draftAppPasscodeEnabled)
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.storageIcon
                tone: backend.appPasscodeConfigured ? "success" : "warn"
                title: settingsRoot.label("حالة الإعداد", "Setup state")
                detail: settingsRoot.passcodeConfiguredLabel()
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.retentionIcon
                tone: backend.appPasscodeTimeoutSec === settingsRoot.draftAppPasscodeTimeoutSec ? "success" : "warn"
                title: settingsRoot.label("المهلة المؤكدة", "Confirmed timeout")
                detail: settingsRoot.timeoutLabel(backend.appPasscodeTimeoutSec)
                trailingText: settingsRoot.label("مسودة", "Draft") + ": " + settingsRoot.timeoutLabel(settingsRoot.draftAppPasscodeTimeoutSec)
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: securityBoundaryContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: securityBoundaryContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.warningIcon; tone: "warn"; Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; text: settingsRoot.label("حدود الأمان", "Security boundary"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label { Layout.fillWidth: true; text: settingsRoot.label("قرارات القفل، التحقق، وحفظ رمز الدخول تبقى داخل النظام. الواجهة تعرض الحالة وتمنع الضغط المكرر فقط.", "Lock, verification, and passcode saving decisions stay with BioAuth. The UI displays state and only guards duplicate input."); color: theme.muted; font.pixelSize: 13; wrapMode: Text.Wrap }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.securityIcon
                tone: "info"
                title: settingsRoot.label("حساسية المخاطر", "Risk sensitivity")
                detail: settingsRoot.safeString(backend.riskSensitivityPreset, settingsRoot.label("حسب إعدادات النظام", "System configured"))
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.infoIcon
                tone: "neutral"
                title: settingsRoot.label("أدوات متقدمة", "Advanced tools")
                detail: settingsRoot.label("تقارير السلامة وأدوات الاسترجاع المتقدمة غير ظاهرة هنا.", "Advanced safety reports and rollback tools are not shown here.")
            }
        }
    }
}
