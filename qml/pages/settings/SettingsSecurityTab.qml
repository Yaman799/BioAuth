import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

Item {
    id: securityTab
    property var controller
    property var theme
    property var rootWindow
    property string sectionMode: "security"
    readonly property bool protectionSection: sectionMode === "protection"
    readonly property bool securitySection: !protectionSection
    readonly property var autoEnrollment: backend.autoEnrollmentState || ({})
    readonly property var safetyReport: backend.safetyGateReport || ({})
    readonly property var safetyGates: safetyReport.gate_results || ({})
    function trx(arText, enText) { return controller ? controller.trx(arText, enText) : enText }
    function safetyGateStatus(key) { var gate = safetyGates[key] || ({}); return String(gate.status || "unavailable") }
    function safetyGateDisplayLabel(key) { var gate = safetyGates[key] || ({}); return String(gate.display_label || gate.status || "unavailable") }
    function safetyGateTone(key) { var gate = safetyGates[key] || ({}); return String(gate.tone || "details") }
    function safetyGateCodes(key) { var gate = safetyGates[key] || ({}); var codes = gate.reason_codes || []; if (!codes || codes.length === 0) return trx("لا توجد رموز", "no reason codes"); return codes.join(", ") }

    readonly property var retentionValues: [7, 14, 30, 90]

    ListModel {
        id: retentionModel
        ListElement { days: 7; label: "" }
        ListElement { days: 14; label: "" }
        ListElement { days: 30; label: "" }
        ListElement { days: 90; label: "" }
    }

    function refreshRetentionLabels() {
        retentionModel.setProperty(0, "label", backend.tr("retention_7_days"))
        retentionModel.setProperty(1, "label", backend.tr("retention_14_days"))
        retentionModel.setProperty(2, "label", backend.tr("retention_30_days"))
        retentionModel.setProperty(3, "label", backend.tr("retention_90_days"))
    }

    Component.onCompleted: refreshRetentionLabels()
    Connections {
        target: backend
        function onLanguageChanged() { securityTab.refreshRetentionLabels() }
    }
    Layout.fillWidth: true
        implicitHeight: securityGrid.implicitHeight

    GridLayout {
        id: securityGrid
        width: parent.width
        columns: width >= 1120 ? 2 : 1
        columnSpacing: 16
        rowSpacing: 16

        SettingsPrivacyCenterCard {
            visible: securityTab.securitySection
            Layout.fillWidth: true
            Layout.columnSpan: securityGrid.columns
            controller: controller
            theme: theme
            rootWindow: rootWindow
        }

        GlassCard {
            visible: securityTab.securitySection
            Layout.fillWidth: true
            Layout.columnSpan: securityGrid.columns
            implicitHeight: safetyRollbackContent.implicitHeight + 40
            ColumnLayout {
                id: safetyRollbackContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                SectionHeader {
                    title: trx("Safety Gates & Rollback", "Safety Gates & Rollback")
                    subtitle: trx("كل gate والـ rollback status يأتي من backend.safetyGateReport. QML يعرض فقط ولا يقرر الجاهزية أو القفل.", "Every gate and rollback status comes from backend.safetyGateReport. QML only displays and never decides readiness or lock behavior.")
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 10
                    InfoPill { objectName: "safetyGateDeveloperDirectOffPill"; textValue: trx("Direct control", "Direct control") + ": " + String(safetyGateStatus("developer_direct_enabled")); pillTone: safetyGateTone("developer_direct_enabled") }
                    InfoPill { objectName: "safetyGateInfluencePill"; textValue: trx("Influence", "Influence") + ": " + String(safetyGateStatus("device_influence")); pillTone: safetyGateTone("device_influence") }
                    InfoPill { objectName: "safetyGateNoSingleLockPill"; textValue: trx("No single model lock", "No single model lock") + ": " + safetyGateDisplayLabel("no_single_model_lock_enforced"); pillTone: safetyGateTone("no_single_model_lock_enforced") }
                    InfoPill { objectName: "safetyGateRollbackPill"; textValue: trx("Rollback snapshot", "Rollback snapshot") + ": " + safetyGateStatus("rollback_snapshot_exists"); pillTone: "details" }
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: safetyGateList.implicitHeight + 28
                    radius: 18
                    color: theme.surface1
                    border.color: theme.border
                    border.width: 1
                    ColumnLayout {
                        id: safetyGateList
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 7
                        Label { objectName: "safetyGateEvaluationHarnessLabel"; text: "evaluation_harness_passed: " + safetyGateDisplayLabel("evaluation_harness_passed") + " | " + safetyGateStatus("evaluation_harness_passed") + " | " + safetyGateCodes("evaluation_harness_passed"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { objectName: "safetyGateThresholdsLabel"; text: "thresholds_calibrated: " + safetyGateDisplayLabel("thresholds_calibrated") + " | " + safetyGateStatus("thresholds_calibrated") + " | " + safetyGateCodes("thresholds_calibrated"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { objectName: "safetyGateFaceLabel"; text: "face_confirmation_enabled: " + safetyGateDisplayLabel("face_confirmation_enabled") + " | " + safetyGateStatus("face_confirmation_enabled") + " | " + safetyGateCodes("face_confirmation_enabled"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { objectName: "safetyGateRollbackLabel"; text: "rollback_snapshot_exists: " + safetyGateDisplayLabel("rollback_snapshot_exists") + " | " + safetyGateStatus("rollback_snapshot_exists") + " | " + safetyGateCodes("rollback_snapshot_exists"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { objectName: "safetyGateFallbacksLabel"; text: "fallbacks: timeout=" + safetyGateDisplayLabel("timeout_fallback_enabled") + ", schema=" + safetyGateDisplayLabel("schema_error_fallback_enabled"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: controller.compactPage ? 1 : 3
                    columnSpacing: 12
                    rowSpacing: 12
                    AppButton { objectName: "emergencyDisableHybridButton"; visible: false; enabled: false; text: trx("Hybrid removed", "Hybrid removed"); role: "danger"; compact: true }
                    AppButton { objectName: "rollbackToClassicButton"; text: trx("Rollback to Classic", "Rollback to Classic"); role: "warn"; compact: true; onClicked: backend.rollbackToClassic() }
                    AppButton { objectName: "writeSafetyGateReportButton"; text: trx("Write Safety Gate Report", "Write Safety Gate Report"); role: "details"; compact: true; onClicked: backend.writeSafetyGateReport() }
                }
                Label { Layout.fillWidth: true; text: trx("Rollback controls preserve model evidence, logs, reports, and Shadow artifacts. Hybrid Direct Test is removed from the commercial flow and cannot block training.", "Rollback controls preserve model evidence, logs, reports, and Shadow artifacts. Hybrid Direct Test is removed from the commercial flow and cannot block training."); color: theme.muted; wrapMode: Text.Wrap }
            }
        }

        GlassCard {
            visible: securityTab.securitySection
            Layout.fillWidth: true
            Layout.columnSpan: securityGrid.columns
            implicitHeight: smartEnrollmentOverviewPointerContent.implicitHeight + 40
            ColumnLayout {
                id: smartEnrollmentOverviewPointerContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                SectionHeader {
                    title: trx("Smart Auto Enrollment", "Smart Auto Enrollment")
                    subtitle: trx("تتم إدارة أزرار Smart Auto Enrollment الآن من صفحة Profile & Training بدل Overview.", "Smart Auto Enrollment controls are now managed from Profile & Training instead of Overview.")
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 10
                    InfoPill { textValue: autoEnrollment.enabled === true ? trx("Enabled", "Enabled") : trx("Disabled", "Disabled"); pillTone: autoEnrollment.enabled === true ? "info" : "neutral" }
                    InfoPill { textValue: autoEnrollment.consentSatisfied === true ? trx("Consent OK", "Consent OK") : trx("Consent required", "Consent required"); pillTone: autoEnrollment.consentSatisfied === true ? "success" : "warn" }
                    InfoPill { textValue: trx("Accepted", "Accepted") + ": " + String(autoEnrollment.acceptedSessions || 0) + " / " + String(autoEnrollment.requiredSessions || 8); pillTone: autoEnrollment.trainingReady === true ? "success" : "warn" }
                }

                Label {
                    Layout.fillWidth: true
                    text: trx("Open Profile & Training → Smart Auto Enrollment to enable Smart Auto Enrollment, Auto-train when ready, or Auto-promote when production-safe.", "Open Profile & Training → Smart Auto Enrollment to enable Smart Auto Enrollment, Auto-train when ready, or Auto-promote when production-safe.")
                    color: theme.text
                    wrapMode: Text.Wrap
                }
                Label {
                    Layout.fillWidth: true
                    text: trx("Requires explicit privacy consent. Collection still uses existing safety gates and only accepted quality-gated sessions count.", "Requires explicit privacy consent. Collection still uses existing safety gates and only accepted quality-gated sessions count.")
                    color: theme.muted
                    wrapMode: Text.Wrap
                }
            }
        }

        GlassCard {
            visible: securityTab.protectionSection
            Layout.fillWidth: true
            implicitHeight: securityPostureContent.implicitHeight + 40
            ColumnLayout {
                id: securityPostureContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                SectionHeader {
                    title: trx("Security posture", "Security posture")
                    subtitle: trx("ملخص سريع يوضح حالة الجاهزية والثقة قبل تعديل الإعدادات الحساسة.", "A fast read of readiness and trust before changing sensitive controls.")
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 10
                    InfoPill { textValue: backend.profile.ready ? trx("Profile ready", "Profile ready") : trx("Profile learning", "Profile learning"); pillTone: backend.profile.ready ? "success" : "warn" }
                    InfoPill { textValue: backend.runtimeState.trustLabel || backend.runtimeState.decisionLabel || backend.runtimeState.decisionText || backend.tr("status_idle"); pillTone: backend.runtimeState.active ? (backend.runtimeState.trustTone || (rootWindow ? rootWindow.decisionTone(backend.runtimeState.decisionText) : "info")) : "neutral" }
                    InfoPill { textValue: trx("Drift Lab", "Drift Lab") + ": " + trx("Preview / Experimental", "Preview / Experimental"); pillTone: "neutral" }
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: securityPostureSummary.implicitHeight + 28
                    radius: 18
                    color: theme.surface1
                    border.color: theme.border
                    border.width: 1
                    ColumnLayout {
                        id: securityPostureSummary
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 6
                        Label { text: backend.profile.progressText || trx("Profile is ready for protected sessions.", "Profile is ready for protected sessions."); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: trx("Use Drift Lab only as an experimental preview of real backend state, then confirm with the live session decision.", "Use Drift Lab only as an experimental preview of real backend state, then confirm with the live session decision."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }
        }

        GlassCard {
            visible: securityTab.protectionSection
            Layout.fillWidth: true
            implicitHeight: riskSensitivityContent.implicitHeight + 40
            ColumnLayout {
                id: riskSensitivityContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                SectionHeader {
                    title: backend.tr("risk_sensitivity")
                    subtitle: trx("اضبط توازن الحساسية بين تقليل الإنذارات الكاذبة ورفع التشدد عند الشك.", "Tune the balance between fewer false positives and stricter intervention when behavior drifts.")
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    ChoiceChip {
                        titleText: trx("محافظ", "Conservative")
                        descriptionText: trx("إنذارات أقل، عتبات أعلى.", "Fewer alerts, higher thresholds.")
                        selected: controller.draftRiskSensitivity === "conservative"
                        accentColor: theme.info
                        onChosen: controller.draftRiskSensitivity = "conservative"
                    }
                    ChoiceChip {
                        titleText: trx("متوازن", "Balanced")
                        descriptionText: trx("الخيار الافتراضي الموصى به.", "Recommended default profile.")
                        selected: controller.draftRiskSensitivity === "balanced"
                        accentColor: theme.accent
                        onChosen: controller.draftRiskSensitivity = "balanced"
                    }
                    ChoiceChip {
                        titleText: trx("صارم", "Strict")
                        descriptionText: trx("أسرع في رفع مستوى المخاطرة.", "Escalates risk more aggressively.")
                        selected: controller.draftRiskSensitivity === "strict"
                        accentColor: theme.warn
                        onChosen: controller.draftRiskSensitivity = "strict"
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: riskSensitivitySummary.implicitHeight + 28
                    radius: 18
                    color: theme.surface1
                    border.color: theme.border
                    border.width: 1
                    ColumnLayout {
                        id: riskSensitivitySummary
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 4
                        Label { text: backend.riskSensitivityPreset === "strict" ? trx("Strict mode is active", "Strict mode is active") : (backend.riskSensitivityPreset === "conservative" ? trx("Conservative mode is active", "Conservative mode is active") : trx("Balanced mode is active", "Balanced mode is active")); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: trx("يؤثر هذا على الـ scoring والتصعيد الحي وسياسة تأكيد القفل، وليس على شكل البيانات المسجلة.", "This now affects scoring, live escalation, and lock confirmation policy, not the captured behavioral data."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }
        }


        GlassCard {
            visible: securityTab.securitySection
            Layout.fillWidth: true
            implicitHeight: rememberLoginContent.implicitHeight + 40
            ColumnLayout {
                id: rememberLoginContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                SectionHeader {
                    title: backend.tr("remember_login")
                    subtitle: trx("تحكم واضح وصريح في استعادة آخر حساب محلي على هذا الجهاز فقط.", "A clear opt-in for restoring the last local account on this device only.")
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: rememberLoginRow.implicitHeight + 28
                    radius: 18
                    color: theme.surface1
                    border.color: theme.border
                    border.width: 1

                    RowLayout {
                        id: rememberLoginRow
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 12

                        StartupSwitch {
                            checked: controller.draftRememberLoginEnabled
                            onToggled: function(nextChecked) { controller.draftRememberLoginEnabled = nextChecked }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Label {
                                text: backend.tr("remember_login")
                                color: theme.text
                                font.bold: true
                                wrapMode: Text.Wrap
                            }
                            Label {
                                text: backend.tr("remember_login_note")
                                color: theme.muted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: trx("يتم إبطال هذا التذكر عند تسجيل الخروج أو انتهاء المهلة أو تغيير كلمة المرور.", "This remembered sign-in is cleared on logout, after the expiry window, or when the password changes.")
                    color: theme.muted
                    wrapMode: Text.Wrap
                }
            }
        }

        GlassCard {
            visible: securityTab.securitySection
            Layout.fillWidth: true
            implicitHeight: incidentEvidenceContent.implicitHeight + 40
            ColumnLayout {
                id: incidentEvidenceContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                property var retentionValues: [7, 14, 30, 90]
                SectionHeader {
                    title: trx("Incident evidence", "Incident evidence")
                    subtitle: trx("يلتقط لقطة شاشة وصور كاميرا قصيرة فقط عند تأكيد وجود دخيل، ويحفظها محليًا على هذا الجهاز.", "Capture one screenshot and a short webcam burst only after a confirmed intruder event, and keep them locally on this device.")
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: incidentEvidenceToggleRow.implicitHeight + 28
                    radius: 18
                    color: controller.draftIncidentEvidenceEnabled ? (theme.surface1) : (theme.surface1)
                    border.color: controller.draftIncidentEvidenceEnabled ? theme.success : theme.border
                    border.width: 1
                    RowLayout {
                        id: incidentEvidenceToggleRow
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 14
                        StartupSwitch {
                            checked: controller.draftIncidentEvidenceEnabled
                            onToggled: function(nextChecked) { controller.draftIncidentEvidenceEnabled = nextChecked }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Label {
                                text: trx("Enable incident evidence capture", "Enable incident evidence capture")
                                color: theme.text
                                font.bold: true
                                wrapMode: Text.Wrap
                            }
                            Label {
                                text: controller.draftIncidentEvidenceEnabled ? trx("سيعمل فقط عند confirmed intruder ويحفظ الأدلة محليًا بدون سحابة أو مشاركة تلقائية.", "Runs only on confirmed intruder events and stores evidence locally with no cloud upload or auto-sharing.") : trx("مغلق حاليًا. عند الإغلاق لن يتم حفظ أي screenshot أو webcam evidence للحوادث.", "Currently off. When disabled, no screenshot or webcam incident evidence will be saved.")
                                color: theme.muted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: controller.compactPage ? 1 : 2
                    columnSpacing: 12
                    rowSpacing: 12
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: incidentEvidenceScreenshotRow.implicitHeight + 28
                        radius: 18
                        color: theme.surface1
                        border.color: theme.border
                        border.width: 1
                        opacity: controller.draftIncidentEvidenceEnabled ? 1 : 0.6
                        RowLayout {
                            id: incidentEvidenceScreenshotRow
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 12
                            StartupSwitch {
                                checked: controller.draftIncidentEvidenceCaptureScreenshot
                                enabled: controller.draftIncidentEvidenceEnabled
                                onToggled: function(nextChecked) { controller.draftIncidentEvidenceCaptureScreenshot = nextChecked }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Label { text: trx("Screenshot", "Screenshot"); color: theme.text; font.bold: true }
                                Label { text: trx("One shot before lock and before any visual cleanup.", "One shot before lock and before any visual cleanup."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: incidentEvidenceWebcamRow.implicitHeight + 28
                        radius: 18
                        color: theme.surface1
                        border.color: theme.border
                        border.width: 1
                        opacity: controller.draftIncidentEvidenceEnabled ? 1 : 0.6
                        RowLayout {
                            id: incidentEvidenceWebcamRow
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 12
                            StartupSwitch {
                                checked: controller.draftIncidentEvidenceCaptureWebcam
                                enabled: controller.draftIncidentEvidenceEnabled
                                onToggled: function(nextChecked) { controller.draftIncidentEvidenceCaptureWebcam = nextChecked }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Label { text: trx("Webcam", "Webcam"); color: theme.text; font.bold: true }
                                Label { text: trx("Short burst captured before lock for higher reliability.", "Short burst captured before lock for higher reliability."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            }
                        }
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: controller.compactPage ? 1 : 3
                    columnSpacing: 12
                    rowSpacing: 12
                    Label { text: trx("Retention", "Retention"); color: theme.text; font.bold: true }
                    ComboBox {
                        id: incidentRetentionBox
                        Layout.fillWidth: true
                        Layout.preferredWidth: 220
                        model: retentionModel
                        textRole: "label"
                        currentIndex: Math.max(0, retentionValues.indexOf(controller.draftIncidentEvidenceRetentionDays))
                        onActivated: controller.draftIncidentEvidenceRetentionDays = retentionModel.get(currentIndex).days
                        enabled: controller.draftIncidentEvidenceEnabled
                    }
                    Label {
                        Layout.fillWidth: true
                        text: trx("Older local evidence is cleaned automatically according to this retention period.", "Older local evidence is cleaned automatically according to this retention period.")
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                }
            }
        }

        GlassCard {
            visible: securityTab.securitySection
            Layout.fillWidth: true
            implicitHeight: passwordUpdateContent.implicitHeight + 40
            ColumnLayout {
                id: passwordUpdateContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                SectionHeader {
                    title: backend.tr("update_password")
                    subtitle: trx("حدّث كلمة المرور محليًا داخل هذا الجهاز من قسم واحد واضح ومباشر.", "Update the local password on this device from one clear, focused section.")
                }
                AppTextField {
                    id: currentPw
                    Layout.fillWidth: true
                    placeholderText: backend.tr("current_password")
                    echoMode: TextInput.Password
                }
                AppTextField {
                    id: newPw
                    Layout.fillWidth: true
                    placeholderText: backend.tr("new_password")
                    echoMode: TextInput.Password
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: controller.compactPage ? 1 : 2
                    columnSpacing: 12
                    rowSpacing: 12
                    AppButton {
                        text: backend.tr("update_password")
                        role: "details"
                        compact: true
                        onClicked: {
                            backend.changePassword(currentPw.text, newPw.text)
                            currentPw.text = ""
                            newPw.text = ""
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: trx("Security changes are isolated here to reduce accidental edits.", "Security changes are isolated here to reduce accidental edits.")
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }
}
