import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

GlassCard {
    id: privacyCenter
    property var controller
    property var theme
    property var rootWindow
    readonly property int privacyRefreshKey: (backend.sessions ? backend.sessions.length : 0) + Number((backend.profile && backend.profile.session_count) || 0) + Number(backend.incidentEvidenceRetentionDays || 0)
    readonly property var privacyState: privacyRefreshKey >= 0 ? (backend.privacyCenterState || ({})) : ({})
    readonly property var autoEnrollment: backend.autoEnrollmentState || ({})

    function trx(arText, enText) { return controller ? controller.trx(arText, enText) : enText }
    function boolText(value) { return value ? trx("نعم", "Yes") : trx("لا", "No") }
    function enabledText(value) { return value ? trx("مفعّل", "Enabled") : trx("مغلق", "Disabled") }
    function privacyTone() { return privacyState.privacyConsentGranted ? "success" : "warn" }
    function evidenceTone() { return privacyState.incidentEvidenceEnabled ? "info" : "neutral" }
    function destructiveEnabled() { return privacyState.authenticated && privacyState.deleteMyDataAvailable && !backend.trainingInProgress && !backend.canStop }
    function toneColor(tone) { return rootWindow ? rootWindow.toneColor(tone) : (tone === "danger" ? theme.danger : (tone === "warn" ? theme.warn : (tone === "success" ? theme.success : theme.info))) }

    Layout.fillWidth: true
    implicitHeight: privacyCenterContent.implicitHeight + 42

    ColumnLayout {
        id: privacyCenterContent
        anchors.fill: parent
        anchors.margins: 20
        spacing: 14

        SectionHeader {
            title: trx("Privacy Center", "Privacy Center")
            subtitle: trx("مكان واحد للوصول إلى سياسة الخصوصية، الموافقة، حالة أدلة الحوادث، حزمة الدعم، وحذف البيانات المحلي الآمن.", "One place for privacy policy access, consent, incident evidence status, support export, and safe local data deletion controls.")
        }

        Flow {
            Layout.fillWidth: true
            spacing: 10
            InfoPill { textValue: trx("Privacy consent", "Privacy consent") + ": " + boolText(privacyState.privacyConsentGranted); pillTone: privacyCenter.privacyTone() }
            InfoPill { textValue: trx("Evidence", "Evidence") + ": " + enabledText(privacyState.incidentEvidenceEnabled); pillTone: privacyCenter.evidenceTone() }
            InfoPill { textValue: trx("Smart enrollment", "Smart enrollment") + ": " + enabledText(autoEnrollment.enabled === true); pillTone: autoEnrollment.enabled === true ? "info" : "neutral" }
            InfoPill { textValue: trx("Retention", "Retention") + ": " + String(privacyState.incidentEvidenceRetentionDays || backend.incidentEvidenceRetentionDays || 30) + "d"; pillTone: "details" }
            InfoPill { textValue: trx("License", "License") + ": " + String(privacyState.licenseTier || "free").toUpperCase(); pillTone: privacyState.licensePremiumActive ? "success" : "info" }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: controller && controller.compactPage ? 1 : 2
            columnSpacing: 14
            rowSpacing: 14

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: localDataContent.implicitHeight + 28
                radius: 18
                color: theme.surface1
                border.color: theme.border
                border.width: 1

                ColumnLayout {
                    id: localDataContent
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 8
                    Label { text: trx("Local data summary", "Local data summary"); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Label {
                        Layout.fillWidth: true
                        text: privacyState.localDataSummaryText || trx("No local profile summary is available yet.", "No local profile summary is available yet.")
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        text: autoEnrollment.collectionStatusText || trx("Smart Auto Enrollment collects only after consent and when safe.", "Smart Auto Enrollment collects only after consent and when safe.")
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        text: privacyState.safeBoundaryText || trx("Support bundles exclude secrets and raw behavioral data.", "Support bundles exclude secrets and raw behavioral data.")
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: evidenceStatusContent.implicitHeight + 28
                radius: 18
                color: theme.surface1
                border.color: privacyState.incidentEvidenceEnabled ? theme.info : theme.border
                border.width: 1

                ColumnLayout {
                    id: evidenceStatusContent
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 8
                    Label { text: trx("Incident evidence consent/status", "Incident evidence consent/status"); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Label {
                        Layout.fillWidth: true
                        text: privacyState.incidentEvidenceStatusText || trx("Incident evidence is disabled.", "Incident evidence is disabled.")
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        InfoPill { textValue: trx("Evidence consent", "Evidence consent") + ": " + boolText(privacyState.evidenceConsentGranted); pillTone: privacyState.evidenceConsentGranted ? "success" : "neutral" }
                        InfoPill { textValue: trx("Screenshot", "Screenshot") + ": " + enabledText(privacyState.incidentEvidenceCaptureScreenshot); pillTone: privacyState.incidentEvidenceCaptureScreenshot ? "info" : "neutral" }
                        InfoPill { textValue: trx("Webcam", "Webcam") + ": " + enabledText(privacyState.incidentEvidenceCaptureWebcam); pillTone: privacyState.incidentEvidenceCaptureWebcam ? "info" : "neutral" }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: actionsContent.implicitHeight + 28
            radius: 18
            color: theme.surface1
            border.color: theme.border
            border.width: 1

            ColumnLayout {
                id: actionsContent
                anchors.fill: parent
                anchors.margins: 14
                spacing: 12
                Label { text: trx("Backend-backed privacy actions", "Backend-backed privacy actions"); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                GridLayout {
                    Layout.fillWidth: true
                    columns: controller && controller.compactPage ? 1 : 2
                    columnSpacing: 10
                    rowSpacing: 10
                    AppButton {
                        text: backend.tr("open_policy")
                        role: "details"
                        compact: true
                        Layout.fillWidth: true
                        onClicked: backend.openPrivacyPolicy()
                    }
                    AppButton {
                        text: trx("Create support bundle", "Create support bundle")
                        role: "details"
                        compact: true
                        Layout.fillWidth: true
                        enabled: privacyState.supportBundleAvailable !== false
                        onClicked: backend.exportSupportBundle()
                    }
                    AppButton {
                        text: trx("Delete incident evidence", "Delete incident evidence")
                        role: "warn"
                        compact: true
                        Layout.fillWidth: true
                        enabled: privacyState.deleteIncidentEvidenceAvailable === true && !backend.trainingInProgress && !backend.canStop
                        onClicked: rootWindow.openDeleteIncidentEvidenceConfirm()
                    }
                    AppButton {
                        text: backend.tr("delete_my_data")
                        role: "danger"
                        compact: true
                        Layout.fillWidth: true
                        enabled: privacyCenter.destructiveEnabled()
                        onClicked: rootWindow.openDeleteMyDataConfirm()
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: privacyState.destructiveActionBlocked ? trx("Destructive privacy actions are disabled while training or a protected session is active.", "Destructive privacy actions are disabled while training or a protected session is active.") : trx("Deletion controls use existing backend slots and confirmation dialogs before any local data is removed.", "Deletion controls use existing backend slots and confirmation dialogs before any local data is removed.")
                    color: privacyState.destructiveActionBlocked ? privacyCenter.toneColor("warn") : theme.muted
                    wrapMode: Text.Wrap
                }
                Label {
                    Layout.fillWidth: true
                    visible: backend.lastSupportBundlePath !== ""
                    text: trx("Last support bundle", "Last support bundle") + ": " + backend.lastSupportBundlePath
                    color: theme.muted
                    wrapMode: Text.WrapAnywhere
                }
            }
        }
    }
}
