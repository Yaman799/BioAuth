import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"
import "../settings"
import "../../theme/Ui.js" as Ui

GridLayout {
    id: privacySettingsSection
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
    visible: settingsRoot.activeSection === "privacy"
    enabled: visible
    Layout.preferredHeight: visible ? implicitHeight : 0
    Layout.minimumHeight: visible ? implicitHeight : 0
    Layout.maximumHeight: visible ? 1000000 : 0

    GlassCard {
        Layout.fillWidth: true
        Layout.columnSpan: settingsRoot.compactLayout ? 1 : 2
        implicitHeight: privacyHeaderContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: privacyHeaderContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.privacyIcon; tone: "success"; Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Label { Layout.fillWidth: true; text: settingsRoot.label("مركز الخصوصية", "Privacy Center"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("إدارة سياسة الخصوصية، أدلة الحوادث، وحزمة الدعم من مكان واحد. لا يتم عرض بيانات حساسة داخل الواجهة.", "Manage privacy policy access, incident evidence, and support export from one place. Sensitive data is not displayed in the UI.")
                        color: theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                    }
                }
                InfoPill {
                    textValue: settingsRoot.privacyFeedbackText.length > 0 ? settingsRoot.privacyFeedbackText : settingsRoot.privacyFeedbackFallback()
                    pillTone: settingsRoot.privacyFeedbackCurrentTone()
                }
            }

            Flow {
                Layout.fillWidth: true
                spacing: 10
                InfoPill { textValue: settingsRoot.label("الموافقة", "Consent") + ": " + settingsRoot.yesNo(settingsRoot.privacyState.privacyConsentGranted === true); pillTone: settingsRoot.privacyState.privacyConsentGranted === true ? "success" : "warn" }
                InfoPill { textValue: settingsRoot.label("أدلة الحوادث", "Evidence") + ": " + settingsRoot.yesNo(backend.incidentEvidenceEnabled); pillTone: backend.incidentEvidenceEnabled ? "info" : "neutral" }
                InfoPill { textValue: settingsRoot.label("الاحتفاظ", "Retention") + ": " + settingsRoot.retentionLabel(backend.incidentEvidenceRetentionDays); pillTone: "details" }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AppButton {
                    text: settingsRoot.settingsActionInFlight ? settingsRoot.label("جاري الفتح…", "Opening…") : settingsRoot.label("فتح سياسة الخصوصية", "Open privacy policy")
                    role: "details"
                    enabled: !settingsRoot.settingsActionInFlight
                    onClicked: settingsRoot.openPrivacySummary()
                }

                AppButton {
                    text: settingsRoot.settingsActionInFlight ? settingsRoot.label("جاري التصدير…", "Exporting…") : settingsRoot.label("تصدير حزمة الدعم", "Export support bundle")
                    role: "neutral"
                    enabled: !settingsRoot.settingsActionInFlight && settingsRoot.privacyState.supportBundleAvailable !== false
                    onClicked: settingsRoot.guardedExportSupportBundle()
                }

                Label {
                    Layout.fillWidth: true
                    text: settingsRoot.safeString(settingsRoot.privacyState.safeBoundaryText, settingsRoot.label("حزمة الدعم تستخدم تشخيصات مسموحة فقط ولا تعرض كلمات مرور أو رموز دخول أو بيانات حيوية خام.", "Support bundles use allowlisted support data and do not expose passwords, passcodes, or raw biometric data."))
                    color: theme.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.localDataIcon
                tone: "info"
                title: settingsRoot.label("ملخص البيانات المحلية", "Local data summary")
                detail: settingsRoot.safeString(settingsRoot.privacyState.localDataSummaryText, settingsRoot.label("لا يوجد ملخص بيانات محلي معروض حالياً.", "No local data summary is shown right now."))
                trailingText: settingsRoot.label("من النظام", "System")
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        Layout.columnSpan: settingsRoot.compactLayout ? 1 : 2
        implicitHeight: privacyEvidenceContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: privacyEvidenceContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.storageIcon; tone: "info"; Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Label { Layout.fillWidth: true; text: settingsRoot.label("أدلة الحوادث والاحتفاظ", "Incident evidence & retention"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("هذه الإعدادات تحفظ فقط عبر النظام. تفعيل الأدلة يعني السماح بحفظ أدلة للحوادث المؤكدة حسب سياسة النظام.", "These settings save only through BioAuth. Enabling evidence allows incident evidence for confirmed events according to system policy.")
                        color: theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                    }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: settingsRoot.compactLayout ? 1 : 2
                columnSpacing: 14
                rowSpacing: 12

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Label { Layout.fillWidth: true; text: settingsRoot.label("أدلة الحوادث", "Incident evidence"); color: theme.text; font.bold: true; wrapMode: Text.Wrap }
                        Label { Layout.fillWidth: true; text: settingsRoot.label("يحفظ فقط ما يسمح به النظام عند الحوادث المؤكدة.", "Only system-allowed evidence is saved for confirmed incidents."); color: theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
                    }
                    StartupSwitch {
                        theme: settingsRoot.calmToggleTheme
                        enabled: !settingsRoot.privacyApplyInFlight && !settingsRoot.settingsActionInFlight
                        checked: settingsRoot.draftIncidentEvidenceEnabled
                        debugLabel: "privacy incident evidence"
                        onToggled: settingsRoot.setDraftIncidentEvidenceEnabled(checked)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Label { Layout.fillWidth: true; text: settingsRoot.label("لقطات الشاشة", "Screenshots"); color: theme.text; font.bold: true; wrapMode: Text.Wrap }
                        Label { Layout.fillWidth: true; text: settingsRoot.label("لا تلتقط الواجهة لقطات؛ تعرض فقط اختيار النظام.", "The UI does not capture screenshots; it only shows the system setting."); color: theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
                    }
                    StartupSwitch {
                        theme: settingsRoot.calmToggleTheme
                        enabled: !settingsRoot.privacyApplyInFlight && !settingsRoot.settingsActionInFlight
                        checked: settingsRoot.draftIncidentEvidenceCaptureScreenshot
                        debugLabel: "privacy screenshot evidence"
                        onToggled: settingsRoot.setDraftIncidentEvidenceCaptureScreenshot(checked)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Label { Layout.fillWidth: true; text: settingsRoot.label("دليل الكاميرا", "Camera evidence"); color: theme.text; font.bold: true; wrapMode: Text.Wrap }
                        Label { Layout.fillWidth: true; text: settingsRoot.label("لا تعرض الواجهة صور كاميرا محفوظة أو قوالب وجه.", "The UI does not display saved camera images or face templates."); color: theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
                    }
                    StartupSwitch {
                        theme: settingsRoot.calmToggleTheme
                        enabled: !settingsRoot.privacyApplyInFlight && !settingsRoot.settingsActionInFlight
                        checked: settingsRoot.draftIncidentEvidenceCaptureWebcam
                        debugLabel: "privacy camera evidence"
                        onToggled: settingsRoot.setDraftIncidentEvidenceCaptureWebcam(checked)
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Label { Layout.fillWidth: true; text: settingsRoot.label("مدة الاحتفاظ", "Retention period"); color: theme.text; font.bold: true; wrapMode: Text.Wrap }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        ChoiceChip {
                            titleText: settingsRoot.label("7 أيام", "7 days")
                            descriptionText: settingsRoot.label("أقصر مدة", "Shortest")
                            selected: settingsRoot.draftIncidentEvidenceRetentionDays === 7
                            accentColor: Ui.roleColor(theme, "info")
                            onChosen: settingsRoot.chooseDraftIncidentEvidenceRetentionDays(7)
                        }
                        ChoiceChip {
                            titleText: settingsRoot.label("30 يوم", "30 days")
                            descriptionText: settingsRoot.label("افتراضي", "Default")
                            selected: settingsRoot.draftIncidentEvidenceRetentionDays === 30
                            accentColor: Ui.roleColor(theme, "info")
                            onChosen: settingsRoot.chooseDraftIncidentEvidenceRetentionDays(30)
                        }
                        ChoiceChip {
                            titleText: settingsRoot.label("90 يوم", "90 days")
                            descriptionText: settingsRoot.label("أطول", "Longest")
                            selected: settingsRoot.draftIncidentEvidenceRetentionDays === 90
                            accentColor: Ui.roleColor(theme, "info")
                            onChosen: settingsRoot.chooseDraftIncidentEvidenceRetentionDays(90)
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AppButton {
                    text: settingsRoot.privacyApplyInFlight ? settingsRoot.label("جاري الحفظ…", "Saving…") : settingsRoot.label("حفظ إعدادات الخصوصية", "Save privacy settings")
                    role: "success"
                    enabled: settingsRoot.hasPrivacyDraftChanges && !settingsRoot.privacyApplyInFlight && !settingsRoot.settingsActionInFlight
                    onClicked: settingsRoot.applyPrivacySettings()
                }

                AppButton {
                    text: settingsRoot.label("إلغاء التعديلات", "Discard changes")
                    role: "neutral"
                    enabled: settingsRoot.hasPrivacyDraftChanges && !settingsRoot.privacyApplyInFlight
                    onClicked: settingsRoot.resetPrivacyDrafts()
                }

                Label {
                    Layout.fillWidth: true
                    text: settingsRoot.hasPrivacyDraftChanges ? settingsRoot.label("راجع إعدادات الخصوصية قبل الحفظ.", "Review privacy settings before saving.") : settingsRoot.label("لا توجد تغييرات خصوصية معلّقة.", "No pending privacy changes.")
                    color: theme.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}
