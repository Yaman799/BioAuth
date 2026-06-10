import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    objectName: "overviewPage"
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool compactLayout: rootWindow ? rootWindow.compactLayout : width < 1180
    property bool denseLayout: rootWindow ? rootWindow.denseLayout : width < 980
    property int summaryColumns: width >= 1180 ? 3 : (width >= 760 ? 2 : 1)
    readonly property var dashboardState: backend.dashboardState || ({})
    readonly property var runtimeState: backend.runtimeState || ({})
    readonly property var faceState: backend.faceConfirmationState || ({})
    readonly property var productionApproval: backend.productionApprovalState || ({})

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }

    function trainingProgressParams() {
        return backend.trainingProgress && backend.trainingProgress.message_params ? backend.trainingProgress.message_params : ({})
    }
    function heartbeatText() {
        var seconds = Number(trainingProgressParams().heartbeat_seconds || 0)
        if (!backend.trainingInProgress || seconds <= 0)
            return ""
        return trx("ما زال التدريب يعمل... " + String(seconds) + "ث", "Still running... " + String(seconds) + "s")
    }
    function positiveSessionsText() {
        var count = Number(trainingProgressParams().positive_sessions || 0)
        if (count <= 0)
            return ""
        return trx("الجلسات الإيجابية: ", "Positive sessions: ") + String(count)
    }
    function referenceNegativesText() {
        var count = Number(trainingProgressParams().reference_negatives || 0)
        if (count <= 0)
            return ""
        return trx("المرجعيات السلبية: ", "Reference negatives: ") + String(count)
    }
    readonly property string heartbeatSummary: heartbeatText()
    readonly property string positiveSessionsSummary: positiveSessionsText()
    readonly property string referenceNegativesSummary: referenceNegativesText()
    function openSection(index) {
        if (!rootWindow)
            return
        rootWindow.navSelection = index
    }
    function safeText(value, fallbackText) {
        if (value === undefined || value === null || String(value).length === 0)
            return fallbackText
        return String(value)
    }
    function systemStatusText() {
        if (dashboardState.lastRefreshError)
            return trx("تحتاج المزامنة انتباهًا", "Refresh needs attention")
        if (dashboardState.loading || dashboardState.updating || dashboardState.historyLoading)
            return trx("يتم التحديث", "Updating")
        return runtimeState.active ? trx("يعمل", "Running") : backend.tr("status_idle")
    }
    function systemStatusTone() {
        if (dashboardState.lastRefreshError)
            return theme.warn
        if (runtimeState.active)
            return theme.success
        if (dashboardState.loading || dashboardState.updating || dashboardState.historyLoading)
            return theme.info
        return theme.primary
    }
    function protectionModeText() {
        return safeText(runtimeState.modeText || runtimeState.protectionModeText || runtimeState.flowText || runtimeState.runtimeDisplayText, runtimeState.active ? backend.tr("start_protected") : trx("Classic / idle", "Classic / idle"))
    }
    function profileSummaryText() {
        return safeText(backend.profile.readyText, trx("غير متاح", "Unavailable"))
    }
    function profileSummaryDetail() {
        return safeText(backend.profile.progressText, trx("افتح Profile & Training للتفاصيل.", "Open Profile & Training for details."))
    }
    function faceSummaryText() {
        return safeText(faceState.statusText || faceState.message, faceState.enabled === true ? trx("مفعل", "Enabled") : trx("غير مفعل", "Disabled"))
    }
    function faceSummaryBadge() {
        return faceState.enabled === true ? trx("Enabled", "Enabled") : trx("Summary", "Summary")
    }
    function rollbackSummaryText() {
        return safeText(productionApproval.rollbackStatusText || productionApproval.rollback_status_text || productionApproval.rollbackReadyText || productionApproval.rollback_ready_text, trx("غير معروض في Overview", "Not exposed in Overview"))
    }
    function lastDecisionText() {
        return safeText(runtimeState.trustLabel || runtimeState.decisionLabel || runtimeState.decisionText, backend.tr("status_idle"))
    }
    function lastDecisionDetail() {
        return safeText(runtimeState.statusDetail || runtimeState.runtimeDisplayText || runtimeState.activeText, trx("افتح Live Session لمؤشرات الجلسة.", "Open Live Session for session telemetry."))
    }

    ScrollView {
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        ColumnLayout {
            width: parent.width
            spacing: root.compactLayout ? 14 : 18

            GlassCard {
                objectName: "overviewControlDashboardCard"
                Layout.fillWidth: true
                implicitHeight: overviewIntroColumn.implicitHeight + (root.denseLayout ? 32 : 44)

                ColumnLayout {
                    id: overviewIntroColumn
                    anchors.fill: parent
                    anchors.margins: root.denseLayout ? 18 : 22
                    spacing: 14

                    SectionHeader {
                        title: trx("نظرة عامة متقدمة", "Advanced control overview")
                        subtitle: trx(
                            "ملخص سريع فقط. تفاصيل الجلسة، التدريب، الدريفت، الأدلة، والتقييم موجودة في صفحاتها المخصصة.",
                            "A quick command surface only. Live session, training, drift, evidence, and evaluation details live in their dedicated pages."
                        )
                        Layout.fillWidth: true
                    }

                    Label {
                        visible: dashboardState.lastRefreshError || dashboardState.stale
                        text: dashboardState.lastRefreshError
                              ? trx("توجد مشكلة في تحديث ملخص dashboard؛ لم يتم إخفاء أي حالة أمنية أو استدعاء إصلاح تلقائي.", "Dashboard refresh has an issue; no security state is hidden and no automatic repair is triggered.")
                              : trx("يعرض Overview ملخصًا محفوظًا مؤقتًا حتى يكتمل تحديث backend.", "Overview is showing a cached summary until the backend refresh completes.")
                        color: dashboardState.lastRefreshError ? theme.warn : theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10

                        InfoPill { textValue: trx("Details moved", "Details moved"); pillTone: "details" }
                        InfoPill { textValue: trx("Backend-owned state", "Backend-owned state"); pillTone: "info" }
                        InfoPill { textValue: trx("No local readiness logic", "No local readiness logic"); pillTone: "warn" }
                    }
                }
            }

            GridLayout {
                objectName: "overviewSummaryTiles"
                Layout.fillWidth: true
                columns: root.summaryColumns
                columnSpacing: 16
                rowSpacing: 16

                StatTile {
                    Layout.fillWidth: true
                    title: trx("System Status", "System Status")
                    value: systemStatusText()
                    subtitle: dashboardState.lastRefreshError ? safeText(dashboardState.lastRefreshError, "") : trx("Backend dashboard summary only.", "Backend dashboard summary only.")
                    accentColor: systemStatusTone()
                    badge: runtimeState.active ? trx("Active", "Active") : trx("Idle", "Idle")
                }
                StatTile {
                    Layout.fillWidth: true
                    title: trx("Protection Mode", "Protection Mode")
                    value: protectionModeText()
                    subtitle: trx("Open Live Session for live telemetry and decision context.", "Open Live Session for live telemetry and decision context.")
                    accentColor: theme.info
                    badge: trx("Summary", "Summary")
                }
                StatTile {
                    Layout.fillWidth: true
                    title: trx("Profile Readiness", "Profile Readiness")
                    value: profileSummaryText()
                    subtitle: profileSummaryDetail()
                    accentColor: backend.profile.ready ? theme.success : theme.warn
                    badge: trx("Backend", "Backend")
                }
                StatTile {
                    Layout.fillWidth: true
                    title: trx("Face Confirmation", "Face Confirmation")
                    value: faceSummaryText()
                    subtitle: trx("Open Settings or the face setup page for enrollment and consent controls.", "Open Settings or the face setup page for enrollment and consent controls.")
                    accentColor: faceState.enabled === true ? theme.success : theme.warn
                    badge: faceSummaryBadge()
                }
                StatTile {
                    Layout.fillWidth: true
                    title: trx("Rollback", "Rollback")
                    value: rollbackSummaryText()
                    subtitle: trx("Detailed safety and rollback controls remain backend-owned and outside Overview until wired.", "Detailed safety and rollback controls remain backend-owned and outside Overview until wired.")
                    accentColor: theme.warn
                    badge: trx("Summary", "Summary")
                }
                StatTile {
                    Layout.fillWidth: true
                    title: trx("Last Decision", "Last Decision")
                    value: lastDecisionText()
                    subtitle: lastDecisionDetail()
                    accentColor: rootWindow ? rootWindow.toneColor(runtimeState.trustTone || rootWindow.decisionTone(runtimeState.decisionText)) : theme.info
                    badge: safeText(runtimeState.statusLabel || runtimeState.activeText, "")
                }
            }

            GlassCard {
                objectName: "overviewPrimaryActionsCard"
                Layout.fillWidth: true
                implicitHeight: primaryActionsColumn.implicitHeight + (root.denseLayout ? 32 : 44)

                ColumnLayout {
                    id: primaryActionsColumn
                    anchors.fill: parent
                    anchors.margins: root.denseLayout ? 18 : 22
                    spacing: 14

                    SectionHeader {
                        title: trx("Primary actions", "Primary actions")
                        subtitle: trx(
                            "الأزرار هنا تستدعي methods موجودة فقط أو تنتقل لصفحات مخصصة. أي إجراء غير مربوط بالـ backend يبقى disabled.",
                            "Buttons here call existing methods only or navigate to dedicated pages. Anything not wired by the backend stays disabled."
                        )
                        Layout.fillWidth: true
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 12

                        AppButton {
                            objectName: "overviewStartEnrollmentLoggerButton"
                            text: backend.tr("start_enrollment_logger")
                            role: "primary"
                            enabled: backend.canStartEnrollmentLogger
                            ToolTip.visible: hovered && !enabled && backend.startEnrollmentLoggerUnavailableReason.length > 0
                            ToolTip.text: backend.startEnrollmentLoggerUnavailableReason
                            ToolTip.delay: 100
                            onClicked: backend.startEnrollment()
                        }
                        AppButton {
                            objectName: "overviewStopEnrollmentLoggerButton"
                            text: backend.tr("stop_enrollment_logger")
                            role: "danger"
                            enabled: backend.canStopEnrollmentLogger
                            ToolTip.visible: hovered && !enabled && backend.stopEnrollmentLoggerUnavailableReason.length > 0
                            ToolTip.text: backend.stopEnrollmentLoggerUnavailableReason
                            ToolTip.delay: 100
                            onClicked: backend.stopEnrollmentLogger(false)
                        }
                        AppButton {
                            objectName: "overviewStartMonitorButton"
                            text: trx("Start Monitor", "Start Monitor")
                            role: "info"
                            enabled: backend.canStartProductionMonitor
                            onClicked: backend.startProtected()
                        }
                        AppButton {
                            objectName: "overviewStopMonitorButton"
                            text: trx("Stop Monitor", "Stop Monitor")
                            role: "danger"
                            enabled: backend.canStopProductionMonitor
                            onClicked: backend.stopProductionMonitor(false)
                        }
                        AppButton {
                            objectName: "overviewRunEvaluationButton"
                            text: trx("Run Evaluation", "Run Evaluation")
                            role: "neutral"
                            enabled: false
                        }
                        AppButton {
                            objectName: "overviewTrainCalibrateButton"
                            text: backend.trainingInProgress ? (trx("Train/Calibrate", "Train/Calibrate") + " • " + String(backend.trainingProgress.percent || 0) + "%") : trx("Train/Calibrate", "Train/Calibrate")
                            role: "success"
                            enabled: backend.canTrain
                            debugLabel: backend.trainingBlockedReason
                            onClicked: backend.trainProfile()
                        }
                        AppButton {
                            objectName: "overviewOpenLatestReportButton"
                            text: trx("Open Latest Report", "Open Latest Report")
                            role: "neutral"
                            enabled: false
                        }
                    }

                    Label {
                        objectName: "overviewEnrollmentLoggerUnavailableReason"
                        Layout.fillWidth: true
                        visible: !backend.canStartEnrollmentLogger && backend.startEnrollmentLoggerUnavailableReason.length > 0
                        text: backend.startEnrollmentLoggerUnavailableReason
                        color: theme.warn
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: trx(
                            "التقييم المتقدم يبقى report-only، والتدريب التجاري يعتمد على جلسات التهيئة العادية فقط.",
                            "Advanced evaluation remains report-only, and commercial training uses normal enrollment sessions only."
                        )
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                }
            }

            GlassCard {
                objectName: "overviewRelocationMapCard"
                Layout.fillWidth: true
                implicitHeight: relocationColumn.implicitHeight + (root.denseLayout ? 32 : 44)

                ColumnLayout {
                    id: relocationColumn
                    anchors.fill: parent
                    anchors.margins: root.denseLayout ? 18 : 22
                    spacing: 14

                    SectionHeader {
                        title: trx("Where details live now", "Where details live now")
                        subtitle: trx(
                            "Overview لا يحتوي بعد الآن على لوحات Live/Drift/Training/Shadow/Evaluation الطويلة.",
                            "Overview no longer contains the long Live/Drift/Training/Shadow/Evaluation panels."
                        )
                        Layout.fillWidth: true
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: root.compactLayout ? 1 : 2
                        columnSpacing: 12
                        rowSpacing: 12

                        AppButton { text: trx("Live Session", "Live Session"); role: "details"; Layout.fillWidth: true; onClicked: root.openSection(1) }
                        AppButton { text: trx("Profile & Training", "Profile & Training"); role: "details"; Layout.fillWidth: true; onClicked: root.openSection(2) }
                        AppButton { text: trx("Model Evaluation", "Model Evaluation"); role: "details"; Layout.fillWidth: true; onClicked: root.openSection(3) }
                        AppButton { text: trx("Sessions & Data", "Sessions & Data"); role: "details"; Layout.fillWidth: true; onClicked: root.openSection(4) }
                        AppButton { text: trx("Drift Lab", "Drift Lab"); role: "details"; Layout.fillWidth: true; onClicked: root.openSection(5) }
                    }
                }
            }
        }
    }
}
