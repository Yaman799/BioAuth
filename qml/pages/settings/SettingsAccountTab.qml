import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

Item {
    property var controller
    property var theme
    property var rootWindow
    property bool localDataOperationBusy: backend.trainingInProgress || backend.canStop || (backend.companionApiState && backend.companionApiState.running)
    function trx(arText, enText) { return controller ? controller.trx(arText, enText) : enText }
    Layout.fillWidth: true
        implicitHeight: accountColumn.implicitHeight

    ColumnLayout {
        id: accountColumn
        width: parent.width
        spacing: 16

        SettingsLicenseCard {
            controller: controller
            theme: theme
            rootWindow: rootWindow
        }

        GridLayout {
            id: accountGrid
            width: parent.width
            columns: width >= 1120 ? 2 : 1
            columnSpacing: 16
            rowSpacing: 16

            GlassCard {
                Layout.fillWidth: true
                implicitHeight: accountIdentityContent.implicitHeight + 40
                ColumnLayout {
                    id: accountIdentityContent
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 12
                    SectionHeader {
                        title: trx("Account identity", "Account identity")
                        subtitle: trx("بيانات الحساب المعروض حاليًا داخل الكونسول.", "The account currently loaded in the console.")
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: accountIdentitySummary.implicitHeight + 28
                        radius: 18
                        color: theme.surface1
                        border.color: theme.border
                        border.width: 1
                        ColumnLayout {
                            id: accountIdentitySummary
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 6
                            Label { text: trx("Display name", "Display name") + ": " + (backend.currentUser.display_name || "—"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: trx("Account ID", "Account ID") + ": " + (backend.currentUser.user_id || "—"); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: trx("Language", "Language") + ": " + backend.language; color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                implicitHeight: workspaceContextContent.implicitHeight + 40
                ColumnLayout {
                    id: workspaceContextContent
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 12
                    SectionHeader {
                        title: trx("Workspace context", "Workspace context")
                        subtitle: trx("ملخص سريع للتفضيلات الحالية وما يرتبط بها من حالة تشغيل.", "A fast summary of current preferences and the running workspace context.")
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        InfoPill { textValue: backend.tr("theme") + ": " + controller.draftTheme; pillTone: "details" }
                        InfoPill { textValue: trx("Startup", "Startup") + ": " + (backend.runOnStartup ? trx("Enabled", "Enabled") : trx("Disabled", "Disabled")); pillTone: backend.runOnStartup ? "success" : "neutral" }
                        InfoPill { textValue: trx("Protection", "Protection") + ": " + (backend.runtimeState.active ? trx("Active", "Active") : trx("Idle", "Idle")); pillTone: backend.runtimeState.active ? "info" : "neutral" }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: trx("العمليات الحساسة أصبحت داخل نفس قسم الحساب بدل بقائها ثابتة في أسفل الواجهة.", "Sensitive operations now live inside the Account section instead of staying fixed at the bottom of the page.")
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                }
            }
        }



        GlassCard {
            Layout.fillWidth: true
            implicitHeight: passwordRecoveryContent.implicitHeight + 40

            ColumnLayout {
                id: passwordRecoveryContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                SectionHeader {
                    title: trx("Password recovery", "Password recovery")
                    subtitle: trx("أنشئ كود استرداد محليًا لهذا الحساب حتى تتمكن من إعادة تعيين كلمة المرور لاحقًا بدون خادم خارجي.", "Create a local recovery code for this account so you can reset the password later without an external server.")
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: passwordRecoverySummary.implicitHeight + 28
                    radius: 18
                    color: theme.surface1
                    border.color: theme.border
                    border.width: 1

                    ColumnLayout {
                        id: passwordRecoverySummary
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 8

                        Label {
                            Layout.fillWidth: true
                            text: backend.currentUser.password_recovery_ready ? backend.tr("password_recovery_status_ready") : backend.tr("password_recovery_status_missing")
                            color: theme.text
                            font.bold: true
                            wrapMode: Text.Wrap
                        }

                        Label {
                            Layout.fillWidth: true
                            text: backend.tr("password_recovery_help")
                            color: theme.muted
                            wrapMode: Text.Wrap
                        }

                        AppTextField {
                            id: recoveryCurrentPassword
                            Layout.topMargin: 6
                            Layout.fillWidth: true
                            placeholderText: backend.tr("password_recovery_current_password")
                            echoMode: TextInput.Password
                            enabled: backend.authenticated
                            onAccepted: backend.regeneratePasswordRecoveryCode(text)
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            AppButton {
                                text: backend.currentUser.password_recovery_ready ? backend.tr("password_recovery_regenerate") : backend.tr("password_recovery_generate")
                                role: "details"
                                compact: true
                                enabled: backend.authenticated && recoveryCurrentPassword.text.length > 0
                                onClicked: {
                                    backend.regeneratePasswordRecoveryCode(recoveryCurrentPassword.text)
                                    recoveryCurrentPassword.text = ""
                                }
                            }

                            Label {
                                Layout.fillWidth: true
                                text: trx("سيعرض BioAuth الكود مرة واحدة فقط داخل رسالة محلية. احتفظ به خارج التطبيق.", "BioAuth shows the code once in a local dialog. Store it outside the app.")
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
            implicitHeight: backupRestoreContent.implicitHeight + 40

            ColumnLayout {
                id: backupRestoreContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                SectionHeader {
                    title: trx("Encrypted backup & local data", "Encrypted backup & local data")
                    subtitle: trx("الأوامر الحساسة تُنفّذ في الخلفية فقط؛ الواجهة تمرر المسار والتأكيد ولا تنفذ منطق الحماية.", "Sensitive commands run in the backend only; the UI passes paths/confirmation and does not implement protection logic.")
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 1120 ? 2 : 1
                    columnSpacing: 16
                    rowSpacing: 16

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: exportBackupContent.implicitHeight + 28
                        radius: 18
                        color: theme.surface1
                        border.color: theme.border
                        border.width: 1
                        ColumnLayout {
                            id: exportBackupContent
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8
                            Label { text: trx("Export encrypted backup", "Export encrypted backup"); color: theme.text; font.bold: true }
                            Label {
                                Layout.fillWidth: true
                                text: trx("اكتب مسار ملف النسخة الاحتياطية. الملف الناتج encrypted envelope v2 ومحمّي بالسلامة. أوقف الجلسات أو ربط الهاتف قبل النسخ.", "Enter a backup file path. The output is an encrypted envelope v2 with integrity protection. Stop sessions or phone pairing before backup.")
                                color: theme.muted
                                wrapMode: Text.Wrap
                            }
                            AppTextField {
                                id: backupExportPath
                                Layout.fillWidth: true
                                placeholderText: trx("C:/Users/you/Documents/bioauth-backup.bioauthbackup", "C:/Users/you/Documents/bioauth-backup.bioauthbackup")
                                enabled: backend.authenticated && !localDataOperationBusy
                            }
                            AppButton {
                                text: trx("Export backup", "Export backup")
                                role: "details"
                                compact: true
                                enabled: backupExportPath.text.length > 0 && !localDataOperationBusy
                                onClicked: backend.exportEncryptedBackup(backupExportPath.text)
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: importBackupContent.implicitHeight + 28
                        radius: 18
                        color: theme.surface1
                        border.color: theme.border
                        border.width: 1
                        ColumnLayout {
                            id: importBackupContent
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8
                            Label { text: trx("Import encrypted backup", "Import encrypted backup"); color: theme.text; font.bold: true }
                            Label {
                                Layout.fillWidth: true
                                text: trx("الاستيراد يتحقق من النسخة قبل الكتابة. اكتب RESTORE LOCAL BACKUP للتأكيد. يجب إيقاف الجلسات وربط الهاتف أولًا.", "Restore validates the backup before writing. Type RESTORE LOCAL BACKUP to confirm. Stop sessions and phone pairing first.")
                                color: theme.muted
                                wrapMode: Text.Wrap
                            }
                            AppTextField {
                                id: backupImportPath
                                Layout.fillWidth: true
                                placeholderText: trx("Backup file path", "Backup file path")
                                enabled: backend.authenticated && !localDataOperationBusy
                            }
                            AppTextField {
                                id: backupImportConfirmation
                                Layout.fillWidth: true
                                placeholderText: "RESTORE LOCAL BACKUP"
                                enabled: backend.authenticated && !localDataOperationBusy
                            }
                            AppButton {
                                text: trx("Import backup", "Import backup")
                                role: "warn"
                                compact: true
                                enabled: backupImportPath.text.length > 0 && backupImportConfirmation.text.length > 0 && !localDataOperationBusy
                                onClicked: backend.importEncryptedBackup(backupImportPath.text, backupImportConfirmation.text)
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: resetProfileCommandContent.implicitHeight + 28
                        radius: 18
                        color: theme.dangerBg
                        border.color: theme.warn
                        border.width: 1
                        ColumnLayout {
                            id: resetProfileCommandContent
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8
                            Label { text: trx("Reset current profile", "Reset current profile"); color: theme.text; font.bold: true }
                            Label { Layout.fillWidth: true; text: trx("يحذف النموذج السلوكي الحالي فقط ولا يحذف الحساب. اكتب RESET PROFILE للتأكيد.", "Deletes the current behavioral model only, not the account. Type RESET PROFILE to confirm."); color: theme.muted; wrapMode: Text.Wrap }
                            AppTextField { id: resetProfileConfirmation; Layout.fillWidth: true; placeholderText: "RESET PROFILE"; enabled: backend.authenticated && !localDataOperationBusy }
                            AppButton {
                                text: trx("Reset profile", "Reset profile")
                                role: "warn"
                                compact: true
                                enabled: resetProfileConfirmation.text.length > 0 && backend.authenticated && !localDataOperationBusy
                                onClicked: backend.resetCurrentProfileData(resetProfileConfirmation.text)
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: deleteAllLocalContent.implicitHeight + 28
                        radius: 18
                        color: theme.dangerBg
                        border.color: theme.danger
                        border.width: 1
                        ColumnLayout {
                            id: deleteAllLocalContent
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8
                            Label { text: trx("Delete all local BioAuth data", "Delete all local BioAuth data"); color: theme.text; font.bold: true }
                            Label { Layout.fillWidth: true; text: trx("يحذف بيانات BioAuth المحلية على هذا الجهاز. اكتب DELETE LOCAL BIOAUTH DATA للتأكيد.", "Deletes local BioAuth data on this device. Type DELETE LOCAL BIOAUTH DATA to confirm."); color: theme.muted; wrapMode: Text.Wrap }
                            AppTextField { id: deleteAllLocalConfirmation; Layout.fillWidth: true; placeholderText: "DELETE LOCAL BIOAUTH DATA"; enabled: !localDataOperationBusy }
                            AppButton {
                                text: trx("Delete local data", "Delete local data")
                                role: "danger"
                                compact: true
                                enabled: deleteAllLocalConfirmation.text.length > 0 && !localDataOperationBusy
                                onClicked: backend.deleteAllLocalBioAuthData(deleteAllLocalConfirmation.text)
                            }
                        }
                    }
                }
            }
        }

        GlassCard {
            Layout.fillWidth: true
            implicitHeight: dangerContent.implicitHeight + 42

            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 27
                color: Qt.rgba(theme.danger.r, theme.danger.g, theme.danger.b, theme.isDark ? 0.12 : 0.07)
                border.color: theme.danger
                border.width: 1.2
            }

            ColumnLayout {
                id: dangerContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 14

                SectionHeader {
                    title: trx("Danger zone", "Danger zone")
                    subtitle: trx("هذا القسم أصبح جزءًا من تبويب الحساب نفسه حتى تبقى كل عمليات الهوية الحساسة في مكان واحد.", "This area now lives inside the Account tab so all sensitive identity operations stay in one place.")
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 1120 ? 2 : 1
                    columnSpacing: 16
                    rowSpacing: 16

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: resetProfileDangerContent.implicitHeight + 28
                        radius: 18
                        color: theme.dangerBg
                        border.color: theme.danger
                        border.width: 1

                        ColumnLayout {
                            id: resetProfileDangerContent
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8
                            Label { text: backend.tr("reset_profile"); color: theme.text; font.bold: true }
                            Label {
                                text: trx("يعيد بناء الملف السلوكي من الصفر. استخدمه فقط إذا أردت إعادة التهيئة بالكامل.", "Rebuilds the behavioral profile from scratch. Use this only when you want a full re-enrollment.")
                                color: theme.muted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            Item { Layout.fillHeight: true }
                            AppButton {
                                text: backend.tr("reset_profile")
                                role: "danger"
                                compact: true
                                enabled: backend.authenticated && !localDataOperationBusy
                                onClicked: rootWindow.openResetProfileConfirm()
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: deleteAccountDangerContent.implicitHeight + 28
                        radius: 18
                        color: theme.dangerBg
                        border.color: theme.danger
                        border.width: 1

                        ColumnLayout {
                            id: deleteAccountDangerContent
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8
                            Label { text: backend.tr("delete_account"); color: theme.text; font.bold: true }
                            AppTextField {
                                id: deletePw
                                Layout.fillWidth: true
                                placeholderText: backend.tr("password")
                                echoMode: TextInput.Password
                                enabled: backend.authenticated && !localDataOperationBusy
                            }
                            GridLayout {
                                Layout.fillWidth: true
                                columns: controller.compactPage ? 1 : 2
                                columnSpacing: 10
                                rowSpacing: 10
                                AppButton {
                                    text: backend.tr("delete_account")
                                    role: "danger"
                                    compact: true
                                    enabled: backend.authenticated && !localDataOperationBusy && deletePw.text.length > 0
                                    onClicked: rootWindow.openDeleteAccountConfirm(deletePw.text)
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: trx("Requires password confirmation and permanently removes the local account.", "Requires password confirmation and permanently removes the local account.")
                                    color: theme.muted
                                    wrapMode: Text.Wrap
                                }
                            }
                        }
                    }
                }
            }
        }
    }

}
